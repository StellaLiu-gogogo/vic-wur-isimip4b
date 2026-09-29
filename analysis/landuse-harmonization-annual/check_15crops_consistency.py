#!/usr/bin/env python
"""
15crops checks (one streamed pass per file, 12 time steps at a time):
 (a) 2021: sum(*_rainfed*) and sum(*_irrigated*) of 15crops vs 5crops vs landuse-totals cropland_rainfed/irrigated (cell-wise max |diff|)
 (b) rice_irrigated <= sum(*_irrigated*) cell-wise for every year of every scenario
 (c) annual global totals (km2) per VIC class: 12 = sum rainfed (incl. rice_rainfed, *_rainfed_food, *_rainfed_bf), 15 = rice_irrigated,
     14 = sum irrigated - rice_irrigated; plus _bf totals, rice_rainfed totals, pastures
 (d) per-class time maximum, first positive year and scenario bitmask (union) on the ISIMIP grid -> union_15crops.npz
Inputs: 03Data/raw_dkrz/InputData/socioeconomic/landuse/{histsoc,1850soc,2021soc,ssp1vlsoc-noadapt,ssp3hsoc-noadapt}/landuse-15crops_*_15arcmin_*.nc
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python check_15crops_consistency.py
"""
import os, json, time, numpy as np, netCDF4 as nc
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v
t0 = time.time(); OUT = f'{WORKDIR}/analysis/landuse-harmonization-annual'; os.makedirs(OUT, exist_ok=True)
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
F15 = {'histsoc': (f'{RAW}/histsoc/landuse-15crops_histsoc_15arcmin_annual_1850_2021.nc', 1850), '1850soc': (f'{RAW}/1850soc/landuse-15crops_1850soc_15arcmin_annual_1850_2021.nc', 1850),
       '2021soc': (f'{RAW}/2021soc/landuse-15crops_2021soc_15arcmin_annual_2022_2100.nc', 2022), 'ssp1vl': (f'{RAW}/ssp1vlsoc-noadapt/landuse-15crops_ssp1vl_15arcmin_annual_2022_2100.nc', 2022),
       'ssp3h': (f'{RAW}/ssp3hsoc-noadapt/landuse-15crops_ssp3h_15arcmin_annual_2022_2100.nc', 2022)}
F5 = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc'
FT = f'{RAW}/histsoc/landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'
R = 6371000.0
d0 = nc.Dataset(F15['histsoc'][0]); lat = d0['lat'][:]; lon = d0['lon'][:]
A = ((R ** 2) * np.deg2rad(0.25) * (np.sin(np.deg2rad(lat + 0.125)) - np.sin(np.deg2rad(lat - 0.125))))[:, None] * np.ones((1, lon.size))
VARS = [v for v in d0.variables if v not in ('time', 'lat', 'lon')]
RF = [v for v in VARS if '_rainfed' in v]; IR = [v for v in VARS if '_irrigated' in v]; BF = [v for v in VARS if v.endswith('_bf')]
res = {'grid': {'nlat': int(lat.size), 'nlon': int(lon.size), 'lat0': float(lat[0]), 'lat1': float(lat[-1]), 'lon0': float(lon[0]), 'lon1': float(lon[-1]), 'calendar': d0['time'].calendar, 'time_units': d0['time'].units},
       'variables': VARS, 'n_vars': len(VARS), 'rainfed_vars_class12': RF, 'irrigated_vars': IR, 'paddy_var_class15': 'rice_irrigated', 'bf_vars': BF, 'fill': float(d0['rice_irrigated']._FillValue), 'units': d0['rice_irrigated'].units,
       'comment': d0.comment, 'source': d0.source}
# (a) 2021 three-way consistency
t21 = 171
rf15 = sum(d0[v][t21].filled(0).astype('f8') for v in RF); ir15 = sum(d0[v][t21].filled(0).astype('f8') for v in IR); fill15 = np.ma.getmaskarray(d0['rice_irrigated'][t21])
d5 = nc.Dataset(F5); rf5 = sum(d5[v][t21].filled(0).astype('f8') for v in d5.variables if 'rainfed' in v); ir5 = sum(d5[v][t21].filled(0).astype('f8') for v in d5.variables if 'irrigated' in v); fill5 = np.ma.getmaskarray(d5['c3ann_irrigated'][t21])
dt = nc.Dataset(FT); rft = dt['cropland_rainfed'][t21].filled(0).astype('f8'); irt = dt['cropland_irrigated'][t21].filled(0).astype('f8'); fillt = np.ma.getmaskarray(dt['cropland_rainfed'][t21])
res['consistency_2021'] = {'same_grid_5crops': bool(np.allclose(d5['lat'][:], lat) and np.allclose(d5['lon'][:], lon)), 'same_grid_totals': bool(np.allclose(dt['lat'][:], lat)), 'same_time_axis_5crops': bool(np.allclose(d5['time'][:], d0['time'][:])),
                           'fill_masks_identical': bool((fill15 == fill5).all() and (fill15 == fillt).all()), 'fill_cells': int(fill15.sum()),
                           'rainfed_max_abs_diff_15_vs_5': float(np.abs(rf15 - rf5).max()), 'rainfed_max_abs_diff_15_vs_totals': float(np.abs(rf15 - rft).max()), 'rainfed_max_abs_diff_5_vs_totals': float(np.abs(rf5 - rft).max()),
                           'irrigated_max_abs_diff_15_vs_5': float(np.abs(ir15 - ir5).max()), 'irrigated_max_abs_diff_15_vs_totals': float(np.abs(ir15 - irt).max()), 'irrigated_max_abs_diff_5_vs_totals': float(np.abs(ir5 - irt).max()),
                           'global_Mkm2_2021': {'rainfed_15crops': float((rf15 * A).sum() * 1e-12), 'rainfed_5crops': float((rf5 * A).sum() * 1e-12), 'rainfed_totals': float((rft * A).sum() * 1e-12),
                                                'irrigated_15crops': float((ir15 * A).sum() * 1e-12), 'irrigated_5crops': float((ir5 * A).sum() * 1e-12), 'irrigated_totals': float((irt * A).sum() * 1e-12),
                                                'rice_irrigated_15crops': float((d0['rice_irrigated'][t21].filled(0).astype('f8') * A).sum() * 1e-12), 'rice_rainfed_15crops': float((d0['rice_rainfed'][t21].filled(0).astype('f8') * A).sum() * 1e-12),
                                                'irrigated_nonpaddy_15crops': float(((ir15 - d0['rice_irrigated'][t21].filled(0).astype('f8')) * A).sum() * 1e-12)}}
