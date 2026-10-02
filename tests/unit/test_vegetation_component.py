"""Unit tests for workflow/03_parameters/vegetation/build_vegetation.py (rules on small synthetic grids).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, os, unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'vegetation', 'build_vegetation.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('build_vegetation', SRC)
    bv = importlib.util.module_from_spec(spec); spec.loader.exec_module(bv)


def base_case():
    """2 x 3 grid, 16 classes; cell (1, 2) inactive."""
    mask = np.array([[True, True, True], [True, True, False]])
    cv = np.zeros((16, 2, 3))
    cv[0] = [[0.5, 1.0, 0.0], [0.2, 0.0, 0.0]]
    cv[11] = [[0.5, 0.0, 0.7], [0.0, 0.0, 0.0]]
    cv[15] = [[0.0, 0.0, 0.3], [0.8, 1.0, 0.0]]
    cv[:, ~mask] = np.nan
    return cv, mask


class TileRulesTest(unittest.TestCase):
    def test_bits_round_trip(self):
        cv, mask = base_case()
        bits = bv.coverage_bits(cv, mask)
        self.assertTrue(np.array_equal(bv.bits_to_tiles(bits), (np.nan_to_num(cv) > 0) & mask[None]))
        self.assertEqual(int(bits[1, 2]), 0)                                   # inactive cell carries no bits

    def test_extend_tiles(self):
        cv, mask = base_case()
        cov = np.zeros_like(cv); cov[13, 0, 1] = 0.1; cov[11, 1, 1] = 0.4; cov[0, 0, 0] = 0.3   # 2 new, 1 existing
        cov[13, 1, 2] = 0.9                                                    # inactive cell: ignored
        out, nveg, added = bv.extend_tiles(cv, bv.coverage_bits(cov, mask), mask)
        self.assertEqual(int(added.sum()), 2)
        self.assertTrue(added[13, 0, 1] and added[11, 1, 1])
        self.assertTrue(np.allclose(np.nansum(out, axis=0)[mask], 1, atol=1e-15))
        self.assertTrue(np.isnan(out[:, 1, 2]).all() and nveg[1, 2] == -1)
        self.assertAlmostEqual(out[13, 0, 1], bv.PLACEHOLDER_CV, delta=1e-20)
        self.assertAlmostEqual(out[0, 0, 0], 0.5, delta=1e-11)                 # base cover kept
        tiles = np.nan_to_num(out) > 0
        self.assertTrue((tiles >= ((np.nan_to_num(cov) > 0) & mask[None])).all())   # every forcing tile is a tile
        self.assertTrue(np.array_equal(nveg[mask], tiles[:15].sum(axis=0)[mask]))  # class 16 not counted
        self.assertEqual(int(nveg[1, 0]), 1)                                   # class 1 + class 16 -> Nveg 1

    def test_active_cell_without_tile_fails(self):
        cv, mask = base_case(); cv[:, 0, 1] = 0
        with self.assertRaises(ValueError):
            bv.extend_tiles(cv, np.zeros(mask.shape, np.uint16), mask)


class KoppenTest(unittest.TestCase):
    def test_mode(self):
        kg = np.zeros((4, 6), np.uint8)
        kg[:2, :2] = [[3, 3], [5, 0]]          # block 0,0: 3 wins
        kg[:2, 2:4] = [[7, 8], [8, 7]]         # tie -> lowest (7)
        kg[2:, :2] = [[0, 0], [0, 4]]          # zeros ignored -> 4
        m = bv.koppen_mode(kg, block=2)
        self.assertEqual(m.tolist(), [[3, 7, 0], [4, 0, 0]])


class DonorLadderTest(unittest.TestCase):
    def test_levels(self):
        # donors: A near target 0; B far, Koppen 9; C in target 2's latitude band but far in longitude; D nearest to 2/3
        d_lat = np.array([10.0, 40.0, -30.0, -20.0]); d_lon = np.array([10.0, 100.0, 170.0, 0.0])
        d_kg = np.array([1, 9, 2, 2], np.uint8)
        t_lat = np.array([12.0, 10.0, -30.0, 70.0]); t_lon = np.array([11.0, 60.0, 0.0, 0.0])
        t_kg = np.array([1, 9, 5, 0], np.uint8)
        lev, idx, dist = bv.choose_donors(t_lat, t_lon, t_kg, d_lat, d_lon, d_kg)
        self.assertEqual(lev.tolist(), [2, 3, 4, 5])
        self.assertEqual(idx.tolist(), [0, 1, 2, 1])   # L3 skips the nearer A; L4 takes C in the band, not D;
        # L5: B (56 deg away over the pole side) is nearer to 70N 0E than A (60 deg)
        self.assertLess(dist[0], 500)
        self.assertGreater(dist[1], 500)

    def test_no_donor(self):
        with self.assertRaises(ValueError):
            bv.choose_donors(np.array([0.0]), np.array([0.0]), np.array([1]), np.array([]), np.array([]), np.array([]))


class FcanopyFloorTest(unittest.TestCase):
    def test_floor(self):
        fc = np.array([[[0.0, 0.5], [np.nan, 5e-5]]])
        tiles = np.array([[True, True], [True, False]])
        out, n = bv.floor_fcanopy(fc, tiles)
        self.assertEqual(n, 1)
        self.assertEqual(out[0, 0, 0], bv.FCANOPY_FLOOR)
        self.assertTrue(np.isnan(out[0, 1, 0]))
        self.assertEqual(out[0, 1, 1], 5e-5)                                   # not a tile: untouched
        self.assertGreater(float(np.float32(bv.FCANOPY_FLOOR)), 1e-4)          # VIC MIN_FCANOPY, strict


if __name__ == '__main__':
    unittest.main()
