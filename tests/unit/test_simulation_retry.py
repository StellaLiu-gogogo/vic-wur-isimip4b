"""Unit tests for two maintenance paths of workflow/05_simulation/submit/: a retry with a new Slurm job file
(submit_run.py --retry --rerender-job) and the log rescan of an attempt (run_manifest.py rescan-logs).

--rerender-job renders config/job.sbatch again from the current template and resources, keeps the previous job file
as config/job.attempt-<n>.sbatch, records both in the manifest (job_files) and leaves the inputs fingerprint
unchanged, so the retry is a new attempt of the same run; it refuses when another rendered file changed or the kept
name exists. rescan-logs recomputes the log scan of one attempt from its own log files and changes nothing else.

The run directory is synthetic, in a temporary workdir; Slurm (sbatch, scontrol), conda and git are replaced by
stand-ins. The resources file and the job template are read from the repository.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import contextlib, copy, datetime, hashlib, io, json, os, shutil, sys, tempfile, types, unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'submit'))
import run_manifest as rm    # noqa: E402
import submit_run as sr      # noqa: E402

RESOURCES = 'configs/resources/vic-global-5arcmin.yaml'


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def make_run(W, attempts, groups=128, modules=('2025', 'netCDF/4.9.3-gompi-2025a')):
    """runs/c/r rendered with an old job file and the given attempts (decomposition groups and runtime modules of the
    build as recorded in resolved.yaml)."""
    rd = os.path.join(W, 'runs', 'c', 'r')
    for sub in ('config', 'logs', 'states', 'output', 'forcing'):
        os.makedirs(os.path.join(rd, sub))
    files = {'config/vic_global.txt': 'vic global\n', 'config/vic_constants.txt': 'constants\n',
             rm.JOB_FILE: 'old job\n'}
    for rel, text in files.items():
        with open(os.path.join(rd, rel), 'w') as fh:
            fh.write(text)
    model = {'commit': 'm' * 40, 'executable': 'builds/vic/m/bin/vic_image.exe', 'executable_sha256': 'e' * 64,
             'runtime_modules': list(modules)}
    with open(os.path.join(rd, 'config', 'resolved.yaml'), 'w') as fh:
        yaml.safe_dump({'campaign_id': 'c', 'run_id': 'r', 'start_year': 2015, 'end_year': 2016,
                        'resources_file': RESOURCES, 'model': model,
                        'decomposition': {'groups': groups, 'largest_group_cells': 10, 'smallest_group_cells': 1,
                                          'active_cells': 100}}, fh)
    m = {'run_id': 'r', 'status': attempts[-1]['status'] if attempts else 'rendered', 'run_dir': 'runs/c/r',
         'parent': {'segment_id': None, 'init_state': None, 'initialisation': 'cold_start'},
         'model': {'executable': model['executable'], 'executable_sha256': model['executable_sha256']},
         'inputs': {'parameters': {}, 'forcing_units': {}}, 'forcing_view': {}, 'forcing_links': {},
         'rendered_files': {rel: text_sha(t) for rel, t in files.items()},
         'expected_outputs': ['output/daily.2015-01-01.nc'], 'attempts': attempts}
    m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
    rm.save(rd, m)
    return rd


class RerenderJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.rd = make_run(self.W, [{'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-07T00:00:00Z',
                                     'status': 'failed', 'failure_reason': 'TIMEOUT'}])
        self.calls = []; self.next_id = iter((201, 202))

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, cmd, **kw):
        self.calls.append(cmd[0])
        if cmd[0] == 'conda':
            return types.SimpleNamespace(returncode=0, stdout='/conda\n', stderr='')
        if cmd[0] == 'sbatch':
            return types.SimpleNamespace(returncode=0, stdout=f'{next(self.next_id)}\n', stderr='')
        if cmd[0] == 'scontrol':
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(f'unexpected command {cmd}')

    def retry(self, rerender=True):
        argv = ['submit_run', '--retry', 'runs/c/r', '--no-check'] + (['--rerender-job'] if rerender else [])
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}), mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(sr.subprocess, 'run', side_effect=self.fake_run), \
                mock.patch.object(sr.rr, 'git_state', return_value=('c' * 40, False)), \
                contextlib.redirect_stdout(io.StringIO()):
            sr.main()

    def read(self, rel):
        with open(os.path.join(self.rd, rel)) as fh:
            return fh.read()

    def test_new_job_file_and_same_fingerprint(self):
        before = rm.load(self.rd)
        self.retry()
        m = rm.load(self.rd)
        self.assertEqual(self.read('config/job.attempt-1.sbatch'), 'old job\n')
        new = self.read(rm.JOB_FILE)
        self.assertNotIn('{{', new)
        self.assertIn('#SBATCH', new)
        self.assertIn(self.rd, new)
        self.assertEqual(m['rendered_files'][rm.JOB_FILE], text_sha(new))
        self.assertEqual({k: v for k, v in m['rendered_files'].items() if k != rm.JOB_FILE},
                         {k: v for k, v in before['rendered_files'].items() if k != rm.JOB_FILE})
        self.assertEqual(m['inputs_fingerprint'], before['inputs_fingerprint'])
        self.assertEqual(rm.inputs_fingerprint(m), before['inputs_fingerprint'])
        with open(os.path.join(REPO, RESOURCES)) as fh:
            res = yaml.safe_load(fh)
        jf = m['job_files']
        self.assertEqual(len(jf), 1)
        self.assertEqual((jf[0]['kept_as'], jf[0]['sha256']), ('config/job.attempt-1.sbatch', text_sha('old job\n')))
        self.assertEqual((jf[0]['replaced_by_commit'], jf[0]['code_dirty']), ('c' * 40, False))
        self.assertEqual(jf[0]['resources'], {k: res[k] for k in ('ntasks', 'cpus_per_task', 'mem', 'launcher')})
        self.assertIsInstance(jf[0]['wall_time_hours'], int)
        # the retry is a new attempt of the same run, submitted with the new job file
        self.assertEqual([(a['attempt'], a['status']) for a in m['attempts']], [(1, 'failed'), (2, 'submitted')])
        self.assertEqual(m['attempts'][1]['slurm_job_id'], 201)
        self.assertEqual(m['attempts'][1]['inputs_fingerprint'], before['inputs_fingerprint'])
        self.assertEqual(self.calls, ['conda', 'sbatch', 'scontrol'])

    def test_second_rerender_keeps_both_job_files(self):
        self.retry()
        m = rm.load(self.rd); m['attempts'][1]['status'] = 'failed'; m['status'] = 'failed'; rm.save(self.rd, m)
        first = self.read(rm.JOB_FILE)
        self.retry()
        m = rm.load(self.rd)
        self.assertEqual(self.read('config/job.attempt-1.sbatch'), 'old job\n')
        self.assertEqual(self.read('config/job.attempt-2.sbatch'), first)
        self.assertEqual([j['kept_as'] for j in m['job_files']], ['config/job.attempt-1.sbatch',
                                                                  'config/job.attempt-2.sbatch'])
        self.assertEqual(m['job_files'][1]['sha256'], text_sha(first))
        self.assertEqual([a['slurm_job_id'] for a in m['attempts']], [101, 201, 202])

    def test_changed_model_file_refused(self):
        with open(os.path.join(self.rd, 'config', 'vic_global.txt'), 'w') as fh:
            fh.write('edited by hand\n')
        before = rm.load(self.rd)
        with self.assertRaises(SystemExit) as cm:
            self.retry()
        self.assertIn('config/vic_global.txt differs from the rendered file', str(cm.exception))
        self.assertEqual(self.read(rm.JOB_FILE), 'old job\n')
        self.assertFalse(os.path.exists(os.path.join(self.rd, 'config', 'job.attempt-1.sbatch')))
        self.assertEqual(rm.load(self.rd), before)
        self.assertNotIn('sbatch', self.calls)

    def assert_refused(self, message):
        before = rm.load(self.rd)
        with self.assertRaises(SystemExit) as cm:
            self.retry()
        self.assertIn(message, str(cm.exception))
        self.assertEqual(self.read(rm.JOB_FILE), 'old job\n')
        self.assertEqual(rm.load(self.rd), before)
        self.assertNotIn('sbatch', self.calls)

    def test_more_tasks_than_groups_refused(self):
        """Review P3 A3: the job file rendered again is checked like a new render (MPI tasks <= groups)."""
        shutil.rmtree(os.path.join(self.W, 'runs'))
        self.rd = make_run(self.W, [{'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-07T00:00:00Z',
                                     'status': 'failed'}], groups=4)
        self.assert_refused('decomposition groups')

    def test_other_modules_refused(self):
        """Review P3 A3: the resources modules must equal the runtime modules of the build."""
        shutil.rmtree(os.path.join(self.W, 'runs'))
        self.rd = make_run(self.W, [{'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-07T00:00:00Z',
                                     'status': 'failed'}], modules=('2024', 'netCDF/4.9.2'))
        self.assert_refused('runtime_modules')

    def test_kept_name_exists_refused(self):
        with open(os.path.join(self.rd, 'config', 'job.attempt-1.sbatch'), 'w') as fh:
            fh.write('an earlier file\n')
        before = rm.load(self.rd)
        with self.assertRaises(SystemExit) as cm:
            self.retry()
        self.assertIn('job.attempt-1.sbatch exists', str(cm.exception))
        self.assertEqual(self.read(rm.JOB_FILE), 'old job\n')
        self.assertEqual(self.read('config/job.attempt-1.sbatch'), 'an earlier file\n')
        self.assertEqual(rm.load(self.rd), before)

    def test_completed_run_not_retried(self):
        m = rm.load(self.rd); m['attempts'][0]['status'] = 'completed'; rm.save(self.rd, m)
        with self.assertRaises(SystemExit) as cm:
            self.retry()
        self.assertIn('nothing to retry', str(cm.exception))
        self.assertEqual(self.read(rm.JOB_FILE), 'old job\n')

    def test_retry_without_rerender_keeps_job_file(self):
        before = rm.load(self.rd)
        self.retry(rerender=False)
        m = rm.load(self.rd)
        self.assertEqual(self.read(rm.JOB_FILE), 'old job\n')
        self.assertNotIn('job_files', m)
        self.assertEqual(m['rendered_files'], before['rendered_files'])
        self.assertEqual(len(m['attempts']), 2)


class RescanLogsTest(unittest.TestCase):
    """Attempt 2 (job 202) started at 2026-10-07T12:00:00Z; logs/ also holds the files of attempt 1 (job 101)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        old_scan = {'files': ['logs/old.txt'], 'categories': {'warning': {'count': 99, 'examples': []}}}
        self.rd = make_run(self.W, [
            {'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-06T00:00:00Z',
             'started_at': '2026-10-06T00:00:00Z', 'status': 'failed', 'log_scan': copy.deepcopy(old_scan)},
            {'attempt': 2, 'slurm_job_id': 202, 'submitted_at': '2026-10-07T11:00:00Z',
             'started_at': '2026-10-07T12:00:00Z', 'status': 'completed', 'vic_exit_code': 0,
             'vic_timing': {'Run Time': {'wall_s': 1.0}}, 'log_scan': copy.deepcopy(old_scan)}])
        logs = os.path.join(self.rd, 'logs')
        self.write(f'{logs}/vic_stdout_202.txt', '[WARN] no vegetation tile in cell 5\n'
                   '[ERROR] withdrawal larger than demand\nall fine\n', '2026-10-07T13:00:00')
        self.write(f'{logs}/slurm-202.out', 'warning: missing value in cell 7\n', '2026-10-07T13:00:00')
        self.write(f'{logs}/vic.log.0000.txt', '[WARN] Nveg 3 at cell 9\n', '2026-10-07T12:30:00')
        self.write(f'{logs}/vic_stdout_101.txt', '[WARN] tile\n' * 5, '2026-10-06T01:00:00')     # attempt 1
        self.write(f'{logs}/vic.log.old.txt', '[WARN] fcanopy\n', '2026-10-06T01:00:00')           # attempt 1

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text, mtime):
        with open(path, 'w') as fh:
            fh.write(text)
        t = datetime.datetime.fromisoformat(mtime).replace(tzinfo=datetime.timezone.utc).timestamp()
        os.utime(path, (t, t))

    def rescan(self, job_id):
        argv = ['run_manifest.py', 'rescan-logs', '--run-dir', self.rd, '--job-id', str(job_id)]
        out = io.StringIO()
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}), mock.patch.object(sys, 'argv', argv), \
                contextlib.redirect_stdout(out):
            rm.main()
        return json.loads(out.getvalue())

    def test_rescan_one_attempt(self):
        before = rm.load(self.rd)
        counts = self.rescan(202)
        m = rm.load(self.rd)
        scan = m['attempts'][1]['log_scan']
        self.assertEqual(sorted(scan['files']), ['logs/slurm-202.out', 'logs/vic.log.0000.txt', 'logs/vic_stdout_202.txt'])
        self.assertIn('rescanned_at', scan)
        cat = scan['categories']
        self.assertEqual(counts, {k: v['count'] for k, v in cat.items()})
        self.assertEqual((cat['warning']['count'], cat['error']['count']), (2, 1))
        self.assertEqual((cat['tile_allocation']['count'], cat['nveg']['count'], cat['fcanopy']['count']), (1, 1, 0))
        self.assertEqual((cat['water_use']['count'], cat['missing_cells']['count']), (1, 1))
        self.assertIn('[WARN] no vegetation tile in cell 5', cat['tile_allocation']['examples'])
        # nothing else changes: the other attempt, the other keys of this attempt, the run record
        self.assertEqual(m['attempts'][0], before['attempts'][0])
        self.assertEqual({k: v for k, v in m['attempts'][1].items() if k != 'log_scan'},
                         {k: v for k, v in before['attempts'][1].items() if k != 'log_scan'})
        self.assertEqual({k: v for k, v in m.items() if k != 'attempts'}, {k: v for k, v in before.items() if k != 'attempts'})

    def test_unknown_job_id(self):
        before = rm.load(self.rd)
        with self.assertRaises(SystemExit) as cm:
            self.rescan(303)
        self.assertIn('no attempt with job id 303', str(cm.exception))
        self.assertEqual(rm.load(self.rd), before)


if __name__ == '__main__':
    unittest.main()
