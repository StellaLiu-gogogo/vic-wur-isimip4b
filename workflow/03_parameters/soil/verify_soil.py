#!/usr/bin/env python3
"""Independent verification of the soil component written by smooth_calibration_fields.py.

Checks (each with its own status; the component passes only when all pass):
  grid           lat, lon and run_cell bitwise equal to the base bundle; lat, lon equal the domain; run_cell equals
                 the domain mask
  unchanged      every variable except the 7 changed ones (depth, Ds, Dsmax, Ws, c, max_moist, init_moist) is
                 bitwise equal to the base bundle (stored values, dtype, dimensions, fill value); of the 3-layer
                 variables depth, max_moist and init_moist the layers 1 and 3 are bitwise equal; the 7 changed
                 variables are bitwise equal to the base outside the domain mask; no variable of the file comes from
                 anywhere else and none of the base's natural variables is missing
  blocks         the block values recovered here from the base bundle (own loop over the blocks of the edge rule:
                 even latitudes, even longitudes east of 0, odd west of 0) equal calibration_blocks.csv exactly
                 (kind, value, number of active cells), and every empty block's donor is a land block at the
                 smallest great-circle distance (recomputed here; equidistant blocks are an allowed choice) whose
                 value it took
  centres        at every land block the four cells around the block centre differ in mean from the block value by at
                 most 5 % of the largest difference between the block and its 8 neighbours (what a bilinear surface
                 can move within one cell of the centre): the block centres keep their values
  local_range    every active cell lies between the smallest and largest of the four block values around it, and
                 within the range of the block values of the field
  staircase      the largest difference between neighbouring active cells (east-west across 180 degrees too,
                 north-south) is at most the largest difference between neighbouring blocks divided by the number
                 of cells between their centres (24 for 2-degree blocks, 18 next to the two 1-degree blocks): the
                 2-degree steps are gone; also reported against the user's number, largest block difference / 24
  global_mean    the area-weighted mean over the active cells changes by at most 2 % per field (GLOBAL_MEAN_TOL)
  dependent      max_moist[2] = depth[2] x (1 - bulk_density / soil_density) x 1000 within 1e-9 relative;
                 init_moist[2] / max_moist[2] equals the base ratio within 1e-9 relative; init_moist[2] <= max_moist[2]
  vic_rules      on the active cells: depth[2] >= 0.001 m and depth[1] <= depth[2]; the NIJSSEN2001 conversion of
                 vic_init.c (VIC 39e21ff5): Ws below the bottom layer's maximum moisture, converted Ds and Ws in
                 [0, 1], converted Dsmax and c > 0 (the assembled bundle is checked again by verify_bundle.py)
Reported only: the distribution of the area-weighted block means of the smoothed fields against the block values
(bilinear interpolation does not conserve block means: an isolated block pulls towards its neighbours), and the
share of the variance within 0.5-degree blocks before and after.
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{<field>_<region>.png, depth2_global.png}, where
<qc> is qc/parameters/<status>/<set>/soil/ (or <component-dir>/qc/ with --component-dir), and sets qc.status in the
component's provenance.yaml (not with --component-dir). Exit status: 0 passed, 1 failed (common/qc.py).

Usage: verify_soil.py [--parameter-set ID] [--parameter-status candidates] [--component-dir DIR]
"""
import argparse, csv, json, os, sys, warnings

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common import gitstate, provenance, qc, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import smooth_calibration_fields as sm   # noqa: E402  (names, constants and the block geometry; checks computed here)

GLOBAL_MEAN_TOL = 0.02
CENTRE_TOL = 0.05
DEPENDENT_TOL = 1e-9
MINSOILDEPTH = 0.001          # m, vic_run/include/vic_def.h
REGIONS = {'west_siberia': (58, 66, 78, 90), 'alps': (42, 50, 2, 14)}   # lat0, lat1, lon0, lon1
MAPPED = ('depth', 'Ds')


def raw(ds, name):
    v = ds[name]; v.set_auto_maskandscale(False)
    return np.asarray(v[:])


def same_bits(a, b):
    a = np.ascontiguousarray(a); b = np.ascontiguousarray(b)
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def fill_of(var):
    return var.getncattr('_FillValue') if '_FillValue' in var.ncattrs() else None


def active_values(ds, name, mask):
    """Values of a 2-d variable, or of its layers, on every cell as f8 with the fill as NaN."""
    x = raw(ds, name).astype('f8'); f = fill_of(ds[name])
    if f is not None and not np.isnan(f):
        x = np.where(x == f, np.nan, x)
    return x


