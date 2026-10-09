#!/usr/bin/env python3
"""Submit VIC-WUR runs of a campaign: render the run directories, submit each job on hold, record the attempt
in the run manifest, then release the job.

  new runs   render_run.py renders runs/<campaign-id>/<run-id>/ (an existing directory stops it), then each
             run's config/job.sbatch is submitted with --hold; the attempt (scheduler job id, time, inputs
             fingerprint) is written to run_manifest.json before the job is released, so the job always finds
             its attempt; the run directory is locked from the check to the release, so a second submission of
             the same run stops. A run whose parent run is submitted in the same call waits for it (afterok).
  --retry    resubmit an existing run directory whose last attempt did not complete: the rendered files must
             be unchanged (sha256 recorded at rendering) and the inputs fingerprint equal, so the retry is a new
             attempt of the same run (docs/glossary.md, "Run"). Nothing is rendered again, except with
             --rerender-job: only the Slurm job file is rendered again from the current template and resources
             (a change of how the run is executed, not of what is simulated); the previous job file is kept as
             config/job.attempt-<n>.sbatch and both are recorded in the manifest (job_files).

The job verifies the input checksums before VIC starts and completes the manifest after VIC ends
(run_manifest.py). After each run job a check job is submitted that starts when the run has succeeded
(monitor/check_run.py: checks, derived per-sector withdrawal file, figures, GRDC comparison); --no-check
skips it. Scratch renders (render_run.py --scratch) are never submitted by this script.

Usage: submit_run.py --campaign configs/campaigns/smoke.yaml [--label smoke2015] [--run-id ID] [--dry-run]
       submit_run.py --retry runs/<campaign-id>/<run-id> [--rerender-job]
"""
import argparse, datetime, hashlib, os, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'render'))
sys.path.insert(0, os.path.join(HERE, '..', 'monitor'))
import run_manifest as rm      # noqa: E402
import submit_check as sc      # noqa: E402
import render_run as rr        # noqa: E402
import resolve_campaign as rc  # noqa: E402


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def submit(run_dir, dependency=None):
    with rm.run_lock(run_dir):          # one submission of a run at a time: check, submit, record, release
        m = rm.load(run_dir)
        if any(a['status'] in ('submitted', 'running') for a in m['attempts']):
            raise SystemExit(f'{run_dir}: an attempt is still submitted or running')
        for rel, digest in m['rendered_files'].items():
            with open(os.path.join(run_dir, rel)) as fh:
                if hashlib.sha256(fh.read().encode()).hexdigest() != digest:
                    raise SystemExit(f'{run_dir}/{rel} differs from the rendered file; a changed run needs a new render')
        if rm.inputs_fingerprint(m) != m['inputs_fingerprint']:
            raise SystemExit(f'{run_dir}: inputs fingerprint changed; a retry must have identical inputs')
        cmd = ['sbatch', '--parsable', '--hold'] + ([f'--dependency=afterok:{dependency}'] if dependency else [])
        r = subprocess.run(cmd + [os.path.join(run_dir, 'config', 'job.sbatch')], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f'sbatch failed: {r.stderr}')
        job_id = r.stdout.strip().split(';')[0]
        commit, dirty = rr.git_state()
        m['attempts'].append({'attempt': len(m['attempts']) + 1, 'slurm_job_id': int(job_id), 'submitted_at': utcnow(),
                              'submitted_by_commit': commit, 'code_dirty': dirty, 'dependency': dependency,
                              'inputs_fingerprint': m['inputs_fingerprint'], 'status': 'submitted'})
        m['status'] = 'submitted'
        try:
            rm.save(run_dir, m)
        except rm.ManifestConflict as e:   # the held job is never released without its attempt
            subprocess.run(['scancel', job_id])
            raise SystemExit(f'{e}; job {job_id} cancelled')
        subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {m["run_id"]} as job {job_id} (attempt {len(m["attempts"])})')
    return job_id


