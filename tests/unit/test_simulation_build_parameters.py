"""Unit tests for the model-build and parameter-file checks of workflow/05_simulation/render/render_run.py
(check_build, parameter_files), which the render tests replace by fixed results.

check_build: the campaign's model commit must equal model/vic.lock.yaml, the build manifest must be a build of that
commit with status built or tested, the runtime modules of the build must equal the modules of the resources, and a
production campaign needs a frozen lock; a non-production campaign with model.test_build runs a test build of a commit
derived from the locked commit. parameter_files: every parameter file of the campaign must be recorded in
the parameter manifest with an md5 and exist under parameters/<status>/<set>/.

The repository files (lock, parameter manifest) and the workdir (build manifest, parameter files) are synthetic,
in temporary directories; nothing under the workdir is read or written.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, sys, tempfile, unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'render'))
import render_run as rr      # noqa: E402

COMMIT = 'a' * 40
MODULES = ['2025', 'netCDF/4.9.3-gompi-2025a']


def dump_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        yaml.safe_dump(data, fh)


class Synthetic(unittest.TestCase):
    """A repository root R (model lock, parameter manifest) and a workdir W (build, parameter files)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.R = os.path.join(self.tmp.name, 'repo'); self.W = os.path.join(self.tmp.name, 'workdir')
        self.patch = mock.patch.object(rr, 'REPO', self.R); self.patch.start()
        self.lock(COMMIT, 'provisional')
        self.build(COMMIT, 'built', MODULES)
        self.campaign = {'production': False, 'model': {'lock': 'model/vic.lock.yaml', 'commit': COMMIT},
                         'parameter_set': {'id': 'pset', 'status': 'candidates',
                                           'files': {'domain': 'domain/domain.nc', 'parameters': 'bundle/params.nc'}}}
        self.resources = {'modules': list(MODULES)}
        self.manifest({'domain': {'qc_status': 'passed', 'files': [{'path': 'domain/domain.nc', 'md5': 'd' * 32}]},
                       'bundle': {'qc_status': 'warning', 'files': [{'path': 'bundle/params.nc', 'md5': 'b' * 32},
                                                                    {'path': 'bundle/other.nc', 'md5': 'o' * 32}]}})
        for rel in ('domain/domain.nc', 'bundle/params.nc'):
            self.parameter_file(rel)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def lock(self, commit, freeze_status):
        dump_yaml(os.path.join(self.R, 'model', 'vic.lock.yaml'), {'commit': commit, 'freeze_status': freeze_status})

    def build(self, commit, status, modules, model_commit=None, build_kind='candidate', test_base=None):
        bdir = os.path.join(self.W, 'builds', 'vic', commit); os.makedirs(bdir, exist_ok=True)
        m = {'model': {'model_commit': model_commit or commit}, 'status': status, 'build_kind': build_kind,
             'executable': {'path': 'bin/vic_image.exe', 'sha256': 'e' * 64, 'vic_git_tag': 'tag'},
             'runtime_modules': modules}
        if test_base:
            m['test'] = {'base_commit': test_base}
        with open(os.path.join(bdir, 'build_manifest.json'), 'w') as fh:
            json.dump(m, fh)

    def manifest(self, components):
        dump_yaml(os.path.join(self.R, 'manifests', 'parameters', 'pset.yaml'), {'components': components})

    def parameter_file(self, rel):
        p = os.path.join(self.W, 'parameters', 'candidates', 'pset', rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').close()
        return p


class CheckBuildTest(Synthetic):
    def test_usable_build(self):
        m = rr.check_build(self.W, self.campaign, self.resources)
        self.assertEqual(m['commit'], COMMIT)
        self.assertEqual(m['build'], f'builds/vic/{COMMIT}')
        self.assertEqual(m['executable'], f'builds/vic/{COMMIT}/bin/vic_image.exe')
        self.assertEqual((m['executable_sha256'], m['build_status'], m['freeze_status']), ('e' * 64, 'built', 'provisional'))
        self.assertEqual(m['runtime_modules'], MODULES)
        self.build(COMMIT, 'tested', MODULES)
        self.assertEqual(rr.check_build(self.W, self.campaign, self.resources)['build_status'], 'tested')

    def test_campaign_commit_differs_from_lock(self):
        self.lock('b' * 40, 'provisional')
        with self.assertRaisesRegex(rr.RenderError, 'differs from model/vic.lock.yaml'):
            rr.check_build(self.W, self.campaign, self.resources)

    def test_build_of_another_commit(self):
        self.build(COMMIT, 'built', MODULES, model_commit='b' * 40)
        with self.assertRaisesRegex(rr.RenderError, 'not a usable build'):
            rr.check_build(self.W, self.campaign, self.resources)

    def test_build_without_manifest(self):
        os.remove(os.path.join(self.W, 'builds', 'vic', COMMIT, 'build_manifest.json'))
        with self.assertRaises((OSError, rr.RenderError)):                 # rendering stops either way
            rr.check_build(self.W, self.campaign, self.resources)

    def test_build_status_not_usable(self):
        for status in ('failed', 'building', 'not_checked'):
            self.build(COMMIT, status, MODULES)
            with self.assertRaisesRegex(rr.RenderError, f'status {status}'):
                rr.check_build(self.W, self.campaign, self.resources)

    def test_runtime_modules_differ_from_resources(self):
        for modules in (['2025'], MODULES[::-1], MODULES + ['extra']):
            with self.assertRaisesRegex(rr.RenderError, 'runtime_modules'):
                rr.check_build(self.W, self.campaign, {'modules': modules})

    def test_production_needs_frozen_lock(self):
        self.campaign['production'] = True
        with self.assertRaisesRegex(rr.RenderError, 'frozen model lock'):
            rr.check_build(self.W, self.campaign, self.resources)
        self.lock(COMMIT, 'frozen')
        self.build(COMMIT, 'built', MODULES, build_kind='production')
        self.assertEqual(rr.check_build(self.W, self.campaign, self.resources)['freeze_status'], 'frozen')

    def test_production_needs_production_build(self):
        # D01 amendment 2026-10-28: a production campaign runs only a production build (build_vic.sh with a frozen
        # lock, or a candidate build promoted by promote_build.py); a non-production campaign may use a candidate
        self.lock(COMMIT, 'frozen')
        self.assertEqual(rr.check_build(self.W, self.campaign, self.resources)['build_kind'], 'candidate')
        self.campaign['production'] = True
        with self.assertRaisesRegex(rr.RenderError, 'needs a production build'):
            rr.check_build(self.W, self.campaign, self.resources)
        self.build(COMMIT, 'built', MODULES, build_kind='production')
        self.assertEqual(rr.check_build(self.W, self.campaign, self.resources)['build_kind'], 'production')


class TestBuildTest(Synthetic):
    """A non-production campaign with model.test_build runs a test build (build_vic.sh --test-commit) of a commit that
    descends from the locked commit (task L5, user 2026-10-31)."""
    TEST = 'c' * 40

    def setUp(self):
        super().setUp()
        self.lock(COMMIT, 'frozen')
        self.campaign['model'] = {'lock': 'model/vic.lock.yaml', 'commit': self.TEST, 'test_build': True}

    def test_usable_test_build(self):
        self.build(self.TEST, 'built', MODULES, build_kind='test', test_base=COMMIT)
        m = rr.check_build(self.W, self.campaign, self.resources)
        self.assertEqual((m['commit'], m['freeze_status'], m['build_kind']), (self.TEST, 'test', 'test'))
        self.assertEqual(m['build'], f'builds/vic/{self.TEST}')

    def test_needs_the_flag(self):
        self.build(self.TEST, 'built', MODULES, build_kind='test', test_base=COMMIT)
        for flag in (False, 'yes'):
            self.campaign['model']['test_build'] = flag
            with self.subTest(flag=flag), self.assertRaisesRegex(rr.RenderError, 'differs from model/vic.lock.yaml'):
                rr.check_build(self.W, self.campaign, self.resources)

    def test_never_in_production(self):
        self.build(self.TEST, 'built', MODULES, build_kind='test', test_base=COMMIT)
        self.campaign['production'] = True
        with self.assertRaisesRegex(rr.RenderError, 'production campaign cannot run a test build'):
            rr.check_build(self.W, self.campaign, self.resources)

    def test_flag_with_the_locked_commit(self):
        self.campaign['model']['commit'] = COMMIT
        with self.assertRaisesRegex(rr.RenderError, 'is the locked commit'):
            rr.check_build(self.W, self.campaign, self.resources)

    def test_needs_a_test_build_of_the_locked_commit(self):
        for kind, base in (('candidate', None), ('production', None), ('test', None), ('test', 'b' * 40)):
            self.build(self.TEST, 'built', MODULES, build_kind=kind, test_base=base)
            with self.subTest(kind=kind, base=base), self.assertRaisesRegex(rr.RenderError, 'needs a test build'):
                rr.check_build(self.W, self.campaign, self.resources)


class ParameterFilesTest(Synthetic):
    def test_recorded_files(self):
        out = rr.parameter_files(self.W, self.campaign)
        self.assertEqual(set(out), {'domain', 'parameters'})
        self.assertEqual(out['domain'], {'path': 'parameters/candidates/pset/domain/domain.nc', 'md5': 'd' * 32,
                                         'manifest_entry': 'domain', 'qc_status': 'passed'})
        self.assertEqual(out['parameters']['manifest_entry'], 'bundle')
        self.assertEqual(out['parameters']['qc_status'], 'warning')

    def test_file_not_in_manifest(self):
        self.campaign['parameter_set']['files']['routing'] = 'routing/routing.nc'
        self.parameter_file('routing/routing.nc')
        with self.assertRaisesRegex(rr.RenderError, r'routing/routing.nc \(routing\) is not recorded'):
            rr.parameter_files(self.W, self.campaign)

    def test_missing_md5(self):
        for md5 in (None, ''):
            self.manifest({'domain': {'files': [{'path': 'domain/domain.nc', 'md5': md5}]},
                           'bundle': {'files': [{'path': 'bundle/params.nc', 'md5': 'b' * 32}]}})
            with self.assertRaisesRegex(rr.RenderError, r'domain/domain.nc \(domain\) has no md5'):
                rr.parameter_files(self.W, self.campaign)
        self.manifest({'domain': {'files': [{'path': 'domain/domain.nc'}]},
                       'bundle': {'files': [{'path': 'bundle/params.nc', 'md5': 'b' * 32}]}})
        with self.assertRaisesRegex(rr.RenderError, 'has no md5'):
            rr.parameter_files(self.W, self.campaign)

    def test_missing_file(self):
        os.remove(os.path.join(self.W, 'parameters', 'candidates', 'pset', 'bundle', 'params.nc'))
        with self.assertRaisesRegex(rr.RenderError, 'parameter file missing'):
            rr.parameter_files(self.W, self.campaign)

    def test_status_selects_the_directory(self):
        self.campaign['parameter_set']['status'] = 'production'          # files exist only under candidates/
        with self.assertRaisesRegex(rr.RenderError, 'parameters/production/pset/domain/domain.nc'):
            rr.parameter_files(self.W, self.campaign)


if __name__ == '__main__':
    unittest.main()
