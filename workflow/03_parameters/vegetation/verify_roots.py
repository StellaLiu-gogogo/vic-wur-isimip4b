#!/usr/bin/env python3
"""Independent verification of a vegetation component written by recompute_roots.py.

Checks (each with its own status; the component passes only when all pass):
  unchanged      every variable except root_depth and root_fract is bitwise equal to the base vegetation component
                 (stored values, dtype, dimensions), the coordinates included; backfill_tiles.csv equals the base
                 copy (sha256); root_depth and root_fract of the unchanged classes (11, 12, 14, 15, 16) are bitwise
                 equal; outside the domain mask the two root variables are bitwise equal in every class
  grid           lat and lon of the component, the soil component and the domain are equal; the soil component is
                 accepted (qc passed, code committed; reported only in a scratch test with --component-dir) and its
                 sha256 is the one recorded
  root_depth     classes 1-10 and 13: on every active cell root_depth equals the three layer depths of the soil
                 component exactly, except added tiles (backfill_level > 0), which equal their donor's values
  root_fract     the fractions recomputed here from the layer depths (Zeng 2001, own implementation) equal the file
                 within 1e-12 on every active cell, added tiles equal their donor; on tiles of classes 1-15 the
                 fractions are in [0, 1] and sum to 1 within 1e-9; class 16 is 0
  reproduction   the same rule applied to the layer depths of the base bundle (base set) reproduces root_fract of the
                 base component on every base tile of the Zeng classes exactly after rounding to float32, and
                 root_depth exactly: the rule is the one vic_parameter used (task Z, user 2026-11-02)
  forcing_tiles  the tiles (Cv) are bitwise equal to the base component, whose QC (forcing_tiles) checked every
                 coverage file of the five land-use units; those files are still the ones the units' provenance
                 records list (same sha256) and none was added or removed; the files are recorded here as
                 checked_files, which render_run.py compares with the land-use files of a run
Writes <qc>/summary.json and <qc>/reports/verify.json, where <qc> is qc/parameters/<status>/<set>/vegetation/
(or <component-dir>/qc/ with --component-dir), and sets qc.status in the component's provenance.yaml (not with
--component-dir). Exit status: 0 passed, 1 failed (common/qc.py).

Usage: verify_roots.py [--parameter-set ID] [--parameter-status candidates] [--component-dir DIR]
"""
import argparse, json, os, sys

import numpy as np
import netCDF4 as nc

from common import gitstate, hashing, provenance, qc, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_vegetation as bv   # noqa: E402  (names and constants)
import recompute_roots as rr    # noqa: E402  (names, constants, coefficient file and donor table; checks computed here)
import verify_vegetation as vv  # noqa: E402  (landuse_files: the current land-use files and their recorded sha256)

FRACT_TOL = 1e-12
SUM_TOL = 1e-9


def raw(ds, name, idx=None):
    v = ds[name]; v.set_auto_maskandscale(False)
    return np.asarray(v[:] if idx is None else v[idx])


def same_bits(a, b):
    a = np.ascontiguousarray(a); b = np.ascontiguousarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def bitwise(o, s, name):
    if o[name].dtype != s[name].dtype or o[name].dimensions != s[name].dimensions or o[name].shape != s[name].shape:
        return False
    if o[name].ndim < 3:
        return same_bits(raw(o, name), raw(s, name))
    return all(same_bits(raw(o, name, i), raw(s, name, i)) for i in range(o[name].shape[0]))


def own_fractions(depth, a, b):
    """Zeng fractions computed layer by layer (not with cumsum/diff): Y(top..bottom) per layer, normalised."""
    top = np.zeros(depth.shape[1:]); fr = []
    for k in range(depth.shape[0]):
        bottom = top + depth[k]
        fr.append(rr.zeng_cumulative(bottom, a, b) - rr.zeng_cumulative(top, a, b)); top = bottom
    fr = np.stack(fr); total = rr.zeng_cumulative(top, a, b)
    return fr / total[None]


