#!/usr/bin/env python3
"""Render climate_forcing.sbatch, submit it, and create the job record logs/04_forcing/<job-name>_<slurm-job-id>/.

The job is submitted on hold, the record (job.sbatch, job.yaml) is written, and the job is then released; the
job moves its scheduler output into the record when it starts (docs/directory-contracts.md, `logs/`). With
--verify-only the job runs only the verifier on the existing files (e.g. the whole unit after an extension; it
updates qc.status in provenance.yaml). The submit script decides whether the producer writes to scratch (a
repository that is not clean) and passes the decision on; a producer started for a forcing unit stops when the
repository is no longer clean at the submitted commit.

Usage: submit_climate_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-hist --years 2015 [--variables ...]
       [--scratch] [--verify-only] [--time 08:00:00] [--mem 64G] [--cpus 8] [--partition main] [--dry-run]
       submit_climate_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-picontrol --start-years 1591 --cycle-window 1601-1610
  --start-years writes spin-up start years as copies of their cycle years (D20, downscale_climate.py); the verifier
  then checks the start years (--years of the verifier: the start years).
"""
import argparse, glob, os, sys

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
    ap.add_argument('--years', default=None)
    ap.add_argument('--start-years', default=None, help='spin-up start years (D20), with --cycle-window')
    ap.add_argument('--cycle-window', default=None, help='with --start-years: FIRST-LAST of the campaign cycle')
    ap.add_argument('--variables', default=None)
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--scratch-label', default=None, help='with --scratch: scratch/climate-forcing/runs/<label>/')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing output')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--time', default='08:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--cpus', type=int, default=8)
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = workdir.root()
    # decided once, here: a repository that is not clean redirects the producer to scratch (not existing files,
    # which --verify-only checks in place); otherwise the producer stops if the repository changes before it runs
    commit, dirty = dc.git_state(); to_scratch = a.scratch or (dirty and not a.verify_only)
    variables = dc.select_variables(a.variables, to_scratch)
    if bool(a.years) == bool(a.start_years) or bool(a.start_years) != bool(a.cycle_window):
        raise SystemExit('give either --years, or --start-years with --cycle-window')
    starts = sorted(int(v) for v in a.start_years.split(',')) if a.start_years else []
    if starts:
        years = starts
        span = 'start-' + '-'.join(str(v) for v in starts)
        yopt = f'--start-years {",".join(str(v) for v in starts)} --cycle-window {a.cycle_window}'
        vopt = f'--years-list {",".join(str(v) for v in starts)}'
    else:
        y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
        span = f'{years[0]}' if len(years) == 1 else f'{years[0]}-{years[-1]}'
        yopt = vopt = f'--years {years[0]}-{years[-1]}'
    job_name = f'climate-forcing-{a.gcm}-{a.alias}-{span}' + ('-scratch' if to_scratch or dirty else '') + \
        (f'-{a.scratch_label}' if a.scratch_label else '') + ('-verify' if a.verify_only else '')
    common = f'--gcm {a.gcm} --alias {a.alias} --variables {",".join(variables)}'
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    label = f' --scratch-label {a.scratch_label}' if a.scratch_label else ''
    producer = f'{common} {yopt} {params} --processes {min(a.cpus, len(variables))}' + (' --scratch' + label if to_scratch else f' --expect-commit {commit}')
    # a verifier from a repository that is not clean checks the output in place but keeps its results in scratch and
    # never changes the output's status (--qc-to-scratch); otherwise it stops if the repository changes (--expect-commit)
    verifier = f'{common} {vopt} {params} --processes {a.cpus}' + (' --scratch' + label if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    stage_logs = workdir.logs('04_forcing', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(a.cpus), 'MEM': a.mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO,
        'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    base = (f'{W}/scratch/climate-forcing' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')) if to_scratch \
        else f'{W}/forcing/climate'
    if a.verify_only:
        empty = [v for v in variables if not glob.glob(f'{base}/{a.gcm}/{a.alias}/{v}/*.nc')]
        if empty:
            raise SystemExit(f'no files to verify for {empty} under {base}/{a.gcm}/{a.alias}')
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': a.cpus, 'mem': a.mem},
        'commands': {'producer': None if a.verify_only else f'python3 workflow/04_forcing/climate/downscale_climate.py {producer}',
                     'verifier': f'python3 workflow/04_forcing/climate/verify_forcing.py {verifier}'},
        'inputs': sorted(f'forcing/climate/{a.gcm}/{a.alias}/{v}/{dc.out_name(v, a.gcm, a.alias, s)}'
                         for v in variables for s in {dc.cycle_source(yy, dc.parse_window(a.cycle_window))
                                                      for yy in starts}) if starts else
        sorted({os.path.relpath(dc.isimip_file(W, a.gcm, a.alias, s, yy), W)
                for yy in years for v in variables for s in dc.VARIABLES[v]['sources']}) + [
            dc.DOMAIN_FILE.format(status=a.parameter_status, pset=a.parameter_set),
            dc.BUNDLE_FILE.format(status=a.parameter_status, pset=a.parameter_set), dc.ERA5_FILE],
        'outputs': [os.path.relpath(f'{base}/{a.gcm}/{a.alias}/{v}', W) for v in variables],
        'qc': [os.path.relpath(f'{base}/{a.gcm}/{a.alias}/{v}/qc', W) if to_scratch
               else f'scratch/climate-forcing/verify-uncommitted/qc/forcing/climate/{a.gcm}/{a.alias}/{v}' if dirty
               else f'qc/forcing/climate/{a.gcm}/{a.alias}/{v}' for v in variables]}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/04_forcing/climate/submit_climate_forcing.py',
                     'workflow/04_forcing/climate/climate_forcing.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
