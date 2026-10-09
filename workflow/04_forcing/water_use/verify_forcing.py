#!/usr/bin/env python3
"""Independent verification of a water-use forcing unit produced by downscale_water_use.py.

The checks use their own code path: the source files are read again with xarray and a separate year and latitude
lookup, the 5' demand is converted back to volumes and summed onto the 0.5 deg parents with index arrays (not the
producer's block reshape), and the fractions are recomputed from the sources and the WaterGAP tables.

Per year and sector:
  files      the three files exist; time `days since <year>-01-01 00:00:00`, value 0, calendar proleptic_gregorian,
             year in the name equal to the year of the time axis; float32; lat/lon identical to the domain file;
             finite values exactly on the active domain cells
  demand     >= 0; per parent with an active child, the re-aggregated volume equals the source volume
             (relative error <= 1e-5 or absolute <= 1 m3); no volume where the source is zero; the source volume
             of parents without an active child equals the producer's lost-demand ledger; source = written + lost
  fractions  within [0, 1]; constant over the active children of a parent; consumption fraction equal to
             min(wc/ww, 1) of the source where ww > 0; groundwater fraction equal to the WaterGAP table value
             where the parent has an Arc_ID (tolerance 1e-6)
Writes qc/forcing/water_use/<soc>/reports/verify_<year>.json, figures/verify_<year>.png, summary.json, and sets
qc.status in the unit's provenance.yaml: `passed` when every year of the unit passes, `failed` when any fails,
`not_checked` while the unit is only partly verified. Each report records the SHA-256 of the six data files of its
year and the verifier version; a report of an earlier run counts only while both still match (common/qc.py),
otherwise its year is not_checked. Exit status: 0 passed, 1 failed, 3 warning, 4 not_checked (common/qc.py).

Usage: verify_forcing.py --scenario histsoc [--years 1850-2021] [--unit-dir DIR] [--processes N]
  --unit-dir verifies outputs written to scratch; results then go to <unit-dir>/qc/ and provenance is not updated.
"""
import argparse, calendar, os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import xarray as xr
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

from common import provenance, qc, workdir

WORKDIR = workdir.root()
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
VARIABLES = ('demand', 'consumption_fraction', 'groundwater_fraction')
WA = f'{WORKDIR}/raw/external/isimip3-water-abstraction/dkrz-2026-10-02'
GW = f'{WORKDIR}/raw/external/watergap-groundwater-fractions/snapshot-2026-10-02'
SECTOR_SRC = {'municipal': ('dom', 'domestic/input/G_FRACTGW_DOM.txt'),
              'manufacturing': ('ind', 'industrial/input/G_FRACTGW_MAN.txt')}
YEARS = {'histsoc': (1850, 2021), '1850soc': (1850, 2021), '2021soc': (2022, 2100),
         'ssp1vlsoc-noadapt': (2022, 2100), 'ssp3hsoc-noadapt': (2022, 2100)}
TOL_REL, TOL_ABS_M3, TOL_FRAC = 1e-5, 1.0, 1e-6


def sources(scen, s, year):
    """(withdrawal file, var, year), (cf withdrawal ...), (cf consumption ...) as absolute paths."""
    a, b = f'{WA}/ISIMIP3a/InputData/socioeconomic/water_abstraction', f'{WA}/ISIMIP3b/InputData/socioeconomic/water_abstraction'
    if scen in ('histsoc', '2021soc'):
        y = year if scen == 'histsoc' else 2021
        span = '1850_1900' if y < 1901 else '1901_2021'
        ww = (f'{a}/histsoc/{s}ww_histsoc_annual_{span}.nc', f'{s}ww', y)
        return ww, ww, (f'{a}/histsoc/{s}wc_histsoc_annual_{span}.nc', f'{s}wc', y)
    if scen == '1850soc':
        span = '1850_2014' if year < 2015 else '2015_2100'
        ww = (f'{b}/1850soc/{s}ww_1850soc_annual_{span}.nc', f'{s}ww', year)
        return ww, ww, (f'{b}/1850soc/{s}wc_1850soc_annual_{span}.nc', f'{s}wc', year)
    ssp = {'ssp1vlsoc-noadapt': 'ssp126', 'ssp3hsoc-noadapt': 'ssp370'}[scen]
    return ((f'{b}/{ssp}soc-noadapt/{s}ww-modelavg_{ssp}_annual_2015_2100.nc', f'{s}ww', year),
            (f'{b}/2015soc/{s}ww_2015soc_annual_2015_2100.nc', f'{s}ww', 2015),
            (f'{b}/2015soc/{s}wc_2015soc_annual_2015_2100.nc', f'{s}wc', 2015))


