#!/usr/bin/env python3
"""Soil component of a parameter set whose soil fields come from an external VIC parameter file (task Z).

Writes parameters/<status>/<set>/soil/vic_global_5min_soil_<label>.nc: every non-vegetation variable of the base
set's assembled bundle (its provenance names them, method.natural_variables) copied bitwise, except the soil
fields of FIELDS, whose values on the active cells are taken from the external file named with --soil-source,
stored as they are there (double precision, every layer). Nothing is recomputed: the external file is a complete
VIC soil product whose own closure (max_moist = porosity x depth, init_moist) is checked, not rebuilt.

  kept       elev (the external file's elev must equal the base within ELEV_TOL m; reported), phi_s (the external
             file carries a zero compatibility field), the snow bands, run_cell, the diagnostic variables of the
             base soil product, every other natural variable: bitwise from the base
  replaced   FIELDS on the active cells, all layers; a field that is missing in the external file stops the build,
             as does a fill or NaN on an active cell
  inactive   cells outside the domain mask keep the stored fill values of the base, bitwise
  template   the external file's other variables (its own vegetation, snow bands, ...) are not used; the build
             report lists which of the base's natural variables it holds and whether they equal the base

The first use is the MPR soil candidate of vic_parameter (nauta_mpr_reproduced_5m_image_driver_candidate_v2), whose
non-soil variables come from the legacy global parameter file and not from version-a. The root zones of the
vegetation follow in vegetation/recompute_roots.py with the new layer depths.

Outputs: the component file, provenance.yaml and the build report qc/parameters/<status>/<set>/soil/reports/
build_report.json. From a repository that is not clean, or with --scratch, everything goes to
scratch/soil-component/soil/ (qc under its qc/).

Usage: adopt_soil_fields.py --soil-source FILE --soil-label LABEL [--parameter-set vic-global-5arcmin-version-c]
       [--base-set vic-global-5arcmin-version-a] [--parameter-status candidates] [--scratch] [--expect-commit SHA]
"""
import argparse, json, os, re, sys, time

import numpy as np
import netCDF4 as nc

from common import gitstate, hashing, provenance, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'bundle'))
import assemble_bundle as ab   # noqa: E402  (the bitwise variable copy of the bundle assembly and the file names)
sys.path.insert(0, HERE)
import smooth_calibration_fields as sm   # noqa: E402  (base bundle and domain paths, scratch location, helpers)

CREATED_BY = 'workflow/03_parameters/soil/adopt_soil_fields.py'
METHOD_VERSION = '1.0'
FIELDS = ('expt', 'Ksat', 'bubble', 'quartz', 'bulk_density', 'soil_density', 'depth', 'init_moist', 'max_moist',
          'Wcr_FRACT', 'Wpwp_FRACT', 'Wfc_FRACT', 'resid_moist', 'infilt', 'Ds', 'Dsmax', 'Ws', 'c')
ELEV_TOL = 1e-6                                         # m; the external file's elev must equal the base
FORBIDDEN_TOKENS = re.compile(r'(^|[-_])(v\d+|new|old|fix|fixed|final|latest)([-_]|$)')


