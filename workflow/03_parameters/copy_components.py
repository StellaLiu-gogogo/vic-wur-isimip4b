#!/usr/bin/env python3
"""Copy the unchanged components of one candidate parameter set into a new candidate set (contract, `parameters/`).

A new parameter set that differs from an existing one in a few components (task Z: vic-global-5arcmin-version-b
takes the soil, vegetation and bundle components anew and keeps domain, routing, irrigation, dams and water_use of
vic-global-5arcmin-version-a) gets the unchanged components as verified copies, never as links, so that the set is
complete on its own, can be promoted and keeps its own QC evidence. For every component named:

  1. the files are those of every entry of manifests/parameters/<from-set>.yaml whose component is the one named
     (its `files` and its `provenance` record; entries marked `promotion: excluded` included, so that the
     component is complete, e.g. the adopted decomposition file that the generated one records as an input);
  2. every file is checked against the manifest (md5, and sha256 and size where recorded) before it is copied;
  3. each file is copied with its modification time under a temporary name, checked (md5, sha256) against the
     source and renamed; a provenance.yaml is copied with every occurrence of the source set's id in its paths
     and commands replaced by the new set's id, its qc set to not_checked (the component is verified again in the
     new set) and a `copied_from` block that names the source record and its sha256;
  4. the record of the copy (every file with size, md5, sha256 and modification day; the local date of the copy,
     which the manifest of the new set records as adopted_on) is printed, so that it stays in the output of the
     job record (logs/03_parameters/copy-components-<set>_<slurm-job-id>/slurm-<id>.out), which the manifest names.

A component directory that exists and is not empty in the new set stops the copy. Outside scratch the repository
must be clean at the commit the job was submitted for (contract rule 14). The manifest of the new set is written by
hand from the record.

Usage: copy_components.py --parameter-set vic-global-5arcmin-version-b --from-set vic-global-5arcmin-version-a
       --components domain routing irrigation dams water_use [--scratch] [--expect-commit SHA]
"""
import argparse, datetime, os, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import gitstate, hashing, provenance, workdir   # noqa: E402

sys.path.insert(0, HERE)
import promote_parameter_set as pp   # noqa: E402  (manifest path, the verified copy)

SCRIPT = 'workflow/03_parameters/copy_components.py'
SCRATCH = 'scratch/copy-components'


class CopyError(ValueError):
    pass


def component_files(manifest, component):
    """[{path, entry, md5, sha256, size_bytes}] of every file of the manifest entries of `component` (each path
    once), and the provenance records among them."""
    files, seen, records = [], set(), []
    for key, comp in manifest['components'].items():
        if comp.get('component', key) != component:
            continue
        entries = [dict(f) for f in comp.get('files', [])]
        prov = comp.get('provenance')
        if prov and prov not in {f['path'] for f in entries}:
            entries.append({'path': prov})
        if prov:
            records.append(prov)
        for f in entries:
            if f['path'] in seen:
                continue
            if not f['path'].startswith(component + '/'):
                raise CopyError(f'entry {key}: {f["path"]} is not a file of component {component}')
            seen.add(f['path'])
            files.append({'path': f['path'], 'entry': key, 'md5': f.get('md5'), 'sha256': f.get('sha256'),
                          'size_bytes': f.get('size_bytes')})
    if not files:
        raise CopyError(f'the manifest has no files of component {component}')
    return files, sorted(set(records))


