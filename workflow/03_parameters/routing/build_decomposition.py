#!/usr/bin/env python3
"""FILE decomposition of the routing component (DECOMPOSITION_PARAMETERS) that keeps every routing, water-use and
dam service link of the parameter set inside one group (task L3).

VIC 39e21ff5 with DECOMPOSITION FILE reads the int variable `basin` (lat, lon) and gives whole groups to the MPI
ranks, largest first, each to the rank with the fewest cells so far (plugins/routing/src/rout_decomposition.c).
All computations of a cell run on its rank. A dam service cell or a water-use source cell on another rank is
dropped by VIC with a warning only (dams/src/dam_init.c, wateruse/src/wu_init.c). Routing, dams and water use run
cell after cell on each rank (plugin_simulation.c), so the rank with the most cells sets the pace.

Method (version 1.0)
  basins      every active cell belongs to the outlet it drains to (routing downstream_id/downstream, walked by
              verify_routing.walk); an outlet points to itself or to an id that is no active cell, as in VIC
  links       water use: every (demander, source) pair of `receiving` in the water-use file; dams: every (dam cell,
              serviced cell) pair of `service` in the histsoc dam file (the three D19 dam files hold the same
              service maps, verify_dams.py check same_list)
  components  basins joined by a link are one component, without a size limit
  groups      components packed into --groups groups by VIC's own rule: largest first, each to the group with the
              fewest cells (ties: lowest group number); group numbers 0 .. groups-1

Outputs in parameters/<status>/<set>/routing/ (whose adopted files stay): FILE_NAME and provenance.yaml (covering only
this file); build report qc/parameters/<status>/<set>/routing/decomposition/reports/build_report.json. From a
repository that is not clean, or with --scratch, everything goes to scratch/dam-parameters/decomposition/ (qc under
its qc/).

Usage: build_decomposition.py [--parameter-set ID] [--parameter-status candidates] [--groups 128] [--processes 8]
       [--scratch] [--expect-commit SHA]
"""
import argparse, heapq, json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import yaml
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from common import gitstate, hashing, provenance, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'domain'))
sys.path.insert(0, os.path.join(HERE, '..', 'water_use'))
import verify_routing as vr        # noqa: E402  (the walk of the routing network)
import verify_water_use as vw      # noqa: E402  (ids to cells)

CREATED_BY = 'workflow/03_parameters/routing/build_decomposition.py'
METHOD_VERSION = '1.0'
SCRATCH = 'scratch/dam-parameters/decomposition'
QC_SUBDIR = 'decomposition'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
ROUTING = vr.ROUTING
WATER_USE = vw.WATER_USE
DAMS = 'dams/vic_global_5min_dam_parameters_isimip4b_histsoc.nc'
ADOPTED_DECOMPOSITION = 'routing/vic_global_5min_file_decomposition_wateruse_dams.nc'
FILE_NAME = 'vic_global_5min_file_decomposition_wateruse_isimip4b-dams.nc'
INPUTS = (DOMAIN, ROUTING, WATER_USE, DAMS)
GROUPS = 128
RANKS_REPORTED = (1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 32, 64, 128)


def git_state():
    return gitstate.state(REPO)


# ------------------------------------------------------------------------------------------------------- inputs
def manifest_inputs(pset_rel, paths, require_passed):
    """[(workdir path, md5, recorded in)] of `paths` (relative to the set) from the parameter manifest; with
    require_passed, every manifest entry of these files must have qc_status passed."""
    mrel = f'manifests/parameters/{os.path.basename(pset_rel)}.yaml'
    pm = yaml.safe_load(open(f'{REPO}/{mrel}'))
    found = {}
    for key, comp in pm['components'].items():
        for f in comp.get('files', []):
            if f['path'] in paths:
                found[f['path']] = (f.get('md5'), key, comp.get('qc_status'))
    missing = [p for p in paths if p not in found or not found[p][0]]
    if missing:
        raise SystemExit(f'{missing} not recorded with an md5 in {mrel}')
    unchecked = [f'{p} ({found[p][1]}: {found[p][2]})' for p in paths if found[p][2] != 'passed']
    if require_passed and unchecked:
        raise SystemExit(f'inputs without qc_status passed in {mrel}: {unchecked}')
    return [(f'{pset_rel}/{p}', found[p][0], mrel) for p in paths]


