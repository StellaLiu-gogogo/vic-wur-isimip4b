#!/usr/bin/env python3
"""Independent verification of a soil component written by adopt_soil_fields.py.

Checks (each with its own status; the component passes only when all pass):
  grid           lat, lon and run_cell bitwise equal to the base bundle; lat, lon equal the domain and the external
                 file; run_cell equals the domain mask
  unchanged      every natural variable of the base except the replaced fields is bitwise equal to the base bundle
                 (stored values, dtype, dimensions, fill value); the replaced fields are bitwise equal to the base
                 outside the domain mask; no variable of the file comes from anywhere else and none of the base's
                 natural variables is missing
  replaced       on the active cells every replaced field is bitwise equal to the stored values of the external file
                 (every layer) and holds no fill or NaN; the external file is the one of the provenance (sha256)
  elev           elev of the external file equals the kept base elev within the producer's tolerance (the external
                 soil belongs to this elevation)
  closure        the external soil's own closure holds: porosity 1 - bulk_density / soil_density in (0, 1),
                 max_moist = depth x porosity x 1000 within CLOSURE_TOL relative, 0 <= init_moist <= max_moist,
                 resid_moist < porosity, Wpwp_FRACT <= Wcr_FRACT <= Wfc_FRACT <= 1, every field finite
  vic_rules      on the active cells the rules of vic_init.c (VIC 39e21ff5): every layer >= 0.001 m and layer 1
                 not thicker than layer 2; the NIJSSEN2001 conversion: Ws below the bottom layer's maximum
                 moisture, converted Ds and Ws in [0, 1], converted Dsmax and c > 0; expt > 3, Ksat > 0, bubble > 0,
                 quartz in [0, 1], infilt > 0 (the assembled bundle is checked again by verify_bundle.py)
Reported only: the area-weighted global means of every replaced field in the base and the component, and which of
the base's other natural variables the external file holds with different values (its own template, not used).
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{<field>_<region>.png, depth2_global.png}, where
<qc> is qc/parameters/<status>/<set>/soil/ (or <component-dir>/qc/ with --component-dir), and sets qc.status in the
component's provenance.yaml (not with --component-dir). Exit status: 0 passed, 1 failed (common/qc.py).

Usage: verify_adopted_soil.py [--parameter-set ID] [--parameter-status candidates] [--component-dir DIR]
"""
import argparse, json, os, sys

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common import gitstate, hashing, provenance, qc, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import smooth_calibration_fields as sm   # noqa: E402  (scratch location, area mean)
import adopt_soil_fields as ad           # noqa: E402  (the replaced fields, elev tolerance, file name)
from verify_soil import raw, same_bits, fill_of, active_values   # noqa: E402

CHECKED_BY = 'workflow/03_parameters/soil/verify_adopted_soil.py'
CLOSURE_TOL = 1e-6
MINSOILDEPTH = 0.001          # m, vic_run/include/vic_def.h
REGIONS = {'west_siberia': (58, 66, 78, 90), 'alps': (42, 50, 2, 14)}   # lat0, lat1, lon0, lon1
MAPPED = (('depth', 1), ('Ds', None), ('Wcr_FRACT', 1))                 # (field, layer index or None)


