#!/usr/bin/env python3
"""Render backup_snapshot.sbatch, submit it and create the job record logs/09_backup/<job-name>_<slurm-job-id>/.

The job writes a backup snapshot (backup_snapshot.py --run) or, with --list, only prints what a snapshot would
contain (--dry-run; the listing is in the job's slurm-<id>.out). Copying into the backup root needs the user's
approval of the listed content (contract "Data protection"), given as --approved "user, <date>" and recorded in the
job record. The repository may be dirty: the snapshot records the commit and the dirty flag and copies the working
tree as it is.

Usage: submit_backup.py --list [--time 01:00:00]
       submit_backup.py --approved "user, 2026-11-03" [--snapshot-id YYYY-MM-DD] [--processes 8] [--time 12:00:00]
       [--mem 8G] [--partition main] [--dry-run]
"""
import argparse
import os
import sys

from common import gitstate, jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'backup_snapshot.sbatch')
sys.path.insert(0, HERE)
import backup_snapshot as bs   # noqa: E402

STAGE = '09_backup'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--list', action='store_true', help='only list what a snapshot would contain')
    ap.add_argument('--approved', default=None, help='the user\'s approval of the listed content, e.g. "user, 2026-11-03"')
    ap.add_argument('--snapshot-id', default=None)
    ap.add_argument('--processes', type=int, default=8)
    ap.add_argument('--time', default=None, help='default 01:00:00 for --list, 12:00:00 for a snapshot')
    ap.add_argument('--mem', default='8G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    if not a.list and not a.approved:
        raise SystemExit('a snapshot copies into the backup root: give --approved "user, <date>" (contract "Data '
                         'protection"), or --list to see what it would contain')
    W, root = workdir.root(), bs.backup_root()
    commit, dirty = gitstate.state(bs.REPO)
    args = '--dry-run' if a.list else f'--run --processes {a.processes}' + \
        (f' --snapshot-id {a.snapshot_id}' if a.snapshot_id else '')
    job_name = 'backup-list' if a.list else 'backup-snapshot' + (f'-{a.snapshot_id}' if a.snapshot_id else '')
    cpus = 1 if a.list else a.processes
    time = a.time or ('01:00:00' if a.list else '12:00:00')
    stage_logs = workdir.logs(STAGE, W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': time, 'CPUS': str(cpus), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'BACKUP': root,
        'REPO': bs.REPO, 'ARGS': args})
    if a.dry_run:
        print(text); return
    details = {'resources': {'partition': a.partition, 'time': time, 'cpus_per_task': cpus, 'mem': a.mem},
               'commands': {'backup': f'python3 workflow/09_backup/backup_snapshot.py {args}'},
               'inputs': [W, bs.REPO], 'outputs': [] if a.list else [f'{root}/archive/<snapshot-id>', f'{root}/{bs.BARE}'],
               'approved': a.approved}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/09_backup/submit_backup.py',
                     'workflow/09_backup/backup_snapshot.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
