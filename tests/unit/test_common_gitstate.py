"""Unit tests for workflow/common/gitstate.py in a temporary Git repository.

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, subprocess, tempfile, unittest

from common import gitstate


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.org', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@example.org')
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


class GitStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.repo = r = self.tmp.name
        git(r, 'init', '-q')
        os.makedirs(f'{r}/workflow/stage'); os.makedirs(f'{r}/workflow/common')
        for p, text in (('workflow/stage/a.py', 'a = 1\n'), ('workflow/common/b.py', 'b = 2\n')):
            with open(f'{r}/{p}', 'w') as fh:
                fh.write(text)
        git(r, 'add', '-A'); git(r, 'commit', '-q', '-m', 'first')

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_and_dirty(self):
        commit, dirty = gitstate.state(self.repo)
        self.assertEqual(commit, git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual(len(commit), 40)
        self.assertFalse(dirty)
        with open(f'{self.repo}/untracked.txt', 'w') as fh:     # an untracked file makes the repository not clean
            fh.write('x')
        self.assertTrue(gitstate.state(self.repo)[1])
        os.remove(f'{self.repo}/untracked.txt')
        with open(f'{self.repo}/workflow/stage/a.py', 'a') as fh:  # so does a modified tracked file
            fh.write('# edit\n')
        self.assertEqual(gitstate.state(self.repo), (commit, True))

    def test_tree_hashes(self):
        h = gitstate.tree_hashes(self.repo, ['workflow/stage', 'workflow/common', 'workflow/missing'])
        self.assertEqual(list(h), ['workflow/stage', 'workflow/common', 'workflow/missing'])
        self.assertEqual(h['workflow/stage'], git(self.repo, 'rev-parse', 'HEAD:workflow/stage'))
        self.assertIsNone(h['workflow/missing'])
        # trees are those of HEAD: an uncommitted edit does not change them, a commit of one directory changes
        # only that directory's hash
        with open(f'{self.repo}/workflow/stage/a.py', 'a') as fh:
            fh.write('# edit\n')
        self.assertEqual(gitstate.tree_hashes(self.repo, ['workflow/stage']), {'workflow/stage': h['workflow/stage']})
        git(self.repo, 'commit', '-q', '-am', 'edit')
        h2 = gitstate.tree_hashes(self.repo, ['workflow/stage', 'workflow/common'])
        self.assertNotEqual(h2['workflow/stage'], h['workflow/stage'])
        self.assertEqual(h2['workflow/common'], h['workflow/common'])

    def test_not_a_repository_stops(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                gitstate.state(d)


if __name__ == '__main__':
    unittest.main()