def check_md5(W, items):
    for rel, md5, src in items:
        got = hashing.md5(f'{W}/{rel}')
        if got != md5:
            raise SystemExit(f'{rel}: md5 {got} differs from {md5} recorded in {src}')


def raw(ds, name, idx=None):
    v = ds[name]; v.set_auto_maskandscale(False)
    return np.asarray(v[:] if idx is None else v[idx])


# ------------------------------------------------------------------------------------------------------- method
def basins(downstream_id, downstream):
    """Outlet (index into the active cells) of every active cell; stops on a loop."""
    nxt, _ = vr.network(downstream_id, downstream)
    cyclic, outlet, _ = vr.walk(nxt)
    if cyclic.size:
        raise SystemExit(f'the routing has {cyclic.size} cells on loops')
    return outlet


def water_use_links(receiving, receiving_id):
    """(demander, source) indices into the active cells. receiving: (slots, active cells), receiving_id: (active
    cells,). Values that are no id are counted, not linked (VIC drops them)."""
    dem, src = [], []; unresolved = 0
    for k in range(receiving.shape[0]):
        v = receiving[k].astype('i8')
        i = np.flatnonzero(v > 0)
        j = vw.resolve(v[i], receiving_id.astype('i8'))
        unresolved += int((j < 0).sum())
        dem.append(i[j >= 0]); src.append(j[j >= 0])
    return np.concatenate(dem), np.concatenate(src), unresolved


def _dam_slices(args):
    path, k0, k1, mask_path = args
    mask = np.load(mask_path)
    out = []
    with nc.Dataset(path) as f:
        ids = raw(f, 'id'); nserv = raw(f, 'Nservice')
        for k in range(k0, k1):
            if nserv[k] == 0:
                continue
            s = raw(f, 'service', k)[mask]
            out.append((int(ids[k]), np.flatnonzero(s > 0)))
    return out


def dam_links(path, mask, cell_id, processes):
    """(dam cell, serviced cell) indices into the active cells for every dam with a service map; cell_id: routing
    id of the active cells (the dam's `id` is the id of its cell)."""
    with nc.Dataset(path) as f:
        n = len(f.dimensions['dam_class'])
    mask_path = os.path.join(os.environ.get('TMPDIR', '/tmp'), f'decomposition_mask_{os.getpid()}.npy')
    np.save(mask_path, mask)
    step = 100
    tasks = [(path, k, min(k + step, n), mask_path) for k in range(0, n, step)]
    try:
        with ProcessPoolExecutor(processes, mp_context=get_context('spawn')) as ex:
            parts = [r for part in ex.map(_dam_slices, tasks) for r in part]
    finally:
        os.remove(mask_path)
    ids = np.array([p[0] for p in parts], 'i8')
    dam_cell = vw.resolve(ids, cell_id.astype('i8'))
    if (dam_cell < 0).any():
        raise SystemExit(f'{int((dam_cell < 0).sum())} dams whose id is no active cell')
    a = np.concatenate([np.full(p[1].size, c) for p, c in zip(parts, dam_cell)])
    b = np.concatenate([p[1] for p in parts])
    return a, b, len(parts)


def components(outlet, a, b):
    """Component label (0..m-1) of every active cell: cells of one basin are joined to their outlet, and every
    link (a[i], b[i]) joins two cells."""
    n = outlet.size
    rows = np.concatenate([np.arange(n), a]); cols = np.concatenate([outlet, b])
    g = coo_matrix((np.ones(rows.size, np.int8), (rows, cols)), shape=(n, n))
    return connected_components(g, directed=False)[1]


def pack(sizes, ngroups):
    """Group of every component: largest first (ties: lower component number), each to the group with the fewest
    cells (ties: lower group number)."""
    order = np.lexsort((np.arange(sizes.size), -sizes))
    heap = [(0, g) for g in range(ngroups)]
    group = np.empty(sizes.size, np.int32)
    for c in order:
        load, g = heapq.heappop(heap)
        group[c] = g
        heapq.heappush(heap, (load + int(sizes[c]), g))
    return group


def rank_loads(group_sizes, ntasks):
    """Cells per rank when VIC hands out whole groups, largest first, to the rank with the fewest cells."""
    group_sizes = np.asarray(group_sizes)
    return np.bincount(pack(group_sizes, ntasks), weights=group_sizes, minlength=ntasks).astype(int)


