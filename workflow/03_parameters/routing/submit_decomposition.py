#!/usr/bin/env python3
"""Render decomposition.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job builds the FILE decomposition with build_decomposition.py and verifies it with verify_decomposition.py.
--verify-only runs only the verifier on the existing file (it updates qc.status in provenance.yaml). The submit
script decides whether the producer writes to scratch (a repository that is not clean) and passes the decision on;
a producer started for the parameter set stops when the repository is no longer clean at the submitted commit.

Usage: submit_decomposition.py [--groups 128] [--scratch] [--verify-only] [--time 02:00:00] [--mem 64G]
       [--processes 8] [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'decomposition.sbatch')
sys.path.insert(0, HERE)
import build_decomposition as bdc   # noqa: E402  (paths and git state)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--groups', type=int, default=bdc.GROUPS)
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing file')
    ap.add_argument('--time', default='02:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--processes', type=int, default=8, help='parallel readers of the dam service maps')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = bdc.git_state(); to_scratch = a.scratch or (dirty and not a.verify_only)
    pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
    out = f'{W}/{bdc.SCRATCH}' if to_scratch else f'{W}/{pset}/routing'
    job_name = f'decomposition-{a.parameter_set}' + ('-scratch' if to_scratch or dirty else '') + \
        ('-verify' if a.verify_only else '')
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = params + f' --groups {a.groups} --processes {a.processes}' + \
        (' --scratch' if to_scratch else f' --expect-commit {commit}')
    verifier = params + f' --processes {a.processes}' + \
        (f' --file-dir {out}' if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(a.processes), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': bdc.REPO,
        'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer,
        'RUN_VERIFIER': 'yes', 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    target = f'{out}/{bdc.FILE_NAME}'
    if a.verify_only and not os.path.exists(target):
        raise SystemExit(f'{target} does not exist; nothing to verify')
    if not a.verify_only and not to_scratch and (os.path.exists(target) or os.path.exists(f'{out}/provenance.yaml')):
        raise SystemExit(f'{target} or {out}/provenance.yaml exists; the producer never overwrites them')
    qc_rel = f'{pset}/routing/{bdc.QC_SUBDIR}'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': a.processes, 'mem': a.mem},
        'commands': {'producer': None if a.verify_only else f'python3 {bdc.CREATED_BY} {producer}',
                     'verifier': f'python3 workflow/03_parameters/routing/verify_decomposition.py {verifier}'},
        'inputs': [f'{pset}/{p}' for p in bdc.INPUTS + (bdc.ADOPTED_DECOMPOSITION,)],
        'outputs': [os.path.relpath(f'{out}/{bdc.FILE_NAME}', W), os.path.relpath(f'{out}/provenance.yaml', W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'{bdc.SCRATCH}/verify-uncommitted/qc/{qc_rel}'
        if dirty else f'qc/{qc_rel}'}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/routing/submit_decomposition.py',
                     'workflow/03_parameters/routing/decomposition.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
