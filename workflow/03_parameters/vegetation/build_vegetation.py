#!/usr/bin/env python3
"""16-class VIC-WUR vegetation component: base bundle tiles + land-use tile union, backfilled parameters.

Builds parameters/<status>/<parameter-set>/vegetation/ from
  * the 16-class base bundle (bundle/vic_global_5min_humanimpact_16class_root-b-zeng2001.nc, adopted from
    vic_parameter, Version A 16-class): Cv, Nveg and the vegetation parameters of its 2003-2022 tile union;
  * the land-use forcing units forcing/landuse/<soc>/ of the five soc scenarios: every (cell, class) with
    coverage > 0 in any year of any unit must be a tile of the parameter file, because VIC allocates tiles
    only where the parameter Cv > 0 (vic_init.c) and stops when the forcing has Cv > 0 on a class that has
    no tile (lu_force.c);
  * the Koppen-Geiger 1991-2020 map of Beck et al. (2023), 1 km, for the donor ladder (D04 item 5).

Method
  tiles      final tiles = base tiles (Cv > 0) | land-use union; tiles added by the union get the placeholder
             Cv = 1e-12 and every active cell is renormalized to sum(Cv) = 1. The forcing replaces Cv at the
             first time step of a run (lu_force.c), so the placeholder only lets VIC allocate the tile.
  Nveg       number of tiles among classes 1-15 (class 16 barren is VIC's bare-soil class, Nbare = 1);
             VIC requires Nveg <= tiles <= Nveg + 1 (vic_init.c).
  backfill   every added tile gets all vegetation parameters (LAI, fcanopy, albedo, displacement, veg_rough
             (12 months), root_depth, root_fract (3 zones), overstory, rarc, rmin, RGL, rad_atten, wind_atten,
             trunk_ratio, wind_h) copied unchanged from ONE donor tile of the same class of the base bundle:
               L1 the same cell already has finite values for the class (kept as they are)
               L2 nearest same-class tile within 500 km (great circle)
               L3 nearest same-class tile with the same Koppen-Geiger class (5' majority of the 1 km map)
               L4 nearest same-class tile within +-2.5 degrees latitude
               L5 nearest same-class tile anywhere
             The level, donor cell and distance of every added tile are written to backfill_tiles.csv.
  fcanopy    floored at 1.001e-4 on every tile: VIC replaces fcanopy < MIN_FCANOPY = 1e-4 (vic_def.h) with a
             warning; 1.001e-4 stays above 1e-4 after a float32 round trip.
  LAI, fcanopy and albedo are the 12-month 2003-2022 climatology of the base bundle, read by VIC with
  LAI_SRC/FCAN_SRC/ALB_SRC = FROM_VEGPARAM; classes 12, 14 and 15 share one crop climatology (user,
  2026-10-01).

Reusable intermediates (the land-use tile union, keyed by the sha256 of every forcing file) are kept in
scratch/vegetation-component/ until workflow/common/cache.py exists.

Outputs: <out>/vic_global_5min_vegetation_16class_root-b-zeng2001.nc, <out>/backfill_tiles.csv,
<out>/provenance.yaml, and the build report <qc>/reports/build_report.json, where <out> is
parameters/<status>/<set>/vegetation/ and <qc> is qc/parameters/<status>/<set>/vegetation/. From a
repository that is not clean, or with --scratch, everything goes to scratch/vegetation-component/vegetation/
(qc under its qc/).

Usage: build_vegetation.py [--parameter-set ID] [--parameter-status candidates] [--processes 16] [--scratch]
"""
import argparse, csv, hashlib, json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
from scipy.spatial import cKDTree

