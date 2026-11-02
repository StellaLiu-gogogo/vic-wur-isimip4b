#!/usr/bin/env python3
"""Backup snapshot of the workdir and the repository (D13; docs/directory-contracts.md, "Data protection").

Layout under the backup root (ISIMIP4B_BACKUP):
  archive/<snapshot-id>/workdir/...   the selected workdir content (backup_rules.py), same relative paths
  archive/<snapshot-id>/repo/...      the repository working tree without .git/ (uncommitted edits included)
  archive/<snapshot-id>/backup-manifest.json, backup-checksums.sha256
  current -> archive/<snapshot-id>    the newest complete snapshot
  repo.git/                           bare repository: every branch and tag (git push --all, git push --tags)

A snapshot is copied to archive/<snapshot-id>.staging/ with rsync --link-dest against the current snapshot
(an unchanged file is a hard link and takes no space), every copied file is compared with its source by sha256
(a symbolic link by its target), the checksums file and the manifest are written, the staging directory is
renamed to its final name and `current` is pointed at it. The current snapshot is therefore complete at any
time; a failed snapshot leaves its staging directory for inspection (removal: contract "Deletion permissions").
Snapshots are never deleted by this script. The copy runs on a compute node (submit_backup.py); --dry-run only
lists and may run anywhere.

Usage: backup_snapshot.py --dry-run [--json FILE]
       backup_snapshot.py --run [--snapshot-id YYYY-MM-DD] [--processes N]
       backup_snapshot.py --verify [--snapshot-id ID] [--processes N]
"""
import argparse
import datetime
import json
import multiprocessing
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import backup_rules as br                      # noqa: E402
from common import gitstate, hashing, workdir  # noqa: E402

ENV_BACKUP = 'ISIMIP4B_BACKUP'
SCHEMA = 'isimip4b-backup-snapshot-1'
MANIFEST = 'backup-manifest.json'
CHECKSUMS = 'backup-checksums.sha256'
CURRENT = 'current'
BARE = 'repo.git'
KINDS = ('workdir', 'repo')


class SnapshotError(Exception):
    pass


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def backup_root():
    r = os.environ.get(ENV_BACKUP)
    if not r:
        sys.exit(f'set {ENV_BACKUP} (the backup root, contract "Data protection")')
    return r


def human(n):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if n < 1024 or unit == 'TiB':
            return f'{n:.1f} {unit}' if unit != 'B' else f'{n} B'
        n /= 1024


def plan(W, repo, rules):
    """Everything a snapshot would contain: {'accepted_runs', 'runs_not_accepted', 'selection': {kind: [...]},
    'summary': {category: {files, bytes}}}."""
    runs = br.accepted_runs(W)
    accepted = sorted(r for r, why in runs.items() if why is None)
    sel = {'workdir': list(br.select(W, rules, 'workdir', accepted)),
           'repo': list(br.select(repo, rules, 'repo'))}
    return {'accepted_runs': accepted,
            'runs_not_accepted': {r: why for r, why in runs.items() if why is not None},
            'selection': sel, 'summary': br.summarize(sel['workdir'] + sel['repo'])}


def describe(p, W, repo, root, rules):
    lines = [f'workdir {W}', f'repository {repo}', f'backup root {root}' +
             ('' if os.path.isdir(root) else ' (does not exist yet)')]
    cur = os.path.join(root, CURRENT)
    lines.append(f'current snapshot: {os.readlink(cur) if os.path.islink(cur) else "none"}')
    staging = sorted(d for d in os.listdir(os.path.join(root, 'archive')) if d.endswith('.staging')) \
        if os.path.isdir(os.path.join(root, 'archive')) else []
    if staging:
        lines.append(f'staging directories of failed snapshots: {staging}')
    lines.append('excluded: top-level ' + ', '.join(br.EXCLUDED_TOP) + '/, every ' +
                 ', '.join(d + '/' for d in br.EXCLUDED_DIR_NAMES) + ', repository .git/, and the file types of the '
                 '.gitignore sections ' + ', '.join(f'"{s}" ({len(v)})' for s, v in rules.sections.items()))
    lines.append('kept whatever the type: ' + ', '.join(f'{d}/' for d in br.WHOLE_DIRS) +
                 ', states/ of accepted production runs')
    lines.append(f'accepted production runs ({len(p["accepted_runs"])}): ' + (', '.join(p['accepted_runs']) or '-'))
    prod_not = {r: w for r, w in p['runs_not_accepted'].items() if w != 'not a production run'}
    if prod_not:
        lines.append('production runs not accepted: ' + '; '.join(f'{r}: {w}' for r, w in prod_not.items()))
    lines.append(f'{"category":16s} {"files":>8s} {"size":>12s}')
    total_f = total_b = 0
    for cat, v in p['summary'].items():
        lines.append(f'{cat:16s} {v["files"]:8d} {human(v["bytes"]):>12s}')
        total_f += v['files']; total_b += v['bytes']
    lines.append(f'{"total":16s} {total_f:8d} {human(total_b):>12s}')
    probe = root if os.path.isdir(root) else os.path.dirname(root.rstrip('/'))
    while not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    u = shutil.disk_usage(probe)
    lines.append(f'filesystem of {probe}: {human(u.free)} free of {human(u.total)} ({100 * u.used / u.total:.0f} % used)')
    return '\n'.join(lines)


