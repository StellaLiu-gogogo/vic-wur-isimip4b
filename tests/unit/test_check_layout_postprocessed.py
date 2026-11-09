"""Unit tests for the postprocessed/ rules of tests/check_layout.py (check_product_set; D11, task AD): a product set
holds product-set.yaml, checksums.sha256, fixed/ with NetCDF files, and <gcm>/<segment-key>/<start>-<end>/ product
units with provenance.yaml and <variable>_<daily|monthly>_<start>_<end>.nc files; a .writing-<start>-<end>/ staging
directory is a warning; spin-up segments, unknown scenarios and other names are errors.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import check_layout

SET = 'water-global-ec-earth3-esm-1-1'
UNIT = f'{SET}/ec-earth3-esm-1-1/picontrol_1850soc_default_pre-industrial/1601-1625'


class ProductSetLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.touch(f'{SET}/product-set.yaml', f'{SET}/checksums.sha256', f'{SET}/fixed/cellarea.nc',
                   f'{UNIT}/provenance.yaml', f'{UNIT}/qtot_daily_1601_1625.nc', f'{UNIT}/dis_monthly_1601_1625.nc')

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, *paths):
        for rel in paths:
            f = self.root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('')

    def check(self):
        report = check_layout.Report()
        check_layout.check_product_set(report, self.root / SET, f'postprocessed/{SET}')
        return report

    def test_valid_set(self):
        report = self.check()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_staging_directory_is_a_warning(self):
        self.touch(f'{SET}/ec-earth3-esm-1-1/picontrol_1850soc_default_pre-industrial/.writing-1626-1650/x.nc')
        report = self.check()
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn('.writing-1626-1650', report.warnings[0])

    def test_errors(self):
        cases = [
            f'{SET}/notes.txt',                                                      # file at set level
            f'{SET}/fixed/outlets.csv',                                              # non-NetCDF fixed file
            f'{SET}/unknown-gcm/historical_histsoc_default_historical/1850-1874/provenance.yaml',
            f'{SET}/ec-earth3-esm-1-1/picontrol_1850soc_default_spinup/1551-1575/provenance.yaml',
            f'{SET}/ec-earth3-esm-1-1/picontrol_1850soc_default/1601-1625/provenance.yaml',  # experiment ID
            f'{SET}/ec-earth3-esm-1-1/historical_histsoc_default_historical/first/provenance.yaml',
            f'{UNIT}/qtot_annual_1601_1625.nc',                                      # unknown time step
            f'{UNIT}/qtot/qtot_daily_1601_1625.nc',                                  # variable level
        ]
        for case in cases:
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                self.touch(case)
                self.assertTrue(self.check().errors, case)

    def test_unit_without_provenance(self):
        (self.root / UNIT / 'provenance.yaml').unlink()
        errors = self.check().errors
        self.assertEqual(len(errors), 1)
        self.assertIn('no provenance.yaml', errors[0])


if __name__ == '__main__':
    unittest.main()