def read_depth(path):
    with nc.Dataset(path) as d:
        d.set_auto_mask(False)
        x = np.asarray(d['depth'][:]).astype('f8')
        f = d['depth'].getncattr('_FillValue') if '_FillValue' in d['depth'].ncattrs() else None
        return np.where(x == f, np.nan, x) if f is not None else x


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-b')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--component-dir', default=None, help='verify a component in this directory (scratch test)')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    ap.add_argument('--qc-to-scratch', action='store_true',
                    help='set by the submit script when the repository was not clean: results go to scratch')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(rr.REPO)
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    uncommitted = not a.component_dir and (dirty or a.qc_to_scratch)
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/vegetation'
    comp = a.component_dir or f'{W}/{rel_obj}'
    qc_dir = f'{comp}/qc' if a.component_dir else f'{W}/qc/{rel_obj}'
    if uncommitted:
        qc_dir = f'{W}/{rr.SCRATCH}/verify-uncommitted/qc/{rel_obj}'
    os.makedirs(f'{qc_dir}/reports', exist_ok=True)
    prov = provenance.read(f'{comp}/provenance.yaml'); inp = prov['inputs']
    v = nc.Dataset(f'{comp}/{bv.OUT_NAME}'); b = nc.Dataset(f'{W}/{inp["base_vegetation"]}')
    sprov = provenance.read(f'{W}/{inp["soil_provenance"]}')
    depth = read_depth(f'{W}/{inp["soil_component"]}')
    zeng, unchanged = rr.coefficients()
    checks = {}

    # ---- unchanged variables and the donor table
    names = [n for n in b.variables if n not in bv.ROOT]
    differ = [n for n in names if n not in v.variables or not bitwise(v, b, n)]
    foreign = [n for n in v.variables if n not in b.variables]
    with nc.Dataset(f'{W}/{inp["soil_component"]}') as s:
        s.set_auto_mask(False); mask = np.asarray(s['run_cell'][:]) == 1
        slat, slon = np.asarray(s['lat'][:]), np.asarray(s['lon'][:])
    root_unchanged = {str(k): [bool(same_bits(raw(v, n, k - 1), raw(b, n, k - 1))) for n in bv.ROOT] for k in unchanged}
    root_inactive = {str(k): [int((raw(v, n, k - 1)[:, ~mask] != raw(b, n, k - 1)[:, ~mask]).sum() -
                                  int((np.isnan(raw(v, n, k - 1)[:, ~mask]) & np.isnan(raw(b, n, k - 1)[:, ~mask])).sum()))
                              for n in bv.ROOT] for k in zeng}
    csv_ok = hashing.sha256(f'{comp}/{rr.CSV}') == hashing.sha256(f'{W}/{inp["backfill_tiles"]}')
    checks['unchanged'] = {'variables': len(names), 'differ_or_missing': differ, 'foreign': foreign,
                           'root_variables_of_unchanged_classes_bitwise': root_unchanged,
                           'root_cells_outside_mask_differ': root_inactive, 'backfill_tiles_equal': csv_ok,
                           'status': 'passed' if not differ and not foreign and csv_ok and all(all(x) for x in root_unchanged.values())
                           and all(all(n == 0 for n in x) for x in root_inactive.values()) else 'failed'}

    # ---- grid and the soil component
    pset = f'{W}/parameters/{a.parameter_status}/{a.parameter_set}'
    dom = f'{pset}/{bv.DOMAIN}' if os.path.isfile(f'{pset}/{bv.DOMAIN}') else f'{W}/{sprov["inputs"]["domain"]}'
    with nc.Dataset(dom) as d:
        dlat, dlon = np.asarray(d['lat'][:]), np.asarray(d['lon'][:])
    lat, lon = np.asarray(v['lat'][:]), np.asarray(v['lon'][:])
    g = {'grid_equals_soil': bool(np.array_equal(lat, slat) and np.array_equal(lon, slon)),
         'grid_equals_domain': bool(np.array_equal(lat, dlat) and np.array_equal(lon, dlon)), 'domain_file': os.path.relpath(dom, W),
         'soil_accepted': (sprov.get('qc') or {}).get('status') == 'passed' and sprov.get('code_dirty') is False,
         'soil_sha256_recorded': hashing.sha256(f'{W}/{inp["soil_component"]}') == prov['input_sha256']['soil_component']}
    # in a scratch test (--component-dir) the soil component is a scratch output that cannot be accepted: reported only
    judged = [k for k in g if k not in ('domain_file',) and not (a.component_dir and k == 'soil_accepted')]
    checks['grid'] = {**g, 'status': 'passed' if all(g[k] for k in judged) else 'failed'}

    # ---- root_depth and root_fract per class, reproduction on the base bundle
    base_depth = read_depth(f'{W}/{sprov["inputs"]["base_bundle"]}')
    added = rr.donors(f'{comp}/{rr.CSV}')
    cv = raw(v, 'Cv'); tiles = (np.nan_to_num(cv) > 0) & mask[None]
    rd_c = {}; rf_c = {}; rep = {}; ok_rd = ok_rf = ok_rep = True
    for k in sorted(zeng):
        a_, b_ = zeng[k]; i = k - 1
        rd = raw(v, 'root_depth', i).astype('f8'); rf = raw(v, 'root_fract', i).astype('f8')
        lev = raw(v, 'backfill_level', i); own = mask & (lev == 0); add = mask & (lev > 0)
        tr, tc, dr, dc = added[k]
        exp_fr = own_fractions(np.where(mask[None], depth, 1.0), a_, b_)
        d_bad = int((~np.all(rd == depth, axis=0))[own].sum())
        f_bad = int((~np.all(np.abs(rf - exp_fr) <= FRACT_TOL, axis=0))[own].sum())
        donor_d = int((~np.all(rd[:, tr, tc] == rd[:, dr, dc], axis=0)).sum()) if len(tr) else 0
        donor_f = int((~np.all(rf[:, tr, tc] == rf[:, dr, dc], axis=0)).sum()) if len(tr) else 0
        csv_vs_level = int((~add[tr, tc]).sum()) if len(tr) else 0
        t = tiles[i]; s = rf.sum(axis=0)
        sum_bad = int((np.abs(s - 1) > SUM_TOL)[t].sum()); range_bad = int(((rf < 0) | (rf > 1)).any(axis=0)[t].sum())
        rd_c[str(k)] = {'own_cells': int(own.sum()), 'own_cells_not_equal_depth': d_bad, 'added_tiles': int(len(tr)),
                        'added_not_equal_donor': donor_d, 'csv_rows_not_added_tiles': csv_vs_level}
        rf_c[str(k)] = {'own_cells_beyond_tolerance': f_bad, 'added_not_equal_donor': donor_f, 'tiles': int(t.sum()),
                        'sum_not_1_on_tiles': sum_bad, 'outside_0_1_on_tiles': range_bad,
                        'max_abs_deviation_own_cells': float(np.nanmax(np.abs(rf - exp_fr)[:, own])) if own.any() else 0.0}
        ok_rd &= d_bad == donor_d == csv_vs_level == 0; ok_rf &= f_bad == donor_f == sum_bad == range_bad == 0
        # reproduction of the base component on its base tiles
        bd_ = raw(b, 'root_depth', i).astype('f8'); bf_ = raw(b, 'root_fract', i).astype('f8')
        base_tiles = tiles[i] & (raw(b, 'backfill_level', i) == 0)
        exp_b = own_fractions(np.where(base_tiles[None], base_depth, 1.0), a_, b_).astype('f4').astype('f8')
        n_t = int(base_tiles.sum())
        rep[str(k)] = {'base_tiles': n_t, 'root_depth_equal': int(np.all(bd_ == base_depth, axis=0)[base_tiles].sum()),
                       'root_fract_equal_after_float32': int(np.all(bf_ == exp_b, axis=0)[base_tiles].sum())}
        ok_rep &= rep[str(k)]['root_depth_equal'] == n_t == rep[str(k)]['root_fract_equal_after_float32']
        print(f'class {k}: depth bad {d_bad}, fract bad {f_bad}, donors bad {donor_d}/{donor_f}, reproduction '
              f'{rep[str(k)]["root_fract_equal_after_float32"]}/{n_t}', flush=True)
    k16 = raw(v, 'root_fract', 15)
    zeros16 = int((np.nan_to_num(k16) != 0)[:, tiles[15]].sum())
    checks['root_depth'] = {'by_class': rd_c, 'status': 'passed' if ok_rd else 'failed'}
    checks['root_fract'] = {'tolerance': FRACT_TOL, 'sum_tolerance': SUM_TOL, 'by_class': rf_c, 'class_16_nonzero_on_tiles': zeros16,
                            'status': 'passed' if ok_rf and zeros16 == 0 else 'failed'}
    checks['reproduction'] = {'base_bundle': sprov['inputs']['base_bundle'], 'by_class': rep, 'status': 'passed' if ok_rep else 'failed'}

    # ---- forcing tiles: inherited from the base component's QC, the land-use files unchanged since
    files, checked_files, missing_files = vv.landuse_files(W)
    bq = inp.get('base_qc') or {}
    bqc_path = f'{W}/{bq.get("evidence", "")}/reports/verify.json'
    base_checked = {}; base_status = None
    if os.path.isfile(bqc_path):
        with open(bqc_path) as fh:
            bj = json.load(fh)['checks'].get('forcing_tiles', {})
        base_checked = bj.get('checked_files') or {}; base_status = bj.get('status')
    cv_same = 'Cv' not in differ and 'Nveg' not in differ
    same_files = base_checked == checked_files and not missing_files and all(s is not None for s in checked_files.values())
    ft = {'cv_bitwise_equal_base': cv_same, 'base_qc_status': bq.get('status'), 'base_forcing_tiles_status': base_status,
          'base_checked_files': len(base_checked), 'current_files': len(checked_files),
          'files_differing_from_base_qc': sorted(set(base_checked.items()) ^ set(checked_files.items()))[:10],
          'recorded_files_missing': missing_files, 'checked_files': checked_files}
    ft['status'] = 'passed' if cv_same and bq.get('status') == 'passed' and base_status == 'passed' and same_files else 'failed'
    checks['forcing_tiles'] = ft
    v.close(); b.close()

    status = qc.combine(c['status'] for c in checks.values())
    now = provenance.utcnow()
    qc.write_json(f'{qc_dir}/reports/verify.json', {'object': rel_obj, 'checked_at': now, 'status': status,
                                                    'checked_by': 'workflow/03_parameters/vegetation/verify_roots.py',
                                                    'code_commit': commit, 'code_dirty': dirty, 'checks': checks})
    summary = {'object': rel_obj if not a.component_dir else os.path.relpath(comp, W), 'status': status,
               'checked_by': 'workflow/03_parameters/vegetation/verify_roots.py', 'updated_at': now,
               'checks': {n: c['status'] for n, c in checks.items()}}
    if uncommitted:
        summary['note'] = 'verifier code not committed (repository not clean): results kept in scratch, the status of the object is unchanged'
    qc.write_summary(qc_dir, summary)
    if not a.component_dir and not uncommitted:
        provenance.set_qc(f'{comp}/provenance.yaml', status, f'qc/{rel_obj}')
    print(json.dumps(summary, indent=1))
    qc.exit_with(status)


if __name__ == '__main__':
    main()
