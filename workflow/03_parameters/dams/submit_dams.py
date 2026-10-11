#!/usr/bin/env python3
"""Render dams.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job builds the dam component with build_dams.py and verifies it with verify_dams.py. --review runs only the
producer up to the hand-review tables (scratch/dam-parameters/review/, no verifier). --verify-only runs only the
verifier on the existing component (it updates qc.status in provenance.yaml). The submit script decides whether the
producer writes to scratch (a repository that is not clean) and passes the decision on; a producer started for the
component stops when the repository is no longer clean at the submitted commit.

Usage: submit_dams.py [--review | --discharge-run RUN_DIR [--discharge-years 1992 2021]] [--scratch] [--verify-only]
       [--time 04:00:00] [--mem 48G] [--processes 8] [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'dams.sbatch')
sys.path.insert(0, HERE)
import build_dams as bd   # noqa: E402  (paths and git state)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--review', action='store_true', help='only the hand-review tables (scratch)')
    ap.add_argument('--discharge-run', help='run directory (under the workdir) of the natural run')
    ap.add_argument('--discharge-years', type=int, nargs=2, default=[1992, 2021])
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing output')
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='48G')
    ap.add_argument('--processes', type=int, default=8, help='parallel readers of the verifier')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    if not (a.review or a.verify_only or a.discharge_run):
        raise SystemExit('--discharge-run is required unless --review or --verify-only')
    commit, dirty = bd.git_state(); to_scratch = a.scratch or a.review or (dirty and not a.verify_only)
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/dams'
    out = f'{W}/{bd.SCRATCH}/review' if a.review else f'{W}/{bd.SCRATCH}/dams' if to_scratch else f'{W}/{rel_obj}'
    job_name = f'dam-component-{a.parameter_set}' + ('-review' if a.review else '-scratch' if to_scratch or dirty else '') \
        + ('-verify' if a.verify_only else '')
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = params + (' --review' if a.review else
                         f' --discharge-run {a.discharge_run} --discharge-years {a.discharge_years[0]} {a.discharge_years[1]}')
    producer += ' --scratch' if to_scratch and not a.review else '' if a.review else f' --expect-commit {commit}'
    verifier = params + f' --processes {a.processes}' + (f' --component-dir {out}' if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(a.processes), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': bd.REPO,
        'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer,
        'RUN_VERIFIER': 'no' if a.review else 'yes', 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    first = f'{out}/{bd.OUT_NC.format(scenario=bd.SCENARIOS[0])}'
    if a.verify_only and not os.path.exists(first):
        raise SystemExit(f'{first} does not exist; nothing to verify')
    if not a.verify_only and not to_scratch and os.path.exists(first):
        raise SystemExit(f'{first} exists; the producer never overwrites it')
    pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': a.processes, 'mem': a.mem},
        'commands': {'producer': None if a.verify_only else f'python3 {bd.CREATED_BY} {producer}',
                     'verifier': None if a.review else f'python3 workflow/03_parameters/dams/verify_dams.py {verifier}'},
        'inputs': [f'{pset}/{bd.DOMAIN}', f'{pset}/{bd.ROUTING}', bd.GDW_DIR, f'raw/ISIMIP4b/{bd.HISTSOC}'] +
                  [f'raw/ISIMIP4b/{p}' for p in bd.SSP.values()] + ([a.discharge_run] if a.discharge_run else []),
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'{bd.SCRATCH}/verify-uncommitted/qc/{rel_obj}' if dirty
        else f'qc/{rel_obj}'}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/dams/submit_dams.py',
                     'workflow/03_parameters/dams/dams.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
