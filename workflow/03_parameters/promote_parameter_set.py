#!/usr/bin/env python3
"""Promote a parameter set from parameters/candidates/<set>/ to parameters/production/<set>/ (contract, `parameters/`).

The promotion copies, never moves: the candidate set stays as it is (earlier runs record its paths). It

  1. selects the files of every entry of manifests/parameters/<set>.yaml that is not marked `promotion: excluded`
     (its `files` and its `provenance` record); every selected entry must have qc_status passed;
  2. checks every selected candidate file against the manifest (md5, and sha256 when recorded) and records the
     sha256 of files the manifest gives no checksum for (provenance records);
  3. lists the restriction attributes (RESTRICTIONS) of the candidate NetCDF files, selected or excluded, and stops
     unless the user's acceptance of them is given (--accepted-restrictions);
  4. copies each file (contents and modification time) to the production directory under a temporary name, checks
     md5 and sha256 of the copy against the candidate, and renames it;
  5. writes promotion.yaml last: time, workflow commit, the user's authorisation, the accepted restrictions, every
     file with size, md5 and sha256, the excluded entries with their reasons, and the QC evidence of every entry.

A production directory that already exists stops the promotion (a production set is never overwritten). Outside
scratch the repository must be clean at the commit the job was submitted for (contract rule 14). The manifest is
changed by hand after verify_parameter_promotion.py has passed.

Usage: promote_parameter_set.py --authorised "user, 2026-10-30" --accepted-restrictions TEXT
       [--parameter-set ID] [--scratch] [--expect-commit SHA]
"""
import argparse, os, shutil, sys

import netCDF4 as nc
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import gitstate, hashing, provenance, workdir   # noqa: E402

SCRIPT = 'workflow/03_parameters/promote_parameter_set.py'
SCRATCH = 'scratch/parameter-promotion'
RECORD = 'promotion.yaml'
RESTRICTIONS = ('not_authorized_for_global_production', 'product_stage')


class PromoteError(ValueError):
    pass


def manifest_path(repo, pset):
    return os.path.join(repo, 'manifests', 'parameters', f'{pset}.yaml')


def selection(manifest):
    """(included, excluded): included is a list of {path, entry, md5, sha256, size_bytes} (each path once);
    excluded a list of {entry, reason, files}. Stops when a selected entry has not passed QC or a path belongs to
    both a selected and an excluded entry."""
    included, excluded, seen = [], [], {}
    for key, comp in manifest['components'].items():
        files = [dict(f) for f in comp.get('files', [])]
        prov = comp.get('provenance')
        if prov and prov not in {f['path'] for f in files}:
            files.append({'path': prov})
        if comp.get('promotion') == 'excluded':
            if not str(comp.get('promotion_reason') or '').strip():
                raise PromoteError(f'entry {key} is excluded without a promotion_reason')
            excluded.append({'entry': key, 'reason': ' '.join(str(comp['promotion_reason']).split()),
                             'files': [f['path'] for f in files]})
            continue
        if comp.get('qc_status') != 'passed':
            raise PromoteError(f'entry {key} has qc_status {comp.get("qc_status")}: every promoted entry must have '
                               f'passed QC (or be marked promotion: excluded with a reason)')
        for f in files:
            if f['path'] in seen:
                continue
            seen[f['path']] = key
            included.append({'path': f['path'], 'entry': key, 'md5': f.get('md5'), 'sha256': f.get('sha256'),
                             'size_bytes': f.get('size_bytes')})
    clash = sorted({p for e in excluded for p in e['files']} & set(seen))
    if clash:
        raise PromoteError(f'files listed by both a promoted and an excluded entry: {clash}')
    return included, excluded


def check_sources(cand, included):
    """md5 and sha256 of every selected candidate file; stops when a file is missing or differs from the manifest."""
    out = {}
    for f in included:
        p = os.path.join(cand, f['path'])
        if not os.path.isfile(p):
            raise PromoteError(f'candidate file missing: {p}')
        md5, sha = hashing.file_hashes(p)
        size = os.path.getsize(p)
        for what, got, want in (('md5', md5, f['md5']), ('sha256', sha, f['sha256']), ('size', size, f['size_bytes'])):
            if want is not None and got != want:
                raise PromoteError(f'{f["path"]}: {what} {got} differs from the manifest ({want})')
        out[f['path']] = {'md5': md5, 'sha256': sha, 'size_bytes': size}
    return out


