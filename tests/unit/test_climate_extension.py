"""Unit tests for the extension rule of workflow/04_forcing/climate/downscale_climate.py (docs/directory-contracts.md,
"Forcing unit and provenance record"): an existing climate forcing unit may get years it does not contain yet only
when the method version, the code (equal Git tree hashes, or a chain of entries of manifests/code-equivalence.yaml),
the key software versions, the inputs used again (SHA-256) and the existing data files (SHA-256) are unchanged; a
year the unit already contains is refused.

check_extension() is tested on synthetic provenance records. The extension branch of main() runs on a synthetic
workdir and repository (input files, MD5SUMS, input and parameter manifests, code-equivalence record) in temporary
directories, with Git, the grid relation and the per-variable worker replaced by stand-ins: no downscaling is done.
The real code-equivalence record of the repository is read once (its climate entry).

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import contextlib, hashlib, importlib.util, io, os, sys, tempfile, unittest
from unittest import mock

import numpy as np
import yaml

from common import provenance

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '04_forcing', 'climate', 'downscale_climate.py')
spec = importlib.util.spec_from_file_location('downscale_climate_extension', SRC)
dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)

CLIMATE, COMMON = 'workflow/04_forcing/climate', 'workflow/common'
T0 = {CLIMATE: 'a0', COMMON: None}
T1 = {CLIMATE: 'a1', COMMON: 'c1'}
T2 = {CLIMATE: 'a2', COMMON: 'c1'}
SOFTWARE = provenance.software_versions()
GCM, ALIAS, VAR = 'ec-earth3-esm-1-1', 'esm-hist', 'prec'
UNIT = f'climate/{GCM}/{ALIAS}/{VAR}'


def sha256(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def md5(path):
    with open(path, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(text)
    return path


def dump_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def entry(i, f, t, producer=dc.CREATED_BY, version=dc.METHOD_VERSION):
    return {'id': i, 'producer': producer, 'method_version': version, 'from': f, 'to': t}


class EquivalenceRecord:
    """A temporary repository root for common/provenance.py, holding a synthetic manifests/code-equivalence.yaml."""

    def use_record(self, root, entries):
        dump_yaml(os.path.join(root, provenance.EQUIVALENCE), {'equivalences': entries})
        p = mock.patch.object(provenance, 'REPO', root); p.start(); self.addCleanup(p.stop)


# ------------------------------------------------------------------------------------------------ check_extension
class CheckExtensionTest(EquivalenceRecord, unittest.TestCase):
    STATIC = ['parameters/dom.nc', 'parameters/bundle.nc', 'raw/era5.nc']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, 'unit')
        f = write(os.path.join(self.out, 'prec_2015.nc'), 'data 2015')
        recorded = {p: p[0] * 64 for p in self.STATIC + ['raw/src_2011_2020.nc']}
        self.prov = {'method': {'version': dc.METHOD_VERSION},
                     'fingerprint': {'code_tree': dict(T0), 'method_version': dc.METHOD_VERSION, 'software': dict(SOFTWARE)},
                     'input_sha256': recorded, 'files': [{'path': 'prec_2015.nc', 'year': 2015, 'sha256': sha256(f)}]}
        self.current = {'code_tree': dict(T0), 'software': dict(SOFTWARE), 'static_inputs': list(self.STATIC),
                        'input_sha256': dict(recorded, **{'raw/src_2021_2030.nc': 'n' * 64})}   # a new source file
        self.use_record(os.path.join(self.tmp.name, 'repo'), [])

    def check(self):
        return dc.check_extension(self.prov, self.out, self.current)

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
        self.current['code_tree'] = dict(T1)
        self.assert_refused('no entry of manifests/code-equivalence.yaml connects them')

    def test_code_tree_chain_through_record(self):
        self.use_record(os.path.join(self.tmp.name, 'repo'), [entry('e1', T0, T1), entry('e2', T1, T2)])
        for tree in (T1, T2):
            self.current['code_tree'] = dict(tree)
            self.assertEqual(self.check(), [])

    def test_record_entry_of_other_method_or_producer(self):
        self.current['code_tree'] = dict(T1)
        for e in (entry('e1', T0, T1, version='0.9'), entry('e1', T0, T1, producer='workflow/other.py')):
            self.use_record(os.path.join(self.tmp.name, 'repo'), [e])
            self.assert_refused('no entry of')

    def test_record_is_one_way(self):
        self.use_record(os.path.join(self.tmp.name, 'repo'), [entry('e1', T1, T0)])
        self.current['code_tree'] = dict(T1)                              # the unit was made by T0
        self.assert_refused('no entry of')

    def test_repository_record_connects_the_climate_entry(self):
        """The entry common-modules-climate of the repository's record leads from the tree hashes before task G to
        those after it."""
        with open(os.path.join(HERE, '..', '..', provenance.EQUIVALENCE)) as fh:
            e = next(x for x in yaml.safe_load(fh)['equivalences'] if x['id'] == 'common-modules-climate')
        self.prov['fingerprint']['code_tree'] = dict(e['from']); self.current['code_tree'] = dict(e['to'])
        with mock.patch.object(provenance, 'REPO', os.path.abspath(os.path.join(HERE, '..', '..'))):
            self.assertEqual(self.check(), [])
            self.assertEqual(provenance.code_equivalence(e['from'], e['to'], dc.CREATED_BY, dc.METHOD_VERSION),
                             ['common-modules-climate'])

    def test_software_changed(self):
        self.current['software'] = dict(SOFTWARE, numpy='0.0.1')
        self.assert_refused('software')

    def test_input_used_again_changed(self):
        self.current['input_sha256']['raw/src_2011_2020.nc'] = 'z' * 64
        self.assert_refused('input raw/src_2011_2020.nc changed (sha256)')
        self.current['input_sha256']['raw/src_2011_2020.nc'] = self.prov['input_sha256']['raw/src_2011_2020.nc']
        self.current['input_sha256']['parameters/dom.nc'] = 'z' * 64
        self.assert_refused('input parameters/dom.nc changed')

    def test_static_input_not_recorded(self):
        del self.prov['input_sha256']['raw/era5.nc']
        self.assert_refused('static input raw/era5.nc not recorded in the unit')

    def test_existing_file_changed_or_missing(self):
        write(os.path.join(self.out, 'prec_2015.nc'), 'other data')
        self.assert_refused('prec_2015.nc sha256 differs from provenance')
        os.remove(os.path.join(self.out, 'prec_2015.nc'))
        self.assert_refused('prec_2015.nc missing')


# ------------------------------------------------------------------------------------------------ main()
class FakePool:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def map(self, f, jobs, chunksize=None): return list(map(f, jobs))


class ExtensionBranchTest(EquivalenceRecord, unittest.TestCase):
    """main() on an existing prec unit with year 2015, made by code tree T0 at commit o...o, extended with 2016."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.W = W = os.path.join(self.tmp.name, 'workdir'); self.R = R = os.path.join(self.tmp.name, 'repo')
        pdir = 'parameters/candidates/pset'
        static = {'dom': write(f'{W}/{pdir}/domain/vic_global_5min_domain_nogl.nc', 'domain'),
                  'bundle': write(f'{W}/{pdir}/bundle/vic_global_5min_natural_static_root-b-zeng2001.nc', 'bundle'),
                  'era5': write(f'{W}/{dc.ERA5_FILE}', 'era5')}
        src_dir = dc.ISIMIP_DIR.format(alias=ALIAS, gcm_dir=dc.GCM_DIR[GCM])
        self.src = write(f'{W}/{src_dir}/{GCM}_x_w5e5_era5_{ALIAS}_pr_global_30arcmin_daily_2011_2020.nc', 'pr 2011-2020')
        write(f'{R}/{dc.ISIMIP_MD5SUMS}', f'{md5(self.src)}  {os.path.relpath(self.src, f"{W}/raw/ISIMIP4b")}\n')
        dump_yaml(f'{R}/{dc.ERA5_MANIFEST}', {'files': [{'md5': md5(static['era5'])}]})
        dump_yaml(f'{R}/manifests/parameters/pset.yaml',
                  {'components': {'domain': {'files': [{'md5': md5(static['dom'])}]},
                                  'bundle': {'files': [{'md5': md5(static['bundle'])}]}}})
        self.use_record(R, [entry('e1', T0, T1)])
        # the existing unit
        self.unit = f'{W}/forcing/{UNIT}'
        self.f2015 = write(f'{self.unit}/{dc.out_name(VAR, GCM, ALIAS, 2015)}', 'prec 2015')
        inputs = {os.path.relpath(p, W): sha256(p) for p in list(static.values()) + [self.src]}
        self.record = {
            'forcing_unit': UNIT, 'created_by': dc.CREATED_BY, 'code_commit': 'o' * 40, 'code_dirty': False,
            'created_at': '2026-10-01T00:00:00Z', 'inputs': sorted(inputs), 'input_sha256': inputs,
            'method': {'version': dc.METHOD_VERSION},
            'fingerprint': provenance.fingerprint(dict(T0), dc.METHOD_VERSION, dict(SOFTWARE)),
            'files': [{'path': os.path.basename(self.f2015), 'year': 2015, 'size_bytes': 9, 'sha256': sha256(self.f2015),
                       'created_at': '2026-10-01T00:00:00Z', 'code_commit': 'o' * 40}],
            'qc': {'status': 'passed', 'evidence': f'qc/forcing/{UNIT}'}}
        dump_yaml(self.prov_path(), self.record)
        self.before = os.stat(self.f2015).st_mtime_ns
        self.produced = []

    def prov_path(self):
        return f'{self.unit}/provenance.yaml'

    def prov(self):
        with open(self.prov_path()) as fh:
            return yaml.safe_load(fh)

    def produce(self, job):
        """Stand-in for produce_variable: writes one small file per year and returns its record."""
        recs = []
        for y in job['years']:
            p = write(f'{job["ctx"]["out_dir"][job["var"]]}/{dc.out_name(job["var"], GCM, ALIAS, y)}', f'new {y}')
            recs.append({'path': os.path.basename(p), 'year': y, 'size_bytes': os.path.getsize(p), 'sha256': sha256(p),
                         'created_at': '2026-10-08T00:00:00Z', 'code_commit': job['ctx']['commit']})
            self.produced.append(y)
        return job['var'], recs

    def main(self, years, tree=T1):
        argv = ['downscale', '--gcm', GCM, '--alias', ALIAS, '--years', years, '--variables', VAR,
                '--parameter-set', 'pset']
        static = (None, None, None, None, None, np.ones(2, bool), None, np.zeros(2), None, 'cache', 'key')
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}), mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(dc, 'REPO', self.R), \
                mock.patch.object(dc, 'git_state', return_value=('n' * 40, False)), \
                mock.patch.object(dc.gitstate, 'tree_hashes', return_value=dict(tree)), \
                mock.patch.object(dc, 'static_reference', return_value=static), \
                mock.patch.object(dc, 'Pool', FakePool), mock.patch.object(dc, 'produce_variable', self.produce), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            dc.main()

    def assert_unit_unchanged(self):
        self.assertEqual(self.prov(), self.record)
        self.assertEqual(sorted(os.listdir(self.unit)), sorted([os.path.basename(self.f2015), 'provenance.yaml']))
        self.assertEqual(self.produced, [])

    def assert_refused(self, years, text, tree=T1):
        with self.assertRaises(SystemExit) as cm:
            self.main(years, tree)
        self.assertIn(text, str(cm.exception))
        self.assert_unit_unchanged()

    def test_extension_through_the_record(self):
        self.main('2016')
        self.assertEqual(self.produced, [2016])
        with open(self.f2015) as fh:                                      # the existing file is not touched
            self.assertEqual(fh.read(), 'prec 2015')
        self.assertEqual(os.stat(self.f2015).st_mtime_ns, self.before)
        p = self.prov()
        self.assertEqual(p['files'][0], self.record['files'][0])
        self.assertEqual([f['year'] for f in p['files']], [2015, 2016])
        self.assertEqual(p['files'][1]['code_commit'], 'n' * 40)
        self.assertEqual(p['files'][1]['sha256'], sha256(f'{self.unit}/{dc.out_name(VAR, GCM, ALIAS, 2016)}'))
        self.assertEqual((p['code_commit'], p['created_at'], p['code_dirty']), ('o' * 40, '2026-10-01T00:00:00Z', False))
        self.assertEqual(p['years'], '2015-2016')
        self.assertEqual(p['qc'], {'status': 'not_checked', 'evidence': f'qc/forcing/{UNIT}'})   # was passed
        self.assertEqual(p['fingerprint']['code_tree'], T1)
        self.assertEqual(len(p['extended']), 1)
        ext = p['extended'][0]
        self.assertEqual((ext['code_commit'], ext['years'], ext['code_equivalence']), ('n' * 40, [2016], ['e1']))
        self.assertEqual(p['input_sha256'], self.record['input_sha256'])  # the same 2011-2020 source file

    def test_extension_with_the_same_code(self):
        self.main('2016', tree=T0)
        ext = self.prov()['extended']
        self.assertEqual(len(ext), 1)
        self.assertNotIn('code_equivalence', ext[0])

    def test_year_clash_refused(self):
        self.assert_refused('2015-2016', 'already contains [2015]; an existing unit is never overwritten')

    def test_changed_existing_file_refused(self):
        write(self.f2015, 'prec 2015, changed')                           # the record keeps the old SHA-256
        with self.assertRaises(SystemExit) as cm:
            self.main('2016')
        self.assertIn('cannot be extended', str(cm.exception))
        self.assertIn('sha256 differs from provenance', str(cm.exception))
        self.assertEqual(self.prov(), self.record)
        self.assertEqual(self.produced, [])

    def test_code_without_entry_refused(self):
        self.assert_refused('2016', 'no entry of manifests/code-equivalence.yaml', tree=T2)

    def test_method_version_refused(self):
        self.record['method']['version'] = '1.0'; dump_yaml(self.prov_path(), self.record)
        self.assert_refused('2016', 'method version 1.0')

    def test_software_refused(self):
        self.record['fingerprint']['software']['netCDF4'] = '0.0.1'; dump_yaml(self.prov_path(), self.record)
        self.assert_refused('2016', 'software')

    def test_input_used_again_refused(self):
        self.record['input_sha256'][os.path.relpath(self.src, self.W)] = '0' * 64
        dump_yaml(self.prov_path(), self.record)
        self.assert_refused('2016', 'changed (sha256)')

    def test_source_not_matching_its_manifest_refused(self):
        write(f'{self.R}/{dc.ISIMIP_MD5SUMS}', f'{"0" * 32}  {os.path.relpath(self.src, f"{self.W}/raw/ISIMIP4b")}\n')
        self.assert_refused('2016', f'md5 does not match {dc.ISIMIP_MD5SUMS}')

    def test_files_without_provenance_refused(self):
        os.remove(self.prov_path())
        with self.assertRaises(SystemExit) as cm:
            self.main('2016')
        self.assertIn('no provenance.yaml (incomplete unit)', str(cm.exception))
        self.assertEqual(os.listdir(self.unit), [os.path.basename(self.f2015)])
        self.assertEqual(self.produced, [])


if __name__ == '__main__':
    unittest.main()
