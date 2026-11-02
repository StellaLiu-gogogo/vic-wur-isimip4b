#!/usr/bin/env python3
"""Soil component with the five 2-degree calibration fields of the baseflow smoothed (task Z).

Writes parameters/<status>/<set>/soil/vic_global_5min_soil_calibration-smoothed.nc: every non-vegetation variable
of the base bundle (the assembled image-driver file of the base parameter set,
bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc, whose provenance.yaml lists them as
natural_variables), the coordinates and the global attributes. 46 variables are copied bitwise, 7 are changed:
depth (layer 2 only), Ds, Dsmax, Ws, c, max_moist (layer 2 only) and init_moist (layer 2 only).

Method (version 1.0, user 2026-11-02)
  blocks     in the base set the depth of layer 2 and the NIJSSEN2001 baseflow parameters Ds, Dsmax, Ws and c are
             constant over 2-degree blocks (they were calibrated on a 2-degree grid): latitude edges on even
             degrees everywhere; longitude edges on even degrees east of 0 and on odd degrees west of 0 (the
             negative longitudes were rounded the other way when the blocks were mapped), so the blocks
             [-180, -179] and [-1, 0] are one degree wide. A block with active cells takes the one value of its
             cells (uniform block) or the most frequent value (mixed block, almost all coastal; ties take the
             smallest value); a block without active cells (empty) takes the value of the nearest land block on the
             sphere (great-circle distance between block centres).
  smoothing  bilinear interpolation between the block centres on every active cell: linear in latitude between the
             two nearest centre rows (beyond the outermost rows the nearest row alone), linear in longitude between
             the two nearest centre columns, periodic across 180 degrees. A block centre keeps its value, every cell
             lies between the values of the four blocks around it, and the steps at the block edges disappear.
  dependent  max_moist[2] = depth[2] x (1 - bulk_density / soil_density) x 1000 mm, in double precision;
             init_moist[2] = (init_moist[2] / max_moist[2] of the base) x the new max_moist[2]; layers 1 and 3 are
             unchanged. The root zones of the vegetation follow in vegetation/recompute_roots.py.
  precision  the new values are written in double precision (the base holds float32-representable values).
  inactive   cells outside the domain mask keep the stored fill values of the base, bitwise.

Outputs: the component file, calibration_blocks.csv (one row per block and field: block indices and edges, kind,
value, number of active cells, share of the most frequent value, donor block of an empty block), provenance.yaml
and the build report qc/parameters/<status>/<set>/soil/reports/build_report.json. From a repository that is not
clean, or with --scratch, everything goes to scratch/soil-component/soil/ (qc under its qc/).

Usage: smooth_calibration_fields.py [--parameter-set vic-global-5arcmin-version-b] [--base-set vic-global-5arcmin-version-a]
       [--parameter-status candidates] [--scratch] [--expect-commit SHA]
"""
import argparse, csv, json, os, sys, time

import numpy as np
import netCDF4 as nc
from scipy.spatial import cKDTree

from common import gitstate, hashing, provenance, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'bundle'))
import assemble_bundle as ab   # noqa: E402  (the bitwise variable copy of the bundle assembly and the file names)

CREATED_BY = 'workflow/03_parameters/soil/smooth_calibration_fields.py'
METHOD_VERSION = '1.0'
BASE_BUNDLE = f'bundle/{ab.OUT_NAME}'
DOMAIN = ab.DOMAIN
OUT_NAME = 'vic_global_5min_soil_calibration-smoothed.nc'
BLOCKS_CSV = 'calibration_blocks.csv'
SCRATCH = 'scratch/soil-component'
BLOCK_DEG = 2.0
FIELDS = ('depth', 'Ds', 'Dsmax', 'Ws', 'c')          # smoothed; depth in layer 2 only
LAYER = 1                                              # 0-based index of layer 2
DEPENDENT = ('max_moist', 'init_moist')                # recomputed in layer 2
CHANGED = FIELDS + DEPENDENT
KINDS = {0: 'empty', 1: 'uniform', 2: 'mixed'}
RK = 6371.0088                                         # km, for the reported distance of a fill donor


