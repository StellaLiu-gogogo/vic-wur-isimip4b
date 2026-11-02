#!/usr/bin/env python3
"""Independent verification of the assembled 16-class image-driver parameter file (assemble_bundle.py).

Checks (each with its own status):
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
  natural         every other variable is bitwise equal to the source of the non-vegetation variables named in
                  the file's provenance.yaml (inputs.natural_bundle, the adopted natural bundle, or
                  inputs.soil_component, the soil component of the set), and no variable of the file comes from
                  anywhere else
  tiles           on active cells: Nveg <= number of classes with Cv > 0 <= Nveg + 1 (vic_init.c), and the
                  int-read overstory is 0 or 1 on every tile
  soil            on active cells, failed when a rule of vic_init.c is broken (no fill or NaN, except in annual_prec,
                  which VIC reads but uses in no calculation, so its fill and values are reported only; layer depth
                  >= 0.001 m, layer 1 not thicker than layer 2; porosity 1 - bulk_density / soil_density in (0, 1);
                  Wpwp_FRACT <= Wcr_FRACT <= Wfc_FRACT <= 1; wilting point >= residual moisture; NIJSSEN2001
                  baseflow: Ws below the bottom layer's maximum moisture, converted Ds and Ws in [0, 1], converted
                  Dsmax and c > 0); warning for implausible values (Ksat, bubble, rough, snow_rough, dp <= 0;
                  expt < 3; quartz outside [0, 1]; resid_moist >= porosity; fs_active not 0/1; avg_T outside
                  AVG_T_RANGE; infilt outside (0, 1]; init_moist above the maximum moisture); statistics,
                  the gap-fill diagnostics, max_moist (not read by VIC) and the cells with bulk or soil density
                  below 500 kg m-3 are reported only
  snow_bands      on active cells, failed when VIC stops (fill or NaN; AreaFract < 0 or summing to 0; Pfactor < 0 or
                  > 0 on a band without area); warning when VIC changes values without stopping (AreaFract or
                  Pfactor not summing to 1 within 1e-5; area-weighted mean band elevation not equal to elev within
                  1e-5 m, so VIC replaces elev, the elevation the climate forcing was downscaled to)
The check passes when all pass; a warning (exit status 3) is not an acceptance.
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{soil_total_depth,band_mean_minus_elev}.png,
where <qc> is qc/parameters/<status>/<set>/bundle/
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


# ---------------------------------------------------------------------------------------------- soil and snow bands
SOIL_2D = ('infilt', 'Ds', 'Dsmax', 'Ws', 'c', 'elev', 'avg_T', 'dp', 'rough', 'snow_rough', 'annual_prec', 'fs_active')
SOIL_3D = ('expt', 'Ksat', 'init_moist', 'phi_s', 'depth', 'bubble', 'quartz', 'bulk_density', 'soil_density',
           'Wcr_FRACT', 'Wpwp_FRACT', 'resid_moist', 'Wfc_FRACT')
BANDS = ('AreaFract', 'elevation', 'Pfactor')
MINSOILDEPTH = 0.001          # m, vic_run/include/vic_def.h
SUM_TOL = 1e-5                # AREA_SUM_ERROR_THRESH (absolute), drivers/shared_image/include/vic_driver_shared_image.h
AVG_T_RANGE = (-60.0, 40.0)   # degC, plausible mean annual air temperature
# read by vic_init.c but used in no calculation of VIC 39e21ff5 (only printed): fill and values are reported only
# (user, 2026-10-30)
READ_NOT_USED = ('annual_prec',)
LOW_DENSITY = 500.0           # kg m-3, bulk or soil density below this is counted for the report


def stats(x):
    x = np.asarray(x, 'f8').ravel(); x = x[np.isfinite(x)]
    if x.size == 0:
        return {'n': 0}
    q = np.percentile(x, [1, 50, 99])
    return {'n': int(x.size), 'min': float(x.min()), 'p1': float(q[0]), 'median': float(q[1]), 'p99': float(q[2]),
            'max': float(x.max()), 'mean': float(x.mean())}


def soil_checks(v):
    """VIC rules (vic_init.c at VIC 39e21ff5, BASEFLOW NIJSSEN2001, WFC_SRC FROM_VEGPARAM) and plausibility of the
    soil variables on the active cells. v: {name: float array (cells,) or (nlayer, cells)}, fill already replaced by
    NaN. Returns (vic, plausible, derived): counts of cells breaking each rule; derived holds porosity, max_moist."""
    any_l = lambda b: int(np.asarray(b).any(axis=0).sum()) if np.ndim(b) == 2 else int(np.sum(b))   # noqa: E731
    fill = {k: any_l(~np.isfinite(v[k])) for k in SOIL_2D + SOIL_3D if k not in READ_NOT_USED}
    with np.errstate(invalid='ignore', divide='ignore'):
        por = 1 - v['bulk_density'] / v['soil_density']
        mm = v['depth'] * por * 1000.0                                   # max_moist, mm
        wpwp_mm = v['Wpwp_FRACT'] * mm
        resid_mm = v['resid_moist'] * v['depth'] * 1000.0
        mm_b = mm[-1]
        dsmax = v['Dsmax'] * (mm_b - v['Ws']) ** v['c'] + v['Ds'] * mm_b  # converted ARNO Dsmax (mm/day)
        ds = v['Ds'] * v['Ws'] / dsmax
        ws = v['Ws'] / mm_b
        vic = {
            'fill_or_nan': {k: n for k, n in fill.items() if n},
            'depth_below_min': any_l(v['depth'] < MINSOILDEPTH),
            'layer1_thicker_than_layer2': int((v['depth'][0] > v['depth'][1]).sum()),
            'porosity_outside_0_1': any_l(~((por > 0) & (por < 1))),
            'Wpwp_above_Wcr': any_l(v['Wpwp_FRACT'] > v['Wcr_FRACT']),
            'Wcr_above_Wfc': any_l(v['Wcr_FRACT'] > v['Wfc_FRACT']),
            'Wfc_above_1': any_l(v['Wfc_FRACT'] > 1),
            'wilting_point_below_residual': any_l(wpwp_mm < resid_mm),
            'Ws_not_below_bottom_max_moist': int(np.sum(~(v['Ws'] < mm_b))),
            'converted_Ds_outside_0_1': int(np.sum(~((ds >= 0) & (ds <= 1)))),
            'converted_Ws_outside_0_1': int(np.sum(~((ws >= 0) & (ws <= 1)))),
            'converted_Dsmax_not_positive': int(np.sum(~(dsmax > 0))),
            'c_not_positive': int(np.sum(~(v['c'] > 0))),
        }
        lo, hi = AVG_T_RANGE
        plausible = {
            **{f'{k}_not_positive': any_l(~(v[k] > 0)) for k in ('Ksat', 'bubble', 'rough', 'snow_rough', 'dp')},
            'expt_below_3': any_l(v['expt'] < 3),
            'quartz_outside_0_1': any_l(~((v['quartz'] >= 0) & (v['quartz'] <= 1))),
            'resid_moist_not_below_porosity': any_l(~(v['resid_moist'] < por)),
            'fs_active_not_0_or_1': int(np.sum(~np.isin(v['fs_active'], (0, 1)))),
            'avg_T_outside_range': int(np.sum(~((v['avg_T'] >= lo) & (v['avg_T'] <= hi)))),
            'infilt_outside_0_1': int(np.sum(~((v['infilt'] > 0) & (v['infilt'] <= 1)))),
            'init_moist_above_max_moist': any_l(v['init_moist'] > mm),
        }
    unused = {k: {'fill_or_nan': int(np.sum(~np.isfinite(v[k]))), 'not_positive': int(np.sum(v[k] <= 0))}
              for k in READ_NOT_USED}
    return vic, plausible, {'unused': unused, 'porosity': por, 'max_moist': mm, 'Ds_converted': ds, 'Ws_converted': ws,
                            'Dsmax_converted': dsmax}


def band_checks(af, el, pf, elev):
    """Snow-band rules of vic_init.c on the active cells. af, el, pf: (snow_band, cells); elev: (cells,).
    Returns (vic, silent, mean_minus_elev): rules that stop VIC; values VIC changes without stopping (sums
    rescaled, cell elevation replaced by the band mean, as the forcing was downscaled to elev)."""
    s = af.sum(axis=0)
    off = ~(np.abs(s - 1) <= SUM_TOL)
    afn = np.where(off & (s > 0), af / np.where(s > 0, s, 1), af)            # VIC divides by the sum
    mean = (el * afn).sum(axis=0)
    diff = mean - elev
    ps = pf.sum(axis=0)
    nan = (~np.isfinite(af) | ~np.isfinite(el) | ~np.isfinite(pf)).any(axis=0) | ~np.isfinite(elev)
    vic = {'fill_or_nan': int(nan.sum()),
           'AreaFract_negative': int((af < 0).any(axis=0).sum()), 'AreaFract_sum_0': int((s <= 0).sum()),
           'Pfactor_negative': int((pf < 0).any(axis=0).sum()),
           'Pfactor_on_band_without_area': int(((pf > 0) & (af == 0)).any(axis=0).sum())}
    silent = {'AreaFract_sum_not_1': int(off.sum()), 'Pfactor_sum_not_1': int((~(np.abs(ps - 1) <= SUM_TOL)).sum()),
              'band_mean_elevation_not_elev': int((~(np.abs(diff) <= SUM_TOL)).sum()),
              'band_mean_elevation_minus_elev_max_abs_m': float(np.nanmax(np.abs(diff))) if diff.size else 0.0}
    return vic, silent, diff


def status_of(vic, plausible):
    def bad(d):
        return any((bad(x) if isinstance(x, dict) else x > 0) for k, x in d.items() if not k.endswith('_max_abs_m'))
    return 'failed' if bad(vic) else 'warning' if bad(plausible) else 'passed'


def save_map(path, values, lat, lon, title, label, cmap='viridis', vmin=None, vmax=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 6), dpi=120)
    img = values[::-1] if lat[0] < lat[-1] else values
    im = ax.imshow(img, extent=(lon.min(), lon.max(), lat.min(), lat.max()), cmap=cmap, vmin=vmin, vmax=vmax,
                   interpolation='nearest', aspect='auto')
    fig.colorbar(im, ax=ax, label=label, shrink=0.8)
    ax.set_title(title); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


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
    out = nc.Dataset(f'{bdir}/{ab.OUT_NAME}'); veg = nc.Dataset(f'{pset}/{ab.VEGETATION}')
    bprov = yaml.safe_load(open(f'{bdir}/provenance.yaml'))
    source_keys = [k for k in ab.SOURCE_KEYS if k in (bprov.get('inputs') or {})]
    if len(source_keys) != 1:
        raise SystemExit(f'{bdir}/provenance.yaml must name exactly one of {ab.SOURCE_KEYS} under inputs')
    source_rel = bprov['inputs'][source_keys[0]]
    nat = nc.Dataset(f'{W}/{source_rel}')
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
    checks['natural'] = {'variables': len(nat_vars), 'source': source_rel, 'differ_or_foreign': differ_n,
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
    del cv, ov, tiles

    # ---- soil and snow-band values on active cells (stored values, fill as NaN)
    def active(name):
        x = raw(out, name); fv = getattr(out[name], '_FillValue', None)
        x = (x[..., mask] if x.ndim == 3 else x[mask]).astype('f8')
        return np.where(x == fv, np.nan, x) if fv is not None and not np.isnan(fv) else x
    v = {k: active(k) for k in SOIL_2D + SOIL_3D}
    vic, plausible, der = soil_checks(v)
    soil_stats = {k: stats(v[k]) if np.ndim(v[k]) == 1 else {f'layer{i + 1}': stats(v[k][i]) for i in range(len(v[k]))}
                  for k in v}
    soil_stats |= {'porosity': {f'layer{i + 1}': stats(der['porosity'][i]) for i in range(3)},
                   'Ds_converted': stats(der['Ds_converted']), 'Ws_converted': stats(der['Ws_converted']),
                   'Dsmax_converted_mm_per_day': stats(der['Dsmax_converted']),
                   'total_depth_m': stats(v['depth'].sum(axis=0))}
    report_only = {'read_but_not_used_by_vic': der['unused'],
                   f'cells_with_density_below_{LOW_DENSITY:g}_kg_m3': {
                       k: int((v[k] < LOW_DENSITY).any(axis=0).sum()) for k in ('bulk_density', 'soil_density')}}
    if 'max_moist' in out.variables:
        with np.errstate(invalid='ignore', divide='ignore'):
            rel = np.abs(active('max_moist') / der['max_moist'] - 1)
        report_only['max_moist_vs_depth_porosity_max_relative'] = float(np.nanmax(rel))
    if 'gapfill_distance_degrees' in out.variables:
        g = active('gapfill_distance_degrees')
        report_only['gapfilled_fraction_of_active_cells'] = {f'layer{i + 1}': float((g[i] > 0).mean()) for i in range(len(g))}
        report_only['gapfill_distance_degrees'] = stats(g[g > 0])
    report_only['valid_fraction'] = {k: stats(active(k)) for k in out.variables if k.endswith('_valid_fraction')}
    checks['soil'] = {'cells': int(mask.sum()), 'vic_rules': vic, 'plausibility': plausible,
                      'avg_T_range_degC': list(AVG_T_RANGE), 'statistics': soil_stats, 'report_only': report_only,
                      'status': status_of(vic, plausible)}
    af, el, pf = active('AreaFract'), active('elevation'), active('Pfactor')
    bvic, silent, diff = band_checks(af, el, pf, v['elev'])
    nbands = (af > 0).sum(axis=0)
    band_report = {'bands_with_area': {str(k): int(n) for k, n in zip(*np.unique(nbands, return_counts=True))}}
    if 'Nelev' in out.variables:
        band_report['Nelev_differs_from_bands_with_area'] = int((active('Nelev') != nbands).sum())
    checks['snow_bands'] = {'vic_rules': bvic, 'changed_silently_by_vic': silent, 'tolerance': SUM_TOL,
                            'band_mean_minus_elev_m': stats(diff), 'report_only': band_report,
                            'status': status_of(bvic, silent)}
    os.makedirs(f'{qc}/figures', exist_ok=True)
    m2 = np.full(mask.shape, np.nan)
    m2[mask] = v['depth'].sum(axis=0)
    save_map(f'{qc}/figures/soil_total_depth.png', m2, dlat, dlon, 'total soil depth (sum of the 3 layers)', 'm',
             vmin=0, vmax=float(np.nanpercentile(m2, 99)))
    m2[mask] = diff
    lim = max(float(np.nanpercentile(np.abs(diff), 99)), SUM_TOL)
    save_map(f'{qc}/figures/band_mean_minus_elev.png', m2, dlat, dlon,
             'area-weighted mean snow-band elevation minus elev', 'm', cmap='RdBu_r', vmin=-lim, vmax=lim)

    sts = [c['status'] for c in checks.values()]
    status = 'failed' if 'failed' in sts else 'warning' if 'warning' in sts else 'passed'
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
    sys.exit({'passed': 0, 'failed': 1, 'warning': 3}[status])   # the exit status of workflow/common/qc.py


if __name__ == '__main__':
    main()
