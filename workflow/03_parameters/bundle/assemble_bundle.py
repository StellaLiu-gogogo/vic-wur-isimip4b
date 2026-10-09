#!/usr/bin/env python3
"""Assemble the 16-class VIC image-driver parameter file of a parameter set (bundle component).

The file VIC reads with PARAMETERS combines
  * every non-vegetation variable (soil, snow bands, elev, run_cell, ...) of the adopted natural bundle
    bundle/vic_global_5min_natural_static_root-b-zeng2001.nc, copied bitwise, and
  * every variable of the 16-class vegetation component
    vegetation/vic_global_5min_vegetation_16class_root-b-zeng2001.nc (workflow/03_parameters/vegetation/),
    copied bitwise; it replaces the 14-class vegetation of the natural bundle.
A natural-bundle variable is a vegetation variable when the component has a variable of the same name or when
it has the dimension `veg_class`; a variable with `veg_class` that the component does not provide stops the
assembly. Data are copied as stored (no unpacking or masking), with the source dtype, fill value, chunking and
compression; lat and lon must equal the domain file exactly.

Output: parameters/<status>/<set>/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc and
bundle/provenance.yaml (for this file only; the other files of the bundle component are adopted and recorded
in manifests/parameters/<set>.yaml). From a repository that is not clean, or with --scratch, everything goes
to scratch/parameter-bundle/bundle/.

Usage: assemble_bundle.py [--parameter-set ID] [--parameter-status candidates] [--scratch]
"""
import argparse, datetime, hashlib, os, subprocess, sys

import numpy as np
import netCDF4 as nc
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
CREATED_BY = 'workflow/03_parameters/bundle/assemble_bundle.py'
METHOD_VERSION = '1.0'
NATURAL = 'bundle/vic_global_5min_natural_static_root-b-zeng2001.nc'
VEGETATION = 'vegetation/vic_global_5min_vegetation_16class_root-b-zeng2001.nc'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
OUT_NAME = 'vic_global_5min_16class_landuse-union_root-b-zeng2001.nc'
SCRATCH = 'scratch/parameter-bundle'
COORDS = ('lat', 'lon')
VEG_DIM = 'veg_class'
SLAB_BYTES = 2 << 30   # variables up to 2 GiB are copied in one piece, larger ones per index of the first dimension


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def file_hash(path, algo='sha256', n=1 << 24):
    h = hashlib.new(algo)
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(n), b''):
            h.update(b)
    return h.hexdigest()


def git_state():
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout.strip())
    return commit, dirty


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def plan(nat, veg):
    """Split the variables: {'vegetation': [...], 'natural': [...], 'replaced': [...]} and the output dimensions.
    Raises ValueError on a conflict."""
    veg_vars = [v for v in veg.variables if v not in COORDS]
    replaced = [v for v in nat.variables if v in veg.variables and v not in COORDS]
    orphan = [v for v in nat.variables if v not in veg.variables and VEG_DIM in nat[v].dimensions]
    if orphan:
        raise ValueError(f'natural-bundle variables with {VEG_DIM} that the vegetation component lacks: {orphan}')
    keep = [v for v in nat.variables if v not in veg.variables and v not in COORDS]
    dims = {}
    for name, d in nat.dimensions.items():
        if any(name in nat[v].dimensions for v in keep + list(COORDS) if v in nat.variables):
            dims[name] = len(d)
    for name, d in veg.dimensions.items():
        if name in dims and dims[name] != len(d) and name != VEG_DIM:
            raise ValueError(f'dimension {name}: {dims[name]} in the natural bundle, {len(d)} in the component')
        dims[name] = len(d)
    for c in COORDS:
        a = nat[c][:]; b = veg[c][:]
        if a.shape != b.shape or not np.array_equal(np.asarray(a), np.asarray(b)):
            raise ValueError(f'{c} differs between the natural bundle and the vegetation component')
    return {'vegetation': veg_vars, 'natural': keep, 'replaced': replaced, 'coords': list(COORDS)}, dims


def copy_variable(src, out, name):
    """Create `name` in `out` like in `src` and copy the stored values slab by slab along the first dimension."""
    s = src[name]; s.set_auto_maskandscale(False)
    filt = s.filters() or {}
    kw = {}
    if filt.get('zlib'):
        kw.update(zlib=True, complevel=filt.get('complevel', 4), shuffle=bool(filt.get('shuffle')))
    chunk = s.chunking()
    if chunk not in (None, 'contiguous'):
        kw['chunksizes'] = chunk
    fill = s.getncattr('_FillValue') if '_FillValue' in s.ncattrs() else None
    v = out.createVariable(name, s.dtype, s.dimensions, fill_value=fill, **kw)
    v.set_auto_maskandscale(False)
    v.setncatts({k: s.getncattr(k) for k in s.ncattrs() if k != '_FillValue'})
    if s.ndim == 0:
        v.assignValue(s.getValue()); return
    if s.ndim < 3 or np.prod(s.shape, dtype='i8') * s.dtype.itemsize <= SLAB_BYTES:
        v[:] = s[:]; return
    for i in range(s.shape[0]):   # e.g. one vegetation class of (veg_class, month, lat, lon)
        v[i] = s[i]


