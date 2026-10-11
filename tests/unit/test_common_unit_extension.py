"""Unit tests for workflow/common/unit_extension.py: the rules for extending a forcing unit with years it does not
contain (docs/directory-contracts.md, "Forcing unit and provenance record"): years of a unit, the conditions checked
before anything is written (method version, code tree or code-equivalence chain, software versions, inputs used
again, existing files), the decision for a producer (new unit, extension, refused), and the merge of the new files
into the unit's record.

Synthetic provenance records and files in temporary directories; the code-equivalence record is a temporary file,
except for one test that reads the repository's own record (its climate entry).

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import hashlib, os, tempfile, unittest
from unittest import mock

import yaml

from common import provenance, unit_extension as ue

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCER = 'workflow/04_forcing/climate/downscale_climate.py'
VERSION = '1.1'
CLIMATE, COMMON = 'workflow/04_forcing/climate', 'workflow/common'
T0 = {CLIMATE: 'a0', COMMON: None}
T1 = {CLIMATE: 'a1', COMMON: 'c1'}
T2 = {CLIMATE: 'a2', COMMON: 'c1'}
SOFTWARE = provenance.software_versions()
STATIC = ['parameters/dom.nc', 'parameters/bundle.nc', 'raw/era5.nc']


def sha256(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(text)
    return path


def dump_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def entry(i, f, t, producer=PRODUCER, version=VERSION):
    return {'id': i, 'producer': producer, 'method_version': version, 'from': f, 'to': t}


class Base(unittest.TestCase):
    """A unit with one file (2015), made by code tree T0, and a temporary code-equivalence record."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.unit = os.path.join(self.tmp.name, 'unit')
        self.f2015 = write(os.path.join(self.unit, 'prec_x_y_2015.nc'), 'data 2015')
        self.recorded = {p: p[0] * 64 for p in STATIC + ['raw/src_2011_2020.nc']}
        self.prov = {'forcing_unit': 'climate/x/y/prec', 'code_commit': 'o' * 40, 'code_dirty': False,
                     'created_at': '2026-10-01T00:00:00Z', 'inputs': sorted(self.recorded), 'input_sha256': dict(self.recorded),
                     'method': {'version': VERSION},
                     'fingerprint': {'code_tree': dict(T0), 'method_version': VERSION, 'software': dict(SOFTWARE)},
                     'files': [{'path': 'prec_x_y_2015.nc', 'year': 2015, 'size_bytes': 9, 'sha256': sha256(self.f2015),
                                'created_at': '2026-10-01T00:00:00Z', 'code_commit': 'o' * 40}],
                     'qc': {'status': 'passed', 'evidence': 'qc/forcing/climate/x/y/prec'}}
        dump_yaml(f'{self.unit}/provenance.yaml', self.prov)
        self.new_inputs = dict(self.recorded, **{'raw/src_2021_2030.nc': 'n' * 64})    # one new source file
        self.tree = dict(T0)
        self.use_record([])

    def use_record(self, entries):
        root = os.path.join(self.tmp.name, 'repo')
        dump_yaml(os.path.join(root, provenance.EQUIVALENCE), {'equivalences': entries})
        p = mock.patch.object(provenance, 'REPO', root); p.start(); self.addCleanup(p.stop)

    def check(self):
        return ue.check(self.prov, self.unit, PRODUCER, VERSION, self.tree, dict(SOFTWARE), self.new_inputs, STATIC)

    def prepare(self, years):
        return ue.prepare(self.unit, 'climate/x/y/prec', years, PRODUCER, VERSION, self.tree, dict(SOFTWARE),
                          self.new_inputs, STATIC)


class YearsTest(unittest.TestCase):
    def test_year_of_every_family(self):
        self.assertEqual(ue.year_of('coverage_1850soc_1601.nc'), 1601)
        self.assertEqual(ue.year_of('/a/b/municipal_demand_2021soc_2100.nc'), 2100)
        self.assertEqual(ue.year_of('prec_ec-earth3-esm-1-1_esm-picontrol_1551.nc'), 1551)
        for bad in ('coverage.nc', 'coverage_1850soc_1601.txt', 'prec_abc.nc', 'provenance.yaml'):
            with self.assertRaises(ValueError):
                ue.year_of(bad)

    def test_unit_years_from_key_or_name(self):
        prov = {'files': [{'path': 'c_2016.nc'}, {'path': 'x.nc', 'year': 2014}, {'path': 'c_2015.nc'}]}
        self.assertEqual(ue.unit_years(prov), [2014, 2015, 2016])
        self.assertEqual(ue.unit_years({}), [])
        self.assertEqual(ue.years_span([2016, 2014]), '2014-2016')
        self.assertIsNone(ue.years_span([]))


