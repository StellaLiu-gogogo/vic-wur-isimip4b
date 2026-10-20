"""Unit tests for the spin-up start years of the climate producer and verifier (D20, task P): a start year outside the
input is written as a copy of its cycle year (data unchanged, time axis and year of the start year), recorded under
start_years and cycle_windows; the verifier checks the copy against the unit's file of the cycle year. The cycle rule
of the producer, the verifier and the renderer (workflow/05_simulation/render/forcing_years.py) must agree.

Synthetic files on a 3 x 4 grid in a temporary directory; no ISIMIP input is read.

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import contextlib, importlib.util, io, os, sys, tempfile, unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
import netCDF4 as nc

from common import hashing, provenance

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


dc = load('downscale_climate_start_years', 'workflow/04_forcing/climate/downscale_climate.py')
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'render'))
import forcing_years as fy   # noqa: E402

GCM, ALIAS, VAR = 'ec-earth3-esm-1-1', 'esm-picontrol', 'tair'
UNIT = f'climate/{GCM}/{ALIAS}/{VAR}'
LAT, LON = np.array([-1.0, 0.0, 1.0]), np.array([10.0, 11.0, 12.0, 13.0])


def source_file(path, year):
    """A small daily file of `year` as the producer writes it, day k filled with k + 0.5 (fill value on one cell)."""
    n = 366 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 365
    o, x = dc.create_output(path, VAR, LAT, LON, year, n, {'year': np.int32(year), 'code_commit': 'c' * 40,
                                                          'source_files': f'raw input of {year}'})
    for k in range(n):
        a = np.full((3, 4), k + 0.5, 'f4'); a[0, 0] = dc.FILL
        x[k] = a
    o.close()


class CycleRuleTest(unittest.TestCase):
    def test_same_rule_everywhere(self):
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': os.environ.get('ISIMIP4B_WORKDIR', tempfile.gettempdir())}):
            vf = load('verify_forcing_start_years', 'workflow/04_forcing/climate/verify_forcing.py')
        for window in ((1601, 1610), (1601, 1650), (1800, 1849)):
            for y in range(1500, 1900):
                s = dc.cycle_source(y, window)
                self.assertEqual(s, fy.cycle_source(y, window), (y, window))
                self.assertEqual(s, vf.cycle_year(y, window), (y, window))

    def test_d20_years(self):
        self.assertEqual(dc.cycle_source(1591, (1601, 1610)), 1601)
        self.assertEqual(dc.cycle_source(1551, (1601, 1650)), 1601)
        self.assertEqual(dc.cycle_source(1576, (1601, 1650)), 1628)


class CopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.udir = os.path.join(self.W, 'forcing', UNIT); os.makedirs(self.udir)
        self.src = os.path.join(self.udir, dc.out_name(VAR, GCM, ALIAS, 1601))
        source_file(self.src, 1601)
        self.out = os.path.join(self.W, 'out'); os.makedirs(self.out)
        ctx = {'W': self.W, 'gcm': GCM, 'alias': ALIAS, 'unit': {VAR: UNIT}, 'out_dir': {VAR: self.out},
               'source_files': {VAR: {1601: self.src}}, 'window': [1601, 1610],
               'attrs': {'code_commit': 'd' * 40, 'code_dirty': 'false', 'created_by': dc.CREATED_BY,
                         'created_at': 't'}, 'commit': 'd' * 40}
        with contextlib.redirect_stdout(io.StringIO()):
            _, self.records = dc.copy_start_year({'var': VAR, 'years': {1591: 1601}, 'ctx': ctx})
        self.copy = os.path.join(self.out, dc.out_name(VAR, GCM, ALIAS, 1591))

    def tearDown(self):
        self.tmp.cleanup()

    def test_data_unchanged_time_restamped(self):
        with nc.Dataset(self.copy) as d, nc.Dataset(self.src) as s:
            d.set_auto_mask(False); s.set_auto_mask(False)
            self.assertTrue(np.array_equal(d[VAR][:], s[VAR][:]))
            self.assertEqual(d['time'].units, 'days since 1591-01-01 00:00:00')
            self.assertTrue(np.array_equal(d['time'][:], np.arange(365)))
            self.assertEqual((int(d.year), int(d.source_year)), (1591, 1601))
            self.assertEqual(list(d.cycle_window), [1601, 1610])
            self.assertEqual(d.source_file, f'forcing/{UNIT}/{os.path.basename(self.src)}')
            self.assertEqual(d.code_commit, 'd' * 40)
            self.assertEqual(d[VAR].chunking(), [1, 3, 4])
        self.assertEqual(self.records[0]['sha256'], hashing.sha256(self.copy))

    def test_other_day_count_refused(self):
        ctx = {'W': self.W, 'gcm': GCM, 'alias': ALIAS, 'unit': {VAR: UNIT}, 'out_dir': {VAR: self.out},
               'source_files': {VAR: {1601: self.src}}, 'window': [1601, 1610], 'attrs': {}, 'commit': 'd' * 40}
        with self.assertRaises(SystemExit):     # 1592 is a leap year, 1601 is not
            dc.copy_start_year({'var': VAR, 'years': {1592: 1601}, 'ctx': ctx})

    def verifier(self):
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}):   # the verifier reads the workdir on import
            vf = load('verify_forcing_start_years_w', 'workflow/04_forcing/climate/verify_forcing.py')
        start = {'source': 1601, 'window': [1601, 1610], 'source_path': os.path.basename(self.src),
                 'source_sha256': hashing.sha256(self.src), 'unit': UNIT}
        return vf, start

    def test_verifier_accepts_copy(self):
        vf, start = self.verifier()
        with nc.Dataset(self.copy) as d:
            d.set_auto_mask(False)
            c = vf.check_start_year(d, VAR, 1591, start, self.udir, UNIT)
        self.assertTrue(c['ok'], c)
        self.assertEqual(c['days_differing_from_source'], 0)

    def test_verifier_finds_changed_day(self):
        vf, start = self.verifier()
        with nc.Dataset(self.copy, 'a') as d:
            d[VAR][100, 1, 1] = 99.0
        with nc.Dataset(self.copy) as d:
            d.set_auto_mask(False)
            c = vf.check_start_year(d, VAR, 1591, start, self.udir, UNIT)
        self.assertFalse(c['ok']); self.assertEqual(c['days_differing_from_source'], 1)

    def test_verifier_finds_wrong_window(self):
        vf, start = self.verifier()
        start['window'] = [1601, 1650]           # 1591 -> 1641 in this window
        with nc.Dataset(self.copy) as d:
            d.set_auto_mask(False)
            self.assertFalse(vf.check_start_year(d, VAR, 1591, start, self.udir, UNIT)['ok'])


class RefusalTest(unittest.TestCase):
    def args(self, starts, window='1601-1610'):
        return SimpleNamespace(gcm=GCM, alias=ALIAS, start_years=starts, cycle_window=window, processes=1)

    def test_year_of_the_input_refused(self):
        with mock.patch.object(dc, 'input_has_year', return_value=True):
            with self.assertRaises(SystemExit):
                dc.write_start_years(self.args('1800'), '/nonexistent', 'c', False, True, [VAR], {VAR: UNIT}, {})

    def test_year_inside_window_refused(self):
        with mock.patch.object(dc, 'input_has_year', return_value=False):
            with self.assertRaises(SystemExit):
                dc.write_start_years(self.args('1605'), '/nonexistent', 'c', False, True, [VAR], {VAR: UNIT}, {})

    def test_unit_without_cycle_year_refused(self):
        with tempfile.TemporaryDirectory() as W:
            udir = os.path.join(W, 'forcing', UNIT); os.makedirs(udir)
            provenance.write(os.path.join(udir, 'provenance.yaml'),
                             {'forcing_unit': UNIT, 'code_dirty': False, 'qc': {'status': 'passed'},
                              'files': [{'path': dc.out_name(VAR, GCM, ALIAS, 1602), 'year': 1602, 'sha256': 'x'}]})
            with mock.patch.object(dc, 'input_has_year', return_value=False), \
                    mock.patch.object(dc.gitstate, 'tree_hashes', return_value={}):
                with self.assertRaises(SystemExit) as e:
                    dc.write_start_years(self.args('1591'), W, 'c', False, True, [VAR], {VAR: UNIT},
                                         {VAR: os.path.join(W, 'out')})
            self.assertIn('1601', str(e.exception))


if __name__ == '__main__':
    unittest.main()
