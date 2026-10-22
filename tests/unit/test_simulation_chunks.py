"""Unit tests for chunked runs (task L4b): the chunk plan and the rendered chunk directories (render_run.py), the
chunk bookkeeping of the run manifest (run_manifest.py) and the submission chain (submit_run.py). Uses the render
harness of test_simulation_render.py (temporary workdir, build/parameter/forcing steps replaced).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, sys, unittest
from unittest import mock

import test_simulation_render as tsr
from test_simulation_render import FUT, HIST, rm, rr

sys.path.insert(0, os.path.join(tsr.REPO, 'workflow', '05_simulation', 'monitor'))
import submit_run as sr     # noqa: E402
import compare_runs as cr   # noqa: E402


class ChunkPlanTest(unittest.TestCase):
    def test_plan(self):
        p = rr.chunk_plan(1850, 2021, 20)
        self.assertEqual(len(p), 9)
        self.assertEqual((p[0], p[1], p[-1]), ((1850, 1869), (1870, 1889), (2010, 2021)))
        self.assertEqual(rr.chunk_plan(2015, 2016, 1), [(2015, 2015), (2016, 2016)])
        self.assertEqual(rr.chunk_plan(2011, 2020, 20), [(2011, 2020)])
        self.assertEqual(rr.chunk_plan(2011, 2020, None), [(2011, 2020)])

    def test_end_state(self):
        self.assertEqual(rr.end_state_rel(2011, 2020, 20), 'states/state.20210101_00000.nc')
        self.assertEqual(rr.end_state_rel(2015, 2016, 1), 'chunks/2016-2016/states/state.20170101_00000.nc')

    def test_restriction_run_chunk_years(self):
        import resolve_campaign as rc
        c = tsr.smoke()
        c['restriction']['runs']['smoke2015'] = {'years': [2015, 2016], 'chunk_years': 1}
        seg = tsr.segment('historical', 'histsoc', 'historical', (1850, 2021), None)
        runs = rc.runs(c, {HIST: seg}, 'smoke2015')
        self.assertEqual(rr.run_chunk_years(runs[0], {'chunk_years': 20}), 1)
        c['restriction']['runs']['smoke2015']['chunk_years'] = 0
        with self.assertRaises(rc.CampaignError):
            rc.runs(c, {HIST: seg}, 'smoke2015')


class ChunkRenderTest(tsr.RenderHarness):
    chunk_years = 20

    def test_chunk_directories(self):
        self.render(HIST)
        rd = os.path.join(self.W, 'runs', 'smoke', HIST)
        m = self.manifest(HIST)
        self.assertEqual([c['id'] for c in m['chunks']][:2], ['1850-1869', '1870-1889'])
        self.assertEqual(len(m['chunks']), 9)
        self.assertEqual(sorted(os.listdir(rd)), ['chunks', 'run_manifest.json'])        # contract: runs/ chunks
        for c in m['chunks']:
            self.assertEqual(sorted(os.listdir(os.path.join(rd, c['dir']))),
                             ['config', 'forcing', 'logs', 'output', 'states'])
        self.assertEqual(m['end_state'], 'chunks/2010-2021/states/state.20220101_00000.nc')
        with open(os.path.join(rd, 'chunks', '1870-1889', 'config', 'vic_global.txt')) as fh:
            g = fh.read()
        self.assertIn(f'INIT_STATE              {rd}/chunks/1850-1869/states/state.18700101_00000.nc', g)
        self.assertIn('STARTYEAR               1870', g)
        self.assertIn(f'RESULT_DIR              {rd}/chunks/1870-1889/output/', g)
        with open(os.path.join(rd, 'chunks', '1850-1869', 'config', 'vic_global.txt')) as fh:
            self.assertNotIn('INIT_STATE              /', fh.read())                  # cold start of the run
        self.assertIn('chunks/1870-1889/output/monthly.1870-01.nc', m['expected_outputs'])
        self.assertEqual(m['chunks'][1]['expected_outputs'][-1], 'chunks/1870-1889/states/state.18900101_00000.nc')
        self.assertIn('chunks/1870-1889/config/job.sbatch', m['rendered_files'])

    def test_child_starts_from_last_chunk(self):
        self.render()
        p = self.manifest(FUT)['parent']
        self.assertEqual(p['init_state'], f'runs/smoke/{HIST}/chunks/2010-2021/states/state.20220101_00000.nc')

    def test_fingerprint_ignores_chunk_job_files(self):
        self.render(HIST)
        m = self.manifest(HIST)
        before = rm.inputs_fingerprint(m)
        m['rendered_files']['chunks/1870-1889/config/job.sbatch'] = '0' * 64
        self.assertEqual(rm.inputs_fingerprint(m), before)
        m['rendered_files']['chunks/1870-1889/config/vic_global.txt'] = '0' * 64
        self.assertNotEqual(rm.inputs_fingerprint(m), before)


def chunked_manifest():
    chunks = [{'id': f'{y}-{y}', 'start_year': y, 'end_year': y, 'dir': f'chunks/{y}-{y}',
               'end_state': f'chunks/{y}-{y}/states/state.{y + 1}0101_00000.nc',
               'job_file': f'chunks/{y}-{y}/config/job.sbatch', 'expected_outputs': []} for y in (2015, 2016, 2017)]
    return {'run_id': 'r', 'status': 'rendered', 'chunks': chunks, 'attempts': []}


class ChunkManifestTest(unittest.TestCase):
    def add(self, m, chunk, status):
        m['attempts'].append({'attempt': len(m['attempts']) + 1, 'slurm_job_id': 100 + len(m['attempts']),
                              'chunk': chunk, 'status': status})

    def test_completion(self):
        m = chunked_manifest()
        self.assertFalse(rm.is_completed(m)); self.assertEqual(rm.first_incomplete_chunk(m), 0)
        self.add(m, '2015-2015', 'completed'); self.add(m, '2016-2016', 'failed')
        self.assertEqual(rm.first_incomplete_chunk(m), 1); self.assertEqual(rm.run_status(m), 'failed')
        self.add(m, '2016-2016', 'completed'); self.add(m, '2017-2017', 'running')
        self.assertEqual(rm.run_status(m), 'running')
        m['attempts'][-1]['status'] = 'completed'
        self.assertTrue(rm.is_completed(m)); self.assertEqual(rm.run_status(m), 'completed')
        self.assertIsNone(rm.first_incomplete_chunk(m))

    def test_unchunked_unchanged(self):
        m = {'run_id': 'r', 'attempts': [{'attempt': 1, 'status': 'failed'}, {'attempt': 2, 'status': 'completed'}]}
        self.assertTrue(rm.is_completed(m)); self.assertEqual(rm.run_status(m), 'completed')
        self.assertIsNone(rm.chunk(m, None))
        with self.assertRaises(SystemExit):
            rm.chunk(m, '2015-2015')

    def test_previous_chunk_state(self):
        import tempfile
        with tempfile.TemporaryDirectory() as rd:
            m = chunked_manifest()
            self.assertEqual(rm.previous_chunk_state(m, '2015-2015', rd), (None, None))   # first chunk
            rec, problem = rm.previous_chunk_state(m, '2016-2016', rd)
            self.assertEqual(problem, 'chunks/2015-2015/states/state.20160101_00000.nc')  # not completed
            self.add(m, '2015-2015', 'completed')
            path = os.path.join(rd, m['chunks'][0]['end_state']); os.makedirs(os.path.dirname(path))
            with open(path, 'w') as fh:
                fh.write('state')
            rec, problem = rm.previous_chunk_state(m, '2016-2016', rd)
            self.assertIsNone(problem); self.assertEqual(rec['chunk'], '2015-2015')
            # a retry of the chunk must find the state its first attempt started from
            m['attempts'].append({'attempt': 2, 'chunk': '2016-2016', 'status': 'failed',
                                  'input_verification': {'chunk_state': {**rec, 'sha256': '0' * 64}}})
            self.assertIsNotNone(rm.previous_chunk_state(m, '2016-2016', rd)[1])


class ChunkSubmitTest(unittest.TestCase):
    def test_chain_and_checks(self):
        calls = []
        jobs = iter(range(1, 100))

        def fake_submit(run_dir, dependency=None, chunk=None):
            j = str(next(jobs)); calls.append(('run', chunk, dependency, j)); return j

        def fake_check(run_dir, dependency=None, chunk=None):
            calls.append(('check', chunk, dependency))
        with mock.patch.object(sr.rm, 'load', return_value=chunked_manifest()), \
                mock.patch.object(sr, 'submit', side_effect=fake_submit), \
                mock.patch.object(sr.sc, 'submit', side_effect=fake_check):
            last = sr.submit_run('rd', dependency='7')
        runs = [c for c in calls if c[0] == 'run']
        self.assertEqual([(c[1], c[2]) for c in runs], [('2015-2015', '7'), ('2016-2016', '1'), ('2017-2017', '2')])
        checks = [c for c in calls if c[0] == 'check']
        self.assertEqual(checks, [('check', '2015-2015', '1'), ('check', '2016-2016', '2'), ('check', '2017-2017', '3'),
                                  ('check', None, '3')])
        self.assertEqual(last, '3')

    def test_retry_from_chunk(self):
        calls = []
        with mock.patch.object(sr.rm, 'load', return_value=chunked_manifest()), \
                mock.patch.object(sr, 'submit', side_effect=lambda rd, d=None, chunk=None: calls.append((chunk, d)) or 'j'), \
                mock.patch.object(sr.sc, 'submit'):
            sr.submit_run('rd', check=True, from_chunk=1)
        self.assertEqual(calls, [('2016-2016', None), ('2017-2017', 'j')])

    def test_spinup_gets_the_convergence_test(self):
        runs, checks = [], []
        m = {**chunked_manifest(), 'segment_id': 'ec-earth3-esm-1-1_picontrol_1850soc_default_spinup'}
        with mock.patch.object(sr.rm, 'load', return_value=m), \
                mock.patch.object(sr, 'submit', side_effect=lambda rd, d=None, chunk=None: runs.append((chunk, d)) or chunk), \
                mock.patch.object(sr.sc, 'submit', side_effect=lambda *a, **k: checks.append(k)):
            last = sr.submit_run('rd', dependency='7', check=True)
        self.assertEqual(runs, [('2015-2015', '7'), ('2016-2016', '2015-2015'), ('2017-2017', '2016-2016')])
        self.assertEqual(checks, [{'dependency': '2017-2017', 'spinup': True}])   # once, after the last chunk
        self.assertEqual(last, '2017-2017')


class CompareRunsTest(unittest.TestCase):
    def test_arrays(self):
        import numpy as np
        a = np.array([[1.0, np.nan], [3.0, 4.0]])
        self.assertEqual(cr.compare_arrays(a, a.copy()), (0, 0.0, 4.0))
        b = a.copy(); b[1, 1] = 4.5
        self.assertEqual(cr.compare_arrays(a, b), (1, 0.5, 4.0))
        mask = np.array([[True, True], [True, False]])            # the differing value is outside the domain
        self.assertEqual(cr.compare_arrays(a, b, mask)[0], 0)

    def test_files_and_years(self):
        import tempfile
        import numpy as np
        import netCDF4 as nc
        with tempfile.TemporaryDirectory() as d:
            for name, val in (('a.nc', 1.0), ('b.nc', 1.0), ('c.nc', 2.0)):
                with nc.Dataset(f'{d}/{name}', 'w') as f:
                    f.createDimension('time', 2); f.createDimension('lat', 2); f.createDimension('lon', 2)
                    f.createVariable('OUT_X', 'f4', ('time', 'lat', 'lon'))[:] = np.full((2, 2, 2), val)
            mask = np.ones((2, 2), bool)
            self.assertEqual(cr.compare_files(f'{d}/a.nc', f'{d}/b.nc', mask)[0]['OUT_X']['values_differing'], 0)
            self.assertEqual(cr.compare_files(f'{d}/a.nc', f'{d}/c.nc', mask)[0]['OUT_X']['values_differing'], 8)
        m = chunked_manifest()
        self.assertEqual(cr.year_dirs('/r', m)[2016], '/r/chunks/2016-2016')
        self.assertEqual(cr.year_dirs('/r', {'period': {'start': '2015-01-01', 'end': '2016-12-31'}}),
                         {2015: '/r', 2016: '/r'})


if __name__ == '__main__':
    unittest.main()
