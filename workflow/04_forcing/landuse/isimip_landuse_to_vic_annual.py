#!/usr/bin/env python3
"""ISIMIP4b landuse-15crops (+ landuse-urbanareas) 15' annual fractions -> VIC-WUR 5' annual Cv forcing (16 classes).

Produces one forcing unit, forcing/landuse/<soc-scenario>/, containing one file
coverage_<soc-scenario>_<year>.nc per year and provenance.yaml (docs/directory-contracts.md,
"Forcing unit and provenance record"). Method: Option 1, annual only; joint order-free
water-filling; VIC coverage 2003-2022 mean class pattern as within-parent weights.

Class mapping (ISIMIP -> VIC 1-based class):
  12 rainfed_crop            = sum of all *_rainfed* variables (17, incl. rice_rainfed and *_rainfed_bf)
  14 irrigated_non_paddy     = sum of all *_irrigated* variables (17) - rice_irrigated
  15 irrigated_paddy         = rice_irrigated
  13 urban                   = urbanareas
  pastures                   -> not mapped (natural remainder)
  1-11, 16                   = natural remainder r(i) = 1 - sum(12,13,14,15), split by the cell's VIC 2003-2022 mean
                               composition (nearest cell with composition <= 100 km if the cell has none; else 16 barren)
  closure                    the rounding residual 1 - sum goes to the largest class the cell already has (natural
                               first), never to a class with zero cover (method 1.3)
Algorithm per parent j (3x3 children i):
  T_k(j) = f_k(j) * A_full(j)                        (whole-cell fraction x spherical 15' area)
  W_k(i) = P_k(i) * land_i, P_k = VIC 2003-2022 mean fraction of class k; land_i = spherical 5' area x mask
  fallback chain when sum_i W_k(i) == 0 (recorded):  paddy: paddy->nonpaddy->rainfed->lowveg->uniform ;
        nonpaddy: nonpaddy->paddy->rainfed->lowveg->uniform ; rainfed: rainfed->irrigated->lowveg->uniform ;
        urban: urban->crop->lowveg->uniform
  single-child rule: fallback parent with T_k/A_full < SMALL -> whole target into one child (D04: SMALL = inf,
        i.e. every fallback parent; a finite --small reproduces the 2026-09-23 prototypes)
  joint water-filling: all classes get E_k(i) = T_k W_k(i)/sum W_k simultaneously; saturated children scale all
        classes' increments equally; deficits are redistributed within the parent; spill to uniform land weights
        when a class has no free weighted child; parents whose total target exceeds capacity are cut proportionally

Inputs (all under $ISIMIP4B_WORKDIR):
  raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-{15crops,urbanareas}_*_15arcmin_annual_*.nc
  raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_<2003..2022>.nc     (weights)
  parameters/<candidates|production>/<parameter-set-id>/domain/vic_global_5min_domain_nogl.nc
Outputs:
  forcing/landuse/<soc>/coverage_<soc>_<year>.nc, provenance.yaml (qc.status: not_checked)
      time: one step 0, units days since <year>-01-01 00:00:00, calendar proleptic_gregorian (the VIC clock
      calendar of the project; VIC aborts when a plugin forcing file has another calendar)
  qc/forcing/landuse/<soc>/reports/{ledger,qa}_<year>.{csv,json}
  scratch/landuse-converter/vic-coverage-mean-2003-2022-weights.npz (weights cache; becomes an
      intermediate cache once workflow/common/cache.py exists)
Rule 14 of the contract: accepted forcing is produced only from a clean repository. If the repository is
not clean, everything is written under scratch/landuse-converter/<soc>/ instead and provenance records
code_dirty: true. A forcing unit is generated as a whole: the producer refuses to write into an existing
forcing/landuse/<soc>/ (replacing an accepted unit needs the user's authorization; move it away first).
Years are converted in parallel with --processes (one year per process, about 6 GB each); the result does
not depend on the number of processes.

Usage: isimip_landuse_to_vic_annual.py --scenario histsoc --years 1850-2021 [--parameter-set ID]
       [--parameter-status candidates|production] [--small inf] [--union-mask file.nc] [--max-iter 60]
       [--processes N] [--scratch [--scratch-label LABEL]]
  --scratch-label puts a test run under scratch/landuse-converter/runs/<LABEL>/<soc>/ so that it does not
  replace another test run.
D04 (docs/decisions/D04-landuse-harmonization.md): every fallback parent uses a single child (--small inf,
the default); rice_rainfed and the *_bf bioenergy variables are part of the rainfed/irrigated sums.
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import yaml
from scipy.spatial import cKDTree

WORKDIR = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
CREATED_BY = 'workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py'
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
COVERAGE = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{{y}}.nc'
WEIGHT_YEARS = list(range(2003, 2023))
CACHE = f'{WORKDIR}/scratch/landuse-converter/vic-coverage-mean-2003-2022-weights.npz'
# soc scenario (ISIMIP specifier) -> (15crops file, urbanareas file, first year)
SCEN = {
    'histsoc': ('histsoc/landuse-15crops_histsoc_15arcmin_annual_1850_2021.nc', 'histsoc/landuse-urbanareas_histsoc_15arcmin_annual_1850_2021.nc', 1850),
    '1850soc': ('1850soc/landuse-15crops_1850soc_15arcmin_annual_1850_2021.nc', '1850soc/landuse-urbanareas_1850soc_15arcmin_annual_1850_2021.nc', 1850),
    '2021soc': ('2021soc/landuse-15crops_2021soc_15arcmin_annual_2022_2100.nc', '2021soc/landuse-urbanareas_2021soc_15arcmin_annual_2022_2100.nc', 2022),
    'ssp1vlsoc-noadapt': ('ssp1vlsoc-noadapt/landuse-15crops_ssp1vl_15arcmin_annual_2022_2100.nc', 'ssp1vlsoc-noadapt/landuse-urbanareas_ssp1vl_15arcmin_annual_2022_2100.nc', 2022),
    'ssp3hsoc-noadapt': ('ssp3hsoc-noadapt/landuse-15crops_ssp3h_15arcmin_annual_2022_2100.nc', 'ssp3hsoc-noadapt/landuse-urbanareas_ssp3h_15arcmin_annual_2022_2100.nc', 2022)}
CLASS_NAMES = ('evergreen_needleleaf|evergreen_broadleaf|deciduous_needleleaf|deciduous_broadleaf|mixed_forest|closed_shrubland|'
               'open_shrubland|woody_savanna|savanna|grassland|permanent_wetland|rainfed_crop|urban|irrigated_non_paddy_crop|'
               'irrigated_paddy_crop|barren')
CL = {'urban': 12, 'paddy': 14, 'nonpaddy': 13, 'rf': 11}          # 0-based indices of the managed classes
NATIDX = list(range(0, 11)) + [15]; LOWVEG = [5, 6, 7, 8, 9]
CHAIN = {'urban': ['urban', 'crop_any', 'low', 'uni'], 'paddy': ['paddy', 'nonpaddy', 'rf', 'low', 'uni'],
         'nonpaddy': ['nonpaddy', 'paddy', 'rf', 'low', 'uni'], 'rf': ['rf', 'irr_any', 'low', 'uni']}
R = 6371000.0; RK = 6371.0088; ROW0, ROW1 = 24, 584      # ISIMIP rows covered by the VIC domain (N->S)
METHOD_VERSION = '1.4'   # bump when results change for identical inputs (1.2: D04 default --small inf; 1.3: residual to an existing class;
                         # 1.4: time calendar proleptic_gregorian instead of standard, coverage unchanged)


def sha256(path, n=1 << 24):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(n), b''):
            h.update(b)
    return h.hexdigest()


def git_state():
    """(commit, dirty) of the repository; dirty means `git status --porcelain` prints anything."""
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout.strip())
    return commit, dirty


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sph_area(lat, d, nlon):
    a = (R ** 2) * np.deg2rad(d) * (np.sin(np.deg2rad(lat + d / 2)) - np.sin(np.deg2rad(lat - d / 2)))
    return a[:, None] * np.ones((1, nlon))


def blk(x, NB):
    return x.reshape(NB[0], 3, NB[1], 3)


def build_weights_cache(path, vlat, vlon, mask):
    """VIC 2003-2022 mean class fractions on the 5' grid (all 16 classes)."""
    n = len(WEIGHT_YEARS); NY, NX = mask.shape; P = np.zeros((16, NY, NX), 'f8')
    for y in WEIGHT_YEARS:
        d = nc.Dataset(COVERAGE.format(y=y)); assert np.allclose(d['lat'][:], vlat) and np.allclose(d['lon'][:], vlon)
        cov = d['coverage'][0]
        for k in range(16): P[k] += np.nan_to_num(cov[k].filled(np.nan)) / n
        d.close(); print(f'  weights: {y}', flush=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    P = P.astype('f4')  # stored and used at float32 so that results do not depend on whether the cache existed
    np.savez_compressed(path, P=P, years=np.array(WEIGHT_YEARS), source=COVERAGE)
    return P.astype('f8')


def close_cells(Cv, mask):
    """Closure guard: cells whose managed classes exceed 1 are rescaled (natural set to 0); in every other active
    cell the rounding residual 1 - sum(Cv) goes to a class the cell already has: the largest natural class, or the
    largest class when the cell has no natural class (method 1.3; 1.2 gave it to class 1 in such cells, creating
    class-1 cover of about 1e-16 that VIC must allocate as a tile). Returns (Cv, rescaled cells, cells whose
    residual went to a managed class)."""
    man = list(CL.values()); msum = Cv[man].sum(axis=0); over1 = mask & (msum > 1)
    Cv[man] = np.where(over1[None], Cv[man] / np.where(msum > 1, msum, 1)[None], Cv[man]); Cv[NATIDX] = np.where(over1[None], 0.0, Cv[NATIDX])
    resid = 1 - Cv.sum(axis=0)
    big_nat = np.argmax(np.where(np.isin(np.arange(16), NATIDX)[:, None, None], Cv, -1), axis=0)
    has_nat = np.take_along_axis(Cv, big_nat[None], 0)[0] > 0
    big = np.where(has_nat, big_nat, np.argmax(Cv, axis=0))
    present = np.take_along_axis(Cv, big[None], 0)[0] > 0
    add = np.where(mask & ~over1 & present, resid, 0); np.put_along_axis(Cv, big[None], np.take_along_axis(Cv, big[None], 0) + add[None], 0)
    return Cv, over1, int((mask & ~over1 & present & ~has_nat).sum())


def convert_year(scen, year, P, dom_grid, a, f15, furb):
    """Allocate one year; returns (Cv f4 array (16,NY,NX), qa dict, ledger rows)."""
    t0 = time.time(); vlat, vlon, mask = dom_grid; y0 = SCEN[scen][2]; t = year - y0
    NY, NX = mask.shape; NB = (NY // 3, NX // 3); land = np.where(mask, sph_area(vlat, 1 / 12., NX), 0.0); Lb = blk(land, NB)
    W = {k: P[ki] * land for k, ki in CL.items()}; Wlow = sum(P[k] for k in LOWVEG) * land
    natc = P[NATIDX]; nat_sum = natc.sum(axis=0)
    # ---------------- targets (m2 per parent, S->N)
    d = nc.Dataset(f15); assert 0 <= t < len(d['time']), f'year {year} outside {f15}'
    ilat = d['lat'][:]; A15 = sph_area(ilat, 0.25, 1440); assert np.abs(ilat[ROW0:ROW1][::-1] - vlat.reshape(NB[0], 3).mean(1)).max() < 1e-9
    rfv = [v for v in d.variables if '_rainfed' in v]; irv = [v for v in d.variables if '_irrigated' in v]
    assert len(rfv) == 17 and len(irv) == 17 and 'rice_irrigated' in irv
    rf = sum(d[v][t].filled(0).astype('f8') for v in rfv); ir = sum(d[v][t].filled(0).astype('f8') for v in irv)
    rc = d['rice_irrigated'][t].filled(0).astype('f8'); d.close()
    du = nc.Dataset(furb); ur = du['urbanareas'][t].filled(0).astype('f8'); du.close()
    assert (rc - ir).max() <= 1e-6, 'rice_irrigated exceeds irrigated sum'
    S = lambda x: (x * A15)[ROW0:ROW1][::-1]
    T = {'urban': S(ur), 'paddy': S(rc), 'nonpaddy': S(np.maximum(ir - rc, 0)), 'rf': S(rf)}; Afull = S(np.ones_like(rf))
    # ---------------- per-class weight blocks with fallback chain + single-child rule
    def wfield(name):
        if name == 'crop_any': return W['rf'] + W['nonpaddy'] + W['paddy']
        if name == 'irr_any': return W['nonpaddy'] + W['paddy']
        if name == 'low': return Wlow
        if name == 'uni': return land
        return W[name]
    wn, lvl, single = {}, {}, {}
    for c in CL:
        Tn = T[c]; need = Tn > 0; w = np.zeros(Lb.shape); s = np.zeros(NB); L = np.zeros(NB, np.int8)
        for li, name in enumerate(CHAIN[c], start=1):
            wf = blk(wfield(name), NB); f = need & (s == 0) & (wf.sum(axis=(1, 3)) > 0)
            w = np.where(f[:, None, :, None], wf, w); s = w.sum(axis=(1, 3)); L[f] = li
        L[need & (s == 0)] = 9
        sm = need & (L >= 2) & (L < 9) & (Tn / Afull < a.small)
        if sm.any():
            flat = w.transpose(0, 2, 1, 3).reshape(NB[0], NB[1], 9); kb = flat.argmax(axis=2); one = np.zeros_like(flat)
            idx = np.where(sm); one[idx[0], idx[1], kb[idx]] = 1.0
            one = one.reshape(NB[0], NB[1], 3, 3).transpose(0, 2, 1, 3); w = np.where(sm[:, None, :, None], one * (Lb > 0), w)
        wn[c], lvl[c], single[c] = w, L, sm
    # ---------------- joint order-free water-filling
    cls = list(CL); capn = Lb.sum(axis=(1, 3)); tot = sum(T[c] for c in cls)
    scale_p = np.where(tot > capn, capn / np.where(tot == 0, 1, tot), 1.0)
    A = {c: np.zeros_like(Lb) for c in cls}; free = {c: np.ones_like(Lb, dtype=bool) for c in cls}; sat = np.zeros_like(Lb, dtype=bool)
    rem = {c: np.where(T[c] > 0, T[c] * scale_p, 0.0) for c in cls}; spill = {c: 0 for c in cls}
    for it in range(1, a.max_iter + 1):
        inc = {}
        for c in cls:
            ww = np.where(free[c] & ~sat, wn[c], 0.0); s2 = ww.sum(axis=(1, 3)); sp = (rem[c] > 1e-6) & (s2 == 0)
            if sp.any(): ww = np.where(sp[:, None, :, None] & ~sat, Lb, ww); s2 = ww.sum(axis=(1, 3)); spill[c] += int(sp.sum())
            inc[c] = np.where(s2[:, None, :, None] > 0, ww / np.where(s2 == 0, 1, s2)[:, None, :, None], 0.0) * rem[c][:, None, :, None]
        used = sum(A[c] for c in cls); prop = sum(inc[c] for c in cls); over = used + prop > Lb + 1e-9
        if not over.any():
            for c in cls: A[c] += inc[c]
            break
        f = np.where(over, np.maximum(Lb - used, 0) / np.where(prop == 0, 1, prop), 1.0)
        for c in cls:
            A[c] += inc[c] * f; rem[c] = np.where(T[c] > 0, np.maximum(T[c] * scale_p - A[c].sum(axis=(1, 3)), 0), 0)
        sat |= over
        if all((rem[c] <= 1e-6).all() for c in cls): break
    Cv = np.zeros((16, NY, NX), 'f8')
    for c, ki in CL.items():
        al = A[c].reshape(NY, NX); Cv[ki] = np.where(land > 0, al / np.where(land > 0, land, 1), 0)
    # ---------------- natural remainder
    r = np.where(mask, 1 - Cv[list(CL.values())].sum(axis=0), 0); r = np.where(r < 0, 0, r)
    comp = natc / np.where(nat_sum > 1e-9, nat_sum, 1)[None]
    need = mask & (r > 1e-9) & ~(nat_sum > 1e-9); n_borrow = n_barren = 0
    if need.any():
        LAT, LON = np.meshgrid(vlat, vlon, indexing='ij'); ok = (nat_sum > 1e-9) & mask
        def xyz(la, lo):
            la = np.deg2rad(la); lo = np.deg2rad(lo)
            return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))
        tree = cKDTree(xyz(LAT[ok], LON[ok])); dist, idx = tree.query(xyz(LAT[need], LON[need]))
        dkm = 2 * RK * np.arcsin(np.clip(dist / 2, 0, 1)); oi, oj = np.where(ok); ni, nj = np.where(need); use = dkm <= 100
        comp[:, ni[use], nj[use]] = comp[:, oi[idx[use]], oj[idx[use]]]
        comp[:, ni[~use], nj[~use]] = 0; comp[11, ni[~use], nj[~use]] = 1.0     # index 11 in NATIDX = class 16 barren
        n_borrow, n_barren = int(use.sum()), int((~use).sum())
    for a_, ki in enumerate(NATIDX): Cv[ki] += r * comp[a_]
    Cv, over1, n_resid_managed = close_cells(Cv, mask)
    assert Cv[:, mask].min() > -1e-9, f'negative coverage {Cv[:, mask].min()}'
    Cv = np.maximum(Cv, 0); Cv = np.where(mask[None], Cv, np.nan).astype('f4')
    # ---------------- QA numbers and ledger
    got = {c: A[c].sum(axis=(1, 3)) for c in cls}
    cons = {}
    for c in cls:
        sel = (T[c] > 0) & (tot <= capn + 1e-6) & (lvl[c] < 9)
        cons[c] = float(np.abs(got[c] - T[c])[sel].max() * 1e-6) if sel.any() else 0.0
    closure = np.nansum(Cv, axis=0)
    qa = {'method_version': METHOD_VERSION, 'scenario': scen, 'year': year, 'small_share_threshold': a.small, 'joint_iterations': it,
          'totals_Mkm2': {c: {'target': float(T[c].sum() * 1e-12), 'allocated': float(got[c].sum() * 1e-12),
                              'unplaced_km2': float((T[c].sum() - got[c].sum()) * 1e-6)} for c in cls},
          'parents': {c: {'with_target': int((T[c] > 0).sum()),
                          'fallback_by_level': {**{f'L{L}:{CHAIN[c][L - 1]}': int((lvl[c] == L).sum()) for L in range(2, len(CHAIN[c]) + 1)},
                                                'L9:no_active_child': int((lvl[c] == 9).sum())},
                          'single_child': int(single[c].sum()), 'spill_events': spill[c],
                          'max_abs_conservation_error_km2_capacity_ok': cons[c]} for c in cls},
          'parents_over_total_capacity': int((tot > capn + 1e-6).sum()), 'children_saturated': int(sat.sum()),
          'natural': {'natural_Mkm2': float((r * land).sum() * 1e-12), 'cells_borrowed_composition_le100km': n_borrow, 'cells_barren_fallback': n_barren},
          'closure': {'cells_managed_sum_gt1_rescaled': int(over1.sum()), 'cells_residual_to_managed_class': n_resid_managed, 'max_abs_sum_minus_1_active': float(np.abs(closure[mask] - 1).max()),
                      'negative_values': int((Cv[:, mask] < 0).sum()), 'nan_active': int(np.isnan(Cv[:, mask]).sum()),
                      'finite_inactive': int(np.isfinite(Cv[:, ~mask]).sum())},
          'tiles_gt0': {c: int((Cv[ki][mask] > 0).sum()) for c, ki in CL.items()}, 'runtime_s': time.time() - t0}
    if a.union_mask:
        ub = nc.Dataset(a.union_mask)['class_union_bits'][:].filled(0).astype(np.uint16)
        viol = {k + 1: int(((np.nan_to_num(Cv[k]) > 0) & (((ub >> k) & 1) == 0)).sum()) for k in range(16)}
        qa['union_violations_by_class'] = viol
        if sum(viol.values()) > 0:
            raise SystemExit(f'ABORT: coverage > 0 outside union mask {viol}')
    plat = vlat.reshape(NB[0], 3).mean(1); plon = vlon.reshape(NB[1], 3).mean(1); ledger = []
    for c, vc in (('rf', 12), ('urban', 13), ('nonpaddy', 14), ('paddy', 15)):
        pi, pj = np.where(T[c] > 0)
        for i, j in zip(pi, pj):
            ledger.append(f'{i},{j},{plat[i]:.4f},{plon[j]:.4f},{vc},{T[c][i, j] * 1e-6:.6f},{got[c][i, j] * 1e-6:.6f},'
                          f'{(T[c][i, j] - got[c][i, j]) * 1e-6:.6f},{int(lvl[c][i, j])},{int(single[c][i, j])}')
    return Cv, qa, ledger


