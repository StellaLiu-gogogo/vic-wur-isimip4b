# Temporary diagnosis (task L5): what do the cells that differ on 2016-01-01 between ranks8 and ranks16 have in common?
import os

import numpy as np
from netCDF4 import Dataset
W = os.environ['ISIMIP4B_WORKDIR']
S = 'ec-earth3-esm-1-1_historical_histsoc_default_historical'
A = f'{W}/runs/dam-test/{S}__ranks8-2015-2016'; B = f'{W}/runs/dam-test/{S}__ranks16-2015-2016'

def read(path, var, t=0):
    with Dataset(path) as d:
        d.set_auto_mask(False); v = d[var]
        x = np.asarray(v[t], 'f8'); fv = getattr(v, '_FillValue', None)
    if fv is not None: x[x == fv] = np.nan
    x[np.abs(x) > 1e30] = np.nan
    return x

x = read(f'{A}/output/daily.2016-01-01.nc', 'OUT_RUNOFF'); y = read(f'{B}/output/daily.2016-01-01.nc', 'OUT_RUNOFF')
land = np.isfinite(x)
D = land & (x != y)
print('active cells', land.sum(), 'differing day 1', D.sum())
rel = np.abs(x - y)[D] / np.maximum(np.abs(x[D]), 1e-12)
print('relative difference quantiles 0/10/50/90/100 %:', np.percentile(rel, [0, 10, 50, 90, 100]))
print('absolute difference quantiles (mm):', np.percentile(np.abs(x - y)[D], [0, 10, 50, 90, 100]))
cov = []
for yr in (2015, 2016):
    with Dataset(f'{B}/forcing/landuse/coverage_histsoc_{yr}.nc') as d:
        d.set_auto_mask(False); c = np.asarray(d['coverage'][0], 'f8')
    c[np.abs(c) > 1e30] = np.nan; cov.append(c)
s0 = np.nansum(cov[0], axis=0); s1 = np.nansum(cov[1], axis=0)
dc = np.nanmax(np.abs(cov[1] / np.where(s1 > 0, s1, 1) - cov[0] / np.where(s0 > 0, s0, 1)), axis=0)
for lo, hi in ((-1, 0), (0, 1e-5), (1e-5, 1e-3), (1e-3, 1e-2), (1e-2, 2)):
    sel = land & (dc > lo) & (dc <= hi)
    print(f'cover change ({lo:g}, {hi:g}]: cells {sel.sum():8d}, differing {(sel & D).sum():6d} ({(sel & D).sum() / max(sel.sum(), 1):.4f})')
swe = read(f'{A}/output/monthly.2015-12.nc', 'OUT_SWE')
for name, sel in (('SWE Dec 2015 = 0', land & (swe == 0)), ('SWE Dec 2015 > 0', land & (swe > 0))):
    print(f'{name}: cells {sel.sum():8d}, differing {(sel & D).sum():6d} ({(sel & D).sum() / max(sel.sum(), 1):.4f})')
ch = land & (dc > 1e-5)
for name, sel in (('change & snow', ch & (swe > 0)), ('change & no snow', ch & (swe == 0)),
                  ('no change & snow', ~ch & land & (swe > 0)), ('no change & no snow', ~ch & land & (swe == 0))):
    print(f'{name}: cells {sel.sum():8d}, differing {(sel & D).sum():6d} ({(sel & D).sum() / max(sel.sum(), 1):.4f})')
with Dataset(f'{A}/output/daily.2016-01-01.nc') as d:
    lat = np.asarray(d['lat'][:])
rr, cc = np.nonzero(D)
h, e = np.histogram(lat[rr], bins=[-90, -30, 0, 20, 30, 40, 50, 60, 90])
print('differing cells by latitude band', dict(zip([f'{a}..{b}' for a, b in zip(e[:-1], e[1:])], h.tolist())))
