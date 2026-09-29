#!/usr/bin/env python
"""
2021 paddy comparison: ISIMIP4b landuse-15crops `rice_irrigated` (fraction of whole 15' cell x spherical area) vs VIC-WUR
coverage_VersionA_v5_2021 class 15 irrigated_paddy_crop (5' fraction x spherical area x mask, 3x3 sum). Same framework and
thresholds as evidence/irrigated_area_comparison_5crops_15arcmin/compare_irrigated_area.py (presence > 1 km2, approx equal
|D| <= max(1 km2, 5 % max)). Also non-paddy (class 14 vs sum irrigated - rice_irrigated) for completeness.
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python compare_paddy_2021.py
"""
import os, json, numpy as np, netCDF4 as nc
from scipy import stats as sstats
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib import colors as mcolors; from matplotlib.patches import Patch
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v
OUT = f'{WORKDIR}/analysis/landuse-harmonization-annual'; os.makedirs(OUT, exist_ok=True); FIG = f'{OUT}/figures'
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
F15 = f'{RAW}/histsoc/landuse-15crops_histsoc_15arcmin_annual_1850_2021.nc'
F_COV = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_2021.nc'
F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
R = 6371000.0; KM2 = 1e-6; THR = 1.0; TOL = 0.05
dom = nc.Dataset(F_DOM); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool)
A5 = ((R ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, vlon.size)); land = np.where(mask, A5, 0.0)
def agg(f5):  # 5' (S->N) -> 15' ISIMIP grid rows 24..583 (N->S)
    b = f5.reshape(560, 3, 1440, 3).sum(axis=(1, 3))[::-1]; out = np.zeros((720, 1440)); out[24:584] = b; return out
d = nc.Dataset(F15); ilat = d['lat'][:]; ilon = d['lon'][:]; t = 171
A15 = ((R ** 2) * np.deg2rad(0.25) * (np.sin(np.deg2rad(ilat + 0.125)) - np.sin(np.deg2rad(ilat - 0.125))))[:, None] * np.ones((1, 1440))
rice = d['rice_irrigated'][t]; fill = np.ma.getmaskarray(rice); rice = rice.filled(0).astype('f8')
irr = sum(d[v][t].filled(0).astype('f8') for v in d.variables if '_irrigated' in v)
cov = nc.Dataset(F_COV)['coverage'][0]; c14 = np.nan_to_num(cov[13].filled(np.nan)) * land; c15 = np.nan_to_num(cov[14].filled(np.nan)) * land
L15 = agg(land); common = (~fill) & (L15 > 0)
def metrics(Av, Ai, sel):
    av = Av[sel] * KM2; ai = Ai[sel] * KM2; dd = av - ai; o = np.minimum(av, ai); u = np.maximum(av, ai); tv, ti = av.sum(), ai.sum()
    pv = av > THR; pi = ai > THR; tol = np.maximum(1.0, TOL * u); either = pv | pi
    m = {'VIC_total_km2': tv, 'ISIMIP_total_km2': ti, 'diff_pct_of_ISIMIP': 100 * (tv - ti) / ti, 'sum_min_km2': o.sum(), 'overlap_over_VIC': o.sum() / tv, 'overlap_over_ISIMIP': o.sum() / ti,
         'IoU': o.sum() / u.sum(), 'Dice': 2 * o.sum() / (tv + ti), 'VIC_excess_km2': np.maximum(dd, 0).sum(), 'ISIMIP_excess_km2': np.maximum(-dd, 0).sum(),
         'cells_VIC_only': int((pv & ~pi).sum()), 'area_VIC_only_km2': av[pv & ~pi].sum(), 'cells_ISIMIP_only': int((~pv & pi).sum()), 'area_ISIMIP_only_km2': ai[~pv & pi].sum(),
         'cells_both': int((pv & pi).sum()), 'cells_both_VIC_larger': int((pv & pi & (dd > tol)).sum()), 'cells_both_ISIMIP_larger': int((pv & pi & (dd < -tol)).sum()), 'cells_both_approx_equal': int((pv & pi & (np.abs(dd) <= tol)).sum()),
         'pearson_r_either': float(np.corrcoef(av[either], ai[either])[0, 1]), 'spearman_either': float(sstats.spearmanr(av[either], ai[either]).correlation),
         'MAE_km2_either': float(np.abs(dd[either]).mean()), 'median_abs_diff_km2_either': float(np.median(np.abs(dd[either]))), 'cells_VIC_gt0': int((av > 0).sum()), 'cells_ISIMIP_gt0': int((ai > 0).sum())}
    return m
