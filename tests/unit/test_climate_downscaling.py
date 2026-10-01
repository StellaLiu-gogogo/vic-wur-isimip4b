"""Unit tests for workflow/04_forcing/climate/downscale_climate.py.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
Tests that compare with cdo are skipped when cdo is not on PATH.
"""
import importlib.util, os, shutil, subprocess, tempfile, unittest

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '04_forcing', 'climate', 'downscale_climate.py')
spec = importlib.util.spec_from_file_location('downscale_climate', SRC)
dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)

HAVE_CDO = shutil.which('cdo') is not None


def centres(start, step, n):
    return start + step * np.arange(n)


def synthetic_grids():
    """Coarse 3 degree global grid and a 0.5 degree 6 x 6 subdivision of part of it (like ISIMIP and VIC)."""
    clat = centres(-88.5, 3.0, 60); clon = centres(-178.5, 3.0, 120)
    flat = centres(-54.0 + 0.25, 0.5, 6 * 45)          # rows -54 .. 81, south to north
    flon = centres(-180.0 + 0.25, 0.5, 720)
    return clat, clon, flat, flon


def write_lonlat(path, lat, lon, field, name='x'):
    d = nc.Dataset(path, 'w')
    d.createDimension('lat', len(lat)); d.createDimension('lon', len(lon))
    v = d.createVariable('lat', 'f8', ('lat',)); v[:] = lat; v.units = 'degrees_north'; v.standard_name = 'latitude'
    v = d.createVariable('lon', 'f8', ('lon',)); v[:] = lon; v.units = 'degrees_east'; v.standard_name = 'longitude'
    v = d.createVariable(name, 'f8', ('lat', 'lon')); v[:] = field
    d.close()


def griddes(path, lat, lon):
    with open(path, 'w') as fh:
        fh.write(f'gridtype = lonlat\nxsize = {len(lon)}\nysize = {len(lat)}\nxfirst = {float(lon[0])!r}\n'
                 f'xinc = {float(lon[1] - lon[0])!r}\nyfirst = {float(lat[0])!r}\nyinc = {float(lat[1] - lat[0])!r}\n')


def cdo_remap(op, src_file, target_grid, out):
    subprocess.run(['cdo', '-s', '-O', f'{op},{target_grid}', src_file, out], check=True, capture_output=True)
    d = nc.Dataset(out); x = np.array(d['x'][:], 'f8'); lat = d['lat'][:]; d.close()
    return x[::-1] if lat[0] > lat[-1] else x