def replace_set_id(value, old, new):
    """Every occurrence of the source set's id in the strings of a record (keys and values, nested) replaced."""
    if isinstance(value, dict):
        return {replace_set_id(k, old, new): replace_set_id(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_set_id(v, old, new) for v in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def copied_provenance(src_path, src_rel, old, new, copied_at):
    """The provenance record of a copied component: paths and commands renamed to the new set, qc not_checked,
    and the block copied_from (src_rel: the workdir-relative path of the source record)."""
    rec = provenance.read(src_path)
    out = replace_set_id(rec, old, new)
    out['qc'] = {'status': 'not_checked'}
    out['copied_from'] = {'parameter_set': old, 'record': src_rel,
                          'record_sha256': hashing.sha256(src_path), 'copied_by': SCRIPT, 'copied_at': copied_at,
                          'note': 'the files are verified copies (md5, sha256) of the source set; the paths and commands '
                                  'of this record were renamed to the new set; qc is given anew in the new set'}
    return out


def copy_components(W, repo, new_set, from_set, components, target_root, commit, dirty):
    """Copy `components` of candidates/<from_set>/ into target_root/<new_set>/; returns the record."""
    with open(pp.manifest_path(repo, from_set)) as fh:
        manifest = yaml.safe_load(fh)
    src_root = os.path.join(W, 'parameters', 'candidates', from_set)
    dst_root = os.path.join(target_root, new_set)
    plan = {}
    for c in components:
        d = os.path.join(dst_root, c)
        if os.path.exists(d) and os.listdir(d):
            raise CopyError(f'{d} exists and is not empty; a component is replaced only with the user\'s authorization')
        plan[c] = component_files(manifest, c)
    copied_at = provenance.utcnow(); today = datetime.date.today().isoformat()
    record = {'parameter_set_id': new_set, 'copied_from': from_set, 'copied_at': copied_at, 'copied_on': today,
              'copied_by': SCRIPT, 'code_commit': commit, 'code_dirty': dirty,
              'manifest': {'path': os.path.relpath(pp.manifest_path(repo, from_set), repo),
                           'sha256': hashing.sha256(pp.manifest_path(repo, from_set))},
              'source': os.path.relpath(src_root, W), 'target': os.path.relpath(dst_root, W), 'components': {}}
    for c, (files, records) in plan.items():
        hashes = pp.check_sources(src_root, files)        # md5/sha256/size against the manifest, stops on a difference
        out = []
        for f in files:
            src, dst = os.path.join(src_root, f['path']), os.path.join(dst_root, f['path'])
            if f['path'] in records:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                provenance.write(dst, copied_provenance(src, os.path.relpath(src, W), from_set, new_set, copied_at))
                out.append({'path': f['path'], 'entry': f['entry'], 'record': 'renamed to the new set, qc not_checked',
                            'source_sha256': hashes[f['path']]['sha256'], 'sha256': hashing.sha256(dst)})
                continue
            pp.copy_verified(src, dst, hashes[f['path']])
            st = os.stat(dst)
            out.append({'path': f['path'], 'entry': f['entry'], **hashes[f['path']],
                        'mtime': datetime.date.fromtimestamp(st.st_mtime).isoformat()})
            print(f'copied {f["path"]} ({st.st_size} bytes, md5 {hashes[f["path"]]["md5"]})', flush=True)
        record['components'][c] = {'files': out, 'provenance_records': records}
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', required=True, help='the new candidate set')
    ap.add_argument('--from-set', required=True, help='the candidate set the components are copied from')
    ap.add_argument('--components', nargs='+', required=True)
    ap.add_argument('--scratch', action='store_true', help=f'test: copy into {SCRATCH}/candidates/')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script: stop unless the repository is clean at this commit')
    a = ap.parse_args(); W = workdir.root()
    if a.parameter_set == a.from_set:
        raise SystemExit('the new set must differ from the source set')
    commit, dirty = gitstate.state(REPO)
    if not a.scratch:
        if a.expect_commit is None:
            raise SystemExit('a copy outside scratch is started by submit_copy_components.py (--expect-commit)')
        if dirty or commit != a.expect_commit:
            raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the '
                             f'repository is now at {commit} and {"not clean" if dirty else "clean"}; submit again')
    root = os.path.join(W, SCRATCH, 'candidates') if a.scratch else os.path.join(W, 'parameters', 'candidates')
    try:
        record = copy_components(W, REPO, a.parameter_set, a.from_set, a.components, root, commit, dirty)
    except (CopyError, pp.PromoteError) as e:
        raise SystemExit(f'copy stopped: {e}')
    print('--- record of the copy (YAML) ---')
    print(yaml.safe_dump(record, sort_keys=False, width=110))
    print('--- end of the record ---')
    n = sum(len(c['files']) for c in record['components'].values())
    print(f'copied {n} files of {len(record["components"])} components into {record["target"]}')


if __name__ == '__main__':
    main()
