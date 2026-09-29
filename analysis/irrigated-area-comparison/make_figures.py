#!/usr/bin/env python
"""Figures for the VIC-WUR vs ISIMIP4b (landuse-5crops) irrigated-area comparison.
Reads cellwise_comparison.nc and the CSV tables written by compare_irrigated_area.py; writes figures/*.png.
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python make_figures.py
Colour rules: sequential = one hue (Blues / Oranges); diverging = two hues + neutral midpoint (RdBu-like, symlog);
categorical = fixed Okabe-Ito order; areas in km2 per 15' cell; symlog colour scales so that the few very large cells
do not hide the bulk of the distribution (no value is clipped: the top of the scale equals the data maximum).
"""
import os, numpy as np, netCDF4 as nc, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.patches import Patch
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v
OUT = f'{WORKDIR}/analysis/irrigated-area-comparison'; os.makedirs(OUT, exist_ok=True); FIG = f'{OUT}/figures'; os.makedirs(FIG, exist_ok=True)
plt.rcParams.update({'font.size': 9, 'axes.titlesize': 10, 'figure.dpi': 110})

d = nc.Dataset(f'{OUT}/cellwise_comparison.nc')
lat = d['lat'][:]; lon = d['lon'][:]
def V(n):
    a = d[n][:]
    if np.ma.isMaskedArray(a): return a.filled(np.nan) if a.dtype.kind == 'f' else a.filled(-1)
    return np.asarray(a)
Ai = V('A_isimip'); Av = V('A_vic'); D = V('D'); cat = V('category'); ratio = V('overlap_ratio'); common = V('common_valid') == 1
valid = V('isimip_valid') == 1; L = V('L_vic'); reg_id = V('region_id')
snap_years = d['snapshot_year'][:]; snaps = d['A_isimip_snapshots'][:].filled(np.nan)
src_i = 'ISIMIP4b landuse-5crops_histsoc_15arcmin 2021, sum of 7 *_irrigated* fractions x full-cell area'
src_v = 'VIC-WUR coverage_VersionA_v5_2021 classes 14+15 x 5arcmin area, 3x3 sum'
EXT = [-180, 180, -90, 90]; YL = (-60, 85)
land_outline = np.where(valid, 1, 0)

def base(ax, title):
    ax.set_xlim(-180, 180); ax.set_ylim(*YL); ax.set_title(title, loc='left'); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
    ax.contour(lon, lat, land_outline, levels=[0.5], colors='#777777', linewidths=0.25)
    ax.set_facecolor('#f4f4f4')

def cite(fig, txt):
    fig.text(0.01, 0.005, txt, fontsize=6.5, color='#555555', ha='left', va='bottom')

vmax = np.nanmax([np.nanmax(Ai), np.nanmax(Av)])
snorm = mcolors.SymLogNorm(linthresh=10, linscale=0.5, vmin=0, vmax=vmax)
# 1/2 area maps
for name, A, ttl, cmap, src in (('fig01_isimip_irrigated_area_2021_15arcmin', Ai, 'ISIMIP4b (LUH3, landuse-5crops) irrigated cropland area 2021, km² per 15′ cell', 'Blues', src_i),
                                ('fig02_vic_irrigated_area_2021_15arcmin', Av, 'VIC-WUR Version-A (classes 14+15) irrigated cropland area 2021, aggregated 5′→15′, km² per cell', 'Oranges', src_v)):
    fig, ax = plt.subplots(figsize=(12, 5.6)); base(ax, ttl)
    im = ax.imshow(np.where(A > 0, A, np.nan), extent=EXT, origin='upper', cmap=cmap, norm=snorm, interpolation='nearest')
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, extend='neither'); cb.set_label('km² per cell (symlog, linear below 10 km²; max = data max, nothing clipped)')
    tot = np.nansum(A) / 1e6
    ax.text(0.01, 0.03, f'global total {tot:.3f} Mkm²; cells > 0: {(A > 0).sum():,}; max {np.nanmax(A):.0f} km²', transform=ax.transAxes, fontsize=8, bbox=dict(fc='white', ec='none', alpha=0.8))
    cite(fig, f'source: {src}; grey = ISIMIP land (non-fill) outline; cells with 0 km² left blank'); fig.tight_layout(); fig.savefig(f'{FIG}/{name}.png', dpi=160); plt.close(fig)

