#!/usr/bin/env python
"""
Mechanics test of the proposed conservative 15'->5' allocation (weights x water-filling) using the weights that ARE
available on disk: the VIC-WUR 2021 irrigated pattern (classes 14+15) as proxy for a HYDE-like 5' weight field.
HYDE itself is not available locally (no *hyde* file under vic_parameter / isimip4b / vic_coupled/Data), so this
script quantifies only the scheme mechanics: how many ISIMIP parents need a fallback (sum of weights == 0), how often
children saturate (A_i > active land area), how many water-filling iterations are needed, and the conservation error.

  w_i = max(proxy_i, 0) * land_i ;  A_i = A_parent * w_i / sum(w)  ;  cap A_i <= land_i (iterative water-filling)
Fallbacks tested when sum(w) == 0: (F1) uniform over active children; (F2) nearest parent (3x3 neighbourhood) pattern.
Run: /home/WUR/liu297/miniconda3/envs/py39/bin/python downscale_waterfill_test.py
"""
import os, json, numpy as np, netCDF4 as nc
import os as _os
WORKDIR = _os.environ["ISIMIP4B_WORKDIR"]  # project work directory (docs/directory-contracts.md)
def _external(var, what):
    """Inputs that are not yet part of this project (see README)."""
    v = _os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} to the path of {what}")
    return v
OUT = f'{WORKDIR}/analysis/irrigated-area-comparison'; os.makedirs(OUT, exist_ok=True)

F_DOM = f'{WORKDIR}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
R = 6371000.0
dom = nc.Dataset(F_DOM); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool)
A5 = ((R ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, vlon.size))
land = np.where(mask, A5, 0.0)                     # m2, active land per 5' cell
cov = nc.Dataset(f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_2021.nc')['coverage'][0]
proxy = np.nan_to_num(cov[13].filled(np.nan).astype('f8')) + np.nan_to_num(cov[14].filled(np.nan).astype('f8'))   # fraction
d = nc.Dataset(f'{OUT}/cellwise_comparison.nc'); Ai = d['A_isimip'][:].filled(0) * 1e6   # m2, ISIMIP 2021 on 720x1440 N->S
Ai = Ai[24:584][::-1]                                # rows covered by VIC, flipped to S->N -> (560, 1440)
NB = (vlat.size // 3, vlon.size // 3)
def blocks(x): return x.reshape(NB[0], 3, NB[1], 3)
def run(weights, label):
    w = blocks(np.maximum(weights, 0) * land); L = blocks(land); T = Ai.copy()
    sw = w.sum(axis=(1, 3)); cap = L.sum(axis=(1, 3))
    need = (T > 0); nofb = need & (sw == 0); overcap = need & (T > cap)
    res = {'weights': label, 'parents_with_target': int(need.sum()), 'target_total_km2': T.sum() * 1e-6,
           'parents_sum_w_zero': int(nofb.sum()), 'area_in_parents_sum_w_zero_km2': T[nofb].sum() * 1e-6,
           'parents_target_exceeds_land_capacity': int(overcap.sum()), 'excess_over_capacity_km2': np.maximum(T - cap, 0)[need].sum() * 1e-6}
    # allocation with water filling on parents with sum w > 0
    A = np.zeros_like(w); rem = np.where(sw > 0, T, 0.0); free = np.ones_like(w, dtype=bool); it = 0; sat_children = 0
    while True:
        it += 1
        ww = np.where(free, w, 0.0); s = ww.sum(axis=(1, 3))
        # spill rule: parents that still have area but whose weighted children are all saturated -> remaining
        # unsaturated active children get the remainder in proportion to their land area (documented fallback)
        spill = (rem > 1e-6) & (s == 0)
        if spill.any():
            ww = np.where(spill[:, None, :, None] & free, L, ww); s = ww.sum(axis=(1, 3))
            res['spill_events'] = res.get('spill_events', 0) + int(spill.sum())
        share = np.where(s[:, None, :, None] > 0, ww / np.where(s == 0, 1, s)[:, None, :, None], 0.0) * rem[:, None, :, None]
        newA = A + share; over = newA > L
        if not over.any(): A = newA; break
        # saturate over-capacity children, redistribute remainder next iteration
        sat_children += int(over.sum())
        A = np.where(over, L, newA); free &= ~over
        rem = T - A.sum(axis=(1, 3)); rem = np.where(sw > 0, np.maximum(rem, 0), 0.0)
        if it > 30: break
    alloc = A.sum(axis=(1, 3)); cons_err = (alloc - np.where(sw > 0, T, 0.0))
    res.update({'water_filling_iterations': it, 'children_saturated': sat_children,
                'conservation_abs_error_km2_parents_with_weights': float(np.abs(cons_err).sum() * 1e-6),
                'unallocated_after_saturation_km2': float(np.maximum(-cons_err, 0).sum() * 1e-6),
                'children_receiving_area': int((A > 0).sum()), 'children_receiving_area_but_proxy_zero': int(((A > 0) & (w == 0)).sum())})
    # F1 uniform fallback for parents with sw == 0
    Lb = L.copy(); capb = Lb.sum(axis=(1, 3)); fb = nofb & (capb > 0)
    A_fb = np.where(fb[:, None, :, None], Lb / np.where(capb == 0, 1, capb)[:, None, :, None] * T[:, None, :, None], 0.0)
    res['F1_uniform_fallback_parents'] = int(fb.sum()); res['F1_area_km2'] = float(A_fb.sum() * 1e-6)
    res['F1_children_new_irrigated_tiles'] = int((A_fb > 0).sum())
    res['parents_sum_w_zero_and_no_land'] = int((nofb & (capb == 0)).sum())
    # F2 nearest-parent pattern: does a 3x3 parent neighbourhood have weights?
    from scipy.ndimage import uniform_filter
    nb_has = uniform_filter((sw > 0).astype(float), 3) * 9 > 0.5
    res['F2_parents_sum_w_zero_with_neighbour_pattern'] = int((nofb & nb_has).sum()); res['F2_area_km2'] = float(T[nofb & nb_has].sum() * 1e-6)
    return res, A
results = []
r1, A1 = run(proxy, 'VIC 2021 irrigated fraction (classes 14+15)'); results.append(r1)
r2, A2 = run(np.where(mask, 1.0, 0.0), 'uniform over active land (no proxy)'); results.append(r2)
# how different are the two allocations at 5'?  (shows how much the proxy matters within parents)
diff = np.abs(A1 - A2).sum() * 1e-6 / 2
results.append({'weights': 'note', 'half_sum_abs_diff_between_VIC_proxy_and_uniform_allocation_km2': float(diff),
                'VIC_proxy_allocation_total_km2': float(A1.sum() * 1e-6), 'uniform_allocation_total_km2': float(A2.sum() * 1e-6)})
json.dump(results, open(f'{OUT}/downscale_waterfill_test.json', 'w'), indent=1)
print(json.dumps(results, indent=1))
