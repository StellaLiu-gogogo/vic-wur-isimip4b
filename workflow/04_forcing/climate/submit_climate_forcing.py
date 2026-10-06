#!/usr/bin/env python3
"""Render climate_forcing.sbatch, submit it, and create the job record logs/04_forcing/<job-name>_<slurm-job-id>/.

The job is submitted on hold, the record (job.sbatch, job.yaml) is written, and the job is then released; the
job moves its scheduler output into the record when it starts (docs/directory-contracts.md, `logs/`).

Usage: submit_climate_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-hist --years 2015 [--variables ...]
       [--scratch] [--time 08:00:00] [--mem 64G] [--cpus 8] [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'climate_forcing.sbatch')
sys.path.insert(0, HERE)
import downscale_climate as dc   # noqa: E402  (variable selection and input discovery)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--gcm', required=True, choices=list(dc.GCM_DIR))
    ap.add_argument('--alias', required=True)
    ap.add_argument('--years', required=True)
    ap.add_argument('--variables', default=None)
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--scratch-label', default=None, help='with --scratch: scratch/climate-forcing/runs/<label>/')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--time', default='08:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--cpus', type=int, default=8)
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = workdir.root()
    commit, dirty = dc.git_state(); to_scratch = a.scratch or dirty
    variables = dc.select_variables(a.variables, to_scratch)
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    span = f'{years[0]}' if len(years) == 1 else f'{years[0]}-{years[-1]}'
    job_name = f'climate-forcing-{a.gcm}-{a.alias}-{span}' + ('-scratch' if to_scratch else '') + \
        (f'-{a.scratch_label}' if a.scratch_label else '')
    common = f'--gcm {a.gcm} --alias {a.alias} --variables {",".join(variables)} --years {years[0]}-{years[-1]}'
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    label = f' --scratch-label {a.scratch_label}' if a.scratch_label else ''
    producer = f'{common} {params} --processes {min(a.cpus, len(variables))}' + (' --scratch' + label if a.scratch else '')
    verifier = f'{common} {params} --processes {a.cpus}' + (' --scratch' + label if to_scratch else '')
    stage_logs = workdir.logs('04_forcing', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(a.cpus), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO,
        'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    base = (f'{W}/scratch/climate-forcing' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')) if to_scratch \
        else f'{W}/forcing/climate'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': a.cpus, 'mem': a.mem},
        'commands': {'producer': f'python3 workflow/04_forcing/climate/downscale_climate.py {producer}',
                     'verifier': f'python3 workflow/04_forcing/climate/verify_forcing.py {verifier}'},
        'inputs': sorted({os.path.relpath(dc.isimip_file(W, a.gcm, a.alias, s, yy), W)
                          for yy in years for v in variables for s in dc.VARIABLES[v]['sources']}) + [
            dc.DOMAIN_FILE.format(status=a.parameter_status, pset=a.parameter_set),
            dc.BUNDLE_FILE.format(status=a.parameter_status, pset=a.parameter_set), dc.ERA5_FILE],
        'outputs': [os.path.relpath(f'{base}/{a.gcm}/{a.alias}/{v}', W) for v in variables],
        'qc': [os.path.relpath(f'{base}/{a.gcm}/{a.alias}/{v}/qc', W) if to_scratch
               else f'qc/forcing/climate/{a.gcm}/{a.alias}/{v}' for v in variables]}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/04_forcing/climate/submit_climate_forcing.py',
                     'workflow/04_forcing/climate/climate_forcing.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
