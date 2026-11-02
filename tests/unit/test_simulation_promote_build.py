"""Unit tests for workflow/05_simulation/build/promote_build.py (D01 amendment 2026-10-28): a candidate build of the
frozen commit is recorded as the production build without recompiling, on a small synthetic workdir and repository.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import hashlib, json, os, sys, tempfile, unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'build'))
import promote_build as pb   # noqa: E402

COMMIT = 'a' * 40


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.W = os.path.join(self.tmp.name, 'workdir'); self.R = os.path.join(self.tmp.name, 'repo')
        os.makedirs(os.path.join(self.R, 'model'))
        self.lock('frozen')
        self.bdir = os.path.join(self.W, 'builds', 'vic', COMMIT)
        for d in ('bin', 'logs', 'tests'):
            os.makedirs(os.path.join(self.bdir, d))
        self.exe = os.path.join(self.bdir, 'bin', 'vic_image.exe')
        with open(self.exe, 'wb') as fh:
            fh.write(b'executable')
        self.write_manifest()
        self.git = mock.patch.object(pb.gitstate, 'state', return_value=('c' * 40, False)); self.git.start()

    def tearDown(self):
        self.git.stop()
        self.tmp.cleanup()

    def lock(self, status):
        with open(os.path.join(self.R, 'model', 'vic.lock.yaml'), 'w') as fh:
            yaml.safe_dump({'commit': COMMIT, 'freeze_status': status, 'set_on': '2026-10-28', 'set_by': 'user (D01)'}, fh)

    def write_manifest(self, **kw):
        m = {'schema': 'isimip4b-vic-build-manifest-1', 'status': 'built', 'build_kind': 'candidate',
             'model': {'model_commit': COMMIT, 'checkout_head': COMMIT, 'freeze_status': 'provisional'},
             'workflow': {'code_commit': 'e' * 40, 'code_dirty': False},
             'executable': {'path': 'bin/vic_image.exe', 'sha256': hashlib.sha256(b'executable').hexdigest(),
                            'size_bytes': 10},
             'tests': {'vic_test_suite': {'status': 'skipped'}}, 'logs': ['build.log']}
        m.update(kw)
        self.text = json.dumps(m, indent=2) + '\n'
        with open(os.path.join(self.bdir, 'build_manifest.json'), 'w') as fh:
            fh.write(self.text)

    def manifest(self):
        with open(os.path.join(self.bdir, 'build_manifest.json')) as fh:
            return json.load(fh)

    def test_promotion(self):
        pb.promote(self.W, self.R, 'user, 2026-10-28')
        m = self.manifest()
        self.assertEqual((m['build_kind'], m['model']['freeze_status'], m['status']), ('production', 'frozen', 'built'))
        p = m['promotion']
        self.assertEqual(p['authorised_by'], 'user, 2026-10-28')
        self.assertFalse(p['recompiled'])
        self.assertEqual(p['from'], {'build_kind': 'candidate', 'freeze_status': 'provisional'})
        self.assertEqual(p['executable']['sha256_verified'], hashlib.sha256(b'executable').hexdigest())
        self.assertEqual(p['vic_test_suite'], 'skipped')
        self.assertEqual(p['workflow']['code_commit'], 'c' * 40)
        self.assertEqual(m['workflow'], {'code_commit': 'e' * 40, 'code_dirty': False})   # the build's own record
        self.assertEqual(m['logs'], ['build.log', 'build_manifest.candidate.json'])
        with open(os.path.join(self.bdir, pb.KEPT)) as fh:                     # the earlier manifest, byte for byte
            self.assertEqual(fh.read(), self.text)
        self.assertEqual(p['previous_manifest']['sha256'], hashlib.sha256(self.text.encode()).hexdigest())
        self.assertEqual(sorted(os.listdir(self.bdir)), ['bin', 'build_manifest.json', 'logs', 'tests'])
        with open(self.exe, 'rb') as fh:
            self.assertEqual(fh.read(), b'executable')

    def test_only_once(self):
        pb.promote(self.W, self.R, 'user, 2026-10-28')
        with self.assertRaisesRegex(pb.PromoteError, 'production build'):
            pb.promote(self.W, self.R, 'user, 2026-10-28')

    def test_dry_run_writes_nothing(self):
        pb.promote(self.W, self.R, 'user, 2026-10-28', dry_run=True)
        with open(os.path.join(self.bdir, 'build_manifest.json')) as fh:
            self.assertEqual(fh.read(), self.text)
        self.assertFalse(os.path.exists(os.path.join(self.bdir, pb.KEPT)))

    def test_stops(self):
        cases = [
            (lambda: self.lock('provisional'), 'not frozen'),
            (lambda: self.write_manifest(status='failed'), 'status failed'),
            (lambda: self.write_manifest(build_kind='production'), 'production build'),
            (lambda: self.write_manifest(model={'model_commit': COMMIT, 'checkout_head': 'b' * 40}), 'checkout'),
            (lambda: open(self.exe, 'ab').write(b'x'), 'sha256'),
            (lambda: open(os.path.join(self.bdir, pb.KEPT), 'w').close(), 'never overwritten'),
        ]
        for change, msg in cases:
            with self.subTest(msg=msg):
                self.tearDown(); self.setUp()
                change()
                with self.assertRaisesRegex(pb.PromoteError, msg):
                    pb.promote(self.W, self.R, 'user, 2026-10-28')

    def test_needs_authorisation_and_clean_repository(self):
        with self.assertRaisesRegex(pb.PromoteError, 'authorised'):
            pb.promote(self.W, self.R, ' ')
        with mock.patch.object(pb.gitstate, 'state', return_value=('c' * 40, True)):
            with self.assertRaisesRegex(pb.PromoteError, 'not clean'):
                pb.promote(self.W, self.R, 'user, 2026-10-28')
        self.assertEqual(self.manifest()['build_kind'], 'candidate')


if __name__ == '__main__':
    unittest.main()