from common import gitstate, hashing, provenance, workdir

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
CREATED_BY = 'workflow/03_parameters/vegetation/build_vegetation.py'
METHOD_VERSION = '1.0'
BASE_BUNDLE = 'bundle/vic_global_5min_humanimpact_16class_root-b-zeng2001.nc'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
OUT_NAME = 'vic_global_5min_vegetation_16class_root-b-zeng2001.nc'
KOPPEN = 'raw/external/koppen-geiger/beck2023/1991_2020/koppen_geiger_0p00833333.tif'
SOC = ('histsoc', '1850soc', '2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt')   # bit i of soc_bits
SCRATCH = 'scratch/vegetation-component'
NCLASS = 16
MONTHLY = ('LAI', 'fcanopy', 'albedo', 'displacement', 'veg_rough')
ROOT = ('root_depth', 'root_fract')
LIBRARY = ('overstory', 'rarc', 'rmin', 'RGL', 'rad_atten', 'wind_atten', 'trunk_ratio', 'wind_h')
FIELDS = MONTHLY + ROOT + LIBRARY
PLACEHOLDER_CV = 1e-12
FCANOPY_FLOOR = 1.001e-4
RADIUS_KM = 500.0
BAND_DEG = 2.5
RK = 6371.0088
LEVELS = {1: 'same_cell', 2: 'same_class_within_500km', 3: 'same_class_same_koppen', 4: 'same_class_latitude_band',
          5: 'same_class_global'}


# ---------------------------------------------------------------------------------------------- helpers
def git_state():
    """(commit, dirty) of the repository (common/gitstate.py)."""
    return gitstate.state(REPO)


def unit_sphere(lat, lon):
    la = np.deg2rad(np.asarray(lat, 'f8')); lo = np.deg2rad(np.asarray(lon, 'f8'))
    return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))


def chord_to_km(chord):
    return 2 * RK * np.arcsin(np.clip(chord / 2, 0, 1))


# ---------------------------------------------------------------------------------------------- core rules
def coverage_bits(cov, mask):
    """uint16 (ny, nx): bit k set where class k (0-based) has coverage > 0 on an active cell."""
    bits = np.zeros(mask.shape, np.uint16)
    for k in range(cov.shape[0]):
        bits |= ((np.nan_to_num(cov[k]) > 0) & mask).astype(np.uint16) << np.uint16(k)
    return bits


def bits_to_tiles(bits, nclass=NCLASS):
    """bool (nclass, ny, nx) from class bits."""
    return np.stack([((bits >> np.uint16(k)) & 1).astype(bool) for k in range(nclass)])


def extend_tiles(cv, union_bits, mask, eps=PLACEHOLDER_CV):
    """Add the union tiles to the base Cv. Returns (Cv f8 with NaN off the domain, Nveg i4, added tiles bool)."""
    base = np.nan_to_num(cv) > 0
    union = bits_to_tiles(union_bits, cv.shape[0]) & mask[None]
    added = union & ~base
    out = np.where(base, np.nan_to_num(cv), 0.0)
    out[added] = eps
    s = out.sum(axis=0)
    if (mask & (s <= 0)).any():
        raise ValueError(f'{int((mask & (s <= 0)).sum())} active cells without any tile')
    out = np.where(mask[None], out / np.where(s > 0, s, 1)[None], np.nan)
    nveg = np.where(mask, (out[:-1] > 0).sum(axis=0), -1).astype('i4')
    return out, nveg, added


def koppen_mode(kg, block=10, nclass=30):
    """Majority Koppen class of each block x block window (0 = no data is ignored; ties -> lowest class)."""
    ny, nx = kg.shape[0] // block, kg.shape[1] // block
    b = kg[:ny * block, :nx * block].reshape(ny, block, nx, block)
    counts = np.zeros((nclass + 1, ny, nx), np.int16)
    for c in range(1, nclass + 1):
        counts[c] = (b == c).sum(axis=(1, 3))
    mode = counts.argmax(axis=0).astype(np.uint8)
    return np.where(counts.max(axis=0) > 0, mode, 0).astype(np.uint8)


