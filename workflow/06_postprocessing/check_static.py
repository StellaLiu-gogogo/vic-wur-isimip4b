#!/usr/bin/env python3
"""Check of the static files of a product set (static_fields.py; D07, D08, D11).

Recomputes what it checks by another route than the producer (5' arrays reshaped into 6 x 6 blocks instead of
summed by cell index) and writes qc/postprocessed/<product-set-id>/static/ (below scratch/<task>/ with --scratch):
summary.json, reports/check.json, reports/outlets_ddm30.csv, figures/*.png.

Checks (each passed, warning or failed; the summary takes the worst):
  files       every file present; data model, compression level, one chunk per field and layer, fill value of the
              configuration, global attributes institution and contact, ISIMIP units and long names of the protocol,
              the grid of the ISIMIP mask
  coverage    values exactly on the mask cells with an active 5' cell; the number of uncovered mask cells equals the
              D08 number
  cellarea    equal to the sum of the 36 domain areas; its relative difference from the analytic WGS84 cell area
              above the tolerance of products.yaml is a warning
  contfrac    in (0, 1]; landfrac equal to contfrac; sum of contfrac x cellarea equal to the area of the counted 5'
              cells
  soil_layers positive thicknesses equal to the weighted block mean of the 5' layer depths; bottoms their sum
  outlets     every covered cell has an outlet inside its block, active and inside the mask, with the largest upstream
              area of the block; upstream areas conserve the area of the network (the outlets of the 5' network carry
              all active area); n_cells equal to the count of counted 5' cells
Diagnostic only (D07 part 2, not part of the status): upstream area of each outlet against the DDM30 upstream area of
its 0.5-degree cell, for cells with a DDM30 upstream area of at least ddm30_min_area_km2.

Exit status: passed 0, failed 1, warning 3, not_checked 4.
Usage: check_static.py --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import json
import os
import sys

import numpy as np
import netCDF4 as nc
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import static_fields   # noqa: E402
import routing        # noqa: E402
import support        # noqa: E402

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563


# ------------------------------------------------------------------------------------------------ geometry
def wgs84_band_area_km2(lat_south, lat_north, dlon_deg):
    """Area (km2) of the WGS84 ellipsoid between two latitudes over dlon_deg degrees of longitude (authalic form)."""
    e2 = WGS84_F * (2 - WGS84_F); e = np.sqrt(e2); b = WGS84_A * (1 - WGS84_F)

    def q(lat):
        s = np.sin(np.radians(lat))
        return s / (1 - e2 * s * s) + np.log((1 + e * s) / (1 - e * s)) / (2 * e)

    return 0.5 * b * b * np.radians(dlon_deg) * (q(lat_north) - q(lat_south)) / 1e6


def blocks(a, rows05, cols05, f):
    """5' array (..., ny5, nx5) as (..., ny05, f, nx05, f) blocks."""
    return a.reshape(*a.shape[:-2], rows05, f, cols05, f)


def place(values, lat_blocks, lat05):
    """Put block values (rows of the 5' block order) onto the rows of the 0.5-degree grid by their latitudes."""
    step = lat05[1] - lat05[0]
    idx = np.rint((lat_blocks - lat05[0]) / step).astype('i8')
    out = np.full(values.shape[:-2] + (lat05.size, values.shape[-1]), np.nan)
    out[..., idx, :] = values
    return out


# ------------------------------------------------------------------------------------------------ checks
def check_files(static_dir, cfg, protocol, mask_coords):
    problems = []
    rules = cfg['file_rules']; fill = cfg['fill_value']
    for fname in static_fields.STATIC_FILES:
        p = os.path.join(static_dir, fname)
        if not os.path.exists(p):
            problems.append(f'{fname} missing'); continue
        with nc.Dataset(p) as d:
            if d.data_model != rules['data_model']:
                problems.append(f'{fname}: data model {d.data_model}')
            for k in ('institution', 'contact'):
                if not getattr(d, k, ''):
                    problems.append(f'{fname}: global attribute {k} missing')
            for name in ('lat', 'lon'):
                if not np.array_equal(d[name][:], mask_coords[name][0]):
                    problems.append(f'{fname}: {name} differs from the ISIMIP mask grid')
            for name, v in d.variables.items():
                if name in ('lat', 'lon', 'layer'):
                    continue
                flt = v.filters() or {}
                if not flt.get('zlib') or flt.get('complevel', 0) < rules['complevel']:
                    problems.append(f'{fname}:{name}: compression {flt}')
                want = [1 if dd == 'layer' else len(d.dimensions[dd]) for dd in v.dimensions]
                if v.chunking() != want:
                    problems.append(f'{fname}:{name}: chunks {v.chunking()} instead of {want}')
                if v.dtype.kind == 'f' and not np.isclose(v._FillValue, fill):
                    problems.append(f'{fname}:{name}: fill value {v._FillValue}')
                if name in protocol:
                    for key in ('units', 'long_name'):
                        want_v = support.for_sector(protocol[name][key])
                        if getattr(v, key, None) != want_v:
                            problems.append(f'{fname}:{name}: {key} {getattr(v, key, None)!r} instead of {want_v!r}')
    return ('failed' if problems else 'passed'), {'problems': problems}


