#!/usr/bin/env python3
"""Static files of a product set: the 0.5-degree fields the products are made with (D07 parts 2 and 3, D08).

Writes postprocessed/<product-set-id>/static/ (product-set ID = campaign ID, D11), or the same path below
scratch/<task>/ with --scratch:

  cellarea.nc       ISIMIP cellarea (km2): sum of the domain areas (WGS84) of the 36 5' cells of the 0.5-degree cell
  contfrac.nc       ISIMIP contfrac (1): area x frac of the active 5' cells inside the mask cell / cellarea
  landfrac.nc       ISIMIP landfrac (1): equal to contfrac (no inland water bodies, LAKES FALSE)
  soil-layers.nc    thickness and bottom depth (m) of the three VIC soil layers: the weighted mean of the 5' values
  dis-outlets.nc    the 5' outlet cell of every 0.5-degree cell: the active 5' cell inside it with the largest upstream
                    area along the routing network (ties: the smallest 5' flat index), its indices, coordinates,
                    upstream area (km2), and the number of active 5' cells of the 0.5-degree cell

Only active 5' cells inside a cell of the ISIMIP water_global mask count (D08); every field is the fill value on the
mask cells without an active 5' cell and outside the mask. Weights are domain area x frac. The upstream area is
accumulated over every active 5' cell, also those outside the mask, since their water reaches the rivers.

The files are written into .writing-static/ beside static/ and renamed when all are complete; an existing static/ is
never overwritten. Outside --scratch the repository must be clean (contract rule 14), and with --expect-commit it must
still be at the submitted commit.

Usage: static_fields.py --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import json
import os
import sys

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routing   # noqa: E402
import support   # noqa: E402

STATIC_FILES = ('cellarea.nc', 'contfrac.nc', 'landfrac.nc', 'soil-layers.nc', 'dis-outlets.nc')


# ------------------------------------------------------------------------------------------------ grids
def block_index(fine, coarse):
    """Index of the coarse cell that holds each fine coordinate (one axis). Stops unless every coarse cell that is
    touched holds the same number of consecutive fine cells (an exact subdivision). Returns (index, factor)."""
    fine = np.asarray(fine, 'f8'); coarse = np.asarray(coarse, 'f8')
    step = coarse[1] - coarse[0]
    pos = (fine - coarse[0]) / step
    idx = np.rint(pos).astype('i8')
    if (np.abs(pos - idx) > 0.49).any() or (idx < 0).any() or (idx >= coarse.size).any():
        raise SystemExit('the 5 arcmin grid is not inside the cells of the 0.5 degree grid')
    counts = np.bincount(idx, minlength=coarse.size)
    used = counts[counts > 0]
    if used.min() != used.max() or (np.diff(idx) * np.sign(np.diff(fine)[0] * step) < 0).any():
        raise SystemExit('the 5 arcmin grid is not an exact subdivision of the 0.5 degree grid')
    return idx, int(used[0])


def cell_index(rows, cols, ncols05):
    """Flat 0.5-degree cell index of every 5' cell (row-major over the 5' grid)."""
    return (rows[:, None] * ncols05 + cols[None, :]).ravel()


def static_fields(cell, n05, inmask05, active, area, frac, depth):
    """The static fields on the flat 0.5-degree grid from flat 5' arrays.
    cell: 0.5-degree index of each 5' cell; inmask05: mask cells (flat); active, area (m2), frac: 5' domain;
    depth: (nlayer, n5) layer thickness (m). Returns a dict of flat arrays (NaN where missing) and the 5' weights."""
    counted = active & inmask05[cell]
    w = np.where(counted, area * frac, 0.0)
    wsum = np.bincount(cell, weights=w, minlength=n05)
    asum = np.bincount(cell, weights=area, minlength=n05)
    covered = inmask05 & (wsum > 0)
    out = {'covered': covered, 'weight_m2': wsum,
           'cellarea': np.where(covered, asum / 1e6, np.nan),
           'contfrac': np.where(covered, wsum / np.where(asum > 0, asum, 1.0), np.nan),
           'n_cells': np.bincount(cell, weights=counted.astype('f8'), minlength=n05).astype('i8')}
    out['landfrac'] = out['contfrac'].copy()
    th = np.full((depth.shape[0], n05), np.nan)
    for k in range(depth.shape[0]):
        s = np.bincount(cell, weights=np.where(counted, depth[k], 0.0) * w, minlength=n05)
        th[k, covered] = s[covered] / wsum[covered]
    out['layer_thickness'] = th
    out['layer_bottom'] = np.cumsum(th, axis=0)
    return out, w, counted


def outlets(cell, n05, counted, upa):
    """Outlet 5' cell (flat index, -1 if none) of every 0.5-degree cell: the counted 5' cell with the largest upstream
    area; ties go to the smallest 5' flat index."""
    cand = np.flatnonzero(counted)
    order = np.lexsort((cand, -upa[cand], cell[cand]))
    c = cand[order]
    first = np.r_[True, cell[c][1:] != cell[c][:-1]]
    out = np.full(n05, -1, 'i8')
    out[cell[c[first]]] = c[first]
    return out