def choose_donors(t_lat, t_lon, t_kg, d_lat, d_lon, d_kg, radius_km=RADIUS_KM, band_deg=BAND_DEG):
    """Donor ladder L2-L5 for target tiles. Returns (level i1, donor index into d_*, distance km)."""
    n = len(t_lat)
    level = np.full(n, 5, np.int8); idx = np.zeros(n, np.int64); dist = np.zeros(n)
    if n == 0:
        return level, idx, dist
    if len(d_lat) == 0:
        raise ValueError('no donor tile for this class')
    txyz = unit_sphere(t_lat, t_lon); dxyz = unit_sphere(d_lat, d_lon)
    ch, ii = cKDTree(dxyz).query(txyz); km = chord_to_km(ch)
    idx[:] = ii; dist[:] = km                                   # L5 default: nearest anywhere
    l2 = km <= radius_km; level[l2] = 2
    rest = ~l2
    for c in np.unique(t_kg[rest & (t_kg > 0)]):              # L3: nearest with the same Koppen class
        sel_t = rest & (t_kg == c); dd = np.where(d_kg == c)[0]
        if dd.size == 0:
            continue
        ch3, i3 = cKDTree(dxyz[dd]).query(txyz[sel_t])
        level[sel_t] = 3; idx[sel_t] = dd[i3]; dist[sel_t] = chord_to_km(ch3)
    rest = level == 5
    if rest.any():                                            # L4: nearest within +-band_deg latitude
        order = np.argsort(d_lat); slat = np.asarray(d_lat)[order]
        for la in np.unique(t_lat[rest]):
            sel_t = rest & (t_lat == la)
            lo, hi = np.searchsorted(slat, la - band_deg - 1e-9), np.searchsorted(slat, la + band_deg + 1e-9, side='right')
            if hi <= lo:
                continue
            dd = order[lo:hi]
            ch4, i4 = cKDTree(dxyz[dd]).query(txyz[sel_t])
            level[sel_t] = 4; idx[sel_t] = dd[i4]; dist[sel_t] = chord_to_km(ch4)
    return level, idx, dist


def floor_fcanopy(fc, tiles, floor=FCANOPY_FLOOR):
    """fcanopy (months, ny, nx) with values below the floor raised on tiles; returns (array, count raised)."""
    low = tiles[None] & np.isfinite(fc) & (fc < floor)
    return np.where(low, floor, fc), int(low.sum())


# ---------------------------------------------------------------------------------------------- land-use union
_MASK = {}     # domain mask, set before the reader processes are forked


def _file_bits(path):
    with nc.Dataset(path) as d:
        cov = d['coverage'][0].filled(np.nan)
    return coverage_bits(cov, _MASK['mask'])


def landuse_units(W, require_accepted):
    """{soc: (unit dir, provenance dict)} for the five soc units; stops if a unit is missing or not accepted."""
    units = {}
    for soc in SOC:
        u = f'{W}/forcing/landuse/{soc}'; p = f'{u}/provenance.yaml'
        if not os.path.exists(p):
            raise SystemExit(f'missing land-use forcing unit {u}')
        prov = provenance.read(p)
        ok = prov.get('code_dirty') is False and (prov.get('qc') or {}).get('status') == 'passed'
        if not ok:
            msg = f'land-use unit {soc} is not accepted (code_dirty {prov.get("code_dirty")}, qc {prov.get("qc")})'
            if require_accepted:
                raise SystemExit(msg)
            print(f'warning: {msg}', file=sys.stderr)
        units[soc] = (u, prov)
    return units


