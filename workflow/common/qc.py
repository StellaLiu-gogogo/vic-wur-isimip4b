"""Quality-control results: status vocabulary, combined status, summary.json, binding of per-file reports, and the
exit status of a verifier (docs/directory-contracts.md, "Status vocabulary" and `qc/`).

Exit status of a verifier (so that a Slurm job ends FAILED unless the object is accepted):
  passed 0, failed 1, warning 3, not_checked 4.
A warning is not an acceptance (an object is accepted only with qc.status passed), so it does not end with 0;
3 and 4 are kept apart from 2, which Python uses for command-line errors.

Binding: a per-file report counts only for the data files and the verifier code it was written for. Each report
records the SHA-256 of its data files and the verifier's commit, Git state and code-tree hashes; report_status()
treats a report as not_checked when a data file has changed, or, for a report of an earlier run, when the
verifier code differs or either run came from a repository that is not clean (the tree hashes then do not
describe the code that ran).
"""
import json
import os
import sys

from common import gitstate, hashing

STATUSES = ('passed', 'warning', 'failed', 'not_checked')
EXIT_CODES = {'passed': 0, 'failed': 1, 'warning': 3, 'not_checked': 4}


def combine(statuses):
    """Status of an object from the statuses of its parts: failed if any part failed, not_checked if any part is
    not checked (or missing), warning if any part has a warning, passed otherwise (also for no parts)."""
    s = ['not_checked' if x == 'missing' else x for x in statuses]
    for x in s:
        if x not in STATUSES:
            raise ValueError(f'unknown QC status {x}')
    for status in ('failed', 'not_checked', 'warning'):
        if status in s:
            return status
    return 'passed'


def write_json(path, record):
    with open(path + '.part', 'w') as fh:
        json.dump(record, fh, indent=1)
    os.replace(path + '.part', path)


def write_summary(qc_dir, summary):
    """<qc_dir>/summary.json."""
    write_json(f'{qc_dir}/summary.json', summary)


def exit_with(status):
    """End the verifier with the exit status of `status` (see above)."""
    sys.exit(EXIT_CODES[status])


def verifier_state(repo, verifier_dir):
    """Version of the verifier code: commit, Git state, tree hashes of its directory and workflow/common."""
    commit, dirty = gitstate.state(repo)
    return {'verifier_commit': commit, 'verifier_dirty': dirty,
            'verifier_code_tree': gitstate.tree_hashes(repo, [verifier_dir, 'workflow/common'])}


def binding(data_files, verifier):
    """Binding block of a per-file report: SHA-256 of each data file (by file name) and the verifier version."""
    return {'data_sha256': {os.path.basename(p): hashing.sha256(p) for p in sorted(data_files)}, **verifier}


def report_status(report_path, data_files, verifier, this_run=False):
    """Status of a per-file report, or not_checked when there is none or it does not belong to the current data
    files and verifier. `this_run` marks reports written by the current run, whose verifier version is the
    current one by construction."""
    if not os.path.exists(report_path):
        return 'not_checked'
    with open(report_path) as fh:
        rep = json.load(fh)
    b = rep.get('binding') or {}
    if b.get('data_sha256') != {os.path.basename(p): hashing.sha256(p) for p in sorted(data_files)}:
        return 'not_checked'
    if not this_run and (b.get('verifier_dirty') is not False or verifier['verifier_dirty']
                         or b.get('verifier_code_tree') != verifier['verifier_code_tree']):
        return 'not_checked'
    return rep.get('status', 'not_checked')