def read_static(static_dir):
    out = {}
    for fname in static_fields.STATIC_FILES:
        with nc.Dataset(os.path.join(static_dir, fname)) as d:
            for name, v in d.variables.items():
                if name not in ('lat', 'lon', 'layer'):
                    a = v[:]
                    out[name] = np.ma.filled(a.astype('f8'), np.nan) if v.dtype.kind == 'f' else \
                        np.ma.filled(a, -1).astype('i8')
    return out


def check_all(fx, ref, cfg):
    """Every check except the file format, from the static fields `fx` and the recomputed references `ref`."""
    res = {}
    cov = ref['covered']; inmask = ref['inmask']
    # coverage
    probs = []
    for name in ('cellarea', 'contfrac', 'landfrac'):
        has = np.isfinite(fx[name])
        if (has != cov).any():
            probs.append(f'{name}: {int((has & ~cov).sum())} values off the covered cells, '
                         f'{int((~has & cov).sum())} covered cells missing')
    for name in ('layer_thickness', 'layer_bottom'):
        if (np.isfinite(fx[name]) != cov[None]).any():
            probs.append(f'{name}: values do not match the covered cells')
    if ((fx['outlet_row'] >= 0) != cov).any() or ((fx['n_cells'] >= 0) != cov).any():
        probs.append('outlets: values do not match the covered cells')
    uncovered = int((inmask & ~cov).sum())
    if uncovered != cfg['product_grid']['uncovered_cells_expected']:
        probs.append(f'{uncovered} uncovered mask cells instead of {cfg["product_grid"]["uncovered_cells_expected"]} '
                     '(D08)')
    res['coverage'] = ('failed' if probs else 'passed',
                       {'problems': probs, 'mask_cells': int(inmask.sum()), 'covered': int(cov.sum()),
                        'uncovered': uncovered, 'active_5arcmin_outside_mask': ref['active_outside_mask']})
    # cellarea
    rel_dom = np.abs(fx['cellarea'][cov] / ref['area_sum_km2'][cov] - 1)
    rel_wgs = np.abs(fx['cellarea'][cov] / ref['wgs84_km2'][cov] - 1)
    tol = cfg['static']['cellarea_tolerance']
    st = 'failed' if rel_dom.max() > 1e-6 else ('warning' if rel_wgs.max() > tol else 'passed')
    res['cellarea'] = (st, {'max_rel_diff_domain_sum': float(rel_dom.max()),
                            'max_rel_diff_wgs84': float(rel_wgs.max()),
                            'median_rel_diff_wgs84': float(np.median(rel_wgs)), 'tolerance_wgs84': tol,
                            'total_km2': float(fx['cellarea'][cov].sum())})
    # contfrac, landfrac
    cf = fx['contfrac'][cov]
    total = float(np.nansum(fx['contfrac'] * fx['cellarea']))
    rel_total = abs(total / ref['counted_area_km2'] - 1)
    probs = []
    if (cf <= 0).any() or (cf > 1 + 1e-6).any():
        probs.append(f'contfrac outside (0, 1]: min {cf.min()}, max {cf.max()}')
    if not np.array_equal(fx['landfrac'][cov], cf):
        probs.append('landfrac differs from contfrac')
    if rel_total > 1e-5:
        probs.append(f'sum of contfrac x cellarea differs from the counted 5 arcmin area by {rel_total:.2e}')
    res['contfrac'] = ('failed' if probs else 'passed',
                       {'problems': probs, 'continental_area_km2': total,
                        'counted_5arcmin_area_km2': ref['counted_area_km2'], 'rel_diff': rel_total,
                        'cells_contfrac_below_1': int((cf < 1 - 1e-6).sum())})
    # soil layers
    th = fx['layer_thickness'][:, cov]; bt = fx['layer_bottom'][:, cov]
    dev = np.abs(th - ref['layer_thickness'][:, cov])
    probs = []
    if (th <= 0).any():
        probs.append('non-positive layer thickness')
    if dev.max() > 1e-3:
        probs.append(f'layer thickness differs from the block mean by up to {dev.max():.4f} m')
    if np.abs(bt - np.cumsum(th, axis=0)).max() > 1e-3:
        probs.append('layer bottoms are not the sums of the thicknesses')
    res['soil_layers'] = ('failed' if probs else 'passed',
                          {'problems': probs, 'max_abs_diff_m': float(dev.max()),
                           'thickness_m': {f'layer_{k + 1}': {'min': float(th[k].min()), 'median':
                                                              float(np.median(th[k])), 'max': float(th[k].max())}
                                           for k in range(th.shape[0])}})
    # outlets
    probs = []
    r, c = fx['outlet_row'][cov], fx['outlet_col'][cov]
    if (ref['cell_of_5'][r, c] != np.flatnonzero(cov)).any():
        probs.append('outlet cells outside their 0.5 degree cell')
    if not ref['counted5'][r, c].all():
        probs.append('outlet cells that are not active or outside the mask')
    if np.abs(ref['upa'][r, c] - fx['outlet_upstream_area'][cov]).max() > 1e-6 * ref['upa'].max():
        probs.append('outlet upstream area differs from the network')
    if np.abs(fx['outlet_upstream_area'][cov] - ref['block_max_upa'][cov]).max() > 1e-6 * ref['upa'].max():
        probs.append('an outlet does not have the largest upstream area of its block')
    if not np.array_equal(fx['n_cells'][cov], ref['n_counted'][cov]):
        probs.append('n_cells differs from the count of the counted 5 arcmin cells')
    if abs(ref['terminal_upa_km2'] / ref['active_area_km2'] - 1) > 1e-9:
        probs.append('the upstream areas of the network outlets do not add up to the active area')
    res['outlets'] = ('failed' if probs else 'passed',
                      {'problems': probs, 'outlets': int(cov.sum()),
                       'network_outlets': ref['n_terminal'],
                       'terminal_upstream_area_km2': ref['terminal_upa_km2'],
                       'active_area_km2': ref['active_area_km2']})
    return res


