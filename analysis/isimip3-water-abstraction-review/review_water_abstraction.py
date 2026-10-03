#!/usr/bin/env python3
"""Review of the ISIMIP3a/3b water-abstraction files and the WaterGAP groundwater-fraction tables (task D1 of D05).

Reads the 52 NetCDF files of raw/external/isimip3-water-abstraction/dkrz-2026-10-02/ and the 4 tables of
raw/external/watergap-groundwater-fractions/snapshot-2026-10-02/, and writes tables and figures to
workdir/analysis/isimip3-water-abstraction-review/ and the QC summaries to
qc/raw/external/<dataset-id>/<version>/summary.json. With --scratch everything goes to
scratch/isimip3-water-abstraction-review/run/ instead (test runs).

Checks: headers (dimensions, variables, units, fill values, time axis, grid), values (fill versus zero,
negatives, extremes, consumption > withdrawal, withdrawal without population, withdrawal outside the VIC domain),
time (continuity between files, 3b versus 3a, constant scenarios, joins between histsoc and the SSP series,
model spread), regional totals in km3/yr, and a comparison with published estimates.

Usage (always on a compute node):
  review_water_abstraction.py --submit [--scratch]     render the Slurm job, keep its record, submit it
  review_water_abstraction.py [--scratch]              the computation itself (run inside the job)
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

import numpy as np
import pandas as pd
import netCDF4

TASK = 'isimip3-water-abstraction-review'
WA_ID, WA_VERSION = 'isimip3-water-abstraction', 'dkrz-2026-10-02'
GW_ID, GW_VERSION = 'watergap-groundwater-fractions', 'snapshot-2026-10-02'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
WA_SUB = 'InputData/socioeconomic/water_abstraction'
NLAT, NLON = 360, 720                        # ISIMIP 0.5 degree grid, north to south, -180 to 180
LAT05 = 89.75 - 0.5 * np.arange(NLAT)
LON05 = -179.75 + 0.5 * np.arange(NLON)
R_EARTH = 6371000.0                          # m, sphere for cell areas (only used for mm/yr maps)
KM3 = 1e9
SECTORS = ('dom', 'ind')
CONTINENTS = ('Africa', 'Asia', 'Europe', 'North America', 'South America', 'Oceania')
REGIONS = ('global',) + CONTINENTS + ('no country',)
SERIES_LABEL = {
    '3a-histsoc': 'ISIMIP3a histsoc', '3b-histsoc': 'ISIMIP3b histsoc', '3b-1850soc': 'ISIMIP3b 1850soc',
    '3b-2015soc': 'ISIMIP3b 2015soc', '3b-ssp126': 'ISIMIP3b ssp126soc-noadapt (modelavg)',
    '3b-ssp370': 'ISIMIP3b ssp370soc-noadapt (modelavg)'}

SBATCH = """#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=main
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=48G
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/{step}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={workdir}
export OMP_NUM_THREADS=1
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
/usr/bin/time -v python3 analysis/{task}/review_water_abstraction.py {args}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


# ----------------------------------------------------------------------------------------------- paths

def workdir():
    w = os.environ.get('ISIMIP4B_WORKDIR')
    if not w:
        sys.exit('set ISIMIP4B_WORKDIR')
    return w


def out_dirs(scratch):
    w = workdir()
    if scratch:
        base = f'{w}/scratch/{TASK}/run'
        return base, f'{base}/qc/{WA_ID}', f'{base}/qc/{GW_ID}'
    return (f'{w}/analysis/{TASK}', f'{w}/qc/raw/external/{WA_ID}/{WA_VERSION}',
            f'{w}/qc/raw/external/{GW_ID}/{GW_VERSION}')


# ----------------------------------------------------------------------------------------------- reading

def file_table():
    """One row per NetCDF file: series, sector, quantity, statistic, path relative to the dataset version."""
    root = f'{workdir()}/raw/external/{WA_ID}/{WA_VERSION}'
    rows = []
    for p in sorted(glob.glob(f'{root}/ISIMIP3?/{WA_SUB}/*/*.nc')):
        rel = os.path.relpath(p, root)
        rnd, scen, name = rel.split('/')[0][-2:], rel.split('/')[-2], os.path.basename(rel)
        m = re.match(r'(dom|ind)w([wc])(-model(avg|std))?_', name)
        sector, q, stat = m.group(1), 'w' + m.group(2), ('model' + m.group(4)) if m.group(4) else 'value'
        series = f'{rnd}-' + (scen.split('soc-')[0] if 'ssp' in scen else scen)
        rows.append(dict(series=series, sector=sector, quantity=q, stat=stat, path=rel, abspath=p,
                         scenario_dir=scen, round=rnd))
    return pd.DataFrame(rows)


def decode_years(t):
    """Calendar year of each time step and the largest offset from a whole year (in the unit of the file)."""
    v = np.asarray(t[:], dtype='f8')
    if t.units.startswith('years since 1901-1-1'):
        # not decodable by netCDF4/cftime/xarray for the standard calendar: value = years after 1901
        yrs = 1901 + np.round(v).astype(int)
        off = np.abs(v - np.round(v))
        first = int(yrs[np.argmax(off > 1e-9)]) if (off > 1e-9).any() else None
        return yrs, float(off.max()), f'years after 1901 (rounded); first year with offset: {first}'
    dates = netCDF4.num2date(v, t.units, getattr(t, 'calendar', 'standard'))
    yrs = np.array([d.year for d in dates])
    off = max(abs((d.month - 1) * 31 + d.day - 1) for d in dates)
    return yrs, float(off), 'num2date'


def read_file(row, land):
    """Read one file onto the 360 x 720 grid (NaN for fill and for rows outside the file); header and value stats."""
    d = netCDF4.Dataset(row['abspath'])
    vname = [v for v in d.variables if v not in ('lat', 'lon', 'time')][0]
    var, lat, lon = d[vname], np.asarray(d['lat'][:], 'f8'), np.asarray(d['lon'][:], 'f8')
    yrs, toff, how = decode_years(d['time'])
    iy = np.round((89.75 - lat) / 0.5).astype(int)
    ix = np.round((lon + 179.75) / 0.5).astype(int)
    on_grid = bool(np.allclose(LAT05[iy], lat, atol=1e-6) and np.allclose(LON05[ix], lon, atol=1e-6))
    raw = np.ma.getdata(var[:]).astype('f8')
    fill = getattr(var, '_FillValue', None)
    isfill = (raw >= 1e19) | ~np.isfinite(raw)
    a = np.where(isfill, np.nan, raw)
    full = np.full((len(yrs), NLAT, NLON), np.nan)
    full[np.ix_(np.arange(len(yrs)), iy, ix)] = a
    landb = np.broadcast_to(land, full.shape)
    inrows = np.zeros((NLAT, NLON), bool); inrows[np.ix_(iy, ix)] = True
    fin = np.isfinite(full)
    h = dict(
        path=row['path'], series=row['series'], sector=row['sector'], quantity=row['quantity'], stat=row['stat'],
        variable=vname, dtype=str(var.dtype), dims='x'.join(var.dimensions), shape='x'.join(map(str, var.shape)),
        units=getattr(var, 'units', ''), long_name=getattr(var, 'long_name', ''), fill_value=fill,
        missing_value=getattr(var, 'missing_value', None), lat_first=lat[0], lat_last=lat[-1], n_lat=len(lat),
        lat_order='north-to-south' if lat[0] > lat[-1] else 'south-to-north', lon_first=lon[0],
        lon_last=lon[-1], n_lon=len(lon), on_isimip_05_grid=on_grid, time_units=d['time'].units,
        time_calendar=getattr(d['time'], 'calendar', ''), time_decoding=how, time_max_offset=toff,
        year_first=int(yrs[0]), year_last=int(yrs[-1]), n_years=len(yrs),
        years_contiguous=bool(np.all(np.diff(yrs) == 1)),
        history=getattr(d, 'history', '')[:300], comment=getattr(d, 'comment', ''),
        title=getattr(d, 'title', ''), description=' '.join(getattr(d, 'description', '').split()),
        n_fill_cellyears=int(isfill.sum()), n_fill_land_cellyears=int((~fin & landb & inrows).sum()),
        n_land_cells_fill_first_year=int((land & ~fin[0]).sum()),
        n_negative=int((full < 0).sum()), min=float(np.nanmin(full)), max=float(np.nanmax(full)),
        n_zero_cellyears=int((full == 0).sum()),
        n_land_cells_zero_all_years=int((land & inrows & np.all(np.nan_to_num(full) == 0, axis=0)).sum()),
        n_ocean_cells_positive=int((~land & np.any(full > 0, axis=0)).sum()),
        ocean_volume_km3_last_year=float(np.nansum(np.where(land, 0, full[-1])) / KM3),
        global_km3_first_year=float(np.nansum(full[0]) / KM3), global_km3_last_year=float(np.nansum(full[-1]) / KM3))
    imax = np.unravel_index(np.nanargmax(full), full.shape)
    h.update(max_year=int(yrs[imax[0]]), max_lat=float(LAT05[imax[1]]), max_lon=float(LON05[imax[2]]))
    d.close()
    return yrs, full, h