# ---------------------------------------------------------------------------------------------- block geometry
def block_edges(lat, lon, block=BLOCK_DEG):
    """(latitude edges, longitude edges) of the 2-degree blocks of the base set: latitude edges on even degrees
    covering the grid; longitude edges on odd degrees west of 0 and even degrees east of 0, with -180 and 0."""
    lat0 = np.floor(lat.min() / block) * block; lat1 = np.ceil(lat.max() / block) * block
    lat_edges = np.arange(lat0, lat1 + 1e-9, block)
    west = np.arange(-180.0 + block / 2, 0.0, block)       # -179, -177, ..., -1
    east = np.arange(block, 180.0 + 1e-9, block)           # 2, 4, ..., 180
    lon_edges = np.concatenate(([-180.0], west, [0.0], east))
    if lon.min() < -180 or lon.max() >= 180:
        raise ValueError('longitudes must lie in [-180, 180)')
    return lat_edges, lon_edges


def block_index(edges, x):
    """Index of the block [edges[i], edges[i + 1]) holding every value of x."""
    i = np.searchsorted(edges, x, side='right') - 1
    if (i < 0).any() or (i >= len(edges) - 1).any():
        raise ValueError('a cell lies outside the blocks')
    return i


def centres(edges):
    return (edges[:-1] + edges[1:]) / 2


# ---------------------------------------------------------------------------------------------- block values
def recover_blocks(x, mask, bi, bj, shape):
    """Value of every block from its active cells: the one value of a uniform block, the most frequent value of a
    mixed block (ties: the smallest value), NaN for an empty block. x (ny, nx) with NaN where there is no value;
    bi (ny,), bj (nx,) block indices of the rows and columns; shape (nbi, nbj).
    Returns values, kind (int8: 0 empty, 1 uniform, 2 mixed), n_active, share of the block value among the active
    cells, each (nbi, nbj)."""
    nbi, nbj = shape
    rows, cols = np.nonzero(mask & np.isfinite(x))
    uniq, code = np.unique(x[rows, cols], return_inverse=True)
    block = bi[rows] * nbj + bj[cols]
    counts = np.zeros((nbi * nbj, uniq.size), np.int32)
    np.add.at(counts, (block, code), 1)
    n_act = counts.sum(axis=1)
    best = counts.argmax(axis=1)                            # the first maximum: the smallest of tied values
    values = np.where(n_act > 0, uniq[best], np.nan)
    n_distinct = (counts > 0).sum(axis=1)
    kind = np.where(n_act == 0, 0, np.where(n_distinct == 1, 1, 2)).astype(np.int8)
    share = np.where(n_act > 0, counts.max(axis=1) / np.maximum(n_act, 1), np.nan)
    return values.reshape(shape), kind.reshape(shape), n_act.reshape(shape), share.reshape(shape)


def unit_sphere(lat, lon):
    la = np.deg2rad(np.asarray(lat, 'f8')); lo = np.deg2rad(np.asarray(lon, 'f8'))
    return np.column_stack((np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)))


def fill_empty(values, clat, clon):
    """Empty blocks (NaN) take the value of the nearest block with a value (great-circle distance between block
    centres). Returns (filled values, donor (nbi, nbj) flat index of the donor block or -1, distance km or 0)."""
    land = np.isfinite(values)
    if not land.any():
        raise ValueError('no block has a value')
    I, J = np.meshgrid(np.arange(values.shape[0]), np.arange(values.shape[1]), indexing='ij')
    xyz = unit_sphere(clat[I].ravel(), clon[J].ravel())
    land_flat = land.ravel(); idx_land = np.flatnonzero(land_flat)
    chord, k = cKDTree(xyz[idx_land]).query(xyz[~land_flat])
    donor = np.full(values.size, -1, np.int64); dist = np.zeros(values.size)
    donor[~land_flat] = idx_land[k]; dist[~land_flat] = 2 * RK * np.arcsin(np.clip(chord / 2, 0, 1))
    filled = values.copy(); filled[~land] = values.ravel()[donor[~land_flat]]
    return filled, donor.reshape(values.shape), dist.reshape(values.shape)


