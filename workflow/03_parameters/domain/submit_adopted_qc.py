#!/usr/bin/env python3
"""Render adopted_qc.sbatch, submit it, and create the job record logs/03_parameters/<job-name>_<slurm-job-id>/.

One job runs the verifiers of the adopted components domain, routing, irrigation and water_use of a parameter set
(each writes qc/parameters/<status>/<set>/<component>/). The job is submitted on hold, the record (job.sbatch,
job.yaml) is written, and the job is then released. From a clean repository the verifiers stop when the repository
is no longer clean at the submitted commit when the job starts (--expect-commit); from a repository that is not
clean their results go to scratch/adopted-parameter-qc/verify-uncommitted/qc/... (--qc-to-scratch).

Usage: submit_adopted_qc.py [--parameter-set ID] [--components domain routing irrigation water_use]
       [--time 02:00:00] [--mem 24G] [--partition main] [--dry-run]
"""
import argparse, os, sys

from common import gitstate, jobrecord, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'adopted_qc.sbatch')
sys.path.insert(0, HERE)
import adopted   # noqa: E402

COMPONENTS = ('domain', 'routing', 'irrigation', 'water_use')
FILES = {'domain': adopted.DOMAIN, 'routing': 'routing/vic_global_5min_routing.nc',
         'irrigation': 'irrigation/vic_global_5min_irrigation_parameters.nc',
         'water_use': 'water_use/vic_global_5min_wateruse_parameters_receiving-network.nc'}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default=adopted.DEFAULT_SET)
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--components', nargs='+', default=list(COMPONENTS), choices=COMPONENTS)
    ap.add_argument('--time', default='02:00:00')
    ap.add_argument('--mem', default='24G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args(); W = workdir.root()
    commit, dirty = gitstate.state(adopted.REPO)
    pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
    for c in a.components:
        if not os.path.exists(f'{W}/{pset}/{FILES[c]}'):
            raise SystemExit(f'{pset}/{FILES[c]} does not exist; nothing to verify')
    job_name = f'adopted-parameter-qc-{a.parameter_set}' + ('-uncommitted' if dirty else '')
    verifier = f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}' + \
        (' --qc-to-scratch' if dirty else f' --expect-commit {commit}')
    stage_logs = workdir.logs('03_parameters', W)
    text = jobrecord.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'MEM': a.mem, 'STAGE_LOGS': stage_logs,
        'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': adopted.REPO,
        'COMPONENTS': ' '.join(a.components), 'VERIFIER_ARGS': verifier})
    if a.dry_run:
        print(text); return
    qc_root = f'{adopted.SCRATCH}/verify-uncommitted/qc/{pset}' if dirty else f'qc/{pset}'
    details = {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': {c: f'python3 workflow/03_parameters/{c}/verify_{c}.py {verifier}' for c in a.components},
        'inputs': [f'{pset}/{FILES[c]}' for c in a.components] + [f'{pset}/{adopted.DOMAIN}',
                                                                 f'manifests/parameters/{a.parameter_set}.yaml'],
        'outputs': [f'{qc_root}/{c}' for c in a.components],
        'qc': [f'{qc_root}/{c}' for c in a.components]}
    jobrecord.submit(text, stage_logs, job_name, 'workflow/03_parameters/domain/submit_adopted_qc.py',
                     'workflow/03_parameters/domain/adopted_qc.sbatch', commit, dirty, details)


if __name__ == '__main__':
    main()
