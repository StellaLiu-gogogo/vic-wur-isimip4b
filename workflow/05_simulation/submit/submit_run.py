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
             config/job.attempt-<n>.sbatch and both are recorded in the manifest (job_files). With --dependency
             <job-id> the first job waits for that job (afterok), e.g. the retried parent. The run is reconciled
             with the scheduler first (below).
  --reconcile  <campaign-id or run directory>: compare every attempt still 'submitted' or 'running' with sacct
             (run_manifest.reconcile): ended jobs (time limit, scancel, node failure: the completion step never ran)
             get status timeout, cancelled or failed with the final scheduler rows and a reason; jobs waiting on a
             dependency that can never be met are cancelled and recorded; running or normally waiting jobs are left
             alone. Every attempt that ended without completing is written to the campaign's recovery ledger
             runs/<campaign-id>/recovery.json (run, chunk, years, job, state, reason, the jobs cancelled after it,
             the command that resumes it).
  --resume   <campaign-id>: reconcile the campaign, then resubmit every stranded run (an attempt that ended
             without completing, no attempt running) from its first incomplete chunk, parents first, each waiting
             for its parent's job when the parent has not completed (its running job, or the job resubmitted in
             the same call); the ledger records the new attempt of every entry it resumed. (Review 2026-11-01, R2.)

A chunked run (resources chunk_years, render_run.py) is submitted as one job per chunk, each waiting for the
previous one (afterok), with a check of each chunk and, after the last chunk and the chunk checks, the check of the
whole run; --retry resubmits from the first chunk whose latest attempt did not complete (with --rerender-job, the job
files of those chunks are rendered again).

The job verifies the input checksums before VIC starts and completes the manifest after VIC ends
(run_manifest.py). After each run job a check job is submitted that starts when the run has succeeded
(monitor/check_run.py: checks, derived per-sector withdrawal file, figures, GRDC comparison); --no-check
skips it. Scratch renders (render_run.py --scratch) are never submitted by this script.

Usage: submit_run.py --campaign configs/campaigns/smoke.yaml [--label smoke2015] [--run-id ID] [--dry-run]
       submit_run.py --retry runs/<campaign-id>/<run-id> [--rerender-job] [--dependency <job-id>]
       submit_run.py --reconcile <campaign-id or run directory>
       submit_run.py --resume <campaign-id>
