"""Unit tests for workflow/09_backup/backup_rules.py: the selection rules of a backup snapshot (D13).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '09_backup'))
import backup_rules as br  # noqa: E402

GITIGNORE = """# Scientific data and model products belong in ../workdir, never in Git.
*.nc
*.zarr/
*.npy

# Logs and scheduler output
*.log
*.out
slurm-*.out

# Build products
*.exe

# Python and notebook caches
__pycache__/
*.py[cod]

# Editor and OS files
*.swp
"""


def touch(root, rel, text='x'):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        fh.write(text)


def manifest(root, run, production, status):
    touch(root, f'{run}/run_manifest.json', json.dumps({'production': production, 'status': status}))


class Workdir:
    """A small workdir with every case of the rules."""
    ACCEPTED = 'runs/prod/seg-a'
    def __init__(self, root):
        self.root = root
        touch(root, 'README.md')
        touch(root, 'raw/ISIMIP4b/notes.txt')                       # raw/: excluded whole
        touch(root, 'scratch/task/job.sbatch')                      # scratch/: excluded whole
        touch(root, 'forcing/climate/u/2015.nc', 'nc')              # data type
        touch(root, 'forcing/climate/u/provenance.yaml')
        touch(root, 'forcing/climate/u/cache.zarr/0.0')             # directory pattern
        touch(root, 'logs/04_forcing/job_1/job.sbatch')
        touch(root, 'logs/04_forcing/job_1/slurm-1.out')
        touch(root, 'logs/04_forcing/job_1/job.yaml')
        touch(root, 'builds/vic/c/bin/vic_image.exe', 'exe')
        touch(root, 'builds/vic/c/build_manifest.json')
        touch(root, 'parameters/production/p/soil.nc', 'nc' * 3)   # whole
        touch(root, 'parameters/production/p/logs/promote.log')     # whole: even logs
        touch(root, 'parameters/candidates/q/soil.nc', 'nc')
        touch(root, 'postprocessed/s/qtot.nc', 'nc')                # whole
        touch(root, 'delivery/d/qtot.nc', 'nc')                     # whole
        touch(root, 'analysis/t/figure.png', 'png')
        touch(root, 'analysis/t/table.csv')
        touch(root, 'qc/forcing/u/summary.json')
        # accepted production run: manifest production + completed + qc summary
        manifest(root, self.ACCEPTED, True, 'completed')
        touch(root, 'qc/runs/prod/seg-a/summary.json')
        touch(root, f'{self.ACCEPTED}/config/job.sbatch')
        touch(root, f'{self.ACCEPTED}/states/state.1.nc', 'state')
        touch(root, f'{self.ACCEPTED}/chunks/1601-1625/states/state.2.nc', 'state2')
        touch(root, f'{self.ACCEPTED}/chunks/1601-1625/config/vic.txt')
        touch(root, f'{self.ACCEPTED}/chunks/1601-1625/output/daily.nc', 'out')
        touch(root, f'{self.ACCEPTED}/chunks/1601-1625/output/notes.txt')
        touch(root, f'{self.ACCEPTED}/logs/vic.log')
        # production run completed but not checked, and a non-production run
        manifest(root, 'runs/prod/seg-b', True, 'completed')
        touch(root, 'runs/prod/seg-b/states/state.nc', 'state')
        manifest(root, 'runs/smoke/r', False, 'completed')
        touch(root, 'runs/smoke/r/states/state.nc', 'state')
        touch(root, 'qc/runs/smoke/r/summary.json')
        os.symlink('../../../../forcing/climate/u/2015.nc', os.path.join(root, f'{self.ACCEPTED}/config/link.nc'))


class GitignoreTest(unittest.TestCase):
    def test_sections_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, '.gitignore', GITIGNORE)
            p = br.gitignore_patterns(os.path.join(d, '.gitignore'))
        self.assertEqual(p['Scientific data'], ['*.nc', '*.zarr/', '*.npy'])
        self.assertEqual(p['Logs and scheduler output'], ['*.log', '*.out', 'slurm-*.out'])
        self.assertEqual(p['Build products'], ['*.exe'])
        self.assertNotIn('Editor and OS files', p)

    def test_missing_section_stops(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, '.gitignore', '# Scientific data\n*.nc\n')
            with self.assertRaises(br.RulesError):
                br.gitignore_patterns(os.path.join(d, '.gitignore'))

    def test_real_gitignore_has_every_section(self):
        p = br.gitignore_patterns(os.path.join(REPO, '.gitignore'))
        self.assertIn('*.nc', p['Scientific data'])
        self.assertIn('slurm-*.out', p['Logs and scheduler output'])
        self.assertIn('*.exe', p['Build products'])
        self.assertIn('__pycache__/', p['Python and notebook caches'])


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Workdir(self.tmp.name)
        with tempfile.TemporaryDirectory() as d:
            touch(d, '.gitignore', GITIGNORE)
            self.rules = br.Rules.from_gitignore(os.path.join(d, '.gitignore'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_runs(self):
        runs = br.accepted_runs(self.w.root)
        self.assertIsNone(runs[Workdir.ACCEPTED])
        self.assertEqual(runs['runs/prod/seg-b'], 'no run check or convergence test summary')
        self.assertEqual(runs['runs/smoke/r'], 'not a production run')

    def test_selection(self):
        accepted = [r for r, why in br.accepted_runs(self.w.root).items() if why is None]
        sel = {rel: (cat, link) for rel, size, cat, link in br.select(self.w.root, self.rules, 'workdir', accepted)}
        kept = set(sel)
        for rel in ('README.md', 'forcing/climate/u/provenance.yaml', 'logs/04_forcing/job_1/job.sbatch',
                    'logs/04_forcing/job_1/job.yaml', 'builds/vic/c/build_manifest.json', 'analysis/t/figure.png',
                    'analysis/t/table.csv', 'qc/forcing/u/summary.json', f'{Workdir.ACCEPTED}/run_manifest.json',
                    f'{Workdir.ACCEPTED}/config/job.sbatch', f'{Workdir.ACCEPTED}/chunks/1601-1625/config/vic.txt',
                    'runs/prod/seg-b/run_manifest.json', 'runs/smoke/r/run_manifest.json'):
            self.assertIn(rel, kept, rel)
            self.assertEqual(sel[rel][0], 'workdir', rel)
        for rel in ('raw/ISIMIP4b/notes.txt', 'scratch/task/job.sbatch', 'forcing/climate/u/2015.nc',
                    'forcing/climate/u/cache.zarr/0.0', 'logs/04_forcing/job_1/slurm-1.out',
                    'builds/vic/c/bin/vic_image.exe', 'parameters/candidates/q/soil.nc',
                    f'{Workdir.ACCEPTED}/chunks/1601-1625/output/daily.nc',
                    f'{Workdir.ACCEPTED}/chunks/1601-1625/output/notes.txt', f'{Workdir.ACCEPTED}/logs/vic.log',
                    'runs/prod/seg-b/states/state.nc', 'runs/smoke/r/states/state.nc'):
            self.assertNotIn(rel, kept, rel)
        self.assertEqual(sel['parameters/production/p/soil.nc'], ('parameter-sets', False))
        self.assertEqual(sel['parameters/production/p/logs/promote.log'], ('parameter-sets', False))
        self.assertEqual(sel['postprocessed/s/qtot.nc'], ('products', False))
        self.assertEqual(sel['delivery/d/qtot.nc'], ('products', False))
        self.assertEqual(sel[f'{Workdir.ACCEPTED}/states/state.1.nc'], ('states', False))
        self.assertEqual(sel[f'{Workdir.ACCEPTED}/chunks/1601-1625/states/state.2.nc'], ('states', False))
        # a symbolic link is listed as itself (it ends in .nc, so the type rule drops it like any file)
        self.assertNotIn(f'{Workdir.ACCEPTED}/config/link.nc', kept)

    def test_symlink_kept_when_name_allowed(self):
        os.symlink('/nowhere', os.path.join(self.w.root, 'forcing/climate/u/view'))
        sel = {rel: link for rel, size, cat, link in br.select(self.w.root, self.rules, 'workdir', [])}
        self.assertTrue(sel['forcing/climate/u/view'])

    def test_summary(self):
        accepted = [Workdir.ACCEPTED]
        s = br.summarize(br.select(self.w.root, self.rules, 'workdir', accepted))
        self.assertEqual(s['states']['files'], 2)
        self.assertEqual(s['states']['bytes'], len('state') + len('state2'))
        self.assertEqual(s['parameter-sets']['files'], 2)
        self.assertEqual(s['products']['files'], 2)
        self.assertEqual(s['repo']['files'], 0)

    def test_repo_selection(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, '.git/HEAD'); touch(d, '.git/objects/ab/cd')
            touch(d, 'workflow/a.py'); touch(d, 'workflow/__pycache__/a.cpython-312.pyc')
            touch(d, 'docs/a.md'); touch(d, 'tests/out.log'); touch(d, 'configs/c.yaml')
            sel = {rel: cat for rel, size, cat, link in br.select(d, self.rules, 'repo')}
        self.assertEqual(set(sel), {'workflow/a.py', 'docs/a.md', 'configs/c.yaml'})
        self.assertEqual(set(sel.values()), {'repo'})


if __name__ == '__main__':
    unittest.main()