def landuse_union(W, units, mask, processes):
    """Per-soc class bits (5, ny, nx) uint16, cached in scratch keyed by the sha256 of every coverage file."""
    files = [(soc, f) for soc, (u, prov) in units.items() for f in prov['files']]
    key = hashlib.sha256(json.dumps([(s, f['path'], f['sha256']) for s, f in files]).encode()).hexdigest()
    cache = f'{W}/{SCRATCH}/landuse-tile-union.nc'
    if os.path.exists(cache):
        with nc.Dataset(cache) as d:
            if getattr(d, 'input_fingerprint', None) == key and d['soc_class_bits'].shape[1:] == mask.shape:
                print(f'land-use union from {cache}', flush=True)
                return d['soc_class_bits'][:].filled(0).astype(np.uint16), key, cache
    t0 = time.time(); bits = np.zeros((len(SOC),) + mask.shape, np.uint16)
    jobs = [f'{units[s][0]}/{f["path"]}' for s, f in files]
    _MASK['mask'] = mask
    with ProcessPoolExecutor(processes, mp_context=get_context('fork')) as ex:   # fails at once if a worker dies
        for (s, f), b in zip(files, ex.map(_file_bits, jobs, chunksize=4)):
            bits[SOC.index(s)] |= b
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with nc.Dataset(cache + '.part', 'w') as d:
        d.createDimension('soc', len(SOC)); d.createDimension('lat', mask.shape[0]); d.createDimension('lon', mask.shape[1])
        v = d.createVariable('soc_class_bits', 'u2', ('soc', 'lat', 'lon'), zlib=True, complevel=4)
        v[:] = bits; v.description = 'bit k (0-based class) set where coverage > 0 in any year of the unit'
        d.soc_order = ' '.join(SOC); d.input_fingerprint = key; d.files = len(files); d.created_by = CREATED_BY
        d.purpose = 'reusable intermediate kept in scratch until workflow/common/cache.py exists'
    os.replace(cache + '.part', cache)
    print(f'land-use union of {len(files)} files in {time.time() - t0:.0f} s -> {cache}', flush=True)
    return bits, key, cache


def koppen_5arcmin(path, lat, lon):
    """5' majority Koppen class on the VIC grid (lat ascending) from the 1 km (1/120 degree) map."""
    import rasterio
    from rasterio.windows import Window
    res = 1 / 120.0; d5 = 1 / 12.0
    with rasterio.open(path) as ds:
        tr = ds.transform
        if not (abs(tr.a - res) < 1e-12 and abs(tr.e + res) < 1e-12 and abs(tr.c + 180) < 1e-9 and abs(tr.f - 90) < 1e-9):
            raise ValueError(f'unexpected Koppen grid {tr}')
        row0 = int(round((90 - (lat.max() + d5 / 2)) / res)); col0 = int(round((lon.min() - d5 / 2 + 180) / res))
        kg = ds.read(1, window=Window(col0, row0, len(lon) * 10, len(lat) * 10))
    return koppen_mode(kg)[::-1]                              # N->S map rows -> VIC rows S->N


# ---------------------------------------------------------------------------------------------- writer
def create_output(path, base, lat, lon, attrs):
    o = nc.Dataset(path, 'w', format='NETCDF4'); ny, nx = len(lat), len(lon)
    o.createDimension('veg_class', NCLASS); o.createDimension('month', 12); o.createDimension('root_zone', 3)
    o.createDimension('lat', ny); o.createDimension('lon', nx)
    for name in ('veg_class', 'month', 'root_zone', 'lat', 'lon'):
        src = base[name]; fill = getattr(src, '_FillValue', None)
        v = o.createVariable(name, src.dtype, src.dimensions, fill_value=fill)
        v.setncatts({a: src.getncattr(a) for a in src.ncattrs() if a not in ('_FillValue', 'eulaVlliF_')}); v[:] = src[:]
    comp = dict(zlib=True, complevel=4, shuffle=True)
    for name in ('Cv',) + FIELDS:
        src = base[name]; chunks = tuple(1 if dim in ('veg_class', 'month', 'root_zone') else min(s, 420 if dim == 'lat' else 1080)
                                         for dim, s in zip(src.dimensions, src.shape))
        v = o.createVariable(name, 'f8', src.dimensions, fill_value=np.nan, chunksizes=chunks, **comp)
        v.setncatts({a: src.getncattr(a) for a in src.ncattrs() if a not in ('_FillValue', 'eulaVlliF_')})
    v = o.createVariable('Nveg', 'i4', ('lat', 'lon'), fill_value=np.int32(-1), **comp)
    v.long_name = 'number of vegetation tiles among classes 1-15 (class 16 is bare soil)'
    v = o.createVariable('landuse_union_bits', 'u2', ('lat', 'lon'), **comp)
    v.long_name = 'bit k (0-based class): coverage > 0 in some year of some land-use forcing unit (all five soc scenarios)'
    v = o.createVariable('added_tile_bits', 'u2', ('lat', 'lon'), **comp)
    v.long_name = 'bit k (0-based class): tile added to the base bundle for the land-use union (placeholder Cv)'
    v = o.createVariable('backfill_level', 'i1', ('veg_class', 'lat', 'lon'), fill_value=np.int8(0),
                         chunksizes=(1, 420, 1080), **comp)
    v.long_name = 'donor level of an added tile: ' + '; '.join(f'{k} {n}' for k, n in LEVELS.items()) + '; 0 not added'
    for k, val in attrs.items():
        setattr(o, k, val)
    return o


