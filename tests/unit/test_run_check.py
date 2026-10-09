"""Unit tests for workflow/05_simulation/monitor/grdc.py (routing network, upstream area, station mapping,
GRDC file reading, monthly means and climatology) on small synthetic inputs, and for the overall status of
check_run.py main() (coverage, water-use budget and end-state file) on a tiny synthetic run in a temporary workdir,
with the GRDC comparison, the figures and git replaced by fixed results.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'monitor'))
import grdc          # noqa: E402
import check_run     # noqa: E402
import run_figures   # noqa: E402

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



# ------------------------------------------------------------------------------------------------ check_run.main
YEAR = 2015
RUN_MASK = np.array([[1, 1, 1], [1, 1, 0]], bool)
FILL = 9.96921e36


def write_nc(path, dims, variables, dtype='f4'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with nc.Dataset(path, 'w') as d:
        for k, n in dims.items():
            d.createDimension(k, n)
        for name, (vdims, data) in variables.items():
            v = d.createVariable(name, dtype, vdims, fill_value=np.float32(FILL) if dtype == 'f4' else None)
            v[:] = data


class CheckRunMainTest(unittest.TestCase):
    """A one-year run of 2 x 3 cells (one inactive) with consistent output: the overall status is passed only when
    the coverage and budget checks pass and the end-state file exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); W = self.W = self.tmp.name
        self.rd = f'{W}/runs/c/r'
        ny, nx = RUN_MASK.shape
        write_nc(f'{W}/parameters/p/domain.nc', {'lat': ny, 'lon': nx},
                 {'lat': (('lat',), [10.0, 10.5]), 'lon': (('lon',), [20.0, 20.5, 21.0]),
                  'mask': (('lat', 'lon'), RUN_MASK.astype('f8')), 'area': (('lat', 'lon'), np.full((ny, nx), 1e8))},
                 dtype='f8')
        ids = np.arange(ny * nx).reshape(ny, nx)
        write_nc(f'{W}/parameters/p/routing.nc', {'lat': ny, 'lon': nx},
                 {'downstream_id': (('lat', 'lon'), ids), 'downstream': (('lat', 'lon'), ids)}, dtype='i4')
        view = {}
        for sector in ('municipal', 'manufacturing'):
            for var, value in (('consumption_fraction', 0.5), ('demand', 0.01)):
                rel = f'forcing/water_use/histsoc/{sector}_{var}_histsoc_{YEAR}.nc'
                write_nc(f'{W}/{rel}', {'time': 1, 'lat': ny, 'lon': nx},
                         {var: (('time', 'lat', 'lon'), np.full((1, ny, nx), value))})
                view[f'water_use/{sector}_{var}'] = {str(YEAR): {'source': rel, 'rule': 'identity'}}
        for sub in ('config', 'states', 'output', 'logs'):
            os.makedirs(f'{self.rd}/{sub}')
        with open(f'{self.rd}/run_manifest.json', 'w') as fh:
            json.dump({'run_id': 'r', 'run_dir': 'runs/c/r', 'forcing_view': view,
                       'period': {'start': f'{YEAR}-01-01', 'end': f'{YEAR}-12-31'}}, fh)
        with open(f'{self.rd}/config/resolved.yaml', 'w') as fh:
            yaml.safe_dump({'parameters': {'domain': {'path': 'parameters/p/domain.nc'},
                                           'routing': {'path': 'parameters/p/routing.nc'}}}, fh)
        self.daily()
        self.monthly()
        self.state = f'{self.rd}/states/state.{YEAR + 1}0101_00000.nc'
        with open(self.state, 'w') as fh:
            fh.write('state')

    def tearDown(self):
        self.tmp.cleanup()

    def daily(self, gap=False):
        """Daily runoff, baseflow and discharge of 1 everywhere; with gap, no discharge on one active cell and day."""
        ny, nx = RUN_MASK.shape
        q = np.ones((365, ny, nx)); q[100, 0, 1] = FILL if gap else 1.0
        write_nc(f'{self.rd}/output/daily.{YEAR}-01-01.nc', {'time': 365, 'lat': ny, 'lon': nx},
                 {'OUT_RUNOFF': (('time', 'lat', 'lon'), np.ones((365, ny, nx))),
                  'OUT_BASEFLOW': (('time', 'lat', 'lon'), np.ones((365, ny, nx))),
                  'OUT_DISCHARGE': (('time', 'lat', 'lon'), q)})

    def monthly(self, withdrawn=25.0):
        """Monthly water use: 1 mm per sector and source (5 x 5 = 25 mm withdrawn), demand 50 mm."""
        ny, nx = RUN_MASK.shape
        sect = np.ones((12, 5, ny, nx))
        vals = {v: (('time', 'wu_class', 'lat', 'lon'), sect) for v in check_run.WI + ('OUT_DE_GW_SECT', 'OUT_DE_SURF_SECT')}
        vals['OUT_WI_REM_SECT'] = (('time', 'wu_class', 'lat', 'lon'), np.zeros((12, 5, ny, nx)))
        cell = {'OUT_WITHDRAWN': withdrawn, 'OUT_DEMAND': 50.0, 'OUT_CONSUMED': 5.0, 'OUT_RETURNED': 20.0,
                'OUT_RECEIVED': 1.0, 'OUT_REQUIREMENT': 1.0, 'OUT_APPLIED': 1.0, 'OUT_WATER_ERROR': 0.0,
                'OUT_DISCHARGE': 1.0}
        vals.update({v: (('time', 'lat', 'lon'), np.full((12, ny, nx), x)) for v, x in cell.items()})
        write_nc(f'{self.rd}/output/monthly.{YEAR}-01.nc', {'time': 12, 'wu_class': 5, 'lat': ny, 'lon': nx}, vals)

    def main(self):
        """check_run.main() on the synthetic run; returns (summary.json, reports/check.json)."""
        no_stations = pd.DataFrame({'row': [], 'col': [], 'lat': [], 'lon': []})
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}), \
                mock.patch.object(sys, 'argv', ['check_run', '--run-dir', self.rd]), \
                mock.patch.object(check_run, 'grdc_compare', return_value=(no_stations, {}, [YEAR], None)), \
                mock.patch.object(check_run, 'grdc_figures', return_value=({'stations_mapped': 0}, [])), \
                mock.patch.object(check_run, 'draw'), \
                mock.patch.object(run_figures, 'water_use_figures', return_value=[]), \
                mock.patch.object(run_figures, 'water_balance', return_value=({}, 'wb.png')), \
                mock.patch.object(check_run.os, 'popen', return_value=io.StringIO('c' * 40)), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                check_run.main(); self.exit_status = 0
            except SystemExit as e:
                self.exit_status = e.code
        qc = f'{self.W}/qc/runs/c/r'
        with open(f'{qc}/summary.json') as fh, open(f'{qc}/reports/check.json') as gh:
            return json.load(fh), json.load(gh)

    def test_complete_run_passes(self):
        summary, report = self.main()
        self.assertEqual((summary['status'], report['status']), ('passed', 'passed'), report['years'])
        self.assertEqual(summary['object'], 'runs/c/r')
        y = report['years'][str(YEAR)]
        self.assertEqual((y['coverage']['status'], y['budget']['status']), ('passed', 'passed'))
        self.assertEqual(report['state_files'], [{'path': f'states/state.{YEAR + 1}0101_00000.nc', 'size_bytes': 5}])
        self.assertTrue(os.path.isfile(f'{self.W}/qc/runs/c/r/reports/water_use_by_sector_{YEAR}.nc'))
        self.assertEqual(self.exit_status, 0)
        # OUT_WATER_ERROR is a monthly mean (VIC default aggregation), reported as such (review P3 D3)
        self.assertIn('max_abs_monthly_mean_water_error_mm', y['water_balance'])

    def test_missing_state_fails(self):
        os.remove(self.state)
        summary, report = self.main()
        self.assertEqual((summary['status'], report['status']), ('failed', 'failed'))
        self.assertEqual(report['state_files'], [])
        self.assertEqual(report['years'][str(YEAR)]['budget']['status'], 'passed')
        self.assertEqual(self.exit_status, 1)                          # the check job ends FAILED (review P3 A2)

    def test_coverage_gap_fails(self):
        self.daily(gap=True)
        summary, report = self.main()
        cov = report['years'][str(YEAR)]['coverage']
        self.assertEqual((cov['status'], cov['active_cells_with_missing_values']), ('failed', 1))
        self.assertEqual(summary['status'], 'failed')

    def test_budget_violation_fails(self):
        self.monthly(withdrawn=60.0)                                   # more than the demand, not the sum of sources
        summary, report = self.main()
        b = report['years'][str(YEAR)]['budget']
        self.assertEqual(b['status'], 'failed')
        self.assertEqual(b['violations']['withdrawn_gt_demand'], 12 * RUN_MASK.sum())
        self.assertEqual(report['years'][str(YEAR)]['coverage']['status'], 'passed')
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(self.exit_status, 1)


class ClimatologyYearsTest(unittest.TestCase):
    """Review P3 D5: only a cold-started run leaves out its first year from the GRDC climatology."""

    def test_cold_and_warm_start(self):
        years = list(range(2011, 2021))
        self.assertEqual(check_run.climatology_years(years, cold_start=True), years[1:])
        self.assertEqual(check_run.climatology_years(years, cold_start=False), years)
        self.assertEqual(check_run.climatology_years([2015, 2016], cold_start=True), [2015, 2016])   # too short


if __name__ == '__main__':
    unittest.main()
