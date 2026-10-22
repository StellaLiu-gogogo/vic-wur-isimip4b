#!/usr/bin/env python3
"""Convergence test of a spin-up block (D19 spin-up rule 3; task P3b, rules chosen by the user on 2026-10-22).

Reads the monthly spin-up output of the block (output.spinup of the campaign, one file per year; a chunked block
through its chunks), the domain and routing files of the parameter set, and writes to
qc/runs/<campaign-id>/<run-id>/: summary.json (status passed or failed), reports/convergence.json,
reports/convergence_annual.csv and figures/convergence_global.png, figures/convergence_basins.png; from a repository
that is not clean the same files go to scratch/spinup-check/uncommitted/qc/runs/... and the block has no test.

Quantities (annual values of every year of the block; month means weighted by their number of days)
  soil_moisture_layer2/3     area-weighted mean soil moisture of VIC layers 2 and 3 (mm) over the active cells
                             (global) and over each of the BASINS largest river basins (the outlets of the routing
                             network with the largest upstream area)
  december_swe               snow water equivalent of December (OUT_SWE + OUT_SNOW_CANOPY, km3) without the
                             perennial-snow cells: cells whose monthly snow water equivalent is never below
                             PERENNIAL_SWE_MM in the last TEST_YEARS years (snow that never melts and grows without a
                             glacier model; stands in for the glacier cells of D18, which an analysis identified)
  river_storage              OUT_STREAM_MOIST, annual mean volume (km3)
  reservoir_storage          OUT_GDAM_STORAGE + OUT_LDAM_STORAGE (hm3 per cell), annual mean volume (km3); only
                             with the dams plugin on
  irrigation_withdrawal      sector 4 of OUT_WI_{GW,SURF,DAM,TREM,NREN}_SECT (mm per month), annual volume (km3);
                             only for a 2021soc spin-up with the irrigation plugin on (D19)
Test (each quantity, the last TEST_YEARS annual values): the least-squares trend b (per year) and the standard
deviation s (ddof 1) of the values after removing that trend; the quantity passes when |b| <= TREND_LIMIT * s. The
block has converged (status passed) when every quantity passes; a block shorter than TEST_YEARS years, a missing
variable or a missing value on an active cell fails the test.

Usage: check_spinup.py --run-dir runs/<campaign-id>/<run-id>
"""
import argparse, csv, datetime, json, os, sys

import numpy as np
import netCDF4 as nc
import yaml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import grdc          # noqa: E402  (routing network, upstream area, outlets)
from common import gitstate, qc as qc_status   # noqa: E402

CHECKED_BY = 'workflow/05_simulation/monitor/check_spinup.py'
TEST_YEARS = 10
TREND_LIMIT = 0.1
PERENNIAL_SWE_MM = 1.0
BASINS = 20
IRRIGATION_SECTOR = 4
WI = ('OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_DAM_SECT', 'OUT_WI_TREM_SECT', 'OUT_WI_NREN_SECT')
FILL_LIMIT = 1e19
UNCOMMITTED = 'scratch/spinup-check/uncommitted'


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def trend_test(values, limit=TREND_LIMIT):
    """{slope_per_year, detrended_sd, ratio, limit, passed} of a series of annual values (see the module text)."""
    y = np.asarray(values, 'f8')
    if y.size < 3 or not np.isfinite(y).all():
        return {'slope_per_year': None, 'detrended_sd': None, 'ratio': None, 'limit': limit, 'passed': False,
                'note': 'fewer than 3 values or a missing value'}
    t = np.arange(y.size, dtype='f8')
    b, a = np.polyfit(t, y, 1)
    sd = float(np.std(y - (a + b * t), ddof=1))
    scale = max(float(np.abs(y).max()), 1e-30)
    if sd <= 1e-12 * scale:                     # values on a straight line: converged only if the line is flat
        ratio = 0.0 if abs(b) <= 1e-12 * scale else float('inf')
    else:
        ratio = abs(float(b)) / sd
    return {'slope_per_year': float(b), 'detrended_sd': sd, 'ratio': ratio, 'limit': limit,
            'passed': bool(ratio <= limit)}