RESTRICTIONS = ('not_authorized_for_global_production', 'product_stage')   # of the natural bundle, carried over


def vegetation_not_accepted(pset):
    """None when the vegetation component of the parameter set is accepted (provenance.yaml: code_dirty false,
    qc.status passed), else the reason."""
    p = f'{pset}/{os.path.dirname(VEGETATION)}/provenance.yaml'
    if not os.path.exists(p):
        return f'{p}: no provenance record'
    with open(p) as fh:
        prov = yaml.safe_load(fh) or {}
    status = (prov.get('qc') or {}).get('status')
    if prov.get('code_dirty') is not False or status != 'passed':
        return f'vegetation component not accepted (code_dirty {prov.get("code_dirty")}, qc.status {status})'
    return None


def source_restrictions(nat):
    """Restriction attributes of the natural bundle, carried into the assembled file and its provenance."""
    return {k: nat.getncattr(k) for k in RESTRICTIONS if k in nat.ncattrs()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script for an accepted output: stop unless the repository is clean and at '
                         'this commit')
    a = ap.parse_args(); W = workdir()
    commit, dirty = git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    pset_rel = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{pset_rel}'
    to_scratch = a.scratch or dirty
    out_dir = f'{W}/{SCRATCH}/bundle' if to_scratch else f'{pset}/bundle'
    out = f'{out_dir}/{OUT_NAME}'
    if os.path.exists(out):
        sys.exit(f'{out} exists; an assembled file is never overwritten')
    if dirty and not a.scratch:
        print('repository is not clean: writing to scratch (docs/directory-contracts.md, rule 14)')
    problem = vegetation_not_accepted(pset)
    if problem and not to_scratch:
        sys.exit(f'{problem}; an accepted bundle is assembled only from an accepted vegetation component')
    if problem:
        print(f'warning: {problem}')
    os.makedirs(out_dir, exist_ok=True)
    nat = nc.Dataset(f'{pset}/{NATURAL}'); veg = nc.Dataset(f'{pset}/{VEGETATION}')
    with nc.Dataset(f'{pset}/{DOMAIN}') as d:
        for c in COORDS:
            if not np.array_equal(np.asarray(d[c][:]), np.asarray(nat[c][:])):
                sys.exit(f'{c} of the natural bundle differs from the domain file')
    split, dims = plan(nat, veg)
    restrictions = source_restrictions(nat)
    print(f'{len(split["natural"])} natural variables, {len(split["vegetation"])} vegetation variables, '
          f'{len(split["replaced"])} natural vegetation variables replaced')
    t0 = utcnow(); part = out + '.part'
    o = nc.Dataset(part, 'w', format='NETCDF4')
    for name, n in dims.items():
        o.createDimension(name, n)
    for c in COORDS:
        copy_variable(nat, o, c)
    for name in split['natural']:
        copy_variable(nat, o, name)
    for name in split['vegetation']:
        copy_variable(veg, o, name)
    o.setncatts({
        'title': 'VIC-WUR 5 arcmin image-driver parameters, 16 vegetation classes with the land-use tile union',
        'parameter_set': a.parameter_set,
        'sources': f'non-vegetation variables: {pset_rel}/{NATURAL}; vegetation variables: {pset_rel}/{VEGETATION}',
        'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(),
        'created_at': t0, 'method_version': METHOD_VERSION,
        'object': os.path.relpath(out, W), **restrictions})
    o.close(); nat.close(); veg.close()
    os.replace(part, out)
    info = {'path': OUT_NAME, 'size_bytes': os.path.getsize(out), 'sha256': file_hash(out), 'md5': file_hash(out, 'md5')}
    prov = {
        'object': os.path.relpath(out, W), 'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': dirty,
        'created_at': t0, 'method_version': METHOD_VERSION,
        'inputs': {'natural_bundle': f'{pset_rel}/{NATURAL}', 'vegetation_component': f'{pset_rel}/{VEGETATION}',
                   'domain': f'{pset_rel}/{DOMAIN}'},
        'input_sha256': {'natural_bundle': file_hash(f'{pset}/{NATURAL}'),
                         'vegetation_component': file_hash(f'{pset}/{VEGETATION}'),
                         'domain': file_hash(f'{pset}/{DOMAIN}')},
        'method': {'natural_variables': split['natural'], 'vegetation_variables': split['vegetation'],
                   'replaced_natural_variables': split['replaced'], 'coordinates': split['coords'],
                   'dimensions': dims, 'copy': 'stored values, dtype, fill value, chunking and compression unchanged'},
        'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --parameter-status {a.parameter_status}',
        'files': [info],
        'restrictions': {**restrictions, 'source': f'{pset_rel}/{NATURAL}'} if restrictions else {},
        'note': 'This record covers the assembled file only; the adopted files of the bundle component are '
                f'recorded in manifests/parameters/{a.parameter_set}.yaml.',
        'qc': {'status': 'not_checked'}}
    with open(f'{out_dir}/provenance.yaml.part', 'w') as fh:
        yaml.safe_dump(prov, fh, sort_keys=False)
    os.replace(f'{out_dir}/provenance.yaml.part', f'{out_dir}/provenance.yaml')
    print(f'wrote {out} ({info["size_bytes"]} bytes, md5 {info["md5"]})')


if __name__ == '__main__':
    main()