def out_name(label):
    """File name of the component for a label such as mpr-reproduced."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', label) or FORBIDDEN_TOKENS.search(label):
        raise SystemExit(f'label {label!r}: lower-case letters, digits and hyphens, without version-like tokens')
    return f'vic_global_5min_soil_{label}.nc'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--soil-source', required=True, help='external VIC parameter file (absolute path)')
    ap.add_argument('--soil-label', required=True, help='label of the component file, vic_global_5min_soil_<label>.nc')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-c')
    ap.add_argument('--base-set', default='vic-global-5arcmin-version-a',
                    help='parameter set whose assembled bundle and domain are the inputs')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--scratch', action='store_true', help=f'test run: write under {sm.SCRATCH}/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script for an accepted output: stop unless the repository is clean and at '
                         'this commit')
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    name = out_name(a.soil_label)
    commit, dirty = gitstate.state(REPO); to_scratch = dirty or a.scratch
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    base_rel = f'parameters/{a.parameter_status}/{a.base_set}'; base = f'{W}/{base_rel}'
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/soil'
    out = f'{W}/{sm.SCRATCH}/soil' if to_scratch else f'{W}/{rel_obj}'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{rel_obj}'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out}', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; a component is replaced only with the user\'s authorization')
    f_base, f_dom, f_bprov = f'{base}/{sm.BASE_BUNDLE}', f'{base}/{sm.DOMAIN}', f'{base}/bundle/provenance.yaml'
    f_src = os.path.abspath(a.soil_source)
    for p in (f_base, f_dom, f_bprov, f_src):
        if not os.path.isfile(p):
            raise SystemExit(f'missing input {p}')
    bprov = provenance.read(f_bprov)
    if not to_scratch and ((bprov.get('qc') or {}).get('status') != 'passed' or bprov.get('code_dirty') is not False):
        raise SystemExit(f'the base bundle {f_base} is not accepted (qc {bprov.get("qc")}, code_dirty {bprov.get("code_dirty")})')
    natural = list(bprov['method']['natural_variables'])
    missing = [v for v in FIELDS if v not in natural]
    if missing:
        raise SystemExit(f'fields to replace are not natural variables of the base bundle: {missing}')
    os.makedirs(out, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)

    src = nc.Dataset(f_base); ext = nc.Dataset(f_src); ext.set_auto_mask(False)
    lat = np.asarray(src['lat'][:], 'f8'); lon = np.asarray(src['lon'][:], 'f8')
    with nc.Dataset(f_dom) as d:
        d.set_auto_mask(False)
        mask = np.asarray(d['mask'][:]) == 1; area = np.asarray(d['area'][:], 'f8')
        if not (np.array_equal(np.asarray(d['lat'][:]), lat) and np.array_equal(np.asarray(d['lon'][:]), lon)):
            raise SystemExit('base bundle and domain grids differ')
    if not (np.array_equal(np.asarray(ext['lat'][:], 'f8'), lat) and np.array_equal(np.asarray(ext['lon'][:], 'f8'), lon)):
        raise SystemExit(f'{f_src}: lat or lon differ from the base bundle')
    run_cell, _ = sm.stored(src, 'run_cell')
    if not np.array_equal(run_cell == 1, mask):
        raise SystemExit('run_cell of the base bundle differs from the domain mask')
    for v in natural:
        if ab.VEG_DIM in src[v].dimensions:
            raise SystemExit(f'{v} is listed as a natural variable but has the dimension {ab.VEG_DIM}')
    absent = [v for v in FIELDS if v not in ext.variables]
    if absent:
        raise SystemExit(f'{f_src} has no variable {absent}')

    # ---- the replaced fields: stored values of the external file on the active cells, fill as NaN
    new = {}; report = {'method_version': METHOD_VERSION, 'fields': {}}
    for v in FIELDS:
        if ext[v].dimensions != src[v].dimensions:
            raise SystemExit(f'{v}: dimensions {ext[v].dimensions} of the external file differ from the base {src[v].dimensions}')
        x = sm.as_nan(*sm.stored(ext, v)); b = sm.as_nan(*sm.stored(src, v))
        m = np.broadcast_to(mask, x.shape)
        if np.isnan(x[m]).any():
            raise SystemExit(f'{v}: {int(np.isnan(x[m]).sum())} active cells without a value in the external file')
        new[v] = x
        rep = {}
        for k in (range(x.shape[0]) if x.ndim == 3 else (None,)):
            xk, bk = (x[k], b[k]) if k is not None else (x, b)
            key = f'layer{k + 1}' if k is not None else 'value'
            rep[key] = {'area_mean_base': sm.area_mean(bk, mask, area), 'area_mean_new': sm.area_mean(xk, mask, area),
                        'range_base': [float(np.nanmin(bk[mask])), float(np.nanmax(bk[mask]))],
                        'range_new': [float(xk[mask].min()), float(xk[mask].max())],
                        'cells_changed': int((xk[mask] != bk[mask]).sum())}
        report['fields'][v] = rep
        means = ', '.join(f'{k}: {r["area_mean_base"]:.4g} -> {r["area_mean_new"]:.4g}' for k, r in rep.items())
        print(f'{v}: {means}', flush=True)

    # ---- the external file's other variables, reported only
    template = {}
    for v in natural:
        if v in FIELDS or v not in ext.variables:
            continue
        if ext[v].dimensions != src[v].dimensions:
            template[v] = {'dimensions_differ': True}; continue
        x = sm.as_nan(*sm.stored(ext, v)); b = sm.as_nan(*sm.stored(src, v)); m = np.broadcast_to(mask, x.shape)
        with np.errstate(invalid='ignore'):
            d = np.abs(x - b)[m]
        template[v] = {'max_abs_diff_active': float(np.nanmax(d)) if d.size else 0.0,
                       'cells_differ': int(((d > 0) | np.isnan(d)).sum())}
    report['external_template_variables'] = template
    report['external_variables_missing_from_base_naturals'] = [v for v in natural if v not in ext.variables]
    elev_diff = template.get('elev', {}).get('max_abs_diff_active')
    if elev_diff is None or elev_diff > ELEV_TOL:
        raise SystemExit(f'elev of the external file differs from the base by up to {elev_diff} m (> {ELEV_TOL}); the '
                         f'component keeps the base elev, so the external soil would not belong to this elevation')

    # ---- the component file: every natural variable, the FIELDS with the external values on the active cells
    sha = {'base_bundle': hashing.sha256(f_base), 'domain': hashing.sha256(f_dom), 'base_provenance': hashing.sha256(f_bprov),
           'soil_source': hashing.sha256(f_src)}
    created_at = provenance.utcnow()
    restrictions = ab.source_restrictions(src)
    ext_restrictions = ab.source_restrictions(ext)
    ext_ids = {k: ext.getncattr(k) for k in ('product_id', 'soil_route') if k in ext.ncattrs()}
    f_out = f'{out}/{name}'; part = f_out + '.part'
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
        if v not in FIELDS:
            copied.append(v); continue
        var = o[v]; var.set_auto_maskandscale(False)
        full = np.asarray(var[:]).astype('f8'); m = np.broadcast_to(mask, full.shape)
        full[m] = new[v][m]
        var[:] = full
        var.setncattr('soil_component_change', f'active cells from {os.path.basename(f_src)} (workflow/03_parameters/soil/)')
    o.setncatts({
        'title': 'VIC-WUR 5 arcmin soil component: the non-vegetation variables of the base bundle with the soil '
                 'fields replaced on the active cells by those of an external VIC parameter file',
        'parameter_set': a.parameter_set, 'base_parameter_set': a.base_set, 'base_bundle': f'{base_rel}/{sm.BASE_BUNDLE}',
        'soil_source': f_src, 'soil_source_sha256': sha['soil_source'], 'replaced_fields': ' '.join(FIELDS),
        'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(), 'created_at': created_at,
        'method_version': METHOD_VERSION, 'object': os.path.relpath(out, W),
        **{f'soil_source_{k}': v for k, v in ext_ids.items()}, **ext_restrictions, **restrictions})
    o.close(); src.close(); ext.close()
    os.replace(part, f_out)

    report.update({'created_at': created_at, 'code_commit': commit, 'code_dirty': dirty, 'active_cells': int(mask.sum()),
                   'variables_copied_bitwise': copied, 'variables_replaced': list(FIELDS), 'soil_source': f_src,
                   'soil_source_sha256': sha['soil_source'], 'soil_source_attributes': {**ext_ids, **ext_restrictions},
                   'runtime_s': round(time.time() - t0)})
    json.dump(report, open(f'{qc}/reports/build_report.json', 'w'), indent=1)
    files = [{'path': name, 'size_bytes': os.path.getsize(f_out), 'sha256': hashing.sha256(f_out), 'md5': hashing.md5(f_out)}]
    all_restrictions = {**restrictions, **ext_restrictions}
    prov = {'object': rel_obj if not to_scratch else os.path.relpath(out, W), 'created_by': CREATED_BY,
            'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at, 'method_version': METHOD_VERSION,
            'base_parameter_set': a.base_set,
            'inputs': {'base_bundle': f'{base_rel}/{sm.BASE_BUNDLE}', 'base_provenance': f'{base_rel}/bundle/provenance.yaml',
                       'domain': f'{base_rel}/{sm.DOMAIN}', 'soil_source': f_src},
            'input_sha256': sha,
            'method': {'fields': list(FIELDS), 'kept': 'elev, phi_s, snow bands, run_cell, diagnostics and every other natural '
                       'variable bitwise from the base; the external file\'s other variables are not used',
                       'cells': 'active cells only; cells outside the domain mask keep the base values',
                       'precision': 'stored values of the external file (double)', 'elev_tolerance_m': ELEV_TOL,
                       'soil_source_attributes': {**ext_ids, **ext_restrictions}},
            'rebuild_command': f'python3 {CREATED_BY} --soil-source {f_src} --soil-label {a.soil_label} '
                               f'--parameter-set {a.parameter_set} --base-set {a.base_set} '
                               f'--parameter-status {a.parameter_status}' + (' --scratch' if a.scratch else ''),
            'files': files,
            'restrictions': {**all_restrictions, 'source': f'{base_rel}/{sm.BASE_BUNDLE}; {f_src}'} if all_restrictions else {},
            'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done in {time.time() - t0:.0f} s -> {f_out}')


if __name__ == '__main__':
    main()
