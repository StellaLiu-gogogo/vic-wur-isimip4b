#!/usr/bin/env python3
"""Submit one step of the land-use visualisation as a Slurm job; the job script and the scheduler output are kept
in workdir/analysis/landuse-visualization/logs/<step>_<slurm-job-id>/.

  cache    build_cache.py (reads the 581 VIC files and the ISIMIP inputs)
  figures  plot_maps.py, plot_timeseries.py and write_report.py (read only the cache)

Usage: submit.py --step cache|figures [--processes 16] [--mem 96G] [--time 02:00:00] [--partition main]
"""
import argparse, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lu_vis as lv   # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SBATCH = """#!/bin/bash
#SBATCH --job-name=landuse-visualization-{step}
#SBATCH --partition={partition}
#SBATCH --time={time}
#SBATCH --cpus-per-task={processes}
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
export OMP_NUM_THREADS=1
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
{commands}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--step', required=True, choices=['cache', 'figures'])
    ap.add_argument('--processes', type=int, default=16)
    ap.add_argument('--mem', default='96G')
    ap.add_argument('--time', default='02:00:00')
    ap.add_argument('--partition', default='main')
    a = ap.parse_args()
    logs = f'{lv.products()}/logs'; os.makedirs(logs, exist_ok=True)
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip()
    d = 'analysis/landuse-visualization'
    commands = {'cache': f'/usr/bin/time -v python3 {d}/build_cache.py --processes {a.processes}',
                'figures': (f'/usr/bin/time -v python3 {d}/plot_maps.py --processes {a.processes}\n'
                            f'/usr/bin/time -v python3 {d}/plot_timeseries.py\n'
                            f'/usr/bin/time -v python3 {d}/write_report.py')}[a.step]
    text = SBATCH.format(partition=a.partition, time=a.time, processes=a.processes, mem=a.mem, logs=logs, conda=conda,
                         workdir=lv.workdir(), repo=REPO, step=a.step, commands=commands)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]; job_dir = f'{logs}/{a.step}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}/')


if __name__ == '__main__':
    main()