class GridTests(unittest.TestCase):
    def test_subdivision_index(self):
        clat, clon, flat, flon = synthetic_grids()
        idx, ratio = dc.subdivision_index(flat, clat)
        self.assertEqual(ratio, 6)
        self.assertTrue(np.all(np.abs(flat - clat[idx]) < 1.5))
        self.assertTrue(np.all(np.bincount(idx)[idx.min():] == 6))

    def test_subdivision_rejects_offset_grid(self):
        clat, _, flat, _ = synthetic_grids()
        with self.assertRaises(ValueError):
            dc.subdivision_index(flat + 0.1, clat)

    def test_linear_weights_wrap_longitude(self):
        clon = centres(-178.5, 3.0, 120)
        i0, i1, w = dc.linear_weights(np.array([179.75, -179.75]), clon, period=360.0)
        self.assertEqual((i0[0], i1[0]), (119, 0)); self.assertAlmostEqual(w[0], 1.25 / 3)   # 178.5 -> 181.5
        self.assertEqual((i0[1], i1[1]), (119, 0)); self.assertAlmostEqual(w[1], 1.75 / 3)   # -181.5 -> -178.5

    def test_linear_weights_no_extrapolation(self):
        with self.assertRaises(ValueError):
            dc.linear_weights(np.array([89.9]), centres(-88.5, 3.0, 60))

    def test_bilinear_reproduces_linear_field(self):
        clat, clon, flat, flon = synthetic_grids()
        rel = dc.GridRelation(clat, clon, flat, flon)
        c = 2.0 * clat[:, None] + 0.0 * clon[None, :] + 5.0
        np.testing.assert_allclose(rel.bilinear(c), 2.0 * flat[:, None] + 5.0 + 0 * flon[None, :], atol=1e-12)

    def test_replication_is_blockwise_and_conservative(self):
        clat, clon, flat, flon = synthetic_grids()
        rel = dc.GridRelation(clat, clon, flat, flon)
        rng = np.random.default_rng(1); c = rng.random((60, 120))
        f = rel.replicate(c)
        self.assertTrue(np.array_equal(f[:6, :6], np.full((6, 6), c[rel.ry[0], rel.rx[0]])))
        mask = rng.random(f.shape) > 0.4; area = np.cos(np.deg2rad(flat))[:, None] * np.ones_like(f)
        a = np.where(mask, area, 0)
        w05 = np.zeros_like(c); np.add.at(w05, (rel.ry[:, None].repeat(len(flon), 1), rel.rx[None, :].repeat(len(flat), 0)), a)
        self.assertAlmostEqual((f * a).sum() / a.sum(), (c * w05).sum() / w05.sum(), places=12)

    @unittest.skipUnless(HAVE_CDO, 'cdo not available')
    def test_against_cdo(self):
        clat, clon, flat, flon = synthetic_grids()
        rel = dc.GridRelation(clat, clon, flat, flon)
        rng = np.random.default_rng(2); c = rng.random((60, 120)) * 10
        with tempfile.TemporaryDirectory() as t:
            write_lonlat(f'{t}/c.nc', clat[::-1], clon, c[::-1])            # stored north to south, like ISIMIP
            griddes(f'{t}/f.grid', flat, flon)
            np.testing.assert_allclose(rel.bilinear(c), cdo_remap('remapbil', f'{t}/c.nc', f'{t}/f.grid', f'{t}/b.nc'), atol=1e-10)
            np.testing.assert_allclose(rel.replicate(c), cdo_remap('remapcon', f'{t}/c.nc', f'{t}/f.grid', f'{t}/k.nc'), atol=1e-10)
            np.testing.assert_allclose(rel.replicate(c), cdo_remap('remapnn', f'{t}/c.nc', f'{t}/f.grid', f'{t}/n.nc'), atol=0)

    def test_conservative_remap_preserves_mean(self):
        slat = centres(-90, 1.0, 181); slon = centres(0, 1.0, 360)   # points on integer degrees, like ERA5
        dlat = centres(-89, 2.0, 90); dlon = centres(-179, 2.0, 180)
        rng = np.random.default_rng(3); z = rng.random((181, 360))
        se, sw = dc.edges_from_centres(slat, -90, 90), dc.edges_from_centres(slon)
        de, dw = dc.edges_from_centres(dlat, -90, 90), dc.edges_from_centres(dlon)
        out = dc.conservative_remap(z, se, sw, de, dw)
        a_src = np.diff(np.sin(np.deg2rad(se)))[:, None] * np.ones((1, 360))
        a_dst = np.diff(np.sin(np.deg2rad(de)))[:, None] * np.ones((1, 180))
        self.assertAlmostEqual((z * a_src).sum() / a_src.sum(), (out * a_dst).sum() / a_dst.sum(), places=12)
        np.testing.assert_allclose(dc.conservative_remap(np.full_like(z, 7.0), se, sw, de, dw), 7.0, atol=1e-12)
        if HAVE_CDO:
            with tempfile.TemporaryDirectory() as t:
                write_lonlat(f'{t}/z.nc', slat[::-1], slon, z[::-1])
                griddes(f'{t}/d.grid', dlat, dlon)
                np.testing.assert_allclose(out, cdo_remap('remapcon', f'{t}/z.nc', f'{t}/d.grid', f'{t}/o.nc'), atol=1e-9)