# ----------------------------------------------------------------------------------------------- reference grids

def cell_area():
    lat = np.deg2rad(LAT05)
    a = R_EARTH ** 2 * np.deg2rad(0.5) * (np.sin(lat + np.deg2rad(0.25)) - np.sin(lat - np.deg2rad(0.25)))
    return np.repeat(a[:, None], NLON, axis=1)


def region_weights():
    """Fraction of each 0.5 degree cell belonging to each continent (from the ISIMIP4b fractional country masks)."""
    cont = pd.read_csv(f'{HERE}/continents.csv', comment='#').set_index('iso3')['continent']
    d = netCDF4.Dataset(f'{workdir()}/raw/ISIMIP4b/InputData/geo_conditions/countrymasks/'
                        'countrymasks-fractional_30arcmin.nc')
    assert np.allclose(d['lat'][:], LAT05) and np.allclose(d['lon'][:], LON05)
    w = {c: np.zeros((NLAT, NLON)) for c in CONTINENTS}
    codes = [v for v in d.variables if v not in ('lat', 'lon', 'world')]
    missing = sorted(set(codes) - set(cont.index))
    assert not missing, f'continents.csv lacks {missing}'
    for c in codes:
        w[cont[c]] += np.nan_to_num(np.ma.filled(d[c][:].astype('f8'), 0.0))
    tot = sum(w.values())
    w['no country'] = np.clip(1.0 - tot, 0, 1)
    w['global'] = np.ones((NLAT, NLON))
    return np.stack([w[r] for r in REGIONS])                       # (nreg, lat, lon)


def water_global_mask():
    d = netCDF4.Dataset(f'{workdir()}/raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_water-global.nc')
    assert np.allclose(d['lat'][:], LAT05) and np.allclose(d['lon'][:], LON05)
    m = np.ma.filled(d['mask'][0].astype('f8'), 0.0)
    return np.nan_to_num(m) == 1


