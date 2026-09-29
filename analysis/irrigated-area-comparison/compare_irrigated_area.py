#!/usr/bin/env python
"""
Cell-wise comparison of total irrigated cropland area: VIC-WUR 5' Version-A land-use forcing (classes 14+15)
aggregated conservatively to 15' versus ISIMIP4b `landuse-5crops` (LUH3) 15' irrigated fractions.

Run with:  /home/WUR/liu297/miniconda3/envs/py39/bin/python compare_irrigated_area.py
Outputs go to $ISIMIP4B_WORKDIR/analysis/irrigated-area-comparison (OUT). Nothing outside OUT is written.

Definitions (all areas in km^2 unless stated):
  ISIMIP side  : f_ISIMIP(j) = sum of the 7 *_irrigated* variables of landuse-5crops (fraction of WHOLE grid cell,
                 global attribute `comment`: "Fractions are of the whole grid cell, not land area").
                 A_ISIMIP_15(j) = f_ISIMIP(j) * A_full(j), A_full = spherical 15' cell area (R = 6371 km).
                 Cross-check: sum of the 7 variables == landuse-totals `cropland_irrigated` (max |diff| 6.5e-8).
  VIC side     : f_VIC(i) = coverage[class 14 'irrigated_non_paddy_crop'] + coverage[class 15 'irrigated_paddy_crop']
                 (1-based VIC class numbers; 0-based indices 13, 14), fraction of the 5' cell (domain frac == 1
                 everywhere active, so this is also a whole-cell fraction).
                 A_VIC_5(i) = f_VIC(i) * A_5(i) * mask(i); A_VIC_15(j) = sum over the 3x3 children i of j.
                 A_5 = spherical 5' cell area (R = 6371 km); the domain `area` variable is also reported as a check.
"""
import os, sys, json, time
import numpy as np
import netCDF4 as nc
import pandas as pd
from scipy import stats as sstats
import cftime
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v

OUT = f'{WORKDIR}/analysis/irrigated-area-comparison'; os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regions import ISO3_TO_REGION, REGION_ORDER

# ----------------------------------------------------------------------------- inputs (read-only)
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData'
F_5CROPS = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc'   # md5 cf868f0e... (== DKRZ)
F_TOTALS = f'{RAW}/socioeconomic/landuse/histsoc/landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'   # cross-check only
F_CMASK = f'{RAW}/geo_conditions/countrymasks/countrymasks-fractional_15arcmin.nc'

F_COV = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{year}.nc'
F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'

YEAR_MAIN = 2021
ISIMIP_SNAPSHOT_YEARS = [1850, 1900, 1950, 2000, 2010, 2021]
VIC_YEARS = list(range(2003, 2023))
R_EARTH = 6371000.0
KM2 = 1e-6            # m2 -> km2
CLS_IRR_NONPADDY, CLS_IRR_PADDY = 13, 14   # 0-based indices of VIC classes 14 and 15

# thresholds
PRESENCE_KM2_MAIN = 1.0            # a cell "has irrigation" if A > 1 km2
EQ_TOL_REL_MAIN = 0.05             # approximately equal if |D| <= max(1 km2, 5% * max(A_vic, A_isimip))
EQ_TOL_ABS_KM2 = 1.0
REL_DENOM_MIN_KM2 = 10.0           # D/A_isimip only reported where A_isimip > 10 km2
EPS_KM2 = 1.0                      # D / max(A_vic, A_isimip, eps)

CAT_NAMES = {0: 'neither', 1: 'VIC only', 2: 'ISIMIP only', 3: 'both, VIC larger', 4: 'both, ISIMIP larger',
             5: 'both, approx. equal', -1: 'not compared (outside common valid grid)'}

log_lines = []
def log(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); log_lines.append(s)

def sph_area(lat_centres, dlat_deg, dlon_deg, nlon):
    """Spherical cell area (m2) for a regular lat/lon grid; returns (nlat, nlon)."""
    h = dlat_deg / 2.0
    a = (R_EARTH ** 2) * np.deg2rad(dlon_deg) * (np.sin(np.deg2rad(lat_centres + h)) - np.sin(np.deg2rad(lat_centres - h)))
    return a[:, None] * np.ones((1, nlon))

