"""Unit tests for the land-use forcing driver (workflow/04_forcing/landuse/).

The allocation itself is checked by verify_forcing.py on real output; these tests cover the driver rules:
an existing forcing unit is never overwritten (extended only under the rules of common/unit_extension.py), the
year range is checked, the start years of D20 (--start-years: the constant field of the scenario's first year with
the start year's time axis, 1850soc and 2021soc only) are written and recorded and the verifier checks their
source year, the Slurm job is rendered completely with the verifier pointed at the producer's output, and the
file format VIC reads (time axis and calendar) is written by the producer and checked by the verifier.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import numpy as np
import netCDF4 as nc

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

    def inputs(self):
        """Input files that exist (content irrelevant: the producer stops before reading them in these tests)."""
        for rel in [self.lu.SCEN['histsoc'][0], self.lu.SCEN['histsoc'][1]]:
            p = os.path.join(self.lu.RAW, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()
        p = os.path.join(self.W, 'parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc')
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()
        for y in self.lu.WEIGHT_YEARS:
            p = self.lu.COVERAGE.format(y=y); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()

    def test_existing_unit_without_fingerprint_cannot_be_extended(self):
        """The units made before the fingerprint block existed (histsoc, the SSP units) are never written into."""
        self.inputs()
        unit = os.path.join(self.W, 'forcing', 'landuse', 'histsoc'); os.makedirs(unit)
        with open(os.path.join(unit, 'provenance.yaml'), 'w') as fh:
            fh.write('forcing_unit: landuse/histsoc\nmethod:\n  version: "1.4"\nfiles:\n- path: coverage_histsoc_2014.nc\n')
        with mock.patch.object(self.lu.gitstate, 'tree_hashes', return_value={}):
            msg = self.run_main(['--scenario', 'histsoc', '--years', '2015'])
        self.assertIn('cannot be extended', msg); self.assertIn('code tree None', msg)
        self.assertEqual(os.listdir(unit), ['provenance.yaml'])

    def test_year_already_in_the_unit_and_incomplete_unit(self):
        self.inputs()
        unit = os.path.join(self.W, 'forcing', 'landuse', 'histsoc'); os.makedirs(unit)
        with open(os.path.join(unit, 'provenance.yaml'), 'w') as fh:
            fh.write('files:\n- path: coverage_histsoc_2015.nc\n')
        with mock.patch.object(self.lu.gitstate, 'tree_hashes', return_value={}):
            self.assertIn('already contains [2015]', self.run_main(['--scenario', 'histsoc', '--years', '2015']))
        os.remove(os.path.join(unit, 'provenance.yaml')); open(os.path.join(unit, 'coverage_histsoc_2015.nc'), 'w').close()
        with mock.patch.object(self.lu.gitstate, 'tree_hashes', return_value={}):
            self.assertIn('incomplete unit', self.run_main(['--scenario', 'histsoc', '--years', '2016']))

    def test_start_years_option(self):
        lu = self.lu
        self.assertEqual(lu.parse_start_years('1850soc', '2022,1601,1551'), [1551, 1601, 2022])
        self.assertEqual(lu.parse_start_years('2021soc', '1850'), [1850])
        self.assertEqual(lu.parse_start_years('1850soc', None), [])
        for scen, text, msg in (('histsoc', '1601', 'allowed for 1850soc, 2021soc only'), ('ssp1vlsoc-noadapt', '2021', 'allowed for'),
                                ('1850soc', '1601,1900', 'lie inside the years of 1850soc'), ('2021soc', '2022', 'lie inside'),
                                ('1850soc', '1601,1601', 'distinct')):
            with self.assertRaises(SystemExit) as cm:
                lu.parse_start_years(scen, text)
            self.assertIn(msg, str(cm.exception))
        self.assertEqual(lu.source_year_of('1850soc', 1601), 1850); self.assertEqual(lu.source_year_of('1850soc', 1900), 1900)
        self.assertEqual(lu.source_year_of('2021soc', 1825), 2022); self.assertEqual(lu.source_year_of('2021soc', 2100), 2100)
        with self.assertRaises(ValueError):
            lu.source_year_of('histsoc', 1601)
        self.assertIn('give --years and/or --start-years', self.run_main(['--scenario', '1850soc']))
        self.assertIn('allowed for', self.run_main(['--scenario', 'histsoc', '--start-years', '1601']))

    def test_scratch_does_not_touch_existing_unit(self):
        unit = os.path.join(self.W, 'forcing', 'landuse', 'histsoc'); os.makedirs(unit)
        open(os.path.join(unit, 'provenance.yaml'), 'w').close()
        err = io.StringIO()
        with mock.patch.object(self.lu, 'git_state', return_value=('0' * 40, False)), \
                mock.patch.object(sys, 'argv', ['producer', '--scenario', 'histsoc', '--years', '2015', '--scratch',
                                                '--scratch-label', 'unit-test']), redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                self.lu.main()
        self.assertIn('missing input', str(cm.exception.code))      # stops at the inputs, after choosing the scratch location
        self.assertIn(os.path.join('scratch', 'landuse-converter', 'runs', 'unit-test', 'histsoc'), err.getvalue())
        self.assertEqual(os.listdir(unit), ['provenance.yaml'])    # the unit is not even looked at

    def test_year_range(self):
        self.assertIn('covers 1850-2021', self.run_main(['--scenario', 'histsoc', '--years', '2020-2022']))
        self.assertIn('covers 2022-2100', self.run_main(['--scenario', 'ssp3hsoc-noadapt', '--years', '2021']))

    def test_scratch_label_needs_scratch(self):
        self.assertIn('--scratch-label needs', self.run_main(['--scenario', 'histsoc', '--years', '2015',
                                                               '--scratch-label', 'x']))
        self.assertIn('--scratch-label needs', self.run_main(['--scenario', 'histsoc', '--years', '2015', '--scratch',
                                                               '--scratch-label', 'Bad_Label']))


class StartYearsDriverTest(unittest.TestCase):
    """main() on a tiny synthetic workdir: the allocation (convert_year) and the weights cache are stand-ins, the
    files, provenance.yaml and the extension path are real. 1850soc with the start years 1601 (new unit) and 1551
    (extension)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name; self.lu = lu = load_producer(self.W)
        for rel in lu.SCEN['1850soc'][:2]:
            p = os.path.join(lu.RAW, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write(rel)
        for y in lu.WEIGHT_YEARS:
            p = lu.COVERAGE.format(y=y); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write(str(y))
        self.dom = os.path.join(self.W, 'parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc')
        os.makedirs(os.path.dirname(self.dom))
        with nc.Dataset(self.dom, 'w') as d:
            d.createDimension('lat', 2); d.createDimension('lon', 3)
            d.createVariable('lat', 'f8', ('lat',))[:] = [-1.0, 1.0]; d.createVariable('lon', 'f8', ('lon',))[:] = [10.0, 11.0, 12.0]
            d.createVariable('mask', 'i4', ('lat', 'lon'))[:] = np.ones((2, 3), 'i4')
        self.unit = os.path.join(self.W, 'forcing', 'landuse', '1850soc')
        self.converted = []

    def tearDown(self):
        self.tmp.cleanup()

    def convert(self, scen, year, P, grid, a, f15, furb):
        """Stand-in for the allocation: the coverage depends on the (source) year, so a copied year is visible."""
        self.converted.append(year)
        Cv = np.zeros((16, 2, 3), 'f4'); Cv[11] = 0.25; Cv[0] = 0.75; Cv[1] = year * 1e-6
        return Cv, {'runtime_s': 0.0, 'year': year, 'closure': {'max_abs_sum_minus_1_active': 0.0}}, ['0,0,0,0,12,1,1,0,1,0']

    def main(self, argv):
        lu = self.lu
        with mock.patch.object(lu, 'git_state', return_value=('n' * 40, False)), \
                mock.patch.object(lu.gitstate, 'tree_hashes', return_value={'workflow/04_forcing/landuse': 't', 'workflow/common': 'c'}), \
                mock.patch.object(lu, 'weights', return_value=(np.zeros((16, 2, 3)), os.path.join(self.W, 'scratch/w.npz'), 'k')), \
                mock.patch.object(lu, 'convert_year', self.convert), mock.patch.object(sys, 'argv', ['producer'] + argv), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            lu.main()

    def prov(self):
        import yaml
        with open(os.path.join(self.unit, 'provenance.yaml')) as fh:
            return yaml.safe_load(fh)

    def test_new_unit_with_a_start_year_then_extension(self):
        self.main(['--scenario', '1850soc', '--years', '1850-1851', '--start-years', '1601'])
        self.assertEqual(self.converted, [1850, 1850, 1851])               # 1601 is converted from the 1850 data
        p = self.prov()
        self.assertEqual([f['year'] for f in p['files']], [1601, 1850, 1851])
        self.assertEqual(p['start_years'], {1601: 1850}); self.assertEqual(p['years'], '1601-1851')
        self.assertIn('--start-years 1601', p['rebuild_command']); self.assertIn('--years 1850-1851', p['rebuild_command'])
        self.assertEqual(p['fingerprint']['code_tree'], {'workflow/04_forcing/landuse': 't', 'workflow/common': 'c'})
        self.assertEqual(set(p['input_sha256']), set(p['inputs'])); self.assertEqual(len(p['inputs']), 23)
        self.assertEqual(p['qc']['status'], 'not_checked'); self.assertNotIn('extended', p)
        with nc.Dataset(os.path.join(self.unit, 'coverage_1850soc_1601.nc')) as d, \
                nc.Dataset(os.path.join(self.unit, 'coverage_1850soc_1850.nc')) as s:
            self.assertEqual((int(d.year), int(d.source_year)), (1601, 1850))
            self.assertEqual(d['time'].units, 'days since 1601-01-01 00:00:00')
            self.assertTrue(np.array_equal(d['coverage'][:], s['coverage'][:]))
            self.assertNotIn('source_year', s.ncattrs())
        # the extension: the same code, one more start year; existing files untouched
        before = {f: os.stat(os.path.join(self.unit, f)).st_mtime_ns for f in os.listdir(self.unit) if f.endswith('.nc')}
        self.converted.clear()
        self.main(['--scenario', '1850soc', '--start-years', '1551'])
        self.assertEqual(self.converted, [1850])
        p = self.prov()
        self.assertEqual([f['year'] for f in p['files']], [1551, 1601, 1850, 1851])
        self.assertEqual(p['start_years'], {1551: 1850, 1601: 1850}); self.assertEqual(p['years'], '1551-1851')
        self.assertEqual(len(p['extended']), 1)
        self.assertEqual((p['extended'][0]['years'], p['extended'][0]['start_years']), ([1551], {1551: 1850}))
        self.assertEqual({f: os.stat(os.path.join(self.unit, f)).st_mtime_ns for f in before}, before)
        # a year already present, and a year inside the scenario given as a start year, are refused
        for argv, msg in ((['--start-years', '1601'], 'already contains [1601]'), (['--start-years', '1900'], 'lie inside')):
            with self.assertRaises(SystemExit) as cm:
                self.main(['--scenario', '1850soc'] + argv)
            self.assertIn(msg, str(cm.exception))
        self.assertEqual([f['year'] for f in self.prov()['files']], [1551, 1601, 1850, 1851])


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

    def test_verifier_start_year_rule(self):
        """A file outside the scenario years passes only for a constant scenario, with source_year = first year and
        the same entry in provenance (start_years)."""
        import netCDF4 as nc
        Cv = np.zeros((16, 2, 3), 'f4'); Cv[11] = 1.0
        fn = os.path.join(self.tmp.name, 'coverage_1850soc_1601.nc')
        self.lu.write_coverage(fn, Cv, self.lat, self.lon, '1850soc', 1601, {}, source_year=1850)
        with nc.Dataset(fn) as d:
            self.assertEqual(int(d.source_year), 1850)
            f = self.vf.check_format(d, fn, self.lat, self.lon, '1850soc', {1601: 1850})
            self.assertTrue(f['ok'], f); self.assertEqual(f['source_year'], 1850)
            self.assertFalse(self.vf.check_format(d, fn, self.lat, self.lon, '1850soc', {})['ok'])          # not in provenance
            self.assertFalse(self.vf.check_format(d, fn, self.lat, self.lon, '1850soc', {1601: 1851})['ok'])  # other source
        other = os.path.join(self.tmp.name, 'coverage_histsoc_1601.nc'); os.rename(fn, other)
        with nc.Dataset(other) as d:
            self.assertFalse(self.vf.check_format(d, other, self.lat, self.lon, 'histsoc', {1601: 1850})['ok'])  # not constant
        # a year inside the scenario must not carry a source_year of another year
        with nc.Dataset(self.fn, 'a') as d:
            d.source_year = 2015
        with nc.Dataset(self.fn) as d:
            self.assertFalse(self.vf.check_format(d, self.fn, self.lat, self.lon, 'histsoc', {})['ok'])
        self.assertEqual(self.vf.expected_source_year('2021soc', 1800, {1800: 2022}), 2022)
        self.assertIsNone(self.vf.expected_source_year('2021soc', 1800, {}))
        self.assertEqual(self.vf.expected_source_year('2021soc', 2050, {}), 2050)

    def test_verifier_rejects_other_grid_and_year(self):
        import netCDF4 as nc
        with nc.Dataset(self.fn) as d:
            self.assertFalse(self.vf.check_format(d, self.fn, self.lat, self.lon + 1)['ok'])
        other = os.path.join(self.tmp.name, 'coverage_histsoc_2017.nc'); os.rename(self.fn, other)
        with nc.Dataset(other) as d:
            self.assertFalse(self.vf.check_format(d, other, self.lat, self.lon)['ok'])


class WeightsCacheTest(unittest.TestCase):
    """Review P3 C1 (a): the weights cache (VIC 2003-2022 mean class pattern) is keyed by the sha256 of its inputs (the
    domain file and the VIC coverage files) and used only when its key and grid match; it is written under a name of
    its own and published by rename."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        self.lu = load_producer(W)
        self.lat, self.lon = np.array([0.0, 1.0]), np.array([0.0, 1.0, 2.0]); self.mask = np.ones((2, 3), bool)
        os.makedirs(f'{W}/raw'); self.cov = f'{W}/raw/coverage_{{y}}.nc'
        for y, v in ((2003, 0.25), (2004, 0.75)):
            with nc.Dataset(self.cov.format(y=y), 'w') as d:
                d.createDimension('time', 1); d.createDimension('veg_class', 16)
                d.createDimension('lat', 2); d.createDimension('lon', 3)
                d.createVariable('lat', 'f8', ('lat',))[:] = self.lat; d.createVariable('lon', 'f8', ('lon',))[:] = self.lon
                d.createVariable('coverage', 'f4', ('time', 'veg_class', 'lat', 'lon'), fill_value=np.nan)[:] = v
        self.dom = f'{W}/domain.nc'
        with open(self.dom, 'w') as fh:
            fh.write('domain')
        self.patches = [mock.patch.object(self.lu, 'COVERAGE', self.cov), mock.patch.object(self.lu, 'WEIGHT_YEARS', [2003, 2004]),
                        mock.patch.object(self.lu, 'CACHE_DIR', f'{W}/scratch/landuse-converter')]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        self.tmp.cleanup()

    def weights(self):
        with redirect_stdout(io.StringIO()):
            return self.lu.weights(self.dom, self.lat, self.lon, self.mask)

    def test_built_once_and_reused(self):
        P, path, key = self.weights()
        self.assertTrue(np.allclose(P, 0.5))
        self.assertIn(key[:16], os.path.basename(path))
        with mock.patch.object(self.lu, 'build_weights_cache', side_effect=AssertionError('rebuilt')):
            P2, path2, key2 = self.weights()                           # same inputs: the cache is used
        self.assertEqual((path2, key2), (path, key)); self.assertTrue(np.array_equal(P, P2))

    def test_changed_input_is_not_reused(self):
        _, path, key = self.weights()
        with open(self.dom, 'w') as fh:
            fh.write('another domain')
        P, path2, key2 = self.weights()
        self.assertNotEqual(key2, key); self.assertNotEqual(path2, path)

    def test_cache_of_other_key_or_grid_refused(self):
        _, path, key = self.weights()
        self.assertIsNone(self.lu.load_weights(path, 'x' * 64, self.mask.shape))
        self.assertIsNone(self.lu.load_weights(path, key, (3, 3)))
        with open(path, 'w') as fh:
            fh.write('truncated')
        self.assertIsNone(self.lu.load_weights(path, key, self.mask.shape))


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

    def test_start_years_job(self):
        text = self.dry_run_clean('--scenario', '1850soc', '--years', '1850-2021', '--start-years', '1601,2022,1551,1576')
        self.assertIn('#SBATCH --job-name=landuse-forcing-1850soc-1850-2021-start-1551-1576-1601-2022\n', text)
        self.assertEqual(text.count('--years 1850-2021 --start-years 1551,1576,1601,2022'), 2)   # producer and verifier
        text = self.dry_run_clean('--scenario', '2021soc', '--start-years', '1850', '--verify-only')
        self.assertIn('#SBATCH --job-name=landuse-forcing-2021soc-start-1850-verify', text)
        self.assertIn('--processes 1', text)
        with self.assertRaises(SystemExit):
            self.dry_run_clean('--scenario', 'histsoc', '--start-years', '1601')

    def test_verify_only_job(self):
        text = self.dry_run_clean('--scenario', 'histsoc', '--years', '1850-2021', '--verify-only')
        self.assertIn('if [ "no" = yes ]', text)                   # producer not run
        self.assertIn('#SBATCH --job-name=landuse-forcing-histsoc-1850-2021-verify', text)
        self.assertNotIn('--unit-dir', text)                       # the unit itself
        verifier = [l for l in text.splitlines() if 'verify_forcing.py' in l][0]
        self.assertIn('--expect-commit ' + '0' * 40, verifier)     # (a repository that is not clean: test_submit_job_decision)
        self.assertIn('if [ "yes" = yes ]', self.dry_run('--scenario', 'histsoc', '--years', '2015', '--scratch'))


if __name__ == '__main__':
    unittest.main()
