"""Selection rules of a backup snapshot (D13, docs/directory-contracts.md "Data protection").

A snapshot mirrors the workdir and the repository working tree under the backup root with the same relative
paths. Everything is copied except what can be recomputed from raw data and code:

  excluded directories   raw/ and scratch/ at the workdir top level, and every directory named output/ at any
                         depth (model output of runs and chunks)
  excluded file types    the patterns of the .gitignore sections "Scientific data", "Logs and scheduler output",
                         "Build products" and "Python and notebook caches" (NetCDF and other data files, logs and
                         scheduler output, executables, caches); the patterns are read from the repository's
                         .gitignore so that the two lists cannot drift apart; the repository's own .git/ is left
                         out as well (the bare repository under the backup root holds the history)
  kept whatever the type parameters/production/ (promoted parameter sets: weeks of work), postprocessed/ and
                         delivery/ (products and deliveries until DKRZ holds them), and the states/ directories
                         (run level and every chunk) of an accepted production run: the manifest says
                         production and completed, and the run check or the convergence test has written
                         qc/runs/<campaign-id>/<run-id>/summary.json (hundreds of node hours per state)

Every selected file is reported under one category: workdir (text, metadata, provenance, job records),
states, parameter-sets, products, repo.
"""
import fnmatch
import json
import os

SECTIONS = ('Scientific data', 'Logs and scheduler output', 'Build products', 'Python and notebook caches')
EXCLUDED_TOP = ('raw', 'scratch')
EXCLUDED_DIR_NAMES = ('output',)
WHOLE_DIRS = {'parameters/production': 'parameter-sets', 'postprocessed': 'products', 'delivery': 'products'}
REPO_EXCLUDED_TOP = ('.git',)
CATEGORIES = ('workdir', 'states', 'parameter-sets', 'products', 'repo')


class RulesError(Exception):
    pass


def gitignore_patterns(path, sections=SECTIONS):
    """{section: [pattern, ...]} of the named .gitignore sections; a section starts with a comment line whose
    text begins with the section name and ends at the next blank line. Stops when a section is missing."""
    found = {}
    current = None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip('\n')
            if not line.strip():
                current = None
                continue
            if line.startswith('#'):
                text = line.lstrip('#').strip()
                hit = [s for s in sections if text.startswith(s)]
                current = hit[0] if hit else None
                if current is not None:
                    found.setdefault(current, [])
                continue
            if current is not None:
                found[current].append(line.strip())
    missing = [s for s in sections if s not in found or not found[s]]
    if missing:
        raise RulesError(f'{path}: .gitignore section(s) {missing} not found or empty')
    return found


class Rules:
    """File and directory name patterns of the excluded types (gitignore syntax restricted to basenames)."""

    def __init__(self, patterns):
        self.sections = patterns
        flat = [p for ps in patterns.values() for p in ps]
        self.dir_patterns = [p.rstrip('/') for p in flat if p.endswith('/')]
        self.file_patterns = [p for p in flat if not p.endswith('/')]

    @classmethod
    def from_gitignore(cls, path, sections=SECTIONS):
        return cls(gitignore_patterns(path, sections))

    def excluded_file(self, name):
        return any(fnmatch.fnmatchcase(name, p) for p in self.file_patterns)

    def excluded_dir(self, name):
        return any(fnmatch.fnmatchcase(name, p) for p in self.dir_patterns)


def accepted_runs(workdir):
    """Relative run directories (runs/<campaign-id>/<run-id>) of the accepted production runs, with the reason a
    run is not accepted for every other run that has a manifest: {run_dir: None | reason}."""
    out = {}
    base = os.path.join(workdir, 'runs')
    if not os.path.isdir(base):
        return out
    for campaign in sorted(os.listdir(base)):
        cdir = os.path.join(base, campaign)
        if not os.path.isdir(cdir):
            continue
        for run in sorted(os.listdir(cdir)):
            mpath = os.path.join(cdir, run, 'run_manifest.json')
            if not os.path.isfile(mpath):
                continue
            rel = f'runs/{campaign}/{run}'
            try:
                with open(mpath) as fh:
                    m = json.load(fh)
            except (OSError, ValueError) as e:
                out[rel] = f'manifest unreadable: {e}'
                continue
            if not m.get('production'):
                out[rel] = 'not a production run'
            elif m.get('status') != 'completed':
                out[rel] = f'status {m.get("status")}'
            elif not os.path.isfile(os.path.join(workdir, 'qc', rel, 'summary.json')):
                out[rel] = 'no run check or convergence test summary'
            else:
                out[rel] = None
    return out


def _states_dir(rel_dir, run_dir):
    """True for the states/ directory of the run or of one of its chunks."""
    inside = rel_dir[len(run_dir) + 1:]
    return inside == 'states' or (inside.startswith('chunks/') and inside.count('/') == 2 and
                                  inside.endswith('/states'))


def select(root, rules, kind, accepted=None):
    """Yield (relative path, size in bytes, category, is_symlink) of every file of `root` that the rules select.
    `kind` is 'workdir' or 'repo'; `accepted` are the accepted run directories (workdir only). Directories are
    walked without following symbolic links; a symbolic link is reported as a file of its own."""
    accepted = set(accepted or ())
    excluded_top = EXCLUDED_TOP if kind == 'workdir' else REPO_EXCLUDED_TOP
    for rel, size, link in _walk(root, '', rules, kind, excluded_top, accepted, None):
        yield rel, size, _category(rel, kind, accepted), link


def _category(rel, kind, accepted):
    if kind == 'repo':
        return 'repo'
    for top, cat in WHOLE_DIRS.items():
        if rel.startswith(top + '/'):
            return cat
    for run in accepted:
        if rel.startswith(run + '/') and _states_dir(os.path.dirname(rel), run):
            return 'states'
    return 'workdir'


def _whole(rel_dir, kind, accepted):
    """True when every file of this directory is kept whatever its type."""
    if kind != 'workdir':
        return False
    if any(rel_dir == top or rel_dir.startswith(top + '/') for top in WHOLE_DIRS):
        return True
    return any(rel_dir.startswith(run + '/') and
               (_states_dir(rel_dir, run) or any(_states_dir(p, run) for p in _parents(rel_dir, run)))
               for run in accepted)


def _parents(rel_dir, run_dir):
    p = os.path.dirname(rel_dir)
    while len(p) > len(run_dir):
        yield p
        p = os.path.dirname(p)


def _walk(root, rel_dir, rules, kind, excluded_top, accepted, _unused):
    path = os.path.join(root, rel_dir) if rel_dir else root
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return
    whole = _whole(rel_dir, kind, accepted) if rel_dir else False
    for e in entries:
        rel = f'{rel_dir}/{e.name}' if rel_dir else e.name
        if e.is_dir(follow_symlinks=False):
            if not rel_dir and e.name in excluded_top:
                continue
            if e.name in EXCLUDED_DIR_NAMES:
                continue
            if not whole and rules.excluded_dir(e.name):
                continue
            yield from _walk(root, rel, rules, kind, excluded_top, accepted, None)
        else:
            if not whole and rules.excluded_file(e.name):
                continue
            st = e.stat(follow_symlinks=False)
            yield rel, st.st_size, e.is_symlink()


def summarize(selection):
    """{category: {'files': n, 'bytes': b}} over the selection (any iterable of select() tuples)."""
    out = {c: {'files': 0, 'bytes': 0} for c in CATEGORIES}
    for rel, size, cat, link in selection:
        out[cat]['files'] += 1
        out[cat]['bytes'] += 0 if link else size
    return out
