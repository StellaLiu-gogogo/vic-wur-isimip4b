"""Unit tests for workflow/common/workdir.py.

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import os, unittest
from unittest import mock

from common import workdir


class WorkdirTest(unittest.TestCase):
    def test_root_from_environment(self):
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/some/workdir'}):
            self.assertEqual(workdir.root(), '/some/workdir')
            self.assertEqual(workdir.logs('04_forcing'), '/some/workdir/logs/04_forcing')
        self.assertEqual(workdir.logs('03_parameters', '/w'), '/w/logs/03_parameters')

    def test_missing_variable_stops(self):
        for env in ({}, {'ISIMIP4B_WORKDIR': ''}):
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(SystemExit) as cm:
                    workdir.root()
                self.assertEqual(cm.exception.code, 'set ISIMIP4B_WORKDIR')


if __name__ == '__main__':
    unittest.main()