def largest_basins(routing_path, mask, area_m2, lat, lon, n=BASINS):
    """(label per cell: basin rank 0..n-1 or -1, [basin records]) of the n outlets with the largest upstream area."""
    with nc.Dataset(routing_path) as r:
        r.set_auto_mask(False)
        nxt = grdc.network(r['downstream'][:], r['downstream_id'][:], mask)
    upa = grdc.upstream_area(nxt, area_m2 / 1e6, mask)
    out = grdc.outlets(nxt)
    act = mask.ravel()
    outlets = np.flatnonzero(act & (nxt == np.arange(nxt.size)))
    top = outlets[np.argsort(upa[outlets])[::-1][:n]]
    label = np.full(nxt.size, -1, 'i8')
    rank = {int(c): i for i, c in enumerate(top)}
    sel = act & np.isin(out, top)
    label[sel] = [rank[int(c)] for c in out[sel]]
    ncol = mask.shape[1]
    recs = [{'rank': i + 1, 'outlet_lat': float(lat[c // ncol]), 'outlet_lon': float(lon[c % ncol]),
             'upstream_area_km2': float(upa[c]), 'cells': int((label == i).sum())} for i, c in enumerate(top)]
    return label.reshape(mask.shape), recs


def field(ds, name, t, layer=None):
    v = ds[name]; v.set_auto_mask(False)
    a = np.asarray(v[t] if layer is None else v[t, layer], 'f8')
    a[np.abs(a) > FILL_LIMIT] = np.nan
    return a


def month_days(ds):
    tb = np.asarray(ds['time_bnds'][:], 'f8')
    return tb[:, 1] - tb[:, 0]


class Year:
    """Annual values of one year file and the monthly snow fields the snow test needs."""

    def __init__(self, path, mask, area, label, nbasin, quantities):
        self.values, self.problems = {}, []
        with nc.Dataset(path) as ds:
            need = {'OUT_SOIL_MOIST', 'OUT_SWE', 'OUT_STREAM_MOIST'} | \
                ({'OUT_GDAM_STORAGE', 'OUT_LDAM_STORAGE'} if 'reservoir_storage' in quantities else set()) | \
                (set(WI) if 'irrigation_withdrawal' in quantities else set())
            missing = sorted(need - set(ds.variables))
            if missing:
                self.problems.append(f'{os.path.basename(path)}: variables missing {missing}')
                return
            w = month_days(ds); w = w / w.sum(); nm = len(w)
            if nm != 12:
                self.problems.append(f'{os.path.basename(path)}: {nm} months')
                return
            cell_area = np.where(mask, area, 0.0)
            lab = label[mask]; a_act = area[mask]
            bas_area = np.bincount(lab[lab >= 0], weights=a_act[lab >= 0], minlength=nbasin)
            sm = {2: np.zeros(1 + nbasin), 3: np.zeros(1 + nbasin)}
            river = reservoir = irrigation = 0.0
            self.swe_min = np.full(mask.shape, np.inf, 'f4')    # lowest monthly snow of the year (perennial test)
            for t in range(nm):
                for layer in (2, 3):
                    f = field(ds, 'OUT_SOIL_MOIST', t, layer - 1)[mask]
                    if not np.isfinite(f).all():
                        self.problems.append(f'{os.path.basename(path)} month {t + 1}: soil moisture missing on '
                                             f'{int((~np.isfinite(f)).sum())} active cells')
                    sm[layer][0] += w[t] * np.nansum(f * a_act) / a_act.sum()
                    bsum = np.bincount(lab[lab >= 0], weights=(f * a_act)[lab >= 0], minlength=nbasin)
                    sm[layer][1:] += w[t] * bsum / bas_area
                s = field(ds, 'OUT_SWE', t)
                if 'OUT_SNOW_CANOPY' in ds.variables:
                    s = s + np.nan_to_num(field(ds, 'OUT_SNOW_CANOPY', t))
                s = np.where(mask, s, np.nan).astype('f4')
                self.swe_min = np.fmin(self.swe_min, s)
                if t == 11:
                    self.swe_dec = s
                river += w[t] * np.nansum(field(ds, 'OUT_STREAM_MOIST', t) * cell_area) * 1e-12
                if 'reservoir_storage' in quantities:
                    reservoir += w[t] * (np.nansum(field(ds, 'OUT_GDAM_STORAGE', t)[mask]) +
                                         np.nansum(field(ds, 'OUT_LDAM_STORAGE', t)[mask])) * 1e-3
                if 'irrigation_withdrawal' in quantities:
                    irrigation += sum(np.nansum(field(ds, n, t)[IRRIGATION_SECTOR] * cell_area) for n in WI) * 1e-12
        for layer in (2, 3):
            self.values[f'soil_moisture_layer{layer}'] = float(sm[layer][0])
            for i in range(nbasin):
                self.values[f'soil_moisture_layer{layer}_basin{i + 1:02d}'] = float(sm[layer][1 + i])
        self.values['river_storage'] = float(river)
        if 'reservoir_storage' in quantities:
            self.values['reservoir_storage'] = float(reservoir)
        if 'irrigation_withdrawal' in quantities:
            self.values['irrigation_withdrawal'] = float(irrigation)


def december_swe(years, mask, area, test_years):
    """{year: December snow water equivalent (km3) without the perennial-snow cells} and the perennial-snow mask."""
    lows = np.fmin.reduce([years[y].swe_min for y in test_years])
    perennial = mask & (lows >= PERENNIAL_SWE_MM)
    keep = mask & ~perennial
    out = {y: float(np.nansum(np.where(keep, years[y].swe_dec, 0.0) * area) * 1e-12) for y in years}
    return out, perennial


def year_files(rd, man):
    """{year: monthly output file}: in the run directory, or in the chunk of each year."""
    chunks = man.get('chunks') or [{'dir': '.', 'start_year': int(man['period']['start'][:4]),
                                    'end_year': int(man['period']['end'][:4])}]
    return {y: os.path.normpath(f'{rd}/{c["dir"]}/output/monthly.{y}-01.nc')
            for c in chunks for y in range(c['start_year'], c['end_year'] + 1)}


def figures(figs, series, tests, test_years, basins):
    years = sorted(next(iter(series.values())))
    glob_keys = [k for k in tests if '_basin' not in k]
    for name, keys, ncol in (('global', glob_keys, 3),
                             ('basins', [k for k in tests if '_basin' in k], 5)):
        if not keys:
            continue
        nrow = int(np.ceil(len(keys) / ncol))
        fig, axs = plt.subplots(nrow, ncol, figsize=(4 * ncol, 2.6 * nrow), squeeze=False)
        for ax, k in zip(axs.flat, keys):
            y = [series[k][yy] for yy in years]
            ax.plot(years, y, '.-', color='0.5', lw=0.8)
            tv = [series[k][yy] for yy in test_years]
            ax.plot(test_years, tv, '.', color='k')
            r = tests[k]
            if r['slope_per_year'] is not None:
                t = np.arange(len(test_years))
                a0 = np.mean(tv) - r['slope_per_year'] * t.mean()
                ax.plot(test_years, a0 + r['slope_per_year'] * t, color='tab:green' if r['passed'] else 'tab:red')
            title = k.replace('soil_moisture_', 'SM ').replace('_basin', ' basin ') + \
                (' [mm]' if k.startswith('soil_moisture') else ' [km3]')
            if '_basin' in k:
                b = basins[int(k[-2:]) - 1]
                title += f' ({b["outlet_lat"]:.1f}, {b["outlet_lon"]:.1f})'
            ax.set_title(f'{title}\n|b|/s = {r["ratio"]:.3g}' if r['ratio'] is not None else title, fontsize=8)
            ax.tick_params(labelsize=7)
        for ax in list(axs.flat)[len(keys):]:
            ax.set_visible(False)
        fig.suptitle(f'spin-up convergence: last {len(test_years)} years, pass when |trend per year| <= '
                     f'{TREND_LIMIT} x detrended SD (green passed, red failed)', fontsize=9)
        fig.tight_layout()
        fig.savefig(f'{figs}/convergence_{name}.png', dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    a = ap.parse_args(); W = workdir(); rd = os.path.abspath(a.run_dir)
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    first = (man.get('chunks') or [{'dir': '.'}])[0]['dir']
    with open(f'{rd}/{first}/config/resolved.yaml') as fh:
        res = yaml.safe_load(fh)
    params, plugins, seg = res['parameters'], res['campaign']['plugins'], res['segment']
    commit, dirty = gitstate.state(REPO)
    # results of code that is not committed never stand as the test of a block: they go to scratch (rule 14)
    qc = f'{W}/{UNCOMMITTED}/qc/{man["run_dir"]}' if dirty else f'{W}/qc/{man["run_dir"]}'
    figs = f'{qc}/figures'
    os.makedirs(figs, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)
    with nc.Dataset(f'{W}/{params["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool); area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
        lat = np.asarray(d['lat'][:]); lon = np.asarray(d['lon'][:])
    label, basins = largest_basins(f'{W}/{params["routing"]["path"]}', mask, area, lat, lon)
    quantities = {'soil_moisture', 'december_swe', 'river_storage'} | \
        ({'reservoir_storage'} if plugins['dams']['enabled'] else set()) | \
        ({'irrigation_withdrawal'} if seg['soc'].startswith('2021soc') and plugins['irrigation']['enabled'] else set())
    files = year_files(rd, man)
    years, problems = {}, []
    for y, p in sorted(files.items()):
        if not os.path.isfile(p):
            problems.append(f'{os.path.relpath(p, rd)} missing'); continue
        years[y] = Year(p, mask, area, label, len(basins), quantities)
        problems += years[y].problems
        print(f'{y}: ' + ', '.join(f'{k} {v:.4g}' for k, v in years[y].values.items() if '_basin' not in k), flush=True)
    test_years = sorted(years)[-TEST_YEARS:]
    if len(files) < TEST_YEARS:
        problems.append(f'the block has {len(files)} years, the test needs {TEST_YEARS}')
    series, tests, perennial = {}, {}, np.zeros_like(mask)
    if not problems:
        for k in years[test_years[0]].values:
            series[k] = {y: years[y].values[k] for y in years}
        series['december_swe'], perennial = december_swe(years, mask, area, test_years)
        tests = {k: trend_test([series[k][y] for y in test_years]) for k in series}
    failed = sorted(k for k, r in tests.items() if not r['passed'])
    status = 'passed' if tests and not failed and not problems else 'failed'
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    rule = {'test_years': TEST_YEARS, 'trend_limit_detrended_sd': TREND_LIMIT, 'perennial_swe_mm': PERENNIAL_SWE_MM,
            'basins': BASINS, 'decided': 'D19 spin-up rule 3; test rules chosen by the user on 2026-10-22 (task P3b)'}
    report = {'run': man['run_dir'], 'spinup_block': man.get('spinup_block'), 'checked_at': now,
              'checked_by': CHECKED_BY, 'code_commit': commit, 'code_dirty': dirty, 'rule': rule,
              'years': sorted(years), 'test_years': test_years, 'quantities': sorted(quantities),
              'perennial_snow_cells': int(perennial.sum()),
              'perennial_snow_area_km2': float((area * perennial).sum() / 1e6), 'basins': basins,
              'problems': problems, 'tests': tests, 'failed': failed, 'status': status,
              'annual_values': {k: {str(y): v for y, v in s.items()} for k, s in series.items()}}
    with open(f'{qc}/reports/convergence.json', 'w') as fh:
        json.dump(report, fh, indent=1, default=float)
    if series:
        keys = sorted(series)
        with open(f'{qc}/reports/convergence_annual.csv', 'w', newline='') as fh:
            wr = csv.writer(fh); wr.writerow(['year'] + keys)
            for y in sorted(years):
                wr.writerow([y] + [series[k][y] for k in keys])
        figures(figs, series, tests, test_years, basins)
    with open(f'{qc}/summary.json', 'w') as fh:
        json.dump({'object': man['run_dir'], 'status': status, 'checked_at': now, 'checked_by': CHECKED_BY,
                   'code_commit': commit, 'code_dirty': dirty, 'spinup_block': man.get('spinup_block'),
                   'test_years': test_years, 'failed': failed, 'problems': problems,
                   'note': 'D19 convergence test of a spin-up block; failed means: not converged, continue with the '
                           'next block (render_run.py)'}, fh, indent=1)
    for k, r in tests.items():
        if '_basin' not in k:
            print(f'{k}: slope {r["slope_per_year"]:.4g}/yr, detrended sd {r["detrended_sd"]:.4g}, ratio {r["ratio"]:.3g}'
                  f' -> {"passed" if r["passed"] else "failed"}')
    print(f'basin quantities failed: {sum(1 for k in failed if "_basin" in k)} of '
          f'{sum(1 for k in tests if "_basin" in k)}')
    if problems:
        print('problems:', *problems, sep='\n  ')
    print('status', status, '->', qc)
    qc_status.exit_with(status)


if __name__ == '__main__':
    main()
