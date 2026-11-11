#!/usr/bin/env python3
"""Check of the set records of a product set (collect_set.py; D11) against what is on disk, found by walking the
set directory rather than by the collecting step's derivation.

Writes qc/postprocessed/<product-set-id>/ (below scratch/<task>/ with --scratch): summary.json, reports/check.json.

Checks (each passed, warning or failed; the summary takes the worst):
  records    product-set.yaml and checksums.sha256 exist; the record names the product set and the sha256 of the
             campaign file as it is now and of checksums.sha256; every line of checksums.sha256 is "<sha256>  <path>"
  inventory  every product file on disk (static/*.nc and the .nc files of every unit directory) is listed exactly once
             in checksums.sha256 and every listed file exists; the static files have the listed sha256 (hashed
             again: they are small); a unit file has the size and sha256 of its unit record
  units      every unit directory on disk is an expected unit of the record and is not recorded as missing; every
             unit recorded as made exists; the counts agree with the units; a segment recorded as accepted has only
             accepted units and a passed whole-run check
Warnings: units with status failed, staging directories of interrupted jobs (.writing-*).

Exit status: passed 0, failed 1, warning 3, not_checked 4.
Usage: check_set.py --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect_set     # noqa: E402
import product_set     # noqa: E402
import support         # noqa: E402

UNIT_DIR = re.compile(r'^\d{4}-\d{4}$')
LINE = re.compile(r'^([0-9a-f]{64})  (\S+)$')


def on_disk(set_dir):
    """(static files, {unit path: [file names]}, staging directories) of the set directory, relative to it."""
    static, units, staging = [], {}, []
    sd = os.path.join(set_dir, 'static')
    if os.path.isdir(sd):
        static = sorted(f'static/{f}' for f in os.listdir(sd) if f.endswith('.nc'))
    for gcm in sorted(os.listdir(set_dir)):
        gd = os.path.join(set_dir, gcm)
        if gcm == 'static' or not os.path.isdir(gd):
            continue
        if gcm.startswith('.writing'):
            staging.append(gcm); continue
        for key in sorted(os.listdir(gd)):
            for u in sorted(os.listdir(os.path.join(gd, key))):
                rel = f'{gcm}/{key}/{u}'
                if u.startswith('.writing'):
                    staging.append(rel)
                elif UNIT_DIR.match(u):
                    units[rel] = sorted(f for f in os.listdir(os.path.join(set_dir, rel)) if f.endswith('.nc'))
    return static, units, staging


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--expect-commit')
    a = ap.parse_args()
    W = support.workdir()
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    camp, camp_sha, _ = support.campaign(a.campaign)
    set_dir, qc_dir = product_set.set_paths(W, camp, a.scratch)
    checks = {}

    # records
    rp, listed = [], {}
    rec_path, sums_path = os.path.join(set_dir, collect_set.RECORD), os.path.join(set_dir, collect_set.CHECKSUMS)
    rec = support.load_yaml(rec_path) if os.path.exists(rec_path) else None
    if rec is None or not os.path.exists(sums_path):
        rp.append('product-set.yaml or checksums.sha256 is missing')
    else:
        if rec['product_set'] != camp['campaign_id']:
            rp.append(f'the record names product set {rec["product_set"]}')
        if rec['identity']['campaign_sha256'] != camp_sha:
            rp.append('the campaign file changed after the collection')
        if rec['checksums'].get('sha256') != support.sha256(sums_path):
            rp.append('checksums.sha256 changed after the collection')
        with open(sums_path) as fh:
            for i, line in enumerate(fh, 1):
                m = LINE.match(line.rstrip('\n'))
                if not m:
                    rp.append(f'checksums.sha256 line {i} is not "<sha256>  <path>"'); continue
                if m.group(2) in listed:
                    rp.append(f'{m.group(2)} is listed twice')
                listed[m.group(2)] = m.group(1)
        if rec['checksums'].get('lines') != len(listed):
            rp.append(f'checksums.sha256 has {len(listed)} files, the record says {rec["checksums"].get("lines")}')
    checks['records'] = ('failed' if rp else 'passed', {'problems': rp})
    if rp:
        return finish(W, qc_dir, set_dir, state, checks, rec_path)

    # inventory
    static, units, staging = on_disk(set_dir)
    ip = []
    files = static + [f'{u}/{f}' for u, fs in units.items() for f in fs]
    ip += [f'{f} is not listed in checksums.sha256' for f in files if f not in listed]
    ip += [f'{f} is listed but does not exist' for f in listed if not os.path.exists(os.path.join(set_dir, f))]
    for f in static:
        if f in listed and support.sha256(os.path.join(set_dir, f)) != listed[f]:
            ip.append(f'{f} differs from its listed sha256')
    for u in units:
        r = support.load_yaml(os.path.join(set_dir, u, 'provenance.yaml'))
        for f in r['files']:
            p = f'{u}/{f["name"]}'
            if p in listed and listed[p] != f['sha256']:
                ip.append(f'{p}: listed sha256 differs from the unit record')
            full = os.path.join(set_dir, p)
            if os.path.exists(full) and os.path.getsize(full) != f['size_bytes']:
                ip.append(f'{p}: size differs from the unit record')
    checks['inventory'] = ('failed' if ip else 'passed', {'problems': ip[:200], 'files_on_disk': len(files),
                                                          'files_listed': len(listed)})

    # units and segments
    up, counts = [], collections.Counter()
    recorded = {}
    for s in rec['segments']:
        for u in s['units']:
            recorded[u['unit']] = u['status']
            counts[u['status']] += 1
        if s['accepted'] and not (all(u['status'] == 'accepted' for u in s['units'])
                                  and s['whole_run_check']['status'] == 'passed' and s['whole_run_check']['bound']):
            up.append(f'{s["segment_id"]} is recorded as accepted without every unit accepted and a passed, bound '
                      'whole-run check')
    up += [f'{u} on disk is not an expected unit' for u in units if u not in recorded]
    up += [f'{u} on disk is recorded as missing' for u in units if recorded.get(u) == 'missing']
    up += [f'{u} is recorded as {s} but does not exist' for u, s in recorded.items()
           if s != 'missing' and u not in units]
    want = {'units_expected': len(recorded), **{s: counts[s] for s in product_set.UNIT_STATUSES},
            'segments_expected': len(rec['segments']),
            'segments_accepted': sum(bool(s['accepted']) for s in rec['segments'])}
    if {k: rec['counts'].get(k) for k in want} != want:
        up.append(f'counts {rec["counts"]} differ from the units {want}')
    checks['units'] = ('failed' if up else 'passed', {'problems': up, 'counts': want})
    failed_units = sorted(u for u, s in recorded.items() if s == 'failed')
    checks['unit_status'] = ('warning' if failed_units or staging else 'passed',
                             {'failed_units': failed_units, 'staging_directories': staging})
    return finish(W, qc_dir, set_dir, state, checks, rec_path)


def finish(W, qc_dir, set_dir, state, checks, rec_path):
    status = support.combine([s for s, _ in checks.values()])
    summary = {'object': os.path.relpath(set_dir, W), 'status': status,
               'checks': {k: s for k, (s, _) in checks.items()},
               'record_sha256': support.sha256(rec_path) if os.path.exists(rec_path) else None,
               'checked_by': {'script': 'workflow/06_postprocessing/check_set.py', **state},
               'checked_at': support.utcnow()}
    os.makedirs(f'{qc_dir}/reports', exist_ok=True)
    support.write_json(f'{qc_dir}/reports/check.json', {**summary, 'details': {k: d for k, (_, d) in checks.items()}})
    support.write_json(f'{qc_dir}/summary.json', summary)
    print(json.dumps({'status': status, 'checks': summary['checks']}, indent=1))
    support.exit_with(status)


if __name__ == '__main__':
    main()