# (b)(c)(d) streamed
series = {}; union = {}
for sc, (fn, y0) in F15.items():
    d = nc.Dataset(fn); n = len(d['time']); ys = list(range(y0, y0 + n))
    g = {'years': ys, 'rf_km2': [], 'irr_km2': [], 'paddy_km2': [], 'nonpaddy_km2': [], 'bf_km2': [], 'rice_rainfed_km2': [], 'pastures_km2': []}
    viol = 0; viol_max = 0.0; tmax = np.zeros((3, lat.size, lon.size)); fy = np.full((3, lat.size, lon.size), 9999, np.int16)
    for a in range(0, n, 12):
        b = min(n, a + 12)
        rf = sum(d[v][a:b].filled(0).astype('f8') for v in RF); ir = sum(d[v][a:b].filled(0).astype('f8') for v in IR); rc = d['rice_irrigated'][a:b].filled(0).astype('f8')
        bf = sum(d[v][a:b].filled(0).astype('f8') for v in BF); rr = d['rice_rainfed'][a:b].filled(0).astype('f8'); pa = d['pastures'][a:b].filled(0).astype('f8')
        npd = ir - rc; ex = rc - ir; viol += int((ex > 1e-6).sum()); viol_max = max(viol_max, float(ex.max()))
        for k, x in (('rf_km2', rf), ('irr_km2', ir), ('paddy_km2', rc), ('nonpaddy_km2', np.maximum(npd, 0)), ('bf_km2', bf), ('rice_rainfed_km2', rr), ('pastures_km2', pa)): g[k] += ((x * A).sum(axis=(1, 2)) * 1e-6).tolist()
        for k, x in enumerate((rf, np.maximum(npd, 0), rc)):
            tmax[k] = np.maximum(tmax[k], x.max(axis=0)); pos = x > 0
            first = np.where(pos.any(axis=0), y0 + a + pos.argmax(axis=0), 9999); fy[k] = np.minimum(fy[k], first)
    series[sc] = g; union[sc] = (tmax, fy)
    res[f'rice_le_irrigated_{sc}'] = {'cells_years_violating_gt_1e-6': viol, 'max_excess_fraction': viol_max}
    d.close(); print(sc, 'done', round(time.time() - t0), 's', flush=True)
# union over the 4 scenario files (1850soc == histsoc 1850 per DKRZ check; kept as separate bit)
bits = {'histsoc': 1, '1850soc': 2, '2021soc': 4, 'ssp1vl': 8, 'ssp3h': 16}
U = np.zeros((3, lat.size, lon.size)); FY = np.full((3, lat.size, lon.size), 9999, np.int16); SRC = np.zeros((3, lat.size, lon.size), np.uint8)
for sc, (tmax, fy) in union.items():
    U = np.maximum(U, tmax); FY = np.minimum(FY, fy)
    for k in range(3): SRC[k] |= ((tmax[k] > 0).astype(np.uint8) * bits[sc])
np.savez_compressed(f'{OUT}/union_15crops.npz', U=U.astype('f4'), FY=FY, SRC=SRC, lat=lat, lon=lon, classes=np.array(['12_rainfed', '14_irr_nonpaddy', '15_paddy']))
res['union_parents_pos'] = {c: int((U[k] > 0).sum()) for k, c in enumerate(('12_rainfed', '14_irr_nonpaddy', '15_paddy'))}
res['union_parents_pos_by_scenario'] = {sc: {c: int((union[sc][0][k] > 0).sum()) for k, c in enumerate(('12', '14', '15'))} for sc in union}
res['annual_series'] = series
res['bf_totals_Mkm2'] = {sc: {'max_over_years': max(series[sc]['bf_km2']) * 1e-6, 'year_2100_or_last': series[sc]['bf_km2'][-1] * 1e-6} for sc in series}
res['runtime_s'] = time.time() - t0
json.dump(res, open(f'{OUT}/check_15crops_consistency.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ('annual_series', 'variables', 'comment')}, indent=1))
