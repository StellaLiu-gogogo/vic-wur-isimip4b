#!/usr/bin/env python3
"""Independent verification of the assembled 16-class image-driver parameter file (assemble_bundle.py).

Checks (each with its own status; the file passes only when all pass):
  vic_variables   every variable the image driver at VIC 39e21ff5 reads from PARAMETERS with the options of the
                  project (FULL_ENERGY, SNOW_BAND with 5 bands, BASEFLOW NIJSSEN2001, LAI/FCAN/ALB/WFC_SRC
                  FROM_VEGPARAM, BCO2_SRC FROM_DEFAULT, no ORGANIC_FRACT, SPATIAL_SNOW, SPATIAL_FROST, CARBON,
                  BLOWING, LAKES) is present with the dimensions in the order VIC reads them (VIC_READS below,
                  drivers/shared_image/src/vic_init.c, get_global_domain.c, vic_start.c); dimension lengths
                  veg_class 16, month 12, root_zone 3, nlayer 3, snow_band 5; run_cell is int and equals 1
                  exactly on the domain mask
  latlon          lat and lon equal the domain file exactly
  vegetation      every variable of the vegetation component is bitwise equal to the component (stored values,
                  dtype, dimensions)
  natural         every other variable is bitwise equal to the natural bundle, and no variable of the file
                  comes from anywhere else
  tiles           on active cells: Nveg <= number of classes with Cv > 0 <= Nveg + 1 (vic_init.c), and the
                  int-read overstory is 0 or 1 on every tile
Writes <qc>/summary.json and <qc>/reports/verify.json, where <qc> is qc/parameters/<status>/<set>/bundle/
(or <bundle-dir>/qc/ with --bundle-dir), and sets qc.status in the bundle's provenance.yaml (not with
--bundle-dir).

Usage: verify_bundle.py [--parameter-set ID] [--parameter-status candidates] [--bundle-dir DIR]
"""
import argparse, datetime, json, os, sys

import numpy as np
import netCDF4 as nc
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assemble_bundle as ab   # noqa: E402  (file names only; every check is computed here)

V3 = ('veg_class', 'lat', 'lon'); VM = ('veg_class', 'month', 'lat', 'lon'); VR = ('veg_class', 'root_zone', 'lat', 'lon')
L3 = ('nlayer', 'lat', 'lon'); B3 = ('snow_band', 'lat', 'lon'); G2 = ('lat', 'lon')
VIC_READS = {
    'run_cell': G2, 'Nveg': G2, 'Cv': V3,
    'overstory': V3, 'rarc': V3, 'rmin': V3, 'wind_h': V3, 'RGL': V3, 'rad_atten': V3, 'wind_atten': V3,
    'trunk_ratio': V3,
    'veg_rough': VM, 'displacement': VM, 'LAI': VM, 'albedo': VM, 'fcanopy': VM,
    'root_depth': VR, 'root_fract': VR,
    'infilt': G2, 'Ds': G2, 'Dsmax': G2, 'Ws': G2, 'c': G2, 'elev': G2, 'avg_T': G2, 'dp': G2, 'rough': G2,
    'snow_rough': G2, 'annual_prec': G2, 'fs_active': G2,
    'expt': L3, 'Ksat': L3, 'init_moist': L3, 'phi_s': L3, 'depth': L3, 'bubble': L3, 'quartz': L3,
    'bulk_density': L3, 'soil_density': L3, 'Wcr_FRACT': L3, 'Wpwp_FRACT': L3, 'resid_moist': L3, 'Wfc_FRACT': L3,
    'AreaFract': B3, 'elevation': B3, 'Pfactor': B3,
}
DIM_LENGTHS = {'veg_class': 16, 'month': 12, 'root_zone': 3, 'nlayer': 3, 'snow_band': 5, 'lat': 1680, 'lon': 4320}


def raw(ds, name, idx=None):
    v = ds[name]; v.set_auto_maskandscale(False)
    return v[:] if idx is None else v[idx]