# 3 difference map
fig, ax = plt.subplots(figsize=(12, 5.6)); base(ax, 'VIC − ISIMIP irrigated area 2021, km² per 15′ cell (diverging, symlog, centred on 0)')
dmax = np.nanmax(np.abs(D))
dnorm = mcolors.SymLogNorm(linthresh=10, linscale=0.5, vmin=-dmax, vmax=dmax)
im = ax.imshow(np.where(common & (np.abs(D) > 0), D, np.nan), extent=EXT, origin='upper', cmap='RdBu_r', norm=dnorm, interpolation='nearest')
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02); cb.set_label('km² per cell; red = VIC larger, blue = ISIMIP larger (symlog, ±max |D|, nothing clipped)')
ax.text(0.01, 0.03, f'Σ|D| = {np.nansum(np.abs(D))/1e6:.3f} Mkm²; ΣD = {np.nansum(D)/1e6:+.3f} Mkm²; max |D| = {dmax:.0f} km²', transform=ax.transAxes, fontsize=8, bbox=dict(fc='white', ec='none', alpha=0.8))
cite(fig, f'D = A_vic − A_isimip on common valid cells; {src_v}; {src_i}'); fig.tight_layout(); fig.savefig(f'{FIG}/fig03_difference_vic_minus_isimip_2021.png', dpi=160); plt.close(fig)

# 4 category map (Okabe-Ito, fixed order)
cat_cols = {1: '#E69F00', 2: '#0072B2', 3: '#D55E00', 4: '#56B4E9', 5: '#009E73'}
cat_lab = {1: 'VIC only', 2: 'ISIMIP only', 3: 'both, VIC larger', 4: 'both, ISIMIP larger', 5: 'both, ≈ equal'}
cmap_c = mcolors.ListedColormap([cat_cols[k] for k in (1, 2, 3, 4, 5)]); bnorm = mcolors.BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], 5)
fig, ax = plt.subplots(figsize=(12, 5.6)); base(ax, 'Agreement class per 15′ cell, 2021 (presence > 1 km²; ≈ equal if |D| ≤ max(1 km², 5 % of max))')
ax.imshow(np.where(cat >= 1, cat, np.nan), extent=EXT, origin='upper', cmap=cmap_c, norm=bnorm, interpolation='nearest')
cnt = {k: int((cat == k).sum()) for k in cat_lab}
ax.legend(handles=[Patch(color=cat_cols[k], label=f'{cat_lab[k]} ({cnt[k]:,} cells)') for k in cat_lab], loc='lower left', fontsize=8, framealpha=0.9)
cite(fig, f'{src_v}; {src_i}; cells where neither has > 1 km² left blank'); fig.tight_layout(); fig.savefig(f'{FIG}/fig04_agreement_category_2021.png', dpi=160); plt.close(fig)

# 5 overlap ratio
fig, ax = plt.subplots(figsize=(12, 5.6)); base(ax, 'Overlap ratio min(A_vic, A_isimip) / max(A_vic, A_isimip), 2021, cells where max > 1 km²')
im = ax.imshow(np.where(common & (np.maximum(Av, Ai) > 1), ratio, np.nan), extent=EXT, origin='upper', cmap='viridis', vmin=0, vmax=1, interpolation='nearest')
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02); cb.set_label('overlap ratio (1 = identical area, 0 = only one side present)')
cite(fig, f'{src_v}; {src_i}'); fig.tight_layout(); fig.savefig(f'{FIG}/fig05_overlap_ratio_2021.png', dpi=160); plt.close(fig)

# 6 scatter / hexbin linear and log1p
sel = common & ((Av > 0) | (Ai > 0)); x = Ai[sel]; y = Av[sel]
fig, axs = plt.subplots(1, 2, figsize=(12, 5.4))
for ax, tr, ttl in ((axs[0], lambda v: v, 'linear, km² per cell'), (axs[1], np.log1p, 'log1p(km² per cell)')):
    hb = ax.hexbin(tr(x), tr(y), gridsize=70, bins='log', cmap='Blues', mincnt=1)
    m = max(tr(x).max(), tr(y).max()); ax.plot([0, m], [0, m], 'k--', lw=1, label='1:1'); ax.set_xlabel(f'ISIMIP A_isimip ({ttl})'); ax.set_ylabel(f'VIC A_vic ({ttl})'); ax.set_title(f'VIC vs ISIMIP 2021, {ttl.split(",")[0]}; n = {sel.sum():,} cells', loc='left', fontsize=9)
    fig.colorbar(hb, ax=ax, fraction=0.04, pad=0.02, label='cells per hexagon (log)'); ax.legend(loc='upper left')
r = np.corrcoef(x, y)[0, 1]; axs[0].text(0.98, 0.03, f'Pearson r = {r:.3f}', transform=axs[0].transAxes, ha='right')
cite(fig, f'{src_v}; {src_i}'); fig.tight_layout(); fig.savefig(f'{FIG}/fig06_scatter_hexbin_vic_vs_isimip_2021.png', dpi=160); plt.close(fig)

