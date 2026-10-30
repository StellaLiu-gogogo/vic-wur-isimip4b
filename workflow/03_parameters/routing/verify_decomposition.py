#!/usr/bin/env python3
"""Independent verification of the FILE decomposition built by build_decomposition.py (task L3).

Checks (each with its own status; the file passes only when all pass):
  vic_variables  `basin` (lat, lon) is an int variable as rout_decomposition.c of VIC 39e21ff5 reads it; lat and lon
                 equal the domain file exactly
  groups         every active cell has a group in 0 .. groups-1 (groups from provenance.yaml), every group has cells,
                 cells outside the domain hold the fill value -1
  routing        every active cell lies in the group of the active cell it drains to (downstream matched against
                 downstream_id; a value that is no active id is an outlet, as in VIC)
  water_use      every source cell of `receiving` in the water-use file lies in the group of its demander
  dams           in each of the three D19 dam files, every serviced cell lies in the group of its dam's cell
  provenance     size and SHA-256 of the file equal provenance.yaml; every input md5 recorded there equals the md5
                 in the parameter manifest and of the file on disk
Reported, not judged: cells per group, and the cells of the largest MPI rank for several rank counts when whole
groups go, largest first, to the rank with the fewest cells (rout_decomp_domain_from_basins).
Writes <qc>/summary.json and <qc>/reports/verify.json, where <qc> is
qc/parameters/<status>/<set>/routing/decomposition/ (or <file-dir>/qc/), and sets qc.status in provenance.yaml
(not with --file-dir).

Usage: verify_decomposition.py [--parameter-set ID] [--parameter-status candidates] [--file-dir DIR] [--processes 8]
       [--expect-commit SHA] [--qc-to-scratch]
"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import yaml

from common import hashing, provenance, qc as qcm, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_decomposition as bdc   # noqa: E402  (file names and git state; every check is computed here)

DAM_FILES = [f'dams/vic_global_5min_dam_parameters_isimip4b_{s}.nc' for s in ('histsoc', '1850soc', '2021soc')]
RANKS_REPORTED = (1, 4, 6, 8, 16, 32)


def raw(ds, name, idx=None):
    v = ds[name]; v.set_auto_maskandscale(False)
    return np.asarray(v[:] if idx is None else v[idx])


def index_of(values, ids):
    """Position in `ids` (unique) of every value, -1 where a value is no id."""
    order = np.argsort(ids); s = ids[order]
    pos = np.minimum(np.searchsorted(s, values), s.size - 1)
    return np.where(s[pos] == values, order[pos], -1)


def largest_rank(group_cells, ntasks):
    """Cells of the largest rank: groups largest first, each to the rank with the fewest cells."""
    load = np.zeros(ntasks, 'i8')
    for c in sorted(group_cells, reverse=True):
        load[int(np.argmin(load))] += c
    return int(load.max())


def check_dams(args):
    """Problems [(file, dam_class, text)] of dams k0..k1-1: serviced cells outside the group of the dam's cell."""
    path, k0, k1, group_path = args
    group2 = np.load(group_path)
    out = []; links = 0
    with nc.Dataset(path) as f:
        ids = raw(f, 'id'); nserv = raw(f, 'Nservice'); id_map = raw(f, 'id_map').ravel().astype('i8')
        cell = index_of(ids[k0:k1].astype('i8'), id_map)
        for k in range(k0, k1):
            if nserv[k] == 0:
                continue
            if cell[k - k0] < 0:
                out.append((os.path.basename(path), k, 'dam id not in id_map')); continue
            g = group2.ravel()[cell[k - k0]]
            s = raw(f, 'service', k).ravel()
            served = np.flatnonzero(s > 0); links += served.size
            bad = int((group2.ravel()[served] != g).sum())
            if bad:
                out.append((os.path.basename(path), k, f'{bad} serviced cells outside group {g}'))
    return out, links


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--file-dir', default=None, help='verify the file in this directory (scratch test)')
    ap.add_argument('--processes', type=int, default=8)
    ap.add_argument('--expect-commit', default=None)
    ap.add_argument('--qc-to-scratch', action='store_true')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = bdc.git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    uncommitted = not a.file_dir and (dirty or a.qc_to_scratch)
    rel_pset = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{rel_pset}'
    fdir = a.file_dir or f'{pset}/routing'
    qc = f'{fdir}/qc' if a.file_dir else f'{W}/qc/{rel_pset}/routing/{bdc.QC_SUBDIR}'
    if uncommitted:
        qc = f'{W}/{bdc.SCRATCH}/verify-uncommitted/qc/{rel_pset}/routing/{bdc.QC_SUBDIR}'
    os.makedirs(f'{qc}/reports', exist_ok=True)
    path = f'{fdir}/{bdc.FILE_NAME}'
    prov = provenance.read(f'{fdir}/provenance.yaml')
    ngroups = int(prov['method']['groups'])
    checks = {}

    with nc.Dataset(f'{pset}/{bdc.DOMAIN}') as d:
        mask = np.asarray(d['mask'][:].filled(0)) == 1; dlat = np.asarray(d['lat'][:]); dlon = np.asarray(d['lon'][:])
    with nc.Dataset(path) as f:
        v = f['basin']
        var_ok = v.dimensions == ('lat', 'lon') and v.dtype.kind == 'i'
        ll_ok = np.array_equal(raw(f, 'lat'), dlat) and np.array_equal(raw(f, 'lon'), dlon)
        group2 = raw(f, 'basin').astype('i8')
        fill = int(v.getncattr('_FillValue')) if '_FillValue' in v.ncattrs() else None
        dims, dtype = list(v.dimensions), str(v.dtype)
    checks['vic_variables'] = {'basin_dims': dims, 'basin_dtype': dtype, 'latlon_equal': ll_ok,
                               'status': 'passed' if var_ok and ll_ok else 'failed'}

    g = group2[mask]
    cells = np.bincount(g[(g >= 0) & (g < ngroups)], minlength=ngroups)
    out_of_range = int(((g < 0) | (g >= ngroups)).sum())
    outside_not_fill = int((group2[~mask] != -1).sum())
    checks['groups'] = {'groups': ngroups, 'fill_value': fill, 'active_cells_out_of_range': out_of_range,
                        'empty_groups': np.flatnonzero(cells == 0).tolist(),
                        'cells_outside_domain_not_fill': outside_not_fill,
                        'largest_group_cells': int(cells.max()), 'smallest_group_cells': int(cells.min()),
                        'cells_per_group': cells.tolist(),
                        'status': 'passed' if out_of_range == outside_not_fill == 0 and fill == -1 and
                        (cells > 0).all() else 'failed'}

    with nc.Dataset(f'{pset}/{bdc.ROUTING}') as r:
        did = raw(r, 'downstream_id')[mask].astype('i8'); dsv = raw(r, 'downstream')[mask].astype('i8')
    nxt = index_of(dsv, did)
    linked = nxt >= 0
    bad_rout = int((g[linked] != g[nxt[linked]]).sum())
    checks['routing'] = {'links': int(linked.sum()), 'across_groups': bad_rout,
                         'status': 'passed' if bad_rout == 0 else 'failed'}

    with nc.Dataset(f'{pset}/{bdc.WATER_USE}') as w:
        rid = raw(w, 'receiving_id')[mask].astype('i8'); rec = raw(w, 'receiving')
    wu_links = 0; bad_wu = 0; not_id = 0
    for k in range(rec.shape[0]):
        v = rec[k][mask].astype('i8'); dem = np.flatnonzero(v > 0)
        src = index_of(v[dem], rid)
        not_id += int((src < 0).sum()); dem, src = dem[src >= 0], src[src >= 0]
        wu_links += dem.size; bad_wu += int((g[dem] != g[src]).sum())
    del rec
    checks['water_use'] = {'links': wu_links, 'values_without_active_id': not_id, 'across_groups': bad_wu,
                           'status': 'passed' if bad_wu == 0 else 'failed'}

    group_path = os.path.join(os.environ.get('TMPDIR', '/tmp'), f'verify_decomposition_{os.getpid()}.npy')
    np.save(group_path, np.where(mask, group2, -2))
    tasks = []
    for rel in DAM_FILES:
        with nc.Dataset(f'{pset}/{rel}') as f:
            n = len(f.dimensions['dam_class'])
        tasks += [(f'{pset}/{rel}', k, min(k + 100, n), group_path) for k in range(0, n, 100)]
    try:
        with ProcessPoolExecutor(a.processes, mp_context=get_context('spawn')) as ex:
            res = list(ex.map(check_dams, tasks))
    finally:
        os.remove(group_path)
    dam_problems = [p for r in res for p in r[0]]
    links_per_file = {}
    for t, r in zip(tasks, res):
        links_per_file[os.path.basename(t[0])] = links_per_file.get(os.path.basename(t[0]), 0) + r[1]
    checks['dams'] = {'files': DAM_FILES, 'service_links': links_per_file, 'problems': dam_problems[:50],
                      'n_problems': len(dam_problems), 'status': 'passed' if not dam_problems else 'failed'}

    pm = yaml.safe_load(open(f'{bdc.REPO}/manifests/parameters/{a.parameter_set}.yaml'))
    recorded = {f'{rel_pset}/{f["path"]}': f.get('md5') for c in pm['components'].values() for f in c.get('files', [])}
    f0 = prov['files'][0]
    file_ok = f0['path'] == bdc.FILE_NAME and f0['size_bytes'] == os.path.getsize(path) and \
        f0['sha256'] == hashing.sha256(path)
    inputs_bad = [rel for rel, e in prov['inputs'].items()
                  if e['md5'] != recorded.get(rel) or hashing.md5(f'{W}/{rel}') != e['md5']]
    checks['provenance'] = {'file_matches': file_ok, 'inputs_differing': inputs_bad,
                            'status': 'passed' if file_ok and not inputs_bad else 'failed'}

    ranks = {t: {'largest_rank_cells': largest_rank(cells.tolist(), t), 'balanced_cells': int(np.ceil(mask.sum() / t))}
             for t in RANKS_REPORTED if t <= ngroups}
    status = qcm.combine([c['status'] for c in checks.values()])
    report = {'object': os.path.relpath(path, W), 'checked_at': provenance.utcnow(), 'status': status,
              'checked_by': 'workflow/03_parameters/routing/verify_decomposition.py', 'code_commit': commit,
              'code_dirty': dirty, 'checks': checks, 'ranks': ranks}
    qcm.write_json(f'{qc}/reports/verify.json', json.loads(json.dumps(report, default=str)))
    qcm.write_summary(qc, {k: report[k] for k in ('object', 'checked_at', 'status', 'checked_by')} |
                      {'checks': {k: v['status'] for k, v in checks.items()}} |
                      ({'note': 'verifier code not committed (repository not clean): results kept in scratch, the '
                                'status of the object is unchanged'} if uncommitted else {}))
    if not a.file_dir and not uncommitted:
        provenance.set_qc(f'{fdir}/provenance.yaml', status, os.path.relpath(qc, W))
    print(json.dumps({k: v['status'] for k, v in checks.items()}), status)
    qcm.exit_with(status)


if __name__ == '__main__':
    main()
