#!/usr/bin/env python3
"""Submit VIC-WUR runs of a campaign: render the run directories, submit each job on hold, record the attempt
in the run manifest, then release the job.

  new runs   render_run.py renders runs/<campaign-id>/<run-id>/ (an existing directory stops it), then each
             run's config/job.sbatch is submitted with --hold; the attempt (scheduler job id, time, inputs
             fingerprint) is written to run_manifest.json before the job is released, so the job always finds
             its attempt. A run whose parent run is submitted in the same call waits for it (afterok).
  --retry    resubmit an existing run directory whose last attempt did not complete: the rendered files must
             be unchanged (sha256 recorded at rendering) and the inputs fingerprint equal, so the retry is a new
             attempt of the same run (docs/glossary.md, "Run"). Nothing is rendered again.

The job verifies the input checksums before VIC starts and completes the manifest after VIC ends
(run_manifest.py). Scratch renders (render_run.py --scratch) are never submitted by this script.

Usage: submit_run.py --campaign configs/campaigns/smoke.yaml [--label smoke2015] [--run-id ID] [--dry-run]
       submit_run.py --retry runs/<campaign-id>/<run-id>
"""
import argparse, datetime, hashlib, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'render'))
import run_manifest as rm      # noqa: E402
import render_run as rr        # noqa: E402
import resolve_campaign as rc  # noqa: E402


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def submit(run_dir, dependency=None):
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
    rm.save(run_dir, m)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {m["run_id"]} as job {job_id} (attempt {len(m["attempts"])})')
    return job_id


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign')
    ap.add_argument('--label', default=None)
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--retry', default=None, help='run directory to resubmit')
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
        submit(run_dir); return
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


if __name__ == '__main__':
    main()
