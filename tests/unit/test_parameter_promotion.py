"""Unit tests for workflow/03_parameters/promote_parameter_set.py and verify_parameter_promotion.py on a small
synthetic parameter set: file selection (excluded entries, QC status), checks against the manifest, restriction
attributes, refusal to overwrite, and the verification of the promoted copy.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import importlib.util, json, os, sys, tempfile, unittest
from unittest import mock

import netCDF4 as nc
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, '..', '..', 'workflow', '03_parameters')
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow'))


def load(name):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
        spec = importlib.util.spec_from_file_location(name, os.path.join(P, f'{name}.py'))
        m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m


pp = load('promote_parameter_set')
vp = load('verify_parameter_promotion')
SET = 'test-set'


class Fixture:
    """workdir W with parameters/candidates/test-set/ and qc evidence, repo R with the manifest."""

    def __init__(self, d, restricted=False):
        self.W = os.path.join(d, 'workdir'); self.R = os.path.join(d, 'repo')
        self.cand = os.path.join(self.W, 'parameters', 'candidates', SET)
        os.makedirs(os.path.join(self.R, 'manifests', 'parameters'))
        files = {'domain/d.nc': None, 'veg/v.bin': b'vegetation', 'veg/provenance.yaml': b'qc: passed\n',
                 'old/o.bin': b'old file', 'src/s.nc': None}
        for rel, data in files.items():
            p = os.path.join(self.cand, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            if rel.endswith('.nc'):
                with nc.Dataset(p, 'w') as ds:
                    ds.createDimension('x', 2); ds.createVariable('x', 'f8', ('x',))[:] = [1, 2]
                    if restricted and rel == 'src/s.nc':
                        ds.setncattr('not_authorized_for_global_production', 'true')
            else:
                with open(p, 'wb') as fh:
                    fh.write(data)
        md5 = lambda rel: pp.hashing.md5(os.path.join(self.cand, rel))   # noqa: E731
        for c in ('domain', 'veg'):
            q = os.path.join(self.W, 'qc', 'parameters', 'candidates', SET, c); os.makedirs(q)
            with open(os.path.join(q, 'summary.json'), 'w') as fh:
                json.dump({'status': 'passed'}, fh)
        self.manifest = {'parameter_set_id': SET, 'components': {
            'domain': {'files': [{'path': 'domain/d.nc', 'md5': md5('domain/d.nc')}], 'qc_status': 'passed',
                       'qc_evidence': f'qc/parameters/candidates/{SET}/domain'},
            'veg': {'files': [{'path': 'veg/v.bin', 'md5': md5('veg/v.bin'), 'size_bytes': 10}],
                    'provenance': 'veg/provenance.yaml', 'qc_status': 'passed',
                    'qc_evidence': f'qc/parameters/candidates/{SET}/veg'},
            'old': {'files': [{'path': 'old/o.bin', 'md5': md5('old/o.bin')}], 'qc_status': 'not_checked',
                    'promotion': 'excluded', 'promotion_reason': 'superseded by veg'},
            'src': {'files': [{'path': 'src/s.nc', 'md5': md5('src/s.nc')}], 'qc_status': 'not_checked',
                    'promotion': 'excluded', 'promotion_reason': 'source of veg, not read by VIC'}}}
        self.write_manifest()
        self.root = os.path.join(self.W, 'parameters', 'production')
        self.target = os.path.join(self.root, SET)

    def write_manifest(self):
        with open(pp.manifest_path(self.R, SET), 'w') as fh:
            yaml.safe_dump(self.manifest, fh)

    def promote(self, accepted=None):
        return pp.promote(self.W, self.R, SET, 'user, 2026-10-30', accepted, self.root, 'abc', False)

    def verify(self):
        return vp.verify(self.W, self.R, SET, self.target, scratch=False)


class SelectionTest(unittest.TestCase):
    def test_selection(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d)
            inc, exc = pp.selection(f.manifest)
            self.assertEqual([x['path'] for x in inc], ['domain/d.nc', 'veg/v.bin', 'veg/provenance.yaml'])
            self.assertEqual([e['entry'] for e in exc], ['old', 'src'])

    def test_unchecked_entry_stops(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); f.manifest['components']['veg']['qc_status'] = 'warning'
            with self.assertRaisesRegex(pp.PromoteError, 'veg has qc_status warning'):
                pp.selection(f.manifest)

    def test_excluded_without_reason_or_shared_file_stops(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); f.manifest['components']['old']['promotion_reason'] = ' '
            with self.assertRaisesRegex(pp.PromoteError, 'without a promotion_reason'):
                pp.selection(f.manifest)
            f = Fixture(os.path.join(d, 'b')); f.manifest['components']['old']['files'].append({'path': 'veg/v.bin'})
            with self.assertRaisesRegex(pp.PromoteError, 'both a promoted and an excluded'):
                pp.selection(f.manifest)


class PromoteTest(unittest.TestCase):
    def test_promote_and_verify(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d)
            rpath = f.promote()
            rec = yaml.safe_load(open(rpath))
            self.assertEqual(sorted(vp.tree(f.target)),
                             ['domain/d.nc', 'promotion.yaml', 'veg/provenance.yaml', 'veg/v.bin'])
            self.assertEqual([e['entry'] for e in rec['excluded']], ['old', 'src'])
            self.assertEqual(os.path.getmtime(os.path.join(f.target, 'veg/v.bin')),
                             os.path.getmtime(os.path.join(f.cand, 'veg/v.bin')))
            checks = f.verify()
            self.assertEqual({k: c['status'] for k, c in checks.items()},
                             {'record': 'passed', 'files': 'passed', 'complete': 'passed', 'qc': 'passed'})
            with self.assertRaisesRegex(pp.PromoteError, 'never overwritten'):
                f.promote()

    def test_manifest_mismatch_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); f.manifest['components']['veg']['files'][0]['md5'] = '0' * 32; f.write_manifest()
            with self.assertRaisesRegex(pp.PromoteError, 'differs from the manifest'):
                f.promote()
            self.assertFalse(os.path.exists(f.target))

    def test_restriction_needs_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d, restricted=True)
            with self.assertRaisesRegex(pp.PromoteError, 'restriction attributes found'):
                f.promote()
            self.assertFalse(os.path.exists(f.target))
            rec = yaml.safe_load(open(f.promote(accepted='accepted by the user for ISIMIP4b')))
            self.assertEqual(rec['restrictions']['found'], {'src/s.nc': {'not_authorized_for_global_production': 'true'}})
            self.assertEqual(f.verify()['record']['status'], 'passed')

    def test_verify_finds_changes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); f.promote()
            with open(os.path.join(f.target, 'veg/v.bin'), 'wb') as fh:
                fh.write(b'VEGETATION')
            open(os.path.join(f.target, 'domain', 'extra.txt'), 'w').close()
            c = f.verify()
            self.assertEqual((c['files']['status'], c['complete']['status']), ('failed', 'failed'))
            self.assertEqual(c['complete']['extra_files'], ['domain/extra.txt'])

    def test_verify_without_record(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); os.makedirs(f.target)
            self.assertEqual(f.verify()['record']['status'], 'not_checked')

    def test_verify_qc_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            f = Fixture(d); f.promote()
            with open(os.path.join(f.W, 'qc', 'parameters', 'candidates', SET, 'veg', 'summary.json'), 'w') as fh:
                json.dump({'status': 'failed'}, fh)
            self.assertEqual(f.verify()['qc']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
