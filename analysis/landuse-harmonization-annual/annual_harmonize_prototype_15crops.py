#!/usr/bin/env python
"""
Annual (Option-1) harmonization prototype with ISIMIP4b landuse-15crops targets (no phi split) and landuse-urbanareas:
  class 12 rainfed  = sum(*_rainfed*) ; class 15 paddy = rice_irrigated ; class 14 non-paddy = sum(*_irrigated*) - rice_irrigated ;
  class 13 urban    = urbanareas
  weights = VIC v5 2003-2022 mean class pattern x land ; allocation order urban -> paddy -> non-paddy -> rainfed ;
  cap(i) = land_i - already allocated ; water-filling + spill ; fallback ladder when parent weight sum == 0:
     paddy   : own -> non-paddy W -> rainfed W -> low vegetation W -> uniform over active children -> unplaced
     nonpaddy: own -> paddy W -> rainfed W -> low veg -> uniform -> unplaced
     rainfed : own -> (paddy+nonpaddy) W -> low veg -> uniform -> unplaced
     urban   : own -> any crop W -> low veg -> uniform -> unplaced
  single-child rule: fallback parents (level >= 2) whose target share of the parent < 1e-3 receive the whole target in ONE child
     (largest fallback weight, else largest land) -> limits new-tile count
  natural remainder -> classes 1-11,16 by the cell's 2003-2022 mean composition (nearest <=100 km, else barren)
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python annual_harmonize_prototype_15crops.py
"""
import os, json, time, numpy as np, netCDF4 as nc
from scipy.spatial import cKDTree
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v
t0 = time.time(); OUT = f'{WORKDIR}/analysis/landuse-harmonization-annual'; os.makedirs(OUT, exist_ok=True); FIG = f'{OUT}/figures'
VP = _external('VIC_PARAMETER_ROOT', 'the vic_parameter project root'); F_V5 = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{y}.nc'
F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
F15 = {'histsoc': (f'{RAW}/histsoc/landuse-15crops_histsoc_15arcmin_annual_1850_2021.nc', 1850), 'ssp1vl': (f'{RAW}/ssp1vlsoc-noadapt/landuse-15crops_ssp1vl_15arcmin_annual_2022_2100.nc', 2022), 'ssp3h': (f'{RAW}/ssp3hsoc-noadapt/landuse-15crops_ssp3h_15arcmin_annual_2022_2100.nc', 2022)}
FU = {'histsoc': f'{RAW}/histsoc/landuse-urbanareas_histsoc_15arcmin_annual_1850_2021.nc', 'ssp1vl': f'{RAW}/ssp1vlsoc-noadapt/landuse-urbanareas_ssp1vl_15arcmin_annual_2022_2100.nc', 'ssp3h': f'{RAW}/ssp3hsoc-noadapt/landuse-urbanareas_ssp3h_15arcmin_annual_2022_2100.nc'}
TARGETS = [('histsoc', 1850), ('histsoc', 1950), ('histsoc', 2000), ('histsoc', 2021), ('ssp1vl', 2050), ('ssp1vl', 2100), ('ssp3h', 2050), ('ssp3h', 2100)]
SMALL = 1e-3; R = 6371000.0; RK = 6371.0088
CL = {'urban': 12, 'paddy': 14, 'nonpaddy': 13, 'rf': 11}; LOWVEG = [5, 6, 7, 8, 9]; NATIDX = list(range(0, 11)) + [15]
dom = nc.Dataset(F_DOM); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool)
A5 = ((R ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, vlon.size)); land = np.where(mask, A5, 0.0)
NY, NX = mask.shape; NB = (NY // 3, NX // 3)
def blk(x): return x.reshape(NB[0], 3, NB[1], 3)
A15 = None
# VIC mean patterns
years = list(range(2003, 2023)); n = len(years); P = {k: np.zeros((NY, NX)) for k in CL}; low = np.zeros((NY, NX)); nat = np.zeros((len(NATIDX), NY, NX))
for y in years:
    cov = nc.Dataset(F_V5.format(y=y))['coverage'][0]
    for k, ki in CL.items(): P[k] += np.nan_to_num(cov[ki].filled(np.nan)) / n
    for a, ki in enumerate(NATIDX):
        c = np.nan_to_num(cov[ki].filled(np.nan)); nat[a] += c / n
        if ki in LOWVEG: low += c / n
W = {k: P[k] * land for k in CL}; Wlow = low * land; nat_sum = nat.sum(axis=0)
LAT, LON = np.meshgrid(vlat, vlon, indexing='ij')
def xyz(la, lo): la = np.deg2rad(la); lo = np.deg2rad(lo); return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))
treeN = cKDTree(xyz(LAT[(nat_sum > 1e-9) & mask], LON[(nat_sum > 1e-9) & mask]))
def targets(sc, y):
    global A15
    fn, y0 = F15[sc]; d = nc.Dataset(fn); t = y - y0; lat = d['lat'][:]
    if A15 is None: A15 = ((R ** 2) * np.deg2rad(0.25) * (np.sin(np.deg2rad(lat + 0.125)) - np.sin(np.deg2rad(lat - 0.125))))[:, None] * np.ones((1, 1440))
    rf = sum(d[v][t].filled(0).astype('f8') for v in d.variables if '_rainfed' in v); ir = sum(d[v][t].filled(0).astype('f8') for v in d.variables if '_irrigated' in v); rc = d['rice_irrigated'][t].filled(0).astype('f8'); d.close()
    ur = nc.Dataset(FU[sc])['urbanareas'][t].filled(0).astype('f8')
    S = lambda x: (x * A15)[24:584][::-1]
    return {'urban': S(ur), 'paddy': S(rc), 'nonpaddy': S(np.maximum(ir - rc, 0)), 'rf': S(rf)}, S(np.ones_like(rf))