def write_coverage(fn, Cv, vlat, vlon, scen, year, attrs):
    o = nc.Dataset(fn, 'w', format='NETCDF4'); NY, NX = Cv.shape[1:]
    o.createDimension('time', 1); o.createDimension('veg_class', 16); o.createDimension('lat', NY); o.createDimension('lon', NX)
    v = o.createVariable('time', 'f8', ('time',)); v[:] = [0.0]; v.units = f'days since {year}-01-01 00:00:00'
    v.calendar = 'proleptic_gregorian'; v.standard_name = 'time'   # VIC aborts if it differs from its clock (method 1.4)
    v = o.createVariable('veg_class', 'i2', ('veg_class',)); v[:] = np.arange(1, 17); v.class_names = CLASS_NAMES
    v = o.createVariable('lat', 'f8', ('lat',)); v[:] = vlat; v.units = 'degrees_north'
    v = o.createVariable('lon', 'f8', ('lon',)); v[:] = vlon; v.units = 'degrees_east'
    v = o.createVariable('coverage', 'f4', ('time', 'veg_class', 'lat', 'lon'), zlib=True, complevel=4, fill_value=np.float32(np.nan))
    v[0] = Cv; v.units = '1'; v.long_name = 'annual vegetation coverage fraction'
    o.forcing_contract = 'PLUGIN_FORCE_TYPE CV coverage YEAR <prefix>'; o.soc_scenario = scen; o.year = year
    o.class_mapping = ('class12=sum(*_rainfed*, 17 vars); class15=rice_irrigated; class14=sum(*_irrigated*, 17 vars)-rice_irrigated; '
                       'class13=urbanareas; pastures->natural remainder')
    for k, val in attrs.items(): setattr(o, k, val)
    o.close()


