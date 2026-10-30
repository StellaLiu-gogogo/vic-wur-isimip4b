"""Unit tests for workflow/03_parameters/routing/build_decomposition.py and verify_decomposition.py on small
synthetic networks, links and dam files.

Run from the repository root in the isimip4b environment (PYTHONPATH must include workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'routing'))
import build_decomposition as bdc    # noqa: E402
import verify_decomposition as vdc   # noqa: E402


def two_rivers():
    """Seven active cells, ids 11..17: river A 11 -> 12 -> 13 (outlet), river B 14 -> 15 (outlet), and two one-cell
    basins 16 and 17 (17 points to an id that is no active cell, an outlet as in VIC)."""
    ids = np.array([11, 12, 13, 14, 15, 16, 17])
    down = np.array([12, 13, 13, 15, 15, 16, 99])
    return ids, down


class BasinTest(unittest.TestCase):
    def test_outlets(self):
        ids, down = two_rivers()
        np.testing.assert_array_equal(bdc.basins(ids, down), [2, 2, 2, 4, 4, 5, 6])

    def test_loop_stops(self):
        with self.assertRaises(SystemExit):
            bdc.basins(np.array([1, 2]), np.array([2, 1]))


class LinkTest(unittest.TestCase):
    def test_water_use_links(self):
        ids, _ = two_rivers()
        rec = np.zeros((2, 7), int); rec[0, 0] = 14; rec[1, 0] = 16; rec[0, 5] = 77   # 77 is no id
        dem, src, unresolved = bdc.water_use_links(rec, ids)
        self.assertEqual(sorted(zip(dem.tolist(), src.tolist())), [(0, 3), (0, 5)])
        self.assertEqual(unresolved, 1)

    def test_components_join_linked_basins(self):
        ids, down = two_rivers()
        outlet = bdc.basins(ids, down)
        comp = bdc.components(outlet, np.array([1]), np.array([3]))   # a link from river A to river B
        self.assertEqual(len(set(comp[:5])), 1)
        self.assertEqual(len(set(comp)), 3)
        self.assertEqual(bdc.crossing(comp, np.array([1]), np.array([3])), 0)

    def test_dam_links_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = f'{d}/dams.nc'; write_dams(p)
            mask = np.ones((2, 4), bool)
            a, b, n = bdc.dam_links(p, mask, np.arange(1, 9), processes=1)
        self.assertEqual(n, 1)                                  # the dam with Nservice 0 is skipped
        self.assertEqual(sorted(zip(a.tolist(), b.tolist())), [(1, 1), (1, 6)])


class PackTest(unittest.TestCase):
    def test_largest_first_to_fewest(self):
        sizes = np.array([5, 9, 3, 3, 2])
        group = bdc.pack(sizes, 2)
        # 9 -> g0; 5 -> g1; 3 -> g1 (8); 3 -> g1 (8 < 9, 11); 2 -> g0 (11)
        np.testing.assert_array_equal(np.bincount(group, weights=sizes), [11, 11])
        self.assertEqual(group[1], 0)

    def test_rank_loads_and_verifier_agree(self):
        cells = np.array([372, 100, 90, 80, 70, 60, 50, 40, 30, 20])
        for t in (1, 3, 6):
            self.assertEqual(bdc.rank_loads(cells, t).max(), vdc.largest_rank(cells.tolist(), t))
        self.assertEqual(bdc.rank_loads(cells, 6).max(), 372)    # the largest group sets the pace


class VerifierTest(unittest.TestCase):
    def test_index_of(self):
        np.testing.assert_array_equal(vdc.index_of(np.array([13, 5, 11]), np.array([11, 12, 13])), [2, -1, 0])

    def test_check_dams_finds_cells_outside_the_group(self):
        with tempfile.TemporaryDirectory() as d:
            p = f'{d}/dams.nc'; write_dams(p)
            g = f'{d}/g.npy'
            np.save(g, np.array([[0, 0, 0, 0], [0, 0, 0, 0]]))
            problems, links = vdc.check_dams((p, 0, 2, g))
            self.assertEqual((problems, links), ([], 2))
            np.save(g, np.array([[0, 0, 0, 0], [0, 0, 1, 0]]))         # serviced cell (1, 2) in another group
            problems, _ = vdc.check_dams((p, 0, 2, g))
            self.assertEqual(len(problems), 1)


def write_dams(path):
    """2 x 4 grid, cell ids 1..8 row-major; dam 0 in cell id 2 serving itself and cell id 7; dam 1 (cell id 5) has
    Nservice 0."""
    with nc.Dataset(path, 'w') as o:
        o.createDimension('lat', 2); o.createDimension('lon', 4); o.createDimension('dam_class', 2)
        o.createVariable('id_map', 'i4', ('lat', 'lon'), fill_value=-1)[:] = np.arange(1, 9).reshape(2, 4)
        o.createVariable('id', 'i4', ('dam_class',))[:] = [2, 5]
        o.createVariable('Nservice', 'i4', ('dam_class',))[:] = [2, 0]
        s = np.full((2, 2, 4), -1); s[0, 0, 1] = 2; s[0, 1, 2] = 2
        o.createVariable('service', 'i4', ('dam_class', 'lat', 'lon'), fill_value=-1)[:] = s


if __name__ == '__main__':
    unittest.main()