# ---------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--processes', type=int, default=16, help='parallel readers of the land-use files')
    ap.add_argument('--scratch', action='store_true', help='test run: write under scratch/vegetation-component/')
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    commit, dirty = git_state(); to_scratch = dirty or a.scratch
    pset = f'{W}/parameters/{a.parameter_status}/{a.parameter_set}'
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/vegetation'
    out = f'{W}/{SCRATCH}/vegetation' if to_scratch else f'{W}/{rel_obj}'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{rel_obj}'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out}', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; a component is replaced only with the user\'s authorization')
    f_base, f_dom, f_kg = f'{pset}/{BASE_BUNDLE}', f'{pset}/{DOMAIN}', f'{W}/{KOPPEN}'
    for p in (f_base, f_dom, f_kg):
        if not os.path.isfile(p):
            raise SystemExit(f'missing input {p}')
    units = landuse_units(W, require_accepted=not to_scratch)
    os.makedirs(out, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)

    with nc.Dataset(f_dom) as d:
        mask = d['mask'][:].filled(0).astype(bool); lat = d['lat'][:].filled(np.nan); lon = d['lon'][:].filled(np.nan)
    base = nc.Dataset(f_base); base.set_auto_mask(False)
    if not (np.array_equal(base['lat'][:], lat) and np.array_equal(base['lon'][:], lon)):
        raise SystemExit('base bundle and domain grids differ')
    if base.dimensions['veg_class'].size != NCLASS:
        raise SystemExit('base bundle is not 16-class')

    soc_bits, union_key, union_cache = landuse_union(W, units, mask, a.processes)
    union = np.bitwise_or.reduce(soc_bits, axis=0)
    cv_base = base['Cv'][:]
    if (mask & ~(np.nan_to_num(cv_base) > 0).any(axis=0)).any():
        raise SystemExit('base bundle has active cells without tiles')
    cv, nveg, added = extend_tiles(cv_base, union, mask)
    tiles = np.nan_to_num(cv) > 0
    base_tiles = np.nan_to_num(cv_base) > 0
    del cv_base
    kg = koppen_5arcmin(f_kg, lat, lon)
    print(f'tiles: base {int(base_tiles.sum())}, added {int(added.sum())}, final {int(tiles.sum())}; '
          f'Koppen on active cells: {int((kg[mask] > 0).sum())} of {int(mask.sum())}', flush=True)

    sha = {'base_bundle': hashing.sha256(f_base), 'domain': hashing.sha256(f_dom), 'koppen': hashing.sha256(f_kg)}
    created_at = provenance.utcnow()
    attrs = {'title': 'VIC-WUR 16-class vegetation component with the land-use tile union',
             'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(), 'created_at': created_at,
             'method_version': METHOD_VERSION, 'parameter_set': f'{a.parameter_status}/{a.parameter_set}',
             'class_contract': '1-11 natural; 12 rainfed crop; 13 urban; 14 irrigated non-paddy; 15 irrigated paddy; 16 barren',
             'base_bundle': os.path.relpath(f_base, W), 'base_bundle_sha256': sha['base_bundle'],
             'landuse_union': 'coverage > 0 in any year of forcing/landuse/{' + ','.join(SOC) + '}',
             'landuse_union_fingerprint': union_key, 'placeholder_cv': PLACEHOLDER_CV, 'fcanopy_floor': FCANOPY_FLOOR,
             'vegetation_source_options': 'LAI_SRC FCAN_SRC ALB_SRC = FROM_VEGPARAM (12-month 2003-2022 climatology)',
             'backfill': 'one same-class donor tile per added tile, all parameters copied: ' +
                         '; '.join(f'L{k} {n}' for k, n in LEVELS.items()) + f' (radius {RADIUS_KM} km, band {BAND_DEG} deg)',
             'koppen': f'{KOPPEN} (Beck et al. 2023, 1991-2020), 5 arcmin majority of the 1 km map'}
    f_out = f'{out}/{OUT_NAME}'
    o = create_output(f_out + '.part', base, lat, lon, attrs)
    o['Cv'][:] = cv; o['Nveg'][:] = nveg
    o['landuse_union_bits'][:] = np.where(mask, union, 0)
    added_bits = np.zeros(mask.shape, np.uint16)
    for k in range(NCLASS):
        added_bits |= added[k].astype(np.uint16) << np.uint16(k)
    o['added_tile_bits'][:] = added_bits
    del cv

    report = {'method_version': METHOD_VERSION, 'created_at': created_at, 'code_commit': commit, 'code_dirty': dirty,
              'active_cells': int(mask.sum()), 'nveg_max': int(nveg.max()), 'classes': {}}
    rows_csv = []
    hist = bits_to_tiles(soc_bits[0]) & mask[None]
    union_tiles = bits_to_tiles(union) & mask[None]
    for k in range(NCLASS):
        tk = time.time()
        fields = {f: base[f][k] for f in FIELDS}
        finite = np.ones(mask.shape, bool)
        for f, x in fields.items():
            finite &= np.isfinite(x).all(axis=0) if x.ndim == 3 else np.isfinite(x)
        new = added[k]; l1 = new & finite; targ = new & ~finite
        donors = base_tiles[k] & finite
        missing_base = int((base_tiles[k] & ~finite).sum())
        if missing_base:
            raise SystemExit(f'class {k + 1}: {missing_base} base tiles without complete parameters')
        tr, tc = np.where(targ); dr, dc = np.where(donors)
        lev, di, dist = choose_donors(lat[tr], lon[tc], kg[tr, tc], lat[dr], lon[dc], kg[dr, dc])
        sr, sc = dr[di], dc[di]
        for f, x in fields.items():
            x[..., tr, tc] = x[..., sr, sc]
        fields['fcanopy'], n_floor = floor_fcanopy(fields['fcanopy'], tiles[k])
        level = np.zeros(mask.shape, np.int8); level[l1] = 1; level[tr, tc] = lev
        for f, x in fields.items():
            o[f][k] = x
        o['backfill_level'][k] = level
        lr, lc = np.where(l1)
        for r, c in zip(lr, lc):
            rows_csv.append((k + 1, r, c, lat[r], lon[c], 1, r, c, lat[r], lon[c], 0.0, kg[r, c], kg[r, c], int(sum(
                ((soc_bits[s, r, c] >> k) & 1) << s for s in range(len(SOC))))))
        for i in range(len(tr)):
            r, c, rr, cc = tr[i], tc[i], sr[i], sc[i]
            rows_csv.append((k + 1, r, c, lat[r], lon[c], int(lev[i]), rr, cc, lat[rr], lon[cc], float(dist[i]), kg[r, c],
                             kg[rr, cc], int(sum(((soc_bits[s, r, c] >> k) & 1) << s for s in range(len(SOC))))))
        hk = hist[k]
        report['classes'][str(k + 1)] = {
            'base_tiles': int(base_tiles[k].sum()), 'union_tiles_all_soc': int(union_tiles[k].sum()),
            'union_tiles_histsoc': int(hk.sum()), 'added_tiles_all_soc': int(new.sum()),
            'added_tiles_if_histsoc_only': int((hk & ~base_tiles[k]).sum()), 'final_tiles': int(tiles[k].sum()),
            'union_tiles_not_used_by_any_forcing': int((base_tiles[k] & ~union_tiles[k]).sum()),
            'backfill_levels': {f'L{L}_{n}': int((level == L).sum()) for L, n in LEVELS.items()},
            'donor_distance_km_quantiles': {str(q): float(np.percentile(dist, q)) for q in (50, 90, 99, 100)} if len(dist) else {},
            'fcanopy_values_floored': n_floor, 'runtime_s': round(time.time() - tk, 1)}
        print(f'class {k + 1}: added {int(new.sum())}, levels {report["classes"][str(k + 1)]["backfill_levels"]}, '
              f'fcanopy floored {n_floor}, {time.time() - tk:.0f} s', flush=True)
        o.sync()
    o.close(); base.close()
    os.replace(f_out + '.part', f_out)

    f_csv = f'{out}/backfill_tiles.csv'
    with open(f_csv + '.part', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['class', 'row', 'col', 'lat', 'lon', 'level', 'donor_row', 'donor_col', 'donor_lat', 'donor_lon',
                    'distance_km', 'koppen', 'donor_koppen', 'soc_bits'])
        for r in rows_csv:
            w.writerow([r[0], r[1], r[2], f'{r[3]:.6f}', f'{r[4]:.6f}', r[5], r[6], r[7], f'{r[8]:.6f}', f'{r[9]:.6f}',
                        f'{r[10]:.3f}', r[11], r[12], r[13]])
    os.replace(f_csv + '.part', f_csv)

    managed = tiles[11:15].any(axis=0); natural = tiles[list(range(11)) + [15]].any(axis=0)
    report['totals'] = {'base_tiles': int(base_tiles.sum()), 'added_tiles_all_soc': int(added.sum()),
                        'added_tiles_if_histsoc_only': int((hist & ~base_tiles).sum()), 'final_tiles': int(tiles.sum()),
                        'cells_with_added_tiles': int(added.any(axis=0).sum()),
                        'cells_managed_without_natural_tile': int((mask & managed & ~natural).sum()),
                        'soc_bits': {s: 1 << i for i, s in enumerate(SOC)}}
    report['runtime_s'] = round(time.time() - t0)
    json.dump(report, open(f'{qc}/reports/build_report.json', 'w'), indent=1)

    files = [{'path': os.path.basename(p), 'size_bytes': os.path.getsize(p), 'sha256': hashing.sha256(p),
              'md5': hashing.md5(p)} for p in (f_out, f_csv)]
    prov = {'object': rel_obj if not to_scratch else os.path.relpath(out, W), 'created_by': CREATED_BY,
            'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at, 'method_version': METHOD_VERSION,
            'inputs': {'base_bundle': os.path.relpath(f_base, W), 'domain': os.path.relpath(f_dom, W),
                       'koppen': KOPPEN, 'landuse_units': {s: {'path': os.path.relpath(u, W), 'code_commit': p['code_commit'],
                                                               'created_at': p['created_at'], 'files': len(p['files'])}
                                                           for s, (u, p) in units.items()}},
            'input_sha256': sha, 'landuse_union_fingerprint': union_key,
            'caches': [os.path.relpath(union_cache, W)],
            'method': {'placeholder_cv': PLACEHOLDER_CV, 'fcanopy_floor': FCANOPY_FLOOR, 'radius_km': RADIUS_KM,
                       'band_deg': BAND_DEG, 'levels': LEVELS, 'vegetation_source': 'FROM_VEGPARAM'},
            'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
                               + (' --scratch' if a.scratch else ''),
            'files': files, 'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
