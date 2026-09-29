#!/usr/bin/env python
"""
Revised 2026-09-23 (evening): backfill targets are the new 5' tiles (allocated minus existing bundle), not one child per fallback parent;
donor distance is reported for L2 tiles only (<=500 km by construction) and, separately, for all targets before the cut.
Per-class full union (15crops: class 12 rainfed, 14 irrigated non-paddy, 15 paddy; time max over histsoc, 1850soc, 2021soc,
ssp1vl, ssp3h from union_15crops.npz) vs the VIC 2003-2022 tile union (activity_masks_v5 class_union_bits), and the
LAI/fcanopy/albedo backfill prototype for the NEW class-15 (paddy) and class-14 tiles with the ladder
   L2 same-class donor <= 500 km  ->  L3 same Koppen-Geiger class (Beck et al. 2023, 1991-2020, 0.1 deg) same-class Cv-weighted mean
   -> L4 5-degree latitude-band median  ->  L5 global median.  Paddy borrows only paddy; class 14 borrows only class 14 here
(cross-class rainfed donors are not used at L2 in this run so that the Koppen level is exercised).
One representative child per fallback parent: the active child with the largest VIC 2003-2022 mean irrigated (14+15) fraction,
else the largest mean rainfed fraction, else the largest land area.
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python union_backfill_paddy.py
"""
import os, json, time, numpy as np, netCDF4 as nc, rasterio
from scipy.spatial import cKDTree
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
t0 = time.time(); OUT = f'{WORKDIR}/analysis/landuse-harmonization-annual'; os.makedirs(OUT, exist_ok=True); FIG = f'{OUT}/figures'
VP = _external('VIC_PARAMETER_ROOT', 'the vic_parameter project root')
F_MASKS = f'{VP}/work/human_impact/version_a_activity_masks_v5/HumanImpact_VersionA_activity_masks_v5_2003_2022_5min_domain_nogl.nc'
F_BUNDLE = f'{VP}/outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc'
F_V5 = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{y}.nc'
F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
F_KG = _external('KOPPEN_GEIGER_TIF', 'the Koppen-Geiger 1991-2020 0.1 degree GeoTIFF (Beck et al. 2023)')
RK = 6371.0088
dom = nc.Dataset(F_DOM); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool)
A5 = ((RK ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, vlon.size))
NB = (560, 1440); NY, NX = mask.shape
def blk(x): return x.reshape(NB[0], 3, NB[1], 3)
u = np.load(f'{OUT}/union_15crops.npz'); U = u['U'][:, 24:584][:, ::-1]; SRC = u['SRC'][:, 24:584][:, ::-1]; FY = u['FY'][:, 24:584][:, ::-1]   # S->N parent grid
am = nc.Dataset(F_MASKS); ub = am['class_union_bits'][:].filled(0).astype(np.uint16)
vic = {0: ((ub >> 11) & 1).astype(bool) & mask, 1: ((ub >> 13) & 1).astype(bool) & mask, 2: ((ub >> 14) & 1).astype(bool) & mask}
par_land = blk(mask).any(axis=(1, 3)); names = {0: '12_rainfed', 1: '14_irr_nonpaddy', 2: '15_paddy'}
res = {'union_source_bits': {'histsoc': 1, '1850soc': 2, '2021soc': 4, 'ssp1vl': 8, 'ssp3h': 16}}; fb = {}
for k in range(3):
    par = blk(vic[k]).any(axis=(1, 3)); need = (U[k] > 0) & par_land; f = need & ~par; fb[k] = f; src = SRC[k]
    res[f'{names[k]}'] = {'isimip_union_parents': int((U[k] > 0).sum()), 'vic_union_children_2003_2022': int(vic[k].sum()), 'vic_union_parents': int(par.sum()),
                          'fallback_parents': int(f.sum()), 'histsoc_positive': int((f & ((src & 1) > 0)).sum()), 'only_future': int((f & ((src & 1) == 0)).sum()), 'ssp1vl_positive': int((f & ((src & 8) > 0)).sum()), 'ssp3h_positive': int((f & ((src & 16) > 0)).sum()),
                          'timmax_share_quantiles': {q: float(np.percentile(U[k][f], q)) for q in (50, 90, 99)} if f.any() else {}, 'first_positive_year_quantiles': {q: int(np.percentile(FY[k][f], q)) for q in (5, 50, 95)} if f.any() else {},
                          'parents_isimip_pos_no_vic_land': int(((U[k] > 0) & ~par_land).sum())}
