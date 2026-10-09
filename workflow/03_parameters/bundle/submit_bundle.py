#!/usr/bin/env python3
"""Render bundle.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job assembles the 16-class image-driver parameter file with assemble_bundle.py and verifies it with
verify_bundle.py. The job is submitted on hold, the record (job.sbatch, job.yaml) is written, and the job is
then released; the job moves its scheduler output into the record when it starts (docs/directory-contracts.md,
`logs/`). With --verify-only the job runs only the verifier on the existing file. The submit script decides whether
the producer writes to scratch (a repository that is not clean) and passes the decision on; a producer started for
the parameter set stops when the repository is no longer clean at the submitted commit.

Usage: submit_bundle.py [--scratch] [--verify-only] [--time 02:00:00] [--mem 64G] [--partition main] [--dry-run]
"""
import argparse, datetime, os, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'bundle.sbatch')
sys.path.insert(0, HERE)
import assemble_bundle as ab   # noqa: E402  (paths and git state)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing output')
    ap.add_argument('--time', default='02:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = ab.workdir()
    # decided once, here: a repository that is not clean redirects the producer to scratch (not existing files,
    # which --verify-only checks in place); otherwise the producer stops if the repository changes before it runs
    commit, dirty = ab.git_state(); to_scratch = a.scratch or (dirty and not a.verify_only)
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/bundle'
    out = f'{W}/{ab.SCRATCH}/bundle' if to_scratch else f'{W}/{rel_obj}'
    job_name = f'parameter-bundle-{a.parameter_set}' + ('-scratch' if to_scratch or dirty else '') + \
        ('-verify' if a.verify_only else '')
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = params + (' --scratch' if to_scratch else f' --expect-commit {commit}')
    # a verifier from a repository that is not clean checks the output in place but keeps its results in scratch and
    # never changes the output's status (--qc-to-scratch); otherwise it stops if the repository changes (--expect-commit)
    verifier = params + (f' --bundle-dir {out}' if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    conda_base = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    stage_logs = f'{W}/logs/03_parameters'
    text = open(TEMPLATE).read()
    for k, v in {'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': '1', 'MEM': a.mem,
                 'STAGE_LOGS': stage_logs, 'CONDA_BASE': conda_base, 'WORKDIR': W, 'REPO': REPO,
                 'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer,
                 'VERIFIER_ARGS': verifier}.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    if a.dry_run:
        print(text); return
    if a.verify_only and not os.path.exists(f'{out}/{ab.OUT_NAME}'):
        raise SystemExit(f'{out}/{ab.OUT_NAME} does not exist; nothing to verify')
    if not a.verify_only and os.path.exists(f'{out}/{ab.OUT_NAME}'):
        raise SystemExit(f'{out}/{ab.OUT_NAME} exists; the producer never overwrites it')
    os.makedirs(stage_logs, exist_ok=True)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{stage_logs}/{job_name}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
    record = {
        'slurm_job_id': int(job_id), 'job_name': job_name,
        'rendered_by': 'workflow/03_parameters/bundle/submit_bundle.py',
        'template': 'workflow/03_parameters/bundle/bundle.sbatch',
        'code_commit': commit, 'code_dirty': dirty,
        'submitted_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': {'producer': None if a.verify_only else f'python3 {ab.CREATED_BY} {producer}',
                     'verifier': f'python3 workflow/03_parameters/bundle/verify_bundle.py {verifier}'},
        'inputs': [f'{pset}/{ab.NATURAL}', f'{pset}/{ab.VEGETATION}', f'{pset}/{ab.DOMAIN}'],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'{ab.SCRATCH}/verify-uncommitted/qc/{rel_obj}' if dirty
        else f'qc/{rel_obj}'}
    with open(f'{job_dir}/job.yaml', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')


if __name__ == '__main__':
    main()
