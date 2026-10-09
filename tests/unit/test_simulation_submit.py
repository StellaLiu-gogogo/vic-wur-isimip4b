"""Unit tests for workflow/05_simulation/submit/ (run_manifest.py, submit_run.py) and the run job template: the exit
status of the completion step and of the job, one submission at a time per run, and the input checks of the
forcing view and the parent state. Slurm, git and the filesystem of the run are mocked or synthetic (temporary
directories); nothing under the workdir is read or written.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, subprocess, sys, tempfile, types, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'submit'))
import run_manifest as rm    # noqa: E402
import submit_run as sr      # noqa: E402

SLURM_TEMPLATE = os.path.join(REPO, 'workflow', '05_simulation', 'templates', 'slurm', 'vic_run.sbatch')


def sha256(path):
    return rm.file_hash(path, 'sha256')


def make_run(W, run_id='r', files=None, parent=None, forcing_view=None, units=None, links=None):
    """A rendered run directory under W/runs/c/<run_id> with a manifest of no attempts."""
    rd = os.path.join(W, 'runs', 'c', run_id)
    for sub in ('config', 'logs', 'states', 'output', 'forcing'):
        os.makedirs(os.path.join(rd, sub))
    files = files or {'config/vic_global.txt': 'vic', 'config/job.sbatch': 'job'}
    for rel, text in files.items():
        with open(os.path.join(rd, rel), 'w') as fh:
            fh.write(text)
    exe = os.path.join(W, 'vic.exe')
    with open(exe, 'w') as fh:
        fh.write('exe')
    m = {'run_id': run_id, 'status': 'rendered', 'run_dir': os.path.relpath(rd, W),
         'parent': parent or {'segment_id': None, 'init_state': None, 'initialisation': 'cold_start'},
         'model': {'executable': 'vic.exe', 'executable_sha256': sha256(exe)},
         'inputs': {'parameters': {}, 'forcing_units': units or {}}, 'forcing_view': forcing_view or {},
         'forcing_links': links or {},
         'rendered_files': {rel: rm.hashlib.sha256(t.encode()).hexdigest() for rel, t in files.items()},
         'expected_outputs': ['output/daily.2015-01-01.nc', 'states/state.20160101_00000.nc'], 'attempts': []}
    m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
    rm.save(rd, m)
    return rd


# ------------------------------------------------------------------------------------------------ finding 4
class CompletionExitTest(unittest.TestCase):
    """complete() must end with a failure exit status when it records the attempt as failed, and the job must end
    with a failure status when VIC or the completion step fails, so that afterok children do not start."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.rd = make_run(self.W)
        m = rm.load(self.rd)
        m['attempts'].append({'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-07T00:00:00Z',
                              'started_at': '2026-10-07T00:00:00Z', 'status': 'running',
                              'input_verification': {'passed': True}})
        rm.save(self.rd, m)
        git = types.SimpleNamespace(stdout='c' * 40, returncode=0)
        self.patches = [mock.patch.object(rm, 'sacct', return_value=[]),
                        mock.patch.object(rm.subprocess, 'run', return_value=git)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_missing_outputs_exit_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            rm.complete(self.rd, 101, 0, self.W)                          # VIC 0, no output files
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(rm.load(self.rd)['attempts'][0]['status'], 'failed')

    def test_complete_run_exits_normally(self):
        for rel in rm.load(self.rd)['expected_outputs']:
            open(os.path.join(self.rd, rel), 'w').close()
        rm.complete(self.rd, 101, 0, self.W)
        self.assertEqual(rm.load(self.rd)['attempts'][0]['status'], 'completed')


class JobExitTest(unittest.TestCase):
    """The job's exit status reflects VIC and the completion step."""

    def job_exit(self, vic_rc, complete_rc):
        """Exit status of the template's last lines (completion step to the end) with VIC's exit code `vic_rc` and
        the completion step replaced by true (0) or false (1)."""
        with open(SLURM_TEMPLATE) as fh:
            text = fh.read()
        tail = text[text.index('$MANIFEST complete'):]
        script = (f'set -uo pipefail\nRUN_DIR=/x\nSLURM_JOB_ID=1\nrc={vic_rc}\n'
                  f'MANIFEST={"true" if complete_rc == 0 else "false"}\n' + tail)
        return subprocess.run(['bash', '-c', script], capture_output=True, text=True).returncode

    def test_job_exit_status(self):
        self.assertEqual(self.job_exit(0, 0), 0)
        self.assertNotEqual(self.job_exit(0, 1), 0)                        # outputs missing, or the step failed
        self.assertNotEqual(self.job_exit(3, 1), 0)
        self.assertNotEqual(self.job_exit(3, 0), 0)

    def test_failed_input_check_skips_vic(self):
        """The template's lines from verify-inputs to the end of the VIC block, with verify-inputs replaced by false
        (a non-zero exit status) and the VIC launcher by a marker: VIC must not start and rc must stay non-zero."""
        with open(SLURM_TEMPLATE) as fh:
            text = fh.read()
        start = text.index('$MANIFEST verify-inputs'); end = text.index('\nfi\n', start) + 4
        block = text[start:end]
        for key, value in (('CHECK_PROCESSES', '2'), ('MODULE_LOADS', ''), ('LAUNCHER', 'echo VIC_STARTED;'),
                           ('EXECUTABLE', 'vic')):
            block = block.replace('{{' + key + '}}', value)
        self.assertNotIn('{{', block)
        script = f'set -uo pipefail\nRUN_DIR=/x\nSLURM_JOB_ID=1\nMANIFEST=false\n{block}echo "rc=$rc"\n'
        r = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertNotIn('VIC_STARTED', r.stdout)
        self.assertIn('rc=1', r.stdout)


# ------------------------------------------------------------------------------------------------ finding 1
class ConcurrentSubmitTest(unittest.TestCase):
    """Two submissions of one run: only one may be released, and every released job keeps its attempt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.rd = make_run(self.W)
        self.released, self.cancelled, self.inner = [], [], []
        self.next_id = iter((101, 102, 103))

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, cmd, **kw):
        if cmd[0] == 'sbatch':
            job = next(self.next_id)
            if job == 101:                     # a second submission starts while the first one is between steps
                try:
                    self.inner.append(sr.submit(self.rd))
                except SystemExit as e:
                    self.inner.append(f'refused: {e}')
            return types.SimpleNamespace(returncode=0, stdout=f'{job}\n', stderr='')
        if cmd[0] == 'scontrol':
            self.released.append(cmd[-1])
        if cmd[0] == 'scancel':
            self.cancelled.append(cmd[-1])
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    def test_one_submission_at_a_time(self):
        with mock.patch.object(sr.subprocess, 'run', side_effect=self.fake_run), \
                mock.patch.object(sr.rr, 'git_state', return_value=('c' * 40, False)):
            sr.submit(self.rd)
        self.assertEqual(self.released, ['101'])
        self.assertTrue(str(self.inner[0]).startswith('refused'))
        self.assertEqual([a['slurm_job_id'] for a in rm.load(self.rd)['attempts']], [101])

    def test_save_keeps_newer_attempts(self):
        a, b = rm.load(self.rd), rm.load(self.rd)                      # two readers of the same manifest
        a['attempts'].append({'attempt': 1, 'slurm_job_id': 101, 'status': 'submitted'})
        rm.save(self.rd, a)
        b['attempts'].append({'attempt': 1, 'slurm_job_id': 102, 'status': 'submitted'})
        with self.assertRaises(rm.ManifestConflict):
            rm.save(self.rd, b)
        self.assertEqual([x['slurm_job_id'] for x in rm.load(self.rd)['attempts']], [101])
        a['attempts'][0]['status'] = 'running'                         # updating the newest list is allowed
        rm.save(self.rd, a)
        self.assertEqual(rm.load(self.rd)['attempts'][0]['status'], 'running')


# ------------------------------------------------------------------------------------------------ finding 5
class InputCheckTest(unittest.TestCase):
    """verify-inputs checks the links VIC opens and the parent state file; the fingerprint covers the parent state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        unit = os.path.join(W, 'forcing', 'landuse', 'histsoc')
        os.makedirs(unit)
        with open(os.path.join(unit, 'provenance.yaml'), 'w') as fh:              # an accepted unit
            fh.write('forcing_unit: landuse/histsoc\ncode_dirty: false\nqc:\n  status: passed\n')
        for y in (2015, 2016):
            with open(os.path.join(unit, f'coverage_histsoc_{y}.nc'), 'w') as fh:
                fh.write(f'coverage {y}')
        src = {y: f'forcing/landuse/histsoc/coverage_histsoc_{y}.nc' for y in (2015, 2016)}
        units = {'landuse/histsoc': {'files': {os.path.basename(p): {'path': p, 'sha256': sha256(os.path.join(W, p))}
                                               for p in src.values()}}}
        view = {'landuse': {str(y): {'source': src[y], 'rule': 'identity'} for y in (2015, 2016)}}
        links = {f'forcing/landuse/coverage_histsoc_{y}.nc': src[y] for y in (2015, 2016)}
        # parent run with its end state
        self.prd = make_run(W, 'p')
        pm = rm.load(self.prd)
        pm['attempts'] = [{'attempt': 1, 'slurm_job_id': 90, 'status': 'completed'}]; pm['status'] = 'completed'
        rm.save(self.prd, pm)
        self.state = os.path.join(self.prd, 'states', 'state.20150101_00000.nc')
        with open(self.state, 'w') as fh:
            fh.write('state')
        parent = {'segment_id': 'p', 'init_state': os.path.relpath(self.state, W),
                  'initialisation': 'state of the parent run', 'run_id': 'p', 'attempt': 1,
                  'state_sha256': sha256(self.state)}
        self.rd = make_run(W, 'r', parent=parent, forcing_view=view, units=units, links=links)
        os.makedirs(os.path.join(self.rd, 'forcing', 'landuse'))
        for y in (2015, 2016):
            os.symlink(os.path.relpath(os.path.join(W, src[y]), os.path.join(self.rd, 'forcing', 'landuse')),
                       os.path.join(self.rd, 'forcing', 'landuse', f'coverage_histsoc_{y}.nc'))
        m = rm.load(self.rd)
        m['attempts'].append({'attempt': 1, 'slurm_job_id': 101, 'submitted_at': '2026-10-07T00:00:00Z',
                              'status': 'submitted'})
        rm.save(self.rd, m)

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, stops=False):
        """Run verify-inputs for attempt 1 and return its record. With stops=True it must end with a non-zero exit
        status (the job script then stops before VIC starts); otherwise it must return normally."""
        code = None
        try:
            rm.verify_inputs(self.rd, 101, self.W, 2)
        except SystemExit as e:
            code = 1 if isinstance(e.code, str) else e.code           # sys.exit(message) exits with status 1
        if stops:
            self.assertTrue(code, 'verify-inputs found a mismatch but did not end with a non-zero exit status')
        else:
            self.assertIsNone(code)
        return rm.load(self.rd)['attempts'][0]['input_verification']

    def test_clean_run_passes(self):
        v = self.verify()
        self.assertTrue(v['passed'], v)

    def test_redirected_link_fails(self):
        link = os.path.join(self.rd, 'forcing', 'landuse', 'coverage_histsoc_2016.nc')
        os.remove(link)
        os.symlink('../../../../../forcing/landuse/histsoc/coverage_histsoc_2015.nc', link)   # wrong year
        v = self.verify(stops=True)
        self.assertFalse(v['passed'])
        self.assertIn('forcing/landuse/coverage_histsoc_2016.nc', v['mismatches'])

    def test_changed_parent_state_fails(self):
        with open(self.state, 'w') as fh:
            fh.write('another state')
        v = self.verify(stops=True)
        self.assertFalse(v['passed'])
        self.assertIn(rm.load(self.rd)['parent']['init_state'], v['mismatches'])

    def test_fingerprint_covers_parent_state(self):
        m = rm.load(self.rd)
        f1 = rm.inputs_fingerprint(m)
        m['parent']['state_sha256'] = '0' * 64
        self.assertNotEqual(f1, rm.inputs_fingerprint(m))

    def test_parent_rendered_in_the_same_call(self):
        """The parent was not finished at rendering (state_sha256 unknown): the job checks that the parent completed
        and binds the state checksum to the attempt; a retry must find the same state."""
        m = rm.load(self.rd)
        m['parent']['state_sha256'] = None; m['parent']['attempt'] = None
        m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
        rm.save(self.rd, m)
        v = self.verify()
        self.assertTrue(v['passed'], v)
        self.assertEqual(v['parent_state']['sha256'], sha256(self.state))
        self.assertEqual(v['parent_state']['attempt'], 1)
        m = rm.load(self.rd)                                           # retry after the state changed
        m['attempts'][0]['status'] = 'failed'
        m['attempts'].append({'attempt': 2, 'slurm_job_id': 102, 'submitted_at': '2026-10-07T01:00:00Z',
                              'status': 'submitted'})
        rm.save(self.rd, m)
        with open(self.state, 'w') as fh:
            fh.write('another state')
        with self.assertRaises(SystemExit):
            rm.verify_inputs(self.rd, 102, self.W, 2)
        self.assertFalse(rm.load(self.rd)['attempts'][1]['input_verification']['passed'])

    def test_parent_not_completed_fails(self):
        m = rm.load(self.rd)
        m['parent']['state_sha256'] = None; m['parent']['attempt'] = None
        rm.save(self.rd, m)
        pm = rm.load(self.prd); pm['attempts'][0]['status'] = 'failed'; pm['status'] = 'failed'
        rm.save(self.prd, pm)
        v = self.verify(stops=True)
        self.assertFalse(v['passed'])


if __name__ == '__main__':
    unittest.main()