CHAIN = {'urban': ['urban', 'crop_any', 'low', 'uni'], 'paddy': ['paddy', 'nonpaddy', 'rf', 'low', 'uni'], 'nonpaddy': ['nonpaddy', 'paddy', 'rf', 'low', 'uni'], 'rf': ['rf', 'irr_any', 'low', 'uni']}
def wfield(name):
    if name == 'crop_any': return W['rf'] + W['nonpaddy'] + W['paddy']
    if name == 'irr_any': return W['nonpaddy'] + W['paddy']
    if name == 'low': return Wlow
    if name == 'uni': return land
    return W[name]
def allocate(T, Afull):
    Cv = {}; led = {}; alloc_tot = np.zeros((NY, NX))
    for cls in ('urban', 'paddy', 'nonpaddy', 'rf'):
        Tn = T[cls]; need = Tn > 0; remcap = np.maximum(land - alloc_tot, 0); Ln = blk(remcap); capn = Ln.sum(axis=(1, 3))
        wn = np.zeros(blk(land).shape); s = np.zeros(NB); lvl = np.zeros(NB, np.int8)
        for L, name in enumerate(CHAIN[cls], start=1):
            wf = blk(wfield(name)); f = need & (s == 0) & (wf.sum(axis=(1, 3)) > 0); wn = np.where(f[:, None, :, None], wf, wn); s = wn.sum(axis=(1, 3)); lvl[f] = L
        lvl[need & (s == 0)] = 9
        # single-child rule for small fallback parents
        small = need & (lvl >= 2) & (lvl < 9) & (Tn / Afull < SMALL)
        if small.any():
            flat = wn.transpose(0, 2, 1, 3).reshape(NB[0], NB[1], 9); kbest = flat.argmax(axis=2); one = np.zeros_like(flat); idx = np.where(small); one[idx[0], idx[1], kbest[idx]] = 1.0
            one = one.reshape(NB[0], NB[1], 3, 3).transpose(0, 2, 1, 3); wn = np.where(small[:, None, :, None], one * (blk(land) > 0), wn); s = wn.sum(axis=(1, 3))
        A = np.zeros_like(wn); rem = np.where(need, np.minimum(Tn, capn), 0.0); free = np.ones_like(wn, dtype=bool); it = 0; sat = 0; spill = 0
        while True:
            it += 1; ww = np.where(free, wn, 0.0); s2 = ww.sum(axis=(1, 3)); sp = (rem > 1e-6) & (s2 == 0)
            if sp.any(): ww = np.where(sp[:, None, :, None] & free, Ln, ww); s2 = ww.sum(axis=(1, 3)); spill += int(sp.sum())
            share = np.where(s2[:, None, :, None] > 0, ww / np.where(s2 == 0, 1, s2)[:, None, :, None], 0.0) * rem[:, None, :, None]
            newA = A + share; over = newA > Ln
            if not over.any() or it > 30: A = np.minimum(newA, Ln); break
            sat += int(over.sum()); A = np.where(over, Ln, newA); free &= ~over; rem = np.where(need, np.maximum(Tn - A.sum(axis=(1, 3)), 0), 0)
        al = A.reshape(NY, NX); alloc_tot += al
        with np.errstate(invalid='ignore', divide='ignore'): Cv[cls] = np.where(land > 0, al / np.where(land > 0, land, 1), 0)
        got = A.sum(axis=(1, 3))
        led[cls] = {'target_Mkm2': Tn.sum() * 1e-12, 'allocated_Mkm2': got.sum() * 1e-12, 'parents_with_target': int(need.sum()),
                    'fallback_parents_by_level': {f'L{L}:{CHAIN[cls][L-1]}': int((lvl == L).sum()) for L in range(2, len(CHAIN[cls]) + 1)} | {'L9:no_active_child': int((lvl == 9).sum())},
                    'cross_class_parents': int(((lvl >= 2) & (lvl < 9)).sum()), 'single_child_parents': int(small.sum()), 'single_child_area_km2': float(Tn[small].sum() * 1e-6),
                    'unplaced_over_capacity_km2': float(np.maximum(Tn - capn, 0)[need].sum() * 1e-6), 'unplaced_no_active_child_km2': float(Tn[lvl == 9].sum() * 1e-6),
                    'children_saturated': sat, 'spill_parents': spill, 'iterations': it, 'max_abs_conservation_error_km2_where_capacity_ok': float(np.abs(got - Tn)[need & (Tn <= capn + 1e-6)].max() * 1e-6),
                    'children_with_Cv_gt0': int((Cv[cls] > 0).sum())}
    r = np.where(mask, 1 - alloc_tot / np.where(land > 0, land, 1), 0)
    need = mask & (r > 1e-9) & ~(nat_sum > 1e-9); dkm = np.array([])
    if need.any(): dist, _ = treeN.query(xyz(LAT[need], LON[need])); dkm = 2 * RK * np.arcsin(np.clip(dist / 2, 0, 1))
    led['natural'] = {'min_residual': float(r[mask].min()), 'cells_residual_neg_lt_-1e-6': int((r[mask] < -1e-6).sum()), 'natural_Mkm2': float((np.maximum(r, 0) * land).sum() * 1e-12), 'cells_no_own_composition': int(need.sum()), 'of_which_le100km': int((dkm <= 100).sum()), 'of_which_barren': int((dkm > 100).sum())}
    return Cv, led
