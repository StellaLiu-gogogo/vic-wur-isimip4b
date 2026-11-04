#!/usr/bin/env python3
"""Render roots.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job writes the vegetation component of a set with recomputed root zones (recompute_roots.py) and verifies it
(verify_roots.py). The job is submitted on hold, the record (job.sbatch, job.yaml) is written, and the job is then
released. With --verify-only the job runs only the verifier on the existing component. The submit script decides
whether the producer writes to scratch (a repository that is not clean) and passes the decision on; a producer
started for the component stops when the repository is no longer clean at the submitted commit.

Usage: submit_roots.py [--parameter-set vic-global-5arcmin-version-b] [--base-set vic-global-5arcmin-version-a]
       [--soil-dir DIR] [--scratch] [--verify-only] [--time 03:00:00] [--mem 48G] [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import gitstate, jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'roots.sbatch')
sys.path.insert(0, HERE)
import build_vegetation as bv   # noqa: E402
import recompute_roots as rr    # noqa: E402  (paths and names)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-b')
    ap.add_argument('--base-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--soil-dir', default=None, help='soil component directory for a scratch test (default: soil/ of the set)')
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing output')
    ap.add_argument('--time', default='03:00:00')
    ap.add_argument('--mem', default='48G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(rr.REPO); to_scratch = a.scratch or (dirty and not a.verify_only)
    if a.soil_dir and not to_scratch:
        raise SystemExit('--soil-dir is for scratch tests only; the component takes the soil component of its set')
    pset_rel = f'parameters/{a.parameter_status}/{a.parameter_set}'; rel_obj = f'{pset_rel}/vegetation'
    out = f'{W}/{rr.SCRATCH}/vegetation' if to_scratch else f'{W}/{rel_obj}'
    job_name = f'vegetation-roots-{a.parameter_set}' + ('-scratch' if to_scratch or dirty else '') + \
        ('-verify' if a.verify_only else '')
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = params + f' --base-set {a.base_set}' + (f' --soil-dir {a.soil_dir}' if a.soil_dir else '') + \
        (' --scratch' if to_scratch else f' --expect-commit {commit}')
    verifier = params + (f' --component-dir {out}' if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'MEM': a.mem, 'STAGE_LOGS': stage_logs,
        'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': rr.REPO,
        'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    if a.verify_only and not os.path.exists(f'{out}/{bv.OUT_NAME}'):
        raise SystemExit(f'{out}/{bv.OUT_NAME} does not exist; nothing to verify')
    if not a.verify_only and not to_scratch and os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; the producer would refuse to write into it')
    base = f'parameters/{a.parameter_status}/{a.base_set}/vegetation'
    soil = os.path.relpath(a.soil_dir, W) if a.soil_dir else f'{pset_rel}/soil'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': {'producer': None if a.verify_only else f'python3 {rr.CREATED_BY} {producer}',
                     'verifier': f'python3 workflow/03_parameters/vegetation/verify_roots.py {verifier}'},
        'inputs': [f'{base}/{bv.OUT_NAME}', f'{base}/{rr.CSV}', f'{base}/provenance.yaml', f'{soil}/{os.path.basename(rr.soil_file(f"{W}/{soil}"))}',
                   'workflow/03_parameters/vegetation/root_zeng2001_igbp.yaml'] + [f'forcing/landuse/{s}' for s in bv.SOC],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'{rr.SCRATCH}/verify-uncommitted/qc/{rel_obj}' if dirty
        else f'qc/{rel_obj}'}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/vegetation/submit_roots.py',
                     'workflow/03_parameters/vegetation/roots.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
