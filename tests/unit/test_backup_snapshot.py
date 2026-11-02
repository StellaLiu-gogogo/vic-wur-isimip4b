"""Unit tests for workflow/09_backup/backup_snapshot.py (snapshot, hard links, verification, current pointer,
bare repository) and submit_backup.py (rendering), on temporary directories with real rsync and git.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '09_backup'))
sys.path.insert(0, HERE)
import backup_rules as br      # noqa: E402
import backup_snapshot as bs   # noqa: E402
from test_backup_rules import GITIGNORE, Workdir, touch  # noqa: E402


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(path):
    os.makedirs(path)
    subprocess.run(['git', 'init', '--quiet', '-b', 'main', path], check=True)
    git(path, 'config', 'user.email', 't@example.org'); git(path, 'config', 'user.name', 'test')
    touch(path, '.gitignore', GITIGNORE); touch(path, 'workflow/a.py', 'print(1)\n'); touch(path, 'docs/a.md')
    git(path, 'add', '.'); git(path, 'commit', '--quiet', '-m', 'first')
    git(path, 'tag', 'v-test'); git(path, 'branch', 'task-other')
    touch(path, 'workflow/__pycache__/a.pyc'); touch(path, 'tests/run.log')
    touch(path, 'docs/uncommitted.md', 'not committed')
    return path


@unittest.skipUnless(shutil.which('rsync') and shutil.which('git'), 'needs rsync and git')
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.W = os.path.join(t, 'workdir'); os.makedirs(self.W); Workdir(self.W)
        self.repo = make_repo(os.path.join(t, 'repo'))
        self.root = os.path.join(t, 'backup', 'isimip4b')
        self.rules = br.Rules.from_gitignore(os.path.join(self.repo, '.gitignore'))
        self.log = []

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, sid):
        return bs.run_snapshot(self.W, self.repo, self.root, self.rules, sid, processes=2, log=self.log.append)

    def test_first_snapshot(self):
        m = self.snapshot('2026-11-03')
        snap = os.path.join(self.root, 'archive', '2026-11-03')
        self.assertTrue(os.path.isdir(snap)); self.assertFalse(os.path.exists(snap + '.staging'))
        self.assertEqual(os.readlink(os.path.join(self.root, 'current')), 'archive/2026-11-03')
        self.assertEqual(m['status'], 'complete'); self.assertEqual(m['verification']['mismatches'], [])
        self.assertEqual(m['accepted_runs'], [Workdir.ACCEPTED])
        self.assertEqual(m['repository_commit'], git(self.repo, 'rev-parse', 'HEAD')); self.assertTrue(m['repository_dirty'])
        # selected content copied, excluded content not
        self.assertTrue(os.path.isfile(f'{snap}/workdir/parameters/production/p/soil.nc'))
        self.assertTrue(os.path.isfile(f'{snap}/workdir/{Workdir.ACCEPTED}/chunks/1601-1625/states/state.2.nc'))
        self.assertTrue(os.path.isfile(f'{snap}/workdir/logs/04_forcing/job_1/job.sbatch'))
        self.assertFalse(os.path.exists(f'{snap}/workdir/raw')); self.assertFalse(os.path.exists(f'{snap}/workdir/scratch'))
        self.assertFalse(os.path.exists(f'{snap}/workdir/forcing/climate/u/2015.nc'))
        self.assertFalse(os.path.exists(f'{snap}/workdir/{Workdir.ACCEPTED}/chunks/1601-1625/output'))
        self.assertFalse(os.path.exists(f'{snap}/workdir/runs/prod/seg-b/states'))
        self.assertTrue(os.path.isfile(f'{snap}/repo/docs/uncommitted.md'))
        self.assertFalse(os.path.exists(f'{snap}/repo/.git')); self.assertFalse(os.path.exists(f'{snap}/repo/tests/run.log'))
        # checksums cover every regular file and match
        with open(f'{snap}/backup-checksums.sha256') as fh:
            rows = [line.split('  ', 1) for line in fh.read().splitlines()]
        self.assertEqual(len(rows), m['files'] - m['symlinks'])
        self.assertEqual(bs.verify_snapshot(self.root, '2026-11-03', 2, log=self.log.append), [])
        with open(f'{snap}/backup-manifest.json') as fh:
            self.assertEqual(json.load(fh)['snapshot_id'], '2026-11-03')
        # the bare repository holds every branch and tag
        bare = os.path.join(self.root, 'repo.git')
        self.assertEqual(set(git(bare, 'for-each-ref', '--format=%(refname:short)').split()),
                         {'main', 'task-other', 'v-test'})

    def test_second_snapshot_hard_links_and_pushes_new_commit(self):
        self.snapshot('2026-11-03')
        touch(self.W, 'README.md', 'changed')
        touch(self.repo, 'docs/b.md', 'new'); git(self.repo, 'add', 'docs/b.md'); git(self.repo, 'commit', '--quiet', '-m', 'second')
        m = self.snapshot('2026-11-17')
        a, b = (os.path.join(self.root, 'archive', s) for s in ('2026-11-03', '2026-11-17'))
        same = f'workdir/parameters/production/p/soil.nc'
        self.assertEqual(os.stat(f'{a}/{same}').st_ino, os.stat(f'{b}/{same}').st_ino)   # unchanged: hard link
        self.assertNotEqual(os.stat(f'{a}/workdir/README.md').st_ino, os.stat(f'{b}/workdir/README.md').st_ino)
        with open(f'{a}/workdir/README.md') as fh:
            self.assertEqual(fh.read(), 'x')                                                # old snapshot untouched
        self.assertEqual(m['previous_snapshot'], '2026-11-03')
        self.assertEqual(os.readlink(os.path.join(self.root, 'current')), 'archive/2026-11-17')
        self.assertEqual(git(os.path.join(self.root, 'repo.git'), 'log', '-1', '--format=%s', 'main'), 'second')

    def test_existing_snapshot_or_staging_refused(self):
        self.snapshot('2026-11-03')
        with self.assertRaises(bs.SnapshotError):
            self.snapshot('2026-11-03')
        os.makedirs(os.path.join(self.root, 'archive', '2026-12-01.staging'))
        with self.assertRaises(bs.SnapshotError):
            self.snapshot('2026-12-01')

    def test_verification_failure_keeps_staging(self):
        real = bs.verify_copy
        def corrupt_then_verify(sources, staging, selection, processes):
            with open(os.path.join(staging, 'workdir', 'README.md'), 'w') as fh:
                fh.write('corrupted')
            return real(sources, staging, selection, processes)
        with mock.patch.object(bs, 'verify_copy', corrupt_then_verify):
            with self.assertRaises(bs.SnapshotError):
                self.snapshot('2026-11-03')
        staging = os.path.join(self.root, 'archive', '2026-11-03.staging')
        self.assertTrue(os.path.isdir(staging)); self.assertFalse(os.path.exists(os.path.join(self.root, 'current')))
        with open(os.path.join(staging, 'backup-manifest.json')) as fh:
            m = json.load(fh)
        self.assertEqual(m['status'], 'failed'); self.assertEqual(len(m['verification']['mismatches']), 1)

    def test_verify_detects_changed_copy(self):
        self.snapshot('2026-11-03')
        p = os.path.join(self.root, 'archive', '2026-11-03', 'workdir', 'README.md')
        os.chmod(p, 0o644)
        with open(p, 'w') as fh:
            fh.write('tampered')
        bad = bs.verify_snapshot(self.root, '2026-11-03', 2, log=self.log.append)
        self.assertEqual(len(bad), 1); self.assertIn('workdir/README.md', bad[0])

    def test_describe_lists_categories(self):
        p = bs.plan(self.W, self.repo, self.rules)
        text = bs.describe(p, self.W, self.repo, self.root, self.rules)
        self.assertIn('states', text); self.assertIn('does not exist yet', text)
        self.assertIn('runs/prod/seg-b: no run check or convergence test summary', text)
        self.assertEqual(p['summary']['states']['files'], 2)


class SubmitRenderTest(unittest.TestCase):
    def test_render_and_approval_required(self):
        sys.path.insert(0, os.path.join(REPO, 'workflow', '09_backup'))
        import submit_backup as sb
        env = {'ISIMIP4B_WORKDIR': '/w', 'ISIMIP4B_BACKUP': '/b'}
        with mock.patch.dict(os.environ, env), mock.patch.object(sb.jobrecord, 'conda_base', return_value='/c'), \
                mock.patch.object(sb.gitstate, 'state', return_value=('abc', False)):
            with mock.patch.object(sys, 'argv', ['submit_backup.py', '--dry-run']):
                with self.assertRaises(SystemExit):
                    sb.main()
            with mock.patch.object(sys, 'argv', ['submit_backup.py', '--list', '--dry-run']), \
                    mock.patch('builtins.print') as pr:
                sb.main()
            text = pr.call_args[0][0]
            self.assertIn('--dry-run', text); self.assertIn('ISIMIP4B_BACKUP=/b', text); self.assertIn('--time=01:00:00', text)
            with mock.patch.object(sys, 'argv', ['submit_backup.py', '--approved', 'user, 2026-11-03', '--dry-run',
                                                 '--snapshot-id', '2026-11-03']), mock.patch('builtins.print') as pr:
                sb.main()
            text = pr.call_args[0][0]
            self.assertIn('--run --processes 8 --snapshot-id 2026-11-03', text)
            self.assertIn('--job-name=backup-snapshot-2026-11-03', text); self.assertIn('--cpus-per-task=8', text)
            self.assertNotIn('{{', text)


if __name__ == '__main__':
    unittest.main()
