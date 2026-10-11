"""Extension of a forcing unit with years it does not yet contain (docs/directory-contracts.md, "Forcing unit and
provenance record").

A unit made of one file per year is never regenerated for new years. Its producer adds the files of the new years
and rewrites provenance.yaml, the only existing file that changes, when every condition of the contract holds:

  1. the producing code is unchanged (equal Git tree hashes of the producer's directory and workflow/common, or a
     chain of entries of manifests/code-equivalence.yaml from the recorded to the current hashes) and the method
     version is the recorded one;
  2. every input used again has the SHA-256 recorded in the unit, and every static input is recorded;
  3. the key software versions are the recorded ones;
  and the existing data files are present with their recorded SHA-256. A year the unit already contains is refused.

This module holds the rules that are the same for every producer: which years a unit has, the checks made before
anything is written, and how the new files enter the unit's record. What a year's data are, which inputs a year
needs, and the keys of the record beyond those of the contract stay in the producers.
"""
import os

from common import hashing, provenance

FILE_KEYS = ('path', 'year', 'size_bytes', 'sha256', 'created_at', 'code_commit')   # one entry per data file


def year_of(name):
    """Year of a data file of a yearly unit, taken from the end of its name: <...>_<year>.nc."""
    base = os.path.basename(name)
    try:
        if not base.endswith('.nc'):
            raise ValueError
        return int(base[:-3].rsplit('_', 1)[1])
    except (ValueError, IndexError):
        raise ValueError(f'{name}: the file name does not end in _<year>.nc') from None


def unit_years(prov):
    """Sorted years of the data files recorded in a provenance record (the `year` key, else the file name)."""
    return sorted(f['year'] if 'year' in f else year_of(f['path']) for f in prov.get('files') or [])


def years_span(years):
    """'first-last' of a list of years, None for an empty list."""
    years = sorted(years)
    return f'{years[0]}-{years[-1]}' if years else None


def existing(unit_dir):
    """The provenance record of the unit in `unit_dir`; None when the directory is absent or empty. Stops when the
    directory holds files but no provenance.yaml: an incomplete unit, which is left to the user."""
    prov_path = f'{unit_dir}/provenance.yaml'
    if os.path.exists(prov_path):
        return provenance.read(prov_path)
    if os.path.isdir(unit_dir) and os.listdir(unit_dir):
        raise SystemExit(f'{unit_dir} contains files but no provenance.yaml (incomplete unit); ask the user')
    return None


def check(prov, unit_dir, producer, method_version, code_tree, software, input_sha256, static_inputs):
    """Conditions of the contract for extending the unit recorded in `prov`; returns the list of violations (empty
    when the unit may be extended). `code_tree` and `software` are the current fingerprint parts, `input_sha256`
    the workdir-relative path -> SHA-256 of every input the new years use, `static_inputs` the paths among them
    that every year uses (domain, parameter files, reference datasets)."""
    bad = []
    fp = prov.get('fingerprint') or {}
    recorded_version = (prov.get('method') or {}).get('version')
    if recorded_version != method_version:
        bad.append(f'method version {recorded_version} != {method_version}')
    if provenance.code_equivalence(fp.get('code_tree'), code_tree, producer, method_version) is None:
        bad.append(f'code tree {fp.get("code_tree")} != {code_tree} and no entry of {provenance.EQUIVALENCE} connects them')
    if fp.get('software') != software:
        bad.append(f'software {fp.get("software")} != {software}')
    old = prov.get('input_sha256') or {}
    for p, sha in input_sha256.items():
        if p in old and old[p] != sha:
            bad.append(f'input {p} changed (sha256)')
    for p in static_inputs:
        if p not in old:
            bad.append(f'static input {p} not recorded in the unit')
    for f in prov.get('files') or []:
        path = f'{unit_dir}/{f["path"]}'
        if not os.path.exists(path):
            bad.append(f'{f["path"]} missing')
        elif hashing.sha256(path) != f['sha256']:
            bad.append(f'{f["path"]} sha256 differs from provenance')
    return bad


def prepare(unit_dir, unit, years, producer, method_version, code_tree, software, input_sha256, static_inputs):
    """Decide, before anything is written, how a producer may write `years` into the unit: None when the unit does
    not exist yet (a new unit), the existing provenance record when the unit may be extended. Stops with the reason
    when a requested year is already there or a condition of check() fails."""
    prov = existing(unit_dir)
    if prov is None:
        return None
    clash = sorted(set(unit_years(prov)) & set(years))
    if clash:
        raise SystemExit(f'{unit} already contains {clash}; an existing unit is never overwritten')
    bad = check(prov, unit_dir, producer, method_version, code_tree, software, input_sha256, static_inputs)
    if bad:
        raise SystemExit(f'{unit} cannot be extended:\n  ' + '\n  '.join(bad))
    return prov


def file_record(path, year, commit, created_at=None):
    """Entry of `files` for one written data file; size and SHA-256 are read from the file."""
    return {'path': os.path.basename(path), 'year': year, 'size_bytes': os.path.getsize(path),
            'sha256': hashing.sha256(path), 'created_at': created_at or provenance.utcnow(), 'code_commit': commit}


def extend(prev, new_files, input_sha256, code_tree, producer, method_version, commit, at, years, details=None):
    """The keys of provenance.yaml that an extension changes, for `prov.update()`: `files` (the existing entries
    unchanged, the new ones added, sorted by name), `inputs` and `input_sha256` (the union of the recorded and the
    new values), `years`, `qc` (status back to not_checked, evidence kept) and `extended` (the record's list with one
    more entry: time, commit, years, the code-equivalence chain when the code tree differs from the recorded one, and
    the producer's `details`, e.g. the source year of a copied year). code_commit and created_at of the record stay
    those of the original unit."""
    files = sorted(list(prev.get('files') or []) + [{k: r[k] for k in FILE_KEYS if k in r} for r in new_files],
                   key=lambda f: f['path'])
    sha = dict(prev.get('input_sha256') or {})
    sha.update(input_sha256)
    entry = {'at': at, 'code_commit': commit, 'years': list(years)}
    chain = provenance.code_equivalence((prev.get('fingerprint') or {}).get('code_tree'), code_tree, producer,
                                        method_version)
    if chain:
        entry['code_equivalence'] = chain
    if details:
        entry.update(details)
    return {'inputs': sorted(sha), 'input_sha256': dict(sorted(sha.items())), 'years': years_span(unit_years({'files': files})),
            'files': files, 'qc': {'status': 'not_checked', 'evidence': (prev.get('qc') or {}).get('evidence')},
            'extended': (prev.get('extended') or []) + [entry]}
