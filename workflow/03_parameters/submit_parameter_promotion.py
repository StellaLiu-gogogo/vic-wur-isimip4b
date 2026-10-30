#!/usr/bin/env python3
"""Render parameter_promotion.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job promotes a parameter set (promote_parameter_set.py) and verifies the promoted copy
(verify_parameter_promotion.py). With --scratch the set is promoted into scratch/parameter-promotion/production/ as a
test. Outside scratch the repository must be clean (contract rule 14), the user's authorisation is required, and
the job stops when the repository is no longer clean at the submitted commit when it starts.

Usage: submit_parameter_promotion.py --authorised "user, 2026-10-30" [--accepted-restrictions TEXT]
       [--parameter-set ID] [--scratch] [--time 04:00:00] [--mem 8G] [--partition main] [--dry-run]
"""
import argparse, os, shlex, sys

from common import gitstate, jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'parameter_promotion.sbatch')
sys.path.insert(0, HERE)
import promote_parameter_set as pp   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--authorised', required=True)
    ap.add_argument('--accepted-restrictions', default=None)
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='8G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(pp.REPO)
    if dirty and not a.scratch:
        raise SystemExit('the repository is not clean: a production parameter set is promoted only from a clean '
                         'repository (contract rule 14); commit first or use --scratch')
    root = f'{pp.SCRATCH}/production' if a.scratch else 'parameters/production'
    if os.path.exists(f'{W}/{root}/{a.parameter_set}'):
        raise SystemExit(f'{root}/{a.parameter_set} exists; the promotion would refuse to write into it')
    common = f'--parameter-set {a.parameter_set}' + (' --scratch' if a.scratch else f' --expect-commit {commit}')
    promoter = common + f' --authorised {shlex.quote(a.authorised)}' + \
        (f' --accepted-restrictions {shlex.quote(a.accepted_restrictions)}' if a.accepted_restrictions else '')
    job_name = f'parameter-promotion-{a.parameter_set}' + ('-scratch' if a.scratch else '')
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'MEM': a.mem, 'STAGE_LOGS': stage_logs,
        'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': pp.REPO,
        'PROMOTER_ARGS': promoter, 'VERIFIER_ARGS': common})
    if a.dry_run:
        print(text); return
    qc = f'{pp.SCRATCH}/qc/parameters/production/{a.parameter_set}' if a.scratch else \
        f'qc/parameters/production/{a.parameter_set}'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': {'promoter': f'python3 {pp.SCRIPT} {promoter}',
                     'verifier': f'python3 workflow/03_parameters/verify_parameter_promotion.py {common}'},
        'inputs': [f'parameters/candidates/{a.parameter_set}', f'manifests/parameters/{a.parameter_set}.yaml'],
        'outputs': [f'{root}/{a.parameter_set}'], 'qc': qc}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/submit_parameter_promotion.py',
                     'workflow/03_parameters/parameter_promotion.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