def ddm30_compare(fx, cov, ddm_upa, min_area):
    """Table of the cells with a DDM30 upstream area of at least min_area and their outlet upstream areas."""
    sel = cov & np.isfinite(ddm_upa) & (ddm_upa >= min_area)
    ratio = fx['outlet_upstream_area'][sel] / ddm_upa[sel]
    rows, cols = np.nonzero(sel)
    table = pd.DataFrame({'row05': rows, 'col05': cols, 'ddm30_upstream_km2': ddm_upa[sel],
                          'outlet_upstream_km2': fx['outlet_upstream_area'][sel], 'ratio': ratio,
                          'outlet_lat': fx['outlet_lat'][sel], 'outlet_lon': fx['outlet_lon'][sel]})
    stats = {'cells': int(sel.sum()), 'min_area_km2': min_area}
    if sel.any():
        stats.update({'median_ratio': float(np.median(ratio)), 'p10_ratio': float(np.percentile(ratio, 10)),
                      'p90_ratio': float(np.percentile(ratio, 90)),
                      'within_10_percent': float(np.mean(np.abs(ratio - 1) <= 0.1)),
                      'within_30_percent': float(np.mean(np.abs(ratio - 1) <= 0.3))})
    return table, stats


# ------------------------------------------------------------------------------------------------ main
def references(W, cfg, files):
    """Everything check_all needs, recomputed from the inputs with 6 x 6 blocks."""
    inmask05, coords = static_fields.read_mask(W, cfg)
    lat05, lon05 = coords['lat'][0], coords['lon'][0]
    with nc.Dataset(os.path.join(W, files['domain'])) as d:
        lat5 = np.ma.filled(d['lat'][:]).astype('f8'); lon5 = np.ma.filled(d['lon'][:]).astype('f8')
        active = np.ma.filled(d['mask'][:], 0) == 1
        area = np.ma.filled(d['area'][:], 0.0).astype('f8')
        frac = np.ma.filled(d['frac'][:], 0.0).astype('f8')
    with nc.Dataset(os.path.join(W, files['parameters'])) as d:
        depth = np.nan_to_num(np.ma.filled(d['depth'][:], np.nan).astype('f8'))
    with nc.Dataset(os.path.join(W, files['routing'])) as d:
        d.set_auto_mask(False)
        nxt = routing.network(d['downstream'][:], d['downstream_id'][:], active)
    f = int(round(abs(lat05[1] - lat05[0]) / abs(lat5[1] - lat5[0])))
    ny5, nx5 = active.shape
    nb, nxb = ny5 // f, nx5 // f
    lat_b = blocks(lat5[:, None] * np.ones((1, nx5)), nb, nxb, f).mean(axis=(1, 3))[:, 0]
    rows05 = np.rint((lat_b - lat05[0]) / (lat05[1] - lat05[0])).astype('i8')
    if not np.allclose(lon5.reshape(nxb, f).mean(axis=1), lon05):
        raise SystemExit('the 5 arcmin longitudes are not in the order of the product grid')
    inmask5 = np.repeat(np.repeat(inmask05[rows05], f, axis=0), f, axis=1)
    counted = active & inmask5
    w = np.where(counted, area * frac, 0.0)
    wb = blocks(w, nb, nxb, f).sum(axis=(1, 3))
    ref = {'inmask': inmask05}
    ref['covered'] = inmask05 & (place(wb, lat_b, lat05) > 0)
    ref['area_sum_km2'] = place(blocks(area, nb, nxb, f).sum(axis=(1, 3)), lat_b, lat05) / 1e6
    edges = lat05 + 0.5 * (lat05[1] - lat05[0]) * np.array([[-1], [1]])
    band = wgs84_band_area_km2(edges.min(axis=0), edges.max(axis=0), abs(lon05[1] - lon05[0]))
    ref['wgs84_km2'] = band[:, None] * np.ones((1, lon05.size))
    ref['counted_area_km2'] = float(w.sum() / 1e6)
    ref['active_outside_mask'] = int((active & ~inmask5).sum())
    ref['layer_thickness'] = place(blocks(depth * w, nb, nxb, f).sum(axis=(2, 4)) /
                                   np.where(wb > 0, wb, np.nan), lat_b, lat05)
    upa = routing.upstream_area(nxt, np.where(active, area * frac, 0.0) / 1e6, active.ravel()).reshape(ny5, nx5)
    ref['upa'] = upa
    ref['block_max_upa'] = place(blocks(np.where(counted, upa, -1.0), nb, nxb, f).max(axis=(1, 3)), lat_b, lat05)
    ref['n_counted'] = np.nan_to_num(place(blocks(counted.astype('f8'), nb, nxb, f).sum(axis=(1, 3)), lat_b,
                                           lat05), nan=-1).astype('i8')
    cell05 = (rows05[:, None] * lon05.size + np.arange(nxb)[None, :])
    ref['cell_of_5'] = np.repeat(np.repeat(cell05, f, axis=0), f, axis=1)
    ref['counted5'] = counted
    term = active.ravel() & (nxt == np.arange(nxt.size))
    ref['n_terminal'] = int(term.sum())
    ref['terminal_upa_km2'] = float(upa.ravel()[term].sum())
    ref['active_area_km2'] = float(np.where(active, area * frac, 0.0).sum() / 1e6)
    return ref, coords


