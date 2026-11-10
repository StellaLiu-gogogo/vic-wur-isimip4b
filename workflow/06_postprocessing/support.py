"""Infrastructure of stage 06_postprocessing: workdir, Git state, checksums, records, QC statuses, job records.

The stage is self-contained (user, 2026-11-10, task AD): it may later be published on its own, so it imports no
module of workflow/common or of another stage. This module therefore holds its own copy of the few rules it needs
from the project infrastructure, with the same behaviour:

- the workdir is found only through ISIMIP4B_WORKDIR;
- a repository is clean when `git status --porcelain` prints nothing (docs/glossary.md); accepted products are made
  only from a clean repository (contract rule 14);
- QC statuses passed / warning / failed / not_checked, combined with the worst first, and the exit status of a check
  (passed 0, failed 1, warning 3, not_checked 4);
- every Slurm job keeps its rendered script and its scheduler output in logs/06_postprocessing/<job-name>_<job-id>/
  (contract, `logs/`): the job is submitted on hold, the record is written, then the job is released.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys

import yaml

STAGE = '06_postprocessing'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
CONFIG = os.path.join(HERE, 'products.yaml')
WORKDIR_ENV = 'ISIMIP4B_WORKDIR'

STATUSES = ('passed', 'warning', 'failed', 'not_checked')
EXIT_CODES = {'passed': 0, 'failed': 1, 'warning': 3, 'not_checked': 4}


# ------------------------------------------------------------------------------------------------ workdir, time
def workdir():
    """Absolute path of the workdir; stops with a message when ISIMIP4B_WORKDIR is not set."""
    w = os.environ.get(WORKDIR_ENV)
    if not w:
        sys.exit(f'set {WORKDIR_ENV}')
    return os.path.abspath(w)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------------------------------------ Git
def git(*args, repo=REPO):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)


def git_state(repo=REPO):
    """{'commit', 'branch', 'dirty'} of the repository; stops if git fails."""
    out = {}
    for key, args in (('commit', ('rev-parse', 'HEAD')), ('branch', ('rev-parse', '--abbrev-ref', 'HEAD')),
                      ('status', ('status', '--porcelain'))):
        r = git(*args, repo=repo)
        if r.returncode != 0:
            raise SystemExit(f'git {" ".join(args)} failed in {repo}: {r.stderr.strip()}')
        out[key] = r.stdout.strip()
    return {'commit': out['commit'], 'branch': out['branch'], 'dirty': bool(out['status'])}


def check_expected_commit(expected, repo=REPO):
    """Stop unless the repository is clean and at `expected` (a job started from the submitted commit)."""
    s = git_state(repo)
    if s['dirty'] or s['commit'] != expected:
        raise SystemExit(f'repository is not clean at {expected} (now {s["commit"]}, dirty {s["dirty"]}); '
                         'nothing is written')
    return s


# ------------------------------------------------------------------------------------------------ files
def sha256(path, block=1 << 24):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(block), b''):
            h.update(b)
    return h.hexdigest()


def write_text(path, text):
    """Write a file completely under a temporary name, then rename it into place (never a partial file)."""
    with open(path + '.part', 'w') as fh:
        fh.write(text)
    os.replace(path + '.part', path)


def write_json(path, record):
    write_text(path, json.dumps(record, indent=1) + '\n')


def write_yaml(path, record):
    write_text(path, yaml.safe_dump(record, sort_keys=False))


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------------------------------------ configuration
def config():
    """The product configuration products.yaml of this stage."""
    return load_yaml(CONFIG)


def campaign(path):
    """The campaign file (configs/campaigns/<id>.yaml, relative to the repository or absolute) and its sha256."""
    p = path if os.path.isabs(path) else os.path.join(REPO, path)
    return load_yaml(p), sha256(p), os.path.relpath(p, REPO)


def parameter_files(camp, W):
    """{role: workdir-relative path} of the campaign's parameter set (production or candidate status)."""
    ps = camp['parameter_set']
    base = f'parameters/{ps["status"] if ps["status"] == "production" else "candidates"}/{ps["id"]}'
    files = {k: f'{base}/{v}' for k, v in ps['files'].items() if isinstance(v, str)}
    for k, v in files.items():
        if not os.path.exists(os.path.join(W, v)):
            raise SystemExit(f'{v} ({k}) does not exist')
    return files


def protocol_variables(camp, W):
    """{variable: definition} of the protocol commit pinned by the campaign (definitions/variable/*.yaml)."""
    d = os.path.join(W, camp['protocol']['path'], 'definitions', 'variable')
    out = {}
    for f in sorted(os.listdir(d)):
        if f.endswith('.yaml'):
            for v in load_yaml(os.path.join(d, f)) or []:
                out[v['specifier']] = v
    return out


def for_sector(value, sector='water_global'):
    """A protocol field that may be given per sector ({'other': ..., <sector>: ...}) as the value of `sector`."""
    if isinstance(value, dict):
        return value.get(sector, value.get('other'))
    return value


def output_root(W, scratch_task):
    """Root under which postprocessed/ and qc/ are written: the workdir, or scratch/<task>/ for a scratch run."""
    return W if not scratch_task else os.path.join(W, 'scratch', scratch_task)


# ------------------------------------------------------------------------------------------------ QC
def combine(statuses):
    """Worst status: failed, then not_checked, then warning; passed otherwise (also for no parts)."""
    s = list(statuses)
    for x in s:
        if x not in STATUSES:
            raise ValueError(f'unknown QC status {x}')
    for status in ('failed', 'not_checked', 'warning'):
        if status in s:
            return status
    return 'passed'


def exit_with(status):
    sys.exit(EXIT_CODES[status])


# ------------------------------------------------------------------------------------------------ job records
def conda_base():
    r = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True)
    return r.stdout.strip() or os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))


def render(template, values):
    """Text of the template with every {{NAME}} replaced; stops if a placeholder is left."""
    with open(template) as fh:
        text = fh.read()
    for k, v in values.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    return text


def submit(text, W, job_name, template, state, details):
    """Submit `text` on hold, write job.sbatch and job.yaml in logs/06_postprocessing/<job-name>_<job-id>/, release
    the job. Returns (job ID, job record directory)."""
    stage_logs = os.path.join(W, 'logs', STAGE)
    os.makedirs(stage_logs, exist_ok=True)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{stage_logs}/{job_name}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    write_text(f'{job_dir}/job.sbatch', text)
    record = {'slurm_job_id': int(job_id), 'job_name': job_name, 'rendered_by': os.path.relpath(sys.argv[0], REPO),
              'template': os.path.relpath(template, REPO), 'code_commit': state['commit'],
              'code_branch': state['branch'], 'code_dirty': state['dirty'], 'submitted_at': utcnow(), **details}
    write_yaml(f'{job_dir}/job.yaml', record)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')
    return job_id, job_dir