res = {'inputs': {'ISIMIP': f'{F15} rice_irrigated (paddy) and sum(*_irrigated*) - rice_irrigated (non-paddy), year 2021, fraction of whole cell x spherical area', 'VIC': f'{F_COV} classes 15 / 14 x spherical 5arcmin area x mask, 3x3 sum', 'units': 'km2', 'presence_thr_km2': THR, 'equal_tol': f'max(1 km2, {TOL} x max)'},
       'paddy_class15': metrics(agg(c15), rice * A15, common), 'nonpaddy_class14': metrics(agg(c14), (irr - rice) * A15, common),
       'paddy_share_of_irrigated_global': {'ISIMIP_15crops': float((rice * A15).sum() / (irr * A15).sum()), 'VIC_v5_2021': float(c15.sum() / (c14.sum() + c15.sum()))}}
json.dump(res, open(f'{OUT}/compare_paddy_2021.json', 'w'), indent=1, default=float); print(json.dumps(res, indent=1, default=float))
# figure: category map + scatter for paddy
Av = agg(c15) * KM2; Ai = rice * A15 * KM2; dd = Av - Ai; pv = Av > THR; pi = Ai > THR; tol = np.maximum(1, TOL * np.maximum(Av, Ai))
cat = np.zeros(Av.shape, np.int8); cat[pv & ~pi] = 1; cat[~pv & pi] = 2; cat[pv & pi & (dd > tol)] = 3; cat[pv & pi & (dd < -tol)] = 4; cat[pv & pi & (np.abs(dd) <= tol)] = 5; cat[~common] = 0
cols = {1: '#E69F00', 2: '#0072B2', 3: '#D55E00', 4: '#56B4E9', 5: '#009E73'}; lab = {1: 'VIC only', 2: 'ISIMIP only', 3: 'both, VIC larger', 4: 'both, ISIMIP larger', 5: 'both, ≈ equal'}
fig = plt.figure(figsize=(14, 9)); gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1])
ax = fig.add_subplot(gs[0, :]); ax.set_xlim(-180, 180); ax.set_ylim(-45, 60); ax.set_facecolor('#f4f4f4'); ax.contour(ilon, ilat, (~fill).astype(int), levels=[0.5], colors='#777', linewidths=0.25)
ax.imshow(np.where(cat > 0, cat, np.nan), extent=[-180, 180, -90, 90], origin='upper', cmap=mcolors.ListedColormap([cols[k] for k in (1, 2, 3, 4, 5)]), norm=mcolors.BoundaryNorm([.5, 1.5, 2.5, 3.5, 4.5, 5.5], 5), interpolation='nearest')
cnt = {k: int((cat == k).sum()) for k in cols}; ax.legend(handles=[Patch(color=cols[k], label=f'{lab[k]} ({cnt[k]:,})') for k in cols], loc='lower left', fontsize=8)
m = res['paddy_class15']; ax.set_title(f'Paddy 2021: VIC class 15 ({m["VIC_total_km2"]/1e6:.3f} Mkm²) vs ISIMIP 15crops rice_irrigated ({m["ISIMIP_total_km2"]/1e6:.3f} Mkm²); IoU {m["IoU"]:.3f}, Dice {m["Dice"]:.3f}', loc='left', fontsize=10)
sel = common & ((Av > 0) | (Ai > 0)); ax2 = fig.add_subplot(gs[1, 0]); hb = ax2.hexbin(np.log1p(Ai[sel]), np.log1p(Av[sel]), gridsize=60, bins='log', cmap='Blues', mincnt=1); mx = max(np.log1p(Ai[sel]).max(), np.log1p(Av[sel]).max()); ax2.plot([0, mx], [0, mx], 'k--', lw=1); ax2.set_xlabel('ISIMIP rice_irrigated log1p(km²)'); ax2.set_ylabel('VIC class 15 log1p(km²)'); ax2.set_title('cells with either > 0', loc='left', fontsize=9)
ax3 = fig.add_subplot(gs[1, 1]); s = np.sort(dd[sel]); ax3.plot(s, np.arange(1, s.size + 1) / s.size, color='#0072B2'); ax3.set_xscale('symlog', linthresh=10); ax3.axvline(0, color='grey', lw=0.8); ax3.set_xlabel('VIC − ISIMIP paddy (km² per cell, symlog)'); ax3.set_ylabel('ECDF'); ax3.set_title('difference ECDF', loc='left', fontsize=9)
fig.text(0.01, 0.005, f'inputs: {os.path.basename(F15)} rice_irrigated 2021 x 15arcmin spherical area; coverage_VersionA_v5_2021.nc class 15 x 5arcmin area x mask, 3x3 sum; km2; presence > 1 km2', fontsize=7, color='#555')
fig.tight_layout(); fig.savefig(f'{FIG}/p01_paddy_2021_vic_vs_isimip15crops.png', dpi=150); plt.close(fig)