def ddm30_upstream(W, cfg, coords):
    """DDM30 upstream area (km2) on the rows of the product grid, and the number of steps that left the network."""
    with nc.Dataset(os.path.join(W, cfg['static']['ddm30_flowdir'])) as d:
        fd = d[cfg['static']['ddm30_variable']][:]
        lat = np.ma.filled(d['lat'][:]).astype('f8'); lon = np.ma.filled(d['lon'][:]).astype('f8')
    lat05, lon05 = coords['lat'][0], coords['lon'][0]
    if not np.allclose(lon, lon05):
        raise SystemExit('the DDM30 longitudes differ from the product grid')
    nxt, lost = routing.ddm30_network(fd, lat)
    valid = np.isfinite(np.ma.filled(np.ma.asarray(fd).astype('f8'), np.nan))
    half = abs(lat[1] - lat[0]) / 2
    cell_area = wgs84_band_area_km2(lat - half, lat + half, abs(lon[1] - lon[0]))[:, None] * np.ones((1, lon.size))
    upa = routing.upstream_area(nxt, np.where(valid, cell_area, 0.0).ravel(), valid.ravel()).reshape(valid.shape)
    upa = np.where(valid, upa, np.nan)
    return place(upa[None], lat, lat05)[0], lost


def figures(fx, table, figs):
    os.makedirs(figs, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(fx['contfrac'], vmin=0, vmax=1, cmap='viridis', extent=[-180, 180, -90, 90])
    fig.colorbar(im, ax=ax, label='contfrac'); ax.set_title('contfrac (missing: white)')
    fig.savefig(f'{figs}/contfrac.png', dpi=120, bbox_inches='tight'); plt.close(fig)
    if len(table):
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.loglog(table['ddm30_upstream_km2'], table['outlet_upstream_km2'], '.', ms=2, alpha=0.4)
        lim = [table[['ddm30_upstream_km2', 'outlet_upstream_km2']].min().min(),
               table[['ddm30_upstream_km2', 'outlet_upstream_km2']].max().max()]
        ax.plot(lim, lim, 'k-', lw=0.8)
        ax.set_xlabel('DDM30 upstream area of the 0.5 degree cell (km2)')
        ax.set_ylabel('upstream area of the 5 arcmin outlet (km2)')
        ax.set_title('dis outlets against DDM30 (diagnostic)')
        fig.savefig(f'{figs}/outlets_ddm30.png', dpi=120, bbox_inches='tight'); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--expect-commit')
    a = ap.parse_args()
    W = support.workdir(); cfg = support.config()
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean: checks of accepted files need a clean repository; '
                         'use --scratch <task-id>')
    camp, _, _ = support.campaign(a.campaign)
    pset = camp['campaign_id']
    root = support.output_root(W, a.scratch)
    static_dir = os.path.join(root, 'postprocessed', pset, 'static')
    qc_dir = os.path.join(root, 'qc', 'postprocessed', pset, 'static')
    if not os.path.isdir(static_dir):
        raise SystemExit(f'{static_dir} does not exist')
    files = support.parameter_files(camp, W)
    protocol = support.protocol_variables(camp, W)
    ref, coords = references(W, cfg, files)
    st_files, det_files = check_files(static_dir, cfg, protocol, coords)
    checks = {'files': (st_files, det_files)}
    if st_files == 'failed' and any('missing' in p for p in det_files['problems']):
        checks['contents'] = ('not_checked', {'reason': 'files missing'})
        fx = None
    else:
        fx = read_static(static_dir)
        checks.update(check_all(fx, ref, cfg))
    diag = {}
    os.makedirs(f'{qc_dir}/reports', exist_ok=True)
    if fx is not None:
        ddm_upa, lost = ddm30_upstream(W, cfg, coords)
        table, stats = ddm30_compare(fx, ref['covered'], ddm_upa, cfg['static']['ddm30_min_area_km2'])
        diag = {'ddm30': {**stats, 'steps_leaving_the_network': lost}}
        table.sort_values('ddm30_upstream_km2', ascending=False).to_csv(f'{qc_dir}/reports/outlets_ddm30.csv',
                                                                         index=False, float_format='%.6g')
        figures(fx, table, f'{qc_dir}/figures')
    status = support.combine([s for s, _ in checks.values()])
    sha = {fn: support.sha256(os.path.join(static_dir, fn)) for fn in static_fields.STATIC_FILES
           if os.path.exists(os.path.join(static_dir, fn))}
    summary = {'object': os.path.relpath(static_dir, W), 'status': status,
               'checks': {k: s for k, (s, _) in checks.items()}, 'files_sha256': sha,
               'checked_by': {'script': 'workflow/06_postprocessing/check_static.py', **state},
               'checked_at': support.utcnow()}
    support.write_json(f'{qc_dir}/reports/check.json',
                       {**summary, 'details': {k: d for k, (_, d) in checks.items()}, 'diagnostics': diag})
    support.write_json(f'{qc_dir}/summary.json', summary)
    print(json.dumps({'status': status, 'checks': summary['checks'], 'diagnostics': diag}, indent=1))
    support.exit_with(status)


if __name__ == '__main__':
    main()
