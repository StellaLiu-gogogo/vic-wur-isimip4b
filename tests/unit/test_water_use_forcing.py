"""Unit tests for the water-use forcing producer (workflow/04_forcing/water_use/).

The real output is checked by verify_forcing.py; these tests cover the method on synthetic grids: volume
conservation, the even-split fallback, lost-demand accounting, the time-axis decoding of the ISIMIP3 files, source
orientation and fill handling, the consumption-fraction fallback, the groundwater gap filling, the unit
conversion, and the driver rules (existing unit, year range).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, io, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from unittest import mock

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
WATER_USE = os.path.join(HERE, '..', '..', 'workflow', '04_forcing', 'water_use')


def load_producer(workdir):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}):
        spec = importlib.util.spec_from_file_location('wu_producer', os.path.join(WATER_USE, 'downscale_water_use.py'))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class MethodTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.wu = load_producer(self.tmp.name)
        self.rng = np.random.default_rng(42)

    def tearDown(self):
        self.tmp.cleanup()

    def test_conservation(self):
        parent = self.rng.uniform(0, 1e8, (2, 3))
        weight = self.rng.uniform(0, 10, (12, 18))
        active = self.rng.uniform(size=(12, 18)) > 0.3
        child, cls, rep = self.wu.split_volume(parent, weight, active)
        back = child.reshape(2, 6, 3, 6).sum(axis=(1, 3))
        np.testing.assert_allclose(back, parent, rtol=1e-12)
        self.assertTrue((child[~active] == 0).all())
        self.assertLess(rep['max_parent_relative_residual'], 1e-12)
        self.assertTrue((cls == 1).all())

    def test_even_split_fallback(self):
        parent = np.array([[36.0]]); weight = np.zeros((6, 6)); active = np.zeros((6, 6), bool)
        active[:2, :] = True                                  # 12 active children, no population
        child, cls, rep = self.wu.split_volume(parent, weight, active)
        np.testing.assert_allclose(child[active], 3.0)
        self.assertTrue((child[~active] == 0).all())
        self.assertEqual(cls[0, 0], 2); self.assertEqual(rep['parents_even_split'], 1)
        self.assertAlmostEqual(rep['even_split_km3'], 36e-9)

    def test_weight_outside_active_cells_is_ignored(self):
        parent = np.array([[10.0]]); weight = np.zeros((6, 6)); active = np.zeros((6, 6), bool)
        weight[0, 0] = 5.0                                    # population only in an inactive child
        active[3, 3] = active[4, 4] = True
        child, cls, _ = self.wu.split_volume(parent, weight, active)
        self.assertEqual(cls[0, 0], 2)
        np.testing.assert_allclose(child[active], 5.0)

    def test_lost_accounting(self):
        parent = np.array([[7e9, 3e9]]); weight = np.ones((6, 12)); active = np.zeros((6, 12), bool)
        active[:, 6:] = True                                  # first parent has no active child
        child, cls, rep = self.wu.split_volume(parent, weight, active)
        self.assertEqual(cls.tolist(), [[3, 1]])
        self.assertEqual(rep['parents_lost'], 1); self.assertAlmostEqual(rep['lost_km3'], 7.0)
        self.assertAlmostEqual(rep['child_km3'], 3.0); self.assertAlmostEqual(rep['source_km3'], 10.0)

    def test_decode_years(self):
        dy = self.wu.decode_years
        np.testing.assert_array_equal(dy('years since 1901-1-1 03:00:00', np.arange(-51, 0)), np.arange(1850, 1901))
        v = np.arange(121, dtype='f8'); v[104:] -= 0.000336        # offsets from 2005 on, as in the ISIMIP3a files
        np.testing.assert_array_equal(dy('years since 1901-1-1 03:00:00', v), np.arange(1901, 2022))
        np.testing.assert_array_equal(dy('days since 1901-01-01', [41638.0, 42003.0], 'standard'), [2015, 2016])
        with self.assertRaises(ValueError):
            dy('years since 1901-1-1 03:00:00', [0, 1, 3])
        with self.assertRaises(ValueError):
            dy('years since 1901-1-1 03:00:00', [0, 1.4])

    def test_read_source_orientation_and_fill(self):
        path = os.path.join(self.tmp.name, 'ssp.nc')
        o = nc.Dataset(path, 'w'); o.createDimension('time', 2); o.createDimension('lat', 360); o.createDimension('lon', 720)
        t = o.createVariable('time', 'f8', ('time',)); t[:] = [41638.0, 42003.0]; t.units = 'days since 1901-01-01'; t.calendar = 'standard'
        o.createVariable('lat', 'f8', ('lat',))[:] = 89.75 - 0.5 * np.arange(360)
        o.createVariable('lon', 'f8', ('lon',))[:] = -179.75 + 0.5 * np.arange(720)
        v = o.createVariable('domww', 'f4', ('time', 'lat', 'lon'), fill_value=np.float32(1e20))
        x = np.zeros((2, 360, 720), 'f4'); x[1, 12, 5] = 7.0           # 83.75N in 2016
        x[1, 291, 0] = 3.0                                             # 55.75S
        v[:] = x; v[1, 100, 100] = np.ma.masked
        o.close()
        field, bad = self.wu.read_source(path, 'domww', 2016)
        self.assertEqual(field.shape, (280, 720))
        self.assertEqual(field[-1, 5], 7.0); self.assertEqual(field[0, 0], 3.0)   # flipped to south-to-north
        self.assertEqual(int(bad.sum()), 1); self.assertEqual(field[bad][0], 0.0)
        d = nc.Dataset(path, 'a'); d['domww'][1, 50, 50] = -1.0; d.close()
        with self.assertRaises(SystemExit):
            self.wu.read_source(path, 'domww', 2016)

    def test_consumption_fraction_fallback_and_cap(self):
        ww = np.array([[10.0, 0.0, 4.0], [0.0, 5.0, 0.0]])
        wc = np.array([[2.0, 0.0, 8.0], [0.0, 1.0, 0.0]])
        cont = np.array([[0, 0, 1], [-1, 1, 1]])
        f, rep = self.wu.consumption_fraction(ww, wc, cont, 2)
        np.testing.assert_allclose(f, [[0.2, 0.2, 1.0], [11 / 19, 0.2, 1.0]])
        self.assertEqual(rep['cells_capped_at_1'], 1); self.assertEqual(rep['cells_fallback'], 3)

    def test_unit_conversion(self):
        area = np.array([1e6, 1e6])
        np.testing.assert_allclose(self.wu.volume_to_mm_per_day(np.array([3.65e5, 0.0]), area, 2015), [1.0, 0.0])
        np.testing.assert_allclose(self.wu.volume_to_mm_per_day(np.array([3.66e5]), area[:1], 2020), [1.0])
        self.assertEqual(self.wu.days_in_year(1900), 365); self.assertEqual(self.wu.days_in_year(2000), 366)

    def test_groundwater_gap_fill(self):
        lut = os.path.join(self.tmp.name, 'lut.txt'); tab = os.path.join(self.tmp.name, 'tab.txt')
        with open(lut, 'w') as fh:
            fh.write('Arc_ID\tlon\tlat\tcont_area_km2\r\n1\t0.25\t10.25\t1\r\n2\t3.75\t10.25\t1\r\n')
        with open(tab, 'w') as fh:
            fh.write('"Arc_ID"\t"VALUE"\r\n1\t0.200000\r\n2\t0.600000\r\n')
        target = np.zeros((280, 720), bool)
        i = int((10.25 + 55.75) / 0.5); j0 = int((0.25 + 179.75) / 0.5)
        target[i, j0:j0 + 7] = True                  # Arc_ID cells at j0 and j0 + 7; j0 + 1 .. j0 + 6 have none
        target[i, j0 + 20] = True                    # 6.5 degrees east of the second, about 710 km away
        g, beyond, rep = self.wu.groundwater_parent(tab, lut, target)
        np.testing.assert_allclose(g[i, j0:j0 + 7], [0.2, 0.2, 0.2, 0.2, 0.6, 0.6, 0.6])
        self.assertEqual(g[i, j0 + 20], 0.0); self.assertTrue(beyond[i, j0 + 20])
        self.assertEqual(rep['target_without_arc_id'], 7); self.assertEqual(rep['beyond_bound_set_to_zero'], 1)
        self.assertLess(rep['distance_km_max_filled'], self.wu.GW_MAX_KM)

    def test_replicate_and_blocks(self):
        p = np.arange(6.0).reshape(2, 3)
        c = self.wu.replicate(p)
        self.assertEqual(c.shape, (12, 18))
        np.testing.assert_array_equal(self.wu.blocks(c).mean(axis=1), p.ravel())


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name; self.wu = load_producer(self.W)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, dirty=False):
        with mock.patch.object(self.wu, 'git_state', return_value=('0' * 40, dirty)), \
                mock.patch.object(sys, 'argv', ['producer'] + argv), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.wu.main()
        return str(cm.exception.code)

    def test_refuses_existing_unit(self):
        unit = os.path.join(self.W, 'forcing', 'water_use', 'histsoc'); os.makedirs(unit)
        open(os.path.join(unit, 'municipal_demand_histsoc_2015.nc'), 'w').close()
        self.assertIn('exists and is not empty', self.run_main(['--scenario', 'histsoc', '--years', '2015']))

    def test_year_range(self):
        self.assertIn('covers 2022-2100', self.run_main(['--scenario', 'ssp3hsoc-noadapt', '--years', '2021']))
        self.assertIn('covers 1850-2021', self.run_main(['--scenario', '1850soc', '--years', '2020-2022']))

    def test_sources_follow_the_amended_decision(self):
        s = self.wu.source_spec('ssp1vlsoc-noadapt', 'ind', 2050)
        self.assertIn('ssp126soc-noadapt/indww-modelavg_ssp126', s['ww'][0]); self.assertEqual(s['ww'][2], 2050)
        self.assertIn('2015soc/indwc_2015soc', s['cf_wc'][0]); self.assertEqual(s['cf_wc'][2], 2015)
        s = self.wu.source_spec('2021soc', 'dom', 2080)
        self.assertIn('ISIMIP3a', s['ww'][0]); self.assertEqual(s['ww'][2], 2021)
        s = self.wu.source_spec('1850soc', 'dom', 2018)
        self.assertIn('1850soc/domww_1850soc_annual_2015_2100', s['ww'][0])
        s = self.wu.source_spec('histsoc', 'dom', 1900)
        self.assertIn('histsoc_annual_1850_1900', s['ww'][0])


if __name__ == '__main__':
    unittest.main()
