# Temporary diagnosis (task L5): size of the effect of the snow-density defect in 2016.
# Corrected ranks8 (snow-density-test) against the original ranks8 (dam-test); for scale, original ranks8 against
# original ranks16 (both with the defect, different first cells).
import os

import numpy as np
from netCDF4 import Dataset
W = os.environ['ISIMIP4B_WORKDIR']
S = 'ec-earth3-esm-1-1_historical_histsoc_default_historical'
FIX = f'{W}/runs/snow-density-test/{S}__ranks8-2015-2016'
O8 = f'{W}/runs/dam-test/{S}__ranks8-2015-2016'
O16 = f'{W}/runs/dam-test/{S}__ranks16-2015-2016'
PAIRS = (('corrected - original (ranks8)', FIX, O8), ('original ranks8 - original ranks16', O8, O16))


def read(run, var):
    with Dataset(f'{run}/output/monthly.2016-01.nc') as d:
        d.set_auto_mask(False); v = d[var]
        x = np.asarray(v[:], 'f8'); fv = getattr(v, '_FillValue', None)
        lat = np.asarray(d['lat'][:], 'f8'); lon = np.asarray(d['lon'][:], 'f8')
    if fv is not None: x[x == fv] = np.nan
    x[np.abs(x) > 1e30] = np.nan
    return x, lat, lon


def area(lat, lon):
    r = 6371.0e3; dlat = np.deg2rad(abs(lat[1] - lat[0])); dlon = np.deg2rad(abs(lon[1] - lon[0]))
    return (r * r * dlat * dlon * np.cos(np.deg2rad(lat)))[:, None] * np.ones(lon.size)[None, :]


def counts(d, thresholds, unit):
    return ', '.join(f'>{t:g}{unit}: {(d > t).sum()}' for t in thresholds)


for name, a, b in PAIRS:
    print(f'=== {name}')
    ro = {}
    for run in (a, b):
        r, lat, lon = read(run, 'OUT_RUNOFF'); bf, _, _ = read(run, 'OUT_BASEFLOW')
        ro[run] = np.sum(r + bf, axis=0)
    A = area(lat, lon); land = np.isfinite(ro[a])
    print('active cells', land.sum())
    for var, total in (('runoff+baseflow', ro), ('OUT_EVAP', None)):
        if total is None:
            total = {run: np.sum(read(run, var)[0], axis=0) for run in (a, b)}
        d = (total[a] - total[b])[land]; rel = np.abs(d) / np.maximum(np.abs(total[b][land]), 1.0)
        g = [np.nansum(total[run][land] * A[land]) * 1e-3 * 1e-9 for run in (a, b)]  # km3
        print(f'{var} 2016 annual (mm): cells differing {(d != 0).sum()}; |diff| {counts(np.abs(d), (0.1, 1, 5, 20), " mm")}; '
              f'relative {counts(rel, (0.001, 0.01, 0.05), "")}')
        print(f'  |diff| quantiles 50/90/99/99.9/100 % of differing cells (mm): '
              f'{np.percentile(np.abs(d[d != 0]), [50, 90, 99, 99.9, 100]).round(4)}')
        print(f'  global total km3: {g[0]:.2f} vs {g[1]:.2f} (difference {g[0] - g[1]:+.3f}, {100 * (g[0] - g[1]) / g[1]:+.4f} %)')
    swe = [read(run, 'OUT_SWE')[0] for run in (a, b)]
    d = np.nanmax(np.abs(swe[0] - swe[1]), axis=0)[land]
    print(f'OUT_SWE largest monthly |diff| per cell: {counts(d, (0.1, 1, 10), " mm")}')
    q = [read(run, 'OUT_DISCHARGE')[0] for run in (a, b)]
    qm = np.mean(q[1], axis=0)
    big = land & (qm > 10)
    rel_m = np.nanmax(np.abs(q[0] - q[1]) / np.maximum(q[1], 1.0), axis=0)[big]
    rel_y = (np.abs(np.mean(q[0], axis=0) - qm) / qm)[big]
    print(f'OUT_DISCHARGE, {big.sum()} cells with 2016 mean > 10 m3/s: annual mean relative {counts(rel_y, (0.001, 0.01, 0.05), "")}; '
          f'largest monthly relative {counts(rel_m, (0.001, 0.01, 0.05), "")}')
    print(f'  annual mean relative diff quantiles 50/90/99/100 %: {np.percentile(rel_y, [50, 90, 99, 100])}')