# ----------------------------------------------------------------------------- VIC domain
t0 = time.time()
dom = nc.Dataset(F_DOM)
vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan)
vmask = dom['mask'][:].filled(0).astype(bool)
varea_dom = dom['area'][:].filled(np.nan).astype('f8')
vfrac = dom['frac'][:].filled(np.nan).astype('f8')
assert vlat[0] < vlat[-1] and vlon[0] < vlon[-1]           # S->N, W->E
A5 = sph_area(vlat, 1/12., 1/12., vlon.size)
land5 = np.where(vmask, A5 * np.where(np.isfinite(vfrac), vfrac, 1.0), 0.0)         # m2; frac==1 on all active cells
land5_dom = np.where(vmask, varea_dom * np.where(np.isfinite(vfrac), vfrac, 1.0), 0.0)
log(f'VIC domain: {vmask.shape}, active {vmask.sum()}, lat {vlat[0]:.5f}..{vlat[-1]:.5f}, lon {vlon[0]:.5f}..{vlon[-1]:.5f}')
log(f'VIC frac on active cells: min {vfrac[vmask].min()} max {vfrac[vmask].max()}  (==1 -> coverage fractions are whole-cell fractions)')
log(f'VIC active land area: spherical {land5.sum()*KM2/1e6:.4f} Mkm2, domain-area variable {land5_dom.sum()*KM2/1e6:.4f} Mkm2, '
    f'domain/spherical ratio range {np.nanmin(varea_dom/A5):.5f}..{np.nanmax(varea_dom/A5):.5f}')

# ----------------------------------------------------------------------------- ISIMIP grid
f5 = nc.Dataset(F_5CROPS)
ilat = f5['lat'][:].filled(np.nan); ilon = f5['lon'][:].filled(np.nan)
assert ilat[0] > ilat[-1] and ilon[0] < ilon[-1]           # N->S, W->E
NLAT, NLON = ilat.size, ilon.size
A15 = sph_area(ilat, 0.25, 0.25, NLON)
tvals = f5['time'][:]; tunits = f5['time'].units; tcal = f5['time'].calendar
years_isimip = np.array([d.year for d in cftime.num2date(tvals, tunits, tcal)])
IRR_VARS = [v for v in f5.variables if v.endswith('_irrigated') or '_irrigated_' in v]
log('ISIMIP 5crops irrigated variables used:', IRR_VARS)
log(f'ISIMIP grid {NLAT}x{NLON}, lat {ilat[0]}..{ilat[-1]}, lon {ilon[0]}..{ilon[-1]}, years {years_isimip[0]}..{years_isimip[-1]}, calendar {tcal}')

def read_isimip_frac(year):
    """Sum of the irrigated CFT fractions for one year; returns (frac with fill->0, fillmask)."""
    k = int(np.where(years_isimip == year)[0][0])
    S = np.zeros((NLAT, NLON)); fm = None
    for v in IRR_VARS:
        a = f5[v][k]
        m = np.ma.getmaskarray(a); fm = m if fm is None else (fm | m)
        S += a.filled(0).astype('f8')
    return S, fm

# ----------------------------------------------------------------------------- 5' -> 15' aggregation and alignment
# VIC 5' rows 0..1679 (S->N) form 560 blocks of 3; block b has centre lat = mean of its 3 rows.
NB_LAT, NB_LON = vlat.size // 3, vlon.size // 3
blat = vlat.reshape(NB_LAT, 3).mean(1); blon = vlon.reshape(NB_LON, 3).mean(1)
# map to ISIMIP rows (N->S): row = (90 - lat)/0.25 - 0.5
rows = np.rint((90.0 - blat) / 0.25 - 0.5).astype(int)[::-1]        # after flipping S->N to N->S
cols = np.rint((blon + 180.0) / 0.25 - 0.5).astype(int)
r0, r1 = rows[0], rows[-1] + 1
assert np.all(np.diff(rows) == 1) and np.all(np.diff(cols) == 1) and cols[0] == 0 and cols[-1] == NLON - 1
align = {
    'vic_block_rows_in_isimip_grid': [int(r0), int(r1)],
    'max_abs_lat_diff_deg': float(np.abs(ilat[r0:r1] - blat[::-1]).max()),
    'max_abs_lon_diff_deg': float(np.abs(ilon - blon).max()),
    'isimip_lat_orientation': 'N->S', 'vic_lat_orientation': 'S->N (flipped to N->S after aggregation)',
    'lon_range_both': '-180..180 (cell centres -179.875..179.875 at 15arcmin, -179.958..179.958 at 5arcmin)',
}
log('alignment:', json.dumps(align))

def agg_vic_to_isimip(field5):
    """Sum a 5' field (S->N) over 3x3 blocks and place it on the full ISIMIP 720x1440 grid (N->S)."""
    b = field5.reshape(NB_LAT, 3, NB_LON, 3).sum(axis=(1, 3))[::-1]
    out = np.zeros((NLAT, NLON)); out[r0:r1, :] = b
    return out

