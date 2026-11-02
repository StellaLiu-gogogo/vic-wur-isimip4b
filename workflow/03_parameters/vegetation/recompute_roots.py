#!/usr/bin/env python3
"""Vegetation component of a parameter set whose soil differs from the base set: root zones recomputed (task Z).

Writes parameters/<status>/<set>/vegetation/ from the vegetation component of the base parameter set
(parameters/<status>/<base-set>/vegetation/, built by build_vegetation.py) and the soil component of this set
(soil/vic_global_5min_soil_calibration-smoothed.nc): every variable except root_depth and root_fract is copied
bitwise (the tiles, Cv, Nveg, LAI, fcanopy, albedo, displacement, veg_rough, overstory, rarc, rmin, RGL,
rad_atten, wind_atten, trunk_ratio, wind_h, the bookkeeping variables); backfill_tiles.csv is copied unchanged.

Root rule (root_zeng2001_igbp.yaml; reproduces the base component exactly after rounding to float32, see
verify_roots.py), applied with the new layer depths:
  classes 1-10, 13   on every active cell root_depth = the thickness of the three soil layers of the cell and
                     root_fract = the Zeng (2001) cumulative distribution Y(d) = 1 - 0.5 (exp(-a d) + exp(-b d))
                     integrated between the layer interfaces and divided by Y(soil bottom), in double precision;
                     an added tile (backfill_level > 0, donor in backfill_tiles.csv) takes the values of its donor
                     cell, as every other parameter of an added tile (a level-1 tile is its own donor)
  classes 11, 12, 14, 15, 16   copied bitwise from the base component (no tiles; constant crop root zones;
                     bare soil without roots)
Cells outside the domain mask keep the stored values of the base component.

Outputs: <out>/vic_global_5min_vegetation_16class_root-b-zeng2001.nc, <out>/backfill_tiles.csv, <out>/provenance.yaml
and <qc>/reports/build_report.json, where <out> is parameters/<status>/<set>/vegetation/ and <qc> is
qc/parameters/<status>/<set>/vegetation/. From a repository that is not clean, or with --scratch, everything goes to
scratch/vegetation-roots/vegetation/ (qc under its qc/).

Usage: recompute_roots.py [--parameter-set vic-global-5arcmin-version-b] [--base-set vic-global-5arcmin-version-a]
       [--parameter-status candidates] [--soil-dir DIR] [--scratch] [--expect-commit SHA]
"""
import argparse, csv, json, os, shutil, sys, time

import numpy as np
import netCDF4 as nc
import yaml

from common import gitstate, hashing, provenance, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import build_vegetation as bv   # noqa: E402  (names and constants of the base component)
sys.path.insert(0, os.path.join(HERE, '..', 'bundle'))
import assemble_bundle as ab   # noqa: E402  (the bitwise variable copy of the bundle assembly)
sys.path.insert(0, os.path.join(HERE, '..', 'soil'))
import smooth_calibration_fields as sm   # noqa: E402  (the file name of the soil component)

CREATED_BY = 'workflow/03_parameters/vegetation/recompute_roots.py'
METHOD_VERSION = '1.0'
COEFFICIENTS = os.path.join(HERE, 'root_zeng2001_igbp.yaml')
SCRATCH = 'scratch/vegetation-roots'
SOIL = f'soil/{sm.OUT_NAME}'
CSV = 'backfill_tiles.csv'


def coefficients(path=COEFFICIENTS):
    """{class: (a, b)} of the Zeng classes and the list of unchanged classes."""
    with open(path) as fh:
        c = yaml.safe_load(fh)
    zeng = {int(k): (float(v['a']), float(v['b'])) for k, v in c['zeng'].items()}
    unchanged = sorted(int(k) for k in c['unchanged'])
    if sorted(list(zeng) + unchanged) != list(range(1, bv.NCLASS + 1)):
        raise ValueError('the coefficient file must cover classes 1-16 once')
    return zeng, unchanged


def zeng_cumulative(d, a, b):
    return 1.0 - 0.5 * (np.exp(-a * d) + np.exp(-b * d))


