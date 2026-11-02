"""Unit tests for workflow/03_parameters/vegetation/recompute_roots.py (Zeng root fractions, the coefficient file,
the class rule with donors on a small synthetic grid).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import importlib.util, os, tempfile, unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'vegetation', 'recompute_roots.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('recompute_roots', SRC)
    rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)


class CoefficientsTest(unittest.TestCase):
    def test_file_covers_the_16_classes(self):
        zeng, unchanged = rr.coefficients()
        self.assertEqual(sorted(zeng), list(range(1, 11)) + [13])
        self.assertEqual(unchanged, [11, 12, 14, 15, 16])
        self.assertEqual(zeng[10], (10.740, 2.608)); self.assertEqual(zeng[13], (5.558, 2.614))


class ZengTest(unittest.TestCase):
    def test_fractions_by_hand(self):
        a, b = 6.706, 2.175
        depth = np.array([0.3, 1.0, 0.7]).reshape(3, 1, 1)
        fr = rr.root_fractions(depth, a, b)[:, 0, 0]
        Y = lambda d: 1 - 0.5 * (np.exp(-a * d) + np.exp(-b * d))   # noqa: E731
        raw = np.array([Y(0.3) - Y(0), Y(1.3) - Y(0.3), Y(2.0) - Y(1.3)])
        self.assertTrue(np.allclose(fr, raw / Y(2.0), atol=1e-15))
        self.assertAlmostEqual(fr.sum(), 1.0, places=15)
        self.assertTrue((fr > 0).all())

    def test_deeper_layer_2_moves_roots_into_layer_2(self):
        shallow = rr.root_fractions(np.array([0.3, 0.5, 1.0]).reshape(3, 1, 1), 10.74, 2.608)[:, 0, 0]
        deep = rr.root_fractions(np.array([0.3, 2.5, 1.0]).reshape(3, 1, 1), 10.74, 2.608)[:, 0, 0]
        self.assertGreater(deep[1], shallow[1]); self.assertLess(deep[2], shallow[2])
        self.assertAlmostEqual(deep[0] * (1 - 0) , deep[0])

    def test_class_rule_with_donors(self):
        depth = np.zeros((3, 2, 3)); depth[0] = 0.3; depth[1] = [[0.5, 1.0, 2.5], [4.0, 1.7, 0.7]]; depth[2] = 1.0
        valid = np.ones((2, 3), bool); valid[1, 2] = False; depth[:, 1, 2] = np.nan
        base_d = np.full((3, 2, 3), -1.0); base_f = np.full((3, 2, 3), -1.0)
        zeng = {1: (6.706, 2.175)}
        added = (np.array([0]), np.array([1]), np.array([1]), np.array([0]))      # tile (0, 1) copies donor (1, 0)
        rd, rf = rr.class_roots(1, depth, valid, base_d, base_f, zeng, added)
        self.assertTrue(np.array_equal(rd[:, 0, 0], [0.3, 0.5, 1.0]))
        self.assertTrue(np.array_equal(rd[:, 0, 1], rd[:, 1, 0]) and rd[1, 0, 1] == 4.0)
        self.assertTrue(np.array_equal(rf[:, 0, 1], rf[:, 1, 0]))
        self.assertTrue((rd[:, 1, 2] == -1).all() and (rf[:, 1, 2] == -1).all())   # invalid cell keeps the base
        self.assertTrue(np.allclose(rf[:, valid].sum(axis=0), 1.0, atol=1e-12))
        # a class without the Zeng rule keeps the base arrays as they are
        rd2, rf2 = rr.class_roots(12, depth, valid, base_d, base_f, zeng, added)
        self.assertIs(rd2, base_d); self.assertIs(rf2, base_f)

    def test_donor_table(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, 'backfill_tiles.csv')
            with open(p, 'w') as fh:
                fh.write('class,row,col,lat,lon,level,donor_row,donor_col,donor_lat,donor_lon,distance_km,koppen,donor_koppen,soc_bits\n'
                         '3,5,6,0,0,2,7,8,0,0,10.0,1,1,1\n3,1,1,0,0,1,1,1,0,0,0.0,1,1,1\n')
            d = rr.donors(p)
            self.assertEqual([x.tolist() for x in d[3]], [[5, 1], [6, 1], [7, 1], [8, 1]])
            self.assertEqual(len(d[1][0]), 0)


if __name__ == '__main__':
    unittest.main()