L15 = agg_vic_to_isimip(land5)             # VIC land area per 15' parent, m2 (== full-cell area of active children)
L15_dom = agg_vic_to_isimip(land5_dom)
vic_has_land = L15 > 0

def read_vic_area(year):
    """VIC irrigated area (m2) per 5' cell for classes 14 and 15 and their sum, from coverage_VersionA_v5_<year>.nc."""
    d = nc.Dataset(F_COV.format(year=year))
    assert np.allclose(d['lat'][:], vlat) and np.allclose(d['lon'][:], vlon)
    cov = d['coverage'][0]
    c14 = np.nan_to_num(cov[CLS_IRR_NONPADDY].filled(np.nan).astype('f8')) * land5
    c15 = np.nan_to_num(cov[CLS_IRR_PADDY].filled(np.nan).astype('f8')) * land5
    names = d['veg_class'].class_names.split('|')
    assert names[CLS_IRR_NONPADDY] == 'irrigated_non_paddy_crop' and names[CLS_IRR_PADDY] == 'irrigated_paddy_crop'
    d.close()
    return c14, c15

# ----------------------------------------------------------------------------- main year
fI, fillI = read_isimip_frac(YEAR_MAIN)
AI = fI * A15                                        # m2
c14, c15 = read_vic_area(YEAR_MAIN)
AV5 = c14 + c15
AV = agg_vic_to_isimip(AV5); AV14 = agg_vic_to_isimip(c14); AV15 = agg_vic_to_isimip(c15)
AV_domarea = agg_vic_to_isimip((c14 + c15) / np.where(land5 > 0, land5, 1) * land5_dom)
cons = {
    'vic_5arcmin_total_km2': AV5.sum() * KM2, 'vic_15arcmin_total_km2': AV.sum() * KM2,
    'conservation_abs_error_km2': (AV5.sum() - AV.sum()) * KM2,
    'vic_total_with_domain_area_variable_km2': AV_domarea.sum() * KM2,
    'vic_nonpaddy_km2': AV14.sum() * KM2, 'vic_paddy_km2': AV15.sum() * KM2,
    'isimip_total_all_cells_km2': AI.sum() * KM2,
    'isimip_total_totals_file_cropland_irrigated_km2': float((nc.Dataset(F_TOTALS)['cropland_irrigated'][int(np.where(years_isimip == YEAR_MAIN)[0][0])].filled(0).astype('f8') * A15).sum() * KM2),
}
log('conservation / totals:', json.dumps(cons, indent=1))

# common valid grid
common = (~fillI) & vic_has_land
mask_terms = {
    'isimip_valid_cells': int((~fillI).sum()), 'vic_parents_with_land': int(vic_has_land.sum()), 'common_cells': int(common.sum()),
    'isimip_irrigated_area_in_cells_without_VIC_land_km2': float(AI[~vic_has_land].sum() * KM2),
    'isimip_irrigated_cells_without_VIC_land': int(((AI > 0) & ~vic_has_land).sum()),
    'vic_irrigated_area_in_isimip_fill_cells_km2': float(AV[fillI].sum() * KM2),
    'vic_irrigated_cells_in_isimip_fill': int(((AV > 0) & fillI).sum()),
    'isimip_area_exceeding_VIC_land_km2': float(np.maximum(AI - L15, 0)[common].sum() * KM2),
    'cells_isimip_area_exceeding_VIC_land': int(((AI > L15) & common).sum()),
    'vic_land_area_in_common_cells_Mkm2': float(L15[common].sum() * KM2 / 1e6),
    'full_cell_area_in_common_cells_Mkm2': float(A15[common].sum() * KM2 / 1e6),
}
log('mask terms:', json.dumps(mask_terms, indent=1))

# ----------------------------------------------------------------------------- cell-wise metrics (km2)
Av = AV * KM2; Ai = AI * KM2
D = Av - Ai
O = np.minimum(Av, Ai); U = np.maximum(Av, Ai)
Evic = np.maximum(D, 0); Eisi = np.maximum(-D, 0)
with np.errstate(divide='ignore', invalid='ignore'):
    rel_isimip = np.where(Ai > REL_DENOM_MIN_KM2, D / Ai, np.nan)
    rel_max = D / np.maximum(U, EPS_KM2)
    ratio = np.where(U > 0, O / U, np.nan)