# ------------------------------------------------------------------------------------------------ files
def read_mask(W, cfg):
    g = cfg['product_grid']
    with nc.Dataset(os.path.join(W, g['mask'])) as d:
        m = d[g['mask_variable']][:]
        m = m[0] if m.ndim == 3 else m
        coords = {}
        for name in ('lat', 'lon'):
            v = d[name]
            coords[name] = (np.ma.filled(v[:]).astype('f8'), {a: v.getncattr(a) for a in v.ncattrs()})
    inmask = np.ma.filled(m, 0) == 1
    return inmask, coords


def write_netcdf(path, cfg, coords, variables, global_attrs, nlayer=None):
    """One NetCDF file in the data model and compression of the protocol, one chunk per field (record) and layer.
    variables: {name: (dims, array, dtype, attrs)}; float variables are written with the fill value of the
    configuration as _FillValue and missing_value, integer variables with -1."""
    rules = cfg['file_rules']; fill = cfg['fill_value']
    with nc.Dataset(path, 'w', format=rules['data_model']) as d:
        if nlayer:
            d.createDimension('layer', nlayer)
        for name in ('lat', 'lon'):
            vals, attrs = coords[name]
            d.createDimension(name, vals.size)
            v = d.createVariable(name, 'f8', (name,))
            v.setncatts(attrs); v[:] = vals
        if nlayer:
            v = d.createVariable('layer', 'i4', ('layer',))
            v.setncatts({'long_name': 'VIC soil layer, counted from the surface', 'units': '1', 'axis': 'Z'})
            v[:] = np.arange(1, nlayer + 1)
        for name, (dims, arr, dtype, attrs) in variables.items():
            is_float = np.dtype(dtype).kind == 'f'
            fv = np.array(fill if is_float else -1, dtype)
            chunks = tuple(1 if dd == 'layer' else len(d.dimensions[dd]) for dd in dims)
            v = d.createVariable(name, dtype, dims, zlib=True, complevel=rules['complevel'], chunksizes=chunks,
                                 fill_value=fv)
            v.setncatts({**attrs, 'missing_value': fv})
            a = np.asarray(arr)
            v[:] = np.where(np.isnan(a), fv, a).astype(dtype) if is_float else a.astype(dtype)
        d.setncatts(global_attrs)