def rsync(src, dst, items, link_dest, list_path):
    """Copy the listed relative paths from src to dst (rsync -a, files-from, hard links against link_dest)."""
    with open(list_path, 'wb') as fh:
        fh.write(b''.join(rel.encode() + b'\0' for rel, *_ in items))
    os.makedirs(dst, exist_ok=True)
    cmd = ['rsync', '-a', '--from0', f'--files-from={list_path}'] + \
        ([f'--link-dest={link_dest}'] if link_dest and os.path.isdir(link_dest) else []) + \
        [src.rstrip('/') + '/', dst.rstrip('/') + '/']
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_path)
    if r.returncode != 0:
        raise SnapshotError(f'rsync failed ({r.returncode}): {r.stderr.strip()[-2000:]}')
    return cmd


def push_repository(repo, bare):
    """Push every branch and tag of the repository to the bare repository (created when missing); returns the
    git outputs. Never --mirror: a branch deleted in the working repository stays in the backup."""
    if not os.path.isdir(bare):
        os.makedirs(os.path.dirname(bare), exist_ok=True)
        subprocess.run(['git', 'init', '--bare', '--quiet', bare], check=True)
    out = {}
    for what in ('--all', '--tags'):
        r = subprocess.run(['git', '-C', repo, 'push', '--porcelain', what, bare], capture_output=True, text=True)
        if r.returncode != 0:
            raise SnapshotError(f'git push {what} failed: {r.stderr.strip()[-2000:]}')
        out[what] = (r.stdout + r.stderr).strip()
    return out


def _compare(args):
    """(snapshot-relative path, digest or link target, ok, detail) of one copied file against its source."""
    src, dst, rel, link = args
    try:
        if link:
            a, b = os.readlink(src), os.readlink(dst)
            return rel, None, a == b, None if a == b else f'link target {b!r} differs from {a!r}'
        h_src, h_dst = hashing.sha256(src), hashing.sha256(dst)
        return rel, h_dst, h_src == h_dst, None if h_src == h_dst else 'sha256 differs from the source'
    except OSError as e:
        return rel, None, False, str(e)


def verify_copy(sources, staging, selection, processes):
    """Compare every copied file with its source; returns ([(rel, sha256)] of the regular files, [mismatch lines])."""
    jobs = [(os.path.join(sources[kind], rel), os.path.join(staging, kind, rel), f'{kind}/{rel}', link)
            for kind in KINDS for rel, size, cat, link in selection[kind]]
    with multiprocessing.Pool(max(1, processes)) as pool:
        results = pool.map(_compare, jobs, chunksize=64)
    hashes = [(rel, h) for rel, h, ok, _ in results if h is not None and ok]
    bad = [f'{rel}: {detail}' for rel, _, ok, detail in results if not ok]
    return hashes, bad


def write_checksums(path, hashes):
    with open(path, 'w') as fh:
        for rel, h in hashes:
            fh.write(f'{h}  {rel}\n')


def write_json(path, record):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def point_current(root, sid):
    tmp = os.path.join(root, CURRENT + '.tmp')
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(f'archive/{sid}', tmp)
    os.replace(tmp, os.path.join(root, CURRENT))