def root_fractions(depth, a, b):
    """Zeng (2001) root fractions of the three layers from the layer thicknesses depth (3, ...): the cumulative
    distribution integrated between the layer interfaces, divided by the part within the soil column."""
    inter = np.concatenate([np.zeros((1,) + depth.shape[1:]), np.cumsum(depth, axis=0)], axis=0)
    cum = zeng_cumulative(inter, a, b)
    fr = np.diff(cum, axis=0)
    total = fr.sum(axis=0, keepdims=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(total > 0, fr / np.where(total > 0, total, 1), np.nan)


def donors(csv_path, nclass=bv.NCLASS):
    """{class: (rows, cols, donor rows, donor cols)} of the added tiles from backfill_tiles.csv."""
    rows = {k: [] for k in range(1, nclass + 1)}
    with open(csv_path) as fh:
        for r in csv.DictReader(fh):
            rows[int(r['class'])].append((int(r['row']), int(r['col']), int(r['donor_row']), int(r['donor_col'])))
    return {k: tuple(np.array(v, dtype=int).reshape(-1, 4).T) for k, v in rows.items()}


def class_roots(k, depth, valid, base_depth, base_fract, zeng, added):
    """root_depth and root_fract (3, ny, nx) of class k (1-based): Zeng classes recomputed on the valid cells and
    copied from the donor on added tiles (rows, cols, donor rows, donor cols); other cells keep the base values."""
    if k not in zeng:
        return base_depth, base_fract
    a, b = zeng[k]
    rd = base_depth.astype('f8', copy=True); rf = base_fract.astype('f8', copy=True)
    fr = root_fractions(np.where(valid[None], depth, 1.0), a, b)
    rd[:, valid] = depth[:, valid]; rf[:, valid] = fr[:, valid]
    tr, tc, dr, dc = added
    if len(tr):
        rd[:, tr, tc] = rd[:, dr, dc]; rf[:, tr, tc] = rf[:, dr, dc]
    return rd, rf


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-b')
    ap.add_argument('--base-set', default='vic-global-5arcmin-version-a', help='set whose vegetation component is the base')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--soil-dir', default=None, help='directory of the soil component (default: soil/ of the set)')
    ap.add_argument('--scratch', action='store_true', help=f'test run: write under {SCRATCH}/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script for an accepted output: stop unless the repository is clean and at '
                         'this commit')
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    commit, dirty = gitstate.state(REPO); to_scratch = dirty or a.scratch
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    base_rel = f'parameters/{a.parameter_status}/{a.base_set}/vegetation'; base_dir = f'{W}/{base_rel}'
    pset_rel = f'parameters/{a.parameter_status}/{a.parameter_set}'
    rel_obj = f'{pset_rel}/vegetation'
    soil_dir = a.soil_dir or f'{W}/{pset_rel}/soil'
    out = f'{W}/{SCRATCH}/vegetation' if to_scratch else f'{W}/{rel_obj}'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{rel_obj}'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out}', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; a component is replaced only with the user\'s authorization')
    f_base, f_csv, f_bprov = f'{base_dir}/{bv.OUT_NAME}', f'{base_dir}/{CSV}', f'{base_dir}/provenance.yaml'
    f_soil, f_sprov = f'{soil_dir}/{sm.OUT_NAME}', f'{soil_dir}/provenance.yaml'
    for p in (f_base, f_csv, f_bprov, f_soil, f_sprov):
        if not os.path.isfile(p):
            raise SystemExit(f'missing input {p}')
    bprov, sprov = provenance.read(f_bprov), provenance.read(f_sprov)
    for name, p in (('base vegetation component', bprov), ('soil component', sprov)):
        if (p.get('qc') or {}).get('status') != 'passed' or p.get('code_dirty') is not False:
            msg = f'{name} is not accepted (code_dirty {p.get("code_dirty")}, qc {p.get("qc")})'
            if not to_scratch:
                raise SystemExit(msg)
            print(f'warning: {msg}', file=sys.stderr)
    zeng, unchanged = coefficients()
    os.makedirs(out, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)

    base = nc.Dataset(f_base); soil = nc.Dataset(f_soil); soil.set_auto_mask(False)
    lat = np.asarray(base['lat'][:]); lon = np.asarray(base['lon'][:])
    if not (np.array_equal(np.asarray(soil['lat'][:]), lat) and np.array_equal(np.asarray(soil['lon'][:]), lon)):
        raise SystemExit('base vegetation component and soil component grids differ')
    mask = np.asarray(soil['run_cell'][:]) == 1
    depth = np.asarray(soil['depth'][:]).astype('f8')
    dfill = soil['depth'].getncattr('_FillValue') if '_FillValue' in soil['depth'].ncattrs() else None
    if dfill is not None:
        depth = np.where(depth == dfill, np.nan, depth)
    valid = mask & np.isfinite(depth).all(axis=0) & (depth > 0).all(axis=0)
    if (mask & ~valid).any():
        raise SystemExit(f'{int((mask & ~valid).sum())} active cells without three positive layer depths')
    added = donors(f_csv)
    sha = {'base_vegetation': hashing.sha256(f_base), 'backfill_tiles': hashing.sha256(f_csv),
           'soil_component': hashing.sha256(f_soil), 'coefficients': hashing.sha256(COEFFICIENTS)}
    created_at = provenance.utcnow()

    f_out = f'{out}/{bv.OUT_NAME}'; part = f_out + '.part'
    o = nc.Dataset(part, 'w', format='NETCDF4')
    for dn, d in base.dimensions.items():
        o.createDimension(dn, len(d))
    for v in base.variables:
        ab.copy_variable(base, o, v)            # root_depth and root_fract are overwritten class by class below
    o.setncatts({k: base.getncattr(k) for k in base.ncattrs()})
    o.setncatts({'title': 'VIC-WUR 16-class vegetation component with the land-use tile union, root zones recomputed '
                          'for the soil component of this set',
                 'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(), 'created_at': created_at,
                 'method_version': METHOD_VERSION, 'parameter_set': f'{a.parameter_status}/{a.parameter_set}',
                 'base_vegetation_component': f'{base_rel}/{bv.OUT_NAME}', 'base_vegetation_sha256': sha['base_vegetation'],
                 'soil_component': os.path.relpath(f_soil, W), 'soil_component_sha256': sha['soil_component'],
                 'root_rule': 'classes 1-10 and 13: root_depth = layer depths, root_fract = Zeng (2001) fractions between '
                              'the layer interfaces normalised within the soil column, added tiles copy their donor; '
                              'classes 11, 12, 14, 15, 16 unchanged (root_zeng2001_igbp.yaml)'})
    report = {'method_version': METHOD_VERSION, 'created_at': created_at, 'code_commit': commit, 'code_dirty': dirty,
              'active_cells': int(mask.sum()), 'classes': {}}
    cvar = base['Cv']; cvar.set_auto_maskandscale(False)        # stored values; the fill of Cv is NaN
    tiles = (np.nan_to_num(np.asarray(cvar[:], 'f8')) > 0) & mask[None]
    for k in range(1, bv.NCLASS + 1):
        tk = time.time()
        bd_ = o['root_depth']; bf_ = o['root_fract']; bd_.set_auto_maskandscale(False); bf_.set_auto_maskandscale(False)
        base_depth = np.asarray(bd_[k - 1]); base_fract = np.asarray(bf_[k - 1])
        rd, rf = class_roots(k, depth, valid, base_depth, base_fract, zeng, added[k])
        if k in zeng:
            bd_[k - 1] = rd; bf_[k - 1] = rf
        t = tiles[k - 1]
        rec = {'rule': 'zeng' if k in zeng else 'unchanged', 'tiles': int(t.sum()), 'added_tiles': int(len(added[k][0])),
               'cells_recomputed': int(valid.sum()) if k in zeng else 0, 'runtime_s': round(time.time() - tk, 1)}
        if k in zeng and t.any():
            s = rf.sum(axis=0)[t]
            rec |= {'root_fract_sum_range_on_tiles': [float(s.min()), float(s.max())],
                    'root_fract_changed_on_tiles': int((~np.all(rf == base_fract, axis=0))[t].sum()),
                    'root_depth_changed_on_tiles': int((~np.all(rd == base_depth, axis=0))[t].sum())}
        report['classes'][str(k)] = rec
        print(f'class {k}: {rec}', flush=True)
        o.sync()
    o.close(); base.close(); soil.close()
    os.replace(part, f_out)
    shutil.copyfile(f_csv, f'{out}/{CSV}.part'); os.replace(f'{out}/{CSV}.part', f'{out}/{CSV}')
    if hashing.sha256(f'{out}/{CSV}') != sha['backfill_tiles']:
        raise SystemExit('the copy of backfill_tiles.csv differs from the base')
    report['runtime_s'] = round(time.time() - t0)
    json.dump(report, open(f'{qc}/reports/build_report.json', 'w'), indent=1)

    files = [{'path': os.path.basename(p), 'size_bytes': os.path.getsize(p), 'sha256': hashing.sha256(p),
              'md5': hashing.md5(p)} for p in (f_out, f'{out}/{CSV}')]
    prov = {'object': rel_obj if not to_scratch else os.path.relpath(out, W), 'created_by': CREATED_BY,
            'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at, 'method_version': METHOD_VERSION,
            'base_parameter_set': a.base_set,
            'inputs': {'base_vegetation': f'{base_rel}/{bv.OUT_NAME}', 'backfill_tiles': f'{base_rel}/{CSV}',
                       'base_provenance': f'{base_rel}/provenance.yaml',
                       'base_qc': {'status': (bprov.get('qc') or {}).get('status'), 'evidence': (bprov.get('qc') or {}).get('evidence')},
                       'soil_component': os.path.relpath(f_soil, W), 'soil_provenance': os.path.relpath(f_sprov, W),
                       'coefficients': 'workflow/03_parameters/vegetation/root_zeng2001_igbp.yaml',
                       'landuse_units': bprov.get('inputs', {}).get('landuse_units')},
            'input_sha256': sha,
            'method': {'zeng_classes': sorted(zeng), 'unchanged_classes': unchanged, 'precision': 'double',
                       'added_tiles': 'values of the donor cell of backfill_tiles.csv'},
            'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --base-set {a.base_set} '
                               f'--parameter-status {a.parameter_status}' + (' --scratch' if a.scratch else ''),
            'files': files, 'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
