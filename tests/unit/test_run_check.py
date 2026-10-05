"""Unit tests for workflow/05_simulation/monitor/grdc.py (routing network, upstream area, station mapping,
GRDC file reading, monthly means and climatology) on small synthetic inputs.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'monitor'))
import grdc   # noqa: E402

# 3 x 4 grid; ids = 100 + flat index; cell (2, 3) inactive. Two rivers:
#   row 0: (0,0) -> (0,1) -> (0,2) -> (0,3) outlet
#   rows 1-2: (2,0) -> (1,0) -> (1,1) -> (1,2) -> (1,3) outlet ; (2,1) -> (1,1) ; (2,2) -> (1,2)
MASK = np.array([[1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0]], bool)
IDS = 100 + np.arange(12).reshape(3, 4)
DOWN = np.array([[101, 102, 103, 103], [105, 106, 107, 107], [104, 105, 106, -1]])


class NetworkTest(unittest.TestCase):
    def test_upstream_area_and_outlets(self):
        nxt = grdc.network(DOWN, IDS, MASK)
        self.assertEqual(nxt[0], 1); self.assertEqual(nxt[3], 3); self.assertEqual(nxt[8], 4)
        upa = grdc.upstream_area(nxt, np.ones(12), MASK).reshape(3, 4)
        self.assertEqual(upa[0, 3], 4)                                     # four cells drain to the first outlet
        self.assertEqual(upa[1, 3], 7)                                     # seven to the second
        self.assertEqual(upa[1, 1], 4)                                     # (2,0), (1,0), (2,1) and itself
        self.assertEqual(upa[2, 3], 0)                                     # inactive
        out = grdc.outlets(nxt).reshape(3, 4)
        self.assertTrue((out[0] == 3).all())
        self.assertEqual(set(out[1:, :3].ravel()) | {out[1, 3]}, {7})

    def test_map_stations(self):
        nxt = grdc.network(DOWN, IDS, MASK)
        upa = grdc.upstream_area(nxt, np.full(12, 1000.0), MASK)
        lat = np.array([0.0, 1.0, 2.0]); lon = np.array([0.0, 1.0, 2.0, 3.0])
        st = pd.DataFrame({'lat': [1.0, 0.0, 1.0], 'lon': [2.0, 3.0, 0.0], 'area_km2': [6200.0, 4100.0, 50000.0]},
                          index=[1, 2, 3])
        m = grdc.map_stations(st, upa, lat, lon, MASK, radius=1, max_area_error=0.3)
        self.assertEqual(list(m.index), [1, 2])                            # station 3: no cell within 30 %
        self.assertEqual((m.at[1, 'row'], m.at[1, 'col']), (1, 2))         # 6000 km2 is the closest
        self.assertAlmostEqual(m.at[2, 'area_error'], 4000 / 4100 - 1)


class SeriesTest(unittest.TestCase):
    def test_read_station_and_monthly(self):
        text = ('# Title:                 GRDC STATION DATA FILE\r\n# GRDC-No.:              1234567\r\n'
                '# River:                 TEST RIVER\r\n# Station:               GAUGE\r\n'
                '# Latitude (DD):       12.5\r\n# Longitude (DD):      -7.25\r\n'
                '# Catchment area (km\xb2):      120000.0\r\n# DATA\r\nYYYY-MM-DD;hh:mm; Value\r\n')
        days = pd.date_range('2015-01-01', '2015-02-28')
        vals = ['%.3f' % (10.0 if d.month == 1 else -999) for d in days]
        vals[0] = '-999.000'
        text += ''.join(f'{d:%Y-%m-%d};--:--;{v}\r\n' for d, v in zip(days, vals))
        with tempfile.NamedTemporaryFile('wb', suffix='.txt', delete=False) as fh:
            fh.write(text.encode('latin-1')); path = fh.name
        try:
            meta, s = grdc.read_station(path)
        finally:
            os.unlink(path)
        self.assertEqual((meta['grdc_no'], meta['area_km2'], meta['lat'], meta['lon']), (1234567, 120000.0, 12.5, -7.25))
        self.assertEqual(meta['river'], 'TEST RIVER')
        self.assertTrue(np.isnan(s.iloc[0])); self.assertEqual(s.iloc[1], 10.0)
        mon = grdc.monthly_means(s, min_days=20)
        self.assertEqual(mon.loc['2015-01-01'], 10.0)                       # 30 valid days
        self.assertTrue(np.isnan(mon.loc['2015-02-01']))                    # no valid day

    def test_climatology_needs_years(self):
        idx = pd.date_range('2001-01-01', '2010-12-01', freq='MS')
        mon = pd.Series(np.arange(idx.size, dtype=float), index=idx)
        mon[mon.index.month == 3] = np.nan
        clim, lo, hi, n = grdc.climatology(mon, range(2001, 2011), min_years=5)
        self.assertTrue(np.isnan(clim[2])); self.assertEqual(n[2], 0)
        self.assertEqual(n[0], 10)
        self.assertAlmostEqual(clim[0], np.mean([12 * k for k in range(10)]))
        self.assertEqual(lo[0], 0.0); self.assertEqual(hi[0], 108.0)


if __name__ == '__main__':
    unittest.main()
