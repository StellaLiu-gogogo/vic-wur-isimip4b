#!/usr/bin/env python3
"""Submit the Slurm jobs of stage 06_postprocessing (postprocessing.sbatch) with their job records
logs/06_postprocessing/<job-name>_<slurm-job-id>/.

  static  static_fields.py, then check_static.py, for the product set of a campaign

From a clean repository the job runs with --expect-commit <HEAD>, so it stops when the repository has changed by the
time it starts. A repository that is not clean is accepted only with --scratch <task-id> (outputs below
scratch/<task-id>/, contract rule 14).

Usage: submit.py static --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [--time 02:00:00] [--mem 32G]
       [--partition main] [--dry-run]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import support   # noqa: E402

TEMPLATE = os.path.join(HERE, 'postprocessing.sbatch')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=['static'])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--time', default='02:00:00')
    ap.add_argument('--mem', default='32G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='render and print the job without submitting')
    a = ap.parse_args()
    W = support.workdir(); state = support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean; commit first or use --scratch <task-id>')
    camp, _, camp_rel = support.campaign(a.campaign)
    pset = camp['campaign_id']
    args = f'--campaign {camp_rel}' + (f' --scratch {a.scratch}' if a.scratch else '') + \
        ('' if state['dirty'] else f' --expect-commit {state["commit"]}')
    job_name = f'static-files-{pset}' + ('-scratch' if a.scratch else '')
    text = support.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': '1', 'MEM': a.mem,
        'STAGE_LOGS': os.path.join(W, 'logs', support.STAGE), 'CONDA_BASE': support.conda_base(), 'WORKDIR': W,
        'REPO': support.REPO, 'PRODUCER': f'static_fields.py {args}', 'CHECK': f'check_static.py {args}'})
    if a.dry_run:
        print(text); return
    root = os.path.relpath(support.output_root(W, a.scratch), W)
    out = os.path.normpath(f'{root}/postprocessed/{pset}/static')
    qc = os.path.normpath(f'{root}/qc/postprocessed/{pset}/static')
    support.submit(text, W, job_name, TEMPLATE, state, {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': [f'python3 workflow/06_postprocessing/static_fields.py {args}',
                     f'python3 workflow/06_postprocessing/check_static.py {args}'],
        'inputs': [camp_rel, 'workflow/06_postprocessing/products.yaml'],
        'outputs': [out], 'qc': [qc]})


if __name__ == '__main__':
    main()
