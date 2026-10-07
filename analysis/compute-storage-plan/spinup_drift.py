#!/usr/bin/env python3
"""Drift of the water stores in the 10-year smoke run (cold start, 2011-2020): first direct evidence on how fast the
stores of this configuration (water use on, GWM FALSE) relax, for the spin-up length of the plan.

The run starts from the initial state of the parameter file (no spin-up) under historical climate and histsoc DHF,
so a year-to-year change mixes relaxation from the cold start, climate variability and the DHF trend. Relaxation
shows as a change that is large in the first years and falls to the level of climate variability.

Reads (only) runs/smoke/<run>__smoke2011-2020/output/monthly.<year>-01.nc and the domain file of the run. Writes
under workdir/analysis/compute-storage-plan/:
  tables/drift_global_monthly.csv  global total of each store per month (km3)
  tables/drift_annual.csv          per store and year: December and annual mean (km3), change of the December total
                                   from the previous year, area-weighted mean |change| of the December value per cell
                                   (mm and % of the store's mean depth), share of cells that changed in the same
                                   direction in every year since 2012
  tables/drift_snow_regions.csv    cells whose December snow rose in every year since 2012, by 10-degree box
  figures/spinup_drift.png

Usage: spinup_drift.py [--run smoke2011-2020]
"""
import argparse, csv, glob, os, sys

import netCDF4
import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csp   # noqa: E402

# store -> (VIC outputs summed, layer index or None); units read from the file (mm or hm3)
STORES = {
    'soil layer 1': (['OUT_SOIL_MOIST'], 0),
    'soil layer 2': (['OUT_SOIL_MOIST'], 1),
    'soil layer 3': (['OUT_SOIL_MOIST'], 2),
    'snow': (['OUT_SWE', 'OUT_SNOW_CANOPY'], None),
    'canopy water': (['OUT_WDEW'], None),
    'surface storage': (['OUT_SURFSTOR'], None),
    'river': (['OUT_STREAM_MOIST'], None),
    'reservoirs': (['OUT_GDAM_STORAGE', 'OUT_LDAM_STORAGE'], None),
}
CELL_STORES = ('soil layer 1', 'soil layer 2', 'soil layer 3', 'snow')   # per-cell December comparison


def read_store(ds, store, t):
    names, layer = STORES[store]
    out, units = None, None
    for n in names:
        v = ds.variables[n]
        units = v.getncattr('units')
        a = v[t] if layer is None else v[t, layer]
        a = np.ma.filled(np.ma.masked_invalid(a).astype('f8'), 0.0)
        a[np.abs(a) > 1e30] = 0.0
        out = a if out is None else out + a
    return out, units