def source_field(spec, plat):
    """Source field on the parent latitudes `plat` (ascending), m3/yr, fill -> 0."""
    path, var, year = spec
    ds = xr.open_dataset(path, decode_times=False)
    t = ds['time']; units = t.attrs['units']
    if units.startswith('years since'):
        yrs = 1901 + np.rint(t.values).astype(int)
    else:   # days since 1901-01-01, standard calendar, one step on 1 January of each year
        yrs = np.array([d.year for d in nc.num2date(t.values, units, t.attrs.get('calendar', 'standard'))])
    k = int(np.flatnonzero(yrs == year)[0])
    lat_idx = {round(float(v), 2): i for i, v in enumerate(ds['lat'].values)}
    rows = [lat_idx[round(float(v), 2)] for v in plat]
    x = ds[var].isel(time=k).values.astype('f8')[rows, :]
    ds.close()
    return np.where(np.isfinite(x) & (x < 1e19), x, 0.0)


def watergap_parent(table, plat, plon):
    look = {}
    with open(f'{GW}/input/Arc_ID_lon_lat_continentalarea.txt') as fh:
        next(fh)
        for line in fh:
            p = line.split(); look[p[0]] = (float(p[1]), float(p[2]))
    ilat = {round(float(v), 2): i for i, v in enumerate(plat)}; ilon = {round(float(v), 2): i for i, v in enumerate(plon)}
    out = np.full((len(plat), len(plon)), np.nan)
    with open(f'{GW}/{table}') as fh:
        next(fh)
        for line in fh:
            p = line.split()
            lo, la = look[p[0]]
            if round(la, 2) in ilat:
                out[ilat[round(la, 2)], ilon[round(lo, 2)]] = float(p[1])
    return out


def read_unit_file(path, name):
    d = nc.Dataset(path); d.set_auto_mask(False)
    t = d['time']
    info = {'time_units': t.units, 'calendar': getattr(t, 'calendar', ''), 'time_values': [float(v) for v in t[:]],
            'dtype': str(d[name].dtype), 'dims': list(d[name].dimensions)}
    lat, lon = np.asarray(d['lat'][:]), np.asarray(d['lon'][:])
    x = np.asarray(d[name][0], 'f8'); fill = float(getattr(d[name], '_FillValue', np.nan))
    d.close()
    return info, lat, lon, np.where(x == fill, np.nan, x)


def year_files(unit_dir, scen, year):
    """The data files of one year that exist (two sectors, three variables)."""
    return [p for p in (f'{unit_dir}/{sec}_{var}_{scen}_{year}.nc' for sec in SECTOR_SRC for var in VARIABLES)
            if os.path.exists(p)]


