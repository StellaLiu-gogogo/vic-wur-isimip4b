"""Unit tests for the land-use forcing driver (workflow/04_forcing/landuse/).

The allocation itself is checked by verify_forcing.py on real output; these tests cover the driver rules:
an existing forcing unit is never written into, the year range is checked, and the Slurm job is rendered
completely with the verifier pointed at the producer's output.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
LANDUSE = os.path.join(HERE, '..', '..', 'workflow', '04_forcing', 'landuse')


def load_producer(workdir):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}):
        spec = importlib.util.spec_from_file_location('lu_producer', os.path.join(LANDUSE, 'isimip_landuse_to_vic_annual.py'))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class ProducerDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.lu = load_producer(self.W)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, dirty=False):
        with mock.patch.object(self.lu, 'git_state', return_value=('0' * 40, dirty)), \
                mock.patch.object(sys, 'argv', ['producer'] + argv), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.lu.main()
        return str(cm.exception.code)

    def test_refuses_existing_unit(self):
        unit = os.path.join(self.W, 'forcing', 'landuse', 'histsoc'); os.makedirs(unit)
        open(os.path.join(unit, 'provenance.yaml'), 'w').close()
        msg = self.run_main(['--scenario', 'histsoc', '--years', '2015'])
        self.assertIn('generated as a whole', msg)
        self.assertEqual(os.listdir(unit), ['provenance.yaml'])

    def test_scratch_does_not_touch_existing_unit(self):
        unit = os.path.join(self.W, 'forcing', 'landuse', 'histsoc'); os.makedirs(unit)
        open(os.path.join(unit, 'provenance.yaml'), 'w').close()
        msg = self.run_main(['--scenario', 'histsoc', '--years', '2015', '--scratch', '--scratch-label', 'unit-test'])
        self.assertIn('missing input', msg)          # stops at the inputs, after choosing the scratch location
        self.assertTrue(os.path.isdir(os.path.join(self.W, 'scratch', 'landuse-converter', 'runs', 'unit-test', 'histsoc')))
        self.assertEqual(os.listdir(unit), ['provenance.yaml'])

    def test_year_range(self):
        self.assertIn('covers 1850-2021', self.run_main(['--scenario', 'histsoc', '--years', '2020-2022']))
        self.assertIn('covers 2022-2100', self.run_main(['--scenario', 'ssp3hsoc-noadapt', '--years', '2021']))

    def test_scratch_label_needs_scratch(self):
        self.assertIn('--scratch-label needs', self.run_main(['--scenario', 'histsoc', '--years', '2015',
                                                               '--scratch-label', 'x']))
        self.assertIn('--scratch-label needs', self.run_main(['--scenario', 'histsoc', '--years', '2015', '--scratch',
                                                               '--scratch-label', 'Bad_Label']))


class SubmitRenderTest(unittest.TestCase):
    def dry_run(self, *args):
        env = dict(os.environ, ISIMIP4B_WORKDIR='/nonexistent/workdir')
        r = subprocess.run([sys.executable, os.path.join(LANDUSE, 'submit_landuse_forcing.py'), *args, '--dry-run'],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_scratch_job(self):
        text = self.dry_run('--scenario', 'histsoc', '--years', '2015-2016', '--scratch', '--scratch-label', 'test')
        self.assertNotIn('{{', text)
        self.assertIn('--processes 2', text)                     # capped at the number of years
        self.assertIn('#SBATCH --mem=18G', text)
        self.assertIn('#SBATCH --job-name=landuse-forcing-histsoc-2015-2016-scratch-test', text)
        self.assertIn('--unit-dir /nonexistent/workdir/scratch/landuse-converter/runs/test/histsoc', text)

    def test_unit_job(self):
        text = self.dry_run('--scenario', 'ssp1vlsoc-noadapt', '--years', '2022-2100')
        self.assertIn('--processes 16', text)
        self.assertIn('#SBATCH --mem=144G', text)
        if '-scratch' not in text:                               # clean repository: production unit
            self.assertNotIn('--unit-dir', text)


if __name__ == '__main__':
    unittest.main()
