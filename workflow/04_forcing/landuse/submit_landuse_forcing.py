#!/usr/bin/env python3
"""Render landuse_forcing.sbatch, submit it, and create the job record logs/04_forcing/<job-name>_<slurm-job-id>/.

One job converts the given years of one soc scenario with isimip_landuse_to_vic_annual.py (years in parallel,
one process per year) and then verifies them with verify_forcing.py. The job is submitted on hold, the record
(job.sbatch, job.yaml) is written, and the job is then released; the job moves its scheduler output into the
record when it starts (docs/directory-contracts.md, `logs/`). With --verify-only the job runs only the verifier on
the existing files (e.g. to re-check an accepted unit with a new verifier; it updates qc.status in provenance.yaml).

Memory: up to about 6 GB per producer process and 7.4 GB per verifier process (16 verifier processes
exceeded 112 GB on 2026-10-01); --mem defaults to 9 GB per process.

Usage: submit_landuse_forcing.py --scenario histsoc --years 1850-2021 [--scratch [--scratch-label LABEL]]
       [--verify-only] [--processes 16] [--time 06:00:00] [--mem 144G] [--partition main] [--dry-run]
"""
import argparse, datetime, os, re, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'landuse_forcing.sbatch')
sys.path.insert(0, HERE)
import isimip_landuse_to_vic_annual as lu   # noqa: E402  (scenario files, paths, git state)

PRODUCER = 'workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py'
VERIFIER = 'workflow/04_forcing/landuse/verify_forcing.py'
GB_PER_PROCESS = 9   # observed peaks: producer about 6 GB, verifier about 7.4 GB per process


def render(values):
    text = open(TEMPLATE).read()
    for k, v in values.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(lu.SCEN))
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--scratch-label', default=None, help='with --scratch: scratch/landuse-converter/runs/<label>/')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing files')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=16)
    ap.add_argument('--time', default='06:00:00')
    ap.add_argument('--mem', default=None, help=f'default {GB_PER_PROCESS} GB per process')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = lu.WORKDIR
    commit, dirty = lu.git_state()
    to_scratch = a.scratch or (dirty and not a.verify_only)   # a dirty repository redirects the producer, not existing files
    if a.scratch_label and not (a.scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs --scratch and lowercase words joined by hyphens')
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    nproc = max(1, min(a.processes, len(years)))
    mem = a.mem or f'{GB_PER_PROCESS * nproc}G'
    span = f'{years[0]}' if len(years) == 1 else f'{years[0]}-{years[-1]}'
    job_name = f'landuse-forcing-{a.scenario}-{span}' + ('-scratch' if to_scratch else '') + \
        (f'-{a.scratch_label}' if a.scratch_label else '') + ('-verify' if a.verify_only else '')
    unit = f'landuse/{a.scenario}'
    sbase = f'{W}/scratch/landuse-converter' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
    out = f'{sbase}/{a.scenario}' if to_scratch else f'{W}/forcing/{unit}'
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = f'--scenario {a.scenario} --years {years[0]}-{years[-1]} {params} --processes {nproc}' + \
        (' --scratch' if a.scratch else '') + (f' --scratch-label {a.scratch_label}' if a.scratch_label else '')
    verifier = f'--scenario {a.scenario} --years {years[0]}-{years[-1]} {params} --processes {nproc}' + \
        (f' --unit-dir {out}' if to_scratch else '')
    conda_base = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    stage_logs = f'{W}/logs/04_forcing'
    text = render({'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(nproc), 'MEM': mem,
                   'STAGE_LOGS': stage_logs, 'CONDA_BASE': conda_base, 'WORKDIR': W, 'REPO': REPO,
                   'RUN_PRODUCER': 'no' if a.verify_only else 'yes',
                   'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    if a.verify_only and not (os.path.isdir(out) and os.listdir(out)):
        raise SystemExit(f'{out} has no files to verify')
    if not a.verify_only and not to_scratch and os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; the producer would refuse to write into it')
    os.makedirs(stage_logs, exist_ok=True)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{stage_logs}/{job_name}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    f15, furb, _ = lu.SCEN[a.scenario]
    record = {
        'slurm_job_id': int(job_id), 'job_name': job_name,
        'rendered_by': 'workflow/04_forcing/landuse/submit_landuse_forcing.py',
        'template': 'workflow/04_forcing/landuse/landuse_forcing.sbatch',
        'code_commit': commit, 'code_dirty': dirty,
        'submitted_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': nproc, 'mem': mem},
        'commands': {'producer': None if a.verify_only else f'python3 {PRODUCER} {producer}',
                     'verifier': f'python3 {VERIFIER} {verifier}'},
        'inputs': [os.path.relpath(f'{lu.RAW}/{f15}', W), os.path.relpath(f'{lu.RAW}/{furb}', W),
                   f'parameters/{a.parameter_status}/{a.parameter_set}/domain/vic_global_5min_domain_nogl.nc',
                   os.path.relpath(os.path.dirname(lu.COVERAGE), W)],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'qc/forcing/{unit}'}
    with open(f'{job_dir}/job.yaml', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')


if __name__ == '__main__':
    main()