def verify_year(job):
    year, scen, unit_dir, f_dom, ledger, reports, figs, verifier = job
    binding = qc.binding(year_files(unit_dir, scen, year), verifier)   # before the checks: the files checked
    dom = nc.Dataset(f_dom); dom.set_auto_mask(False)
    dlat, dlon = np.asarray(dom['lat'][:]), np.asarray(dom['lon'][:])
    active = np.asarray(dom['mask'][:]) == 1; area = np.asarray(dom['area'][:], 'f8'); dom.close()
    # parent index of every child, by coordinates (independent of the producer's reshape)
    plat = np.unique(np.round((np.floor((dlat + 90) / 0.5) * 0.5 - 90 + 0.25), 2))
    plon = np.unique(np.round((np.floor((dlon + 180) / 0.5) * 0.5 - 180 + 0.25), 2))
    pi = np.searchsorted(plat, np.round(np.floor((dlat + 90) / 0.5) * 0.5 - 90 + 0.25, 2))
    pj = np.searchsorted(plon, np.round(np.floor((dlon + 180) / 0.5) * 0.5 - 180 + 0.25, 2))
    PI, PJ = np.meshgrid(pi, pj, indexing='ij')
    nact = np.zeros((len(plat), len(plon))); np.add.at(nact, (PI[active], PJ[active]), 1)
    days = 366 if calendar.isleap(year) else 365
    res = {'scenario': scen, 'year': year, 'checked_at': provenance.utcnow(), 'sectors': {}}
    ok_all = True; maps = {}
    for sec, (s, table) in SECTOR_SRC.items():
        r = {}; ok = True
        fields = {}
        for var in VARIABLES:
            fn = f'{unit_dir}/{sec}_{var}_{scen}_{year}.nc'
            if not os.path.exists(fn):
                r[var] = {'missing': True}; ok = False; continue
            info, lat, lon, x = read_unit_file(fn, var)
            fin = np.isfinite(x)
            chk = {'time_axis_ok': info['time_units'] == f'days since {year}-01-01 00:00:00' and info['time_values'] == [0.0],
                   'calendar_ok': info['calendar'] == 'proleptic_gregorian', 'float32': info['dtype'] == 'float32',
                   'dims_ok': info['dims'] == ['time', 'lat', 'lon'],
                   'grid_identical_to_domain': bool(np.array_equal(lat, dlat) and np.array_equal(lon, dlon)),
                   'finite_exactly_on_active_cells': bool(np.array_equal(fin, active)),
                   'min': float(np.nanmin(x)), 'max': float(np.nanmax(x))}
            chk['range_ok'] = chk['min'] >= 0 and (var == 'demand' or chk['max'] <= 1)
            ok &= all(chk[k] for k in ('time_axis_ok', 'calendar_ok', 'float32', 'dims_ok', 'grid_identical_to_domain',
                                       'finite_exactly_on_active_cells', 'range_ok'))
            r[var] = chk; fields[var] = np.where(active, x, 0.0)
        if len(fields) < 3:
            res['sectors'][sec] = r; ok_all = False; continue
        sww, scfw, scfc = sources(scen, s, year)
        src = source_field(sww, plat)
        vol = fields['demand'] * area * days / 1000.0
        agg = np.zeros_like(src); np.add.at(agg, (PI[active], PJ[active]), vol[active])
        has_child = nact > 0
        err = np.abs(agg - src)
        bad = has_child & (err > np.maximum(TOL_REL * src, TOL_ABS_M3))
        lost_src = float(src[~has_child].sum() / 1e9)
        led = ledger.get((year, sec))
        r['conservation'] = {'source_km3': float(src.sum() / 1e9), 'written_km3': float(agg.sum() / 1e9),
                             'lost_km3_recomputed': lost_src, 'lost_km3_ledger': led,
                             'parents_failing': int(bad.sum()),
                             'max_relative_error': float((err[has_child & (src > 0)] / src[has_child & (src > 0)]).max())
                             if (has_child & (src > 0)).any() else 0.0,
                             'volume_where_source_zero_m3': float(agg[src == 0].sum())}
        c = r['conservation']
        c['lost_matches_ledger'] = led is not None and abs(led - lost_src) <= 1e-6 * max(1.0, lost_src) + 1e-9
        c['balance_ok'] = abs(c['source_km3'] - c['written_km3'] - lost_src) <= 1e-6 * c['source_km3'] + 1e-9
        ok &= c['parents_failing'] == 0 and c['volume_where_source_zero_m3'] <= TOL_ABS_M3 and c['lost_matches_ledger'] \
            and c['balance_ok']
        # fractions: constant per parent, consumption from the source, groundwater from the tables
        for var in ('consumption_fraction', 'groundwater_fraction'):
            x = fields[var]
            hi = np.full(src.shape, -np.inf); lo = np.full(src.shape, np.inf)
            np.maximum.at(hi, (PI[active], PJ[active]), x[active]); np.minimum.at(lo, (PI[active], PJ[active]), x[active])
            spread = float(np.max((hi - lo)[has_child])) if has_child.any() else 0.0
            pv = np.where(has_child, hi, np.nan)
            if var == 'consumption_fraction':
                ww, wc = source_field(scfw, plat), source_field(scfc, plat)
                pos = has_child & (ww > 0)
                ref = np.minimum(wc[pos] / ww[pos], 1.0)
                dev = float(np.abs(pv[pos] - ref).max()) if pos.any() else 0.0
            else:
                tab = watergap_parent(table, plat, plon)
                pos = has_child & np.isfinite(tab)
                dev = float(np.abs(pv[pos] - tab[pos]).max()) if pos.any() else 0.0
            r[var].update(max_spread_within_parent=spread, max_deviation_from_source=dev, parents_compared=int(pos.sum()))
            ok &= spread <= TOL_FRAC and dev <= TOL_FRAC
        r['status'] = 'passed' if ok else 'failed'
        ok_all &= ok
        res['sectors'][sec] = r
        maps[sec] = np.where(active, fields['demand'], np.nan)
    res['status'] = 'passed' if ok_all else 'failed'
    res['binding'] = binding
    qc.write_json(f'{reports}/verify_{year}.json', res)
    if maps:
        fig, axs = plt.subplots(len(maps), 1, figsize=(14, 5.2 * len(maps)))
        axs = np.atleast_1d(axs)
        for ax, (sec, m) in zip(axs, maps.items()):
            im = ax.imshow(np.where(m > 0, m, np.nan), origin='lower', extent=[-180, 180, dlat[0], dlat[-1]],
                           cmap='viridis', norm=mcolors.LogNorm(1e-4, 10), interpolation='nearest')
            ax.set_facecolor('#f0f0f0')
            ax.set_title(f'{scen} {year}: {sec} demand (mm/day), '
                         f'{res["sectors"][sec]["conservation"]["written_km3"]:.1f} km3/yr', loc='left', fontsize=10)
            fig.colorbar(im, ax=ax, fraction=0.025)
        fig.tight_layout(); fig.savefig(f'{figs}/verify_{year}.png', dpi=110); plt.close(fig)
    print(f'{scen} {year}: {res["status"]}', flush=True)
    return year, res['status']


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(YEARS))
    ap.add_argument('--years', default=None, help='single year or START-END (default: every year of the unit)')
    ap.add_argument('--unit-dir', default=None, help='verify outputs in this directory instead of the forcing unit')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=1, help='years verified in parallel (about 3 GB each)')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    ap.add_argument('--qc-to-scratch', action='store_true',
                    help='set by the submit script when the repository was not clean: results go to scratch')
    a = ap.parse_args()
    unit = f'water_use/{a.scenario}'; unit_dir = a.unit_dir or f'{WORKDIR}/forcing/{unit}'
    verifier = qc.verifier_state(REPO, 'workflow/04_forcing/water_use')
    commit, dirty = verifier['verifier_commit'], verifier['verifier_dirty']
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    # a verifier that is not committed never changes the status of a unit (rule 14): its results go to scratch
    uncommitted = not a.unit_dir and (dirty or a.qc_to_scratch)
    qc_dir = f'{unit_dir}/qc' if a.unit_dir else f'{WORKDIR}/qc/forcing/{unit}'
    if uncommitted:
        qc_dir = f'{WORKDIR}/scratch/water-use-forcing/verify-uncommitted/qc/forcing/{unit}'
    reports, figs = f'{qc_dir}/reports', f'{qc_dir}/figures'
    os.makedirs(reports, exist_ok=True); os.makedirs(figs, exist_ok=True)
    f_dom = f'{WORKDIR}/parameters/{a.parameter_status}/{a.parameter_set}/domain/vic_global_5min_domain_nogl.nc'
    unit_years = sorted({int(f[:-3].rsplit('_', 1)[1]) for f in os.listdir(unit_dir) if f.endswith('.nc')})
    if not unit_years:
        raise SystemExit(f'no files in {unit_dir}')
    years = unit_years
    if a.years:
        y = a.years.split('-'); want = set(range(int(y[0]), int(y[-1]) + 1)); years = [x for x in unit_years if x in want]
    ledger = {}
    lp = f'{reports}/lost_demand_ledger.csv'
    if os.path.exists(lp):
        with open(lp) as fh:
            head = next(fh).strip().split(',')
            for line in fh:
                row = dict(zip(head, line.strip().split(',')))
                ledger[(int(row['year']), row['sector'])] = float(row['lost_km3'])
    jobs = [(yy, a.scenario, unit_dir, f_dom, ledger, reports, figs, verifier) for yy in years]
    nproc = max(1, min(a.processes, len(jobs)))
    if nproc == 1:
        done = [verify_year(j) for j in jobs]
    else:
        with ProcessPoolExecutor(nproc, mp_context=get_context('fork')) as ex:
            done = list(ex.map(verify_year, jobs))
    y0, y1 = YEARS[a.scenario]
    checked = {yy for yy, _ in done}; per_year = {}
    for yy in range(y0, y1 + 1):
        per_year[yy] = (qc.report_status(f'{reports}/verify_{yy}.json', year_files(unit_dir, a.scenario, yy), verifier,
                                         yy in checked) if yy in unit_years else 'missing')
    status = qc.combine(per_year.values())          # a missing year counts as not_checked
    summary = {'object': f'forcing/{unit}', 'status': status, 'checked_by': 'workflow/04_forcing/water_use/verify_forcing.py',
               'updated_at': provenance.utcnow(),
               'years_expected': f'{y0}-{y1}', 'years_present': len(unit_years),
               'passed': sum(v == 'passed' for v in per_year.values()), 'failed': sum(v == 'failed' for v in per_year.values()),
               'not_checked': sum(v == 'not_checked' for v in per_year.values()),
               'missing': sum(v == 'missing' for v in per_year.values()),
               'per_year': {str(k): v for k, v in per_year.items()}}
    if uncommitted:
        summary['note'] = 'verifier code not committed (repository not clean): results kept in scratch, the status of the object is unchanged'
    qc.write_summary(qc_dir, summary)
    prov_path = f'{unit_dir}/provenance.yaml'
    if not a.unit_dir and not uncommitted and os.path.exists(prov_path):
        provenance.set_qc(prov_path, status, f'qc/forcing/{unit}')
    print(f'unit {unit}: {status} ({summary["passed"]} passed, {summary["failed"]} failed, '
          f'{summary["not_checked"]} not checked, {summary["missing"]} missing of {y0}-{y1})')
    qc.exit_with(status)


if __name__ == '__main__':
    main()
