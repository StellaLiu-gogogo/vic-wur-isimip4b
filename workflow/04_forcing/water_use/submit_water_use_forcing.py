#!/usr/bin/env python3
"""Render water_use_forcing.sbatch, submit it, and create the job record logs/04_forcing/<job-name>_<slurm-job-id>/.

One job produces the given years of one soc scenario with downscale_water_use.py (years in parallel, one process
per year) and then verifies them with verify_forcing.py. The job is submitted on hold, the record (job.sbatch,
job.yaml) is written, and the job is then released; the job moves its scheduler output into the record when it
starts (docs/directory-contracts.md, `logs/`). With --verify-only the job runs only the verifier on the existing
files (it updates qc.status in provenance.yaml). The submit script decides whether the producer writes to scratch
(a repository that is not clean) and passes the decision on; a producer started for a forcing unit stops when the
repository is no longer clean at the submitted commit.

Usage: submit_water_use_forcing.py --scenario histsoc --years 1850-2021 [--scratch [--scratch-label LABEL]]
       [--verify-only] [--processes 16] [--time 04:00:00] [--mem 64G] [--partition main] [--dry-run]
"""
import argparse, os, re, sys

from common import jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'water_use_forcing.sbatch')
sys.path.insert(0, HERE)
import downscale_water_use as wu   # noqa: E402  (scenarios, paths, git state)

PRODUCER = 'workflow/04_forcing/water_use/downscale_water_use.py'
VERIFIER = 'workflow/04_forcing/water_use/verify_forcing.py'
GB_PER_PROCESS = 4


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(wu.SCEN))
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--scratch-label', default=None, help=f'with --scratch: {wu.SCRATCH}/runs/<label>/')
    ap.add_argument('--verify-only', action='store_true', help='run only the verifier on the existing output')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=16)
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default=None, help=f'default {GB_PER_PROCESS} GB per process')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = wu.WORKDIR
    # decided once, here: a repository that is not clean redirects the producer to scratch (not existing files,
    # which --verify-only checks in place); otherwise the producer stops if the repository changes before it runs
    commit, dirty = wu.git_state(); to_scratch = a.scratch or (dirty and not a.verify_only)
    if a.scratch_label and not (a.scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs --scratch and lowercase words joined by hyphens')
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    nproc = max(1, min(a.processes, len(years)))
    mem = a.mem or f'{GB_PER_PROCESS * nproc}G'
    span = f'{years[0]}' if len(years) == 1 else f'{years[0]}-{years[-1]}'
    job_name = f'water-use-forcing-{a.scenario}-{span}' + ('-scratch' if to_scratch or dirty else '') + \
        (f'-{a.scratch_label}' if a.scratch_label else '') + ('-verify' if a.verify_only else '')
    unit = f'water_use/{a.scenario}'
    sbase = f'{W}/{wu.SCRATCH}' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
    out = f'{sbase}/{a.scenario}' if to_scratch else f'{W}/forcing/{unit}'
    params = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
    producer = f'--scenario {a.scenario} --years {years[0]}-{years[-1]} {params} --processes {nproc}' + \
        (' --scratch' if to_scratch else f' --expect-commit {commit}') + \
        (f' --scratch-label {a.scratch_label}' if a.scratch_label else '')
    # a verifier from a repository that is not clean checks the output in place but keeps its results in scratch and
    # never changes the output's status (--qc-to-scratch); otherwise it stops if the repository changes (--expect-commit)
    verifier = f'--scenario {a.scenario} --years {years[0]}-{years[-1]} {params} --processes {nproc}' + \
        (f' --unit-dir {out}' if to_scratch else (' --qc-to-scratch' if dirty else f' --expect-commit {commit}'))
    stage_logs = workdir.logs('04_forcing', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': str(nproc), 'MEM': mem,
        'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO,
        'RUN_PRODUCER': 'no' if a.verify_only else 'yes', 'PRODUCER_ARGS': producer, 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    if a.verify_only and not (os.path.isdir(out) and os.listdir(out)):
        raise SystemExit(f'{out} has no files to verify')
    if not a.verify_only and not to_scratch and os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty; the producer would refuse to write into it')
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': nproc, 'mem': mem},
        'commands': {'producer': None if a.verify_only else f'python3 {PRODUCER} {producer}', 'verifier': f'python3 {VERIFIER} {verifier}'},
        'inputs': [wu.WA, wu.GW, f'{wu.POP}/{wu.SCEN[a.scenario][1][0]}', wu.COUNTRYMASK,
                   wu.DOMAIN.format(status=a.parameter_status, pset=a.parameter_set)],
        'outputs': [os.path.relpath(out, W)],
        'qc': os.path.relpath(f'{out}/qc', W) if to_scratch else f'scratch/water-use-forcing/verify-uncommitted/qc/forcing/{unit}' if dirty
        else f'qc/forcing/{unit}'}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/04_forcing/water_use/submit_water_use_forcing.py',
                     'workflow/04_forcing/water_use/water_use_forcing.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