class PhysicsTests(unittest.TestCase):
    def test_no_elevation_difference_changes_nothing(self):
        t = np.array([280.0]); p = np.array([95000.0]); q = np.array([0.006]); dz = np.array([0.0])
        self.assertEqual(dc.tair_downscaled(t, dz)[0], 280.0)
        self.assertAlmostEqual(dc.psurf_downscaled(p, t, q, dz)[0], 95000.0)

    def test_lapse_rate_and_hypsometric_equation(self):
        t = np.array([288.15]); p = np.array([101325.0]); q = np.array([0.0]); dz = np.array([1000.0])
        self.assertAlmostEqual(dc.tair_downscaled(t, dz)[0], 281.65)
        expected = 101325.0 * np.exp(-1000.0 * 9.80665 / (287.05 * (288.15 + 281.65) / 2))
        self.assertAlmostEqual(dc.psurf_downscaled(p, t, q, dz)[0], expected, places=6)
        self.assertTrue(89000 < expected < 90500)      # standard atmosphere at 1 km: 89 875 Pa

    def test_vapour_pressure_from_specific_humidity(self):
        q = np.array([0.01]); p = np.array([100000.0])
        self.assertAlmostEqual(dc.vapour_pressure(q, p)[0], (0.01 * 100000.0 / (0.622 + 0.378 * 0.01)), places=6)

    def test_svp_vic(self):
        self.assertAlmostEqual(float(dc.svp_vic(np.array(0.0))), 0.61078, places=5)
        self.assertAlmostEqual(float(dc.svp_vic(np.array(20.0))), 2.3383, places=3)
        self.assertLess(float(dc.svp_vic(np.array(-10.0))), 0.61078 * np.exp(17.269 * -10 / 227.3))

    def test_compute_units(self):
        clat, clon, flat, flon = synthetic_grids(); rel = dc.GridRelation(clat, clon, flat, flon)
        shape = (60, 120); dz = np.zeros((len(flat), len(flon)))
        src = {'pr': np.full(shape, 1e-5), 'tas': np.full(shape, 273.15), 'ps': np.full(shape, 100000.0),
               'huss': np.full(shape, 0.01), 'rsds': np.full(shape, 200.0)}
        np.testing.assert_allclose(dc.compute('prec', src, rel, dz), 0.864)
        np.testing.assert_allclose(dc.compute('tair', src, rel, dz), 0.0, atol=1e-12)
        np.testing.assert_allclose(dc.compute('psurf', src, rel, dz), 100.0)
        np.testing.assert_allclose(dc.compute('swdown', src, rel, dz), 200.0)
        np.testing.assert_allclose(dc.compute('vp', src, rel, dz), dc.svp_vic(np.array(0.0)), rtol=1e-12)  # capped
        src['tas'] = np.full(shape, 293.15)        # 20 degC: 1.6 kPa < svp 2.34 kPa, not capped
        np.testing.assert_allclose(dc.compute('vp', src, rel, dz), 1000.0 / (0.622 + 0.378 * 0.01) * 0.01 / 10, rtol=1e-12)

    def test_vp_capped_at_saturation_after_lifting(self):
        clat, clon, flat, flon = synthetic_grids(); rel = dc.GridRelation(clat, clon, flat, flon)
        shape = (60, 120); dz = np.full((len(flat), len(flon)), 1500.0)   # 1.5 km higher: 9.75 K colder
        src = {'tas': np.full(shape, 283.15), 'ps': np.full(shape, 100000.0), 'huss': np.full(shape, 0.0075)}
        vp = dc.compute('vp', src, rel, dz); tair = dc.compute('tair', src, rel, dz)
        self.assertTrue(np.all(vp <= dc.svp_vic(tair) * (1 + 1e-12)))
        np.testing.assert_allclose(vp, dc.svp_vic(tair), rtol=1e-12)


