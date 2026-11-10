"""Unit tests for the static files of stage 06_postprocessing (workflow/06_postprocessing: routing.py, static_fields.py,
check_static.py; D07, D08): river networks and upstream area, grid blocks, weighted block means, outlet choice, the
WGS84 cell area, and producer plus check end to end on a tiny synthetic workdir (1-degree "product" cells of 2 x 2
half-degree "5 arcmin" cells), including a check that fails after an outlet is moved.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import contextlib, io, os, sys, tempfile, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '06_postprocessing'))
import routing        # noqa: E402
import static_fields   # noqa: E402
import check_static    # noqa: E402
import support        # noqa: E402

# the river network of tests/unit/test_run_check.py: 3 x 4 grid, ids 100 + flat index, cell (2, 3) inactive
MASK = np.array([[1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0]], bool)
IDS = 100 + np.arange(12).reshape(3, 4)
DOWN = np.array([[101, 102, 103, 103], [105, 106, 107, 107], [104, 105, 106, -1]])


class RoutingTest(unittest.TestCase):
    def test_network_and_upstream_area(self):
        nxt = routing.network(DOWN, IDS, MASK)
        self.assertEqual(nxt[0], 1); self.assertEqual(nxt[3], 3); self.assertEqual(nxt[11], -1)
        upa = routing.upstream_area(nxt, np.ones(12), MASK).reshape(3, 4)
        self.assertEqual(upa[0, 3], 4); self.assertEqual(upa[1, 3], 7); self.assertEqual(upa[1, 1], 4)
        self.assertEqual(upa[2, 3], 0)

    def test_loop_stops(self):
        down = np.array([[101, 100]]); ids = np.array([[100, 101]])
        nxt = routing.network(down, ids, np.ones((1, 2), bool))
        with self.assertRaises(SystemExit):
            routing.upstream_area(nxt, np.ones(2), np.ones(2, bool))

    def test_ddm30_directions_follow_the_latitude_axis(self):
        # 3 x 3 grid, centre cell flows north; with latitudes ascending north is the next row
        fd = np.ma.masked_all((3, 3)); fd[1, 1] = 7; fd[2, 1] = 0; fd[0, 1] = 1     # (0,1) flows east to (0,2): off
        nxt, lost = routing.ddm30_network(fd, np.array([0.0, 1.0, 2.0]))
        self.assertEqual(nxt[4], 7); self.assertEqual(nxt[7], 7); self.assertEqual(lost, 1)
        nxt, _ = routing.ddm30_network(fd[::-1], np.array([2.0, 1.0, 0.0]))     # same map, latitudes descending
        self.assertEqual(nxt[4], 1)


class BlocksTest(unittest.TestCase):
    def test_block_index(self):
        idx, f = static_fields.block_index(np.array([1.25, 1.75, 2.25, 2.75]), np.array([3.5, 2.5, 1.5, 0.5]))
        self.assertEqual(f, 2); self.assertEqual(list(idx), [2, 2, 1, 1])
        with self.assertRaises(SystemExit):
            static_fields.block_index(np.array([1.25, 1.75, 2.25]), np.array([3.5, 2.5, 1.5, 0.5]))

    def test_static_fields_and_outlets(self):
        # one row of two coarse cells of 2 x 2 fine cells (fine flat indices 0, 1, 4, 5 and 2, 3, 6, 7);
        # coarse cell 1 is outside the mask, fine cell 4 is inactive
        cell = static_fields.cell_index(np.array([0, 0]), np.array([0, 0, 1, 1]), 2)
        self.assertEqual(list(cell), [0, 0, 1, 1, 0, 0, 1, 1])
        active = np.array([1, 1, 1, 1, 0, 1, 1, 1], bool)
        area = np.array([1, 2, 1, 1, 3, 4, 1, 1], float) * 1e6
        frac = np.ones(8)
        depth = np.array([[0.1] * 8, [1.0, 2.0, 1.0, 1.0, 9.0, 2.0, 1.0, 1.0]])
        f, w, counted = static_fields.static_fields(cell, 2, np.array([True, False]), active, area, frac, depth)
        self.assertTrue(f['covered'][0]); self.assertFalse(f['covered'][1])
        self.assertAlmostEqual(f['cellarea'][0], 10.0)                      # all four fine cells, km2
        self.assertAlmostEqual(f['contfrac'][0], 7 / 10)                    # the inactive cell (area 3) excluded
        self.assertAlmostEqual(f['layer_thickness'][1, 0], (1 * 1 + 2 * 2 + 2 * 4) / 7)
        self.assertAlmostEqual(f['layer_bottom'][1, 0], 0.1 + 13 / 7)
        self.assertTrue(np.isnan(f['cellarea'][1]))
        self.assertEqual(list(f['n_cells']), [3, 0])
        upa = np.array([5.0, 7.0, 9.0, 9.0, 99.0, 1.0, 1.0, 1.0])
        out = static_fields.outlets(cell, 2, counted, upa)
        self.assertEqual(out[0], 1); self.assertEqual(out[1], -1)           # inactive 4 and unmasked 2, 3 never
        upa[0] = 7.0
        self.assertEqual(static_fields.outlets(cell, 2, counted, upa)[0], 0)   # tie: smallest flat index


class Wgs84Test(unittest.TestCase):
    def test_area_of_the_earth(self):
        total = check_static.wgs84_band_area_km2(-90.0, 90.0, 360.0)
        self.assertAlmostEqual(total / 510065621.7, 1.0, places=7)


# ------------------------------------------------------------------------------------------------ end to end
LAT05 = np.array([3.5, 2.5, 1.5, 0.5]); LON05 = np.array([0.5, 1.5, 2.5, 3.5])
LAT5 = np.arange(1.25, 4.0, 0.5); LON5 = np.arange(0.25, 4.0, 0.5)     # 6 x 8 fine cells over coarse rows 0-2


def write(path, dims, variables, attrs=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with nc.Dataset(path, 'w', format='NETCDF4_CLASSIC') as d:
        for k, n in dims.items():
            d.createDimension(k, n)
        for name, (vdims, arr, extra) in variables.items():
            v = d.createVariable(name, np.asarray(arr).dtype, vdims, **(extra or {}))
            v[:] = arr
        if attrs:
            d.setncatts(attrs)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        W = self.W = self.tmp.name
        ny, nx = LAT5.size, LON5.size
        # mask: every coarse cell except (2, 3), whose fine cells are active outside the mask; row 3 (lat 0.5)
        # lies outside the fine domain, so its four mask cells are uncovered
        m = np.ma.masked_all((1, 4, 4), 'f4'); m[0] = 1; m[0, 2, 3] = np.ma.masked
        write(f'{W}/raw/mask.nc', {'time': 1, 'lat': 4, 'lon': 4},
              {'lat': (('lat',), LAT05, None), 'lon': (('lon',), LON05, None),
               'mask': (('time', 'lat', 'lon'), m, {'fill_value': np.float32(1e20)})})
        active = np.ones((ny, nx), 'i4'); active[0, 0] = 0
        area = check_static.wgs84_band_area_km2(LAT5 - 0.25, LAT5 + 0.25, 0.5)[:, None] * np.ones((1, nx)) * 1e6
        ps = f'{W}/parameters/production/test-set'
        write(f'{ps}/domain.nc', {'lat': ny, 'lon': nx},
              {'lat': (('lat',), LAT5, None), 'lon': (('lon',), LON5, None),
               'mask': (('lat', 'lon'), active, None), 'area': (('lat', 'lon'), area, None),
               'frac': (('lat', 'lon'), np.ones((ny, nx)), None)})
        depth = np.stack([np.full((ny, nx), 0.1), np.full((ny, nx), 0.5), np.linspace(1, 2, ny * nx).reshape(ny, nx)])
        write(f'{ps}/params.nc', {'nlayer': 3, 'lat': ny, 'lon': nx},
              {'lat': (('lat',), LAT5, None), 'lon': (('lon',), LON5, None), 'depth': (('nlayer', 'lat', 'lon'), depth, None)})
        ids = np.arange(ny * nx, dtype='i4').reshape(ny, nx)
        down = ids + 1                                   # every row flows east; the last column is the outlet
        down[:, -1] = ids[:, -1]
        write(f'{ps}/routing.nc', {'lat': ny, 'lon': nx},
              {'lat': (('lat',), LAT5, None), 'lon': (('lon',), LON5, None),
               'downstream_id': (('lat', 'lon'), ids, None), 'downstream': (('lat', 'lon'), down, None)})
        fd = np.ma.masked_all((4, 4), 'f4'); fd[1:, :3] = 1; fd[1:, 3] = 0      # ascending latitudes 0.5..3.5
        write(f'{W}/raw/ddm30.nc', {'lat': 4, 'lon': 4},
              {'lat': (('lat',), LAT05[::-1], None), 'lon': (('lon',), LON05, None),
               'flowdirection': (('lat', 'lon'), fd, {'fill_value': np.float32(1e20)})})
        prot = f'{W}/protocol/definitions/variable'
        os.makedirs(prot)
        with open(f'{prot}/static.yaml', 'w') as fh:
            yaml.safe_dump([{'specifier': 'cellarea', 'long_name': 'Grid Cell Area', 'units': 'km2'},
                            {'specifier': 'contfrac', 'long_name': 'Continental Fraction of Grid Cell', 'units': '1'},
                            {'specifier': 'landfrac', 'long_name': 'Land Fraction of Grid Cell', 'units': '1'}], fh)
        self.campaign = f'{W}/campaign.yaml'
        with open(self.campaign, 'w') as fh:
            yaml.safe_dump({'campaign_id': 'test-campaign', 'model': {'commit': 'a' * 40},
                            'parameter_set': {'id': 'test-set', 'status': 'production',
                                              'files': {'domain': 'domain.nc', 'parameters': 'params.nc',
                                                        'routing': 'routing.nc', 'dams': {'x': 'y'}}},
                            'protocol': {'path': 'protocol', 'commit': 'b' * 40}}, fh)
        cfg = support.load_yaml(support.CONFIG)
        cfg['product_grid'].update({'mask': 'raw/mask.nc', 'uncovered_cells_expected': 4})
        cfg['attributes'] = {'institution': 'Test institute', 'contact': 'Test <test@example.org>'}
        cfg['static'].update({'ddm30_flowdir': 'raw/ddm30.nc', 'ddm30_min_area_km2': 1.0})
        self.patches = [mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': W}),
                        mock.patch.object(support, 'config', return_value=cfg),
                        mock.patch.object(support, 'git_state',
                                          return_value={'commit': 'c' * 40, 'branch': 'test', 'dirty': False})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_main(self, module):
        argv = [module.__file__, '--campaign', self.campaign, '--scratch', 'test-task']
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            try:
                module.main()
            except SystemExit as e:
                return e.code
        return 0

    def test_produce_and_check(self):
        self.assertEqual(self.run_main(static_fields), 0)
        static = f'{self.W}/scratch/test-task/postprocessed/test-campaign/static'
        self.assertEqual(sorted(os.listdir(static)), sorted(static_fields.STATIC_FILES))
        with nc.Dataset(f'{static}/contfrac.nc') as d:
            self.assertEqual(d.data_model, 'NETCDF4_CLASSIC')
            cf = np.ma.filled(d['contfrac'][:], np.nan)
            self.assertEqual(int(np.isfinite(cf).sum()), 11)              # rows 0-2 minus (2, 3)
            self.assertAlmostEqual(float(cf[2, 0]), 0.75, places=2)       # one of four fine cells inactive
        with nc.Dataset(f'{static}/dis-outlets.nc') as d:
            self.assertEqual(int(d['outlet_col'][1, 0]), 1)               # eastern column of the block
        qc = f'{self.W}/scratch/test-task/qc/postprocessed/test-campaign/static'
        self.assertEqual(self.run_main(check_static), 0)
        s = support.load_yaml(f'{qc}/summary.json')
        self.assertEqual(s['status'], 'passed', s)
        # move one outlet to the western column: the check fails
        with nc.Dataset(f'{static}/dis-outlets.nc', 'a') as d:
            d['outlet_col'][1, 0] = 0
        self.assertEqual(self.run_main(check_static), 1)
        self.assertEqual(support.load_yaml(f'{qc}/summary.json')['checks']['outlets'], 'failed')

    def test_existing_static_files_are_not_overwritten(self):
        self.assertEqual(self.run_main(static_fields), 0)
        code = self.run_main(static_fields)
        self.assertIn('never overwritten', str(code))


if __name__ == '__main__':
    unittest.main()
