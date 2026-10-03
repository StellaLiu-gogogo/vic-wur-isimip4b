#!/usr/bin/env python3
"""Render water_use_forcing.sbatch, submit it, and create the job record logs/04_forcing/<job-name>_<slurm-job-id>/.

One job produces the given years of one soc scenario with downscale_water_use.py (years in parallel, one process
per year) and then verifies them with verify_forcing.py. The job is submitted on hold, the record (job.sbatch,
job.yaml) is written, and the job is then released; the job moves its scheduler output into the record when it
starts (docs/directory-contracts.md, `logs/`).

Usage: submit_water_use_forcing.py --scenario histsoc --years 1850-2021 [--scratch [--scratch-label LABEL]]
       [--processes 16] [--time 04:00:00] [--mem 64G] [--partition main] [--dry-run]
"""
import argparse, datetime, os, re, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'water_use_forcing.sbatch')
sys.path.insert(0, HERE)
import downscale_water_use as wu   # noqa: E402  (scenarios, paths, git state)

PRODUCER = 'workflow/04_forcing/water_use/downscale_water_use.py'
VERIFIER = 'workflow/04_forcing/water_use/verify_forcing.py'
GB_PER_PROCESS = 4


def render(values):
    text = open(TEMPLATE).read()
    for k, v in values.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(wu.SCEN))
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--scratch-label', default=None, help=f'with --scratch: {wu.SCRATCH}/runs/<label>/')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=16)
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default=None, help=f'default {GB_PER_PROCESS} GB per process')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = wu.WORKDIR
    commit, dirty = wu.git_state(); to_scratch = a.scratch or dirty
    if a.scratch_label and not (a.scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs --scratch and lowercase words joined by hyphens')
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    nproc = max(1, min(a.processes, len(years)))
    mem = a.mem or f'{GB_PER_PROCESS * nproc}G'
    span = f'{years[0]}' if len(years) == 1 else f'{years[0]}-{years[-1]}'
    job_name = f'water-use-forcing-{a.scenario}-{span}' + ('-scratch' if to_scratch else '') + \
        (f'-{a.scratch_label}' if a.scratch_label else '')
    unit = f'water_use/{a.scenario}'
    sbase = f'{W}/{wu.SCRATCH}' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
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
                   'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    if not to_scratch and os.path.exists(out) and os.listdir(out):
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
    record = {
        'slurm_job_id': int(job_id), 'job_name': job_name,
        'rendered_by': 'workflow/04_forcing/water_use/submit_water_use_forcing.py',
        'template': 'workflow/04_forcing/water_use/water_use_forcing.sbatch',
        'code_commit': commit, 'code_dirty': dirty,
        'submitted_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': nproc, 'mem': mem},
        'commands': {'producer': f'python3 {PRODUCER} {producer}', 'verifier': f'python3 {VERIFIER} {verifier}'},
        'inputs': [wu.WA, wu.GW, f'{wu.POP}/{wu.SCEN[a.scenario][1][0]}', wu.COUNTRYMASK,
                   wu.DOMAIN.format(status=a.parameter_status, pset=a.parameter_set)],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'qc/forcing/{unit}'}
    with open(f'{job_dir}/job.yaml', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')


if __name__ == '__main__':
    main()