def classify(Av, Ai, thr, tol_rel, tol_abs=EQ_TOL_ABS_KM2, valid=None):
    pv = Av > thr; pi = Ai > thr
    D = Av - Ai; tol = np.maximum(tol_abs, tol_rel * np.maximum(Av, Ai))
    c = np.zeros(Av.shape, dtype=np.int8)
    c[pv & ~pi] = 1; c[~pv & pi] = 2
    both = pv & pi
    c[both & (np.abs(D) <= tol)] = 5
    c[both & (D > tol)] = 3
    c[both & (D < -tol)] = 4
    if valid is not None: c[~valid] = -1
    return c

cat = classify(Av, Ai, PRESENCE_KM2_MAIN, EQ_TOL_REL_MAIN, valid=common)

# ----------------------------------------------------------------------------- statistics helpers
def metrics(Av, Ai, sel, w=None, label=''):
    """Statistics over cells `sel` (bool). w = optional per-cell weight in [0,1] (fractional region weight) applied to areas."""
    w = np.ones_like(Av) if w is None else w
    av = Av[sel] * w[sel]; ai = Ai[sel] * w[sel]
    d = av - ai; o = np.minimum(av, ai); u = np.maximum(av, ai)
    tv, ti = av.sum(), ai.sum()
    m = {}
    m['n_cells'] = int(sel.sum())
    m['VIC_total_km2'] = tv; m['ISIMIP_total_km2'] = ti
    m['diff_total_km2'] = tv - ti; m['diff_total_pct_of_ISIMIP'] = 100 * (tv - ti) / ti if ti > 0 else np.nan
    m['sum_min_overlap_km2'] = o.sum(); m['sum_max_union_km2'] = u.sum()
    m['overlap_over_VIC'] = o.sum() / tv if tv > 0 else np.nan
    m['overlap_over_ISIMIP'] = o.sum() / ti if ti > 0 else np.nan
    m['IoU_summin_over_summax'] = o.sum() / u.sum() if u.sum() > 0 else np.nan
    m['Dice_2summin_over_sum'] = 2 * o.sum() / (tv + ti) if (tv + ti) > 0 else np.nan
    m['VIC_excess_km2'] = np.maximum(d, 0).sum(); m['ISIMIP_excess_km2'] = np.maximum(-d, 0).sum()
    thr = PRESENCE_KM2_MAIN
    pv = av > thr; pi = ai > thr
    m['cells_VIC_only'] = int((pv & ~pi).sum()); m['area_VIC_only_km2'] = av[pv & ~pi].sum()
    m['cells_ISIMIP_only'] = int((~pv & pi).sum()); m['area_ISIMIP_only_km2'] = ai[~pv & pi].sum()
    m['cells_both'] = int((pv & pi).sum()); m['area_both_VIC_km2'] = av[pv & pi].sum(); m['area_both_ISIMIP_km2'] = ai[pv & pi].sum()
    tol = np.maximum(EQ_TOL_ABS_KM2, EQ_TOL_REL_MAIN * u)
    m['cells_both_VIC_larger'] = int((pv & pi & (d > tol)).sum()); m['net_excess_VIC_in_those_km2'] = d[pv & pi & (d > tol)].sum()
    m['cells_both_ISIMIP_larger'] = int((pv & pi & (d < -tol)).sum()); m['net_excess_ISIMIP_in_those_km2'] = -d[pv & pi & (d < -tol)].sum()
    m['cells_both_approx_equal'] = int((pv & pi & (np.abs(d) <= tol)).sum())
    either = pv | pi
    if either.sum() > 2:
        m['pearson_r_either_present'] = float(np.corrcoef(av[either], ai[either])[0, 1])
        m['spearman_rho_either_present'] = float(sstats.spearmanr(av[either], ai[either]).correlation)
        m['pearson_r_all_cells'] = float(np.corrcoef(av, ai)[0, 1])
        m['spearman_rho_all_cells'] = float(sstats.spearmanr(av, ai).correlation)
        de = d[either]
        m['MAE_km2_either_present'] = float(np.abs(de).mean()); m['RMSE_km2_either_present'] = float(np.sqrt((de ** 2).mean()))
        m['median_abs_diff_km2_either_present'] = float(np.median(np.abs(de)))
        for p in (5, 25, 50, 75, 95, 99): m[f'diff_p{p:02d}_km2_either_present'] = float(np.percentile(de, p))
        m['mean_diff_km2_either_present'] = float(de.mean())
    # area-weighted bias: sum(D) / sum(cell area) over 'either' cells, i.e. mean fraction difference weighted by cell area
    if either.sum() > 0:
        Acell = (A15 * KM2)[sel][either] * w[sel][either]
        m['area_weighted_fraction_bias_either_present'] = float(d[either].sum() / Acell.sum())
    return m

