"""Unit tests for workflow/03_parameters/dams/ (dam_sources.py, dam_grid.py, build_dams.py) on small synthetic
grids, tables and files.

Run from the repository root in the isimip4b environment (PYTHONPATH must include workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, struct, sys, tempfile, unittest, zipfile

import numpy as np
import netCDF4 as nc
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DAMS = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'dams')
sys.path.insert(0, DAMS)
import dam_grid as dg       # noqa: E402
import dam_sources as ds    # noqa: E402
import build_dams as bd     # noqa: E402


def chain_grid(ny=3, nx=5, area_km2=10.0):
    """ny x nx grid; row 1 is a river flowing east (col 0 -> col nx-1, outlet at the last column); rows 0 and 2
    drain south/north into row 1. Cell ids 1..ny*nx row-major; every cell area_km2."""
    lat = np.arange(ny) * 1.0; lon = np.arange(nx) * 1.0
    cid = np.arange(1, ny * nx + 1).reshape(ny, nx)
    down = np.zeros((ny, nx), int)
    for c in range(nx):
        down[1, c] = cid[1, c + 1] if c + 1 < nx else cid[1, c]
        down[0, c] = cid[1, c]; down[2, c] = cid[1, c]
    return dg.Grid(lat, lon, np.ones((ny, nx), bool), cid, down, np.full((ny, nx), area_km2 * 1e6))


class TestTopology(unittest.TestCase):
    def test_upstream_area_and_outlet(self):
        g = chain_grid()
        self.assertEqual(g.next_flat[1, 4], -1)                     # the outlet points to itself
        self.assertEqual(g.next_flat[0, 2], 1 * 5 + 2)
        # river cell (1, c) collects itself, its two side cells, and all of (1, 0..c-1) with their side cells
        np.testing.assert_allclose(g.upstream_m2[1] / 1e6, [30, 60, 90, 120, 150])
        np.testing.assert_allclose(g.upstream_m2[0] / 1e6, 10)

    def test_loop_is_an_error(self):
        nxt = np.array([1, 0, -1]);
        with self.assertRaises(ValueError):
            dg.upstream_area(nxt, np.ones(3))

    def test_inactive_cells_have_no_id(self):
        g = chain_grid()
        mask = np.ones((3, 5), bool); mask[0, 0] = False
        g2 = dg.Grid(g.lat, g.lon, mask, np.arange(1, 16).reshape(3, 5), np.where(True, 0, 0) + 1, np.ones((3, 5)))
        self.assertEqual(g2.cell_id[0, 0], -1)


class TestSnap(unittest.TestCase):
    def setUp(self):
        self.g = chain_grid()

    def test_small_catchment_is_local(self):
        s = dg.snap(self.g, 1.1, 2.2, 4.0)
        self.assertEqual((s['row'], s['col'], s['type']), (1, 2, dg.TYPE_LOCAL))
        self.assertAlmostEqual(s['inflow_fraction'], 0.4)

    def test_future_dam_is_global(self):
        self.assertEqual(dg.snap(self.g, 1.1, 2.2, 4.0, force_global=True)['type'], dg.TYPE_GLOBAL)

    def test_neighbourhood_best_upstream_area(self):
        s = dg.snap(self.g, 1.0, 2.0, 125.0)       # nearest (1, 2) has 90 km2; (1, 3) has 120 km2
        self.assertEqual((s['row'], s['col'], s['type'], s['inflow_fraction']), (1, 3, dg.TYPE_GLOBAL, 1.0))
        self.assertTrue(s['method'].endswith('global_neighbourhood'))

    def test_revert_to_nearest_when_no_neighbour_fits(self):
        s = dg.snap(self.g, 1.0, 1.0, 1000.0)      # best neighbour 90 km2, ratio 11 > 1.5
        self.assertEqual((s['row'], s['col']), (1, 1))
        self.assertTrue(s['method'].endswith('global_revert'))

    def test_inactive_nearest_cell(self):
        mask = np.ones((3, 5), bool); mask[1, 2] = False
        g = dg.Grid(self.g.lat, self.g.lon, mask, self.g.cell_id + 0 * mask, np.where(mask, 1, 1), np.full((3, 5), 1e7))
        s = dg.snap(g, 1.0, 2.1, 1.0)
        self.assertTrue(g.mask[s['row'], s['col']])
        self.assertTrue(s['method'].startswith('nearest_active'))
        g3 = dg.Grid(self.g.lat, self.g.lon, np.zeros((3, 5), bool), self.g.cell_id, self.g.cell_id, np.ones((3, 5)))
        self.assertIsNone(dg.snap(g3, 1.0, 2.0, 1.0)['row'])


class TestSnapFuture(unittest.TestCase):
    def test_largest_upstream_in_neighbourhood(self):
        g = chain_grid()
        s = dg.snap_future(g, 0.1, 2.0)              # nearest (0, 2), a 10 km2 side cell; (1, 3) has 120 km2
        self.assertEqual((s['row'], s['col'], s['type'], s['inflow_fraction']), (1, 3, dg.TYPE_GLOBAL, 1.0))
        self.assertEqual(s['method'], 'future_largest_upstream')
        g3 = dg.Grid(g.lat, g.lon, np.zeros((3, 5), bool), g.cell_id, g.cell_id, np.ones((3, 5)))
        self.assertIsNone(dg.snap_future(g3, 1.0, 2.0)['row'])

    def test_future_flag(self):
        self.assertEqual(bd.future_flag({'capacity_mcm': 100.0, 'years_of_mean_flow': 1.0, 'lake_km2': 10.0,
                                         'dam_height_m': 30.0}), '')
        f = bd.future_flag({'capacity_mcm': 172506.0, 'years_of_mean_flow': 35.5, 'lake_km2': 3068.0,
                            'dam_height_m': 68.0})
        self.assertIn('35.5 years', f)
        self.assertIn('mean depth', bd.future_flag({'capacity_mcm': 1000.0, 'lake_km2': 1.0, 'dam_height_m': 50.0}))


class TestPlace(unittest.TestCase):
    def setUp(self):
        self.g = chain_grid()

    def dam(self, name, row, col, cap, typ=dg.TYPE_GLOBAL, catch=90.0, future=False, keeps=True):
        return {'name': name, 'row': row, 'col': col, 'type': typ, 'lat': float(row), 'lon': float(col),
                'catchment_km2': catch, 'capacity_mcm': cap, 'future': future, 'keeps_service': keeps, 'ratio': 1.0}

    def test_move_to_same_river(self):
        dams = [self.dam('big', 1, 2, 100), self.dam('small', 1, 2, 10, catch=100.0)]
        kept = dg.place(self.g, dams)
        self.assertEqual(kept, [0, 1])
        self.assertEqual(dams[1]['placement'], 'moved')
        self.assertIn((dams[1]['row'], dams[1]['col']), [(1, 1), (1, 3)])
        self.assertEqual((dams[1]['row'], dams[1]['col']), (1, 3))   # 120 km2 fits 100 better than (1, 1) 60 km2

    def test_merge_when_nothing_fits(self):
        dams = [self.dam('big', 1, 2, 100), self.dam('small', 1, 2, 10, catch=500.0)]
        kept = dg.place(self.g, dams)
        self.assertEqual(kept, [0])
        self.assertEqual((dams[1]['placement'], dams[1]['merged_into']), ('merged', 0))
        self.assertEqual(dams[0]['capacity_mcm'], 110)
        self.assertEqual(dams[0]['merged'], [1])

    def test_future_dam_is_not_merged(self):
        dams = [self.dam('hist', 1, 2, 100), self.dam('fut', 1, 2, 1000, catch=500.0, future=True)]
        dg.place(self.g, dams)
        self.assertEqual(dams[1]['placement'], 'not_placed')
        self.assertEqual(dams[0]['capacity_mcm'], 100)

    def test_local_moves_to_nearest_free(self):
        dams = [self.dam('a', 1, 2, 100), self.dam('b', 1, 2, 10, typ=dg.TYPE_LOCAL, catch=1.0)]
        dams[1]['lat'], dams[1]['lon'] = 0.2, 2.1
        dg.place(self.g, dams)
        self.assertEqual((dams[1]['placement'], dams[1]['row'], dams[1]['col']), ('moved', 0, 2))


class TestService(unittest.TestCase):
    def test_trace_stops_below_min_frac(self):
        g = chain_grid()
        q = np.ones((3, 5)); q[1] = [1, 2, 5, 11, 20]
        rows, cols, fr = dg.trace_service(g, 1, 0, q)
        self.assertEqual(cols.tolist(), [0, 1, 2])           # 1/11 < 0.1 stops at col 3
        np.testing.assert_allclose(fr, [1.0, 0.5, 0.2])

    def test_trace_never_empty_and_clipped(self):
        g = chain_grid()
        q = np.zeros((3, 5))
        self.assertEqual(len(dg.trace_service(g, 1, 1, q)[0]), 1)
        q = np.ones((3, 5)); q[1, 3] = 0.5
        rows, cols, fr = dg.trace_service(g, 1, 2, q)
        self.assertTrue((fr <= 1).all())
        self.assertEqual(cols.tolist(), [2, 3, 4])

    def test_write_file_nservice_zero_empty(self):
        g = chain_grid()
        dams = [{'row': 1, 'col': 1, 'type': 1, 'capacity_mcm': 5.0, 'inflow_fraction': 1.0},
                {'row': 1, 'col': 3, 'type': 1, 'capacity_mcm': 2.0, 'inflow_fraction': 1.0}]
        nets = [dg.trace_service(g, 1, 1, np.ones((3, 5))), (np.zeros(0, int), np.zeros(0, int), np.zeros(0))]
        with tempfile.TemporaryDirectory() as t:
            p = f'{t}/d.nc'
            dg.write_dam_file(p, g, dams, np.array([1900, 9999]), nets, {'title': 'x'})
            with nc.Dataset(p) as d:
                d.set_auto_mask(False)
                self.assertEqual(d['Nservice'][:].tolist(), [4, 0])
                self.assertEqual(d['id'][:].tolist(), [7, 9])
                self.assertEqual(d['year'][:].tolist(), [1900, 9999])
                s = d['service'][:]
                self.assertEqual(int((s[0] > 0).sum()), 4)
                self.assertTrue((s[0][s[0] > 0] == 7).all())
                self.assertTrue((s[1] == -1).all())
                self.assertTrue(np.isnan(d['service_fraction'][1]).all())


class TestSources(unittest.TestCase):
    def test_purpose_rule(self):
        g_supply = pd.Series({'USE_IRRI': 'Main', 'MAIN_USE': 'Hydroelectricity'})
        g_hydro = pd.Series({'USE_ELEC': 'Main', 'MAIN_USE': 'Hydroelectricity'})
        g_empty = pd.Series({'MAIN_USE': ''})
        self.assertEqual(ds.purpose_rule('Hydroelectricity', g_supply), 'supply')
        self.assertEqual(ds.purpose_rule('hydroelectric; irrigation; recreation', None), 'supply')
        self.assertEqual(ds.purpose_rule('Water supply', g_empty), 'supply')
        self.assertEqual(ds.purpose_rule('NA', g_empty), 'unknown')
        self.assertEqual(ds.purpose_rule('NA', None), 'unknown')
        self.assertEqual(ds.purpose_rule('NA', g_hydro), 'no_supply')
        self.assertEqual(ds.purpose_rule('Flood control', g_empty), 'no_supply')
        self.assertEqual(ds.purpose_rule('NA', pd.Series({'MAIN_USE': 'Water supply'})), 'supply')

    def test_combine_rules_and_service(self):
        self.assertEqual(ds.combine_rules(['no_supply', 'supply']), 'supply')
        self.assertEqual(ds.combine_rules(['unknown', 'no_supply']), 'no_supply')
        self.assertEqual(ds.combine_rules(['unknown', 'unknown']), 'unknown')
        self.assertTrue(ds.keeps_service(0, 'no_supply'))
        self.assertFalse(ds.keeps_service(1, 'no_supply'))
        self.assertTrue(ds.keeps_service(1, 'unknown'))
        self.assertFalse(ds.keeps_service(1, 'ssp_future'))

    def isi(self):
        t = pd.DataFrame({'ID': [1, 2, np.nan, 4], 'DAM_NAME': ['A', 'B', 'C', 'D'], 'SOURCE': ['NA', 'NA', 'wiki', 'NA'],
                          'LAT_ORIG': [0.0, 1.0, 2.0, 3.0], 'LON_ORIG': [0.0, 1.0, 2.0, 3.0],
                          'CAP_MCM': [100.0, 100.0, 50.0, 10.0]})
        t['key'] = [ds.isimip_key(i, n) for i, n in zip(t.ID, t.DAM_NAME)]
        t['grand_sourced'] = t.SOURCE.str.lower().isin(ds.MISSING_TEXT) & t.ID.notna()
        return t

    def gdw(self):
        return pd.DataFrame({'GDW_ID': [10, 11, 12, 13, 14], 'GRAND_ID': [1, 2, np.nan, np.nan, np.nan],
                             'lat': [0.0, 1.5, 2.005, 2.01, 3.0], 'lon': [0.0, 1.0, 2.0, 2.0, 3.0],
                             'CAP_MCM': [300.0, 100.0, 60.0, 50.0, 10.0]})

    def test_crosswalk(self):
        m = ds.match_isimip_gdw(self.isi(), self.gdw())
        self.assertEqual(m.method.tolist(), ['grand_id', 'grand_id', 'location_2km', 'location_2km'])
        self.assertEqual(m.gdw_row.tolist(), [0, 1, 2, 4])
        self.assertIn('capacity ratio', m.review[0])           # 300 / 100 = 3
        self.assertIn('distance', m.review[1])                  # 0.5 degree ~ 56 km
        self.assertEqual(m.review[2], '')

    def test_crosswalk_manual_and_skip(self):
        m = ds.match_isimip_gdw(self.isi(), self.gdw(), manual=[{'isimip': 'name:C', 'gdw_id': 13}], skip=['4'])
        self.assertEqual((m.method[2], m.gdw_row[2]), ('manual_gdw', 3))
        self.assertEqual(m.method[3], 'combined')
        with self.assertRaises(ValueError):
            ds.match_isimip_gdw(self.isi(), self.gdw(), manual=[{'isimip': 'name:X', 'gdw_id': 13}])

    def test_ssp_sites(self):
        cols = {'year_built': [2030, 2040, 2050], 'latitude': [1.0, 2.0, 3.0], 'longitude': [1.0, 2.0, 3.0],
                ds.SSP_SYSTEM: [2, 2, 1], ds.SSP_VOLUME: [1e9, 2e9, np.nan], ds.SSP_ARC_ID: [100, 200, 300],
                ds.SSP_LAKE: [5e7, 1e8, np.nan], ds.SSP_HEIGHT: [40, 60, np.nan]}
        a = pd.DataFrame(cols); a['row'] = range(3)
        b = pd.DataFrame({k: v[:1] for k, v in cols.items()}); b['year_built'] = [2060]; b['row'] = [0]
        sites, rows = ds.ssp_sites({'s1': a, 's3': b})
        self.assertEqual(len(sites), 2)
        self.assertEqual(sites.capacity_mcm.tolist(), [2000.0, 1000.0])
        self.assertEqual(sites.lake_km2.tolist(), [100.0, 50.0])
        self.assertEqual(sites.ddm30_arc_id.tolist(), [200, 100])
        self.assertEqual(sites.loc[sites.lat == 1.0, ['year_s1', 'year_s3']].values.tolist(), [[2030, 2060]])
        self.assertEqual((rows.outcome == 'site').sum(), 3)
        self.assertTrue(rows.outcome[2].startswith('excluded: diversion canal'))
        b[ds.SSP_VOLUME] = [5e8]
        with self.assertRaises(ValueError):
            ds.ssp_sites({'s1': a, 's3': b})

    def test_xlsx_reader(self):
        sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                 '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                 '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c><c r="C2" t="s"><v>3</v></c></row>'
                 '<row r="3"><c r="A3"><v>5</v></c><c r="B3"><v>1900</v></c><c r="C3"><v>12.5</v></c></row>'
                 '</sheetData></worksheet>')
        shared = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<si><t>title</t></si><si><t>ID</t></si><si><t>YEAR</t></si><si><t>CAP_MCM</t></si></sst>')
        with tempfile.TemporaryDirectory() as t:
            p = f'{t}/x.xlsx'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('xl/worksheets/sheet1.xml', sheet); z.writestr('xl/sharedStrings.xml', shared)
            df = ds.read_xlsx_table(p)
        self.assertEqual(list(df.columns), ['ID', 'YEAR', 'CAP_MCM'])
        self.assertEqual(df.iloc[0].tolist(), ['5', '1900', '12.5'])

    def test_shapefile_readers(self):
        with tempfile.TemporaryDirectory() as t:
            fields = [('GDW_ID', 5), ('NAME', 6)]
            recs = [('1', 'Aa'), ('2', 'Bb')]
            rl = 1 + sum(w for _, w in fields); hl = 32 + 32 * len(fields) + 1
            with open(f'{t}/x.dbf', 'wb') as fh:
                fh.write(bytes([3, 0, 0, 0]) + struct.pack('<IHH', len(recs), hl, rl) + bytes(20))
                for n, w in fields:
                    fh.write(n.encode().ljust(11, b'\0') + b'C' + bytes(4) + bytes([w, 0]) + bytes(14))
                fh.write(b'\r')
                for r in recs:
                    fh.write(b' ' + b''.join(v.encode().ljust(w) for v, (_, w) in zip(r, fields)))
            with open(f'{t}/x.cpg', 'w') as fh:
                fh.write('UTF-8')
            with open(f'{t}/x.shp', 'wb') as fh:
                fh.write(bytes(32) + struct.pack('<i', 1) + bytes(64))
                for i, (x, y) in enumerate([(10.5, -3.25), (20.0, 4.0)]):
                    fh.write(struct.pack('>ii', i + 1, 10) + struct.pack('<idd', 1, x, y))
            t1 = ds.read_dbf(f'{t}/x.dbf')
            x, y = ds.read_shp_points(f'{t}/x.shp')
        self.assertEqual(t1.GDW_ID.tolist(), ['1', '2']); self.assertEqual(t1.NAME.tolist(), ['Aa', 'Bb'])
        np.testing.assert_allclose(x, [10.5, 20.0]); np.testing.assert_allclose(y, [-3.25, 4.0])


class TestYears(unittest.TestCase):
    def test_scenario_years(self):
        dams = [{'future': False, 'year_isimip': 1850}, {'future': False, 'year_isimip': 1900},
                {'future': True, 'year_isimip': None}]
        y = bd.scenario_years(dams)
        self.assertEqual(y['histsoc'].tolist(), [1850, 1900, 9999])
        self.assertEqual(y['1850soc'].tolist(), [0, 9999, 9999])
        self.assertEqual(y['2021soc'].tolist(), [0, 0, 9999])



class TestReviewRules(unittest.TestCase):
    def test_capacity_rules(self):
        # C1: a regulated natural lake takes GDW whatever the depths
        self.assertEqual(ds.capacity_rule(141850, 35200, 'Yes', 1800, 214)[:2], ('gdw', 'C1'))
        self.assertEqual(ds.capacity_rule(28360, 1500, 'Enlarged', 1250, None)[:2], ('gdw', 'C1'))
        # C2: ISIMIP depth 479 m behind a 138 m dam; GDW 55 m plausible
        ch, rule, d_i, d_g = ds.capacity_rule(8820, 1008, '', 18.4, 138)
        self.assertEqual((ch, rule), ('gdw', 'C2')); self.assertAlmostEqual(d_i, 8820 / 18.4)
        # C2: ISIMIP depth 1.5 m behind a 92 m dam (below 5 %), GDW 12 m
        self.assertEqual(ds.capacity_rule(1222, 9750, '', 811, 92)[:2], ('gdw', 'C2'))
        # C2: GDW depth 31 m behind a 21 m dam, ISIMIP 11 m
        self.assertEqual(ds.capacity_rule(400, 1100, '', 35, 21)[:2], ('isimip', 'C2'))
        # C3: both plausible, or no height, or no area
        self.assertEqual(ds.capacity_rule(1570, 5100, '', 118, 47)[:2], ('isimip', 'C3'))
        self.assertEqual(ds.capacity_rule(1518, 640, '', 58, np.nan)[:2], ('isimip', 'C3'))
        self.assertEqual(ds.capacity_rule(100, 300, '', np.nan, 50)[:2], ('isimip', 'C3'))

    def test_location_rules(self):
        self.assertEqual(ds.location_rule(6.4, 1.0), ('gdw', 'L1'))
        self.assertEqual(ds.location_rule(1.0, 1.4), ('gdw', 'L1'))
        self.assertEqual(ds.location_rule(1.2, 2.3), ('isimip', 'L2'))
        self.assertEqual(ds.location_rule(3.0, 7.0), ('gdw', 'L3'))

    def test_location_fit(self):
        g = chain_grid()
        self.assertAlmostEqual(dg.location_fit(g, 1.0, 2.0, 120.0), 1.0)      # (1, 3) has 120 km2
        self.assertEqual(dg.location_fit(g, 1.0, 2.0, np.nan), np.inf)


if __name__ == '__main__':
    unittest.main()
