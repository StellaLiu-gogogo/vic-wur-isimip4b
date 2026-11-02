"""Unit tests for workflow/03_parameters/copy_components.py (file selection per component, verified copies, the
renamed provenance record) on a small synthetic candidate set.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import importlib.util, os, tempfile, unittest
from unittest import mock

import yaml

from common import hashing, provenance

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'copy_components.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('copy_components', SRC)
    cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)


def make_set(root, pset):
    cand = os.path.join(root, 'parameters', 'candidates', pset)
    files = {'domain/domain.nc': b'domain', 'routing/routing.nc': b'routing', 'routing/old_decomp.nc': b'old',
             'routing/decomp.nc': b'new', 'dams/dams.nc': b'dams'}
    for rel, content in files.items():
        p = os.path.join(cand, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(content)
    provenance.write(os.path.join(cand, 'routing', 'provenance.yaml'), {
        'object': f'parameters/candidates/{pset}/routing/decomp.nc',
        'inputs': {f'parameters/candidates/{pset}/routing/routing.nc': {'md5': hashing.md5(os.path.join(cand, 'routing/routing.nc')),
                                                                       'recorded_in': f'manifests/parameters/{pset}.yaml'}},
        'rebuild_command': f'python3 build.py --parameter-set {pset}', 'qc': {'status': 'passed', 'evidence': f'qc/parameters/candidates/{pset}/routing'}})

    def entry(path, **kw):
        p = os.path.join(cand, path)
        return {'path': path, 'size_bytes': os.path.getsize(p), 'md5': hashing.md5(p), **kw}
    manifest = {'parameter_set_id': pset, 'components': {
        'domain': {'files': [entry('domain/domain.nc')], 'qc_status': 'passed'},
        'routing': {'files': [entry('routing/routing.nc')], 'qc_status': 'passed'},
        'decomposition': {'component': 'routing', 'files': [entry('routing/old_decomp.nc')], 'qc_status': 'not_checked',
                          'promotion': 'excluded', 'promotion_reason': 'superseded'},
        'decomposition_isimip4b': {'component': 'routing', 'files': [entry('routing/decomp.nc', sha256=hashing.sha256(os.path.join(cand, 'routing/decomp.nc')))],
                                   'provenance': 'routing/provenance.yaml', 'qc_status': 'passed'},
        'dams': {'files': [entry('dams/dams.nc')], 'qc_status': 'passed'}}}
    repo = os.path.join(root, 'repo'); os.makedirs(os.path.join(repo, 'manifests', 'parameters'))
    with open(os.path.join(repo, 'manifests', 'parameters', f'{pset}.yaml'), 'w') as fh:
        yaml.safe_dump(manifest, fh)
    return cand, repo, manifest


class SelectionTest(unittest.TestCase):
    def test_component_files_include_excluded_entries_and_records(self):
        with tempfile.TemporaryDirectory() as t:
            _, _, manifest = make_set(t, 'set-a')
            files, records = cc.component_files(manifest, 'routing')
            self.assertEqual(sorted(f['path'] for f in files),
                             ['routing/decomp.nc', 'routing/old_decomp.nc', 'routing/provenance.yaml', 'routing/routing.nc'])
            self.assertEqual(records, ['routing/provenance.yaml'])
            with self.assertRaises(cc.CopyError):
                cc.component_files(manifest, 'water_use')

    def test_replace_set_id(self):
        rec = {'object': 'parameters/candidates/set-a/x', 'inputs': {'parameters/candidates/set-a/y': {'md5': 'm'}}, 'n': 3}
        out = cc.replace_set_id(rec, 'set-a', 'set-b')
        self.assertEqual(out['object'], 'parameters/candidates/set-b/x')
        self.assertIn('parameters/candidates/set-b/y', out['inputs']); self.assertEqual(out['n'], 3)


class CopyTest(unittest.TestCase):
    def test_copy_is_verified_and_record_renamed(self):
        with tempfile.TemporaryDirectory() as t:
            cand, repo, _ = make_set(t, 'set-a')
            root = os.path.join(t, 'parameters', 'candidates')
            rec = cc.copy_components(t, repo, 'set-b', 'set-a', ['routing', 'dams'], root, 'abc', False)
            dst = os.path.join(root, 'set-b')
            self.assertEqual(sorted(os.listdir(dst)), ['dams', 'routing'])
            for rel in ('routing/routing.nc', 'routing/old_decomp.nc', 'routing/decomp.nc', 'dams/dams.nc'):
                self.assertEqual(hashing.md5(os.path.join(dst, rel)), hashing.md5(os.path.join(cand, rel)))
                self.assertEqual(int(os.stat(os.path.join(dst, rel)).st_mtime), int(os.stat(os.path.join(cand, rel)).st_mtime))
            self.assertFalse(os.path.exists(os.path.join(dst, 'domain')))
            p = provenance.read(os.path.join(dst, 'routing', 'provenance.yaml'))
            self.assertEqual(p['object'], 'parameters/candidates/set-b/routing/decomp.nc')
            self.assertIn('parameters/candidates/set-b/routing/routing.nc', p['inputs'])
            self.assertEqual(p['qc'], {'status': 'not_checked'})
            self.assertEqual(p['copied_from']['parameter_set'], 'set-a')
            self.assertEqual(p['copied_from']['record_sha256'], hashing.sha256(os.path.join(cand, 'routing', 'provenance.yaml')))
            self.assertEqual(p['rebuild_command'], 'python3 build.py --parameter-set set-b')
            self.assertEqual(len(rec['components']['routing']['files']), 4); self.assertEqual(rec['copied_from'], 'set-a')
            # a second copy into the non-empty component stops
            with self.assertRaises(cc.CopyError):
                cc.copy_components(t, repo, 'set-b', 'set-a', ['dams'], root, 'abc', False)

    def test_manifest_mismatch_stops_before_copying(self):
        with tempfile.TemporaryDirectory() as t:
            cand, repo, _ = make_set(t, 'set-a')
            with open(os.path.join(cand, 'dams', 'dams.nc'), 'wb') as fh:
                fh.write(b'changed')
            root = os.path.join(t, 'parameters', 'candidates')
            with self.assertRaises(cc.pp.PromoteError):
                cc.copy_components(t, repo, 'set-b', 'set-a', ['dams'], root, 'abc', False)
            self.assertFalse(os.path.exists(os.path.join(root, 'set-b', 'dams', 'dams.nc')))


if __name__ == '__main__':
    unittest.main()
