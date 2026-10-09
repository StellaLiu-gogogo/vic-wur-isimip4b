"""Unit tests for run_manifest.py verify-inputs (review P3 B4): before VIC starts, every forcing unit of the run must
still be accepted (provenance.yaml: code_dirty false, qc.status passed), not only have the recorded checksums; a unit
judged failed after rendering stops a retry. Synthetic run in a temporary directory.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, tempfile, unittest

import yaml

from test_simulation_submit import make_run, rm, sha256


class UnitStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        self.unit = f'{W}/forcing/landuse/histsoc'; os.makedirs(self.unit)
        with open(f'{self.unit}/coverage_histsoc_2015.nc', 'w') as fh:
            fh.write('coverage')
        self.provenance('passed')
        units = {'landuse/histsoc': {'files': {'coverage_histsoc_2015.nc': {
            'path': 'forcing/landuse/histsoc/coverage_histsoc_2015.nc', 'sha256': sha256(f'{self.unit}/coverage_histsoc_2015.nc')}}}}
        self.rd = make_run(W, units=units)
        m = rm.load(self.rd)
        m['attempts'].append({'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-09T00:00:00Z', 'status': 'submitted'})
        rm.save(self.rd, m)

    def tearDown(self):
        self.tmp.cleanup()

    def provenance(self, status, dirty=False):
        with open(f'{self.unit}/provenance.yaml', 'w') as fh:
            yaml.safe_dump({'forcing_unit': 'landuse/histsoc', 'code_dirty': dirty, 'qc': {'status': status}}, fh)

    def verify(self):
        try:
            rm.verify_inputs(self.rd, 101, self.W, 1)
            code = 0
        except SystemExit as e:
            code = e.code
        return code, rm.load(self.rd)['attempts'][0]['input_verification']

    def test_accepted_unit_passes(self):
        code, v = self.verify()
        self.assertEqual(code, 0); self.assertTrue(v['passed'], v)

    def test_unit_no_longer_accepted_stops(self):
        for status, dirty in (('failed', False), ('not_checked', False), ('passed', True)):
            with self.subTest(status=status, dirty=dirty):
                self.provenance(status, dirty)
                code, v = self.verify()
                self.assertNotEqual(code, 0)
                self.assertFalse(v['passed'])
                self.assertIn('forcing/landuse/histsoc/provenance.yaml', v['mismatches'])


if __name__ == '__main__':
    unittest.main()