# set by main() before the worker processes are forked; read-only in the workers
_JOB = {}


def produce_year(year):
    """Convert, write, and record one year (runs in a worker process); returns (year, runtime_s, closure)."""
    j = _JOB; a = j['args']
    Cv, qa, ledger = convert_year(a.scenario, year, j['P'], j['grid'], a, j['f15'], j['furb'])
    fn = f"{j['out']}/coverage_{a.scenario}_{year}.nc"
    write_coverage(fn + '.part', Cv, j['grid'][0], j['grid'][1], a.scenario, year, j['attrs'])
    os.replace(fn + '.part', fn)   # a file under its final name is always complete
    with open(f"{j['qcdir']}/ledger_{year}.csv", 'w') as fh:
        fh.write('parent_row,parent_col,lat,lon,class,target_km2,allocated_km2,unplaced_km2,fallback_level,single_child\n' + '\n'.join(ledger) + '\n')
    json.dump(qa, open(f"{j['qcdir']}/qa_{year}.json", 'w'), indent=1)
    print(f'{a.scenario} {year}: {qa["runtime_s"]:.0f} s, closure {qa["closure"]["max_abs_sum_minus_1_active"]:.1e}', flush=True)
    return year, qa['runtime_s'], qa['closure']['max_abs_sum_minus_1_active']


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(SCEN), help='ISIMIP soc-scenario specifier')
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--small', type=float, default=float('inf'),
                    help='single-child threshold on parent share; inf (default, D04) = every fallback parent')
    ap.add_argument('--union-mask', default=None, help='optional NetCDF with class_union_bits(lat,lon); coverage>0 outside it aborts')
    ap.add_argument('--max-iter', type=int, default=60)
    ap.add_argument('--processes', type=int, default=1, help='years converted in parallel (about 6 GB each)')
    ap.add_argument('--scratch', action='store_true',
                    help='test run: write under scratch/landuse-converter/ even from a clean repository')
    ap.add_argument('--scratch-label', default=None,
                    help='with --scratch: write under scratch/landuse-converter/runs/<LABEL>/<soc>/')
    a = ap.parse_args(); t0 = time.time()
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    y0 = SCEN[a.scenario][2]; y1 = 2021 if y0 == 1850 else 2100
    if years[0] < y0 or years[-1] > y1:
        raise SystemExit(f'{a.scenario} covers {y0}-{y1}, not {a.years}')
    commit, dirty = git_state()
    unit = f'landuse/{a.scenario}'
    to_scratch = dirty or a.scratch
    if a.scratch_label and not (a.scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs --scratch and lowercase words joined by hyphens')
    sbase = f'{WORKDIR}/scratch/landuse-converter' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
    out = f'{WORKDIR}/forcing/{unit}' if not to_scratch else f'{sbase}/{a.scenario}'
    qcdir = f'{WORKDIR}/qc/forcing/{unit}/reports' if not to_scratch else f'{out}/qc'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out} (not a forcing unit)', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty: a forcing unit is generated as a whole and an existing '
                         f'unit is replaced only with the user\'s authorization (move it away first)')
    os.makedirs(out, exist_ok=True); os.makedirs(qcdir, exist_ok=True)
    f15, furb, _ = SCEN[a.scenario]; f15 = f'{RAW}/{f15}'; furb = f'{RAW}/{furb}'
    f_dom = f'{WORKDIR}/parameters/{a.parameter_status}/{a.parameter_set}/domain/vic_global_5min_domain_nogl.nc'
    for p in (f15, furb, f_dom):
        if not os.path.isfile(p): raise SystemExit(f'missing input {p}')
    dom = nc.Dataset(f_dom); vlat = dom['lat'][:].filled(np.nan); vlon = dom['lon'][:].filled(np.nan); mask = dom['mask'][:].filled(0).astype(bool); dom.close()
    P = np.load(CACHE)['P'].astype('f8') if os.path.exists(CACHE) else build_weights_cache(CACHE, vlat, vlon, mask)
    created_at = utcnow()
    attrs = {'code_commit': commit, 'code_dirty': str(dirty).lower(), 'created_by': CREATED_BY, 'created_at': created_at,
             'forcing_unit': unit, 'method_version': METHOD_VERSION,
             'source_isimip': f'{os.path.relpath(f15, WORKDIR)}; {os.path.relpath(furb, WORKDIR)}',
             'source_weights': 'raw/external/vic-coverage-version-a/5 (2003-2022 mean class pattern)'}
    _JOB.update(args=a, P=P, grid=(vlat, vlon, mask), f15=f15, furb=furb, out=out, qcdir=qcdir, attrs=attrs)
    nproc = max(1, min(a.processes, len(years)))
    if nproc == 1:
        done = [produce_year(yy) for yy in years]
    else:
        # an executor (not a Pool) fails at once if a worker is killed, e.g. by the memory limit
        with ProcessPoolExecutor(nproc, mp_context=get_context('fork')) as ex:
            done = list(ex.map(produce_year, years))
    print(f'{len(done)} year(s), {nproc} process(es), {sum(d[1] for d in done) / len(done):.0f} s per year', flush=True)
    # ---------------- provenance of the whole unit (all coverage files present)
    files = sorted(f for f in os.listdir(out) if f.startswith(f'coverage_{a.scenario}_') and f.endswith('.nc'))
    prov = {
        'forcing_unit': unit, 'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at,
        'input_manifest': 'manifests/inputs/isimip4b-dkrz-2026-09-21/inventory.tsv',
        'inputs': [os.path.relpath(f15, WORKDIR), os.path.relpath(furb, WORKDIR), os.path.relpath(f_dom, WORKDIR)] +
                  [os.path.relpath(COVERAGE.format(y=yy), WORKDIR) for yy in WEIGHT_YEARS],
        'input_sha256': {'landuse-15crops': sha256(f15), 'landuse-urbanareas': sha256(furb), 'domain': sha256(f_dom)},
        'method': {'name': 'annual Cv, joint order-free water-filling', 'version': METHOD_VERSION, 'target_grid': 'vic-5arcmin',
                   'weights': 'VIC coverage 2003-2022 mean class pattern', 'calendar': 'proleptic_gregorian', 'single_child_threshold': a.small,
                   'union_mask': os.path.relpath(a.union_mask, WORKDIR) if a.union_mask else None, 'max_iter': a.max_iter,
                   'parameter_set': f'{a.parameter_status}/{a.parameter_set}'},
        'rebuild_command': f'python3 {CREATED_BY} --scenario {a.scenario} --years {years[0]}-{years[-1]} --parameter-set {a.parameter_set} --parameter-status {a.parameter_status} --small {a.small}'
                           + (' --scratch' if a.scratch else '') + (f' --scratch-label {a.scratch_label}' if a.scratch_label else ''),
        'files': [{'path': f, 'size_bytes': os.path.getsize(f'{out}/{f}'), 'sha256': sha256(f'{out}/{f}')} for f in files],
        'qc': {'status': 'not_checked', 'evidence': f'qc/forcing/{unit}'}}
    with open(f'{out}/provenance.yaml.part', 'w') as fh:
        yaml.safe_dump(prov, fh, sort_keys=False)
    os.replace(f'{out}/provenance.yaml.part', f'{out}/provenance.yaml')
    print(f'done: {len(years)} year(s) in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
