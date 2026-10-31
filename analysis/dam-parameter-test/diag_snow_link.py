# Temporary diagnosis (task L5): are the cells that differ on 2016-01-01 the cells with snow and fresh snowfall on the
# last step of 2015 (lu_support.c calculate_derived_water_states: new snow density from force->air_temp, i.e. the
# first local cell of the rank, instead of force[iCell])?
import os

import numpy as np
from netCDF4 import Dataset
W = os.environ['ISIMIP4B_WORKDIR']
S = 'ec-earth3-esm-1-1_historical_histsoc_default_historical'
A = f'{W}/runs/dam-test/{S}__ranks8-2015-2016'; B = f'{W}/runs/dam-test/{S}__ranks16-2015-2016'

def read(path, var, t):
    with Dataset(path) as d:
        d.set_auto_mask(False); v = d[var]
        t = t if t >= 0 else v.shape[0] + t
        x = np.asarray(v[t], 'f8'); fv = getattr(v, '_FillValue', None)
    if fv is not None: x[x == fv] = np.nan
    x[np.abs(x) > 1e30] = np.nan
    return x

for var in ('OUT_RUNOFF', 'OUT_BASEFLOW'):
    x = read(f'{A}/output/daily.2016-01-01.nc', var, 0); y = read(f'{B}/output/daily.2016-01-01.nc', var, 0)
    land = np.isfinite(x); D = land & (x != y)
    swe = read(f'{A}/output/monthly.2015-01.nc', 'OUT_SWE', 11)          # December 2015 mean
    prec = read(f'{A}/forcing/climate/prec/prec_ec-earth3-esm-1-1_esm-hist_2015.nc', 'prec', -1)
    tair = read(f'{A}/forcing/climate/tair/tair_ec-earth3-esm-1-1_esm-hist_2015.nc', 'tair', -1)
    if np.nanmedian(tair) > 100: tair = tair - 273.15
    snowfall = (prec > 0) & (tair < 0.5)
    print(f'{var}: active {land.sum()}, differing on 2016-01-01 {D.sum()}')
    for name, sel in (('snow Dec 2015 and snowfall 31 Dec', (swe > 0) & snowfall),
                      ('snow Dec 2015, no snowfall 31 Dec', (swe > 0) & ~snowfall),
                      ('no snow Dec 2015, snowfall 31 Dec', ~(swe > 0) & snowfall),
                      ('no snow, no snowfall', ~(swe > 0) & ~snowfall)):
        sel = sel & land
        print(f'  {name:36s}: cells {sel.sum():8d}, differing {(sel & D).sum():6d} '
              f'({(sel & D).sum() / max(sel.sum(), 1):.4f}); share of all differing {(sel & D).sum() / D.sum():.3f}')