def rerender_job(run_dir, W):
    """Render config/job.sbatch again from the current template and resources; keep the previous file."""
    m = rm.load(run_dir)
    for rel, digest in m['rendered_files'].items():
        if rel == rm.JOB_FILE:
            continue
        with open(os.path.join(run_dir, rel)) as fh:
            if hashlib.sha256(fh.read().encode()).hexdigest() != digest:
                raise SystemExit(f'{run_dir}/{rel} differs from the rendered file; a changed run needs a new render')
    with open(os.path.join(run_dir, 'config', 'resolved.yaml')) as fh:
        res = yaml.safe_load(fh)
    resources = rr.read_yaml(os.path.join(rr.REPO, res['resources_file']))
    # the checks of a new render that depend on the resources (render_run.py check_build and check_tasks)
    if [str(x) for x in resources['modules']] != list(res['model']['runtime_modules']):
        raise SystemExit(f'resources modules {resources["modules"]} differ from the build runtime_modules '
                         f'{res["model"]["runtime_modules"]}')
    try:
        rr.check_tasks(resources['ntasks'], dict(res['decomposition']))
    except rr.RenderError as e:
        raise SystemExit(f'{run_dir}: {e}')
    text, hours = rr.render_job(W, run_dir, res['campaign_id'], res['run_id'], res['start_year'], res['end_year'],
                                resources, res['model'])
    old = os.path.join(run_dir, rm.JOB_FILE)
    keep = os.path.join(run_dir, 'config', f'job.attempt-{len(m["attempts"])}.sbatch')
    if os.path.exists(keep):
        raise SystemExit(f'{keep} exists')
    os.rename(old, keep)
    with open(old, 'w') as fh:
        fh.write(text)
    commit, dirty = rr.git_state()
    m.setdefault('job_files', []).append({
        'kept_as': os.path.relpath(keep, run_dir), 'sha256': m['rendered_files'][rm.JOB_FILE],
        'replaced_at': utcnow(), 'replaced_by_commit': commit, 'code_dirty': dirty,
        'resources': {k: resources[k] for k in ('ntasks', 'cpus_per_task', 'mem', 'launcher')}, 'wall_time_hours': hours})
    m['rendered_files'][rm.JOB_FILE] = rr.text_sha256(text)
    m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
    rm.save(run_dir, m)
    print(f'rendered a new job file for {m["run_id"]}; previous kept as {os.path.relpath(keep, run_dir)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign')
    ap.add_argument('--label', default=None)
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--retry', default=None, help='run directory to resubmit')
    ap.add_argument('--rerender-job', action='store_true', help='with --retry: render the Slurm job file again')
    ap.add_argument('--no-check', action='store_true', help='do not submit the run check after each run')
    ap.add_argument('--dry-run', action='store_true', help='resolve and list the runs only')
    a = ap.parse_args()
    W = rc.workdir()
    if a.retry:
        run_dir = os.path.abspath(a.retry if os.path.isabs(a.retry) else os.path.join(W, a.retry))
        if not run_dir.startswith(os.path.join(W, 'runs') + os.sep):
            raise SystemExit('only run directories under runs/ are submitted')
        m = rm.load(run_dir)
        if m['attempts'] and m['attempts'][-1]['status'] == 'completed':
            raise SystemExit(f'{run_dir}: the last attempt completed; nothing to retry')
        if any(a['status'] in ('submitted', 'running') for a in m['attempts']):
            raise SystemExit(f'{run_dir}: an attempt is still submitted or running')
        if a.rerender_job:
            rerender_job(run_dir, W)
        job = submit(run_dir)
        if not a.no_check:
            sc.submit(run_dir, dependency=job)
        return
    if not a.campaign:
        raise SystemExit('give --campaign or --retry')
    c = rc.load_campaign(a.campaign)
    segs, _ = rc.resolve(c, os.path.join(W, c['protocol']['path']))
    todo = rc.runs(c, segs, a.label)
    if a.run_id:
        todo = [r for r in todo if r['run_id'] == a.run_id]
    if a.dry_run:
        for r in todo:
            print(r['run_id'], r['start_year'], r['end_year'], 'parent', r['segment']['parent'])
        return
    try:
        dirs = rr.render(a.campaign, a.label, a.run_id, scratch=False, W=W)
    except (rr.RenderError, rc.CampaignError) as e:
        raise SystemExit(f'render stopped: {e}')
    jobs = {}
    for r, d in zip(todo, dirs):
        parent = r['segment']['parent']
        jobs[r['segment_id']] = submit(d, dependency=jobs.get(parent))
        if not a.no_check:   # the check job starts only when the run job has completed successfully
            sc.submit(d, dependency=jobs[r['segment_id']])


if __name__ == '__main__':
    main()