g_all = metrics(Av, Ai, common)
log('GLOBAL (common valid cells):', json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in g_all.items()}, indent=1))

# ----------------------------------------------------------------------------- regions (fractional country mask, area-weighted)
cm = nc.Dataset(F_CMASK)
assert np.allclose(cm['lat'][:], ilat) and np.allclose(cm['lon'][:], ilon)
isos = [v for v in cm.variables if v not in ('lat', 'lon', 'world')]
missing = [c for c in isos if c not in ISO3_TO_REGION]
assert not missing, f'ISO3 codes without region: {missing}'
regw = {r: np.zeros((NLAT, NLON)) for r in REGION_ORDER}
cfrac_sum = np.zeros((NLAT, NLON))
dom_iso = np.full((NLAT, NLON), '', dtype=object); dom_val = np.zeros((NLAT, NLON))
for c in isos:
    a = np.ma.filled(cm[c][:], 0).astype('f8')
    regw[ISO3_TO_REGION[c]] += a; cfrac_sum += a
    upd = a > dom_val; dom_val[upd] = a[upd]; dom_iso[upd] = c
regw['Unassigned (land without country fraction)'] = np.clip(1.0 - cfrac_sum, 0, 1)
REG_ALL = REGION_ORDER + ['Unassigned (land without country fraction)']
reg_id = np.full((NLAT, NLON), -1, dtype=np.int8); reg_best = np.zeros((NLAT, NLON))
for k, r in enumerate(REG_ALL):
    upd = regw[r] > reg_best; reg_best[upd] = regw[r][upd]; reg_id[upd] = k
rows_reg = []
for k, r in enumerate(REG_ALL):
    w = regw[r]
    sel = common & (w > 0)
    m = metrics(Av, Ai, sel, w=w)            # areas weighted by the fractional country share of the region
    m_cnt = metrics(Av, Ai, common & (reg_id == k))   # counts: cells whose dominant region is r
    row = {'region': r, 'cells_dominant_region': int((common & (reg_id == k)).sum())}
    for key in ('VIC_total_km2', 'ISIMIP_total_km2', 'diff_total_km2', 'diff_total_pct_of_ISIMIP', 'sum_min_overlap_km2',
                'overlap_over_VIC', 'overlap_over_ISIMIP', 'IoU_summin_over_summax', 'Dice_2summin_over_sum',
                'VIC_excess_km2', 'ISIMIP_excess_km2'):
        row[key + '_areaweighted'] = m.get(key, np.nan)
    for key in ('cells_VIC_only', 'area_VIC_only_km2', 'cells_ISIMIP_only', 'area_ISIMIP_only_km2', 'cells_both',
                'cells_both_VIC_larger', 'net_excess_VIC_in_those_km2', 'cells_both_ISIMIP_larger', 'net_excess_ISIMIP_in_those_km2',
                'cells_both_approx_equal', 'pearson_r_either_present', 'spearman_rho_either_present', 'MAE_km2_either_present',
                'RMSE_km2_either_present', 'median_abs_diff_km2_either_present', 'diff_p05_km2_either_present', 'diff_p50_km2_either_present',
                'diff_p95_km2_either_present', 'area_weighted_fraction_bias_either_present'):
        row[key + '_dominantregion'] = m_cnt.get(key, np.nan)
    rows_reg.append(row)
df_reg = pd.DataFrame(rows_reg)
chk = df_reg['VIC_total_km2_areaweighted'].sum(), df_reg['ISIMIP_total_km2_areaweighted'].sum()
log(f'regional area-weighted sums: VIC {chk[0]:.1f} (global {g_all["VIC_total_km2"]:.1f}), ISIMIP {chk[1]:.1f} (global {g_all["ISIMIP_total_km2"]:.1f})')