# ---------------------------------------------------------------------------------------------- interpolation
def interpolation_indices(clat, clon, lat, lon):
    """For every row the two centre rows it lies between (i0, i1, weight of i1; beyond the outermost centres the
    weight is 0 or 1, i.e. the nearest row alone) and for every column the two centre columns (periodic across
    180 degrees: the last centre - 360 and the first + 360 close the circle)."""
    i1 = np.clip(np.searchsorted(clat, lat), 1, len(clat) - 1); i0 = i1 - 1
    wi = np.clip((lat - clat[i0]) / (clat[i1] - clat[i0]), 0.0, 1.0)
    ext = np.concatenate(([clon[-1] - 360.0], clon, [clon[0] + 360.0]))
    j1 = np.searchsorted(ext, lon); j0 = j1 - 1
    wj = (lon - ext[j0]) / (ext[j1] - ext[j0])
    n = len(clon)
    return i0, i1, wi, (j0 - 1) % n, (j1 - 1) % n, wj


def bilinear(filled, clat, clon, lat, lon):
    """Bilinear interpolation of the block values (block centres clat, clon) on the cell centres (lat, lon). The
    result is clipped to the smallest and largest of the four block values around every cell, so that rounding
    (weights that sum to 1 within 1e-16) never puts a cell outside the range of its blocks."""
    i0, i1, wi, j0, j1, wj = interpolation_indices(clat, clon, lat, lon)
    a, b = (1 - wi)[:, None], wi[:, None]
    c, d = (1 - wj)[None, :], wj[None, :]
    four = np.stack([filled[np.ix_(i0, j0)], filled[np.ix_(i0, j1)], filled[np.ix_(i1, j0)], filled[np.ix_(i1, j1)]])
    f = four[0] * a * c + four[1] * a * d + four[2] * b * c + four[3] * b * d
    return np.clip(f, four.min(axis=0), four.max(axis=0))


def smooth_field(x, mask, lat, lon):
    """The smoothed field of x on the active cells (NaN elsewhere) and the block record (values, kind, n_active,
    share, filled values, donor, donor distance, edges)."""
    lat_edges, lon_edges = block_edges(lat, lon)
    bi, bj = block_index(lat_edges, lat), block_index(lon_edges, lon)
    shape = (len(lat_edges) - 1, len(lon_edges) - 1)
    values, kind, n_act, share = recover_blocks(x, mask, bi, bj, shape)
    clat, clon = centres(lat_edges), centres(lon_edges)
    filled, donor, dist = fill_empty(values, clat, clon)
    y = bilinear(filled, clat, clon, lat, lon)
    return np.where(mask, y, np.nan), {'values': values, 'kind': kind, 'n_active': n_act, 'share': share,
                                       'filled': filled, 'donor': donor, 'donor_km': dist,
                                       'lat_edges': lat_edges, 'lon_edges': lon_edges}


def porosity(bulk_density, soil_density):
    return 1.0 - bulk_density / soil_density


def area_mean(x, mask, area):
    w = np.where(mask & np.isfinite(x), area, 0.0)
    return float(np.nansum(np.where(w > 0, x, 0.0) * w) / w.sum())


# ---------------------------------------------------------------------------------------------- main
def stored(ds, name):
    """Stored values (no masking) and the fill value of a variable."""
    v = ds[name]; v.set_auto_maskandscale(False)
    fill = v.getncattr('_FillValue') if '_FillValue' in v.ncattrs() else None
    return np.asarray(v[:]), fill