# 7 histogram / ECDF of D
dd = D[sel]
fig, axs = plt.subplots(1, 2, figsize=(12, 4.6))
edges = np.concatenate([-np.logspace(0, np.log10(np.abs(dd).max() + 1), 40)[::-1], [0], np.logspace(0, np.log10(np.abs(dd).max() + 1), 40)])
axs[0].hist(dd, bins=edges, color='#0072B2'); axs[0].set_xscale('symlog', linthresh=10); axs[0].set_xlabel('D = A_vic − A_isimip (km² per cell, symlog axis)'); axs[0].set_ylabel('cells'); axs[0].set_title('Histogram of cell differences (cells with either > 0)', loc='left')
s = np.sort(dd); axs[1].plot(s, np.arange(1, s.size + 1) / s.size, color='#0072B2', lw=1.5); axs[1].set_xscale('symlog', linthresh=10); axs[1].set_xlabel('D (km² per cell, symlog axis)'); axs[1].set_ylabel('ECDF'); axs[1].set_title('ECDF of D', loc='left'); axs[1].axvline(0, color='grey', lw=0.8)
for p in (5, 25, 50, 75, 95): axs[1].axhline(p / 100, color='#cccccc', lw=0.5)
axs[1].text(0.02, 0.9, 'p05/p50/p95 = ' + ' / '.join(f'{np.percentile(dd, p):.0f}' for p in (5, 50, 95)) + ' km²', transform=axs[1].transAxes)
cite(fig, f'{src_v}; {src_i}'); fig.tight_layout(); fig.savefig(f'{FIG}/fig07_difference_histogram_ecdf_2021.png', dpi=160); plt.close(fig)

# 8 regional stacked bars: overlap, VIC excess, ISIMIP excess (area-weighted by fractional country masks)
reg = pd.read_csv(f'{OUT}/statistics_regional.csv', comment='#')
reg = reg[reg['ISIMIP_total_km2_areaweighted'] + reg['VIC_total_km2_areaweighted'] > 0]
fig, ax = plt.subplots(figsize=(11, 5.2)); xx = np.arange(len(reg)); w = 0.38
ov = reg['sum_min_overlap_km2_areaweighted'] / 1e6; ev = reg['VIC_excess_km2_areaweighted'] / 1e6; ei = reg['ISIMIP_excess_km2_areaweighted'] / 1e6
ax.bar(xx - w / 2, ov, w, color='#009E73', label='overlap Σmin'); ax.bar(xx - w / 2, ev, w, bottom=ov, color='#E69F00', label='VIC excess (VIC total = overlap + excess)')
ax.bar(xx + w / 2, ov, w, color='#009E73'); ax.bar(xx + w / 2, ei, w, bottom=ov, color='#0072B2', label='ISIMIP excess (ISIMIP total = overlap + excess)')
ax.set_xticks(xx); ax.set_xticklabels(reg['region'].str.replace(' (land without country fraction)', '', regex=False), rotation=30, ha='right'); ax.set_ylabel('Mkm²'); ax.legend(); ax.set_title('Irrigated area 2021 by region: left bar = VIC, right bar = ISIMIP; area-weighted with ISIMIP fractional country masks', loc='left')
for i, (a, b) in enumerate(zip(ov + ev, ov + ei)): ax.text(i - w / 2, a, f'{a:.2f}', ha='center', va='bottom', fontsize=7); ax.text(i + w / 2, b, f'{b:.2f}', ha='center', va='bottom', fontsize=7)
cite(fig, 'statistics_regional.csv (area-weighted columns); regions = country groups in regions.py'); fig.tight_layout(); fig.savefig(f'{FIG}/fig08_regional_overlap_excess_2021.png', dpi=160); plt.close(fig)

# 9 time series
ts = pd.read_csv(f'{OUT}/timeseries_global.csv', comment='#')
fig, axs = plt.subplots(1, 2, figsize=(12, 4.6))
ax = axs[0]; ax.plot(ts['year'], ts['ISIMIP_irrigated_km2_all_cells'] / 1e6, color='#0072B2', lw=2, label='ISIMIP4b histsoc (LUH3) global, all cells')
ax.plot(ts['year'], ts['ISIMIP_irrigated_km2_in_VIC_land_parents'] / 1e6, color='#56B4E9', lw=1, ls='--', label='ISIMIP in parents with VIC land')
v = ts.dropna(subset=['VIC_irrigated_km2']); ax.plot(v['year'], v['VIC_irrigated_km2'] / 1e6, color='#E69F00', lw=2, label='VIC Version-A v5 (classes 14+15) 2003–2022')
ax.axhline(float(v.loc[v['year'] == 2021, 'VIC_irrigated_km2'].iloc[0]) / 1e6, color='#E69F00', lw=0.8, ls=':', label='VIC 2021 static baseline')
ax.set_xlabel('year'); ax.set_ylabel('global irrigated cropland area (Mkm²)'); ax.set_title('Global irrigated area 1850–2022', loc='left'); ax.legend(fontsize=8)
ax = axs[1]; z = ts[(ts['year'] >= 2000)]; ax.plot(z['year'], z['ISIMIP_irrigated_km2_all_cells'] / 1e6, color='#0072B2', lw=2, label='ISIMIP4b histsoc')
ax.plot(v['year'], v['VIC_irrigated_km2'] / 1e6, color='#E69F00', lw=2, label='VIC total'); ax.plot(v['year'], v['VIC_nonpaddy_km2'] / 1e6, color='#D55E00', lw=1, label='VIC class 14 non-paddy'); ax.plot(v['year'], v['VIC_paddy_km2'] / 1e6, color='#CC79A7', lw=1, label='VIC class 15 paddy')
ax.set_xlabel('year'); ax.set_ylabel('Mkm²'); ax.set_title('2000–2022 detail', loc='left'); ax.legend(fontsize=8)
cite(fig, 'timeseries_global.csv; ISIMIP = landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc; VIC = coverage_VersionA_v5_2003..2022.nc'); fig.tight_layout(); fig.savefig(f'{FIG}/fig09_global_timeseries.png', dpi=160); plt.close(fig)

