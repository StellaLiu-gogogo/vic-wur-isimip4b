#!/usr/bin/env python3
"""Record an existing candidate build of the frozen VIC-WUR commit as the production build, without recompiling.

D01 (amendment 2026-10-28): the build of 2026-09-30 in builds/vic/<commit>/ was made by build_vic.sh from the then
provisional lock, so its manifest says build_kind candidate and freeze_status provisional. The commit is now frozen
and the user decided that this build, unchanged, is the production build. This script

  1. checks that model/vic.lock.yaml is frozen at the build's commit, that the build is a candidate build with
     status built or tested and no earlier promotion, that its checkout was at that commit, and that the executable
     still has the recorded sha256 and size (the executable is never rebuilt or touched);
  2. keeps the manifest as it was, byte for byte, in logs/build_manifest.candidate.json;
  3. rewrites build_manifest.json with build_kind production, model.freeze_status frozen, the kept manifest added to
     `logs`, and a `promotion` record (time, decision, authorisation, verified executable sha256, kept manifest and
     its sha256, the VIC test-suite status, workflow commit). Status, environment, build command, tests and the
     original workflow record of the build stay as they were.

Nothing else in builds/ changes. A promotion is written only from a clean repository (contract rule 14), and only
once: a build with a `promotion` record, a production build or an existing kept manifest stops it. --dry-run checks
everything and prints the planned file changes without writing.

Usage: promote_build.py --authorised "user, 2026-10-28" [--dry-run]
"""
import argparse, datetime, json, os, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import gitstate, hashing, workdir   # noqa: E402

SCRIPT = 'workflow/05_simulation/build/promote_build.py'
LOCK = 'model/vic.lock.yaml'
KEPT = 'logs/build_manifest.candidate.json'
DECISION = 'docs/decisions/D01-frozen-model-version.md (amendment 2026-10-28: production build)'
REASON = ('built by build_vic.sh from the same commit, with the same module bucket and runtime modules; the smoke and '
          'natural runs used this executable (its sha256 is in their run manifests); not recompiled')


class PromoteError(ValueError):
    pass


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def plan(W, repo, authorised):
    """(build dir, manifest text as it is now, promoted manifest) after every check; stops with PromoteError."""
    if not str(authorised or '').strip():
        raise PromoteError('--authorised must name who authorised the promotion and when (e.g. "user, 2026-10-28")')
    with open(os.path.join(repo, LOCK)) as fh:
        lock = yaml.safe_load(fh)
    commit = lock['commit']
    if lock.get('freeze_status') != 'frozen':
        raise PromoteError(f'{LOCK} is {lock.get("freeze_status")}, not frozen: only a build of the frozen commit can be '
                           'a production build (D01)')
    bdir = os.path.join(W, 'builds', 'vic', commit)
    mpath = os.path.join(bdir, 'build_manifest.json')
    with open(mpath) as fh:
        text = fh.read()
    m = json.loads(text)
    model = m.get('model') or {}
    if model.get('model_commit') != commit or model.get('checkout_head') != commit:
        raise PromoteError(f'{mpath} is a build of {model.get("model_commit")} (checkout {model.get("checkout_head")}), '
                           f'the lock is {commit}')
    if m.get('build_kind') != 'candidate' or 'promotion' in m:
        raise PromoteError(f'{mpath} is a {m.get("build_kind")} build' + (' already promoted' if 'promotion' in m else '')
                           + '; only a candidate build is promoted, once')
    if m.get('status') not in ('built', 'tested'):
        raise PromoteError(f'{mpath} has status {m.get("status")}; only a usable build (built or tested) is promoted')
    if os.path.lexists(os.path.join(bdir, KEPT)):
        raise PromoteError(f'{bdir}/{KEPT} exists; it is never overwritten')
    exe = os.path.join(bdir, m['executable']['path'])
    sha = hashing.sha256(exe)
    if sha != m['executable']['sha256'] or os.path.getsize(exe) != m['executable'].get('size_bytes'):
        raise PromoteError(f'{exe} has sha256 {sha} and {os.path.getsize(exe)} bytes, the manifest records '
                           f'{m["executable"]["sha256"]} and {m["executable"].get("size_bytes")}')
    code_commit, dirty = gitstate.state(repo)
    new = json.loads(text)
    new['build_kind'] = 'production'
    new['model']['freeze_status'] = 'frozen'
    new['logs'] = sorted(set(new.get('logs') or []) | {os.path.basename(KEPT)})
    new['promotion'] = {
        'promoted_at': utcnow(), 'decision': DECISION, 'authorised_by': ' '.join(str(authorised).split()),
        'reason': REASON, 'recompiled': False,
        'from': {'build_kind': m['build_kind'], 'freeze_status': model.get('freeze_status')},
        'to': {'build_kind': 'production', 'freeze_status': 'frozen'},
        'lock': {'file': LOCK, 'commit': commit, 'freeze_status': lock['freeze_status'], 'set_on': str(lock.get('set_on')),
                 'set_by': lock.get('set_by')},
        'executable': {'path': m['executable']['path'], 'sha256_verified': sha, 'size_bytes': os.path.getsize(exe)},
        'status_kept': m['status'],
        'vic_test_suite': (m.get('tests') or {}).get('vic_test_suite', {}).get('status'),
        'previous_manifest': {'path': KEPT, 'sha256': hashing.sha256(mpath), 'size_bytes': len(text.encode())},
        'workflow': {'script': SCRIPT, 'code_commit': code_commit, 'code_dirty': dirty}}
    return bdir, text, new


def promote(W, repo, authorised, dry_run=False):
    bdir, text, new = plan(W, repo, authorised)
    out = json.dumps(new, indent=2) + '\n'
    print(f'{bdir}/{KEPT}: new file, {len(text.encode())} bytes (the manifest as it is now)')
    print(f'{bdir}/build_manifest.json: {len(text.encode())} -> {len(out.encode())} bytes '
          f'(build_kind production, model.freeze_status frozen, logs + {os.path.basename(KEPT)}, promotion record)')
    if dry_run:
        print('dry run: nothing written')
        return new
    if new['promotion']['workflow']['code_dirty']:
        raise PromoteError('the repository is not clean; promote from a clean repository (contract rule 14)')
    with open(os.path.join(bdir, KEPT), 'x') as fh:
        fh.write(text)
    tmp = os.path.join(bdir, '.build_manifest.json.promote')
    with open(tmp, 'x') as fh:
        fh.write(out)
    os.replace(tmp, os.path.join(bdir, 'build_manifest.json'))
    print(f'promoted {bdir} to the production build')
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--authorised', required=True, help='who authorised the promotion and when, e.g. "user, 2026-10-28"')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    try:
        promote(workdir.root(), REPO, a.authorised, a.dry_run)
    except PromoteError as e:
        sys.exit(f'promotion stopped: {e}')


if __name__ == '__main__':
    main()
