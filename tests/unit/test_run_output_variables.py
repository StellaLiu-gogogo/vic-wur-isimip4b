"""Unit tests for run_manifest.py complete (review P3 D2): VIC drops an OUTVAR it does not know with only a warning
(vic_history.c), so the completion step compares the variables requested per stream in config/vic_global.txt with
the variables of the stream's output files; a missing variable fails the attempt. Synthetic run, Slurm and git mocked.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, tempfile, types, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc

from test_simulation_submit import make_run, rm

VIC_GLOBAL = """# test
OUTFILE                 daily
AGGFREQ                 NDAYS 1
OUTVAR                  OUT_RUNOFF
OUTVAR                  OUT_BASEFLOW

OUTFILE                 monthly
AGGFREQ                 NMONTHS 1
OUTVAR                  OUT_SOIL_MOIST  * * * AGG_TYPE_AVG
"""


class OutputVariablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.rd = make_run(self.W, files={'config/vic_global.txt': VIC_GLOBAL, 'config/job.sbatch': 'job'})
        m = rm.load(self.rd)
        m['expected_outputs'] = ['output/daily.2015-01-01.nc', 'output/monthly.2015-01.nc', 'states/state.20160101_00000.nc']
        m['attempts'].append({'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-09T00:00:00Z',
                              'started_at': '2026-10-09T00:00:00Z', 'status': 'running', 'input_verification': {'passed': True}})
        rm.save(self.rd, m)
        open(f'{self.rd}/states/state.20160101_00000.nc', 'w').close()
        self.write('output/monthly.2015-01.nc', ['OUT_SOIL_MOIST'])
        git = types.SimpleNamespace(stdout='c' * 40, returncode=0)
        self.patches = [mock.patch.object(rm, 'sacct', return_value=[]), mock.patch.object(rm.subprocess, 'run', return_value=git)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write(self, rel, names):
        with nc.Dataset(f'{self.rd}/{rel}', 'w') as d:
            d.createDimension('time', 1); d.createDimension('lat', 1); d.createDimension('lon', 1)
            for n in names:
                d.createVariable(n, 'f4', ('time', 'lat', 'lon'))[:] = np.zeros((1, 1, 1))

    def complete(self):
        try:
            rm.complete(self.rd, 101, 0, self.W); code = 0
        except SystemExit as e:
            code = e.code
        return code, rm.load(self.rd)['attempts'][0]

    def test_all_requested_variables_present(self):
        self.write('output/daily.2015-01-01.nc', ['OUT_RUNOFF', 'OUT_BASEFLOW'])
        code, a = self.complete()
        self.assertEqual((code, a['status']), (0, 'completed'), a.get('failure_reason'))
        self.assertEqual(a['output_variables']['daily']['missing'], [])

    def test_dropped_variable_fails(self):
        self.write('output/daily.2015-01-01.nc', ['OUT_RUNOFF'])            # OUT_BASEFLOW dropped by VIC
        code, a = self.complete()
        self.assertEqual((code, a['status']), (1, 'failed'))
        self.assertEqual(a['output_variables']['daily']['missing'], ['OUT_BASEFLOW'])
        self.assertIn('OUT_BASEFLOW', a['failure_reason'])


if __name__ == '__main__':
    unittest.main()