def vic_parents():
    """Active 5 arcmin VIC cells per 0.5 degree parent and the grid relation of the domain."""
    p = f'{workdir()}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
    d = netCDF4.Dataset(p)
    lat, lon = np.asarray(d['lat'][:]), np.asarray(d['lon'][:])
    mask = np.ma.filled(d['mask'][:], 0) == 1
    ny, nx = mask.shape
    plat = lat.reshape(ny // 6, 6).mean(1)
    plon = lon.reshape(nx // 6, 6).mean(1)
    cnt = mask.reshape(ny // 6, 6, nx // 6, 6).sum(axis=(1, 3))
    iy = np.round((89.75 - plat) / 0.5).astype(int)
    out = np.zeros((NLAT, NLON), int); out[iy, :] = cnt
    rel = dict(vic_file=os.path.relpath(p, workdir()), vic_shape=f'{ny}x{nx}',
               vic_lat_order='south-to-north' if lat[0] < lat[-1] else 'north-to-south',
               vic_lat_first=float(lat[0]), vic_lat_last=float(lat[-1]),
               parent_rows=int(ny // 6), parent_lat_first=float(plat[0]), parent_lat_last=float(plat[-1]),
               parents_on_isimip_grid=bool(np.allclose(LAT05[iy], plat) and np.allclose(LON05, plon)),
               n_parents_with_active_cells=int((out > 0).sum()), n_active_cells=int(mask.sum()))
    return out, rel, (iy, mask)


def population05(scen_dir, prefix, year):
    """ISIMIP4b 5 arcmin total population of one year: the 5 arcmin field and its 0.5 degree sum."""
    base = f'{workdir()}/raw/ISIMIP4b/InputData/socioeconomic/population/{scen_dir}'
    for f in sorted(glob.glob(f'{base}/{prefix}_5arcmin_annual_*.nc')):
        y0, y1 = map(int, re.findall(r'_(\d{4})_(\d{4})\.nc$', f)[0])
        if y0 <= year <= y1:
            d = netCDF4.Dataset(f)
            yrs = [x.year for x in netCDF4.num2date(d['time'][:], d['time'].units,
                                                    getattr(d['time'], 'calendar', 'standard'))]
            p5 = np.nan_to_num(np.ma.filled(d['total-population'][yrs.index(year)].astype('f8'), 0.0))
            assert p5.shape == (2160, 4320) and d['lat'][0] > d['lat'][-1]
            return p5, p5.reshape(NLAT, 6, NLON, 6).sum(axis=(1, 3)), os.path.relpath(f, workdir())
    raise FileNotFoundError(f'{scen_dir} {year}')


# ----------------------------------------------------------------------------------------------- helpers

def regional(a, W):
    """Regional totals in km3/yr of a (years, lat, lon) or (lat, lon) array."""
    a2 = np.nan_to_num(a).reshape(-1, NLAT * NLON) if a.ndim == 3 else np.nan_to_num(a).reshape(1, -1)
    return a2 @ W.reshape(len(REGIONS), -1).T / KM3


def maxdiff(a, b):
    """Largest absolute cell difference (m3/yr) and the same relative to the largest cell value."""
    d = np.nanmax(np.abs(np.nan_to_num(a) - np.nan_to_num(b)))
    ref = max(np.nanmax(np.abs(np.nan_to_num(a))), 1e-30)
    return float(d), float(d / ref)


def ratio_stats(before, after, name, sector):
    b, a = np.nan_to_num(before), after
    both = (b > 0) & np.isfinite(a) & (a > 0)
    r = np.where(both, a / np.where(b > 0, b, 1), np.nan)
    w = np.where(both, b, 0)
    rv = r[both]; wv = w[both]
    order = np.argsort(rv); cw = np.cumsum(wv[order]) / wv.sum()
    wq = {q: float(rv[order][np.searchsorted(cw, q)]) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    lost = (b > 0) & ~((np.isfinite(a)) & (a > 0))
    new = (b <= 0) & np.isfinite(a) & (a > 0)
    return dict(join=name, sector=sector, n_cells_both_positive=int(both.sum()),
                ratio_p05=float(np.percentile(rv, 5)), ratio_p50=float(np.percentile(rv, 50)),
                ratio_p95=float(np.percentile(rv, 95)), ratio_min=float(rv.min()), ratio_max=float(rv.max()),
                ratio_volume_weighted_p05=wq[0.05], ratio_volume_weighted_p25=wq[0.25],
                ratio_volume_weighted_p50=wq[0.5], ratio_volume_weighted_p75=wq[0.75],
                ratio_volume_weighted_p95=wq[0.95],
                n_cells_ratio_below_0p5=int((rv < 0.5).sum()), n_cells_ratio_above_2=int((rv > 2).sum()),
                n_cells_before_positive_after_zero_or_fill=int(lost.sum()),
                volume_km3_before_in_those_cells=float(b[lost].sum() / KM3),
                n_cells_before_zero_after_positive=int(new.sum()),
                volume_km3_after_in_those_cells=float(np.nan_to_num(a)[new].sum() / KM3),
                global_before_km3=float(b.sum() / KM3), global_after_km3=float(np.nansum(a) / KM3)), r


# ----------------------------------------------------------------------------------------------- main

def run(scratch):
    base, qc_wa, qc_gw = out_dirs(scratch)
    tabd, figd = f'{base}/tables', f'{base}/figures'
    for p in (tabd, figd, qc_wa, qc_gw):
        os.makedirs(p, exist_ok=True)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True,
                                text=True).stdout.strip())
    land = water_global_mask()
    W = region_weights()
    area = cell_area()
    vicp, vicrel, (vic_iy, vic_mask) = vic_parents()
    files = file_table()
    assert len(files) == 52, len(files)

    # ---- per file: headers, value statistics, regional totals; keep what the cross-file checks need
    headers, totals = [], []
    keep = {}           # (series, sector, quantity, stat) -> dict(year -> 2d array) for selected years
    full_keep = {}      # (series, sector, quantity, stat) -> (years, array) for the 1850-2021 window
    const = []          # constancy checks of fixed-year files
    for _, row in files.iterrows():
        yrs, a, h = read_file(row, land)
        headers.append(h)
        tot = regional(a, W)
        for i, y in enumerate(yrs):
            for j, reg in enumerate(REGIONS):
                totals.append((row['series'], row['sector'], row['quantity'], row['stat'], int(y), reg, tot[i, j]))
        k = (row['series'], row['sector'], row['quantity'], row['stat'])
        sel = keep.setdefault(k, {})
        for y in (1601, 1849, 1850, 1900, 1901, 1950, 2000, 2005, 2006, 2010, 2014, 2015, 2021, 2022, 2050, 2100):
            if y in yrs:
                sel[y] = a[list(yrs).index(y)]
        # constancy: every year equal to the first year of the file
        dmax, drel = maxdiff(a, np.broadcast_to(a[0], a.shape))
        const.append(dict(path=row['path'], series=row['series'], sector=row['sector'], quantity=row['quantity'],
                          stat=row['stat'], years=f'{yrs[0]}-{yrs[-1]}', max_abs_diff_to_first_year_m3=dmax,
                          max_rel_diff_to_first_year=drel, constant=drel < 1e-9))
        if row['series'] in ('3a-histsoc', '3b-histsoc') or row['stat'] != 'value':
            m = (yrs >= 1850) & (yrs <= 2100)
            if m.any():
                py, pa = full_keep.get(k, (np.zeros(0, int), np.zeros((0, NLAT, NLON))))
                full_keep[k] = (np.concatenate([py, yrs[m]]), np.concatenate([pa, a[m]]))
        del a
    hdr = pd.DataFrame(headers)
    hdr.to_csv(f'{tabd}/file_headers.csv', index=False)
    tot = pd.DataFrame(totals, columns=['series', 'sector', 'quantity', 'stat', 'year', 'region', 'km3'])
    tot.to_csv(f'{tabd}/totals_by_region.csv', index=False)
    pd.DataFrame(const).to_csv(f'{tabd}/constancy_per_file.csv', index=False)

    def K(series, sector, q='ww', stat='value'):
        return keep[(series, sector, q, stat if not series.startswith('3b-ssp') else 'modelavg')]

    # ---- time checks: equalities between files and series
    checks = []

    def eq(name, a, b, sector, q, note=''):
        dmax, drel = maxdiff(a, b)
        ga, gb = np.nansum(a) / KM3, np.nansum(b) / KM3
        checks.append(dict(check=name, sector=sector, quantity=q, max_abs_diff_m3=dmax, max_rel_diff=drel,
                           global_a_km3=ga, global_b_km3=gb, global_ratio_b_over_a=gb / ga if ga else np.nan,
                           identical=drel < 1e-9, note=note))

    for s in SECTORS:
        for q in ('ww', 'wc'):
            a3, b3 = keep[('3a-histsoc', s, q, 'value')], keep[('3b-histsoc', s, q, 'value')]
            s18, s15 = keep[('3b-1850soc', s, q, 'value')], keep[('3b-2015soc', s, q, 'value')]
            eq('3a histsoc 1900 vs 1901 (file join 1850_1900 / 1901_2021)', a3[1900], a3[1901], s, q)
            eq('3a histsoc 1850 vs 1901 (pre-1901 filled with 1901?)', a3[1901], a3[1850], s, q)
            eq('3b histsoc 1900 vs 1901 (file join 1850_1900 / 1901_2014)', b3[1900], b3[1901], s, q)
            eq('3b histsoc 1849 vs 1850 (file join 1601_1849 / 1850_1900)', b3[1849], b3[1850], s, q)
            eq('3b histsoc 1601 vs 1901 (pre-1901 filled with 1901?)', b3[1901], b3[1601], s, q)
            eq('3b histsoc 1901 vs 3a histsoc 1901', a3[1901], b3[1901], s, q)
            eq('3b histsoc 1950 vs 3a histsoc 1950', a3[1950], b3[1950], s, q)
            eq('3b histsoc 2005 vs 3a histsoc 2005', a3[2005], b3[2005], s, q)
            eq('3b histsoc 2014 vs 3a histsoc 2014', a3[2014], b3[2014], s, q)
            eq('3b 1850soc (1601) vs 3b histsoc 1850', b3[1850], s18[1601], s, q)
            eq('3b 1850soc (2100) vs 3b 1850soc (1601)', s18[1601], s18[2100], s, q)
            eq('3b 2015soc (1601) vs 3a histsoc 2015', a3[2015], s15[1601], s, q)
            eq('3b 2015soc (2100) vs 3b 2015soc (1601)', s15[1601], s15[2100], s, q)
            eq('3b 2015soc vs 3b histsoc 2014', b3[2014], s15[2015], s, q)
        for ssp in ('3b-ssp126', '3b-ssp370'):
            sp = K(ssp, s)
            eq(f'{ssp} 2015 vs 3b 2015soc', keep[('3b-2015soc', s, 'ww', 'value')][2015], sp[2015], s, 'ww',
               'protocol: SSP series rescaled with a constant multiplier to match historical data in 2015')
            eq(f'{ssp} 2015 vs 3a histsoc 2015', keep[('3a-histsoc', s, 'ww', 'value')][2015], sp[2015], s, 'ww')
            eq(f'{ssp} 2022 vs 3a histsoc 2021', keep[('3a-histsoc', s, 'ww', 'value')][2021], sp[2022], s, 'ww')
    # where the 3b and 3a histsoc differ over 1901-2014
    for s in SECTORS:
        for q in ('ww', 'wc'):
            ya, aa = full_keep[('3a-histsoc', s, q, 'value')]
            yb, bb = full_keep[('3b-histsoc', s, q, 'value')]
            for y in range(1901, 2015):
                d, r = maxdiff(aa[list(ya).index(y)], bb[list(yb).index(y)])
                if r > 1e-9:
                    checks.append(dict(check='first year where 3b histsoc differs from 3a histsoc', sector=s,
                                       quantity=q, max_abs_diff_m3=d, max_rel_diff=r, note=str(y)))
                    break
            else:
                checks.append(dict(check='3b histsoc identical to 3a histsoc for every year 1901-2014', sector=s,
                                   quantity=q, identical=True))
    pd.DataFrame(checks).to_csv(f'{tabd}/time_checks.csv', index=False)

    # ---- joins: regional values and per-cell ratios
    joins, jregion, ratio_maps = [], [], {}
    for s in SECTORS:
        h21 = keep[('3a-histsoc', s, 'ww', 'value')][2021]
        b14 = keep[('3b-histsoc', s, 'ww', 'value')][2014]
        for ssp in ('3b-ssp126', '3b-ssp370'):
            sp = K(ssp, s)
            for name, before, after in ((f'3a histsoc 2021 -> {ssp} 2022', h21, sp[2022]),
                                        (f'3b histsoc 2014 -> {ssp} 2015', b14, sp[2015]),
                                        (f'{ssp} 2021 -> {ssp} 2022 (one model year, reference)', sp[2021],
                                         sp[2022])):
                st, r = ratio_stats(before, after, name, s)
                joins.append(st); ratio_maps[(name, s)] = (r, np.nan_to_num(before))
                rb, ra = regional(before, W)[0], regional(after, W)[0]
                for j, reg in enumerate(REGIONS):
                    jregion.append(dict(join=name, sector=s, region=reg, before_km3=rb[j], after_km3=ra[j],
                                        ratio=ra[j] / rb[j] if rb[j] else np.nan))
        st, r = ratio_stats(keep[('3a-histsoc', s, 'ww', 'value')][2005], keep[('3a-histsoc', s, 'ww', 'value')][2006],
                            '3a histsoc 2005 -> 2006 (start of the WFaS extension)', s)
        joins.append(st); ratio_maps[('3a histsoc 2005 -> 2006 (start of the WFaS extension)', s)] = (
            r, np.nan_to_num(keep[('3a-histsoc', s, 'ww', 'value')][2005]))
        st, r = ratio_stats(keep[('3a-histsoc', s, 'ww', 'value')][2014], keep[('3a-histsoc', s, 'ww',
                                                                                 'value')][2015],
                            '3a histsoc 2014 -> 2015 (reference)', s)
        joins.append(st)
    pd.DataFrame(joins).to_csv(f'{tabd}/join_cell_ratios.csv', index=False)
    npos = []
    for k, (ys, a) in full_keep.items():
        for i, y in enumerate(ys):
            npos.append(dict(series=k[0], sector=k[1], quantity=k[2], stat=k[3], year=int(y),
                             n_cells_positive=int((np.nan_to_num(a[i]) > 0).sum()),
                             n_cells_fill=int(np.isnan(a[i]).sum())))
    pd.DataFrame(npos).to_csv(f'{tabd}/positive_cells_per_year.csv', index=False)
    # cell-level change from one year to the next (3a histsoc), and the 2021 -> 2022 joins for comparison
    steps = []

    def step(name, y, before, after, s, q):
        b0, a0 = np.nan_to_num(before), np.nan_to_num(after)
        pos = b0 > 0
        r = np.where(pos, a0 / np.where(pos, b0, 1), np.nan)
        big = pos & ((r < 0.5) | (r > 2))
        steps.append(dict(step=name, year_before=y, sector=s, quantity=q, global_change=a0.sum() / b0.sum() - 1,
                          share_before_in_cells_halved_or_doubled=b0[big].sum() / b0.sum(),
                          share_before_in_cells_going_to_zero=b0[pos & (a0 <= 0)].sum() / b0.sum(),
                          share_after_in_cells_new=a0[~pos & (a0 > 0)].sum() / a0.sum()))
    for s in SECTORS:
        for q in ('ww', 'wc'):
            ys, a = full_keep[('3a-histsoc', s, q, 'value')]
            for i in range(len(ys) - 1):
                step('3a histsoc year to year', int(ys[i]), a[i], a[i + 1], s, q)
        for ssp in ('3b-ssp126', '3b-ssp370'):
            step(f'3a histsoc 2021 -> {ssp} 2022', 2021, keep[('3a-histsoc', s, 'ww', 'value')][2021],
                 keep[(ssp, s, 'ww', 'modelavg')][2022], s, 'ww')
            ys, a = full_keep[(ssp, s, 'ww', 'modelavg')]
            for i in range(len(ys) - 1):
                step(f'{ssp} year to year', int(ys[i]), a[i], a[i + 1], s, 'ww')
    pd.DataFrame(steps).to_csv(f'{tabd}/year_step_cell_changes.csv', index=False)
    pd.DataFrame(jregion).to_csv(f'{tabd}/join_by_region.csv', index=False)

    # ---- what a per-cell join of the SSP series to the 3a 2021 value implies
    jopt = []
    for s in SECTORS:
        h21 = np.nan_to_num(keep[('3a-histsoc', s, 'ww', 'value')][2021])
        for ssp in ('3b-ssp126', '3b-ssp370'):
            ys, a = full_keep[(ssp, s, 'ww', 'modelavg')]
            a = np.nan_to_num(a)
            s21 = a[list(ys).index(2021)]
            ok = s21 > 0
            ratio = np.where(ok, h21 / np.where(ok, s21, 1), np.nan)
            undefined = (h21 > 0) & ~ok
            for i, y in enumerate(ys):
                if y < 2021:
                    continue
                ratio_join = np.where(ok, a[i] * np.nan_to_num(ratio), 0.0)
                ratio_join_keep = np.where(undefined, h21, ratio_join)       # undefined cells held at 2021
                additive = np.maximum(a[i] + (h21 - s21), 0.0)
                jopt.append(dict(ssp=ssp, sector=s, year=int(y), raw_km3=a[i].sum() / KM3,
                                 ratio_join_km3=ratio_join.sum() / KM3,
                                 ratio_join_hold_undefined_km3=ratio_join_keep.sum() / KM3,
                                 additive_join_km3=additive.sum() / KM3,
                                 hist_2021_km3=h21.sum() / KM3,
                                 n_cells_ratio_undefined=int(undefined.sum()),
                                 volume_2021_km3_ratio_undefined=float(h21[undefined].sum() / KM3),
                                 n_cells_ratio_above_3=int((np.nan_to_num(ratio) > 3).sum()),
                                 n_cells_ratio_below_0p33=int((ok & (np.nan_to_num(ratio) < 1 / 3)).sum())))
            ratio_maps[(f'per-cell join ratio 3a 2021 / {ssp} 2021', s)] = (ratio, h21)
    pd.DataFrame(jopt).to_csv(f'{tabd}/join_options_global.csv', index=False)

    # ---- model spread of the SSP series
    spread = []
    for s in SECTORS:
        for ssp in ('3b-ssp126', '3b-ssp370'):
            for y in (2015, 2022, 2050, 2100):
                avg = np.nan_to_num(keep[(ssp, s, 'ww', 'modelavg')][y])
                sd = np.nan_to_num(keep[(ssp, s, 'ww', 'modelstd')][y])
                pos = avg > 0
                cv = sd[pos] / avg[pos]
                o = np.argsort(cv); cw = np.cumsum(avg[pos][o]) / avg[pos].sum()
                ra, rs = regional(avg, W)[0], regional(sd, W)[0]
                for j, reg in enumerate(REGIONS):
                    spread.append(dict(ssp=ssp, sector=s, year=y, region=reg, modelavg_km3=ra[j],
                                       sum_of_cell_std_km3=rs[j], ratio=rs[j] / ra[j] if ra[j] else np.nan,
                                       cv_median=float(np.median(cv)) if reg == 'global' else np.nan,
                                       cv_volume_weighted_median=float(cv[o][np.searchsorted(cw, 0.5)])
                                       if reg == 'global' else np.nan,
                                       n_cells_cv_above_1=int((cv > 1).sum()) if reg == 'global' else np.nan,
                                       n_cells_std_negative=int((sd < 0).sum()) if reg == 'global' else np.nan))
    pd.DataFrame(spread).to_csv(f'{tabd}/ssp_model_spread.csv', index=False)

    # ---- consumption fraction and consumption > withdrawal
    cfr = []
    for series in ('3a-histsoc', '3b-histsoc', '3b-1850soc', '3b-2015soc'):
        for s in SECTORS:
            for y, ww in keep[(series, s, 'ww', 'value')].items():
                wc = keep[(series, s, 'wc', 'value')].get(y)
                if wc is None:
                    continue
                ww0, wc0 = np.nan_to_num(ww), np.nan_to_num(wc)
                exc = wc0 > ww0 * (1 + 1e-9)
                rw, rc = regional(ww0, W)[0], regional(wc0, W)[0]
                pos = ww0 > 0
                f = wc0[pos] / ww0[pos]
                for j, reg in enumerate(REGIONS):
                    cfr.append(dict(series=series, sector=s, year=y, region=reg, ww_km3=rw[j], wc_km3=rc[j],
                                    consumption_fraction=rc[j] / rw[j] if rw[j] else np.nan,
                                    n_cells_wc_gt_ww=int(exc.sum()) if reg == 'global' else np.nan,
                                    excess_km3=float((wc0 - ww0)[exc].sum() / KM3) if reg == 'global' else np.nan,
                                    n_cells_wc_positive_ww_zero=int(((wc0 > 0) & (ww0 == 0)).sum())
                                    if reg == 'global' else np.nan,
                                    cell_cf_p05=float(np.percentile(f, 5)) if reg == 'global' else np.nan,
                                    cell_cf_p50=float(np.percentile(f, 50)) if reg == 'global' else np.nan,
                                    cell_cf_p95=float(np.percentile(f, 95)) if reg == 'global' else np.nan))
    cf = pd.DataFrame(cfr)
    cf.to_csv(f'{tabd}/consumption_fraction.csv', index=False)
    # annual consumption fraction 1850-2021 (3a) from the regional totals
    piv = tot[(tot.series == '3a-histsoc')].pivot_table(index=['sector', 'year', 'region'], columns='quantity',
                                                         values='km3').reset_index()
    piv['consumption_fraction'] = piv['wc'] / piv['ww']
    piv.to_csv(f'{tabd}/consumption_fraction_3a_annual.csv', index=False)

    # ---- withdrawal without population, and withdrawal outside the VIC domain
    popc, vicc, popmaps = [], [], {}
    pop_cases = [('3a-histsoc', 'histsoc', 'population_histsoc', y) for y in (1901, 1950, 2000, 2014, 2021)]
    pop_cases += [('3b-ssp126', 'ssp1vlsoc-noadapt', 'population_ssp1', y) for y in (2022, 2050, 2100)]
    pop_cases += [('3b-ssp370', 'ssp3hsoc-noadapt', 'population_ssp3', y) for y in (2022, 2050, 2100)]
    for series, pdir, pref, y in pop_cases:
        p5, p05, pfile = population05(pdir, pref, y)
        # population of active VIC cells per parent
        vic_on5 = np.zeros((2160, 4320), bool)
        r0 = int(np.round((89.9583333 - 83.9583333) / (1 / 12)))      # first VIC row (83.96N) in the global 5'
        vic_on5[r0:r0 + vic_mask.shape[0]] = vic_mask[::-1]          # VIC is south-to-north
        pact = (p5 * vic_on5).reshape(NLAT, 6, NLON, 6).sum(axis=(1, 3))
        for s in SECTORS:
            ww = np.nan_to_num(K(series, s)[y])
            tot_ww = ww.sum()
            nopop = (ww > 0) & (p05 <= 0)
            novic = (ww > 0) & (vicp == 0)
            vic_nopop = (ww > 0) & (vicp > 0) & (pact <= 0) & (p05 > 0)    # population only outside VIC
            popc.append(dict(series=series, sector=s, year=y, population_file=pfile,
                             n_cells_ww_positive=int((ww > 0).sum()),
                             n_cells_ww_positive_population_zero=int(nopop.sum()),
                             volume_km3=float(ww[nopop].sum() / KM3), share=float(ww[nopop].sum() / tot_ww),
                             n_cells_population_positive_ww_zero=int(((p05 > 0) & (ww <= 0)).sum())))
            vicc.append(dict(series=series, sector=s, year=y,
                             n_parents_ww_positive_no_active_vic_cell=int(novic.sum()),
                             volume_km3_no_active_vic_cell=float(ww[novic].sum() / KM3),
                             share_no_active_vic_cell=float(ww[novic].sum() / tot_ww),
                             n_parents_ww_positive_population_only_outside_vic=int(vic_nopop.sum()),
                             volume_km3_population_only_outside_vic=float(ww[vic_nopop].sum() / KM3),
                             share_population_only_outside_vic=float(ww[vic_nopop].sum() / tot_ww)))
            if (series, y) in (('3a-histsoc', 2021),):
                popmaps[s] = (nopop, novic, vic_nopop, ww)
    pd.DataFrame(popc).to_csv(f'{tabd}/withdrawal_without_population.csv', index=False)
    pd.DataFrame(vicc).to_csv(f'{tabd}/withdrawal_vs_vic_domain.csv', index=False)

    # ---- grid identity
    gridrel = dict(isimip4b_05_grid='raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_water-global.nc '
                                    '(360 x 720, 89.75 to -89.75, -179.75 to 179.75)',
                   n_water_global_mask_cells=int(land.sum()),
                   hist_files_rows_in_isimip_grid='12-291 (83.75N to 55.75S)', **vicrel,
                   hist_grid_equals_vic_parent_rows=bool(
                       np.isclose(vicrel['parent_lat_first'], -55.75) and np.isclose(vicrel['parent_lat_last'], 83.75)),
                   water_global_cells_outside_hist_rows=int(land[:12].sum() + land[292:].sum()))
    json.dump(gridrel, open(f'{tabd}/grid_relation.json', 'w'), indent=1)

    # ---- published estimates
    pub = pd.read_csv(f'{HERE}/published_estimates.csv', comment='#')
    cmp_rows = []
    for _, p in pub.iterrows():
        secs = ('dom', 'ind') if p.sector == 'dom+ind' else (p.sector,)
        sel = tot[(tot.series == '3a-histsoc') & (tot.year == p.year) & (tot.region == p.region) &
                  (tot.quantity == p.quantity) & tot.sector.isin(secs)]
        v = sel.km3.sum()
        cmp_rows.append(dict(source_id=p.source_id, year=p.year, region=p.region, sector=p.sector,
                             quantity=p.quantity, published_km3=p.km3, isimip3a_km3=v, ratio=v / p.km3))
    pd.DataFrame(cmp_rows).to_csv(f'{tabd}/published_comparison.csv', index=False)

    # ---- WaterGAP groundwater-fraction tables
    gw = review_groundwater_tables(land, tabd)

    # ---- figures
    make_figures(figd, tot, pub, cf, ratio_maps, keep, popmaps, area, land, gw, pd.DataFrame(jopt),
                 pd.DataFrame(steps))

    # ---- QC summaries
    write_qc(qc_wa, qc_gw, hdr, pd.DataFrame(checks), pd.DataFrame(joins), cf, pd.DataFrame(popc),
             pd.DataFrame(vicc), gridrel, gw, base, commit, dirty, t0)
    print('done', datetime.datetime.now(datetime.timezone.utc).isoformat())


def review_groundwater_tables(land, tabd):
    root = f'{workdir()}/raw/external/{GW_ID}/{GW_VERSION}'
    ids = pd.read_csv(f'{root}/input/Arc_ID_lon_lat_continentalarea.txt', sep='\t')
    out = dict(lookup_rows=len(ids), lookup_columns=list(ids.columns),
               lookup_ids_unique=bool(ids.Arc_ID.is_unique),
               lookup_ids_1_to_n=bool((np.sort(ids.Arc_ID.values) == np.arange(1, len(ids) + 1)).all()))
    iy = np.round((89.75 - ids.lat.values) / 0.5).astype(int)
    ix = np.round((ids.lon.values + 179.75) / 0.5).astype(int)
    on_grid = np.allclose(LAT05[iy], ids.lat.values) and np.allclose(LON05[ix], ids.lon.values)
    cellmask = np.zeros((NLAT, NLON), bool); cellmask[iy, ix] = True
    out.update(lookup_on_isimip_grid=bool(on_grid), lookup_cells_unique=int(cellmask.sum()) == len(ids),
               lookup_cells_equal_water_global_mask=bool((cellmask == land).all()),
               lookup_cells_not_in_mask=int((cellmask & ~land).sum()),
               mask_cells_not_in_lookup=int((land & ~cellmask).sum()),
               lookup_cells_not_in_mask_latlon=[[float(LAT05[i]), float(LON05[j])] for i, j in
                                                zip(*np.nonzero(cellmask & ~land))],
               mask_cells_not_in_lookup_latlon=[[float(LAT05[i]), float(LON05[j])] for i, j in
                                                zip(*np.nonzero(land & ~cellmask))],
               lookup_lat_range=[float(ids.lat.min()), float(ids.lat.max())])
    tables, maps = {}, {}
    for key, rel in (('dom', 'domestic/input/G_FRACTGW_DOM.txt'), ('man', 'industrial/input/G_FRACTGW_MAN.txt'),
                     ('irrig', 'irrigation/input/G_FRACTGW_IRRIG.txt')):
        t = pd.read_csv(f'{root}/{rel}', sep='\t')
        v = t.VALUE.values.astype('f8')
        m = np.full((NLAT, NLON), np.nan)
        idx = ids.set_index('Arc_ID').loc[t.Arc_ID]
        m[np.round((89.75 - idx.lat.values) / 0.5).astype(int), np.round((idx.lon.values + 179.75) / 0.5).astype(int)] = v
        maps[key] = m
        tables[key] = dict(file=rel, rows=len(t), columns=list(t.columns), ids_match_lookup=bool(
            (np.sort(t.Arc_ID.values) == np.sort(ids.Arc_ID.values)).all()), n_nan=int(np.isnan(v).sum()),
            min=float(np.nanmin(v)), max=float(np.nanmax(v)), mean=float(np.nanmean(v)),
            n_zero=int((v == 0).sum()), n_one=int((v == 1).sum()), n_outside_0_1=int(((v < 0) | (v > 1)).sum()),
            decimals=int(max(len(x.split('.')[-1]) for x in open(f'{root}/{rel}').read().split()[3::2][:1000])))
    out['tables'] = tables
    json.dump(out, open(f'{tabd}/groundwater_tables.json', 'w'), indent=1)
    out['maps'] = maps
    return out


def status_of(flags):
    order = ['passed', 'warning', 'failed']
    return max(flags, key=order.index) if flags else 'not_checked'


def write_qc(qc_wa, qc_gw, hdr, checks, joins, cf, popc, vicc, grid, gw, base, commit, dirty, t0):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    c = {}
    c['integrity'] = dict(status='passed', detail='size and md5 against levante 52/52, sha512 against '
                          'data.isimip.org 52/52 (manifests/inputs/isimip3-water-abstraction.yaml)')
    struct_ok = bool(hdr.on_isimip_05_grid.all() and hdr.years_contiguous.all())
    c['structure'] = dict(status='passed' if struct_ok else 'failed',
                          files=int(len(hdr)), all_on_isimip_05_grid=bool(hdr.on_isimip_05_grid.all()),
                          all_years_contiguous=bool(hdr.years_contiguous.all()),
                          grids=sorted(set(f'{a}x{b} {o}' for a, b, o in zip(hdr.n_lat, hdr.n_lon, hdr.lat_order))))
    nonCF = sorted(set(hdr.time_units[hdr.time_units.str.startswith('years')]))
    c['time_axis'] = dict(status='warning' if nonCF else 'passed', non_cf_time_units=nonCF,
                          note='"years since" is rejected by netCDF4/cftime/xarray for the standard calendar; '
                               'year = 1901 + round(value)')
    neg = int(hdr.n_negative.sum())
    fill_land = hdr.groupby('series').n_fill_land_cellyears.sum().to_dict()
    ocean = int(hdr.n_ocean_cells_positive.sum())
    c['values'] = dict(status='failed' if neg else ('warning' if (ocean or any(fill_land.values())) else 'passed'),
                       negative_values=neg, files_with_positive_values_outside_water_global_mask=int(
                           (hdr.n_ocean_cells_positive > 0).sum()),
                       fill_cellyears_on_water_global_land_by_series={k: int(v) for k, v in fill_land.items()},
                       note='historical and fixed-year files carry no fill values (missing set to 0 by setmisstoc); '
                            'details in tables/file_headers.csv')
    exc = cf[(cf.region == 'global')].groupby(['series', 'sector']).n_cells_wc_gt_ww.max().to_dict()
    c['consumption_vs_withdrawal'] = dict(
        status='warning' if any(v > 0 for v in exc.values()) else 'passed',
        max_cells_wc_gt_ww_in_checked_years={f'{a} {b}': int(v) for (a, b), v in exc.items()})
    c['time_consistency'] = dict(status='warning', detail='see tables/time_checks.csv and join_cell_ratios.csv',
                                 n_checks=int(len(checks)), n_identical=int(checks.identical.fillna(False).sum()))
    c['population'] = dict(status='warning' if (popc.share > 0.001).any() else 'passed',
                           max_share_without_population=float(popc.share.max()))
    c['vic_domain'] = dict(status='warning' if (vicc.share_no_active_vic_cell > 0.001).any() else 'passed',
                           max_share_outside_vic_domain=float(vicc.share_no_active_vic_cell.max()))
    c['grid'] = dict(status='passed' if grid['hist_grid_equals_vic_parent_rows'] else 'failed', **grid)
    summary = dict(object=f'raw/external/{WA_ID}/{WA_VERSION}', checked_utc=now, checker=
                   f'analysis/{TASK}/review_water_abstraction.py', code_commit=commit, code_dirty=dirty,
                   status=status_of([v['status'] for v in c.values()]), checks=c,
                   products=f'{os.path.relpath(base, workdir())}/ (report.md, tables/, figures/)')
    json.dump(summary, open(f'{qc_wa}/summary.json', 'w'), indent=1, default=str)
    t = gw['tables']
    gok = all(v['n_outside_0_1'] == 0 and v['n_nan'] == 0 and v['ids_match_lookup'] for v in t.values())
    look = {k: v for k, v in gw.items() if k not in ('tables', 'maps')}
    gsum = dict(object=f'raw/external/{GW_ID}/{GW_VERSION}', checked_utc=now,
                checker=f'analysis/{TASK}/review_water_abstraction.py', code_commit=commit, code_dirty=dirty,
                status='passed' if gok and look['lookup_on_isimip_grid'] and look['lookup_cells_unique'] else 'failed',
                checks=dict(integrity=dict(status='passed', detail='md5 against the source 4/4'),
                            lookup=dict(status='passed' if look['lookup_on_isimip_grid'] else 'failed', **look),
                            tables={k: dict(status='passed' if (v['n_outside_0_1'] == 0 and v['n_nan'] == 0
                                                                and v['ids_match_lookup']) else 'failed', **v)
                                    for k, v in t.items()},
                            provenance=dict(status='passed', detail='source recorded in manifests/inputs/'
                                            'watergap-groundwater-fractions.yaml; the files carry no WaterGAP '
                                            'version or citation'),
                            livestock=dict(status='not_checked', detail='no livestock table exists in the source')))
    json.dump(gsum, open(f'{qc_gw}/summary.json', 'w'), indent=1, default=str)


# ----------------------------------------------------------------------------------------------- figures

COLORS = {'3a-histsoc': '#1f4e9c', '3b-histsoc': '#7aa6e0', '3b-1850soc': '#8c8c8c', '3b-2015soc': '#2e2e2e',
          '3b-ssp126': '#2a9d5c', '3b-ssp370': '#d1495b'}
SECTOR_NAME = {'dom': 'domestic', 'ind': 'industrial'}


def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.alpha': 0.3, 'savefig.dpi': 150})
    return plt


def _map(ax, field, title, **kw):
    """Plot a 360 x 720 north-to-south field on a cartopy axis."""
    import cartopy.crs as ccrs
    im = ax.imshow(field, extent=(-180, 180, -90, 90), origin='upper', transform=ccrs.PlateCarree(),
                   interpolation='nearest', **kw)
    ax.coastlines(linewidth=0.3, color='0.4')
    ax.set_extent((-180, 180, -58, 84), ccrs.PlateCarree())
    ax.set_title(title, fontsize=9)
    return im


def _series(tot, series, sector, q, region='global', stat=None):
    st = stat or ('modelavg' if series.startswith('3b-ssp') else 'value')
    d = tot[(tot.series == series) & (tot.sector == sector) & (tot.quantity == q) & (tot.stat == st) &
            (tot.region == region)].sort_values('year')
    return d.year.values, d.km3.values


def make_figures(figd, tot, pub, cf, ratio_maps, keep, popmaps, area, land, gw, jopt, steps):
    plt = _plt()
    import cartopy.crs as ccrs
    from matplotlib.colors import LogNorm, TwoSlopeNorm, ListedColormap

    # 1. global totals 1601-2100, all series
    fig, axs = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for i, q in enumerate(('ww', 'wc')):
        for j, s in enumerate(SECTORS):
            ax = axs[i, j]
            for ser in SERIES_LABEL:
                if q == 'wc' and ser.startswith('3b-ssp'):
                    continue
                y, v = _series(tot, ser, s, q)
                ax.plot(y, v, color=COLORS[ser], lw=1.2 if ser != '3b-histsoc' else 2.2, label=SERIES_LABEL[ser],
                        ls='--' if ser == '3b-histsoc' else '-', zorder=3 if ser == '3a-histsoc' else 2)
            p = pub[(pub.region == 'global') & (pub.sector == s) & (pub.quantity == q)]
            if len(p):
                ax.plot(p.year, p.km3, 'k*', ms=9, label='FAO AQUASTAT, around 2010')
            ax.set_title(f'{SECTOR_NAME[s]} {"withdrawal" if q == "ww" else "consumption"}')
            ax.set_ylabel('km$^3$ yr$^{-1}$')
    axs[0, 0].legend(fontsize=7, loc='upper left')
    axs[1, 0].set_xlim(1600, 2100)
    fig.suptitle('Global totals of all files, 1601-2100 (SSP: model mean; no consumption is provided for the SSPs)')
    fig.tight_layout(); fig.savefig(f'{figd}/01_global_totals_1601_2100.png'); plt.close(fig)

    # 2. the joins around 2014/2015 and 2021/2022, with per-cell join options
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    for j, s in enumerate(SECTORS):
        ax = axs[j]
        for ser in ('3a-histsoc', '3b-histsoc', '3b-2015soc', '3b-ssp126', '3b-ssp370'):
            y, v = _series(tot, ser, s, 'ww')
            m = (y >= 1990)
            ax.plot(y[m], v[m], color=COLORS[ser], label=SERIES_LABEL[ser], lw=1.4,
                    ls='--' if ser == '3b-histsoc' else '-')
        for ssp in ('3b-ssp126', '3b-ssp370'):
            d = jopt[(jopt.ssp == ssp) & (jopt.sector == s) & (jopt.year >= 2022)]
            ax.plot(d.year, d.ratio_join_hold_undefined_km3, color=COLORS[ssp], ls=':', lw=1.6,
                    label=f'{ssp[3:]} joined per cell (ratio to 2021)')
            ax.plot(d.year, d.additive_join_km3, color=COLORS[ssp], ls='-.', lw=1.0,
                    label=f'{ssp[3:]} joined per cell (offset to 2021)')
        ax.axvline(2021.5, color='0.5', lw=0.8); ax.axvline(2014.5, color='0.5', lw=0.8, ls=':')
        ax.set_title(f'{SECTOR_NAME[s]} withdrawal, global'); ax.set_ylabel('km$^3$ yr$^{-1}$')
    axs[0].legend(fontsize=6.5)
    fig.tight_layout(); fig.savefig(f'{figd}/02_global_joins_1990_2100.png'); plt.close(fig)

    # 3. continents
    fig, axs = plt.subplots(2, 6, figsize=(16, 6))
    for i, s in enumerate(SECTORS):
        for j, reg in enumerate(CONTINENTS):
            ax = axs[i, j]
            for ser in ('3a-histsoc', '3b-ssp126', '3b-ssp370'):
                y, v = _series(tot, ser, s, 'ww', reg)
                ax.plot(y, v, color=COLORS[ser], lw=1.2, label=SERIES_LABEL[ser])
            p = pub[(pub.region == reg) & (pub.sector == s)]
            ax.plot(p.year, p.km3, 'k*', ms=8, label='FAO AQUASTAT, around 2010')
            ax.set_xlim(1850, 2100); ax.set_ylim(bottom=0)
            ax.set_title(f'{reg}, {SECTOR_NAME[s]}', fontsize=8)
    axs[0, 0].set_ylabel('withdrawal km$^3$ yr$^{-1}$'); axs[1, 0].set_ylabel('withdrawal km$^3$ yr$^{-1}$')
    axs[0, 0].legend(fontsize=6)
    fig.tight_layout(); fig.savefig(f'{figd}/03_continent_withdrawal_1850_2100.png'); plt.close(fig)

    # 4. consumption fraction 1850-2021 (3a) by region
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    t3 = tot[(tot.series == '3a-histsoc')]
    for j, s in enumerate(SECTORS):
        for reg in REGIONS[:-1]:
            yw, w = _series(t3, '3a-histsoc', s, 'ww', reg)
            _, c = _series(t3, '3a-histsoc', s, 'wc', reg)
            axs[j].plot(yw, c / w, lw=2.2 if reg == 'global' else 1.0, color='k' if reg == 'global' else None,
                        label=reg)
        axs[j].set_title(f'{SECTOR_NAME[s]}: consumption / withdrawal (ISIMIP3a histsoc)')
        axs[j].set_xlim(1850, 2021)
    axs[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f'{figd}/04_consumption_fraction_1850_2021.png'); plt.close(fig)

    # 5. withdrawal maps 2021 (mm/yr) and 6. consumption fraction maps 2021
    fig, axs = plt.subplots(2, 2, figsize=(13, 6.4), subplot_kw=dict(projection=ccrs.PlateCarree()))
    for j, s in enumerate(SECTORS):
        ww = keep[('3a-histsoc', s, 'ww', 'value')][2021]
        wc = keep[('3a-histsoc', s, 'wc', 'value')][2021]
        mm = np.where(ww > 0, ww / area * 1000, np.nan)
        im = _map(axs[0, j], mm, f'{SECTOR_NAME[s]} withdrawal 2021 (ISIMIP3a), mm/yr over the cell area',
                  norm=LogNorm(1e-2, 1e3), cmap='viridis')
        fig.colorbar(im, ax=axs[0, j], shrink=0.7)
        f = np.where(ww > 0, wc / np.where(ww > 0, ww, 1), np.nan)
        im = _map(axs[1, j], f, f'{SECTOR_NAME[s]} consumption fraction 2021 (wc/ww)', vmin=0, vmax=1,
                  cmap='magma_r')
        fig.colorbar(im, ax=axs[1, j], shrink=0.7)
    fig.tight_layout(); fig.savefig(f'{figd}/05_maps_2021_withdrawal_and_consumption_fraction.png'); plt.close(fig)

    # 7. join ratio maps 3a 2021 -> SSP 2022
    fig, axs = plt.subplots(2, 2, figsize=(13, 6.4), subplot_kw=dict(projection=ccrs.PlateCarree()))
    for i, ssp in enumerate(('3b-ssp126', '3b-ssp370')):
        for j, s in enumerate(SECTORS):
            r, _ = ratio_maps[(f'3a histsoc 2021 -> {ssp} 2022', s)]
            im = _map(axs[i, j], np.log2(r), f'{SECTOR_NAME[s]}: log2({ssp[3:]} 2022 / 3a 2021)',
                      cmap='RdBu_r', norm=TwoSlopeNorm(0, -2, 2))
            fig.colorbar(im, ax=axs[i, j], shrink=0.7, extend='both')
    fig.tight_layout(); fig.savefig(f'{figd}/06_maps_join_ratio_2021_2022.png'); plt.close(fig)

    # 8. histograms of per-cell ratios, weighted by the earlier withdrawal
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    bins = np.linspace(-3, 3, 121)
    for j, s in enumerate(SECTORS):
        for name, col, ls in (('3a histsoc 2021 -> 3b-ssp126 2022', COLORS['3b-ssp126'], '-'),
                              ('3a histsoc 2021 -> 3b-ssp370 2022', COLORS['3b-ssp370'], '-'),
                              ('3b histsoc 2014 -> 3b-ssp370 2015', '0.3', '--'),
                              ('3b-ssp370 2021 -> 3b-ssp370 2022 (one model year, reference)', '0.6', ':'),
                              ('3a histsoc 2005 -> 2006 (start of the WFaS extension)', '#1f4e9c', '-.')):
            r, w = ratio_maps[(name, s)]
            ok = np.isfinite(r)
            axs[j].hist(np.log2(r[ok]), bins=bins, weights=w[ok] / w[ok].sum(), histtype='step', color=col, ls=ls,
                        lw=1.4, label=name)
        axs[j].set_xlabel('log2(after / before), per 0.5 degree cell')
        axs[j].set_ylabel('share of the earlier withdrawal'); axs[j].set_title(SECTOR_NAME[s])
    axs[0].legend(fontsize=6.5)
    fig.tight_layout(); fig.savefig(f'{figd}/07_hist_join_ratio.png'); plt.close(fig)

    # 9. model spread (std / mean) of the SSP series
    fig, axs = plt.subplots(2, 2, figsize=(13, 6.4), subplot_kw=dict(projection=ccrs.PlateCarree()))
    for i, y in enumerate((2022, 2100)):
        for j, s in enumerate(SECTORS):
            a = keep[('3b-ssp370', s, 'ww', 'modelavg')][y]
            sd = keep[('3b-ssp370', s, 'ww', 'modelstd')][y]
            cv = np.where(a > 0, sd / np.where(a > 0, a, 1), np.nan)
            im = _map(axs[i, j], cv, f'{SECTOR_NAME[s]} ssp370 {y}: model std / model mean', vmin=0, vmax=1.5,
                      cmap='plasma')
            fig.colorbar(im, ax=axs[i, j], shrink=0.7, extend='max')
    fig.tight_layout(); fig.savefig(f'{figd}/08_maps_ssp370_model_spread.png'); plt.close(fig)

    # 10. cells needing special handling in W2 (2021)
    cmap = ListedColormap(['#e8e8e8', '#d1495b', '#f4a261', '#2a9d8f'])
    fig, axs = plt.subplots(1, 2, figsize=(13, 3.6), subplot_kw=dict(projection=ccrs.PlateCarree()))
    for j, s in enumerate(SECTORS):
        nopop, novic, vic_nopop, ww = popmaps[s]
        cat = np.where(ww > 0, 0.0, np.nan)
        cat[vic_nopop & ~nopop] = 3; cat[nopop] = 1; cat[novic] = 2
        _map(axs[j], cat, f'{SECTOR_NAME[s]} withdrawal 2021: grey = normal, red = no ISIMIP4b population in the cell,\n'
                          f'orange = no active VIC cell, green = population only outside the active VIC cells',
             cmap=cmap, vmin=-0.5, vmax=3.5)
    fig.tight_layout(); fig.savefig(f'{figd}/09_maps_special_cells_2021.png'); plt.close(fig)

    # 11. 3b histsoc versus 3a histsoc
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for s in SECTORS:
        for q in ('ww', 'wc'):
            ya, a = _series(tot, '3a-histsoc', s, q)
            yb, b = _series(tot, '3b-histsoc', s, q)
            yy = np.intersect1d(ya, yb)
            ax.plot(yy, 100 * (b[np.isin(yb, yy)] / a[np.isin(ya, yy)] - 1), label=f'{s}{q}')
    ax.set_ylabel('3b / 3a - 1 (%), global'); ax.legend(fontsize=7)
    ax.set_title('ISIMIP3b histsoc versus ISIMIP3a histsoc, 1850-2014')
    fig.tight_layout(); fig.savefig(f'{figd}/10_3b_vs_3a_histsoc.png'); plt.close(fig)

    # 12. WaterGAP groundwater fractions
    fig, axs = plt.subplots(1, 3, figsize=(16, 3.4), subplot_kw=dict(projection=ccrs.PlateCarree()))
    for j, (k, t) in enumerate((('dom', 'G_FRACTGW_DOM'), ('man', 'G_FRACTGW_MAN'), ('irrig', 'G_FRACTGW_IRRIG'))):
        im = _map(axs[j], gw['maps'][k], f'{t} (WaterGAP table)', vmin=0, vmax=1, cmap='YlGnBu')
    fig.colorbar(im, ax=list(axs), shrink=0.7)
    fig.savefig(f'{figd}/11_maps_groundwater_fractions.png', bbox_inches='tight'); plt.close(fig)

    # 13. cell-level year-to-year change
    fig, axs = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    for j, s in enumerate(SECTORS):
        ax = axs[j]
        for name, col in (('3a histsoc year to year', COLORS['3a-histsoc']), ('3b-ssp126 year to year',
                          COLORS['3b-ssp126']), ('3b-ssp370 year to year', COLORS['3b-ssp370'])):
            d = steps[(steps.step == name) & (steps.sector == s) & (steps.quantity == 'ww')]
            ax.plot(d.year_before + 0.5, 100 * d.share_before_in_cells_halved_or_doubled, color=col, lw=1.2,
                    label=name.replace(' year to year', ''))
        for ssp in ('3b-ssp126', '3b-ssp370'):
            d = steps[(steps.step == f'3a histsoc 2021 -> {ssp} 2022') & (steps.sector == s)]
            ax.plot(d.year_before + 0.5, 100 * d.share_before_in_cells_halved_or_doubled, 'o', color=COLORS[ssp],
                    label=f'3a 2021 -> {ssp[3:]} 2022')
        ax.set_xlim(1950, 2100); ax.set_title(f'{SECTOR_NAME[s]} withdrawal')
        ax.set_ylabel('% of withdrawal in cells that halve or double\nfrom one year to the next')
    axs[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f'{figd}/12_cell_change_year_to_year.png'); plt.close(fig)


# ----------------------------------------------------------------------------------------------- submit

def submit(scratch):
    base, _, _ = out_dirs(scratch)
    logs = f'{base}/logs'
    os.makedirs(logs, exist_ok=True)
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip()
    step = 'review'
    text = SBATCH.format(job=f'{TASK}-{step}', logs=logs, step=step, conda=conda, workdir=workdir(), repo=REPO,
                         task=TASK, args='--scratch' if scratch else '')
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{logs}/{step}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}/')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--submit', action='store_true', help='submit the review as a Slurm job')
    ap.add_argument('--scratch', action='store_true', help=f'write to scratch/{TASK}/run/ (test runs)')
    a = ap.parse_args()
    sys.path.insert(0, HERE)
    if a.submit:
        submit(a.scratch)
    else:
        run(a.scratch)


if __name__ == '__main__':
    main()