def blocks_by_loop(x, mask, lat_edges, lon_edges, lat, lon):
    """Block values by an explicit loop over the blocks (independent of the producer's histogram): value, kind,
    n_active per block."""
    nbi, nbj = len(lat_edges) - 1, len(lon_edges) - 1
    values = np.full((nbi, nbj), np.nan); kind = np.zeros((nbi, nbj), np.int8); n_act = np.zeros((nbi, nbj), int)
    rows = [np.flatnonzero((lat >= lat_edges[i]) & (lat < lat_edges[i + 1])) for i in range(nbi)]
    cols = [np.flatnonzero((lon >= lon_edges[j]) & (lon < lon_edges[j + 1])) for j in range(nbj)]
    for i in range(nbi):
        for j in range(nbj):
            sub = x[np.ix_(rows[i], cols[j])]; m = mask[np.ix_(rows[i], cols[j])] & np.isfinite(sub)
            n = int(m.sum()); n_act[i, j] = n
            if n == 0:
                continue
            u, cnt = np.unique(sub[m], return_counts=True)
            values[i, j] = u[np.flatnonzero(cnt == cnt.max())[0]]
            kind[i, j] = 1 if len(u) == 1 else 2
    return values, kind, n_act


def cos_distance(lat1, lon1, lat2, lon2):
    """Cosine of the great-circle distance between points (degrees); larger is nearer."""
    la1, lo1, la2, lo2 = (np.deg2rad(x) for x in (lat1, lon1, lat2, lon2))
    return np.sin(la1) * np.sin(la2) + np.cos(la1) * np.cos(la2) * np.cos(lo1 - lo2)


def nearest_land_cos(values, clat, clon):
    """For every empty block the cosine of the distance to the nearest land block (NaN for land blocks)."""
    land = np.isfinite(values)
    li, lj = np.nonzero(land); ei, ej = np.nonzero(~land)
    best = np.empty(len(ei))
    for s in range(0, len(ei), 500):
        e = slice(s, s + 500)
        best[e] = cos_distance(clat[ei[e]][:, None], clon[ej[e]][:, None], clat[li][None, :], clon[lj][None, :]).max(axis=1)
    out = np.full(values.shape, np.nan); out[ei, ej] = best
    return out


