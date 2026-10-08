"""Unit tests for the land-use forcing driver (workflow/04_forcing/landuse/).

The allocation itself is checked by verify_forcing.py on real output; these tests cover the driver rules:
an existing forcing unit is never written into, the year range is checked, the Slurm job is rendered
completely with the verifier pointed at the producer's output, and the file format VIC reads (time axis and
calendar) is written by the producer and checked by the verifier.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from common import gitstate

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


class ClosureTest(unittest.TestCase):
    def test_residual_goes_to_existing_class(self):
        lu = load_producer('/nonexistent')
        import numpy as np
        mask = np.array([[True, True, True, False]])
        Cv = np.zeros((16, 1, 4))
        Cv[11, 0, 0] = 0.6; Cv[13, 0, 0] = 0.4 - 2e-16           # no natural class: residual to class 12 (largest)
        Cv[11, 0, 1] = 0.5; Cv[4, 0, 1] = 0.3; Cv[9, 0, 1] = 0.2 - 1e-16   # natural present: residual to class 5
        Cv[12, 0, 2] = 0.7; Cv[14, 0, 2] = 0.5                     # managed sum > 1: rescaled, natural zero
        out, over1, n_man = lu.close_cells(Cv.copy(), mask)
        self.assertEqual(out[0, 0, 0], 0.0)                         # class 1 never gets the residual
        self.assertEqual(int((out[:, 0, 0] > 0).sum()), 2)          # no new class in the cell
        self.assertEqual(int((out[:, 0, 1] > 0).sum()), 3)
        self.assertGreater(out[11, 0, 0], 0.6)                      # residual added to the largest class
        self.assertGreater(out[4, 0, 1], 0.3)
        self.assertTrue(over1[0, 2] and not over1[0, 0])
        self.assertAlmostEqual(out[:, 0, 2].sum(), 1.0, places=15)
        self.assertEqual(n_man, 1)
        self.assertTrue(np.allclose(out[:, 0, :3].sum(axis=0), 1, atol=1e-15))


def load_verifier(workdir):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}):
        spec = importlib.util.spec_from_file_location('lu_verifier', os.path.join(LANDUSE, 'verify_forcing.py'))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class FormatTest(unittest.TestCase):
    """VIC aborts when the calendar of a plugin forcing file differs from its clock (PROLEPTIC_GREGORIAN)."""
    def setUp(self):
        import numpy as np
        self.np = np; self.tmp = tempfile.TemporaryDirectory()
        self.lu = load_producer('/nonexistent'); self.vf = load_verifier('/nonexistent')
        self.lat = np.array([-1.0, 1.0]); self.lon = np.array([10.0, 11.0, 12.0])
        self.fn = os.path.join(self.tmp.name, 'coverage_histsoc_2016.nc')
        Cv = np.zeros((16, 2, 3), 'f4'); Cv[11] = 1.0
        self.lu.write_coverage(self.fn, Cv, self.lat, self.lon, 'histsoc', 2016, {})

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        import netCDF4 as nc
        with nc.Dataset(self.fn) as d:
            return self.vf.check_format(d, self.fn, self.lat, self.lon)

    def test_producer_writes_vic_calendar(self):
        import netCDF4 as nc
        with nc.Dataset(self.fn) as d:
            self.assertEqual(d['time'].calendar, 'proleptic_gregorian')
            self.assertEqual(d['time'].units, 'days since 2016-01-01 00:00:00')
            self.assertEqual(list(d['time'][:]), [0.0])
        f = self.check()
        self.assertTrue(f['ok'], f)

    def test_verifier_rejects_other_calendar(self):
        import netCDF4 as nc
        with nc.Dataset(self.fn, 'a') as d:
            d['time'].calendar = 'standard'                       # the method 1.3 files
        f = self.check()
        self.assertEqual(f['calendar'], 'standard')
        self.assertFalse(f['ok'])

    def test_verifier_rejects_other_grid_and_year(self):
        import netCDF4 as nc
        with nc.Dataset(self.fn) as d:
            self.assertFalse(self.vf.check_format(d, self.fn, self.lat, self.lon + 1)['ok'])
        other = os.path.join(self.tmp.name, 'coverage_histsoc_2017.nc'); os.rename(self.fn, other)
        with nc.Dataset(other) as d:
            self.assertFalse(self.vf.check_format(d, other, self.lat, self.lon)['ok'])


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

    def dry_run_clean(self, *args):
        """--dry-run in this process with the Git state replaced by a clean repository, so that the result does not
        depend on the state of the working copy that runs the tests."""
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent/workdir'}):
            sys.modules.pop('isimip_landuse_to_vic_annual', None)       # imported by the submit script by name
            spec = importlib.util.spec_from_file_location('lu_submit', os.path.join(LANDUSE, 'submit_landuse_forcing.py'))
            sub = importlib.util.module_from_spec(spec); spec.loader.exec_module(sub)
        out = io.StringIO()
        with mock.patch.object(gitstate, 'state', return_value=('0' * 40, False)), \
                mock.patch.object(sub.jobrecord, 'conda_base', return_value='/conda'), \
                mock.patch.object(sys, 'argv', ['submit', *args, '--dry-run']), redirect_stdout(out):
            sub.main()
        return out.getvalue()

    def test_unit_job(self):
        text = self.dry_run_clean('--scenario', 'ssp1vlsoc-noadapt', '--years', '2022-2100')
        self.assertNotIn('{{', text)
        self.assertIn('--processes 16', text)
        self.assertIn('#SBATCH --mem=144G', text)
        self.assertIn('#SBATCH --job-name=landuse-forcing-ssp1vlsoc-noadapt-2022-2100\n', text)
        self.assertNotIn('--unit-dir', text)                     # clean repository: the verifier checks the unit itself
        self.assertNotIn('--scratch', text)

    def test_verify_only_job(self):
        text = self.dry_run('--scenario', 'histsoc', '--years', '1850-2021', '--verify-only')
        self.assertIn('if [ "no" = yes ]', text)                   # producer not run
        self.assertIn('#SBATCH --job-name=landuse-forcing-histsoc-1850-2021-verify', text)
        self.assertNotIn('--unit-dir', text)                       # the unit itself, even from a dirty repository
        self.assertIn('if [ "yes" = yes ]', self.dry_run('--scenario', 'histsoc', '--years', '2015', '--scratch'))


if __name__ == '__main__':
    unittest.main()