class ExistingTest(unittest.TestCase):
    def test_absent_empty_record_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ue.existing(f'{d}/none'))
            os.makedirs(f'{d}/empty'); self.assertIsNone(ue.existing(f'{d}/empty'))
            dump_yaml(f'{d}/unit/provenance.yaml', {'forcing_unit': 'u'})
            self.assertEqual(ue.existing(f'{d}/unit'), {'forcing_unit': 'u'})
            write(f'{d}/broken/c_2015.nc', 'x')
            with self.assertRaises(SystemExit) as cm:
                ue.existing(f'{d}/broken')
            self.assertIn('no provenance.yaml (incomplete unit)', str(cm.exception))


class CheckTest(Base):
    def assert_refused(self, text):
        bad = self.check()
        self.assertEqual(len(bad), 1, bad)
        self.assertIn(text, bad[0])

    def test_unchanged_unit_can_be_extended(self):
        self.assertEqual(self.check(), [])

    def test_method_version_changed(self):
        self.prov['method']['version'] = '1.0'
        self.assert_refused('method version 1.0 != ')

    def test_code_tree_changed_without_entry(self):
        self.tree = dict(T1)
        self.assert_refused('no entry of manifests/code-equivalence.yaml connects them')

    def test_code_tree_chain_through_record(self):
        self.use_record([entry('e1', T0, T1), entry('e2', T1, T2)])
        for tree in (T1, T2):
            self.tree = dict(tree)
            self.assertEqual(self.check(), [])

    def test_record_entry_of_other_method_or_producer(self):
        self.tree = dict(T1)
        for e in (entry('e1', T0, T1, version='0.9'), entry('e1', T0, T1, producer='workflow/other.py')):
            self.use_record([e])
            self.assert_refused('no entry of')

    def test_record_is_one_way(self):
        self.use_record([entry('e1', T1, T0)])
        self.tree = dict(T1)                                               # the unit was made by T0
        self.assert_refused('no entry of')

    def test_no_fingerprint_recorded(self):
        """A record without a fingerprint block (units made before 2026-10-05) can never be extended."""
        del self.prov['fingerprint']
        bad = self.check()
        self.assertEqual(len(bad), 2, bad)
        self.assertIn('code tree None', bad[0]); self.assertIn('software None', bad[1])

    def test_repository_record_connects_the_climate_entry(self):
        """The entry common-modules-climate of the repository's record leads from the tree hashes before task G to
        those after it."""
        with open(os.path.join(HERE, '..', '..', provenance.EQUIVALENCE)) as fh:
            e = next(x for x in yaml.safe_load(fh)['equivalences'] if x['id'] == 'common-modules-climate')
        self.prov['fingerprint']['code_tree'] = dict(e['from']); self.tree = dict(e['to'])
        with mock.patch.object(provenance, 'REPO', os.path.abspath(os.path.join(HERE, '..', '..'))):
            self.assertEqual(self.check(), [])

    def test_software_changed(self):
        self.prov['fingerprint']['software']['numpy'] = '0.0.1'
        self.assert_refused('software')

    def test_input_used_again_changed(self):
        self.new_inputs['raw/src_2011_2020.nc'] = 'z' * 64
        self.assert_refused('input raw/src_2011_2020.nc changed (sha256)')
        self.new_inputs['raw/src_2011_2020.nc'] = self.recorded['raw/src_2011_2020.nc']
        self.new_inputs['parameters/dom.nc'] = 'z' * 64
        self.assert_refused('input parameters/dom.nc changed')

    def test_static_input_not_recorded(self):
        del self.prov['input_sha256']['raw/era5.nc']
        self.assert_refused('static input raw/era5.nc not recorded in the unit')

    def test_existing_file_changed_or_missing(self):
        write(self.f2015, 'other data')
        self.assert_refused('prec_x_y_2015.nc sha256 differs from provenance')
        os.remove(self.f2015)
        self.assert_refused('prec_x_y_2015.nc missing')