def independent_lwdown(src, dz, clat, clon, flat, flon):
    """lwdown written out here without the producer's helpers: np.repeat for replication, np.interp for
    bilinear, Satterlund emissivity, Cosgrove ratio."""
    k = 6
    i0 = int(round((flat[0] - (clat[0] - 1.5)) / 0.5)) // k          # first coarse row of the fine grid
    rep = lambda c: np.repeat(np.repeat(c[i0:i0 + len(flat) // k], k, axis=0), k, axis=1)
    def bil(c):
        ext_lon = np.concatenate([[clon[-1] - 360], clon, [clon[0] + 360]])
        t = np.array([np.interp(flon, ext_lon, np.concatenate([[row[-1]], row, [row[0]]])) for row in c])
        return np.array([np.interp(flat, clat, t[:, j]) for j in range(len(flon))]).T
    tas, ps, q, rl = rep(src['tas']), rep(src['ps']), bil(src['huss']), bil(src['rlds'])
    r = q / (1 - q); t1 = tas - 0.0065 * dz
    p1 = ps * np.exp(-dz * 9.80665 / (287.05 * 0.5 * (tas + t1) * (1 + 0.61 * r)))
    t1c = t1 - 273.15
    es = 0.61078 * np.exp(17.269 * t1c / (237.3 + t1c)); es = np.where(t1c < 0, es * (1 + 0.00972 * t1c + 0.000042 * t1c ** 2), es)
    e1 = np.minimum(r / (0.622 + r) * p1 / 1000.0, es) * 10.0
    t0c = tas - 273.15
    es0 = 0.61078 * np.exp(17.269 * t0c / (237.3 + t0c)); es0 = np.where(t0c < 0, es0 * (1 + 0.00972 * t0c + 0.000042 * t0c ** 2), es0)
    e0 = np.minimum(r / (0.622 + r) * ps / 1000.0, es0) * 10.0
    eps = lambda T, e: 1.08 * (1 - np.exp(-e ** (T / 2016.0)))
    return eps(t1, e1) * t1 ** 4 / (eps(tas, e0) * tas ** 4) * rl


class LongwaveTests(unittest.TestCase):
    def test_emissivity_hand_values(self):
        # eps = 1.08 (1 - exp(-e^(T/2016))): e = 1 hPa gives e^x = 1 for any T, so eps = 1.08 (1 - 1/e)
        self.assertAlmostEqual(float(dc.emissivity(253.15, 1.0)), 1.08 * (1 - np.exp(-1.0)), places=12)
        self.assertAlmostEqual(float(dc.emissivity(253.15, 1.0)), 0.682690, places=6)
        self.assertAlmostEqual(float(dc.emissivity(273.15, 6.11)), 0.779093, places=6)   # 6.11^0.135491 = 1.277914
        self.assertAlmostEqual(float(dc.emissivity(293.15, 23.4)), 0.857905, places=6)   # 23.4^0.145412 = 1.581612
        self.assertAlmostEqual(float(dc.emissivity(300.0, 30.0)), 0.874416, places=6)    # 30^0.148810 = 1.658860

    def test_ratio_sign_in_a_column(self):
        clat, clon, flat, flon = synthetic_grids(); rel = dc.GridRelation(clat, clon, flat, flon)
        shape = (60, 120)
        src = {'tas': np.full(shape, 285.0), 'ps': np.full(shape, 95000.0), 'huss': np.full(shape, 0.005),
               'rlds': np.full(shape, 320.0)}
        for h, cmp in ((0.0, 'eq'), (800.0, 'lt'), (-800.0, 'gt')):
            if h == 0.0:   # also with a supersaturated 0.5 degree level: both levels are capped alike
                src_sat = dict(src, huss=np.full(shape, 0.03))
                np.testing.assert_allclose(dc.compute('lwdown', src_sat, rel, np.zeros((len(flat), len(flon)))),
                                           320.0, rtol=1e-12)
            lw = dc.compute('lwdown', src, rel, np.full((len(flat), len(flon)), h))
            if cmp == 'eq':
                np.testing.assert_allclose(lw, 320.0, rtol=1e-12)
            elif cmp == 'lt':
                self.assertTrue(np.all(lw < 320.0))
            else:
                self.assertTrue(np.all(lw > 320.0))

    def test_lwdown_against_independent_implementation(self):
        clat, clon, flat, flon = synthetic_grids(); rel = dc.GridRelation(clat, clon, flat, flon)
        rng = np.random.default_rng(4); shape = (60, 120)
        src = {'tas': 250 + 45 * rng.random(shape), 'ps': 70000 + 32000 * rng.random(shape),
               'huss': 0.0005 + 0.018 * rng.random(shape), 'rlds': 150 + 300 * rng.random(shape)}
        dz = rng.normal(0, 600, (len(flat), len(flon)))
        np.testing.assert_allclose(dc.compute('lwdown', src, rel, dz),
                                   independent_lwdown(src, dz, clat, clon, flat, flon), rtol=1e-10)


class TimeAndSelectionTests(unittest.TestCase):
    def _time(self, days):
        d = nc.Dataset('t.nc', 'w', diskless=True)
        d.createDimension('time', len(days))
        t = d.createVariable('time', 'f8', ('time',)); t.units = 'days since 2015-1-1 00:00:00'
        t.calendar = 'proleptic_gregorian'; t[:] = days
        return d

    def test_year_indices_leap_year(self):
        d = self._time(np.arange(0, 731) + 0.5)          # 2015 and 2016
        idx, n = dc.year_indices(d['time'], 2016)
        self.assertEqual(n, 366); self.assertEqual(idx[0], 365); d.close()

    def test_year_indices_gap(self):
        days = np.delete(np.arange(0, 365) + 0.5, 100)
        d = self._time(days)
        with self.assertRaises(ValueError):
            dc.year_indices(d['time'], 2015)
        d.close()

    def test_variable_selection(self):
        # D16 decided: lwdown is a forcing unit like the others
        self.assertEqual(dc.select_variables(None, to_scratch=False), list(dc.VARIABLES))
        self.assertEqual(dc.select_variables('tair,lwdown', to_scratch=False), ['tair', 'lwdown'])
        with self.assertRaises(SystemExit):
            dc.select_variables('tas', to_scratch=True)


if __name__ == '__main__':
    unittest.main()
