#!/usr/bin/env python3
"""Independent verification of the dam component (build_dams.py).

Checks (each with its own status; the component passes only when all pass):
  vic_variables  every file has the variables VIC 39e21ff5 reads (dam_start.c, dam_alloc_free.c, dam_init.c) with
                 their dimensions and types; lat and lon equal the domain file exactly
  same_list      id_map, id, type, capacity, inflow_fraction, Nservice, service and service_fraction are identical
                 in the files of all scenarios; only year differs
  cells          id_map equals the routing downstream_id on active cells and -1 elsewhere; every dam id is the id
                 of an active cell; at most one dam per cell (VIC 39e21ff5 sizes the dam output for one dam per cell)
  service        per dam: the service slice holds the dam id on exactly Nservice active cells and fill elsewhere,
                 the fractions are in (0, 1] there and NaN elsewhere, a traced map contains the dam cell;
                 Nservice = 0 exactly for the SSP future dams and the global dams with purpose rule no_supply
  types          SSP future dams are global; global dams have inflow_fraction 1, local dams in (0, 1)
  years          per scenario the D19 rule against the dam list: histsoc = ISIMIP year (future 9999), 1850soc = 0 for
                 year <= 1850 else 9999, 2021soc = 0 for historical and 9999 for future dams
  review         the capacity and location choices of the flagged pairs follow the review rules applied to the
                 evidence recorded in review_pairs.csv (pairs overridden by the decisions file excepted)
  table          the dam list has one row per dam_class with the id, type, capacity and inflow fraction of the files
  accounting     every ISIMIP histsoc record and every SSP record has an outcome; every historical record is a dam,
                 merged into one, or combined into one (none is lost); the historical capacity of the files equals
                 the ISIMIP input total after the merges, the combinations of the decisions file and the capacities
                 chosen for the flagged pairs (review_pairs.csv)
Writes <qc>/summary.json and <qc>/reports/verify.json, where <qc> is qc/parameters/<status>/<set>/dams/ (or
<component-dir>/qc/), and sets qc.status in the component's provenance.yaml (not with --component-dir).

Usage: verify_dams.py [--parameter-set ID] [--parameter-status candidates] [--component-dir DIR] [--processes 8]
"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import pandas as pd
import yaml

from common import provenance, qc as qcm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_dams as bd   # noqa: E402  (file names and the decisions file; every check is computed here)

VIC_READS = {'id_map': (('lat', 'lon'), 'i'), 'id': (('dam_class',), 'i'), 'type': (('dam_class',), 'i'),
             'year': (('dam_class',), 'i'), 'capacity': (('dam_class',), 'f'),
             'inflow_fraction': (('dam_class',), 'f'), 'Nservice': (('dam_class',), 'i'),
             'service': (('dam_class', 'lat', 'lon'), 'i'), 'service_fraction': (('dam_class', 'lat', 'lon'), 'f')}
SAME = ('id_map', 'id', 'type', 'capacity', 'inflow_fraction', 'Nservice')


def raw(ds, name):
    v = ds[name]; v.set_auto_mask(False)
    return np.asarray(v[:])


def check_slices(args):
    """Service checks of dams k0..k1-1; returns a list of problems (dam_class, text)."""
    paths, k0, k1, mask_path = args
    mask = np.load(mask_path)
    files = [nc.Dataset(p) for p in paths]
    for f in files:
        f.set_auto_mask(False)
    ids, nserv = raw(files[0], 'id'), raw(files[0], 'Nservice')
    id_map = raw(files[0], 'id_map')
    problems = []
    for k in range(k0, k1):
        s = np.asarray(files[0]['service'][k]); fr = np.asarray(files[0]['service_fraction'][k])
        on = s > 0
        if (s[on] != ids[k]).any():
            problems.append((k, 'service holds another id than the dam id'))
        if (s[~on] != -1).any():
            problems.append((k, 'service has values other than fill outside the serviced cells'))
        if int(on.sum()) != int(nserv[k]):
            problems.append((k, f'{int(on.sum())} serviced cells, Nservice {int(nserv[k])}'))
        if (on & ~mask).any():
            problems.append((k, 'serviced cells outside the domain'))
        f_on = fr[on]
        if not (np.isfinite(f_on).all() and (f_on > 0).all() and (f_on <= 1).all()):
            problems.append((k, 'service_fraction not in (0, 1] on serviced cells'))
        if np.isfinite(fr[~on]).any():
            problems.append((k, 'service_fraction set outside the serviced cells'))
        if nserv[k] > 0 and not on[id_map == ids[k]].any():
            problems.append((k, 'the dam cell is not serviced'))
        for f in files[1:]:
            if not np.array_equal(np.asarray(f['service'][k]), s) or \
                    not np.array_equal(np.asarray(f['service_fraction'][k]), fr, equal_nan=True):
                problems.append((k, f'service differs in {os.path.basename(f.filepath())}'))
    for f in files:
        f.close()
    return problems


def expected_historical_capacity(dec, isi_caps, review):
    """ISIMIP input total with the combinations of the decisions file and the capacities chosen for the flagged
    pairs (review_pairs.csv: capacity_used_mcm; a combined record takes the combined capacity)."""
    total = float(sum(isi_caps.values()))
    combined = set()
    for e in dec['combined']:
        keys = [e['keep']] + list(e['absorb'])
        combined |= set(keys)
        total += float(e['capacity_mcm']) - sum(isi_caps[k] for k in keys)
    for k, used in zip(review.isimip.astype(str), review.capacity_used_mcm):
        if k not in combined:
            total += float(used) - isi_caps[k]
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--component-dir', default=None, help='verify the component in this directory (scratch test)')
    ap.add_argument('--processes', type=int, default=8)
    ap.add_argument('--expect-commit', default=None)
    ap.add_argument('--qc-to-scratch', action='store_true')
    a = ap.parse_args(); W = bd.workdir.root()
    commit, dirty = bd.git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    uncommitted = not a.component_dir and (dirty or a.qc_to_scratch)
    rel_pset = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{rel_pset}'
    cdir = a.component_dir or f'{pset}/dams'
    qc = f'{cdir}/qc' if a.component_dir else f'{W}/qc/{rel_pset}/dams'
    if uncommitted:
        qc = f'{W}/{bd.SCRATCH}/verify-uncommitted/qc/{rel_pset}/dams'
    os.makedirs(f'{qc}/reports', exist_ok=True)
    paths = [f'{cdir}/{bd.OUT_NC.format(scenario=s)}' for s in bd.SCENARIOS]
    files = [nc.Dataset(p) for p in paths]
    with nc.Dataset(f'{pset}/{bd.DOMAIN}') as d:
        mask = np.asarray(d['mask'][:].filled(0)) == 1; dlat = np.asarray(d['lat'][:]); dlon = np.asarray(d['lon'][:])
    with nc.Dataset(f'{pset}/{bd.ROUTING}') as r:
        rid = raw(r, 'downstream_id')
    lst = pd.read_csv(f'{cdir}/{bd.DAM_LIST}', keep_default_na=False, na_values=[''])
    src = pd.read_csv(f'{cdir}/{bd.DAM_SOURCES}', keep_default_na=False, na_values=[''], low_memory=False)
    dec = bd.load_decisions()
    checks = {}

    # ---- variables
    bad = {}
    for p, f in zip(paths, files):
        for v, (dims, kind) in VIC_READS.items():
            if v not in f.variables:
                bad.setdefault(os.path.basename(p), []).append(f'{v} missing')
            elif f[v].dimensions != dims or f[v].dtype.kind != kind:
                bad.setdefault(os.path.basename(p), []).append(f'{v} {f[v].dimensions} {f[v].dtype}')
        if not (np.array_equal(raw(f, 'lat'), dlat) and np.array_equal(raw(f, 'lon'), dlon)):
            bad.setdefault(os.path.basename(p), []).append('lat/lon differ from the domain')
    checks['vic_variables'] = {'files': [os.path.basename(p) for p in paths], 'problems': bad,
                               'status': 'passed' if not bad else 'failed'}

    # ---- same list
    differ = [f'{v} in {os.path.basename(p)}' for v in SAME for p, f in zip(paths[1:], files[1:])
              if not np.array_equal(raw(f, v), raw(files[0], v), equal_nan=True)]
    checks['same_list'] = {'compared': list(SAME) + ['service', 'service_fraction (in the service check)'],
                           'differ': differ, 'status': 'passed' if not differ else 'failed'}

    ids, typ, cap, infl, nserv = (raw(files[0], v) for v in ('id', 'type', 'capacity', 'inflow_fraction', 'Nservice'))
    id_map = raw(files[0], 'id_map'); n = len(ids)

    # ---- cells
    idm_ok = bool(np.array_equal(id_map[mask], rid[mask]) and (id_map[~mask] == -1).all())
    active_ids = set(id_map[mask].tolist())
    not_active = int(sum(i not in active_ids for i in ids.tolist()))
    dup = int(n - len(set(ids.tolist())))
    checks['cells'] = {'id_map_equals_routing': idm_ok, 'dams_not_on_active_cell': not_active,
                       'cells_with_more_than_one_dam': dup,
                       'status': 'passed' if idm_ok and not_active == 0 and dup == 0 else 'failed'}

    # ---- table
    tab_ok = len(lst) == n and (lst.dam_class.to_numpy() == np.arange(n)).all() and \
        (lst.cell_id.to_numpy() == ids).all() and (lst.type.to_numpy() == typ).all() and \
        np.allclose(lst.capacity_mcm.to_numpy(), cap, rtol=0, atol=1e-9) and \
        np.allclose(lst.inflow_fraction.to_numpy(), infl, rtol=0, atol=1e-12) and \
        (lst.nservice.to_numpy() == nserv).all()
    checks['table'] = {'rows': len(lst), 'dams': n, 'status': 'passed' if tab_ok else 'failed'}

    # ---- types
    fut = (lst.kind == 'ssp_future').to_numpy()
    t_bad = {'future_not_global': int((fut & (typ != 1)).sum()),
             'global_inflow_not_1': int(((typ == 1) & (infl != 1)).sum()),
             'local_inflow_outside_0_1': int(((typ == 0) & ~((infl > 0) & (infl < 1))).sum()),
             'type_not_0_or_1': int((~np.isin(typ, (0, 1))).sum())}
    checks['types'] = {**t_bad, 'status': 'passed' if not any(t_bad.values()) else 'failed'}

    # ---- years
    y_isimip = lst.year_isimip.to_numpy(dtype=float)
    expect = {'histsoc': np.where(fut, bd.YEAR_NEVER, np.nan_to_num(y_isimip, nan=-1)),
              '1850soc': np.where(~fut & (y_isimip <= 1850), 0, bd.YEAR_NEVER),
              '2021soc': np.where(fut, bd.YEAR_NEVER, 0)}
    y_bad = {s: int((raw(f, 'year') != expect[s]).sum()) for s, f in zip(bd.SCENARIOS, files)}
    y_bad['historical_year_missing'] = int((~fut & ~np.isfinite(y_isimip)).sum())
    checks['years'] = {'mismatches': y_bad, 'operating_in_start_year': {
        s: {'1850': int((raw(f, 'year') <= 1850).sum()), '2021': int((raw(f, 'year') <= 2021).sum())}
        for s, f in zip(bd.SCENARIOS, files)}, 'status': 'passed' if not any(y_bad.values()) else 'failed'}

    # ---- service (parallel over dams)
    zero_expected = fut | ((typ == 1) & (lst.purpose_rule == 'no_supply').to_numpy())
    rule_bad = {'nservice_zero_not_expected': int(((nserv == 0) & ~zero_expected).sum()),
                'nservice_nonzero_expected_zero': int(((nserv > 0) & zero_expected).sum())}
    for f in files:
        f.close()
    mask_path = f'{qc}/reports/.mask.npy'; np.save(mask_path, mask)
    step = max(1, -(-n // (a.processes * 4)))
    jobs = [(paths, k, min(k + step, n), mask_path) for k in range(0, n, step)]
    problems = []
    with ProcessPoolExecutor(a.processes, mp_context=get_context('spawn')) as ex:
        for p in ex.map(check_slices, jobs):
            problems += p
    os.remove(mask_path)
    checks['service'] = {**rule_bad, 'nservice_zero': int((nserv == 0).sum()), 'service_links': int(nserv.sum()),
                         'problems': len(problems), 'first_problems': problems[:50],
                         'status': 'passed' if not problems and not any(rule_bad.values()) else 'failed'}

    # ---- review rules: recomputed from the evidence columns of review_pairs.csv
    review = pd.read_csv(f'{cdir}/{bd.REVIEW}', dtype={'isimip': str}, keep_default_na=False, na_values=[''])
    over = {e['isimip'] for e in dec['reviews']}
    bad_rule = []
    for r in review.itertuples():
        if r.isimip in over:
            continue
        if 'capacity' in r.reason:
            ch, rule, _, _ = bd.ds.capacity_rule(r.isimip_cap_mcm, r.gdw_cap_mcm,
                                                 r.gdw_lake_ctrl if isinstance(r.gdw_lake_ctrl, str) else '',
                                                 r.area_km2, r.dam_height_m)
            used = r.gdw_cap_mcm if ch == 'gdw' else r.isimip_cap_mcm
            if (ch, rule) != (r.capacity_choice, r.capacity_rule) or not np.isclose(used, r.capacity_used_mcm):
                bad_rule.append((r.isimip, 'capacity'))
        if 'distance' in r.reason and bd.ds.location_rule(r.fit_isimip_point, r.fit_gdw_point) != \
                (r.location_choice, r.location_rule):
            bad_rule.append((r.isimip, 'location'))
    checks['review'] = {'pairs': len(review), 'overridden_by_decisions': sorted(over),
                        'capacity_rules': review.capacity_rule.value_counts().to_dict(),
                        'location_rules': review.location_rule.value_counts().to_dict(),
                        'rule_mismatches': bad_rule, 'status': 'passed' if not bad_rule else 'failed'}

    # ---- accounting
    hs = src[src.source == 'histsoc']
    no_outcome = int(src.outcome.isna().sum())
    lost = hs[~hs.outcome.str.match(r'^(as_snapped|moved|merged into|combined into)', na=False)]
    ssp_counts = src[src.source != 'histsoc'].groupby('source').size().to_dict()
    isi = bd.ds.read_isimip_histsoc(f'{W}/raw/ISIMIP4b/{bd.HISTSOC}')
    ssp_expected = {s: len(bd.ds.read_ssp(f'{W}/raw/ISIMIP4b/{p}')) for s, p in bd.SSP.items()}
    caps = dict(zip(isi.key, isi.CAP_MCM.astype(float)))
    exp_cap = expected_historical_capacity(dec, caps, review)
    got_cap = float(cap[~fut].sum())
    acc_ok = no_outcome == 0 and len(lost) == 0 and len(hs) == len(isi) == bd.N_HISTSOC and \
        ssp_counts == ssp_expected and abs(got_cap - exp_cap) <= 1e-6 * exp_cap
    checks['accounting'] = {'histsoc_records': len(hs), 'histsoc_lost': lost[['key', 'name', 'outcome']].values.tolist(),
                            'records_without_outcome': no_outcome, 'ssp_records': ssp_counts,
                            'ssp_records_expected': ssp_expected,
                            'ssp_outcomes': src[src.source != 'histsoc'].outcome.str.split(':').str[0].value_counts().to_dict(),
                            'historical_capacity_hm3': got_cap, 'expected_historical_capacity_hm3': exp_cap,
                            'future_capacity_hm3': float(cap[fut].sum()), 'status': 'passed' if acc_ok else 'failed'}

    status = qcm.combine([c['status'] for c in checks.values()])
    report = {'object': os.path.relpath(cdir, W), 'checked_at': provenance.utcnow(), 'status': status,
              'checked_by': 'workflow/03_parameters/dams/verify_dams.py', 'code_commit': commit, 'code_dirty': dirty,
              'checks': checks}
    qcm.write_json(f'{qc}/reports/verify.json', json.loads(json.dumps(report, default=str)))
    qcm.write_summary(qc, {k: report[k] for k in ('object', 'checked_at', 'status', 'checked_by')} |
                      {'checks': {k: v['status'] for k, v in checks.items()}} |
                      ({'note': 'verifier code not committed (repository not clean): results kept in scratch, the '
                                'status of the object is unchanged'} if uncommitted else {}))
    if not a.component_dir and not uncommitted:
        provenance.set_qc(f'{cdir}/provenance.yaml', status, os.path.relpath(qc, W))
    print(json.dumps({k: v['status'] for k, v in checks.items()}), status)
    qcm.exit_with(status)


if __name__ == '__main__':
    main()