def component_file(comp, prov):
    files = [f['path'] for f in prov.get('files', []) if f['path'].endswith('.nc')]
    if len(files) != 1:
        raise SystemExit(f'the provenance of {comp} names {len(files)} NetCDF files; expected one')
    return f'{comp}/{os.path.basename(files[0])}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-c')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--component-dir', default=None, help='verify a component in this directory (scratch test)')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    ap.add_argument('--qc-to-scratch', action='store_true',
                    help='set by the submit script when the repository was not clean: results go to scratch')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(sm.REPO)
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    uncommitted = not a.component_dir and (dirty or a.qc_to_scratch)
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/soil'
    comp = a.component_dir or f'{W}/{rel_obj}'
    qc_dir = f'{comp}/qc' if a.component_dir else f'{W}/qc/{rel_obj}'
    if uncommitted:
        qc_dir = f'{W}/{sm.SCRATCH}/verify-uncommitted/qc/{rel_obj}'
    os.makedirs(f'{qc_dir}/reports', exist_ok=True); os.makedirs(f'{qc_dir}/figures', exist_ok=True)
    prov = provenance.read(f'{comp}/provenance.yaml')
    if prov.get('created_by') != ad.CREATED_BY:
        raise SystemExit(f'{comp} was written by {prov.get("created_by")}, not by {ad.CREATED_BY}')
    fields = list(prov['method']['fields'])
    f_out = component_file(comp, prov); f_src = prov['inputs']['soil_source']
    base = nc.Dataset(f'{W}/{prov["inputs"]["base_bundle"]}'); out = nc.Dataset(f_out)
    ext = nc.Dataset(f_src); ext.set_auto_mask(False)
    natural = list(provenance.read(f'{W}/{prov["inputs"]["base_provenance"]}')['method']['natural_variables'])
    with nc.Dataset(f'{W}/{prov["inputs"]["domain"]}') as d:
        d.set_auto_mask(False)
        dmask = np.asarray(d['mask'][:]) == 1; dlat = np.asarray(d['lat'][:]); dlon = np.asarray(d['lon'][:])
        area = np.asarray(d['area'][:], 'f8')
    checks = {}

    # ---- grid and mask
    lat = np.asarray(out['lat'][:], 'f8'); lon = np.asarray(out['lon'][:], 'f8')
    rc = raw(out, 'run_cell'); mask = rc == 1
    g = {'lat_equals_base': same_bits(raw(out, 'lat'), raw(base, 'lat')), 'lon_equals_base': same_bits(raw(out, 'lon'), raw(base, 'lon')),
         'run_cell_equals_base': same_bits(rc, raw(base, 'run_cell')), 'lat_equals_domain': bool(np.array_equal(lat, dlat)),
         'lon_equals_domain': bool(np.array_equal(lon, dlon)), 'run_cell_equals_domain_mask': bool(np.array_equal(mask, dmask)),
         'lat_equals_source': bool(np.array_equal(lat, np.asarray(ext['lat'][:], 'f8'))),
         'lon_equals_source': bool(np.array_equal(lon, np.asarray(ext['lon'][:], 'f8'))), 'active_cells': int(mask.sum())}
    checks['grid'] = {**g, 'status': 'passed' if all(v for k, v in g.items() if k != 'active_cells') else 'failed'}

    # ---- unchanged variables
    out_vars = [v for v in out.variables if v not in ('lat', 'lon')]
    differ = []; foreign = [v for v in out_vars if v not in natural]; missing = [v for v in natural if v not in out.variables]
    inactive_diff = {}
    for v in natural:
        if v not in out.variables:
            continue
        o, b = out[v], base[v]
        fo, fb = fill_of(o), fill_of(b)
        same_fill = (fo is None and fb is None) or (fo is not None and fb is not None and
                                                   (fo == fb or (np.isnan(float(fo)) and np.isnan(float(fb)))))
        meta_ok = o.dtype == b.dtype and o.dimensions == b.dimensions and o.shape == b.shape and same_fill
        if v not in fields:
            if not meta_ok or not same_bits(raw(out, v), raw(base, v)):
                differ.append(v)
            continue
        if not meta_ok:
            differ.append(v); continue
        xo, xb = raw(out, v), raw(base, v); bits = f'u{xo.dtype.itemsize}'
        m = np.broadcast_to(mask, xo.shape)
        inactive_diff[v] = int((xo[~m].view(bits) != xb[~m].view(bits)).sum())
    u = {'variables': len(natural), 'differ': differ, 'foreign': foreign, 'missing': missing, 'inactive_cells_differ': inactive_diff}
    u['status'] = 'passed' if not (differ or foreign or missing or any(inactive_diff.values())) else 'failed'
    checks['unchanged'] = u

    # ---- replaced fields: bitwise the external file's stored values on the active cells
    sha_ok = hashing.sha256(f_src) == prov['input_sha256']['soil_source']
    rep = {}; ok_rep = sha_ok
    vals = {}
    for v in fields:
        xo, xs = raw(out, v), raw(ext, v)
        m = np.broadcast_to(mask, xo.shape)
        same = xo.shape == xs.shape and bool(np.array_equal(xo[m].view(f'u{xo.dtype.itemsize}'),
                                                           xs[m].astype(xo.dtype).view(f'u{xo.dtype.itemsize}')))
        x = active_values(out, v, mask)
        bad = int((~np.isfinite(x[m])).sum())
        rep[v] = {'equals_source_on_active_cells': same, 'active_cells_without_value': bad}
        ok_rep &= same and bad == 0
        vals[v] = x
    checks['replaced'] = {'soil_source': f_src, 'source_sha256_as_recorded': sha_ok, 'by_field': rep,
                          'status': 'passed' if ok_rep else 'failed'}

    # ---- elev: the external file's elev equals the kept base elev
    e_src = active_values(ext, 'elev', mask) if 'elev' in ext.variables else None
    e_out = active_values(out, 'elev', mask)
    ed = float(np.nanmax(np.abs(e_src - e_out)[mask])) if e_src is not None else None
    checks['elev'] = {'max_abs_diff_m': ed, 'tolerance_m': ad.ELEV_TOL, 'elev_kept_from_base': 'elev' not in fields,
                      'status': 'passed' if ed is not None and ed <= ad.ELEV_TOL and 'elev' not in fields else 'failed'}

    # ---- closure of the external soil
    m = mask
    with np.errstate(invalid='ignore', divide='ignore'):
        por = 1 - vals['bulk_density'] / vals['soil_density']
        mm_expect = vals['depth'] * por * 1000.0
        rel_mm = np.abs(vals['max_moist'] / mm_expect - 1)
    m3 = np.broadcast_to(mask, por.shape)
    cl = {'porosity_outside_0_1': int((~((por[m3] > 0) & (por[m3] < 1))).sum()),
          'max_moist_max_relative_deviation': float(np.nanmax(rel_mm[m3])),
          'init_moist_outside_0_max': int((~((vals['init_moist'][m3] >= 0) & (vals['init_moist'][m3] <= vals['max_moist'][m3]))).sum()),
          'resid_moist_not_below_porosity': int((~(vals['resid_moist'][m3] < por[m3])).sum()),
          'moisture_fractions_disordered': int((~((vals['Wpwp_FRACT'][m3] <= vals['Wcr_FRACT'][m3]) &
                                                 (vals['Wcr_FRACT'][m3] <= vals['Wfc_FRACT'][m3]) & (vals['Wfc_FRACT'][m3] <= 1))).sum()),
          'not_finite': {v: int((~np.isfinite(x[np.broadcast_to(mask, x.shape)])).sum()) for v, x in vals.items()}}
    cl['status'] = 'passed' if cl['porosity_outside_0_1'] == 0 and cl['max_moist_max_relative_deviation'] <= CLOSURE_TOL \
        and cl['init_moist_outside_0_max'] == 0 and cl['resid_moist_not_below_porosity'] == 0 \
        and cl['moisture_fractions_disordered'] == 0 and not any(cl['not_finite'].values()) else 'failed'
    checks['closure'] = cl

    # ---- VIC rules (vic_init.c, BASEFLOW NIJSSEN2001)
    depth = vals['depth']; mm_bottom = depth[2] * por[2] * 1000.0
    Ds, Dsmax, Ws, c = (vals[k] for k in ('Ds', 'Dsmax', 'Ws', 'c'))
    with np.errstate(invalid='ignore', divide='ignore'):
        dsmax_c = Dsmax * (mm_bottom - Ws) ** c + Ds * mm_bottom
        ds_c = Ds * Ws / dsmax_c; ws_c = Ws / mm_bottom
    vr = {'layer_below_min': int((depth[:, m] < MINSOILDEPTH).sum()), 'depth1_thicker_than_depth2': int((depth[0][m] > depth[1][m]).sum()),
          'Ws_not_below_bottom_max_moist': int((~(Ws[m] < mm_bottom[m])).sum()),
          'converted_Ds_outside_0_1': int((~((ds_c[m] >= 0) & (ds_c[m] <= 1))).sum()),
          'converted_Ws_outside_0_1': int((~((ws_c[m] >= 0) & (ws_c[m] <= 1))).sum()),
          'converted_Dsmax_not_positive': int((~(dsmax_c[m] > 0)).sum()), 'c_not_positive': int((~(c[m] > 0)).sum()),
          'expt_not_above_3': int((~(vals['expt'][m3] > 3)).sum()), 'Ksat_not_positive': int((~(vals['Ksat'][m3] > 0)).sum()),
          'bubble_not_positive': int((~(vals['bubble'][m3] > 0)).sum()),
          'quartz_outside_0_1': int((~((vals['quartz'][m3] >= 0) & (vals['quartz'][m3] <= 1))).sum()),
          'infilt_not_positive': int((~(vals['infilt'][m] > 0)).sum())}
    vr['status'] = 'passed' if all(v == 0 for v in vr.values()) else 'failed'
    checks['vic_rules'] = vr

    # ---- report only: global means and the external file's template variables
    gm = {}
    for v in fields:
        xb = active_values(base, v, mask); xo = vals[v]
        if xo.ndim == 3:
            gm[v] = {f'layer{k + 1}': {'base': sm.area_mean(xb[k], mask, area), 'new': sm.area_mean(xo[k], mask, area)} for k in range(xo.shape[0])}
        else:
            gm[v] = {'base': sm.area_mean(xb, mask, area), 'new': sm.area_mean(xo, mask, area)}
    checks['global_means'] = {'note': 'report only', 'by_field': gm, 'status': 'passed'}
    tpl = {}
    for v in natural:
        if v in fields or v not in ext.variables or ext[v].dimensions != base[v].dimensions:
            continue
        xs = active_values(ext, v, mask); xb = active_values(base, v, mask); mm = np.broadcast_to(mask, xs.shape)
        with np.errstate(invalid='ignore'):
            d = np.abs(xs - xb)[mm]
        tpl[v] = {'max_abs_diff_active': float(np.nanmax(d)) if d.size else 0.0, 'cells_differ': int(((d > 0) | np.isnan(d)).sum())}
    checks['external_template'] = {'note': 'report only: the external file\'s other variables are not used',
                                   'variables': tpl, 'status': 'passed'}

    # ---- figures
    for name, k in MAPPED:
        xb = active_values(base, name, mask); xo = vals[name]
        fb, fo = (xb[k], xo[k]) if k is not None else (xb, xo)
        for rname, (la0, la1, lo0, lo1) in REGIONS.items():
            r = np.flatnonzero((lat >= la0) & (lat <= la1)); cc = np.flatnonzero((lon >= lo0) & (lon <= lo1))
            if r.size == 0 or cc.size == 0:
                continue
            fig, axs = plt.subplots(1, 2, figsize=(14, 5), dpi=110)
            for ax, (lab, x) in zip(axs, (('base', fb), ('adopted', fo))):
                sub = np.where(mask, x, np.nan)[np.ix_(r, cc)]
                im = ax.imshow(sub[::-1], extent=(lon[cc].min(), lon[cc].max(), lat[r].min(), lat[r].max()),
                               cmap='viridis', aspect='auto', interpolation='nearest')
                ax.set_title(f'{name}{"[" + str(k + 1) + "]" if k is not None else ""} {lab} ({rname})'); fig.colorbar(im, ax=ax, shrink=0.8)
            fig.tight_layout(); fig.savefig(f'{qc_dir}/figures/{name}_{rname}.png'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(14, 6), dpi=110)
    im = ax.imshow(np.where(mask, depth[1], np.nan)[::-1], extent=(lon.min(), lon.max(), lat.min(), lat.max()), cmap='viridis',
                   aspect='auto', interpolation='nearest')
    fig.colorbar(im, ax=ax, shrink=0.8, label='m'); ax.set_title('depth of layer 2, adopted')
    fig.tight_layout(); fig.savefig(f'{qc_dir}/figures/depth2_global.png'); plt.close(fig)
    out.close(); base.close(); ext.close()

    status = qc.combine(c['status'] for c in checks.values())
    now = provenance.utcnow()
    qc.write_json(f'{qc_dir}/reports/verify.json', {'object': rel_obj, 'checked_at': now, 'status': status,
                                                    'checked_by': CHECKED_BY, 'code_commit': commit, 'code_dirty': dirty,
                                                    'checks': checks})
    summary = {'object': rel_obj if not a.component_dir else os.path.relpath(comp, W), 'status': status,
               'checked_by': CHECKED_BY, 'updated_at': now, 'checks': {n: c['status'] for n, c in checks.items()}}
    if uncommitted:
        summary['note'] = 'verifier code not committed (repository not clean): results kept in scratch, the status of the object is unchanged'
    qc.write_summary(qc_dir, summary)
    if not a.component_dir and not uncommitted:
        provenance.set_qc(f'{comp}/provenance.yaml', status, f'qc/{rel_obj}')
    print(json.dumps(summary, indent=1))
    qc.exit_with(status)


if __name__ == '__main__':
    main()
