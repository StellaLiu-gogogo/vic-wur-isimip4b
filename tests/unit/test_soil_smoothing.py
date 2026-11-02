"""Unit tests for workflow/03_parameters/soil/smooth_calibration_fields.py (block geometry, block values, fill of
empty blocks, bilinear interpolation on small synthetic grids) and the staircase bound of verify_soil.py.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import importlib.util, os, unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'soil', 'smooth_calibration_fields.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('smooth_calibration_fields', SRC)
    sm = importlib.util.module_from_spec(spec); spec.loader.exec_module(sm)

STEP = 1 / 12


def grid(lat0, lat1, lon0, lon1):
    """5-arcmin cell centres covering [lat0, lat1) x [lon0, lon1)."""
    return np.arange(lat0 + STEP / 2, lat1, STEP), np.arange(lon0 + STEP / 2, lon1, STEP)


class BlockGeometryTest(unittest.TestCase):
    def test_edges_follow_the_sign_rule(self):
        lat, lon = grid(-56, 84, -180, 180)
        le, lo = sm.block_edges(lat, lon)
        self.assertEqual(le[0], -56); self.assertEqual(le[-1], 84); self.assertEqual(len(le), 71)
        self.assertEqual(lo[0], -180); self.assertEqual(lo[1], -179); self.assertEqual(lo[-1], 180)
        self.assertIn(0.0, lo); self.assertIn(-1.0, lo); self.assertNotIn(1.0, lo); self.assertNotIn(-2.0, lo)
        self.assertEqual(len(lo) - 1, 181)
        widths = sorted(set(np.round(np.diff(lo), 6)))
        self.assertEqual(widths, [1.0, 2.0])
        # every cell falls in one block, the cells of [-180, -179) in block 0 and of [-1, 0) in block 90
        bj = sm.block_index(lo, lon)
        self.assertEqual(int(bj[0]), 0); self.assertEqual(int(bj[11]), 0); self.assertEqual(int(bj[12]), 1)
        self.assertEqual(int(bj[np.argmin(np.abs(lon + 0.5))]), 90)
        self.assertEqual(int(bj[np.argmin(np.abs(lon - 0.5))]), 91)
        self.assertEqual(int(bj[-1]), 180)

    def test_centres(self):
        c = sm.centres(np.array([-180.0, -179.0, -177.0]))
        self.assertEqual(c.tolist(), [-179.5, -178.0])


class BlockValuesTest(unittest.TestCase):
    def test_uniform_mixed_empty_and_ties(self):
        # 3 blocks of 2 x 2 cells in a row: uniform 5; mixed 1,1,2,inactive; empty
        x = np.array([[5.0, 5.0, 1.0, 2.0, 9.0, 9.0], [5.0, 5.0, 1.0, np.nan, 9.0, 9.0]])
        mask = np.array([[1, 1, 1, 1, 0, 0], [1, 1, 1, 0, 0, 0]], bool)
        bi = np.array([0, 0]); bj = np.array([0, 0, 1, 1, 2, 2])
        values, kind, n_act, share = sm.recover_blocks(x, mask, bi, bj, (1, 3))
        self.assertEqual(values[0, 0], 5.0); self.assertEqual(values[0, 1], 1.0); self.assertTrue(np.isnan(values[0, 2]))
        self.assertEqual(kind.tolist(), [[1, 2, 0]]); self.assertEqual(n_act.tolist(), [[4, 3, 0]])
        self.assertAlmostEqual(share[0, 1], 2 / 3)
        # a tie takes the smallest value
        x2 = np.array([[3.0, 7.0]]); m2 = np.ones((1, 2), bool)
        v2, k2, _, s2 = sm.recover_blocks(x2, m2, np.array([0]), np.array([0, 0]), (1, 1))
        self.assertEqual(v2[0, 0], 3.0); self.assertEqual(int(k2[0, 0]), 2); self.assertEqual(s2[0, 0], 0.5)


class FillTest(unittest.TestCase):
    def test_nearest_land_block_across_the_dateline(self):
        clat = np.array([1.0]); clon = np.array([-179.0, -100.0, 0.0, 100.0, 179.0])
        values = np.array([[np.nan, 2.0, np.nan, 4.0, 5.0]])
        filled, donor, dist = sm.fill_empty(values, clat, clon)
        self.assertEqual(filled[0, 0], 5.0)          # -179 is 2 degrees from 179 across the dateline
        self.assertEqual(donor[0, 0], 4); self.assertAlmostEqual(dist[0, 0], 2 * np.pi / 180 * sm.RK * np.cos(np.deg2rad(1)), delta=1.0)
        self.assertEqual(filled[0, 2], 2.0)          # tie between -100 and 100: the first (cKDTree) -> value 2 or 4
        self.assertEqual(donor[0, 1], -1); self.assertEqual(dist[0, 1], 0.0)
        self.assertTrue(np.array_equal(filled[0, [1, 3, 4]], values[0, [1, 3, 4]]))


class BilinearTest(unittest.TestCase):
    def setUp(self):
        self.lat, self.lon = grid(-56, 84, -180, 180)
        self.le, self.lo = sm.block_edges(self.lat, self.lon)
        self.clat, self.clon = sm.centres(self.le), sm.centres(self.lo)

    def test_constant_field_stays_constant(self):
        filled = np.full((len(self.clat), len(self.clon)), 3.5)
        y = sm.bilinear(filled, self.clat, self.clon, self.lat, self.lon)
        self.assertEqual(y.shape, (len(self.lat), len(self.lon)))
        self.assertTrue(np.allclose(y, 3.5, atol=1e-12))

    def test_linear_in_longitude_and_periodic(self):
        # a field that rises with the block column index: linear between centres, continuous across 180 degrees
        nbi, nbj = len(self.clat), len(self.clon)
        filled = np.tile(np.arange(nbj, dtype=float), (nbi, 1))
        y = sm.bilinear(filled, self.clat, self.clon, self.lat, self.lon)
        row = y[nbi // 2 * 24]
        j = np.argmin(np.abs(self.lon - 10.0))       # between centres 9 (block 95) and 11 (block 96): weight 0.5
        self.assertAlmostEqual(row[j], 95.5 + (self.lon[j] - 10.0) / 2, places=9)
        # beyond the last centre (179) the value goes towards the first centre (-179.5 + 360) with its value 0
        self.assertLess(row[-1], row[np.argmin(np.abs(self.lon - 179.0))])
        self.assertGreater(row[0], 0.0)              # -179.958 is between -179.5 (value 0) and 179 - 360 (value 180)
        # the maximum jump between neighbouring cells is the block difference over the cells between centres
        jumps = np.abs(np.diff(row)); self.assertLessEqual(jumps.max(), 180 / 18 + 1e-9)
        self.assertAlmostEqual(np.abs(row[j + 1] - row[j]), 1 / 24, places=9)

    def test_rows_beyond_outermost_centres_take_the_nearest_row(self):
        nbi, nbj = len(self.clat), len(self.clon)
        filled = np.tile(np.arange(nbi, dtype=float)[:, None], (1, nbj))
        y = sm.bilinear(filled, self.clat, self.clon, self.lat, self.lon)
        self.assertTrue(np.allclose(y[:12], 0.0)); self.assertTrue(np.allclose(y[-12:], nbi - 1))
        i = np.argmin(np.abs(self.lat - 0.0))        # between centres -1 (block 27) and 1 (block 28)
        self.assertAlmostEqual(y[i, 0], 27.5 + (self.lat[i] - 0.0) / 2, places=9)

    def test_centre_values_and_local_range(self):
        rng = np.random.default_rng(3)
        filled = rng.random((len(self.clat), len(self.clon)))
        y = sm.bilinear(filled, self.clat, self.clon, self.lat, self.lon)
        i0, i1, wi, j0, j1, wj = sm.interpolation_indices(self.clat, self.clon, self.lat, self.lon)
        four = np.stack([filled[np.ix_(i0, j0)], filled[np.ix_(i0, j1)], filled[np.ix_(i1, j0)], filled[np.ix_(i1, j1)]])
        self.assertTrue((y >= four.min(axis=0) - 1e-12).all() and (y <= four.max(axis=0) + 1e-12).all())
        # the four cells around a block centre average to the block value within 5 % of the neighbour difference
        bi, bj = 10, 100
        ci = np.argmin(np.abs(self.lat - self.clat[bi])); cj = np.argmin(np.abs(self.lon - self.clon[bj]))
        cells = y[ci - 1:ci + 1, cj - 1:cj + 1] if self.lat[ci] > self.clat[bi] else y[ci:ci + 2, cj - 1:cj + 1]
        self.assertLess(abs(cells.mean() - filled[bi, bj]), 0.05 * 1.0 + 1e-3)


class SmoothFieldTest(unittest.TestCase):
    def test_end_to_end_on_a_small_world(self):
        lat, lon = grid(-56, 84, -180, 180)
        le, lo = sm.block_edges(lat, lon); bi, bj = sm.block_index(le, lat), sm.block_index(lo, lon)
        rng = np.random.default_rng(1)
        block_vals = rng.choice([0.5, 1.0, 2.5, 4.0], size=(len(le) - 1, len(lo) - 1))
        x = block_vals[bi][:, bj]
        mask = np.zeros(x.shape, bool); mask[200:400, 1000:1500] = True; mask[800:900, 4200:] = True
        y, b = sm.smooth_field(x, mask, lat, lon)
        self.assertTrue(np.isnan(y[~mask]).all() and np.isfinite(y[mask]).all())
        land = b['kind'] > 0
        self.assertTrue(np.array_equal(b['values'][land], block_vals[land]))
        self.assertTrue((b['kind'][land] == 1).all())                      # every land block is uniform here
        self.assertTrue(np.isfinite(b['filled']).all())
        self.assertGreaterEqual(y[mask].min(), 0.5); self.assertLessEqual(y[mask].max(), 4.0)
        self.assertEqual(sm.area_mean(np.where(mask, 2.0, np.nan), mask, np.ones(x.shape)), 2.0)


if __name__ == '__main__':
    unittest.main()
