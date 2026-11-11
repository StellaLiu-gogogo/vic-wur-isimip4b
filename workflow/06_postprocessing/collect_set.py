#!/usr/bin/env python3
"""Collecting step of a product set (D11): writes product-set.yaml and checksums.sha256 at the root of
postprocessed/<product-set-id>/ (below scratch/<task>/ with --scratch). The only writer of these two files; a unit job
never writes them. They are written again at every collection, each completely under a temporary name and then
renamed into place; no product unit is changed.

product-set.yaml records the identity of the set (product-set ID = campaign ID, campaign file and its sha256,
parameter set, model and protocol commit), the state of the decisions the products depend on (D07-D11, from
docs/decisions/open-decisions.md), the static files with sha256 and the status of their check, every expected product
unit (derived from the campaign, product_set.py) with its status missing / present / accepted / failed, the reasons
and the number of values outside the protocol's valid range per product file (D11 amendment 2026-11-11),
per segment whether it is accepted (every unit accepted and the whole-run check of its run passed and bound to the
latest attempt of every chunk), the counts, and when, by which commit and job the file was written.

checksums.sha256 lists every product file of the set, in the format of `sha256sum` with paths relative to the set
directory: the static files hashed here, the product files of every present unit with the sha256 of its unit record
(the unit check hashes the files against the record; this step compares only their sizes, so that the products are
not read again).

Usage: collect_set.py --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import product_set     # noqa: E402
import static_fields   # noqa: E402
import support         # noqa: E402

CHECKSUMS = 'checksums.sha256'
RECORD = 'product-set.yaml'


def collect(W, camp, camp_sha, camp_rel, scratch):
    """The record of product-set.yaml without its `written` part, and the lines of checksums.sha256."""
    set_dir, qc_dir = product_set.set_paths(W, camp, scratch)
    pset = camp['campaign_id']
    static_dir = os.path.join(set_dir, 'static')
    lines, static = [], {'directory': os.path.relpath(static_dir, W), 'files': {}, 'check': {'status': 'not_checked'}}
    if os.path.isdir(static_dir):
        for fn in static_fields.STATIC_FILES:
            p = os.path.join(static_dir, fn)
            if os.path.exists(p):
                static['files'][fn] = support.sha256(p)
                lines.append(f'{static["files"][fn]}  static/{fn}')
        sq = os.path.join(qc_dir, 'static', 'summary.json')
        if os.path.exists(sq):
            s = support.load_yaml(sq)
            static['check'] = {'status': s.get('status', 'not_checked'), 'summary': os.path.relpath(sq, W)}
    segments, counts = [], collections.Counter()
    for run in product_set.expected_runs(camp, W):
        man = product_set.run_manifest(W, camp, run)
        units = [product_set.unit_state(W, set_dir, qc_dir, run, u, man) for u in run['units']]
        for u in units:
            counts[u['status']] += 1
            for f in u.pop('files', []):
                lines.append(f'{f["sha256"]}  {u["unit"]}/{f["name"]}')
        whole = product_set.whole_run_check(W, man) if man else {'status': 'not_checked', 'bound': False}
        accepted = all(u['status'] == 'accepted' for u in units) and whole['status'] == 'passed' and whole['bound']
        segments.append({'segment_id': run['segment_id'], 'segment_key': run['segment_key'], 'gcm': run['gcm'],
                         'period': run['period'], 'years': [run['start_year'], run['end_year']],
                         'run_id': run['run_id'], 'run_manifest': 'present' if man else 'missing',
                         'run_status': man.get('status') if man else None, 'whole_run_check': whole,
                         'accepted': accepted, 'units': units})
    record = {
        'product_set': pset,
        'identity': {'campaign': pset, 'campaign_file': camp_rel, 'campaign_sha256': camp_sha,
                     'production': bool(camp.get('production')), 'parameter_set': camp['parameter_set']['id'],
                     'model_commit': camp['model']['commit'], 'protocol_commit': camp['protocol']['commit']},
        'decisions': product_set.decisions(),
        'static': static,
        'counts': {'units_expected': sum(counts.values()), **{s: counts[s] for s in product_set.UNIT_STATUSES},
                   'segments_expected': len(segments),
                   'segments_accepted': sum(s['accepted'] for s in segments)},
        'checksums': {'file': CHECKSUMS, 'lines': len(lines)},
        'segments': segments,
    }
    return record, lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--expect-commit')
    a = ap.parse_args()
    started = support.utcnow()
    W = support.workdir()
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean: the set records need a clean repository (rule 14); '
                         'use --scratch <task-id>')
    camp, camp_sha, camp_rel = support.campaign(a.campaign)
    set_dir, _ = product_set.set_paths(W, camp, a.scratch)
    if not os.path.isdir(set_dir):
        raise SystemExit(f'{set_dir} does not exist: make the static files first')
    record, lines = collect(W, camp, camp_sha, camp_rel, a.scratch)
    support.write_text(os.path.join(set_dir, CHECKSUMS), ''.join(line + '\n' for line in lines))
    record['checksums']['sha256'] = support.sha256(os.path.join(set_dir, CHECKSUMS))
    record['written'] = {'by': 'workflow/06_postprocessing/collect_set.py', **state,
                         'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'started_at': started,
                         'ended_at': support.utcnow()}
    support.write_yaml(os.path.join(set_dir, RECORD), record)
    c = record['counts']
    print(f'{set_dir}: {c["units_expected"]} units expected, {c["accepted"]} accepted, {c["present"]} present, '
          f'{c["failed"]} failed, {c["missing"]} missing; {c["segments_accepted"]} of {c["segments_expected"]} '
          f'segments accepted')


if __name__ == '__main__':
    main()
