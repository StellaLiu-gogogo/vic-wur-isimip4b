#!/usr/bin/env python3
"""Render vegetation_component.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job builds the vegetation component with build_vegetation.py and verifies it with verify_vegetation.py.
The job is submitted on hold, the record (job.sbatch, job.yaml) is written, and the job is then released; the
job moves its scheduler output into the record when it starts (docs/directory-contracts.md, `logs/`).

Usage: submit_vegetation_component.py [--scratch] [--processes 16] [--time 04:00:00] [--mem 96G]
       [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'vegetation_component.sbatch')
sys.path.insert(0, HERE)
import build_vegetation as bv   # noqa: E402  (paths and git state)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--processes', type=int, default=16)
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='96G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = bv.git_state(); to_scratch = a.scratch or dirty
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/vegetation'
    out = f'{W}/{bv.SCRATCH}/vegetation' if to_scratch else f'{W}/{rel_obj}'
    job_name = f'vegetation-component-{a.parameter_set}' + ('-scratch' if to_scratch else '')
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status} --processes {a.processes}'
    producer = params + (' --scratch' if a.scratch else '')
    verifier = params + (f' --component-dir {out}' if to_scratch else '')
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(a.processes), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO,
        'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    if not to_scratch and os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; the producer would refuse to write into it')
    pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': a.processes, 'mem': a.mem},
        'commands': {'producer': f'python3 {bv.CREATED_BY} {producer}',
                     'verifier': f'python3 workflow/03_parameters/vegetation/verify_vegetation.py {verifier}'},
        'inputs': [f'{pset}/{bv.BASE_BUNDLE}', f'{pset}/{bv.DOMAIN}', bv.KOPPEN] + [f'forcing/landuse/{s}' for s in bv.SOC],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'qc/{rel_obj}'}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/vegetation/submit_vegetation_component.py',
                     'workflow/03_parameters/vegetation/vegetation_component.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