# 10 ISIMIP snapshot maps
fig, axs = plt.subplots(3, 2, figsize=(13, 10.5))
for ax, y, A in zip(axs.ravel(), snap_years, snaps):
    base(ax, f'ISIMIP4b histsoc irrigated area {int(y)} ({np.nansum(A)/1e6:.3f} Mkm²)'); im = ax.imshow(np.where(A > 0, A, np.nan), extent=EXT, origin='upper', cmap='Blues', norm=snorm, interpolation='nearest')
fig.colorbar(im, ax=axs.ravel().tolist(), fraction=0.02, pad=0.01, label='km² per 15′ cell (symlog)'); cite(fig, src_i.replace('2021', '1850..2021'))
fig.savefig(f'{FIG}/fig10_isimip_snapshots_1850_2021.png', dpi=140); plt.close(fig)

# 11 multiscale + per-year agreement
ms = pd.read_csv(f'{OUT}/multiscale_agreement.csv', comment='#'); py = pd.read_csv(f'{OUT}/peryear_cellwise_2003_2021.csv', comment='#')
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
axs[0].plot(ms['scale'], ms['IoU'], 'o-', color='#0072B2', label='IoU Σmin/Σmax'); axs[0].plot(ms['scale'], ms['Dice'], 's-', color='#E69F00', label='Dice'); axs[0].plot(ms['scale'], ms['pearson_r_either_present'], '^-', color='#009E73', label='Pearson r'); axs[0].set_ylim(0, 1); axs[0].set_title('Agreement vs aggregation scale (2021)', loc='left'); axs[0].legend(); axs[0].set_xlabel('grid scale'); axs[0].grid(alpha=0.3)
axs[1].plot(py['year'], py['IoU_summin_over_summax'], 'o-', color='#0072B2', label='IoU'); axs[1].plot(py['year'], py['Dice_2summin_over_sum'], 's-', color='#E69F00', label='Dice'); axs[1].plot(py['year'], py['pearson_r_either_present'], '^-', color='#009E73', label='Pearson r'); axs[1].set_ylim(0, 1); axs[1].set_title('Cell-wise agreement per year at 15′, 2003–2021', loc='left'); axs[1].legend(); axs[1].set_xlabel('year'); axs[1].grid(alpha=0.3)
cite(fig, 'multiscale_agreement.csv; peryear_cellwise_2003_2021.csv'); fig.tight_layout(); fig.savefig(f'{FIG}/fig11_multiscale_and_peryear_agreement.png', dpi=160); plt.close(fig)

# 12 regional zooms of category map for the top disagreement regions
zooms = {'South Asia': (60, 100, 5, 38), 'East Asia': (95, 135, 18, 50), 'MENA / Central Asia': (25, 80, 22, 50), 'North America': (-125, -70, 25, 50)}
fig, axs = plt.subplots(2, 2, figsize=(13, 9))
for ax, (nm, (x0, x1, y0, y1)) in zip(axs.ravel(), zooms.items()):
    ax.imshow(np.where(cat >= 1, cat, np.nan), extent=EXT, origin='upper', cmap=cmap_c, norm=bnorm, interpolation='nearest'); ax.contour(lon, lat, land_outline, levels=[0.5], colors='#777777', linewidths=0.3)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_title(f'Agreement class, {nm}', loc='left'); ax.set_facecolor('#f4f4f4')
fig.legend(handles=[Patch(color=cat_cols[k], label=cat_lab[k]) for k in cat_lab], loc='lower center', ncol=5, fontsize=9); fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(f'{FIG}/fig12_agreement_category_zooms_2021.png', dpi=150); plt.close(fig)
print('figures written to', FIG)
