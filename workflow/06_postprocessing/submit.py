#!/usr/bin/env python3
"""Submit the Slurm jobs of stage 06_postprocessing (postprocessing.sbatch: a producer, then its check) with their job
records logs/06_postprocessing/<job-name>_<slurm-job-id>/.

  static   static_fields.py, then check_static.py, for the product set of a campaign
  unit     make_unit.py, then check_unit.py, one job per product unit whose source is ready: of the expected units of
           the campaign (product_set.py; or only those of --run and --chunk) the ones not made yet, without a
           staging directory of an interrupted job and without an active job, whose run chunk has completed with a
           passed chunk check bound to its latest attempt (outside --scratch; with --scratch the latest attempt must
           have completed). Outside --scratch the static files of the set must have passed their check. At most
           --max-jobs product-unit jobs are queued or running at the same time (all product sets together), so that
           they do not slow down the VIC jobs writing to the same file system; the others wait for a later call
  collect  collect_set.py, then check_set.py: product-set.yaml and checksums.sha256 of the product set

From a clean repository the job runs with --expect-commit <HEAD>, so it stops when the repository has changed by the
time it starts. A repository that is not clean is accepted only with --scratch <task-id> (outputs below
scratch/<task-id>/, contract rule 14). --dry-run lists what would be submitted and prints the first job script.

Usage: submit.py static  --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [resources] [--dry-run]
       submit.py unit    --campaign configs/campaigns/<id>.yaml [--run <run-id> [--chunk <start>-<end>]]
                         [--max-jobs 4] [--scratch <task-id>] [resources] [--dry-run]
       submit.py collect --campaign configs/campaigns/<id>.yaml [--scratch <task-id>] [resources] [--dry-run]
       resources: [--time HH:MM:SS] [--mem 32G] [--partition main]
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import product_set   # noqa: E402
import support       # noqa: E402

TEMPLATE = os.path.join(HERE, 'postprocessing.sbatch')
SCRIPT = 'workflow/06_postprocessing'
# default resources per step (one core each). unit from the scratch test of task AD (AD6, 2026-11-11, 10 years with
# daily soilmoist, production runs writing at the same time): producer 8.7 min per model year and 16.5 GB, check 7 min
# and 9.5 GB, so about 4 h for a 25-year chunk; twice that time, and memory for a check that keeps more months
RESOURCES = {'static': ('02:00:00', '32G'), 'unit': ('08:00:00', '40G'), 'collect': ('01:00:00', '8G')}
UNIT_JOB = 'product-unit-'
MAX_JOBS = 4


def job_text(W, a, job_name, producer, check):
    return support.render(TEMPLATE, {
        'JOB_NAME': job_name, 'PARTITION': a.partition, 'TIME': a.time, 'CPUS': '1', 'MEM': a.mem,
        'STAGE_LOGS': os.path.join(W, 'logs', support.STAGE), 'CONDA_BASE': support.conda_base(), 'WORKDIR': W,
        'REPO': support.REPO, 'PRODUCER': producer, 'CHECK': check})


def submit_one(W, a, state, job_name, producer, check, inputs, outputs, qc):
    text = job_text(W, a, job_name, producer, check)
    return support.submit(text, W, job_name, TEMPLATE, state, {
        'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
        'commands': [f'python3 {SCRIPT}/{producer}', f'python3 {SCRIPT}/{check}'],
        'inputs': inputs, 'outputs': outputs, 'qc': qc})


def active_unit_jobs(W):
    """{slurm job ID: unit path relative to the workdir or None} of the user's queued and running product-unit jobs,
    the unit read from the job record."""
    r = subprocess.run(['squeue', '-u', os.environ.get('USER', ''), '-h', '-o', '%i|%j'], capture_output=True,
                       text=True)
    if r.returncode != 0:
        raise SystemExit(f'squeue failed: {r.stderr.strip()}')
    out = {}
    for line in r.stdout.split():
        job_id, name = line.split('|', 1)
        if name.startswith(UNIT_JOB):
            rec = os.path.join(W, 'logs', support.STAGE, f'{name}_{job_id}', 'job.yaml')
            out[job_id] = (support.load_yaml(rec).get('outputs') or [None])[0] if os.path.exists(rec) else None
    return out


def unit_job_name(run, unit, scratch):
    """Job name of a product unit: lower-case letters, digits and hyphens (job records <job-name>_<job-id>)."""
    y0, y1 = unit['years']
    return f'{UNIT_JOB}{run["gcm"]}-{run["segment_key"].replace("_", "-")}-{y0}-{y1}' + ('-scratch' if scratch else '')


def ready_units(W, camp, a, active):
    """[(run, unit, reason or None)] of the units of the campaign selected by --run and --chunk; reason None means
    ready to be made. `active`: the units of active jobs (active_unit_jobs)."""
    set_dir, _ = product_set.set_paths(W, camp, a.scratch)
    runs = product_set.expected_runs(camp, W)
    if a.run:
        runs = [r for r in runs if r['run_id'] == a.run]
        if not runs:
            raise SystemExit(f'{a.run} is not a reported run of the campaign')
    out = []
    for run in runs:
        man = product_set.run_manifest(W, camp, run)
        for unit in run['units']:
            if a.chunk and unit['chunk'] != a.chunk:
                continue
            y0, y1 = unit['years']
            target = os.path.join(set_dir, product_set.unit_rel(run, unit))
            staging = os.path.join(set_dir, run['gcm'], run['segment_key'], f'.writing-{y0}-{y1}')
            if os.path.exists(target):
                reason = 'made'
            elif os.path.exists(staging):
                reason = 'staging directory of an interrupted job (the user decides on its deletion)'
            elif os.path.relpath(target, W) in active:
                reason = 'job active'
            elif man is None:
                reason = 'run not rendered'
            else:
                attempt, _, problems = product_set.source_state(W, man, unit['chunk'])
                if attempt.get('status') != 'completed':
                    reason = f'latest attempt {attempt.get("status")}'
                elif problems and not a.scratch:
                    reason = 'source not accepted: ' + '; '.join(problems)
                else:
                    reason = None
            out.append((run, unit, reason))
    return out


def step_unit(W, a, state, camp, camp_rel, args_common):
    set_dir, qc_dir = product_set.set_paths(W, camp, a.scratch)
    if not os.path.isdir(os.path.join(set_dir, 'static')):
        raise SystemExit(f'{set_dir}/static does not exist: submit the static step first')
    if not a.scratch:
        sq = os.path.join(qc_dir, 'static', 'summary.json')
        status = support.load_yaml(sq).get('status') if os.path.exists(sq) else 'not_checked'
        if status != 'passed':
            raise SystemExit(f'the static files of the set have check status {status}; units need passed')
    active = active_unit_jobs(W)
    units = ready_units(W, camp, a, set(active.values()))
    free = max(0, a.max_jobs - len(active))
    todo = [(r, u) for r, u, why in units if why is None]
    print(f'{len(units)} units selected, {len(todo)} ready, {free} job slots free (--max-jobs {a.max_jobs})')
    for r, u, why in units:
        if why is not None:
            print(f'  {product_set.unit_rel(r, u):60s} {why}')
    for i, (run, unit) in enumerate(todo):
        rel = product_set.unit_rel(run, unit)
        if i >= free:
            print(f'  {rel:60s} ready, waiting for a job slot')
            continue
        args = f'{args_common} --run {run["run_id"]}' + (f' --chunk {unit["chunk"]}' if unit['chunk'] else '')
        job_name = unit_job_name(run, unit, a.scratch)
        if a.dry_run:
            print(f'  {rel:60s} would be submitted as {job_name}')
            if i == 0:
                print(job_text(W, a, job_name, f'make_unit.py {args}', f'check_unit.py {args}'))
            continue
        rd = f'runs/{camp["campaign_id"]}/{run["run_id"]}'
        submit_one(W, a, state, job_name, f'make_unit.py {args}', f'check_unit.py {args}',
                   [camp_rel, f'{SCRIPT}/products.yaml', f'{rd}/run_manifest.json',
                    f'{rd}/chunks/{unit["chunk"]}/output' if unit['chunk'] else f'{rd}/output'],
                   [os.path.relpath(os.path.join(set_dir, rel), W)], [os.path.relpath(os.path.join(qc_dir, rel), W)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=list(RESOURCES))
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--run', help='unit step: only this run')
    ap.add_argument('--chunk', help='unit step: only this chunk of --run')
    ap.add_argument('--max-jobs', type=int, default=MAX_JOBS, help='unit step: product-unit jobs at the same time')
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--time')
    ap.add_argument('--mem')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dry-run', action='store_true', help='list and print without submitting')
    a = ap.parse_args()
    a.time = a.time or RESOURCES[a.step][0]
    a.mem = a.mem or RESOURCES[a.step][1]
    if a.chunk and not a.run:
        raise SystemExit('--chunk needs --run')
    W = support.workdir(); state = support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean; commit first or use --scratch <task-id>')
    camp, _, camp_rel = support.campaign(a.campaign)
    pset = camp['campaign_id']
    args = f'--campaign {camp_rel}' + (f' --scratch {a.scratch}' if a.scratch else '') + \
        ('' if state['dirty'] else f' --expect-commit {state["commit"]}')
    set_dir, qc_dir = product_set.set_paths(W, camp, a.scratch)
    set_rel, qc_rel = os.path.relpath(set_dir, W), os.path.relpath(qc_dir, W)
    suffix = '-scratch' if a.scratch else ''
    if a.step == 'unit':
        return step_unit(W, a, state, camp, camp_rel, args)
    if a.step == 'static':
        job_name = f'static-files-{pset}{suffix}'
        producer, check = f'static_fields.py {args}', f'check_static.py {args}'
        io = ([camp_rel, f'{SCRIPT}/products.yaml'], [f'{set_rel}/static'], [f'{qc_rel}/static'])
    else:
        job_name, producer, check = f'product-set-{pset}{suffix}', f'collect_set.py {args}', f'check_set.py {args}'
        io = ([camp_rel, f'{SCRIPT}/products.yaml'],
              [f'{set_rel}/{collect_set_file}' for collect_set_file in ('product-set.yaml', 'checksums.sha256')],
              [qc_rel])
    if a.dry_run:
        print(job_text(W, a, job_name, producer, check)); return
    submit_one(W, a, state, job_name, producer, check, *io)


if __name__ == '__main__':
    main()