def neighbour_max_diff(filled):
    """Largest absolute difference of every block to its 8 neighbours (periodic in longitude, edge rows to the
    neighbours that exist)."""
    p = np.pad(filled, ((1, 1), (0, 0)), mode='edge')
    p = np.concatenate((p[:, -1:], p, p[:, :1]), axis=1)
    out = np.zeros(filled.shape)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di or dj:
                out = np.maximum(out, np.abs(p[1 + di:1 + di + filled.shape[0], 1 + dj:1 + dj + filled.shape[1]] - filled))
    return out


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
    base = nc.Dataset(f'{W}/{prov["inputs"]["base_bundle"]}'); out = nc.Dataset(f'{comp}/{sm.OUT_NAME}')
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
         'active_cells': int(mask.sum())}
    checks['grid'] = {**g, 'status': 'passed' if all(v for k, v in g.items() if k != 'active_cells') else 'failed'}

    # ---- unchanged variables
    out_vars = [v for v in out.variables if v not in ('lat', 'lon')]
    differ = []; foreign = [v for v in out_vars if v not in natural]; missing = [v for v in natural if v not in out.variables]
    layer_diff = {}; inactive_diff = {}
    for v in natural:
        if v not in out.variables:
            continue
        o, b = out[v], base[v]
        fo, fb = fill_of(o), fill_of(b)
        same_fill = (fo is None and fb is None) or (fo is not None and fb is not None and
                                                   (fo == fb or (np.isnan(float(fo)) and np.isnan(float(fb)))))
        meta_ok = o.dtype == b.dtype and o.dimensions == b.dimensions and o.shape == b.shape and same_fill
        if v not in sm.CHANGED:
            if not meta_ok or not same_bits(raw(out, v), raw(base, v)):
                differ.append(v)
            continue
        xo, xb = raw(out, v), raw(base, v)
        if not meta_ok:
            differ.append(v); continue
        bits = f'u{xo.dtype.itemsize}'            # bitwise comparison per cell (NaN equals NaN)
        if xo.ndim == 3:
            layer_diff[v] = [int(not same_bits(xo[k], xb[k])) for k in range(xo.shape[0]) if k != sm.LAYER]
            inactive_diff[v] = int((xo[sm.LAYER][~mask].view(bits) != xb[sm.LAYER][~mask].view(bits)).sum())
        else:
            inactive_diff[v] = int((xo[~mask].view(bits) != xb[~mask].view(bits)).sum())
    u = {'variables': len(natural), 'differ': differ, 'foreign': foreign, 'missing': missing,
         'other_layers_differ': layer_diff, 'inactive_cells_differ': inactive_diff}
    u['status'] = 'passed' if not (differ or foreign or missing or any(any(x) for x in layer_diff.values())
                                   or any(inactive_diff.values())) else 'failed'
    checks['unchanged'] = u

    # ---- block values, fill, centres, range, staircase, global mean, block means (per field)
    lat_edges, lon_edges = sm.block_edges(lat, lon)
    clat, clon = sm.centres(lat_edges), sm.centres(lon_edges)
    nbi, nbj = len(clat), len(clon)
    csv_rows = {f: {} for f in sm.FIELDS}
    with open(f'{comp}/{sm.BLOCKS_CSV}') as fh:
        for r in csv.DictReader(fh):
            csv_rows[r['field']][(int(r['block_row']), int(r['block_col']))] = r
    bi = sm.block_index(lat_edges, lat); bj = sm.block_index(lon_edges, lon)
    i0, i1, wi, j0, j1, wj = sm.interpolation_indices(clat, clon, lat, lon)
    seg_lon = np.round((np.diff(np.concatenate((clon, [clon[0] + 360.0]))) * 12)).astype(int)   # cells between centres
    seg_lat = np.round(np.diff(clat) * 12).astype(int)
    blk = {}; cen = {}; rng = {}; stair = {}; gmean = {}; bmeans = {}; vshare = {}; fields_new = {}; fields_base = {}
    ok_blk = ok_cen = ok_rng = ok_stair = ok_gmean = True
    for name in sm.FIELDS:
        xb = active_values(base, name, mask); xo = active_values(out, name, mask)
        if name == 'depth':
            xb, xo = xb[sm.LAYER], xo[sm.LAYER]
        fields_new[name] = xo; fields_base[name] = xb
        values, kind, n_act = blocks_by_loop(xb, mask, lat_edges, lon_edges, lat, lon)
        best = nearest_land_cos(values, clat, clon)
        # against the producer's record; the filled grid of the record (checked) is the one the other checks use
        filled = values.copy()
        bad = {'rows_missing': 0, 'kind': 0, 'value': 0, 'n_active': 0, 'donor': 0, 'filled_value': 0}
        for i in range(nbi):
            for j in range(nbj):
                r = csv_rows[name].get((i, j))
                if r is None:
                    bad['rows_missing'] += 1; continue
                k = int(kind[i, j])
                bad['kind'] += r['kind'] != sm.KINDS[k]
                bad['n_active'] += int(r['n_active']) != int(n_act[i, j])
                if k > 0:
                    bad['value'] += float(r['value']) != float(values[i, j])
                    bad['filled_value'] += float(r['filled_value']) != float(values[i, j])
                else:
                    di, dj = int(r['donor_row']), int(r['donor_col'])
                    donor_ok = kind[di, dj] > 0 and cos_distance(clat[i], clon[j], clat[di], clon[dj]) >= best[i, j] - 1e-12
                    bad['donor'] += not donor_ok
                    bad['filled_value'] += float(r['filled_value']) != float(values[di, dj])
                    filled[i, j] = float(r['filled_value'])
        blk[name] = {'empty': int((kind == 0).sum()), 'uniform': int((kind == 1).sum()), 'mixed': int((kind == 2).sum()),
                     'csv_rows': len(csv_rows[name]), 'differences_from_csv': bad}
        ok_blk &= not any(bad.values()) and len(csv_rows[name]) == nbi * nbj
        # centres: the 2 x 2 cells around every land block centre
        dmax = neighbour_max_diff(filled)
        ci1 = np.searchsorted(lat, clat); ci0 = ci1 - 1; cj1 = np.searchsorted(lon, clon); cj0 = cj1 - 1
        ci0 = np.clip(ci0, 0, len(lat) - 1); ci1 = np.clip(ci1, 0, len(lat) - 1)
        cj0 = cj0 % len(lon); cj1 = cj1 % len(lon)
        land = kind > 0
        cvals = np.stack([xo[np.ix_(ci0, cj0)], xo[np.ix_(ci0, cj1)], xo[np.ix_(ci1, cj0)], xo[np.ix_(ci1, cj1)]])
        with np.errstate(invalid='ignore'), warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)       # a centre whose four cells are all inactive
            cmean = np.nanmean(cvals, axis=0)
        have = land & np.isfinite(cmean)              # a land block whose centre cells are all inactive is not testable
        dev = np.abs(cmean - values)
        n_bad_c = int((have & (dev > CENTRE_TOL * dmax + 1e-12)).sum())
        cen[name] = {'land_blocks': int(land.sum()), 'blocks_with_active_centre_cells': int(have.sum()),
                     'max_deviation': float(np.nanmax(np.where(have, dev, np.nan))) if have.any() else 0.0,
                     'blocks_beyond_tolerance': n_bad_c}
        ok_cen &= n_bad_c == 0
        # local and global range
        four = np.stack([filled[np.ix_(i0, j0)], filled[np.ix_(i0, j1)], filled[np.ix_(i1, j0)], filled[np.ix_(i1, j1)]])
        lo, hi = four.min(axis=0), four.max(axis=0)
        below = int((mask & (xo < lo - 1e-12)).sum()); above = int((mask & (xo > hi + 1e-12)).sum())
        vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
        rng[name] = {'block_value_range': [vmin, vmax], 'cell_range': [float(np.nanmin(xo[mask])), float(np.nanmax(xo[mask]))],
                     'cells_below_local_min': below, 'cells_above_local_max': above,
                     'cells_outside_block_range': int((mask & ((xo < vmin - 1e-12) | (xo > vmax + 1e-12))).sum())}
        ok_rng &= below == above == rng[name]['cells_outside_block_range'] == 0
        # staircase
        ew = np.abs(xo - np.roll(xo, -1, axis=1)); ns = np.abs(xo[:-1] - xo[1:])
        ew_ok = mask & np.roll(mask, -1, axis=1); ns_ok = mask[:-1] & mask[1:]
        max_jump = max(float(np.nanmax(np.where(ew_ok, ew, np.nan))) if ew_ok.any() else 0.0,
                       float(np.nanmax(np.where(ns_ok, ns, np.nan))) if ns_ok.any() else 0.0)
        dlon_blk = np.abs(np.roll(filled, -1, axis=1) - filled)          # (nbi, nbj), segment j -> j+1 (periodic)
        dlat_blk = np.abs(filled[1:] - filled[:-1])
        bound = max(float((dlon_blk / seg_lon[None, :]).max()), float((dlat_blk / seg_lat[:, None]).max()))
        max_block_diff = max(float(dlon_blk.max()), float(dlat_blk.max()))
        ew_base = np.abs(xb - np.roll(xb, -1, axis=1)); ns_base = np.abs(xb[:-1] - xb[1:])
        stair[name] = {'max_cell_jump_new': max_jump, 'bound_block_difference_over_cells_between_centres': bound,
                       'max_block_difference_over_24': max_block_diff / 24.0,
                       'max_cell_jump_base': max(float(np.nanmax(np.where(ew_ok, ew_base, np.nan))),
                                                 float(np.nanmax(np.where(ns_ok, ns_base, np.nan))))}
        ok_stair &= max_jump <= bound + 1e-9
        # global mean
        mb, mo = sm.area_mean(xb, mask, area), sm.area_mean(xo, mask, area)
        gmean[name] = {'area_mean_base': mb, 'area_mean_new': mo, 'relative_change': mo / mb - 1}
        ok_gmean &= abs(mo / mb - 1) <= GLOBAL_MEAN_TOL
        # report only: block means, variance share
        w = np.where(mask, area, 0.0); flat = (bi[:, None] * nbj + bj[None, :]).ravel()
        s = np.bincount(flat, weights=(np.where(mask, xo, 0.0) * w).ravel(), minlength=nbi * nbj)
        aw = np.bincount(flat, weights=w.ravel(), minlength=nbi * nbj)
        bm = np.where(aw > 0, s / np.where(aw > 0, aw, 1), np.nan).reshape(nbi, nbj)
        with np.errstate(invalid='ignore', divide='ignore'):
            rel = np.abs(bm - values) / np.abs(values)
        rl = rel[land & np.isfinite(rel)]
        bmeans[name] = {'land_blocks': int(land.sum()),
                        'abs_relative_deviation_quantiles': {str(q): float(np.percentile(rl, q)) for q in (50, 90, 99, 100)},
                        'blocks_within': {f'{int(t * 100)}%': int((rl <= t).sum()) for t in (0.01, 0.05, 0.10)}}
        vshare[name] = {'base': variance_share(xb, mask), 'new': variance_share(xo, mask)}
        print(f'{name}: blocks ok {not any(bad.values())}, centres beyond {n_bad_c}, range {below}/{above}, '
              f'jump {max_jump:.4g} <= {bound:.4g}, mean {mo / mb - 1:+.3%}', flush=True)
    checks['blocks'] = {'by_field': blk, 'status': 'passed' if ok_blk else 'failed'}
    checks['centres'] = {'tolerance': f'{CENTRE_TOL} x largest difference to the 8 neighbouring blocks', 'by_field': cen,
                         'status': 'passed' if ok_cen else 'failed'}
    checks['local_range'] = {'by_field': rng, 'status': 'passed' if ok_rng else 'failed'}
    checks['staircase'] = {'by_field': stair, 'status': 'passed' if ok_stair else 'failed'}
    checks['global_mean'] = {'tolerance': GLOBAL_MEAN_TOL, 'by_field': gmean, 'status': 'passed' if ok_gmean else 'failed'}
    checks['block_means'] = {'note': 'report only: bilinear interpolation does not conserve block means', 'by_field': bmeans,
                             'status': 'passed'}
    checks['variance_share_within_0p5_deg'] = {'note': 'report only', 'by_field': vshare, 'status': 'passed'}

    # ---- dependent variables of layer 2
    L = sm.LAYER
    bd = active_values(out, 'bulk_density', mask)[L]; sd = active_values(out, 'soil_density', mask)[L]
    mm_o = active_values(out, 'max_moist', mask)[L]; im_o = active_values(out, 'init_moist', mask)[L]
    mm_b = active_values(base, 'max_moist', mask)[L]; im_b = active_values(base, 'init_moist', mask)[L]
    with np.errstate(invalid='ignore', divide='ignore'):
        expect = fields_new['depth'] * (1 - bd / sd) * 1000.0
        rel_mm = np.abs(mm_o / expect - 1)[mask]
        rel_ratio = np.abs((im_o / mm_o) / (im_b / mm_b) - 1)[mask]
    dep = {'max_moist_max_relative_deviation': float(np.nanmax(rel_mm)), 'max_moist_nan': int(np.isnan(mm_o[mask]).sum()),
           'init_ratio_max_relative_deviation': float(np.nanmax(rel_ratio)), 'init_moist_nan': int(np.isnan(im_o[mask]).sum()),
           'init_above_max': int((im_o[mask] > mm_o[mask]).sum())}
    dep['status'] = 'passed' if dep['max_moist_max_relative_deviation'] <= DEPENDENT_TOL and dep['max_moist_nan'] == 0 \
        and dep['init_ratio_max_relative_deviation'] <= DEPENDENT_TOL and dep['init_moist_nan'] == 0 and dep['init_above_max'] == 0 \
        else 'failed'
    checks['dependent'] = dep

    # ---- VIC rules touched by the change (vic_init.c, BASEFLOW NIJSSEN2001)
    depth = active_values(out, 'depth', mask); mm3 = active_values(out, 'max_moist', mask)[2]
    por3 = 1 - active_values(out, 'bulk_density', mask)[2] / active_values(out, 'soil_density', mask)[2]
    mm_bottom = depth[2] * por3 * 1000.0
    Ds, Dsmax, Ws, c = (fields_new[k] for k in ('Ds', 'Dsmax', 'Ws', 'c'))
    with np.errstate(invalid='ignore', divide='ignore'):
        dsmax_c = Dsmax * (mm_bottom - Ws) ** c + Ds * mm_bottom
        ds_c = Ds * Ws / dsmax_c; ws_c = Ws / mm_bottom
    m = mask
    vr = {'depth2_below_min': int((depth[1][m] < MINSOILDEPTH).sum()), 'depth1_thicker_than_depth2': int((depth[0][m] > depth[1][m]).sum()),
          'Ws_not_below_bottom_max_moist': int((~(Ws[m] < mm_bottom[m])).sum()),
          'converted_Ds_outside_0_1': int((~((ds_c[m] >= 0) & (ds_c[m] <= 1))).sum()),
          'converted_Ws_outside_0_1': int((~((ws_c[m] >= 0) & (ws_c[m] <= 1))).sum()),
          'converted_Dsmax_not_positive': int((~(dsmax_c[m] > 0)).sum()), 'c_not_positive': int((~(c[m] > 0)).sum()),
          'bottom_max_moist_equals_stored': bool(np.allclose(mm_bottom[m], mm3[m], rtol=1e-6))}
    vr['status'] = 'passed' if all(v == 0 for k, v in vr.items() if k != 'bottom_max_moist_equals_stored') else 'failed'
    checks['vic_rules'] = vr

    # ---- figures
    for name in MAPPED:
        for rname, (la0, la1, lo0, lo1) in REGIONS.items():
            r = np.flatnonzero((lat >= la0) & (lat <= la1)); cc = np.flatnonzero((lon >= lo0) & (lon <= lo1))
            fig, axs = plt.subplots(1, 2, figsize=(14, 5), dpi=110)
            vmin = np.nanmin(fields_base[name][np.ix_(r, cc)]); vmax = np.nanmax(fields_base[name][np.ix_(r, cc)])
            for ax, (lab, x) in zip(axs, (('base', fields_base[name]), ('smoothed', fields_new[name]))):
                im = ax.imshow(x[np.ix_(r, cc)][::-1], extent=(lon[cc].min(), lon[cc].max(), lat[r].min(), lat[r].max()),
                               cmap='viridis', vmin=vmin, vmax=vmax, aspect='auto', interpolation='nearest')
                for gl in np.arange(np.ceil(lo0 / 2) * 2, lo1 + 0.1, 2):
                    ax.axvline(gl, color='w', lw=0.4)
                for gl in np.arange(np.ceil(la0 / 2) * 2, la1 + 0.1, 2):
                    ax.axhline(gl, color='w', lw=0.4)
                ax.set_title(f'{name}{"[2]" if name == "depth" else ""} {lab} ({rname})'); fig.colorbar(im, ax=ax, shrink=0.8)
            fig.tight_layout(); fig.savefig(f'{qc_dir}/figures/{name}_{rname}.png'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(14, 6), dpi=110)
    im = ax.imshow(fields_new['depth'][::-1], extent=(lon.min(), lon.max(), lat.min(), lat.max()), cmap='viridis',
                   aspect='auto', interpolation='nearest')
    fig.colorbar(im, ax=ax, shrink=0.8, label='m'); ax.set_title('depth of layer 2, smoothed')
    fig.tight_layout(); fig.savefig(f'{qc_dir}/figures/depth2_global.png'); plt.close(fig)
    out.close(); base.close()

    status = qc.combine(c['status'] for c in checks.values())
    now = provenance.utcnow()
    qc.write_json(f'{qc_dir}/reports/verify.json', {'object': rel_obj, 'checked_at': now, 'status': status,
                                                    'checked_by': 'workflow/03_parameters/soil/verify_soil.py',
                                                    'code_commit': commit, 'code_dirty': dirty, 'checks': checks})
    summary = {'object': rel_obj if not a.component_dir else os.path.relpath(comp, W), 'status': status,
               'checked_by': 'workflow/03_parameters/soil/verify_soil.py', 'updated_at': now,
               'checks': {n: c['status'] for n, c in checks.items()}}
    if uncommitted:
        summary['note'] = 'verifier code not committed (repository not clean): results kept in scratch, the status of the object is unchanged'
    qc.write_summary(qc_dir, summary)
    if not a.component_dir and not uncommitted:
        provenance.set_qc(f'{comp}/provenance.yaml', status, f'qc/{rel_obj}')
    print(json.dumps(summary, indent=1))
    qc.exit_with(status)


def variance_share(x, mask, n=6):
    """Share of the variance of the active cells that lies within 0.5-degree blocks (n x n cells)."""
    ny, nx = x.shape
    b = x[:ny // n * n, :nx // n * n].reshape(ny // n, n, nx // n, n)
    m = mask[:ny // n * n, :nx // n * n].reshape(ny // n, n, nx // n, n)
    xv = np.where(m, b, np.nan)
    with np.errstate(all='ignore'), warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        bm = np.nanmean(xv, axis=(1, 3)); within = np.nanmean((xv - bm[:, None, :, None]) ** 2)
    tot = np.nanvar(x[mask])
    return float(within / tot) if tot > 0 else None


if __name__ == '__main__':
    main()