# backfill targets = NEW 5' tiles: allocated in the 8-target annual prototype but absent from bundle v3 (U_new = U_full \ U_existing)
nt = np.load(f'{OUT}/annual_harmonize_prototype_15crops_union.npz'); NEW = {2: nt['new_paddy'], 1: nt['new_nonpaddy']}
res['note_targets'] = 'targets are 5-arcmin tiles allocated by annual_harmonize_prototype_15crops.py (8 target years) that have Cv==0 in bundle v3; the full 331-year run will add more'
# Koppen
with rasterio.open(F_KG) as ds:
    kg = ds.read(1); tr = ds.transform
    rows = np.clip(((tr.f - vlat) / -tr.e).astype(int), 0, kg.shape[0] - 1); cols = np.clip(((vlon - tr.c) / tr.a).astype(int), 0, kg.shape[1] - 1)
KG = kg[rows[:, None], cols[None, :]].astype(np.int16)   # 0 = no data/ocean
res['koppen'] = {'file': F_KG, 'classes_present_on_vic_active': int(np.unique(KG[mask]).size), 'active_cells_without_koppen': int(((KG == 0) & mask).sum())}
LAT, LON = np.meshgrid(vlat, vlon, indexing='ij')
def xyz(la, lo): la = np.deg2rad(la); lo = np.deg2rad(lo); return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))
b = nc.Dataset(F_BUNDLE); out_fields = {}
for k, ci in ((2, 14), (1, 13)):
    ti, tj = np.where(NEW[k])
    Cvk = b['Cv'][ci].filled(0); donor = (Cvk > 0) & mask; di, dj = np.where(donor)
    tree = cKDTree(xyz(LAT[di, dj], LON[di, dj])); dist, idx = tree.query(xyz(LAT[ti, tj], LON[ti, tj])); dkm = 2 * RK * np.arcsin(np.clip(dist / 2, 0, 1))
    level = np.full(ti.size, 5, np.int8); level[dkm <= 500] = 2
    kg_t = KG[ti, tj]; kg_d = KG[di, dj]; lat_d = vlat[di]; lat_t = vlat[ti]; cvd = Cvk[di, dj]
    kg_has = np.isin(kg_t, np.unique(kg_d[kg_d > 0])) & (kg_t > 0); level[(level == 5) & kg_has] = 3
    band_has = np.array([(np.abs(lat_d - lt) <= 2.5).any() for lt in lat_t]); level[(level == 5) & band_has] = 4
    fields = {}; qa = {}
    for var in ('LAI', 'fcanopy', 'albedo'):
        V = b[var][ci].filled(np.nan); Vd = V[:, di, dj]; new = np.full((12, ti.size), np.nan)
        s = level == 2; new[:, s] = V[:, di[idx[s]], dj[idx[s]]]
        for kgc in np.unique(kg_t[level == 3]):
            dsel = kg_d == kgc; w = cvd[dsel]; tsel = (level == 3) & (kg_t == kgc)
            new[:, tsel] = (np.nansum(Vd[:, dsel] * w, axis=1) / w.sum())[:, None]
        for n_ in np.where(level == 4)[0]: new[:, n_] = np.nanmedian(Vd[:, np.abs(lat_d - lat_t[n_]) <= 2.5], axis=1)
        new[:, level == 5] = np.nanmedian(Vd, axis=1)[:, None]
        jump_new = np.abs(np.diff(np.concatenate([new, new[:1]]), axis=0)).max(axis=0); jump_old = np.abs(np.diff(np.concatenate([Vd, Vd[:1]]), axis=0)).max(axis=0)
        qa[var] = {'new_tiles': int(ti.size), 'nan_after_fill': int((~np.isfinite(new)).any(axis=0).sum()), 'range_new': [float(np.nanmin(new)), float(np.nanmax(new))], 'range_existing': [float(np.nanmin(Vd)), float(np.nanmax(Vd))],
                   'jump_p99_new': float(np.nanpercentile(jump_new, 99)), 'jump_p99_existing': float(np.nanpercentile(jump_old, 99)), 'jump_max_new': float(np.nanmax(jump_new))}
        fields[var] = new
    res[f'backfill_{names[k]}'] = {'targets': int(ti.size), 'existing_tiles': int(donor.sum()), 'levels': {'L2_same_class_le500km': int((level == 2).sum()), 'L3_koppen_same_class': int((level == 3).sum()), 'L4_lat_band': int((level == 4).sum()), 'L5_global': int((level == 5).sum())},
                                   'nearest_same_class_distance_km_ALL_targets_before_cut': {q: float(np.percentile(dkm, q)) for q in (50, 75, 90, 95, 99)}, 'donor_distance_km_L2_only': {q: float(np.percentile(dkm[level == 2], q)) for q in (50, 75, 90, 95, 100)}, 'fields': qa}
    out_fields[names[k]] = dict(ti=ti, tj=tj, level=level, dkm=dkm, **{f'{v}_new': fields[v] for v in fields})
    # figures for paddy
    if k == 2:
        ext = [-180, 180, -56, 84]; fig, axs = plt.subplots(2, 1, figsize=(12, 10.5))
        ax = axs[0]; src = SRC[2]; cat = np.zeros(fb[2].shape, np.int8); hist = (src & 1) > 0; s1 = (src & 8) > 0; s3 = (src & 16) > 0
        cat[fb[2] & hist] = 1; cat[fb[2] & ~hist & s1 & ~s3] = 2; cat[fb[2] & ~hist & s3 & ~s1] = 3; cat[fb[2] & ~hist & s1 & s3] = 4
        cols = {1: '#0072B2', 2: '#E69F00', 3: '#D55E00', 4: '#009E73'}; lab = {1: 'histsoc 1850–2021', 2: 'SSP1-VL only', 3: 'SSP3-H only', 4: 'both SSPs, not histsoc'}
        ax.imshow(np.where(par_land, 0.5, np.nan), origin='lower', extent=ext, cmap='Greys', vmin=0, vmax=3, interpolation='nearest'); ax.imshow(np.where(cat > 0, cat, np.nan), origin='lower', extent=ext, cmap=mcolors.ListedColormap([cols[c] for c in (1, 2, 3, 4)]), norm=mcolors.BoundaryNorm([.5, 1.5, 2.5, 3.5, 4.5], 4), interpolation='nearest')
        ax.legend(handles=[Patch(color=cols[c], label=f'{lab[c]} ({int((cat == c).sum()):,})') for c in cols], loc='lower left', fontsize=8); ax.set_title(f'15′ parents with ISIMIP 15crops rice_irrigated > 0 in 1850–2100 but no VIC class-15 tile 2003–2022 ({int(fb[2].sum()):,})', loc='left', fontsize=10); ax.set_facecolor('#f4f4f4')
        ax = axs[1]; ax.imshow(np.where(par_land, 0.5, np.nan), origin='lower', extent=ext, cmap='Greys', vmin=0, vmax=3, interpolation='nearest', zorder=0)
        lc = {2: '#009E73', 3: '#E69F00', 4: '#D55E00', 5: '#000000'}; ll = {2: 'L2 same-class ≤500 km', 3: 'L3 Köppen same class', 4: 'L4 5° lat band', 5: 'L5 global'}
        for c in (2, 3, 4, 5): s = level == c; ax.scatter(vlon[tj][s], vlat[ti][s], c=lc[c], s=2, label=f'{ll[c]} ({int(s.sum()):,})')
        ax.legend(loc='lower left', fontsize=8, markerscale=5); ax.set_xlim(-180, 180); ax.set_ylim(-56, 84); ax.set_title(f'Backfill level for LAI/fcanopy/albedo of the {ti.size:,} NEW class-15 (paddy) 5′ tiles (allocated in 8 target years, absent from bundle v3); paddy borrows only paddy donors', loc='left', fontsize=9); ax.set_facecolor('#f4f4f4')
        fig.text(0.01, 0.005, 'union: landuse-15crops rice_irrigated time max over histsoc/1850soc/2021soc/ssp1vl/ssp3h; VIC: activity_masks_v5 class 15; donors: bundle v3 Cv[class15]>0; Köppen: Beck et al. 2023 1991–2020 0.1°', fontsize=7, color='#555')
        fig.tight_layout(); fig.savefig(f'{FIG}/p04_paddy_union_parents_and_backfill_levels.png', dpi=140); plt.close(fig)
        fig, axs = plt.subplots(1, 3, figsize=(15, 4))
        for ax, var in zip(axs, ('LAI', 'fcanopy', 'albedo')):
            V = b[var][14].filled(np.nan); Vd = V[:, di, dj]
            for q, c in ((10, '#ccc'), (50, '#666'), (90, '#ccc')): ax.plot(range(1, 13), np.nanpercentile(Vd, q, axis=1), color=c, label=f'existing p{q}')
            for q, c in ((10, '#56B4E9'), (50, '#0072B2'), (90, '#56B4E9')): ax.plot(range(1, 13), np.nanpercentile(fields[var], q, axis=1), '--', color=c, label=f'new p{q}')
            ax.set_title(f'class 15 {var}: existing vs backfilled', loc='left', fontsize=9); ax.set_xticks(range(1, 13)); ax.grid(alpha=0.3)
        axs[0].legend(fontsize=7); fig.tight_layout(); fig.savefig(f'{FIG}/p05_paddy_monthly_climatology_existing_vs_backfilled.png', dpi=140); plt.close(fig)
    print(names[k], 'done', round(time.time() - t0), 's', flush=True)
np.savez_compressed(f'{OUT}/union_backfill_paddy_fields.npz', fb_rf=fb[0], fb_np=fb[1], fb_pd=fb[2], KG=KG, **{f'{n}_{kk}': vv for n, d_ in out_fields.items() for kk, vv in d_.items()})
res['runtime_s'] = time.time() - t0
json.dump(res, open(f'{OUT}/union_backfill_paddy.json', 'w'), indent=1, default=float); print(json.dumps(res, indent=1, default=float))