def as_nan(x, fill):
    x = x.astype('f8')
    return np.where(x == fill, np.nan, x) if fill is not None and not np.isnan(fill) else x


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-b')
    ap.add_argument('--base-set', default='vic-global-5arcmin-version-a',
                    help='parameter set whose assembled bundle and domain are the inputs')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--scratch', action='store_true', help=f'test run: write under {SCRATCH}/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script for an accepted output: stop unless the repository is clean and at '
                         'this commit')
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    commit, dirty = gitstate.state(REPO); to_scratch = dirty or a.scratch
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    base_rel = f'parameters/{a.parameter_status}/{a.base_set}'; base = f'{W}/{base_rel}'
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/soil'
    out = f'{W}/{SCRATCH}/soil' if to_scratch else f'{W}/{rel_obj}'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{rel_obj}'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out}', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; a component is replaced only with the user\'s authorization')
    f_base, f_dom, f_bprov = f'{base}/{BASE_BUNDLE}', f'{base}/{DOMAIN}', f'{base}/bundle/provenance.yaml'
    for p in (f_base, f_dom, f_bprov):
        if not os.path.isfile(p):
            raise SystemExit(f'missing input {p}')
    bprov = provenance.read(f_bprov)
    if not to_scratch and ((bprov.get('qc') or {}).get('status') != 'passed' or bprov.get('code_dirty') is not False):
        raise SystemExit(f'the base bundle {f_base} is not accepted (qc {bprov.get("qc")}, code_dirty {bprov.get("code_dirty")})')
    natural = list(bprov['method']['natural_variables'])
    os.makedirs(out, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)

    src = nc.Dataset(f_base)
    lat = np.asarray(src['lat'][:], 'f8'); lon = np.asarray(src['lon'][:], 'f8')
    with nc.Dataset(f_dom) as d:
        d.set_auto_mask(False)
        mask = np.asarray(d['mask'][:]) == 1; area = np.asarray(d['area'][:], 'f8')
        if not (np.array_equal(np.asarray(d['lat'][:]), lat) and np.array_equal(np.asarray(d['lon'][:]), lon)):
            raise SystemExit('base bundle and domain grids differ')
    run_cell, _ = stored(src, 'run_cell')
    if not np.array_equal(run_cell == 1, mask):
        raise SystemExit('run_cell of the base bundle differs from the domain mask')
    for v in natural:
        if ab.VEG_DIM in src[v].dimensions:
            raise SystemExit(f'{v} is listed as a natural variable but has the dimension {ab.VEG_DIM}')
    missing = [v for v in CHANGED if v not in natural]
    if missing:
        raise SystemExit(f'variables to change are not natural variables of the base bundle: {missing}')

    # ---- the smoothed fields and the dependent layer-2 variables
    depth_raw, depth_fill = stored(src, 'depth')
    bd = as_nan(*stored(src, 'bulk_density')); sd = as_nan(*stored(src, 'soil_density'))
    mm_raw, mm_fill = stored(src, 'max_moist'); im_raw, im_fill = stored(src, 'init_moist')
    new = {}; blocks = {}; report = {'method_version': METHOD_VERSION, 'fields': {}}
    for name in FIELDS:
        tf = time.time()
        if name == 'depth':
            x = as_nan(depth_raw[LAYER], depth_fill)
        else:
            x = as_nan(*stored(src, name))
        if np.isnan(x[mask]).any():
            raise SystemExit(f'{name}: {int(np.isnan(x[mask]).sum())} active cells without a value')
        y, b = smooth_field(x, mask, lat, lon)
        new[name] = y; blocks[name] = b
        kind = b['kind']; land = kind > 0
        rep = {'blocks': int(kind.size), 'empty': int((kind == 0).sum()), 'uniform': int((kind == 1).sum()),
               'mixed': int((kind == 2).sum()),
               'mixed_minority_share_quantiles': {str(q): float(np.percentile(1 - b['share'][kind == 2], q))
                                                  for q in (50, 90, 100)} if (kind == 2).any() else {},
               'fill_distance_km_quantiles': {str(q): float(np.percentile(b['donor_km'][kind == 0], q))
                                              for q in (50, 90, 100)} if (kind == 0).any() else {},
               'block_value_range': [float(np.nanmin(b['values'])), float(np.nanmax(b['values']))],
               'cell_range_base': [float(np.nanmin(x[mask])), float(np.nanmax(x[mask]))],
               'cell_range_new': [float(np.nanmin(y[mask])), float(np.nanmax(y[mask]))],
               'area_mean_base': area_mean(x, mask, area), 'area_mean_new': area_mean(y, mask, area),
               'cells_changed': int((y[mask] != x[mask]).sum()), 'max_abs_change': float(np.nanmax(np.abs(y - x)[mask])),
               'runtime_s': round(time.time() - tf, 1)}
        rep['area_mean_relative_change'] = rep['area_mean_new'] / rep['area_mean_base'] - 1
        report['fields'][name] = rep
        print(f'{name}: {rep["uniform"]} uniform, {rep["mixed"]} mixed, {rep["empty"]} empty blocks; area mean '
              f'{rep["area_mean_base"]:.6g} -> {rep["area_mean_new"]:.6g} ({rep["area_mean_relative_change"] * 100:+.2f} %)',
              flush=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        por2 = porosity(bd[LAYER], sd[LAYER])
        mm2_new = new['depth'] * por2 * 1000.0
        ratio = as_nan(im_raw[LAYER], im_fill) / as_nan(mm_raw[LAYER], mm_fill)
        im2_new = ratio * mm2_new
    for nm, arr in (('porosity', por2), ('max_moist', mm2_new), ('init_moist', im2_new)):
        if np.isnan(arr[mask]).any():
            raise SystemExit(f'layer-2 {nm}: {int(np.isnan(arr[mask]).sum())} active cells without a value')
    report['dependent'] = {'porosity_layer2_range': [float(por2[mask].min()), float(por2[mask].max())],
                           'max_moist_layer2_range_mm': [float(mm2_new[mask].min()), float(mm2_new[mask].max())],
                           'init_ratio_layer2_range': [float(ratio[mask].min()), float(ratio[mask].max())],
                           'init_moist_layer2_range_mm': [float(im2_new[mask].min()), float(im2_new[mask].max())]}
    new['max_moist'] = mm2_new; new['init_moist'] = im2_new

    # ---- the component file: every natural variable, 7 with new values on the active cells
    sha = {'base_bundle': hashing.sha256(f_base), 'domain': hashing.sha256(f_dom), 'base_provenance': hashing.sha256(f_bprov)}
    created_at = provenance.utcnow()
    restrictions = ab.source_restrictions(src)
    f_out = f'{out}/{OUT_NAME}'; part = f_out + '.part'
    o = nc.Dataset(part, 'w', format='NETCDF4')
    dims = {}
    for v in list(ab.COORDS) + natural:
        for dn in src[v].dimensions:
            dims[dn] = len(src.dimensions[dn])
    for dn, n in dims.items():
        o.createDimension(dn, n)
    for v in ab.COORDS:
        ab.copy_variable(src, o, v)
    copied = []
    for v in natural:
        ab.copy_variable(src, o, v)
        if v not in CHANGED:
            copied.append(v); continue
        var = o[v]; var.set_auto_maskandscale(False)
        if v in ('depth', 'max_moist', 'init_moist'):
            layer = np.asarray(var[LAYER]).astype('f8')
            layer[mask] = new[v][mask]
            var[LAYER] = layer
        else:
            full = np.asarray(var[:]).astype('f8')
            full[mask] = new[v][mask]
            var[:] = full
        var.setncattr('soil_component_change', 'layer 2 recomputed' if v in DEPENDENT else
                      ('layer 2 smoothed' if v == 'depth' else 'smoothed') + ' (workflow/03_parameters/soil/)')
    o.setncatts({
        'title': 'VIC-WUR 5 arcmin soil component: the non-vegetation variables of the base bundle with the 2-degree '
                 'calibration fields depth[2], Ds, Dsmax, Ws and c smoothed by bilinear interpolation between the '
                 'block centres, max_moist[2] and init_moist[2] recomputed',
        'parameter_set': a.parameter_set, 'base_parameter_set': a.base_set, 'base_bundle': f'{base_rel}/{BASE_BUNDLE}',
        'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(), 'created_at': created_at,
        'method_version': METHOD_VERSION, 'object': os.path.relpath(out, W),
        'smoothing': 'blocks: latitude edges on even degrees, longitude edges on even degrees east of 0 and odd '
                     'degrees west of 0; block value = value of a uniform block, most frequent value of a mixed block, '
                     'nearest land block for an empty block; bilinear interpolation between block centres, periodic '
                     'in longitude; active cells only', **restrictions})
    o.close(); src.close()
    os.replace(part, f_out)

    # ---- block record
    f_csv = f'{out}/{BLOCKS_CSV}'
    with open(f_csv + '.part', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['field', 'block_row', 'block_col', 'lat_south', 'lat_north', 'lon_west', 'lon_east', 'kind', 'value',
                    'n_active', 'share_of_value', 'donor_row', 'donor_col', 'donor_km', 'filled_value'])
        for name in FIELDS:
            b = blocks[name]; le, lo = b['lat_edges'], b['lon_edges']; nbj = len(lo) - 1
            for i in range(len(le) - 1):
                for j in range(nbj):
                    k = int(b['kind'][i, j]); dn = int(b['donor'][i, j])
                    w.writerow([name, i, j, f'{le[i]:g}', f'{le[i + 1]:g}', f'{lo[j]:g}', f'{lo[j + 1]:g}', KINDS[k],
                                '' if k == 0 else repr(float(b['values'][i, j])), int(b['n_active'][i, j]),
                                '' if k == 0 else f'{b["share"][i, j]:.6f}', '' if dn < 0 else dn // nbj,
                                '' if dn < 0 else dn % nbj, '' if dn < 0 else f'{b["donor_km"][i, j]:.1f}',
                                repr(float(b['filled'][i, j]))])
    os.replace(f_csv + '.part', f_csv)

    report.update({'created_at': created_at, 'code_commit': commit, 'code_dirty': dirty, 'active_cells': int(mask.sum()),
                   'variables_copied_bitwise': copied, 'variables_changed': list(CHANGED),
                   'runtime_s': round(time.time() - t0)})
    json.dump(report, open(f'{qc}/reports/build_report.json', 'w'), indent=1)
    files = [{'path': os.path.basename(p), 'size_bytes': os.path.getsize(p), 'sha256': hashing.sha256(p),
              'md5': hashing.md5(p)} for p in (f_out, f_csv)]
    prov = {'object': rel_obj if not to_scratch else os.path.relpath(out, W), 'created_by': CREATED_BY,
            'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at, 'method_version': METHOD_VERSION,
            'base_parameter_set': a.base_set,
            'inputs': {'base_bundle': f'{base_rel}/{BASE_BUNDLE}', 'base_provenance': f'{base_rel}/bundle/provenance.yaml',
                       'domain': f'{base_rel}/{DOMAIN}'},
            'input_sha256': sha,
            'method': {'block_deg': BLOCK_DEG, 'fields': list(FIELDS), 'layer': LAYER + 1, 'dependent': list(DEPENDENT),
                       'block_value': 'uniform: the value; mixed: most frequent value of the active cells (ties: smallest); '
                                      'empty: nearest land block on the sphere',
                       'interpolation': 'bilinear between block centres, periodic in longitude, nearest row beyond the '
                                        'outermost centre rows, active cells only',
                       'precision': 'double'},
            'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --base-set {a.base_set} '
                               f'--parameter-status {a.parameter_status}' + (' --scratch' if a.scratch else ''),
            'files': files, 'restrictions': {**restrictions, 'source': f'{base_rel}/{BASE_BUNDLE}'} if restrictions else {},
            'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