def crossing(group, a, b):
    return int((group[a] != group[b]).sum())


# --------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--groups', type=int, default=GROUPS)
    ap.add_argument('--processes', type=int, default=8, help='parallel readers of the dam service maps')
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--expect-commit', default=None)
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    commit, dirty = git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    to_scratch = a.scratch or dirty
    pset_rel = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{pset_rel}'
    out = f'{W}/{SCRATCH}' if to_scratch else f'{pset}/routing'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{pset_rel}/routing/{QC_SUBDIR}'
    prov_path = f'{out}/provenance.yaml'
    if not to_scratch and (os.path.exists(f'{out}/{FILE_NAME}') or os.path.exists(prov_path)):
        raise SystemExit(f'{out}: {FILE_NAME} or provenance.yaml exists; replaced only with the user\'s authorization')
    if to_scratch:
        print(f'{"--scratch" if a.scratch else "repository is not clean"}: writing to {out}', file=sys.stderr)
    os.makedirs(f'{qc}/reports', exist_ok=True)
    md5_items = manifest_inputs(pset_rel, INPUTS, require_passed=not to_scratch)
    md5_items += manifest_inputs(pset_rel, (ADOPTED_DECOMPOSITION,), require_passed=False)
    check_md5(W, md5_items)

    with nc.Dataset(f'{pset}/{DOMAIN}') as d:
        mask = np.asarray(d['mask'][:].filled(0)) == 1
        lat = np.asarray(d['lat'][:], 'f8'); lon = np.asarray(d['lon'][:], 'f8')
    flat = np.flatnonzero(mask); n = flat.size; nx = mask.shape[1]
    with nc.Dataset(f'{pset}/{ROUTING}') as r:
        did = raw(r, 'downstream_id')[mask].astype('i8'); dsv = raw(r, 'downstream')[mask].astype('i8')
    outlet = basins(did, dsv)
    out_ids, basin_cells = np.unique(outlet, return_counts=True)
    with nc.Dataset(f'{pset}/{WATER_USE}') as w:
        rid = raw(w, 'receiving_id')[mask]; rec = raw(w, 'receiving')[:, mask]
    wu_a, wu_b, wu_unresolved = water_use_links(rec, rid); del rec
    print(f'{n} active cells, {out_ids.size} basins, {wu_a.size} water-use links, {time.time() - t0:.0f} s', flush=True)
    dam_a, dam_b, n_dams = dam_links(f'{pset}/{DAMS}', mask, did, a.processes)
    print(f'{dam_a.size} dam service links of {n_dams} dams, {time.time() - t0:.0f} s', flush=True)

    comp = components(outlet, np.concatenate([wu_a, dam_a]), np.concatenate([wu_b, dam_b]))
    comp_cells = np.bincount(comp)
    group_of_comp = pack(comp_cells, a.groups)
    group = group_of_comp[comp]
    group_cells = np.bincount(group, minlength=a.groups)
    lost = {'water_use': crossing(group, wu_a, wu_b), 'dams': crossing(group, dam_a, dam_b),
            'routing': crossing(group, np.arange(n), outlet)}
    if any(lost.values()) or (group_cells == 0).any():
        raise SystemExit(f'links across groups {lost} or empty groups {np.flatnonzero(group_cells == 0).tolist()}')

    # report: the largest component and its largest basins, VIC's ranks, the adopted decomposition with these links
    big = int(comp_cells.argmax())
    big_outlets, big_cells = np.unique(outlet[comp == big], return_counts=True)
    top = np.argsort(-big_cells)[:10]
    rows, cols = np.divmod(flat, nx)
    largest_basins = [{'outlet_lat': float(lat[rows[o]]), 'outlet_lon': float(lon[cols[o]]), 'cells': int(c)}
                      for o, c in zip(big_outlets[top], big_cells[top])]
    ranks = {}
    for t in RANKS_REPORTED:
        if t <= a.groups:
            loads = rank_loads(group_cells, t)
            ranks[t] = {'largest_rank_cells': int(loads.max()), 'balanced_cells': int(np.ceil(n / t)),
                        'speed_bound_vs_one_rank': round(n / float(loads.max()), 2)}
    with nc.Dataset(f'{pset}/{ADOPTED_DECOMPOSITION}') as d:
        old = raw(d, 'basin')[mask]
    report = {
        'method_version': METHOD_VERSION, 'code_commit': commit, 'code_dirty': dirty,
        'active_cells': int(n), 'basins': int(out_ids.size), 'largest_basin_cells': int(basin_cells.max()),
        'links': {'water_use': int(wu_a.size), 'water_use_unresolved_ids': wu_unresolved,
                  'dam_service': int(dam_a.size), 'dams_with_service': n_dams,
                  'water_use_across_basins': crossing(outlet, wu_a, wu_b),
                  'dam_service_across_basins': crossing(outlet, dam_a, dam_b)},
        'components': int(comp_cells.size), 'largest_component_cells': int(comp_cells.max()),
        'largest_component_basins': int(big_outlets.size), 'largest_component_largest_basins': largest_basins,
        'groups': a.groups, 'largest_group_cells': int(group_cells.max()), 'smallest_group_cells': int(group_cells.min()),
        'links_across_groups': lost, 'ranks': ranks,
        'adopted_decomposition_links_across_groups': {'file': ADOPTED_DECOMPOSITION,
                                                      'water_use': crossing(old, wu_a, wu_b),
                                                      'dams': crossing(old, dam_a, dam_b)},
    }

    created_at = provenance.utcnow()
    path = f'{out}/{FILE_NAME}'
    with nc.Dataset(path + '.part', 'w', format='NETCDF4') as o:
        o.createDimension('lat', lat.size); o.createDimension('lon', lon.size)
        v = o.createVariable('lat', 'f8', ('lat',)); v[:] = lat; v.units = 'degrees_north'
        v = o.createVariable('lon', 'f8', ('lon',)); v[:] = lon; v.units = 'degrees_east'
        v = o.createVariable('basin', 'i4', ('lat', 'lon'), fill_value=np.int32(-1), zlib=True, complevel=4)
        g2 = np.full(mask.shape, -1, np.int32); g2[mask] = group; v[:] = g2
        v.units = '1'; v.long_name = 'VIC FILE decomposition group'
        v.description = ('routing basins joined wherever a water-use source link or a dam service link connects them, '
                         'without a size limit, packed into groups largest first; every routing, water-use and dam '
                         'service link lies inside one group')
        o.title = 'VIC-WUR FILE decomposition (DECOMPOSITION_PARAMETERS) keeping the water-use and D19 dam links'
        o.created_by = CREATED_BY; o.code_commit = commit; o.code_dirty = str(dirty).lower()
        o.created_at = created_at; o.method_version = METHOD_VERSION
        o.parameter_set = f'{a.parameter_status}/{a.parameter_set}'
        o.links_from = f'{WATER_USE}, {DAMS}'
        o.setncattr('n_groups', np.int32(a.groups)); o.largest_group_cells = np.int32(group_cells.max())
    os.replace(path + '.part', path)
    report['runtime_s'] = round(time.time() - t0)
    with open(f'{qc}/reports/build_report.json', 'w') as fh:
        json.dump(report, fh, indent=1)
    prov = {'object': os.path.relpath(path, W), 'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': dirty,
            'created_at': created_at, 'method_version': METHOD_VERSION,
            'note': 'covers only the files listed here; the adopted files of this component are recorded in '
                    f'manifests/parameters/{a.parameter_set}.yaml',
            'inputs': {rel: {'md5': md5, 'recorded_in': where} for rel, md5, where in md5_items},
            'method': {'groups': a.groups, 'size_limit': None, 'links': ['routing', 'water_use', 'dam_service']},
            'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --parameter-status '
                               f'{a.parameter_status} --groups {a.groups}' + (' --scratch' if a.scratch else ''),
            'files': [{'path': FILE_NAME, 'size_bytes': os.path.getsize(path), 'sha256': hashing.sha256(path),
                       'md5': hashing.md5(path)}],
            'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(prov_path, prov)
    print(json.dumps({k: report[k] for k in ('largest_component_cells', 'largest_group_cells', 'links_across_groups',
                                             'adopted_decomposition_links_across_groups')}))
    print(f'done in {time.time() - t0:.0f} s -> {path}')


if __name__ == '__main__':
    main()