def km3(a, units, area):
    if units == 'hm3':
        return float(a.sum()) / 1e3
    return float((a * area).sum()) * 1e-12     # mm x m2 = 1e-3 m3; 1 km3 = 1e9 m3


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run', default='smoke2011-2020')
    a = ap.parse_args()
    W = csp.workdir()
    rd = f'{W}/{csp.SMOKE_RUNS[a.run]}'
    res = yaml.safe_load(open(f'{rd}/config/resolved.yaml'))
    with netCDF4.Dataset(f'{W}/{res["parameters"]["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool)
        lat = np.asarray(d['lat'][:], 'f8'); lon = np.asarray(d['lon'][:], 'f8')
        area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
    files = sorted(glob.glob(f'{rd}/output/monthly.*-01.nc'))
    years = [int(os.path.basename(f)[8:12]) for f in files]
    monthly, dec = [], {s: [] for s in CELL_STORES}
    totals = {s: {} for s in STORES}
    for y, f in zip(years, files):
        with netCDF4.Dataset(f) as ds:
            ds.set_auto_mask(True)
            nt = len(ds.dimensions['time'])
            for s in STORES:
                vals = []
                for t in range(nt):
                    arr, units = read_store(ds, s, t)
                    vals.append(km3(arr, units, area))
                    monthly.append(dict(year=y, month=t + 1, store=s, km3=round(vals[-1], 3)))
                    if t == nt - 1 and s in CELL_STORES:
                        dec[s].append(arr.astype('f4'))
                totals[s][y] = (vals[-1], float(np.mean(vals)), units)
        print(f'{y} read', flush=True)

    rows = []
    w = area / area.sum()
    for s in STORES:
        for i, y in enumerate(years):
            d_km3, ann_km3, units = totals[s][y]
            r = dict(store=s, year=y, units_in_file=units, december_km3=round(d_km3, 3), annual_mean_km3=round(ann_km3, 3),
                     december_change_km3=round(d_km3 - totals[s][years[i - 1]][0], 3) if i else '',
                     mean_abs_cell_change_mm='', mean_abs_cell_change_pct_of_depth='', same_direction_share='',
                     same_direction_km3_per_year='')
            if s in CELL_STORES and i:
                cur, prev = dec[s][i].astype('f8'), dec[s][i - 1].astype('f8')
                depth = float((w * cur).sum())
                mac = float((w * np.abs(cur - prev)).sum())
                r['mean_abs_cell_change_mm'] = round(mac, 4)
                r['mean_abs_cell_change_pct_of_depth'] = round(100 * mac / depth, 4) if depth else ''
            rows.append(r)
        if s in CELL_STORES and len(years) >= 4:
            # cells that rose (or fell) in every year from the second December on: steady drift, not weather
            dd = np.diff(np.stack(dec[s][1:]).astype('f8'), axis=0)
            up = mask & np.all(dd > 1e-6, axis=0); down = mask & np.all(dd < -1e-6, axis=0)
            share = float(area[up | down].sum() / area.sum())
            rate = float((np.where(up | down, dd.mean(axis=0), 0.0) * area).sum()) * 1e-12
            if s == 'snow':
                # where snow accumulates without limit (no glacier model): 10-degree boxes
                la, lo = np.meshgrid(lat, lon, indexing='ij')
                box = {}
                for i, j in zip(*np.nonzero(up)):
                    k = (int(np.floor(la[i, j] / 10) * 10), int(np.floor(lo[i, j] / 10) * 10))
                    b = box.setdefault(k, [0, 0.0, 0.0, 0.0])
                    b[0] += 1; b[1] += area[i, j] / 1e6; b[2] += dd[:, i, j].mean() * area[i, j] * 1e-12
                    b[3] = max(b[3], float(dec[s][-1][i, j]))
                sr = [dict(lat_south=k[0], lon_west=k[1], cells=v[0], area_km2=round(v[1]), km3_per_year=round(v[2], 3),
                           max_december_2020_swe_mm=round(v[3])) for k, v in box.items()]
                sr.sort(key=lambda r: -r['km3_per_year'])
                with open(f'{csp.tables()}/drift_snow_regions.csv', 'w', newline='') as fh:
                    cw = csv.DictWriter(fh, fieldnames=list(sr[0])); cw.writeheader(); cw.writerows(sr)
            for r in rows:
                if r['store'] == s and r['year'] == years[-1]:
                    r['same_direction_share'] = round(share, 4)
                    r['same_direction_km3_per_year'] = round(rate, 3)
                    r['rising_share'] = round(float(area[up].sum() / area.sum()), 4)
    with open(f'{csp.tables()}/drift_global_monthly.csv', 'w', newline='') as fh:
        cw = csv.DictWriter(fh, fieldnames=list(monthly[0])); cw.writeheader(); cw.writerows(monthly)
    fields = list(rows[0]) + ['rising_share']
    with open(f'{csp.tables()}/drift_annual.csv', 'w', newline='') as fh:
        cw = csv.DictWriter(fh, fieldnames=fields); cw.writeheader(); cw.writerows(rows)

    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.2))
    for s in STORES:
        v = np.array([totals[s][y][0] for y in years])
        a1.plot(years, v - v[-1], marker='o', ms=3, label=s)
    a1.axhline(0, color='k', lw=0.5)
    a1.set_ylabel('December total minus December 2020 (km3)')
    a1.set_title('Global stores after a cold start (2011-2020)', fontsize=9, loc='left')
    a1.legend(fontsize=7, ncol=2)
    for s in CELL_STORES:
        p = [r['mean_abs_cell_change_pct_of_depth'] for r in rows if r['store'] == s and r['year'] != years[0]]
        a2.plot(years[1:], p, marker='o', ms=3, label=s)
    a2.set_yscale('log')
    a2.set_ylabel('mean |December change| per cell, % of mean depth')
    a2.set_title('Year-to-year change per cell (relaxation + weather)', fontsize=9, loc='left')
    a2.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(f'{csp.figures()}/spinup_drift.png', dpi=130)
    print('wrote drift tables and figure')


if __name__ == '__main__':
    main()
