"""Unit tests for the verifiers of the adopted components (workflow/03_parameters/{domain,routing,irrigation,
water_use}/): the routing walk (outlets, closed loops, unresolved and non-neighbour links, accumulation), the
water-use links and their order, the cell areas, the range checks and the file integrity against a manifest
entry, on small synthetic grids.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import datetime, importlib.util, os, sys, tempfile, unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, '..', '..', 'workflow', '03_parameters')
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow'))


def load(name, path):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


adopted = load('adopted', os.path.join(P, 'domain', 'adopted.py'))
vd = load('verify_domain', os.path.join(P, 'domain', 'verify_domain.py'))
vr = load('verify_routing', os.path.join(P, 'routing', 'verify_routing.py'))
vi = load('verify_irrigation', os.path.join(P, 'irrigation', 'verify_irrigation.py'))
vw = load('verify_water_use', os.path.join(P, 'water_use', 'verify_water_use.py'))


class RoutingWalkTest(unittest.TestCase):
    # active cells 0..5 with ids 10..15; 0 -> 1 -> 2 (outlet), 3 -> 2, 4 <-> 5 a closed loop
    IDS = np.array([10, 11, 12, 13, 14, 15])

    def test_network_outlets_and_unresolved(self):
        nxt, nf = vr.network(self.IDS, np.array([11, 12, 12, 12, 15, 99]))
        self.assertEqual(nxt.tolist(), [1, 2, 2, 2, 5, 5])   # 99 is no active id: the cell becomes an outlet
        self.assertEqual(nf.tolist(), [5])

    def test_walk_tree(self):
        nxt, _ = vr.network(self.IDS, np.array([11, 12, 12, 12, 15, 15]))
        cyclic, outlet, levels = vr.walk(nxt)
        self.assertEqual(cyclic.size, 0)
        self.assertEqual(outlet.tolist(), [2, 2, 2, 2, 5, 5])
        self.assertEqual(levels, 3)

    def test_walk_finds_loop_and_cells_behind_it(self):
        # 4 -> 5 -> 4 is a loop; 3 drains into it
        nxt = np.array([1, 2, 2, 4, 5, 4])
        cyclic, outlet, _ = vr.walk(nxt)
        self.assertEqual(sorted(cyclic.tolist()), [4, 5])
        self.assertEqual(outlet.tolist(), [2, 2, 2, -1, -1, -1])

    def test_walk_long_loop(self):
        n = 50
        nxt = (np.arange(n) + 1) % n            # one loop through every cell
        cyclic, outlet, _ = vr.walk(nxt)
        self.assertEqual(cyclic.size, n)
        self.assertTrue((outlet == -1).all())

    def test_accumulation_equals_basin_sums(self):
        rng = np.random.default_rng(1)
        n = 400
        nxt = np.arange(n)
        for i in range(1, n):                    # random tree: every cell drains to a lower index, 0..9 outlets
            if i >= 10:
                nxt[i] = rng.integers(0, i)
        w = rng.uniform(1, 2, n)
        _, outlet, _ = vr.walk(nxt)
        acc = vr.accumulate(nxt, w); bs = vr.basin_sums(outlet, w)
        outs = np.flatnonzero(nxt == np.arange(n))
        np.testing.assert_allclose(acc[outs], bs[outs], rtol=1e-12)
        self.assertAlmostEqual(acc[outs].sum(), w.sum())

    def test_neighbour_links_wrap_at_dateline(self):
        rows = np.array([0, 0, 0, 3]); cols = np.array([0, 9, 5, 5])
        nxt = np.array([1, 0, 3, 3])             # 0 <-> 9 across the dateline (nlon 10), 2 -> 3 jumps 3 rows
        self.assertEqual(vr.neighbour_links(nxt, rows, cols, 10).tolist(), [2])

    def test_place_station_best_area(self):
        mask = np.ones((5, 5), bool); mask[2, 2] = False
        upa = np.full((5, 5), 10.0); upa[1, 3] = 98.0; upa[4, 4] = 300.0
        glat = np.arange(5.0); glon = np.arange(5.0)
        i, j, a, e = vr.place_station(2.0, 2.0, 100.0, upa, mask, glat, glon, radius=1)
        self.assertEqual((i, j), (1, 3)); self.assertAlmostEqual(e, -0.02)


class WaterUseTest(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(vw.resolve(np.array([5, 7, 9]), np.array([9, 5, 6])).tolist(), [1, -1, 0])

    def test_levels_tree_and_water_use(self):
        # routing 0 -> 1 -> 2 (outlet); cell 3 (outlet) withdraws from 1: 1 waits for 0 and for 3
        before = [0, 1, 3]; after = [1, 2, 1]
        lev = vw.dependency_levels(4, before, after)
        self.assertEqual(lev.tolist(), [1, 2, 3, 1])

    def test_levels_loop(self):
        # routing 0 -> 1 (outlet); 0 withdraws from 1 is fine, but 1 also withdraws from 0: 0 waits for 1
        lev = vw.dependency_levels(3, [0, 0, 1], [1, 1, 0])
        self.assertEqual(lev.tolist(), [0, 0, 1])

    def test_within_steps(self):
        nxt = np.array([1, 2, 3, 3])
        hit = vw.within_steps(nxt, np.array([0, 0, 3]), np.array([3, 3, 0]), 3)
        self.assertEqual(hit.tolist(), [True, True, False])
        self.assertFalse(vw.within_steps(nxt, np.array([0]), np.array([3]), 2)[0])


class DomainTest(unittest.TestCase):
    def test_sphere_area_sums_to_sphere(self):
        lat = np.arange(-89.5, 90); lon = np.arange(-179.5, 180)
        a = vd.sphere_area(lat, lon, step=1.0)
        self.assertAlmostEqual(a.sum() / (4 * np.pi * vd.R_AUTHALIC ** 2), 1.0, places=12)
        np.testing.assert_allclose(vd.sphere_area(lat[::-1], lon, step=1.0), a[::-1])

    def test_ellipsoid_area_sums_to_wgs84_surface(self):
        lat = np.arange(-89.5, 90); lon = np.arange(-179.5, 180)
        self.assertAlmostEqual(vd.ellipsoid_area(lat, lon, step=1.0).sum() / 5.10065621724e14, 1.0, places=9)

    def test_grid_check(self):
        lat = np.arange(-56 + 1 / 24, 84, 1 / 12); lon = np.arange(-180 + 1 / 24, 180, 1 / 12)
        self.assertEqual(vd.grid_check(lat, lon)['status'], 'passed')
        self.assertEqual(vd.grid_check(lat[::-1], lon)['lat']['order'], 'decreasing')
        self.assertEqual(vd.grid_check(lat + 0.01, lon)['status'], 'failed')
        bad = lat.copy(); bad[[3, 4]] = bad[[4, 3]]
        self.assertEqual(vd.grid_check(bad, lon)['status'], 'failed')


class ValuesTest(unittest.TestCase):
    def test_is_fill(self):
        self.assertEqual(adopted.is_fill(np.array([1.0, -1.0, np.nan]), -1.0).tolist(), [False, True, True])
        self.assertEqual(adopted.is_fill(np.array([1, -1]), None).tolist(), [False, False])
        self.assertEqual(adopted.is_fill(np.array([1.0, np.nan]), float('nan')).tolist(), [False, True])

    def test_irrigation_value_check(self):
        mask = np.array([[True, True, False]])
        ok = vi.value_check(np.array([[0.5, 1.0, -1.0]]), -1.0, mask, 0.0, 1.0, low_open=True)
        self.assertEqual(ok['status'], 'passed')
        self.assertEqual(ok['cells_outside_mask_with_values'], 0)
        fill = vi.value_check(np.array([[0.5, -1.0, 0.3]]), -1.0, mask, 0.0, 1.0, low_open=True)
        self.assertEqual((fill['status'], fill['active_cells_fill'], fill['cells_outside_mask_with_values']),
                         ('failed', 1, 1))
        zero = vi.value_check(np.array([[0.0, 0.2, -1.0]]), -1.0, mask, 0.0, 1.0, low_open=True)
        self.assertEqual(zero['active_cells_out_of_range'], 1)
        self.assertEqual(vi.value_check(np.array([[0.0, 0.2, -1.0]]), -1.0, mask, 0.0, 1.0)['status'], 'passed')


class IntegrityTest(unittest.TestCase):
    def test_file_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f'{d}/c')
            with open(f'{d}/c/f.nc', 'wb') as fh:
                fh.write(b'abc')
            t = datetime.datetime(2026, 8, 4, 12).timestamp()
            os.utime(f'{d}/c/f.nc', (t, t))
            md5 = adopted.hashing.md5(f'{d}/c/f.nc')
            entry = {'source_mtime': datetime.date(2026, 8, 4), 'adopted_on': datetime.date(2026, 10, 4),
                     'files': [{'path': 'c/f.nc', 'size_bytes': 3, 'md5': md5}]}
            today = datetime.date.today()
            r = adopted.file_integrity(d, entry, '2026-09-29')
            # the ctime of the test file is today, after the adoption day: a warning, not a failure
            self.assertEqual(r['status'], 'warning' if today > datetime.date(2026, 10, 4) else 'passed')
            self.assertEqual(r['files'][0]['problems'], [])
            bad = dict(entry, files=[{'path': 'c/f.nc', 'size_bytes': 4, 'md5': '0' * 32}])
            r = adopted.file_integrity(d, bad, '2026-09-29')
            self.assertEqual(r['status'], 'failed')
            self.assertEqual(len(r['files'][0]['problems']), 2)
            moved = dict(entry, source_mtime=datetime.date(2026, 8, 3))
            self.assertIn('modification day differs from source_mtime',
                          adopted.file_integrity(d, moved, '2026-09-29')['files'][0]['problems'])
            t2 = datetime.datetime(2026, 10, 5, 12).timestamp(); os.utime(f'{d}/c/f.nc', (t2, t2))
            self.assertIn('modified after adoption', adopted.file_integrity(d, entry, '2026-09-29')['files'][0]['problems'])
            gone = dict(entry, files=[{'path': 'c/missing.nc', 'md5': md5}])
            self.assertEqual(adopted.file_integrity(d, gone, '2026-09-29')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
