"""Unit tests for the water-use part of workflow/05_simulation/monitor/check_run.py and run_figures.py on a small
synthetic run (2 x 3 cells, one inactive): missing monthly water-use values on active cells must fail the check and
must not become zeros in the derived per-sector file. Figures are not drawn.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'monitor'))
import check_run      # noqa: E402
import run_figures    # noqa: E402

YEAR = 2015
MASK = np.array([[1, 1, 1], [1, 1, 0]], bool)
SECTOR_VARS = check_run.WI + ('OUT_DE_GW_SECT', 'OUT_DE_SURF_SECT', 'OUT_WI_REM_SECT')
CELL_VARS = ('OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_CONSUMED', 'OUT_RETURNED', 'OUT_RECEIVED', 'OUT_REQUIREMENT',
             'OUT_APPLIED', 'OUT_WATER_ERROR')
FILL = 9.96921e36


def write(path, dims, variables):
    with nc.Dataset(path, 'w') as d:
        for k, n in dims.items():
            d.createDimension(k, n)
        for name, (vdims, data) in variables.items():
            v = d.createVariable(name, 'f4', vdims, fill_value=np.float32(FILL))
            v[:] = data


class WaterUseMissingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.tmp.name
        self.rd = os.path.join(d, 'run'); self.qc = os.path.join(d, 'qc')
        for sub in ('run/output', 'qc/reports', 'qc/figures', 'forcing'):
            os.makedirs(os.path.join(d, sub))
        ny, nx = MASK.shape
        write(f'{self.rd}/output/daily.{YEAR}-01-01.nc', {'time': 365, 'lat': ny, 'lon': nx},
              {v: (('time', 'lat', 'lon'), np.ones((365, ny, nx))) for v in ('OUT_RUNOFF', 'OUT_BASEFLOW', 'OUT_DISCHARGE')})
        self.view = {}
        for sector in ('municipal', 'manufacturing'):
            for var, value in (('consumption_fraction', 0.5), ('demand', 0.01)):
                p = os.path.join(d, 'forcing', f'{sector}_{var}_{YEAR}.nc')
                write(p, {'time': 1, 'lat': ny, 'lon': nx}, {var: (('time', 'lat', 'lon'), np.full((1, ny, nx), value))})
                self.view[f'water_use/{sector}_{var}'] = {str(YEAR): p}
        self.area = np.where(MASK, 1e8, 0.0)

    def tearDown(self):
        self.tmp.cleanup()

    def monthly(self, missing=()):
        """Monthly file with 1 mm of withdrawal per sector and source; the variables in `missing` are fill values on
        every cell."""
        ny, nx = MASK.shape
        sect = np.zeros((12, 5, ny, nx)); sect[:, :, :, :] = 1.0
        vals = {v: (('time', 'wu_class', 'lat', 'lon'), sect.copy()) for v in SECTOR_VARS}
        vals['OUT_WI_REM_SECT'] = (('time', 'wu_class', 'lat', 'lon'), np.zeros((12, 5, ny, nx)))
        cell = {'OUT_WITHDRAWN': 25.0, 'OUT_DEMAND': 50.0, 'OUT_CONSUMED': 5.0, 'OUT_RETURNED': 20.0,
                'OUT_RECEIVED': 1.0, 'OUT_REQUIREMENT': 1.0, 'OUT_APPLIED': 1.0, 'OUT_WATER_ERROR': 0.0}
        vals.update({v: (('time', 'lat', 'lon'), np.full((12, ny, nx), x)) for v, x in cell.items()})
        for v in missing:
            vals[v] = (vals[v][0], np.full(vals[v][1].shape, FILL))
        write(f'{self.rd}/output/monthly.{YEAR}-01.nc', {'time': 12, 'wu_class': 5, 'lat': ny, 'lon': nx}, vals)

    def check(self):
        with mock.patch.object(check_run, 'draw'), \
                mock.patch.object(run_figures, 'water_use_figures', return_value=[]), \
                mock.patch.object(run_figures, 'water_balance', return_value=({}, 'wb.png')):
            out, _ = check_run.check_year(YEAR, self.rd, MASK, self.area, np.arange(2.0), np.arange(3.0),
                                          np.zeros(MASK.shape, bool), self.qc + '/figures', self.view,
                                          (np.array([0]), np.array([0])), {'title': 'test'}, self.qc)
        return out

    def derived_withdrawal(self):
        with nc.Dataset(f'{self.qc}/reports/water_use_by_sector_{YEAR}.nc') as d:
            d.set_auto_mask(False)
            return np.asarray(d['withdrawal'][:], 'f8')

    def test_complete_fields_pass(self):
        self.monthly()
        out = self.check()
        self.assertEqual(out['budget']['status'], 'passed', out['budget'])
        w = self.derived_withdrawal()
        self.assertTrue(np.allclose(w[:, :, MASK], 5.0))                  # 5 sources x 1 mm

    def test_missing_withdrawal_fails(self):
        self.monthly(missing=SECTOR_VARS + CELL_VARS)
        out = self.check()
        self.assertEqual(out['budget']['status'], 'failed', out['budget'])
        self.assertEqual(out['budget']['missing_values']['OUT_WITHDRAWN'], 12 * MASK.sum())
        self.assertFalse(np.isfinite(self.derived_withdrawal()[:, :, MASK]).any())     # missing, not zero

    def test_one_missing_source_fails(self):
        self.monthly(missing=('OUT_WI_DAM_SECT',))
        out = self.check()
        self.assertEqual(out['budget']['status'], 'failed', out['budget'])
        self.assertEqual(out['budget']['missing_values'], {'OUT_WI_DAM_SECT': 12 * MASK.sum()})


if __name__ == '__main__':
    unittest.main()