class PrepareTest(Base):
    def test_new_unit(self):
        self.unit = os.path.join(self.tmp.name, 'new-unit')
        self.assertIsNone(self.prepare([2016]))
        self.assertFalse(os.path.exists(self.unit))                        # nothing is written

    def test_extension_returns_the_record(self):
        self.assertEqual(self.prepare([2016, 2017]), self.prov)

    def test_year_already_there(self):
        with self.assertRaises(SystemExit) as cm:
            self.prepare([2015, 2016])
        self.assertIn('climate/x/y/prec already contains [2015]; an existing unit is never overwritten', str(cm.exception))

    def test_condition_fails(self):
        self.prov['fingerprint']['software']['hdf5'] = '0'; dump_yaml(f'{self.unit}/provenance.yaml', self.prov)
        with self.assertRaises(SystemExit) as cm:
            self.prepare([2016])
        self.assertIn('climate/x/y/prec cannot be extended:\n  software', str(cm.exception))

    def test_incomplete_unit(self):
        os.remove(f'{self.unit}/provenance.yaml')
        with self.assertRaises(SystemExit) as cm:
            self.prepare([2016])
        self.assertIn('incomplete unit', str(cm.exception))


class ExtendTest(Base):
    def new_file(self, year):
        p = write(os.path.join(self.unit, f'prec_x_y_{year}.nc'), f'new {year}')
        return ue.file_record(p, year, 'n' * 40, created_at='2026-10-12T00:00:00Z')

    def test_file_record(self):
        r = self.new_file(2016)
        self.assertEqual(r, {'path': 'prec_x_y_2016.nc', 'year': 2016, 'size_bytes': 8,
                             'sha256': sha256(f'{self.unit}/prec_x_y_2016.nc'), 'created_at': '2026-10-12T00:00:00Z',
                             'code_commit': 'n' * 40})
        self.assertRegex(ue.file_record(f'{self.unit}/prec_x_y_2016.nc', 2016, 'n' * 40)['created_at'],
                         r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_merge(self):
        self.use_record([entry('e1', T0, T1)])
        new = [self.new_file(2017), dict(self.new_file(2016), extra='dropped')]
        upd = ue.extend(self.prov, new, self.new_inputs, dict(T1), PRODUCER, VERSION, 'n' * 40, '2026-10-12T00:00:00Z',
                        [2016, 2017], details={'source_year': 2015})
        self.assertEqual(sorted(upd), ['extended', 'files', 'input_sha256', 'inputs', 'qc', 'years'])
        self.assertEqual([f['path'] for f in upd['files']], ['prec_x_y_2015.nc', 'prec_x_y_2016.nc', 'prec_x_y_2017.nc'])
        self.assertEqual(upd['files'][0], self.prov['files'][0])          # the existing entry is unchanged
        self.assertEqual(sorted(upd['files'][1]), sorted(ue.FILE_KEYS))     # only the contract's keys
        self.assertEqual(upd['input_sha256'], dict(sorted(self.new_inputs.items())))
        self.assertEqual(upd['inputs'], sorted(self.new_inputs))
        self.assertEqual(upd['years'], '2015-2017')
        self.assertEqual(upd['qc'], {'status': 'not_checked', 'evidence': 'qc/forcing/climate/x/y/prec'})
        self.assertEqual(upd['extended'], [{'at': '2026-10-12T00:00:00Z', 'code_commit': 'n' * 40, 'years': [2016, 2017],
                                            'code_equivalence': ['e1'], 'source_year': 2015}])
        self.assertEqual(self.prov['files'], self.prov['files'][:1])        # the record passed in is not changed
        self.assertNotIn('extended', self.prov)

    def test_same_code_has_no_chain_and_entries_accumulate(self):
        self.prov['extended'] = [{'at': 'earlier', 'code_commit': 'e' * 40, 'years': [2014]}]
        upd = ue.extend(self.prov, [self.new_file(2016)], {}, dict(T0), PRODUCER, VERSION, 'n' * 40, 'now', [2016])
        self.assertEqual(len(upd['extended']), 2)
        self.assertEqual(upd['extended'][1], {'at': 'now', 'code_commit': 'n' * 40, 'years': [2016]})
        self.assertEqual(upd['input_sha256'], self.recorded)
        self.assertEqual(upd['years'], '2015-2016')


if __name__ == '__main__':
    unittest.main()
