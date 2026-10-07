#!/usr/bin/env python3
"""Submit one step of the compute-storage-plan analysis as a Slurm job; the job script and the scheduler output are
kept in workdir/analysis/compute-storage-plan/logs/<step>_<slurm-job-id>/.

  measure  measure_files.py: storage per variable of the smoke files, compression tests on scratch copies
  drift    spinup_drift.py: drift of the water stores in the 10-year smoke run (cold start), for the spin-up length
  snowcmp  snow_compare.py: snow that builds up every year, smoke run against the sibling project's natural run
  plan     plan.py: demand, options, scenarios, figures and report from the run records and the measurement tables

Usage: submit.py --step measure|drift|snowcmp|plan [--measure-steps storage,copy,sample,lossy,fullfile] [--cpus 4] [--mem 96G]
                 [--time 12:00:00] [--partition main]
"""
import argparse, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csp   # noqa: E402

SBATCH = """#!/bin/bash
#SBATCH --job-name=compute-storage-plan-{step}
#SBATCH --partition={partition}
#SBATCH --time={time}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/{step}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={workdir}
export PYTHONPATH={repo}/workflow
export OMP_NUM_THREADS=1
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
{commands}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--step', required=True, choices=['measure', 'drift', 'snowcmp', 'plan'])
    ap.add_argument('--measure-steps', default='storage,copy,sample,lossy,fullfile')
    ap.add_argument('--cpus', type=int, default=4)
    ap.add_argument('--mem', default='96G')
    ap.add_argument('--time', default='12:00:00')   # measure: about 4.5 h
    ap.add_argument('--partition', default='main')
    a = ap.parse_args()
    logs = f'{csp.products()}/logs'; os.makedirs(logs, exist_ok=True)
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip()
    d = f'analysis/{csp.TASK}'
    commands = {'measure': f'/usr/bin/time -v python3 {d}/measure_files.py --steps {a.measure_steps}',
                'drift': f'/usr/bin/time -v python3 {d}/spinup_drift.py',
                'snowcmp': f'/usr/bin/time -v python3 {d}/snow_compare.py',
                'plan': f'/usr/bin/time -v python3 {d}/plan.py'}[a.step]
    text = SBATCH.format(partition=a.partition, time=a.time, cpus=a.cpus, mem=a.mem, logs=logs, conda=conda,
                         workdir=csp.workdir(), repo=csp.REPO, step=a.step, commands=commands)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]; job_dir = f'{logs}/{a.step}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}/')


if __name__ == '__main__':
    main()