def same_bits(a, b):
    a = np.ascontiguousarray(a); b = np.ascontiguousarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def bitwise(out, src, name):
    o = out[name]; s = src[name]
    if o.dtype != s.dtype or o.dimensions != s.dimensions or o.shape != s.shape:
        return False
    if o.ndim < 3:
        return same_bits(raw(out, name), raw(src, name))
    return all(same_bits(raw(out, name, i), raw(src, name, i)) for i in range(o.shape[0]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--bundle-dir', default=None, help='verify an assembled file in this directory (scratch test)')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    ap.add_argument('--qc-to-scratch', action='store_true',
                    help='set by the submit script when the repository was not clean: results go to scratch')
    a = ap.parse_args(); W = ab.workdir()
    commit, dirty = ab.git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    # a verifier that is not committed never changes the status of the file (rule 14): its results go to scratch
    uncommitted = not a.bundle_dir and (dirty or a.qc_to_scratch)
    rel_pset = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{rel_pset}'
    bdir = a.bundle_dir or f'{pset}/bundle'
    qc = f'{bdir}/qc' if a.bundle_dir else f'{W}/qc/{rel_pset}/bundle'
    if uncommitted:
        qc = f'{W}/{ab.SCRATCH}/verify-uncommitted/qc/{rel_pset}/bundle'
    os.makedirs(f'{qc}/reports', exist_ok=True)
    out = nc.Dataset(f'{bdir}/{ab.OUT_NAME}'); nat = nc.Dataset(f'{pset}/{ab.NATURAL}')
    veg = nc.Dataset(f'{pset}/{ab.VEGETATION}')
    with nc.Dataset(f'{pset}/{ab.DOMAIN}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool); dlat = np.asarray(d['lat'][:]); dlon = np.asarray(d['lon'][:])
    checks = {}

    # ---- variables VIC reads
    missing = [v for v in VIC_READS if v not in out.variables]
    wrong_dims = {v: list(out[v].dimensions) for v, dims in VIC_READS.items() if v in out.variables
                  and out[v].dimensions != dims}
    lengths = {k: len(out.dimensions[k]) for k in DIM_LENGTHS if k in out.dimensions}
    bad_len = {k: (lengths.get(k), n) for k, n in DIM_LENGTHS.items() if lengths.get(k) != n}
    rc = raw(out, 'run_cell')
    run_cell = {'dtype': str(rc.dtype), 'not_1_on_mask': int((rc[mask] != 1).sum()),
                'is_1_off_mask': int((rc[~mask] == 1).sum())}
    ok = not missing and not wrong_dims and not bad_len and run_cell['dtype'] == 'int32' and run_cell['not_1_on_mask'] == 0
    checks['vic_variables'] = {'required': len(VIC_READS), 'missing': missing, 'wrong_dimensions': wrong_dims,
                               'wrong_dimension_lengths': bad_len, 'run_cell': run_cell,
                               'status': 'passed' if ok else 'failed'}

    # ---- lat/lon
    eq = {c: bool(np.array_equal(np.asarray(out[c][:]), x)) for c, x in (('lat', dlat), ('lon', dlon))}
    checks['latlon'] = {**eq, 'status': 'passed' if all(eq.values()) else 'failed'}

    # ---- bitwise provenance of every variable
    veg_vars = [v for v in veg.variables if v not in ('lat', 'lon')]
    nat_vars = [v for v in out.variables if v not in veg.variables]
    differ_v = [v for v in veg_vars if v not in out.variables or not bitwise(out, veg, v)]
    differ_n = [v for v in nat_vars if v not in nat.variables or not bitwise(out, nat, v)]
    checks['vegetation'] = {'variables': len(veg_vars), 'differ_or_missing': differ_v,
                            'status': 'passed' if not differ_v else 'failed'}
    checks['natural'] = {'variables': len(nat_vars), 'differ_or_foreign': differ_n,
                         'status': 'passed' if not differ_n else 'failed'}

    # ---- tiles
    cv = raw(out, 'Cv'); nveg = raw(out, 'Nveg')
    ntile = (np.nan_to_num(cv) > 0).sum(axis=0)
    n_act, t_act = nveg[mask], ntile[mask]
    ov = raw(out, 'overstory'); tiles = (np.nan_to_num(cv) > 0) & mask[None]
    ov_bad = int((~np.isin(ov[tiles], (0.0, 1.0))).sum())
    checks['tiles'] = {'active_cells': int(mask.sum()), 'tiles': int(tiles.sum()),
                       'cells_tiles_below_nveg': int((t_act < n_act).sum()),
                       'cells_tiles_above_nveg_plus_1': int((t_act > n_act + 1).sum()),
                       'overstory_not_0_or_1_on_tiles': ov_bad}
    c = checks['tiles']
    c['status'] = 'passed' if c['cells_tiles_below_nveg'] == c['cells_tiles_above_nveg_plus_1'] == ov_bad == 0 else 'failed'

    status = 'passed' if all(c['status'] == 'passed' for c in checks.values()) else 'failed'
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    report = {'object': os.path.relpath(f'{bdir}/{ab.OUT_NAME}', W), 'checked_at': now, 'status': status,
              'checked_by': 'workflow/03_parameters/bundle/verify_bundle.py', 'checks': checks}
    with open(f'{qc}/reports/verify.json', 'w') as fh:
        json.dump(report, fh, indent=1)
    with open(f'{qc}/summary.json', 'w') as fh:
        json.dump({k: report[k] for k in ('object', 'checked_at', 'status', 'checked_by')} |
                  {'checks': {k: v['status'] for k, v in checks.items()}} |
                  ({'note': 'verifier code not committed (repository not clean): results kept in scratch, the status of the object is unchanged'} if uncommitted else {}), fh, indent=1)
    if not a.bundle_dir and not uncommitted:
        p = f'{bdir}/provenance.yaml'; prov = yaml.safe_load(open(p))
        prov['qc'] = {'status': status, 'evidence': os.path.relpath(qc, W)}
        with open(p + '.part', 'w') as fh:
            yaml.safe_dump(prov, fh, sort_keys=False)
        os.replace(p + '.part', p)
    print(json.dumps({k: v['status'] for k, v in checks.items()}), status)
    sys.exit(0 if status == 'passed' else 1)


if __name__ == '__main__':
    main()