"""
import argparse, datetime, glob, hashlib, json, os, subprocess, sys

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


def submit(run_dir, dependency=None, chunk=None):
    """Submit the run, or one chunk of a chunked run; returns the Slurm job id."""
    with rm.run_lock(run_dir):          # one submission of a run at a time: check, submit, record, release
        m = rm.load(run_dir)
        c = rm.chunk(m, chunk)
        if any(a['status'] in ('submitted', 'running') for a in m['attempts'] if a.get('chunk') == chunk):
            raise SystemExit(f'{run_dir}' + (f' chunk {chunk}' if chunk else '') + ': an attempt is still submitted '
                             'or running')
        for rel, digest in m['rendered_files'].items():
            with open(os.path.join(run_dir, rel)) as fh:
                if hashlib.sha256(fh.read().encode()).hexdigest() != digest:
                    raise SystemExit(f'{run_dir}/{rel} differs from the rendered file; a changed run needs a new render')
        if rm.inputs_fingerprint(m) != m['inputs_fingerprint']:
            raise SystemExit(f'{run_dir}: inputs fingerprint changed; a retry must have identical inputs')
        # a job whose dependency can never be met is cancelled by Slurm instead of waiting forever (R2, R18: Anunna
        # has DependencyParameters null, so a dependent of a failed job would stay pending)
        cmd = ['sbatch', '--parsable', '--hold'] + \
            ([f'--dependency=afterok:{dependency}', '--kill-on-invalid-dep=yes'] if dependency else [])
        r = subprocess.run(cmd + [os.path.join(run_dir, c['job_file'] if c else rm.JOB_FILE)], capture_output=True,
                           text=True)
        if r.returncode != 0:
            raise SystemExit(f'sbatch failed: {r.stderr}')
        job_id = r.stdout.strip().split(';')[0]
        try:
            commit, dirty = rr.git_state()
            m['attempts'].append({'attempt': len(m['attempts']) + 1, 'slurm_job_id': int(job_id),
                                  'submitted_at': utcnow(), 'submitted_by_commit': commit, 'code_dirty': dirty,
                                  'dependency': dependency, 'inputs_fingerprint': m['inputs_fingerprint'],
                                  'status': 'submitted', **({'chunk': chunk} if chunk else {})})
            m['status'] = rm.run_status(m)
            rm.save(run_dir, m)
        except BaseException as e:         # the held job is never released without its attempt (R15: any error)
            subprocess.run(['scancel', job_id])
            raise SystemExit(f'{e!r}; job {job_id} cancelled') from e
        subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {m["run_id"]}' + (f' chunk {chunk}' if chunk else '') +
          f' as job {job_id} (attempt {len(m["attempts"])})')
    return job_id


def submit_run(run_dir, dependency=None, check=True, from_chunk=0):
    """Submit a run (with its check), or the chunks of a chunked run from index from_chunk on, each waiting for the
    previous one, with a check per chunk and the check of the whole run after the last chunk. Returns the job id of
    the run or of its last chunk (what a child run waits for). A spin-up gets the convergence test of D19
    (monitor/check_spinup.py) after its last job instead of the run checks: it writes only the monthly convergence
    variables, not the daily and monthly outputs monitor/check_run.py reads."""
    m = rm.load(run_dir)
    if str(m.get('segment_id') or '').endswith('_spinup'):
        job = dependency
        for c in (m.get('chunks') or [{'id': None}])[from_chunk:]:
            job = submit(run_dir, job, chunk=c['id'])
        if check:
            sc.submit(run_dir, dependency=job, spinup=True)
        return job
    chunks = m.get('chunks') or []
    if not chunks:
        job = submit(run_dir, dependency)
        if check:
            sc.submit(run_dir, dependency=job)
        return job
    job = dependency; chunk_checks = []
    for c in chunks[from_chunk:]:
        job = submit(run_dir, job, chunk=c['id'])
        if check:
            chunk_checks.append(sc.submit(run_dir, dependency=job, chunk=c['id']))
    if check:          # the whole-run check reads the status of every chunk check: it waits for them to end
        sc.submit(run_dir, dependency=job, after_checks=chunk_checks)
    return job


def rerender_job(run_dir, W, from_chunk=0):
    """Render the job file again from the current template and resources (the run's config/job.sbatch, or the job
    files of the chunks from index from_chunk on); keep the previous files."""
    m = rm.load(run_dir)
    for rel, digest in m['rendered_files'].items():
        if rm.is_job_file(rel):
            continue
        with open(os.path.join(run_dir, rel)) as fh:
            if hashlib.sha256(fh.read().encode()).hexdigest() != digest:
                raise SystemExit(f'{run_dir}/{rel} differs from the rendered file; a changed run needs a new render')
    first = (m.get('chunks') or [{'dir': '.'}])[0]['dir']
    with open(os.path.join(run_dir, first, 'config', 'resolved.yaml')) as fh:
        res = yaml.safe_load(fh)
    resources = rr.run_resources(res, rr.read_yaml(os.path.join(rr.REPO, res['resources_file'])))
    # the checks of a new render that depend on the resources (render_run.py check_build and check_tasks)
    if [str(x) for x in resources['modules']] != list(res['model']['runtime_modules']):
        raise SystemExit(f'resources modules {resources["modules"]} differ from the build runtime_modules '
                         f'{res["model"]["runtime_modules"]}')
    try:
        rr.check_tasks(resources['ntasks'], dict(res['decomposition']))
    except rr.RenderError as e:
        raise SystemExit(f'{run_dir}: {e}')
    commit, dirty = rr.git_state()
    chunks = m.get('chunks') or []
    pieces = [(None, res['start_year'], res['end_year'], rm.JOB_FILE)] if not chunks else \
        [(c['id'], c['start_year'], c['end_year'], c['job_file']) for c in chunks[from_chunk:]]
    for cid, y0, y1, rel in pieces:
        text, hours = rr.render_job(W, run_dir, res['campaign_id'], res['run_id'], y0, y1, resources, res['model'],
                                    chunk_dir=os.path.join(run_dir, os.path.dirname(os.path.dirname(rel))) if cid
                                    else None, chunk=cid)
        old = os.path.join(run_dir, rel)
        keep = os.path.join(os.path.dirname(old), f'job.attempt-{len(m["attempts"])}.sbatch')
        if os.path.exists(keep):
            raise SystemExit(f'{keep} exists')
        os.rename(old, keep)
        with open(old, 'w') as fh:
            fh.write(text)
        m.setdefault('job_files', []).append({
            'kept_as': os.path.relpath(keep, run_dir), 'sha256': m['rendered_files'][rel], **({'chunk': cid} if cid else {}),
            'replaced_at': utcnow(), 'replaced_by_commit': commit, 'code_dirty': dirty,
            'resources': {k: resources[k] for k in ('ntasks', 'cpus_per_task', 'mem', 'launcher')},
            'wall_time_hours': hours})
        m['rendered_files'][rel] = rr.text_sha256(text)
        print(f'rendered a new job file for {m["run_id"]}' + (f' chunk {cid}' if cid else '') +
              f'; previous kept as {os.path.relpath(keep, run_dir)}')
    m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
    rm.save(run_dir, m)


# ------------------------------------------------------------------------------------------- recovery (R2)
LEDGER = 'recovery.json'
LEDGER_SCHEMA = 'isimip4b-recovery-ledger-1'


def campaign_dir(W, campaign_id):
    return os.path.join(W, 'runs', campaign_id)


def campaign_runs(W, campaign_id):
    """Run directories of a campaign that have a manifest, sorted by name."""
    return sorted(os.path.dirname(p) for p in glob.glob(os.path.join(campaign_dir(W, campaign_id), '*', rm.NAME)))


def ledger_path(W, campaign_id):
    return os.path.join(campaign_dir(W, campaign_id), LEDGER)


def load_ledger(W, campaign_id):
    p = ledger_path(W, campaign_id)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {'schema': LEDGER_SCHEMA, 'campaign_id': campaign_id, 'updated_at': None, 'entries': []}


def save_ledger(W, campaign_id, ledger):
    """Write the ledger atomically (temp file and rename)."""
    ledger['updated_at'] = utcnow()
    os.makedirs(campaign_dir(W, campaign_id), exist_ok=True)
    p = ledger_path(W, campaign_id); tmp = p + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(ledger, fh, indent=1); fh.write('\n')
    os.replace(tmp, p)


def ledger_entry(W, run_dir, m, a):
    """Ledger entry of one attempt that ended without completing."""
    c = rm.chunk(m, a.get('chunk')) if a.get('chunk') else None
    period = m.get('period') or {}
    years = [c['start_year'], c['end_year']] if c else \
        ([int(period['start'][:4]), int(period['end'][:4])] if period else None)
    rel = os.path.relpath(run_dir, W)
    rec = a.get('reconciled') or {}
    row = rm.job_row(a.get('scheduler') or [], a['slurm_job_id'])
    return {'run_id': m['run_id'], 'run_dir': rel, 'chunk': a.get('chunk'), 'years': years,
            'attempt': a['attempt'], 'slurm_job_id': a['slurm_job_id'], 'status': a['status'],
            'state': rec.get('state') or row.get('State'), 'reason': a.get('failure_reason'),
            'ended': rec.get('end') or row.get('End') or a.get('ended_at'),
            'elapsed': rec.get('elapsed') or row.get('Elapsed'), 'nodes': rec.get('nodes') or row.get('NodeList'),
            'downstream_cancelled': [], 'recorded_at': utcnow(),
            'resume_command': f'submit_run.py --retry {rel} [--dependency <job of the parent run when it has not '
                              f'completed>], or submit_run.py --resume {os.path.basename(os.path.dirname(rel))}',
            'resumed_by': None}


def update_ledger(W, campaign_id, run_dirs):
    """Reconcile the runs and record in the campaign's ledger every attempt that ended without completing (one entry
    per job id; entries are kept, their status and resumption are updated). Returns (ledger, changed attempts)."""
    ledger = load_ledger(W, campaign_id)
    by_job = {e['slurm_job_id']: e for e in ledger['entries']}
    changed = []
    for rd in run_dirs:
        for rec in rm.reconcile(rd):
            changed.append({'run_dir': os.path.relpath(rd, W), **rec})
            print(f'{os.path.relpath(rd, W)}' + (f' chunk {rec["chunk"]}' if rec['chunk'] else '') +
                  f' attempt {rec["attempt"]} job {rec["slurm_job_id"]}: {rec["state"]} -> {rec["status"]} ({rec["reason"]})')
        # the final scheduler rows of attempts the job itself recorded (a TERM, a VIC error): the check job that would
        # store them was cancelled with the chain (R16)
        rm.record_scheduler(rd, [a['slurm_job_id'] for a in rm.load(rd)['attempts'] if a['status'] in rm.ENDED_BADLY])
        m = rm.load(rd)
        for a in m['attempts']:
            if a['status'] in rm.ENDED_BADLY:
                e = by_job.get(a['slurm_job_id'])
                if e is None:
                    e = ledger_entry(W, rd, m, a); ledger['entries'].append(e); by_job[e['slurm_job_id']] = e
                else:
                    e.update({k: v for k, v in ledger_entry(W, rd, m, a).items()
                              if k in ('status', 'state', 'reason', 'ended', 'elapsed', 'nodes')})
                later = [b for b in m['attempts'] if b.get('chunk') == a.get('chunk') and b['attempt'] > a['attempt']]
                if later and e.get('resumed_by') is None:
                    e['resumed_by'] = {'attempt': later[0]['attempt'], 'slurm_job_id': later[0]['slurm_job_id']}
    # a cancelled dependent is "downstream" of the failed job it waited for (over every run of the campaign)
    for rd in run_dirs:
        for a in rm.load(rd)['attempts']:
            if a['status'] == 'cancelled' and a.get('dependency') and int(a['dependency']) in by_job:
                e = by_job[int(a['dependency'])]
                if a['slurm_job_id'] not in e['downstream_cancelled']:
                    e['downstream_cancelled'].append(a['slurm_job_id'])
    save_ledger(W, campaign_id, ledger)
    return ledger, changed


def reconcile_target(W, target):
    """(campaign id, run directories) of a --reconcile target: a campaign id, or one run directory."""
    p = os.path.abspath(target if os.path.isabs(target) else os.path.join(W, target))
    if os.path.isfile(os.path.join(p, rm.NAME)):
        return os.path.basename(os.path.dirname(p)), [p]
    if os.path.isdir(campaign_dir(W, target)):
        return target, campaign_runs(W, target)
    raise SystemExit(f'{target}: neither a campaign under runs/ nor a run directory')


def parent_run_dir(W, m):
    """Run directory of the run a manifest starts from (its parent run, or the previous spin-up block), None for a
    cold start or a warm start from another campaign."""
    p = m.get('parent') or {}
    if not p.get('init_state'):
        return None
    rd = os.path.join(W, p['init_state'])
    while rd != W and not os.path.isfile(os.path.join(rd, rm.NAME)):
        rd = os.path.dirname(rd)
    return rd if rd != W else None


def live_job(m):
    """Job id the next run has to wait for: the latest attempt of the run (of its last chunk) when it is submitted
    or running, else None."""
    chunks = m.get('chunks') or []
    last = rm.latest_attempt(m, chunks[-1]['id'] if chunks else None)
    return str(last['slurm_job_id']) if last.get('status') in ('submitted', 'running') else None


def stranded(m):
    """A run whose latest attempt of some chunk ended without completing and that has no attempt running."""
    if rm.is_completed(m) or not m['attempts']:
        return False
    if any(a['status'] in ('submitted', 'running') for a in m['attempts']):
        return False
    chunk_ids = [c['id'] for c in m.get('chunks') or []] or [None]
    return any(rm.latest_attempt(m, c).get('status') in rm.ENDED_BADLY for c in chunk_ids)


def resume(W, campaign_id, check=True):
    """Reconcile the campaign and resubmit every stranded run from its first incomplete chunk, parents first, each
    waiting for its parent's job when the parent has not completed. Returns {run_dir: job id} of the resubmissions."""
    run_dirs = campaign_runs(W, campaign_id)
    ledger, _ = update_ledger(W, campaign_id, run_dirs)
    manifests = {rd: rm.load(rd) for rd in run_dirs}
    todo = [rd for rd in run_dirs if stranded(manifests[rd])]
    # parents first: a run whose parent is also resubmitted waits for the parent's new job
    order = []
    while todo:
        ready = [rd for rd in todo if parent_run_dir(W, manifests[rd]) not in todo]
        if not ready:
            raise SystemExit(f'the parent relations of {todo} form a cycle')
        order += ready; todo = [rd for rd in todo if rd not in ready]
    jobs = {}
    for rd in order:
        m = manifests[rd]
        prd = parent_run_dir(W, m)
        dep = None
        if prd and not rm.is_completed(rm.load(prd)):
            dep = jobs.get(prd) or live_job(rm.load(prd))
            if dep is None:
                print(f'{os.path.relpath(rd, W)}: not resumed, its parent {os.path.relpath(prd, W)} has not '
                      'completed and has no job to wait for')
                continue
        start = rm.first_incomplete_chunk(m) or 0
        jobs[rd] = submit_run(rd, dependency=dep, check=check, from_chunk=start)
        m2 = rm.load(rd); chunks = m2.get('chunks') or []
        new = rm.latest_attempt(m2, chunks[start]['id'] if chunks else None)
        for e in ledger['entries']:
            if e['run_dir'] == os.path.relpath(rd, W) and e.get('resumed_by') is None and \
                    e['chunk'] == new.get('chunk'):
                e['resumed_by'] = {'attempt': new['attempt'], 'slurm_job_id': new['slurm_job_id'],
                                   'dependency': dep, 'at': utcnow()}
    save_ledger(W, campaign_id, ledger)
    for rd in run_dirs:
        m = manifests[rd]
        if not m['attempts'] and not rm.is_completed(m):
            print(f'{os.path.relpath(rd, W)}: rendered but never submitted; submit it with --retry')
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign')
    ap.add_argument('--label', default=None)
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--retry', default=None, help='run directory to resubmit')
    ap.add_argument('--rerender-job', action='store_true', help='with --retry: render the Slurm job file again')
    ap.add_argument('--dependency', default=None, help='with --retry: job the first job waits for (afterok)')
    ap.add_argument('--reconcile', default=None, help='campaign id or run directory to reconcile with sacct')
    ap.add_argument('--resume', default=None, help='campaign id: reconcile and resubmit every stranded run')
    ap.add_argument('--no-check', action='store_true', help='do not submit the run check after each run')
    ap.add_argument('--dry-run', action='store_true', help='resolve and list the runs only')
    a = ap.parse_args()
    W = rc.workdir()
    if a.reconcile:
        campaign_id, run_dirs = reconcile_target(W, a.reconcile)
        ledger, changed = update_ledger(W, campaign_id, run_dirs)
        open_entries = [e for e in ledger['entries'] if e.get('resumed_by') is None]
        print(f'{len(changed)} attempt(s) changed; {len(open_entries)} entr{"y" if len(open_entries) == 1 else "ies"} '
              f'of the ledger not resumed yet ({os.path.relpath(ledger_path(W, campaign_id), W)})')
        for e in open_entries:
            print(f'  {e["run_dir"]}' + (f' chunk {e["chunk"]}' if e['chunk'] else '') + f' job {e["slurm_job_id"]}: '
                  f'{e["status"]} ({e["reason"]}); {e["resume_command"]}')
        return
    if a.resume:
        if not os.path.isdir(campaign_dir(W, a.resume)):
            raise SystemExit(f'no campaign {a.resume} under runs/')
        jobs = resume(W, a.resume, check=not a.no_check)
        print(f'resumed {len(jobs)} run(s)')
        return
    if a.retry:
        run_dir = os.path.abspath(a.retry if os.path.isabs(a.retry) else os.path.join(W, a.retry))
        if not run_dir.startswith(os.path.join(W, 'runs') + os.sep):
            raise SystemExit('only run directories under runs/ are submitted')
        update_ledger(W, os.path.basename(os.path.dirname(run_dir)), [run_dir])     # reconcile first (R2)
        m = rm.load(run_dir)
        if rm.is_completed(m):
            raise SystemExit(f'{run_dir}: the run completed; nothing to retry')
        if m.get('production') and rr.git_state()[1]:     # R5: the render rule holds for every attempt of the run
            raise SystemExit(f'{run_dir}: a production run is retried only from a clean repository '
                             '(docs/directory-contracts.md, rule 14); commit first')
        if any(a['status'] in ('submitted', 'running') for a in m['attempts']):
            raise SystemExit(f'{run_dir}: an attempt is still submitted or running')
        start = rm.first_incomplete_chunk(m) or 0
        if a.rerender_job:
            rerender_job(run_dir, W, start)
        submit_run(run_dir, dependency=a.dependency, check=not a.no_check, from_chunk=start)
        return
    if not a.campaign:
        raise SystemExit('give --campaign, --retry, --reconcile or --resume')
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
    for d in dirs:      # the renderer may leave runs out or render the next spin-up block: follow what it rendered
        m = rm.load(d)
        parent = (m.get('parent') or {}).get('segment_id')
        # the check jobs start only when their run (chunk) job has completed successfully
        jobs[m['segment_id']] = submit_run(d, dependency=jobs.get(parent), check=not a.no_check)


if __name__ == '__main__':
    main()