res = {'weights': 'VIC v5 2003-2022 mean pattern', 'small_share_threshold': SMALL, 'experiments': {}}; union_children = {k: np.zeros((NY, NX), bool) for k in CL}
for sc, y in TARGETS:
    T, Afull = targets(sc, y); Cv, led = allocate(T, Afull); res['experiments'][f'{sc}_{y}'] = led
    for k in CL: union_children[k] |= Cv[k] > 0
    print(sc, y, round(time.time() - t0), 's', flush=True)
res['allocation_union_children_over_8_targets'] = {k: int(v.sum()) for k, v in union_children.items()}
res['vic_union_2003_2022_children_(mean_pattern_gt0)'] = {k: int((P[k] > 0).sum()) for k in CL}
# existing bundle tiles (Cv > 0 in bundle v3) and the correct full union / new-tile sets per class
bnd = nc.Dataset(f'{VP}/outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc')
existing = {k: (bnd['Cv'][ki].filled(0) > 0) & mask for k, ki in CL.items()}
full = {k: existing[k] | union_children[k] for k in CL}; new = {k: union_children[k] & ~existing[k] for k in CL}
res['existing_bundle_v3_tiles'] = {k: int(v.sum()) for k, v in existing.items()}
res['full_union_tiles_existing_OR_allocated_8_targets'] = {k: int(v.sum()) for k, v in full.items()}
res['new_tiles_allocated_minus_existing_8_targets'] = {k: int(v.sum()) for k, v in new.items()}
res['existing_tiles_never_allocated_in_8_targets'] = {k: int((existing[k] & ~union_children[k]).sum()) for k in CL}
np.savez_compressed(f'{OUT}/annual_harmonize_prototype_15crops_union.npz', **{f'alloc_{k}': union_children[k] for k in CL}, **{f'existing_{k}': existing[k] for k in CL}, **{f'new_{k}': new[k] for k in CL})
res['runtime_s'] = time.time() - t0
json.dump(res, open(f'{OUT}/annual_harmonize_prototype_15crops.json', 'w'), indent=1, default=float)
# figures: fallback parents by level, children>0
keys = list(res['experiments']); fig, axs = plt.subplots(1, 4, figsize=(20, 4.6))
for ax, cls in zip(axs, ('rf', 'nonpaddy', 'paddy', 'urban')):
    levels = list(res['experiments'][keys[0]][cls]['fallback_parents_by_level']); x = np.arange(len(keys)); bottom = np.zeros(len(keys))
    for L, c in zip(levels, ('#E69F00', '#009E73', '#0072B2', '#CC79A7', '#000000')):
        v = np.array([res['experiments'][k][cls]['fallback_parents_by_level'][L] for k in keys]); ax.bar(x, v, bottom=bottom, color=c, label=L); bottom += v
    ax.set_xticks(x); ax.set_xticklabels(keys, rotation=35, ha='right', fontsize=8); ax.set_title(f'class {cls}: fallback parents by level', loc='left', fontsize=9); ax.legend(fontsize=7)