def isimip_attrs(protocol, name, cfg):
    p = protocol[name]
    a = {'long_name': support.for_sector(p['long_name']), 'units': support.for_sector(p['units'])}
    comment = cfg['static']['comments'].get(name)
    if comment:
        a['comment'] = comment.strip()
    return a


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scratch', metavar='TASK_ID', help='write below scratch/<task-id>/ (any repository state)')
    ap.add_argument('--expect-commit', help='stop unless the repository is clean at this commit')
    a = ap.parse_args()
    W = support.workdir(); cfg = support.config()
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean: accepted static files need a clean repository (rule 14); '
                         'use --scratch <task-id>')
    for k in ('institution', 'contact'):
        if not cfg['attributes'].get(k):
            raise SystemExit(f'attributes.{k} of products.yaml is not set')
    camp, camp_sha, camp_rel = support.campaign(a.campaign)
    pset = camp['campaign_id']
    root = support.output_root(W, a.scratch)
    set_dir = os.path.join(root, 'postprocessed', pset)
    target, staging = os.path.join(set_dir, 'static'), os.path.join(set_dir, '.writing-static')
    if os.path.exists(target):
        raise SystemExit(f'{target} exists; static files are never overwritten')
    if os.path.exists(staging):
        raise SystemExit(f'{staging} exists (an interrupted job); the user decides on its deletion')
    files = support.parameter_files(camp, W)
    protocol = support.protocol_variables(camp, W)

    inmask05, coords = read_mask(W, cfg)
    ny05, nx05 = inmask05.shape
    with nc.Dataset(os.path.join(W, files['domain'])) as d:
        lat5, lon5 = np.ma.filled(d['lat'][:]).astype('f8'), np.ma.filled(d['lon'][:]).astype('f8')
        active = np.ma.filled(d['mask'][:], 0).ravel() == 1
        area = np.ma.filled(d['area'][:], 0.0).astype('f8').ravel()
        frac = np.ma.filled(d['frac'][:], 0.0).astype('f8').ravel()
    with nc.Dataset(os.path.join(W, files['parameters'])) as d:
        if not (np.allclose(d['lat'][:], lat5) and np.allclose(d['lon'][:], lon5)):
            raise SystemExit('the parameter file and the domain file have different grids')
        depth = np.ma.filled(d['depth'][:], np.nan).astype('f8').reshape(d['depth'].shape[0], -1)
    with nc.Dataset(os.path.join(W, files['routing'])) as d:
        d.set_auto_mask(False)
        if not (np.allclose(d['lat'][:], lat5) and np.allclose(d['lon'][:], lon5)):
            raise SystemExit('the routing file and the domain file have different grids')
        nxt = routing.network(d['downstream'][:], d['downstream_id'][:], active)
    if (area < 0).any() or (active & ~(area > 0)).any():
        raise SystemExit('the domain has active cells without a positive area')
    if (active & ~np.isfinite(depth).all(axis=0)).any():
        raise SystemExit('the parameter file has active cells without layer depths')

    rows, fr = block_index(lat5, coords['lat'][0])
    cols, fc = block_index(lon5, coords['lon'][0])
    if fr != fc:
        raise SystemExit('the 5 arcmin cells are not square subdivisions of the 0.5 degree cells')
    cell = cell_index(rows, cols, nx05)
    n05 = ny05 * nx05
    f, w, counted = static_fields(cell, n05, inmask05.ravel(), active, area, frac, np.nan_to_num(depth))
    upa = routing.upstream_area(nxt, np.where(active, area * frac, 0.0) / 1e6, active)
    out5 = outlets(cell, n05, counted, upa)
    has = out5 >= 0
    r5, c5 = np.divmod(np.where(has, out5, 0), lon5.size)

    inputs = {p: support.sha256(os.path.join(W, p)) for p in
              [cfg['product_grid']['mask'], files['domain'], files['parameters'], files['routing']]}
    common_attrs = {
        'title': f'VIC-WUR ISIMIP4b product set {pset}: static file',
        'institution': cfg['attributes']['institution'], 'contact': cfg['attributes']['contact'],
        'product_set': pset, 'model_commit': camp['model']['commit'], 'parameter_set': camp['parameter_set']['id'],
        'protocol_commit': camp['protocol']['commit'], 'decisions': 'D07, D08, D11',
        'campaign_file': f'{camp_rel} sha256 {camp_sha}', 'inputs_sha256': json.dumps(inputs, sort_keys=True),
        'created_by': 'workflow/06_postprocessing/static_fields.py', 'code_commit': state['commit'],
        'code_branch': state['branch'], 'code_dirty': str(state['dirty']).lower(), 'created_at': support.utcnow()}
    shape = (ny05, nx05)
    os.makedirs(staging)
    for name in cfg['static']['variables']:
        write_netcdf(os.path.join(staging, f'{name}.nc'), cfg, coords,
                     {name: (('lat', 'lon'), f[name].reshape(shape), 'f4', isimip_attrs(protocol, name, cfg))},
                     common_attrs)
    nl = f['layer_thickness'].shape[0]
    write_netcdf(os.path.join(staging, 'soil-layers.nc'), cfg, coords, {
        'layer_thickness': (('layer', 'lat', 'lon'), f['layer_thickness'].reshape(nl, *shape), 'f4',
                            {'long_name': 'thickness of the VIC soil layer, weighted mean of the 5 arcmin cells',
                             'units': 'm'}),
        'layer_bottom': (('layer', 'lat', 'lon'), f['layer_bottom'].reshape(nl, *shape), 'f4',
                         {'long_name': 'depth of the bottom of the VIC soil layer below the surface', 'units': 'm'})},
        common_attrs, nlayer=nl)
    write_netcdf(os.path.join(staging, 'dis-outlets.nc'), cfg, coords, {
        'outlet_row': (('lat', 'lon'), np.where(has, r5, -1).reshape(shape), 'i4',
                       {'long_name': 'row of the outlet cell in the 5 arcmin domain grid (0-based)'}),
        'outlet_col': (('lat', 'lon'), np.where(has, c5, -1).reshape(shape), 'i4',
                       {'long_name': 'column of the outlet cell in the 5 arcmin domain grid (0-based)'}),
        'outlet_lat': (('lat', 'lon'), np.where(has, lat5[r5], np.nan).reshape(shape), 'f8',
                       {'long_name': 'latitude of the outlet cell', 'units': 'degrees_north'}),
        'outlet_lon': (('lat', 'lon'), np.where(has, lon5[c5], np.nan).reshape(shape), 'f8',
                       {'long_name': 'longitude of the outlet cell', 'units': 'degrees_east'}),
        'outlet_upstream_area': (('lat', 'lon'), np.where(has, upa[np.where(has, out5, 0)], np.nan).reshape(shape),
                                 'f8', {'long_name': 'upstream area of the outlet cell along the 5 arcmin routing '
                                                     'network', 'units': 'km2'}),
        'n_cells': (('lat', 'lon'), np.where(f['covered'], f['n_cells'], -1).reshape(shape), 'i4',
                    {'long_name': 'number of active 5 arcmin cells inside the mask cell'})},
        {**common_attrs, 'comment': 'D07 part 2: the dis of a 0.5 degree cell is the 5 arcmin discharge of its '
                                    'outlet cell, the active 5 arcmin cell inside it with the largest upstream area '
                                    '(ties: the smallest 5 arcmin flat index)'})
    os.rename(staging, target)
    print(f'wrote {len(STATIC_FILES)} files to {target}: {int(f["covered"].sum())} covered mask cells, '
          f'{int(inmask05.sum() - f["covered"].sum())} uncovered, {int(has.sum())} outlets')


if __name__ == '__main__':
    main()
