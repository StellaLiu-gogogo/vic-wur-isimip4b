"""Unit tests for monitor/submit_check.py (review P3 E4): the job name of a run check identifies the run, so that the
checks of the production runs of one campaign (run IDs without a label) do not share a job name.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import json, os, re, sys, tempfile, unittest
from unittest import mock

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


class CheckTimeTest(unittest.TestCase):
    """Review 2026-11-01 R4: the wall time of a check grows with the years it reads (a fixed 4 h was short for the
    whole-run check of the 249-year pre-industrial run and for 25-year chunk checks with water use), never below 4 h."""

    def manifest(self, start, end, chunk_years=None):
        m = {'period': {'start': f'{start}-01-01', 'end': f'{end}-12-31'}}
        if chunk_years:
            m['chunks'] = [{'id': f'{y}-{min(y + chunk_years - 1, end)}', 'start_year': y,
                            'end_year': min(y + chunk_years - 1, end)} for y in range(start, end + 1, chunk_years)]
        return m

    def test_unchunked_run(self):
        self.assertEqual(sc.check_time(self.manifest(2015, 2016)), '04:00:00')          # 1 h + 30 min, floor 4 h
        self.assertEqual(sc.check_time(self.manifest(2011, 2020)), '04:00:00')          # 3.5 h -> 4 h
        self.assertEqual(sc.check_time(self.manifest(1850, 2021)), '44:00:00')          # 172 years in one job

    def test_chunk_and_whole_run(self):
        m = self.manifest(1601, 1849, 25)                                               # the pre-industrial segment
        self.assertEqual(sc.check_time(m, chunk='1601-1625'), '08:00:00')               # 1 h + 25 x 15 min = 7.25 h
        self.assertEqual(sc.check_time(m, chunk='1826-1849'), '07:00:00')               # 24 years: 7 h
        self.assertEqual(sc.check_time(m), '10:00:00')                                  # 1 h + 249 x 2 min = 9.3 h
        self.assertEqual(sc.check_time(self.manifest(1850, 2021, 20)), '07:00:00')      # natural run: 6.7 h (2:49 measured)
        self.assertEqual(sc.check_time(self.manifest(2015, 2016, 1)), '04:00:00')


class SubmitCheckTest(unittest.TestCase):
    """Review 2026-11-01 R19 and R2: the check job is submitted through common.jobrecord (job record under
    logs/05_simulation/), its dependency is an #SBATCH line of the job file with --kill-on-invalid-dep=yes, and the
    wall time follows the years of the check."""

    def submit(self, **kw):
        calls = []
        with tempfile.TemporaryDirectory() as W:
            rd = f'{W}/runs/c/r'; os.makedirs(rd)
            with open(f'{rd}/run_manifest.json', 'w') as fh:
                json.dump({'period': {'start': '1601-01-01', 'end': '1849-12-31'},
                           'chunks': [{'id': '1601-1625', 'start_year': 1601, 'end_year': 1625},
                                      {'id': '1626-1650', 'start_year': 1626, 'end_year': 1650}]}, fh)
            with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': W}), \
                    mock.patch.object(sc.jobrecord, 'conda_base', return_value='/conda'), \
                    mock.patch.object(sc.gitstate, 'state', return_value=('c' * 40, False)), \
                    mock.patch.object(sc.jobrecord, 'submit', side_effect=lambda *a: calls.append(a) or ('77', 'd')):
                job = sc.submit('runs/c/r', **kw)
        self.assertEqual(job, '77')
        text, stage_logs, name, rendered_by, template, commit, dirty, details = calls[0]
        return text, name, template, details

    def test_chunk_check_with_dependency(self):
        text, name, template, details = self.submit(dependency='41', chunk='1601-1625')
        self.assertEqual(name, 'run-check-c-r-chunk-1601-1625')
        self.assertEqual(template, 'workflow/05_simulation/monitor/check_run.sbatch')
        self.assertIn('#SBATCH --dependency=afterok:41\n#SBATCH --kill-on-invalid-dep=yes\n', text)
        self.assertIn('#SBATCH --time=08:00:00\n', text)
        self.assertIn('--chunk 1601-1625', text)
        self.assertNotIn('{{', text)
        self.assertEqual((details['dependency'], details['chunk'], details['resources']['time']),
                         ('41', '1601-1625', '08:00:00'))
        self.assertEqual(details['outputs'], ['qc/runs/c/r/chunks/1601-1625'])

    def test_whole_run_check_waits_for_the_chunk_checks(self):
        text, name, template, details = self.submit(dependency='42', after_checks=['51', '52'])
        self.assertIn('#SBATCH --dependency=afterok:42,afterany:51:52\n#SBATCH --kill-on-invalid-dep=yes\n', text)
        self.assertIn('#SBATCH --time=10:00:00\n', text)                   # 1 h + 249 x 2 min
        self.assertEqual(details['after_checks'], ['51', '52'])

    def test_spinup_test_without_dependency(self):
        text, name, template, details = self.submit(spinup=True)
        self.assertEqual((name, template), ('spinup-check-c-r', 'workflow/05_simulation/monitor/check_spinup.sbatch'))
        self.assertNotIn('--dependency', text); self.assertNotIn('kill-on-invalid-dep', text)
        self.assertIn('#SBATCH --time=04:00:00\n', text)
        self.assertIn('check_spinup.py', text)


if __name__ == '__main__':
    unittest.main()
