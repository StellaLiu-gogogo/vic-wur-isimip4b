"""provenance.yaml of forcing units and parameter components: writing, qc.status, the code fingerprint, and the
code-equivalence record (docs/directory-contracts.md, "Forcing unit and provenance record").

The fingerprint block records what must stay unchanged for a unit to be extended with more years: the Git tree
hashes of the producing code, the method version, and the key software versions. A change of the producing code
that leaves every result unchanged is recorded in manifests/code-equivalence.yaml; code_equivalence() follows
those entries from a recorded tree to the current one.
"""
import datetime
import os
import platform

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
EQUIVALENCE = 'manifests/code-equivalence.yaml'


def utcnow():
    """UTC time in the ISO 8601 form used by every provenance record, e.g. 2026-10-05T09:12:00Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def write(path, record):
    """Write a record completely under a temporary name, then rename it into place (never a partial file)."""
    with open(path + '.part', 'w') as fh:
        yaml.safe_dump(record, fh, sort_keys=False)
    os.replace(path + '.part', path)


def set_qc(path, status, evidence):
    """Set qc (status, evidence) of an existing provenance.yaml; only quality-control code calls this."""
    prov = read(path)
    prov['qc'] = {'status': status, 'evidence': evidence}
    write(path, prov)


def software_versions():
    """Versions of the key software that determine the bytes of the NetCDF output."""
    import numpy as np
    import netCDF4 as nc
    return {'python': platform.python_version(), 'numpy': np.__version__, 'netCDF4': nc.__version__,
            'netcdf_c': nc.__netcdf4libversion__, 'hdf5': nc.__hdf5libversion__, 'pyyaml': yaml.__version__}


def fingerprint(code_tree, method_version, software):
    """The fingerprint block of provenance.yaml."""
    return {'code_tree': code_tree, 'method_version': method_version, 'software': software,
            'conda_env': os.environ.get('CONDA_DEFAULT_ENV')}


def load_equivalences(path=None):
    p = path or os.path.join(REPO, EQUIVALENCE)
    if not os.path.exists(p):
        return []
    return read(p).get('equivalences') or []


def code_equivalence(recorded, current, producer, method_version, entries=None):
    """Entry ids that lead from the `recorded` code-tree hashes to the `current` ones for `producer` with an
    unchanged `method_version`: [] when both are equal, None when no chain of entries connects them."""
    if recorded == current:
        return []
    entries = [e for e in (load_equivalences() if entries is None else entries)
               if e.get('producer') == producer and str(e.get('method_version')) == str(method_version)]
    chain, state, seen = [], recorded, []
    while state != current:
        nxt = [e for e in entries if e.get('from') == state and e.get('id') not in seen]
        if len(nxt) != 1:          # no entry, or an ambiguous record: not equivalent
            return None
        chain.append(nxt[0]['id']); seen.append(nxt[0]['id']); state = nxt[0].get('to')
    return chain
