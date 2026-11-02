#!/usr/bin/env python3
"""Render check_run.sbatch for one run directory, submit it, and create the job record
logs/05_simulation/<job-name>_<slurm-job-id>/ (job.sbatch, job.yaml, scheduler output).

For a chunked run, --chunk ID checks one chunk (its years and end state); without --chunk the check of a chunked run
covers the whole run (GRDC comparison of all years, every chunk check passed).

With --spinup it submits the convergence test of a spin-up block (check_spinup.py, D19) instead.

The wall time of a run check grows with the years it reads (review 2026-11-01, R4; measured: 6.8 min per year for a
chunk check with water use, production-config-check 2026-10-31; about 1 min per year for the whole-run check of the
172-year natural run, 2:49 h): a chunk check (or the check of an unchunked run) gets 1 h + 15 min per year, the
whole-run check of a chunked run 1 h + 2 min per year, never below 4 h; --time overrides it. The convergence test
of a spin-up block keeps 4 h.

Usage: submit_check.py --run-dir runs/<campaign-id>/<run-id> [--chunk ID] [--time HH:MM:SS] [--mem 64G]
       [--partition main] [--dependency <slurm-job-id>]   (start only when that job has completed successfully)
       submit_check.py --spinup --run-dir runs/<campaign-id>/<run-id> [--dependency <slurm-job-id>]
"""
import argparse, json, math, os, sys

from common import gitstate, jobrecord

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'check_run.sbatch')
SPINUP_TEMPLATE = os.path.join(HERE, 'check_spinup.sbatch')
SPINUP_TIME = '04:00:00'
MIN_HOURS = 4
HOURS = {'chunk': (1.0, 15 / 60), 'run': (1.0, 2 / 60)}      # (setup hours, hours per year)


def check_years(manifest, chunk=None):
    """Years the check reads: those of the chunk, or of the whole run."""
    if chunk:
        c = next(c for c in manifest.get('chunks') or [] if c['id'] == chunk)
        return c['end_year'] - c['start_year'] + 1
    return int(manifest['period']['end'][:4]) - int(manifest['period']['start'][:4]) + 1


def check_time(manifest, chunk=None):
    """Wall time 'HH:00:00' of a run check: a chunk check (and the check of an unchunked run) reads every output file
    of its years (HOURS['chunk']); the whole-run check of a chunked run reads the monthly and daily discharge only
    (HOURS['run']); at least MIN_HOURS."""
    kind = 'run' if (manifest.get('chunks') and not chunk) else 'chunk'
    setup, per_year = HOURS[kind]
    hours = max(MIN_HOURS, math.ceil(setup + per_year * check_years(manifest, chunk)))
    return f'{hours:02d}:00:00'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--time', default=None, help='wall time; by default scaled with the years of the check')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--partition', default='main')
    ap.add_argument('--dependency', default=None)
    ap.add_argument('--chunk', default=None)
    ap.add_argument('--spinup', action='store_true', help='the convergence test of a spin-up block (check_spinup.py)')
    a = ap.parse_args()
    submit(a.run_dir, a.time, a.mem, a.partition, a.dependency, a.chunk, a.spinup)


def job_name(rd):
    """run-check-<campaign>-<label> for a labelled run, run-check-<campaign>-<run-id with hyphens> for a production
    run, so that the checks of the runs of one campaign never share a job name."""
    run_id = os.path.basename(rd)
    label = run_id.split('__')[1] if '__' in run_id else run_id.replace('_', '-')
    return f'run-check-{os.path.basename(os.path.dirname(rd))}-{label}'


def submit(run_dir, time=None, mem='64G', partition='main', dependency=None, chunk=None, spinup=False,
           after_checks=()):
    """Render, submit on hold, write the job record, release; returns the job id. The check starts when the job
    `dependency` has succeeded and every job of `after_checks` has ended (the chunk checks that the check of a whole
    chunked run reads). Without `time` the wall time follows check_time() (SPINUP_TIME for the convergence test)."""
    W = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
    rd = os.path.abspath(run_dir if os.path.isabs(run_dir) else os.path.join(W, run_dir))
    rel = os.path.relpath(rd, W)
    if spinup and chunk:
        raise SystemExit('the convergence test covers the whole spin-up block, not one chunk')
    if time is None:
        if spinup:
            time = SPINUP_TIME
        else:
            with open(os.path.join(rd, 'run_manifest.json')) as fh:
                time = check_time(json.load(fh), chunk)
    name = (job_name(rd).replace('run-check-', 'spinup-check-', 1) if spinup else job_name(rd)) + \
        (f'-chunk-{chunk}' if chunk else '')
    commit, dirty = gitstate.state(REPO)
    stage_logs = f'{W}/logs/05_simulation'
    after = ([f'afterok:{dependency}'] if dependency else []) + \
        ([f'afterany:{":".join(after_checks)}'] if after_checks else [])
    # the dependency is an #SBATCH line of the job file, so that the record shows it; a job whose dependency can
    # never be met is cancelled by Slurm instead of waiting forever (R2, R18: Anunna has DependencyParameters null)
    dep_lines = [f'#SBATCH --dependency={",".join(after)}', '#SBATCH --kill-on-invalid-dep=yes'] if after else []
    template = SPINUP_TEMPLATE if spinup else TEMPLATE
    text = jobrecord.render(template, {
        'JOB_NAME': name, 'PARTITION': partition, 'TIME': time, 'MEM': mem, 'STAGE_LOGS': stage_logs,
        'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W, 'REPO': REPO, 'RUN_DIR': rd,
        'DEPENDENCY_LINES': '\n'.join(dep_lines), 'CHECK_OPTIONS': f' --chunk {chunk}' if chunk else ''})
    job_id, _ = jobrecord.submit(text, stage_logs, name, 'workflow/05_simulation/monitor/submit_check.py',
                                 os.path.relpath(template, REPO), commit, dirty, {
                                     'resources': {'partition': partition, 'time': time, 'cpus_per_task': 1, 'mem': mem},
                                     'dependency': dependency,
                                     **({'after_checks': list(after_checks)} if after_checks else {}),
                                     'inputs': [rel], 'outputs': [f'qc/{rel}' + (f'/chunks/{chunk}' if chunk else '')],
                                     **({'chunk': chunk} if chunk else {})})
    return job_id


if __name__ == '__main__':
    main()