# ----------------------------------------------------------------------------- threshold sensitivity
sens = []
for thr in (0.0, 1.0, 10.0):
    for tol_rel in (0.05, 0.10, 0.20):
        c = classify(Av, Ai, thr, tol_rel, valid=common)
        rec = {'presence_threshold_km2': thr, 'equality_tol_rel': tol_rel, 'equality_tol_abs_km2': EQ_TOL_ABS_KM2}
        for k in (1, 2, 3, 4, 5):
            s = c == k
            rec[f'cells_{CAT_NAMES[k]}'] = int(s.sum()); rec[f'VICarea_{CAT_NAMES[k]}_km2'] = Av[s].sum(); rec[f'ISIMIParea_{CAT_NAMES[k]}_km2'] = Ai[s].sum()
        pv = Av > thr; pi = Ai > thr
        rec['sum_min_over_cells_either_present_km2'] = O[common & (pv | pi)].sum()
        rec['IoU_either_present'] = O[common & (pv | pi)].sum() / U[common & (pv | pi)].sum()
        rec['area_below_threshold_VIC_km2'] = Av[common & ~pv].sum(); rec['area_below_threshold_ISIMIP_km2'] = Ai[common & ~pi].sum()
        sens.append(rec)
df_sens = pd.DataFrame(sens)

# ----------------------------------------------------------------------------- top disagreement cells
idx = np.argsort(-np.abs(np.where(common, D, 0)).ravel())[:20]
top = []
for k in idx:
    r, c = divmod(int(k), NLON)
    top.append({'rank': len(top) + 1, 'lat': float(ilat[r]), 'lon': float(ilon[c]), 'A_vic_km2': Av[r, c], 'A_isimip_km2': Ai[r, c],
                'A_vic_nonpaddy_km2': AV14[r, c] * KM2, 'A_vic_paddy_km2': AV15[r, c] * KM2,
                'D_vic_minus_isimip_km2': D[r, c], 'rel_D_over_isimip': rel_isimip[r, c], 'rel_D_over_max': rel_max[r, c],
                'overlap_ratio_min_over_max': ratio[r, c], 'full_cell_area_km2': A15[r, c] * KM2, 'VIC_land_area_km2': L15[r, c] * KM2,
                'dominant_country_iso3': dom_iso[r, c], 'dominant_country_fraction': dom_val[r, c], 'region': REG_ALL[reg_id[r, c]],
                'category': CAT_NAMES[int(cat[r, c])]})
df_top = pd.DataFrame(top)

