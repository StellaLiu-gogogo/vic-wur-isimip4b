"""Unit tests for workflow/common/provenance.py: record writing, qc.status, the fingerprint block, and the
code-equivalence chain used by the extension rule (docs/directory-contracts.md, "Forcing unit and provenance
record").

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, re, tempfile, unittest
from unittest import mock

import yaml

from common import provenance

P = 'workflow/04_forcing/climate/downscale_climate.py'
T0 = {'workflow/04_forcing/climate': 'a0', 'workflow/common': None}
T1 = {'workflow/04_forcing/climate': 'a1', 'workflow/common': 'c1'}
T2 = {'workflow/04_forcing/climate': 'a2', 'workflow/common': 'c1'}


def entry(i, f, t, producer=P, version='1.1'):
    return {'id': i, 'producer': producer, 'method_version': version, 'from': f, 'to': t}


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path = os.path.join(self.tmp.name, 'provenance.yaml')

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_keeps_order_and_leaves_no_part_file(self):
        rec = {'forcing_unit': 'climate/x/y/prec', 'code_commit': 'c' * 40, 'qc': {'status': 'not_checked'}}
        provenance.write(self.path, rec)
        self.assertEqual(os.listdir(self.tmp.name), ['provenance.yaml'])
        self.assertEqual(open(self.path).read(), yaml.safe_dump(rec, sort_keys=False))
        self.assertEqual(provenance.read(self.path), rec)

    def test_set_qc_changes_only_qc(self):
        rec = {'forcing_unit': 'u', 'qc': {'status': 'not_checked', 'evidence': 'old'}, 'files': [{'path': 'a.nc'}]}
        provenance.write(self.path, rec)
        provenance.set_qc(self.path, 'passed', 'qc/forcing/u')
        got = provenance.read(self.path)
        self.assertEqual(list(got), ['forcing_unit', 'qc', 'files'])
        self.assertEqual(got['qc'], {'status': 'passed', 'evidence': 'qc/forcing/u'})
        self.assertEqual(got['files'], rec['files'])

    def test_fingerprint_and_time(self):
        sw = provenance.software_versions()
        self.assertEqual(list(sw), ['python', 'numpy', 'netCDF4', 'netcdf_c', 'hdf5', 'pyyaml'])
        with mock.patch.dict(os.environ, {'CONDA_DEFAULT_ENV': 'isimip4b'}):
            fp = provenance.fingerprint(T0, '1.1', sw)
        self.assertEqual(fp, {'code_tree': T0, 'method_version': '1.1', 'software': sw, 'conda_env': 'isimip4b'})
        self.assertRegex(provenance.utcnow(), r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')


class EquivalenceTest(unittest.TestCase):
    def test_equal_trees_need_no_entry(self):
        self.assertEqual(provenance.code_equivalence(T0, dict(T0), P, '1.1', entries=[]), [])

    def test_single_entry_and_chain(self):
        es = [entry('e1', T0, T1), entry('e2', T1, T2)]
        self.assertEqual(provenance.code_equivalence(T0, T1, P, '1.1', entries=es), ['e1'])
        self.assertEqual(provenance.code_equivalence(T0, T2, P, '1.1', entries=es), ['e1', 'e2'])
        self.assertEqual(provenance.code_equivalence(T1, T2, P, '1.1', entries=es), ['e2'])

    def test_not_equivalent(self):
        es = [entry('e1', T0, T1)]
        self.assertIsNone(provenance.code_equivalence(T1, T0, P, '1.1', entries=es))           # entries are one-way
        self.assertIsNone(provenance.code_equivalence(T0, T2, P, '1.1', entries=es))           # no entry to T2
        self.assertIsNone(provenance.code_equivalence(T0, T1, P, '1.2', entries=es))           # other method version
        self.assertIsNone(provenance.code_equivalence(T0, T1, 'workflow/other.py', '1.1', entries=es))
        self.assertIsNone(provenance.code_equivalence(None, T1, P, '1.1', entries=es))         # no fingerprint
        cyc = [entry('e1', T0, T1), entry('e2', T1, T0)]
        self.assertIsNone(provenance.code_equivalence(T0, T2, P, '1.1', entries=cyc))          # loop ends
        amb = [entry('e1', T0, T1), entry('e3', T0, T2)]
        self.assertIsNone(provenance.code_equivalence(T0, T2, P, '1.1', entries=amb))          # ambiguous record

    def test_record_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'code-equivalence.yaml')
            self.assertEqual(provenance.load_equivalences(path), [])
            with open(path, 'w') as fh:
                yaml.safe_dump({'equivalences': [entry('e1', T0, T1)]}, fh, sort_keys=False)
            self.assertEqual(provenance.code_equivalence(T0, T1, P, '1.1', entries=provenance.load_equivalences(path)),
                             ['e1'])

    def test_repository_record(self):
        """Every entry of manifests/code-equivalence.yaml is complete and has a unique id."""
        es = provenance.load_equivalences()
        self.assertEqual(len({e['id'] for e in es}), len(es))
        for e in es:
            for k in ('id', 'producer', 'method_version', 'from', 'to', 'change', 'evidence', 'approved'):
                self.assertIn(k, e, e.get('id'))
            self.assertTrue(os.path.exists(os.path.join(provenance.REPO, e['producer'])), e['producer'])
            self.assertEqual(set(e['from']), set(e['to']))
            for h in e['to'].values():
                self.assertRegex(h, r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
