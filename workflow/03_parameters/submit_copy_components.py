#!/usr/bin/env python3
"""Render copy_components.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

The job copies the named components of a candidate parameter set into a new candidate set with
copy_components.py; the record of the copy is in the job's output in the job record. The job is submitted on hold, the record
(job.sbatch, job.yaml) is written, and the job is then released. Outside scratch the repository must be clean; the
job stops when the repository is no longer clean at the submitted commit.

Usage: submit_copy_components.py --parameter-set vic-global-5arcmin-version-b --from-set vic-global-5arcmin-version-a
       --components domain routing irrigation dams water_use [--scratch] [--time 01:00:00] [--mem 8G]
       [--partition main] [--dry-run]
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import gitstate, jobrecord, workdir   # noqa: E402

sys.path.insert(0, HERE)
import copy_components as cc   # noqa: E402

TEMPLATE = os.path.join(HERE, 'copy_components.sbatch')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', required=True)
    ap.add_argument('--from-set', required=True)
    ap.add_argument('--components', nargs='+', required=True)
    ap.add_argument('--scratch', action='store_true', help=f'test: copy into {cc.SCRATCH}/candidates/')
    ap.add_argument('--time', default='01:00:00')
    ap.add_argument('--mem', default='8G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(REPO)
    if dirty and not a.scratch:
        raise SystemExit('the repository is not clean: a copy into parameters/candidates/ needs a clean repository '
                         '(rule 14); commit first, or use --scratch for a test')
    args = f'--parameter-set {a.parameter_set} --from-set {a.from_set} --components {" ".join(a.components)}' + \
        (' --scratch' if a.scratch else f' --expect-commit {commit}')
    job_name = f'copy-components-{a.parameter_set}' + ('-scratch' if a.scratch else '')
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'MEM': a.mem, 'STAGE_LOGS': stage_logs,
        'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO, 'ARGS': args})
    if a.dry_run:
        print(text); return
    src = f'parameters/candidates/{a.from_set}'
    target = f'{cc.SCRATCH}/candidates/{a.parameter_set}' if a.scratch else f'parameters/candidates/{a.parameter_set}'
    for c in a.components:
        d = f'{W}/{target}/{c}'
        if os.path.exists(d) and os.listdir(d):
            raise SystemExit(f'{d} exists and is not empty; the copy would refuse to write into it')
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': {'copy': f'python3 {cc.SCRIPT} {args}'},
        'inputs': [f'{src}/{c}' for c in a.components] + [f'manifests/parameters/{a.from_set}.yaml'],
        'outputs': [f'{target}/{c}' for c in a.components], 'qc': None}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/submit_copy_components.py',
                     'workflow/03_parameters/copy_components.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
