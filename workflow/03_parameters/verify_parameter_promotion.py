#!/usr/bin/env python3
"""Independent verification of a promoted parameter set (promote_parameter_set.py).

Checks (each with its own status; the set passes only when all pass):
  record      promotion.yaml exists (it is written last, so a set without it is an unfinished promotion), names the
              set, a clean workflow commit (outside scratch) and the user's authorisation; restrictions found are
              accepted
  files       every recorded file exists in the production set with the recorded size, md5 and sha256; the
              candidate file is still identical; md5 and sha256 equal the parameter manifest where it records them
  complete    the production set holds exactly the recorded files and promotion.yaml, and the recorded files are
              exactly the files of the manifest entries not marked `promotion: excluded`
  qc          every promoted manifest entry has qc_status passed and its QC evidence exists with summary.json status
              passed
Writes <qc>/summary.json and <qc>/reports/verify.json, where <qc> is qc/parameters/production/<set>/ (with
--scratch: scratch/parameter-promotion/qc/parameters/production/<set>/).

Usage: verify_parameter_promotion.py [--parameter-set ID] [--scratch]
"""
import argparse, json, os, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import gitstate, hashing, provenance, qc as qcm, workdir   # noqa: E402

sys.path.insert(0, HERE)
import promote_parameter_set as pp   # noqa: E402  (file selection rule and names; every check is computed here)

SCRIPT = 'workflow/03_parameters/verify_parameter_promotion.py'


def tree(root):
    """Relative paths of every file below root."""
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


def verify(W, repo, pset, target, scratch):
    checks = {}
    rpath = os.path.join(target, pp.RECORD)
    if not os.path.isfile(rpath):
        return {'record': {'problem': f'{os.path.relpath(rpath, W)} missing (unfinished or no promotion)',
                           'status': 'not_checked'}}
    with open(rpath) as fh:
        rec = yaml.safe_load(fh)
    with open(pp.manifest_path(repo, pset)) as fh:
        manifest = yaml.safe_load(fh)
    r = rec.get('restrictions') or {}
    problems = []
    if rec.get('parameter_set_id') != pset:
        problems.append(f'record names {rec.get("parameter_set_id")}')
    if not scratch and rec.get('code_dirty') is not False:
        problems.append('promoted from a repository that was not clean')
    if not str(rec.get('authorised') or '').strip():
        problems.append('no authorisation recorded')
    if r.get('found') and not str(r.get('accepted') or '').strip():
        problems.append('restrictions found but not accepted')
    checks['record'] = {'promoted_at': rec.get('promoted_at'), 'code_commit': rec.get('code_commit'),
                        'authorised': rec.get('authorised'), 'restrictions': r, 'problems': problems,
                        'status': 'failed' if problems else 'passed'}

    # ---- files
    man = {}
    for comp in manifest['components'].values():
        for f in comp.get('files', []):
            man[f['path']] = f
    cand = os.path.join(W, 'parameters', 'candidates', pset)
    bad = []
    for f in rec.get('files', []):
        p = os.path.join(target, f['path'])
        if not os.path.isfile(p):
            bad.append({'path': f['path'], 'problem': 'missing'}); continue
        md5, sha = hashing.file_hashes(p)
        got = {'md5': md5, 'sha256': sha, 'size_bytes': os.path.getsize(p)}
        diff = [k for k in got if got[k] != f.get(k)]
        diff += [f'manifest {k}' for k in ('md5', 'sha256') if man.get(f['path'], {}).get(k) not in (None, got[k])]
        cp = os.path.join(cand, f['path'])
        if not os.path.isfile(cp) or hashing.sha256(cp) != sha:
            diff.append('candidate file differs or is missing')
        if diff:
            bad.append({'path': f['path'], 'problem': ', '.join(diff)})
    checks['files'] = {'files': len(rec.get('files', [])), 'bytes': sum(f.get('size_bytes', 0) for f in rec.get('files', [])),
                       'problems': bad, 'status': 'failed' if bad else 'passed'}

    # ---- complete
    recorded = {f['path'] for f in rec.get('files', [])}
    present = set(tree(target)) - {pp.RECORD}
    included, excluded = pp.selection(manifest)
    expected = {f['path'] for f in included}
    checks['complete'] = {'extra_files': sorted(present - recorded), 'recorded_not_selected': sorted(recorded - expected),
                          'selected_not_recorded': sorted(expected - recorded),
                          'excluded_entries': [e['entry'] for e in excluded]}
    c = checks['complete']
    c['status'] = 'failed' if c['extra_files'] or c['recorded_not_selected'] or c['selected_not_recorded'] else 'passed'

    # ---- qc of every promoted entry
    entries = {}
    for k, comp in manifest['components'].items():
        if comp.get('promotion') == 'excluded':
            continue
        ev = comp.get('qc_evidence')
        sp = os.path.join(W, ev, 'summary.json') if ev else None
        st = None
        if sp and os.path.isfile(sp):
            with open(sp) as fh:
                st = json.load(fh).get('status')
        entries[k] = {'qc_status': comp.get('qc_status'), 'qc_evidence': ev, 'evidence_status': st,
                      'ok': comp.get('qc_status') == 'passed' and st == 'passed'}
    checks['qc'] = {'entries': entries, 'status': 'passed' if all(e['ok'] for e in entries.values()) else 'failed'}
    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--scratch', action='store_true', help=f'verify the test promotion in {pp.SCRATCH}/production/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(REPO)
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    rel = f'parameters/production/{a.parameter_set}'
    target = os.path.join(W, pp.SCRATCH, 'production', a.parameter_set) if a.scratch else os.path.join(W, rel)
    qc = os.path.join(W, pp.SCRATCH, 'qc', rel) if a.scratch else os.path.join(W, 'qc', rel)
    os.makedirs(os.path.join(qc, 'reports'), exist_ok=True)
    checks = verify(W, REPO, a.parameter_set, target, a.scratch)
    status = qcm.combine([c['status'] for c in checks.values()])
    report = {'object': os.path.relpath(target, W), 'checked_at': provenance.utcnow(), 'status': status,
              'checked_by': SCRIPT, 'code_commit': commit, 'code_dirty': dirty, 'checks': checks}
    qcm.write_json(os.path.join(qc, 'reports', 'verify.json'), report)
    qcm.write_summary(qc, {k: report[k] for k in ('object', 'checked_at', 'status', 'checked_by', 'code_commit',
                                                  'code_dirty')} | {'checks': {k: v['status'] for k, v in checks.items()}})
    print(json.dumps({k: v['status'] for k, v in checks.items()}), status)
    qcm.exit_with(status)


if __name__ == '__main__':
    main()
