"""Slurm jobs of the non-simulation stages: render a template, submit it, keep the job record
logs/<stage>/<job-name>_<slurm-job-id>/{job.sbatch,job.yaml} (docs/directory-contracts.md, `logs/`).

The job is submitted on hold, the record is written, and only then is the job released, so that a job never runs
without its record. The job template moves the scheduler output into the record when the job starts.
"""
import os
import subprocess

import yaml

from common import provenance


def conda_base():
    """Root of the conda installation, for `source <base>/etc/profile.d/conda.sh` in the job."""
    return subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))


def render(template, values):
    """Text of the template with every {{NAME}} replaced; stops if a placeholder is left."""
    with open(template) as fh:
        text = fh.read()
    for k, v in values.items():
        text = text.replace('{{' + k + '}}', v)
    if '{{' in text:
        raise SystemExit('unrendered placeholder in the job template')
    return text


def submit(text, stage_logs, job_name, rendered_by, template, code_commit, code_dirty, details):
    """Submit `text` on hold, write job.sbatch and job.yaml, release the job. `details` holds the stage-specific
    keys of job.yaml (resources, commands, inputs, outputs, qc), written after the common ones.
    Returns (Slurm job ID, job record directory)."""
    os.makedirs(stage_logs, exist_ok=True)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{stage_logs}/{job_name}_{job_id}'
    os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    record = {'slurm_job_id': int(job_id), 'job_name': job_name, 'rendered_by': rendered_by, 'template': template,
              'code_commit': code_commit, 'code_dirty': code_dirty, 'submitted_at': provenance.utcnow(), **details}
    with open(f'{job_dir}/job.yaml', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}')
    return job_id, job_dir