def restrictions(cand, paths):
    """{path: {attribute: value}} of the RESTRICTIONS global attributes found in the NetCDF files among `paths`."""
    out = {}
    for rel in paths:
        p = os.path.join(cand, rel)
        if not rel.endswith('.nc') or not os.path.isfile(p):
            continue
        with nc.Dataset(p) as d:
            found = {a: str(d.getncattr(a)) for a in RESTRICTIONS if a in d.ncattrs()}
        if found:
            out[rel] = found
    return out


def copy_verified(src, dst, want):
    """Copy src to dst (contents and modification time) through dst + '.part'; check md5 and sha256 of the copy."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part'
    shutil.copy2(src, tmp)
    md5, sha = hashing.file_hashes(tmp)
    if (md5, sha) != (want['md5'], want['sha256']):
        os.remove(tmp)
        raise PromoteError(f'copy of {src} differs from the source (md5 {md5}, sha256 {sha})')
    os.replace(tmp, dst)


def promote(W, repo, pset, authorised, accepted, target_root, commit, dirty):
    """Promote `pset` into target_root/<pset>/; returns the path of promotion.yaml."""
    if not str(authorised or '').strip():
        raise PromoteError('--authorised must name who authorised the promotion and when (e.g. "user, 2026-10-30")')
    mpath = manifest_path(repo, pset)
    with open(mpath) as fh:
        manifest = yaml.safe_load(fh)
    cand = os.path.join(W, 'parameters', 'candidates', pset)
    target = os.path.join(target_root, pset)
    if os.path.exists(target):
        raise PromoteError(f'{target} exists: a production parameter set is never overwritten')
    included, excluded = selection(manifest)
    hashes = check_sources(cand, included)
    found = restrictions(cand, [f['path'] for f in included] + [p for e in excluded for p in e['files']])
    if found and not str(accepted or '').strip():
        raise PromoteError(f'restriction attributes found ({found}); promote only with the user\'s acceptance '
                           f'(--accepted-restrictions)')
    os.makedirs(target)
    for f in included:
        copy_verified(os.path.join(cand, f['path']), os.path.join(target, f['path']), hashes[f['path']])
    record = {
        'parameter_set_id': pset, 'promoted_at': provenance.utcnow(), 'promoted_by': SCRIPT,
        'code_commit': commit, 'code_dirty': dirty, 'authorised': authorised,
        'source': os.path.relpath(cand, W), 'target': os.path.relpath(target, W),
        'manifest': {'path': os.path.relpath(mpath, repo), 'sha256': hashing.sha256(mpath)},
        'restrictions': {'found': found, 'accepted': accepted or None},
        'files': [{'path': f['path'], 'entry': f['entry'], **hashes[f['path']]} for f in included],
        'excluded': excluded,
        'qc': {k: {'qc_status': c.get('qc_status'), 'qc_evidence': c.get('qc_evidence')}
               for k, c in manifest['components'].items() if c.get('promotion') != 'excluded'},
    }
    rpath = os.path.join(target, RECORD)
    with open(rpath + '.part', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False, width=110)
    os.replace(rpath + '.part', rpath)
    return rpath


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--authorised', required=True, help='who authorised the promotion and when')
    ap.add_argument('--accepted-restrictions', default=None,
                    help="the user's acceptance of restriction attributes found in the candidate files")
    ap.add_argument('--scratch', action='store_true', help=f'test: promote into {SCRATCH}/production/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(REPO)
    if not a.scratch:
        if a.expect_commit is None:
            raise SystemExit('a promotion outside scratch is started by submit_parameter_promotion.py (--expect-commit)')
        if dirty or commit != a.expect_commit:
            raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the '
                             f'repository is now at {commit} and {"not clean" if dirty else "clean"}; submit again')
    root = os.path.join(W, SCRATCH, 'production') if a.scratch else os.path.join(W, 'parameters', 'production')
    try:
        rpath = promote(W, REPO, a.parameter_set, a.authorised, a.accepted_restrictions, root, commit, dirty)
    except PromoteError as e:
        raise SystemExit(f'promotion stopped: {e}')
    print(f'promoted {a.parameter_set}; record {os.path.relpath(rpath, W)}')


if __name__ == '__main__':
    main()