fig.text(0.01, 0.005, 'targets: landuse-15crops (rf = Σ*_rainfed*, paddy = rice_irrigated, nonpaddy = Σ*_irrigated* − rice_irrigated) + landuse-urbanareas; weights VIC v5 2003–2022 mean; single-child rule for parent share < 1e-3', fontsize=7, color='#555')
fig.tight_layout(); fig.savefig(f'{FIG}/p02_fallback_parents_by_level_15crops.png', dpi=140); plt.close(fig)
fig, ax = plt.subplots(figsize=(11, 4.4)); x = np.arange(len(keys)); w = 0.2
for i, (cls, c) in enumerate((('rf', '#009E73'), ('nonpaddy', '#D55E00'), ('paddy', '#CC79A7'), ('urban', '#0072B2'))):
    ax.bar(x + (i - 1.5) * w, [res['experiments'][k][cls]['children_with_Cv_gt0'] / 1e3 for k in keys], w, color=c, label=f'{cls} (existing bundle v3 {res["existing_bundle_v3_tiles"][cls]/1e3:.0f}k)')
ax.set_xticks(x); ax.set_xticklabels(keys, rotation=35, ha='right', fontsize=8); ax.set_ylabel('5′ children with Cv > 0 (thousand)'); ax.legend(fontsize=8); ax.set_title('Children with positive Cv per class and target (single-child rule for small fallback parents)', loc='left', fontsize=9)
fig.tight_layout(); fig.savefig(f'{FIG}/p03_children_gt0_by_target_15crops.png', dpi=140); plt.close(fig)
print(json.dumps({k: v for k, v in res.items() if k != 'experiments'}, indent=1))
for k, v in res['experiments'].items(): print(k, json.dumps({c: {a: b for a, b in v[c].items() if a in ('target_Mkm2', 'allocated_Mkm2', 'fallback_parents_by_level', 'cross_class_parents', 'single_child_parents', 'unplaced_over_capacity_km2', 'unplaced_no_active_child_km2', 'children_with_Cv_gt0')} for c in ('urban', 'paddy', 'nonpaddy', 'rf')}, default=float), json.dumps(v['natural']))
