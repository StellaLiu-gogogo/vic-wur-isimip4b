#!/usr/bin/env python3
"""Render check_run.sbatch for one run directory, submit it, and create the job record
logs/05_simulation/<job-name>_<slurm-job-id>/ (job.sbatch, job.yaml, scheduler output).

Usage: submit_check.py --run-dir runs/<campaign-id>/<run-id> [--time 04:00:00] [--mem 64G] [--partition main]
       [--dependency <slurm-job-id>]   (start only when that job has completed successfully)
"""
import argparse, datetime, os, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'check_run.sbatch')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dependency', default=None)
    a = ap.parse_args()
    submit(a.run_dir, a.time, a.mem, a.partition, a.dependency)


def submit(run_dir, time='04:00:00', mem='64G', partition='main', dependency=None):
    """Render, submit on hold, write the job record, release; returns the job id."""
    W = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
    rd = os.path.abspath(run_dir if os.path.isabs(run_dir) else os.path.join(W, run_dir))
    rel = os.path.relpath(rd, W)
    run_id = os.path.basename(rd)
    label = run_id.split('__')[1] if '__' in run_id else run_id.split('_')[-1]
    job_name = f'run-check-{os.path.basename(os.path.dirname(rd))}-{label}'
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True, text=True).stdout.strip())
    conda_base = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    stage_logs = f'{W}/logs/05_simulation'
    text = open(TEMPLATE).read()
    for k, v in {'JOB_NAME': job_name, 'PARTITION': partition, 'TIME': time, 'MEM': mem, 'STAGE_LOGS': stage_logs,
                 'CONDA_BASE': conda_base, 'WORKDIR': W, 'REPO': REPO, 'RUN_DIR': rd}.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    os.makedirs(stage_logs, exist_ok=True)
    cmd = ['sbatch', '--parsable', '--hold'] + ([f'--dependency=afterok:{dependency}'] if dependency else [])
    r = subprocess.run(cmd, input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{stage_logs}/{job_name}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    record = {'slurm_job_id': int(job_id), 'job_name': job_name,
              'rendered_by': 'workflow/05_simulation/monitor/submit_check.py',
              'template': 'workflow/05_simulation/monitor/check_run.sbatch', 'code_commit': commit, 'code_dirty': dirty,
              'submitted_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'resources': {'partition': partition, 'time': time, 'cpus_per_task': 1, 'mem': mem},
              'dependency': dependency,
              'inputs': [rel], 'outputs': [f'qc/{rel}']}
    with open(f'{job_dir}/job.yaml', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')
    return job_id


if __name__ == '__main__':
    main()
