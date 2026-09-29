#!/usr/bin/env python
"""
Allocation-order sensitivity for the annual 15crops harmonization (targets histsoc 2021 and SSP1-VL 2050):
  seqA  : sequential water-filling urban -> paddy -> non-paddy -> rainfed (order used in annual_harmonize_prototype_15crops.py)
  seqB  : reversed order rainfed -> non-paddy -> paddy -> urban
  joint : order-free — every class first gets its unconstrained expected distribution E_k(i) = T_k W_k(i)/sum W_k;
          children where sum_k E_k(i) > land_i are saturated jointly (all classes scaled by the same factor at that child),
          each class's deficit is redistributed inside the parent over its still-free children (iterative), spill to uniform
          land weights when a class has no free weighted child left.
Fallback chains, single-child rule (share < 1e-3) and weights are identical in all three variants.
Metrics: per class, half-sum |Cv_variant - Cv_ref| * land (km2, area moved between children), number of children whose Cv differs
by > 1e-6, unplaced area; ref = joint.
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python order_sensitivity.py
"""
import os, json, time, numpy as np, netCDF4 as nc
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
F_V5 = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{y}.nc'
F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
F15 = {'histsoc': (f'{RAW}/histsoc/landuse-15crops_histsoc_15arcmin_annual_1850_2021.nc', 1850), 'ssp1vl': (f'{RAW}/ssp1vlsoc-noadapt/landuse-15crops_ssp1vl_15arcmin_annual_2022_2100.nc', 2022)}
FU = {'histsoc': f'{RAW}/histsoc/landuse-urbanareas_histsoc_15arcmin_annual_1850_2021.nc', 'ssp1vl': f'{RAW}/ssp1vlsoc-noadapt/landuse-urbanareas_ssp1vl_15arcmin_annual_2022_2100.nc'}
TARGETS = [('histsoc', 2021), ('ssp1vl', 2050)]
SMALL = 1e-3; R = 6371000.0
CL = {'urban': 12, 'paddy': 14, 'nonpaddy': 13, 'rf': 11}; LOWVEG = [5, 6, 7, 8, 9]
dom = nc.Dataset(F_DOM); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool)
A5 = ((R ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, vlon.size)); land = np.where(mask, A5, 0.0)
NY, NX = mask.shape; NB = (NY // 3, NX // 3)
def blk(x): return x.reshape(NB[0], 3, NB[1], 3)
years = list(range(2003, 2023)); n = len(years); P = {k: np.zeros((NY, NX)) for k in CL}; low = np.zeros((NY, NX))
for y in years:
    cov = nc.Dataset(F_V5.format(y=y))['coverage'][0]
    for k, ki in CL.items(): P[k] += np.nan_to_num(cov[ki].filled(np.nan)) / n
    for ki in LOWVEG: low += np.nan_to_num(cov[ki].filled(np.nan)) / n
W = {k: P[k] * land for k in CL}; Wlow = low * land
A15 = None
def targets(sc, y):
    global A15
    fn, y0 = F15[sc]; d = nc.Dataset(fn); t = y - y0; lat = d['lat'][:]
    if A15 is None: A15 = ((R ** 2) * np.deg2rad(0.25) * (np.sin(np.deg2rad(lat + 0.125)) - np.sin(np.deg2rad(lat - 0.125))))[:, None] * np.ones((1, 1440))
    rf = sum(d[v][t].filled(0).astype('f8') for v in d.variables if '_rainfed' in v); ir = sum(d[v][t].filled(0).astype('f8') for v in d.variables if '_irrigated' in v); rc = d['rice_irrigated'][t].filled(0).astype('f8'); d.close()
    ur = nc.Dataset(FU[sc])['urbanareas'][t].filled(0).astype('f8'); S = lambda x: (x * A15)[24:584][::-1]
    return {'urban': S(ur), 'paddy': S(rc), 'nonpaddy': S(np.maximum(ir - rc, 0)), 'rf': S(rf)}, S(np.ones_like(rf))
CHAIN = {'urban': ['urban', 'crop_any', 'low', 'uni'], 'paddy': ['paddy', 'nonpaddy', 'rf', 'low', 'uni'], 'nonpaddy': ['nonpaddy', 'paddy', 'rf', 'low', 'uni'], 'rf': ['rf', 'irr_any', 'low', 'uni']}
def wfield(name):
    if name == 'crop_any': return W['rf'] + W['nonpaddy'] + W['paddy']
    if name == 'irr_any': return W['nonpaddy'] + W['paddy']
    if name == 'low': return Wlow
    if name == 'uni': return land
    return W[name]
def weights_for(cls, Tn, Afull):
    """fallback chain + single-child rule -> per-child weight block for this class (same in all variants)"""
    need = Tn > 0; wn = np.zeros(blk(land).shape); s = np.zeros(NB); lvl = np.zeros(NB, np.int8)
    for L, name in enumerate(CHAIN[cls], start=1):
        wf = blk(wfield(name)); f = need & (s == 0) & (wf.sum(axis=(1, 3)) > 0); wn = np.where(f[:, None, :, None], wf, wn); s = wn.sum(axis=(1, 3)); lvl[f] = L
    small = need & (lvl >= 2) & (Tn / Afull < SMALL)
    if small.any():
        flat = wn.transpose(0, 2, 1, 3).reshape(NB[0], NB[1], 9); kbest = flat.argmax(axis=2); one = np.zeros_like(flat); idx = np.where(small); one[idx[0], idx[1], kbest[idx]] = 1.0
        one = one.reshape(NB[0], NB[1], 3, 3).transpose(0, 2, 1, 3); wn = np.where(small[:, None, :, None], one * (blk(land) > 0), wn)
    return wn
def fill_one(Tn, wn, Ln):
    """water-filling of one class into remaining capacity Ln (block), returns allocated block"""
    need = Tn > 0; capn = Ln.sum(axis=(1, 3)); A = np.zeros_like(wn); rem = np.where(need, np.minimum(Tn, capn), 0.0); free = np.ones_like(wn, dtype=bool)
    for it in range(40):
        ww = np.where(free, wn, 0.0); s2 = ww.sum(axis=(1, 3)); sp = (rem > 1e-6) & (s2 == 0)
        if sp.any(): ww = np.where(sp[:, None, :, None] & free, Ln, ww); s2 = ww.sum(axis=(1, 3))
        share = np.where(s2[:, None, :, None] > 0, ww / np.where(s2 == 0, 1, s2)[:, None, :, None], 0.0) * rem[:, None, :, None]
        newA = A + share; over = newA > Ln
        if not over.any(): A = newA; break
        A = np.where(over, Ln, newA); free &= ~over; rem = np.where(need, np.maximum(Tn - A.sum(axis=(1, 3)), 0), 0)
    return np.minimum(A, Ln)
def sequential(T, Afull, order):
    alloc = np.zeros((NY, NX)); out = {}
    for cls in order:
        Ln = blk(np.maximum(land - alloc, 0)); A = fill_one(T[cls], weights_for(cls, T[cls], Afull), Ln); a = A.reshape(NY, NX); alloc += a; out[cls] = a
    return out
def joint(T, Afull):
    cls_list = list(CL); wn = {c: weights_for(c, T[c], Afull) for c in cls_list}; Lb = blk(land)
    A = {c: np.zeros_like(Lb) for c in cls_list}; free = {c: np.ones_like(Lb, dtype=bool) for c in cls_list}
    capn = Lb.sum(axis=(1, 3)); tot = sum(T[c] for c in cls_list); scale_p = np.where(tot > capn, capn / np.where(tot == 0, 1, tot), 1.0)   # parent-level over-capacity -> proportional cut (unplaced)
    rem = {c: np.where(T[c] > 0, T[c] * scale_p, 0.0) for c in cls_list}; sat = np.zeros_like(Lb, dtype=bool)
    for it in range(60):
        inc = {}
        for c in cls_list:
            ww = np.where(free[c] & ~sat, wn[c], 0.0); s2 = ww.sum(axis=(1, 3)); sp = (rem[c] > 1e-6) & (s2 == 0)
            if sp.any(): ww = np.where(sp[:, None, :, None] & ~sat, Lb, ww); s2 = ww.sum(axis=(1, 3))
            inc[c] = np.where(s2[:, None, :, None] > 0, ww / np.where(s2 == 0, 1, s2)[:, None, :, None], 0.0) * rem[c][:, None, :, None]
        used = sum(A[c] for c in cls_list); prop = sum(inc[c] for c in cls_list); over = used + prop > Lb + 1e-9
        if not over.any():
            for c in cls_list: A[c] += inc[c]
            break
        f = np.where(over, np.maximum(Lb - used, 0) / np.where(prop == 0, 1, prop), 1.0)   # same factor for all classes at a saturated child
        for c in cls_list: A[c] += inc[c] * f; rem[c] = np.where(T[c] > 0, np.maximum(T[c] * scale_p - A[c].sum(axis=(1, 3)), 0), 0)
        sat |= over
        if all((rem[c] <= 1e-6).all() for c in cls_list): break
    return {c: A[c].reshape(NY, NX) for c in cls_list}, it + 1
res = {}
for sc, y in TARGETS:
    T, Afull = targets(sc, y)
    V = {'seqA_urban_paddy_np_rf': sequential(T, Afull, ['urban', 'paddy', 'nonpaddy', 'rf']), 'seqB_rf_np_paddy_urban': sequential(T, Afull, ['rf', 'nonpaddy', 'paddy', 'urban'])}
    J, nit = joint(T, Afull); V['joint'] = J; r = {'joint_iterations': nit}
    for name, out in V.items():
        r[name] = {c: {'allocated_Mkm2': float(out[c].sum() * 1e-12), 'unplaced_km2': float((T[c].sum() - out[c].sum()) * 1e-6)} for c in CL}
        if name != 'joint':
            for c in CL:
                d = out[c] - J[c]; r[name][c]['half_sum_abs_diff_vs_joint_km2'] = float(np.abs(d).sum() * 1e-6 / 2); r[name][c]['children_differing_gt_1e-6_fraction'] = int((np.abs(d / np.where(land > 0, land, 1)) > 1e-6).sum())
                r[name][c]['max_abs_diff_fraction'] = float(np.abs(d / np.where(land > 0, land, 1)).max())
        dAB = {c: float(np.abs(V['seqA_urban_paddy_np_rf'][c] - V['seqB_rf_np_paddy_urban'][c]).sum() * 1e-6 / 2) for c in CL}
        r['seqA_vs_seqB_half_sum_abs_diff_km2'] = dAB
    # children where any capacity conflict occurred (sum of unconstrained expectations > land)
    E = sum(T[c].repeat(3, 0).repeat(3, 1) * 0 for c in CL)
    res[f'{sc}_{y}'] = r; print(sc, y, json.dumps(r, indent=1), flush=True)
res['runtime_s'] = time.time() - t0
json.dump(res, open(f'{OUT}/order_sensitivity.json', 'w'), indent=1)
fig, axs = plt.subplots(1, 2, figsize=(12, 4.2))
for ax, (sc, y) in zip(axs, TARGETS):
    r = res[f'{sc}_{y}']; x = np.arange(4); w = 0.38
    ax.bar(x - w / 2, [r['seqA_urban_paddy_np_rf'][c]['half_sum_abs_diff_vs_joint_km2'] for c in CL], w, color='#E69F00', label='seq A (urban→paddy→np→rf) vs joint')
    ax.bar(x + w / 2, [r['seqB_rf_np_paddy_urban'][c]['half_sum_abs_diff_vs_joint_km2'] for c in CL], w, color='#0072B2', label='seq B (rf→np→paddy→urban) vs joint')
    ax.set_xticks(x); ax.set_xticklabels(list(CL)); ax.set_ylabel('area moved between children (km²)'); ax.set_title(f'{sc} {y}: order sensitivity of the 5′ allocation', loc='left', fontsize=9); ax.legend(fontsize=7); ax.set_yscale('symlog', linthresh=10)
fig.tight_layout(); fig.savefig(f'{FIG}/p06_allocation_order_sensitivity.png', dpi=140); plt.close(fig)
