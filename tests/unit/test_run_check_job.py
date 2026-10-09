"""Unit tests for monitor/submit_check.py (review P3 E4): the job name of a run check identifies the run, so that the
checks of the production runs of one campaign (run IDs without a label) do not share a job name.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'monitor'))
import submit_check as sc   # noqa: E402


class JobNameTest(unittest.TestCase):
    def test_labelled_run_keeps_its_name(self):
        rd = '/w/runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2015'
        self.assertEqual(sc.job_name(rd), 'run-check-smoke-smoke2015')

    def test_production_runs_differ(self):
        names = {sc.job_name(f'/w/runs/fasttrack/ec-earth3-esm-1-1_{c}_{s}_default_historical')
                 for c, s in (('historical', 'histsoc'), ('historical', '1850soc'), ('picontrol', 'histsoc'))}
        self.assertEqual(len(names), 3)
        for n in names:
            self.assertRegex(n, r'^[a-z0-9]+(-[a-z0-9]+)*$')                # lowercase words joined by hyphens


if __name__ == '__main__':
    unittest.main()