def run_snapshot(W, repo, root, rules, sid, processes, log=print):
    """Write the snapshot <sid>; returns the manifest. Raises SnapshotError (the staging directory is kept)."""
    archive = os.path.join(root, 'archive')
    final, staging = os.path.join(archive, sid), os.path.join(archive, sid + '.staging')
    if os.path.exists(final):
        raise SnapshotError(f'{final} exists: a snapshot is never replaced; choose another --snapshot-id')
    if os.path.exists(staging):
        raise SnapshotError(f'{staging} exists from a failed snapshot: inspect it, remove it under the contract '
                            '"Deletion permissions", or choose another --snapshot-id')
    cur = os.path.join(root, CURRENT)
    previous = os.path.realpath(cur) if os.path.islink(cur) else None
    commit, dirty = gitstate.state(repo)
    p = plan(W, repo, rules)
    log(describe(p, W, repo, root, rules))
    os.makedirs(staging)
    manifest = {'schema': SCHEMA, 'snapshot_id': sid, 'started_at': utcnow(), 'workdir': W, 'repository': repo,
                'repository_commit': commit, 'repository_dirty': dirty, 'backup_root': root,
                'previous_snapshot': os.path.basename(previous) if previous else None,
                'rules': {'gitignore_sections': rules.sections, 'excluded_top_level': list(br.EXCLUDED_TOP),
                          'excluded_directory_names': list(br.EXCLUDED_DIR_NAMES),
                          'kept_whole': {**br.WHOLE_DIRS, 'states/ of accepted production runs': 'states'},
                          'repository_excluded': list(br.REPO_EXCLUDED_TOP)},
                'accepted_runs': p['accepted_runs'], 'production_runs_not_accepted':
                {r: w for r, w in p['runs_not_accepted'].items() if w != 'not a production run'},
                'summary': p['summary'],
                'files': sum(len(v) for v in p['selection'].values()),
                'symlinks': sum(1 for v in p['selection'].values() for *_, link in v if link),
                'status': 'staging'}
    write_json(os.path.join(staging, MANIFEST), manifest)
    sources = {'workdir': W, 'repo': repo}
    manifest['rsync'] = {}
    for kind in KINDS:
        log(f'copying {kind}: {len(p["selection"][kind])} files')
        cmd = rsync(sources[kind], os.path.join(staging, kind), p['selection'][kind],
                    os.path.join(previous, kind) if previous else None, os.path.join(staging, f'.files-{kind}'))
        manifest['rsync'][kind] = ' '.join(cmd)
    log('pushing the repository branches and tags')
    manifest['git'] = {'bare': os.path.join(root, BARE), **push_repository(repo, os.path.join(root, BARE))}
    log(f'verifying {manifest["files"]} files with {processes} processes')
    hashes, bad = verify_copy(sources, staging, p['selection'], processes)
    manifest['verification'] = {'files_compared': manifest['files'], 'sha256_recorded': len(hashes),
                                'mismatches': bad, 'checked_at': utcnow()}
    if bad:
        manifest['status'] = 'failed'
        write_json(os.path.join(staging, MANIFEST), manifest)
        raise SnapshotError(f'{len(bad)} file(s) differ from the source after the copy, e.g. {bad[:3]}; the staging '
                            f'directory {staging} is kept')
    write_checksums(os.path.join(staging, CHECKSUMS), hashes)
    manifest['status'] = 'complete'
    manifest['completed_at'] = utcnow()
    write_json(os.path.join(staging, MANIFEST), manifest)
    os.rename(staging, final)
    point_current(root, sid)
    log(f'snapshot {sid} complete: {manifest["files"]} files, '
        f'{human(sum(v["bytes"] for v in p["summary"].values()))}; current -> archive/{sid}')
    return manifest


def verify_snapshot(root, sid, processes, log=print):
    """Re-hash a published snapshot against its checksums file; returns the list of mismatches."""
    snap = os.path.join(root, 'archive', sid)
    path = os.path.join(snap, CHECKSUMS)
    if not os.path.isfile(path):
        raise SnapshotError(f'{path} missing')
    with open(path) as fh:
        rows = [(line[:64], line[66:].rstrip('\n')) for line in fh if len(line) > 66]
    with multiprocessing.Pool(max(1, processes)) as pool:
        digests = pool.map(_hash_or_error, [os.path.join(snap, rel) for _, rel in rows], chunksize=64)
    bad = [f'{rel}: {"missing or unreadable" if d is None else "sha256 differs"}'
           for (h, rel), d in zip(rows, digests) if d != h]
    log(f'snapshot {sid}: {len(rows)} files checked, {len(bad)} mismatch(es)')
    return bad


def _hash_or_error(path):
    try:
        return hashing.sha256(path)
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='list what a snapshot would contain')
    g.add_argument('--run', action='store_true', help='write a snapshot')
    g.add_argument('--verify', action='store_true', help='re-hash a published snapshot (default: current)')
    ap.add_argument('--snapshot-id', default=None, help='default: today (UTC) as YYYY-MM-DD')
    ap.add_argument('--processes', type=int, default=4)
    ap.add_argument('--json', default=None, help='with --dry-run: write the plan summary to this file')
    a = ap.parse_args()
    W, root = workdir.root(), backup_root()
    rules = br.Rules.from_gitignore(os.path.join(REPO, '.gitignore'))
    try:
        if a.dry_run:
            p = plan(W, REPO, rules)
            print(describe(p, W, REPO, root, rules))
            if a.json:
                write_json(a.json, {k: v for k, v in p.items() if k != 'selection'} |
                           {'files': {k: [r for r, *_ in v] for k, v in p['selection'].items()}})
            return
        sid = a.snapshot_id or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        if a.run:
            run_snapshot(W, REPO, root, rules, sid, a.processes)
            return
        cur = os.path.join(root, CURRENT)
        sid = a.snapshot_id or (os.path.basename(os.path.realpath(cur)) if os.path.islink(cur) else None)
        if not sid:
            raise SnapshotError('no current snapshot; give --snapshot-id')
        bad = verify_snapshot(root, sid, a.processes)
        if bad:
            print('\n'.join(bad)); sys.exit(1)
    except SnapshotError as e:
        sys.exit(f'backup stopped: {e}')


if __name__ == '__main__':
    main()