# ----------------------------------------------------------------------------- multi-scale agreement
def coarsen(a, n):
    return a.reshape(NLAT // n, n, NLON // n, n).sum(axis=(1, 3))
ms = []
for n, lab in ((1, '15arcmin'), (2, '30arcmin'), (4, '1deg'), (8, '2deg'), (20, '5deg')):
    av = coarsen(np.where(common, Av, 0), n); ai = coarsen(np.where(common, Ai, 0), n)
    o = np.minimum(av, ai).sum(); u = np.maximum(av, ai).sum(); e = (av > 0) | (ai > 0)
    ms.append({'scale': lab, 'n_cells_either_present': int(e.sum()), 'IoU': o / u, 'Dice': 2 * o / (av.sum() + ai.sum()),
               'pearson_r_either_present': float(np.corrcoef(av[e], ai[e])[0, 1]), 'spearman_rho_either_present': float(sstats.spearmanr(av[e], ai[e]).correlation),
               'VIC_total_km2': av.sum(), 'ISIMIP_total_km2': ai.sum()})
df_ms = pd.DataFrame(ms)

# ----------------------------------------------------------------------------- time series
ts = []
for y in range(int(years_isimip[0]), int(years_isimip[-1]) + 1):
    f, fm = read_isimip_frac(y); a = f * A15 * KM2
    ts.append({'year': y, 'ISIMIP_irrigated_km2_all_cells': a.sum(), 'ISIMIP_irrigated_km2_in_VIC_land_parents': a[vic_has_land].sum()})
df_ts = pd.DataFrame(ts).set_index('year')
snaps = {}
for y in ISIMIP_SNAPSHOT_YEARS:
    f, fm = read_isimip_frac(y); snaps[y] = f * A15 * KM2
vts = []; peryear = []
for y in VIC_YEARS:
    a14, a15 = read_vic_area(y); av5 = a14 + a15
    rec = {'year': y, 'VIC_irrigated_km2': av5.sum() * KM2, 'VIC_nonpaddy_km2': a14.sum() * KM2, 'VIC_paddy_km2': a15.sum() * KM2}
    vts.append(rec)
    if y in years_isimip:
        avy = agg_vic_to_isimip(av5) * KM2; f, fm = read_isimip_frac(y); aiy = f * A15 * KM2
        m = metrics(avy, aiy, common)
        peryear.append({'year': y, **{k: m[k] for k in ('VIC_total_km2', 'ISIMIP_total_km2', 'diff_total_pct_of_ISIMIP', 'IoU_summin_over_summax',
                                                          'Dice_2summin_over_sum', 'pearson_r_either_present', 'cells_VIC_only', 'cells_ISIMIP_only', 'cells_both')}})
df_vts = pd.DataFrame(vts).set_index('year'); df_py = pd.DataFrame(peryear)
df_ts = df_ts.join(df_vts, how='outer')

# ----------------------------------------------------------------------------- write outputs
def fmt(v):
    return float(v) if isinstance(v, (np.floating, float)) else int(v) if isinstance(v, (np.integer, int)) else v
rows = [{'scope': 'conservation_and_totals', 'metric': k, 'value': fmt(v), 'unit': 'km2' if 'km2' in k else '-'} for k, v in cons.items()]
rows += [{'scope': 'mask_terms', 'metric': k, 'value': fmt(v), 'unit': 'km2' if 'km2' in k else ('Mkm2' if 'Mkm2' in k else 'cells')} for k, v in mask_terms.items()]
rows += [{'scope': 'alignment', 'metric': k, 'value': str(v), 'unit': '-'} for k, v in align.items()]
rows += [{'scope': 'global_common_cells', 'metric': k, 'value': fmt(v), 'unit': 'km2' if 'km2' in k else ('cells' if k.startswith(('n_', 'cells')) else '-')} for k, v in g_all.items()]
df_glob = pd.DataFrame(rows)
df_glob.attrs['inputs'] = [F_5CROPS, F_COV.format(year=YEAR_MAIN), F_DOM, F_CMASK]
hdr = (f'# inputs: ISIMIP {os.path.basename(F_5CROPS)} (vars {"+".join(IRR_VARS)}, year {YEAR_MAIN}, fraction of whole cell); '
       f'VIC coverage_VersionA_v5_{YEAR_MAIN}.nc classes 14+15 (irrigated_non_paddy_crop + irrigated_paddy_crop) x spherical 5arcmin area x mask; '
       f'areas km2 (spherical, R=6371 km); presence threshold {PRESENCE_KM2_MAIN} km2; equality tol max({EQ_TOL_ABS_KM2} km2, {EQ_TOL_REL_MAIN*100:.0f}% of max)\n')
for name, df in (('statistics_global.csv', df_glob), ('statistics_regional.csv', df_reg), ('threshold_sensitivity.csv', df_sens),
                 ('top_disagreement_cells.csv', df_top), ('multiscale_agreement.csv', df_ms), ('timeseries_global.csv', df_ts.reset_index()),
                 ('peryear_cellwise_2003_2021.csv', df_py)):
    with open(f'{OUT}/{name}', 'w') as fh:
        fh.write(hdr); df.to_csv(fh, index=False, float_format='%.6g')

# cellwise NetCDF (15' ISIMIP grid, N->S)
o = nc.Dataset(f'{OUT}/cellwise_comparison.nc', 'w', format='NETCDF4')
o.createDimension('lat', NLAT); o.createDimension('lon', NLON); o.createDimension('snapshot_year', len(ISIMIP_SNAPSHOT_YEARS))
v = o.createVariable('lat', 'f8', ('lat',)); v[:] = ilat; v.units = 'degrees_north'; v.long_name = 'latitude of 15 arcmin cell centre (N->S, ISIMIP grid)'
v = o.createVariable('lon', 'f8', ('lon',)); v[:] = ilon; v.units = 'degrees_east'
v = o.createVariable('snapshot_year', 'i4', ('snapshot_year',)); v[:] = ISIMIP_SNAPSHOT_YEARS
def wv(name, data, units, long_name, dtype='f4', fillnan=True, dims=('lat', 'lon')):
    x = o.createVariable(name, dtype, dims, zlib=True, complevel=4, fill_value=(np.nan if dtype.startswith('f') else -1))
    x[:] = data; x.units = units; x.long_name = long_name; return x
wv('A_isimip', np.where(fillI, np.nan, Ai), 'km2', f'ISIMIP4b landuse-5crops histsoc {YEAR_MAIN} irrigated area = sum(7 *_irrigated* fractions) x spherical full cell area; NaN = ISIMIP fill (ocean)')
wv('A_vic', np.where(vic_has_land, Av, np.nan), 'km2', f'VIC-WUR coverage_VersionA_v5_{YEAR_MAIN} classes 14+15 irrigated area, sum of 3x3 5arcmin children (fraction x spherical 5arcmin area x mask); NaN = no VIC land in parent')
wv('A_vic_nonpaddy', np.where(vic_has_land, AV14 * KM2, np.nan), 'km2', 'VIC class 14 irrigated_non_paddy_crop area, 3x3 sum')
wv('A_vic_paddy', np.where(vic_has_land, AV15 * KM2, np.nan), 'km2', 'VIC class 15 irrigated_paddy_crop area, 3x3 sum')
wv('L_vic', L15 * KM2, 'km2', 'VIC active land area per 15arcmin parent (sum of spherical 5arcmin areas of active children)')
wv('A_full', A15 * KM2, 'km2', 'spherical full 15arcmin cell area, R=6371 km')
wv('D', np.where(common, D, np.nan), 'km2', 'A_vic - A_isimip on common valid cells')
wv('rel_D_over_isimip', np.where(common, rel_isimip, np.nan), '1', f'D / A_isimip where A_isimip > {REL_DENOM_MIN_KM2} km2')
wv('rel_D_over_max', np.where(common, rel_max, np.nan), '1', f'D / max(A_vic, A_isimip, {EPS_KM2} km2)')
wv('overlap', np.where(common, O, np.nan), 'km2', 'min(A_vic, A_isimip)')
wv('union', np.where(common, U, np.nan), 'km2', 'max(A_vic, A_isimip)')
wv('E_vic', np.where(common, Evic, np.nan), 'km2', 'max(A_vic - A_isimip, 0)')
wv('E_isimip', np.where(common, Eisi, np.nan), 'km2', 'max(A_isimip - A_vic, 0)')
wv('overlap_ratio', np.where(common, ratio, np.nan), '1', 'min/max where max > 0')
x = wv('category', cat, '1', 'agreement class; ' + '; '.join(f'{k}={v}' for k, v in CAT_NAMES.items()), dtype='i1')
x.flag_values = np.array([-1, 0, 1, 2, 3, 4, 5], dtype='i1'); x.presence_threshold_km2 = PRESENCE_KM2_MAIN; x.equality_tol = f'max({EQ_TOL_ABS_KM2} km2, {EQ_TOL_REL_MAIN} x max)'
wv('isimip_valid', (~fillI).astype('i1'), '1', '1 where ISIMIP 5crops is not _FillValue', dtype='i1')
wv('common_valid', common.astype('i1'), '1', '1 where ISIMIP valid and VIC parent has land', dtype='i1')
x = wv('region_id', reg_id, '1', 'dominant region index (max fractional country share); ' + '; '.join(f'{k}={r}' for k, r in enumerate(REG_ALL)), dtype='i1')
wv('country_fraction_sum', cfrac_sum, '1', 'sum of ISIMIP fractional country masks (countrymasks-fractional_15arcmin.nc, 248 ISO3)')
x = wv('A_isimip_snapshots', np.stack([np.where(fillI, np.nan, snaps[y]) for y in ISIMIP_SNAPSHOT_YEARS]), 'km2', 'ISIMIP histsoc irrigated area for snapshot years', dims=('snapshot_year', 'lat', 'lon'))
o.title = 'VIC-WUR vs ISIMIP4b (landuse-5crops, LUH3) total irrigated cropland area, 15 arcmin, 2021'
o.inputs = f'{F_5CROPS} (md5 cf868f0e9f7bc447fb5f4f01c7b4ee09, identical to DKRZ); {F_COV.format(year=YEAR_MAIN)}; {F_DOM}; {F_CMASK}'
o.isimip_variables = '+'.join(IRR_VARS); o.vic_classes = '14 irrigated_non_paddy_crop + 15 irrigated_paddy_crop (1-based)'
o.method = 'A_vic_15(j) = sum_i f_vic(i) * A5(i) * mask(i) over 3x3 children; A_isimip_15(j) = f_isimip(j) * A_full(j); spherical areas R=6371 km'
o.created = time.strftime('%Y-%m-%d %H:%M:%S'); o.script = os.path.abspath(__file__)
o.close()

json.dump({'conservation_and_totals': cons, 'mask_terms': mask_terms, 'alignment': align, 'global_common_cells': g_all,
           'category_counts_main': {CAT_NAMES[k]: int((cat == k).sum()) for k in (0, 1, 2, 3, 4, 5)},
           'category_area_main_km2': {CAT_NAMES[k]: {'VIC': float(Av[cat == k].sum()), 'ISIMIP': float(Ai[cat == k].sum())} for k in (0, 1, 2, 3, 4, 5)},
           'runtime_s': time.time() - t0}, open(f'{OUT}/summary.json', 'w'), indent=1, default=fmt)
open(f'{OUT}/logs/compare_irrigated_area.log', 'w').write('\n'.join(log_lines) + '\n')
log('done in', round(time.time() - t0, 1), 's')
