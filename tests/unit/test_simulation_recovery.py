"""Unit tests for the recovery of a chain after a failed, timed-out or cancelled job (review 2026-11-01, R2, R16,
R18): run_manifest.reconcile (attempts compared with sacct), the TERM trap of the run job template, the submission
with --kill-on-invalid-dep, the campaign recovery ledger and submit_run.py --resume (parents first, dependencies on
the parent's job). Slurm is replaced by stand-ins; run directories are synthetic, in a temporary workdir.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import contextlib, io, json, os, subprocess, sys, tempfile, types, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'submit'))
import run_manifest as rm    # noqa: E402
import submit_run as sr      # noqa: E402

SLURM_TEMPLATE = os.path.join(REPO, 'workflow', '05_simulation', 'templates', 'slurm', 'vic_run.sbatch')


def row(job, state, reason='None', exit_code='0:0', end='2026-11-02T10:00:00'):
    return {'JobID': str(job), 'State': state, 'ExitCode': exit_code, 'Elapsed': '01:00:00', 'ElapsedRaw': '3600',
            'MaxRSS': '', 'NNodes': '1', 'NCPUS': '128', 'NodeList': 'node1', 'Start': '2026-11-02T09:00:00',
            'End': end, 'Reason': reason}


def make_run(W, campaign, run_id, attempts, chunks=('2015-2015', '2016-2016'), parent=None, production=False):
    """A chunked run directory with the given attempts; `parent`: workdir-relative end state it starts from."""
    rd = os.path.join(W, 'runs', campaign, run_id)
    cs = []
    for cid in chunks:
        y = int(cid[:4])
        for sub in ('config', 'logs', 'states', 'output', 'forcing'):
            os.makedirs(os.path.join(rd, 'chunks', cid, sub))
        with open(os.path.join(rd, 'chunks', cid, 'config', 'job.sbatch'), 'w') as fh:
            fh.write('job\n')
        cs.append({'id': cid, 'start_year': y, 'end_year': y, 'dir': f'chunks/{cid}', 'job_file': f'chunks/{cid}/config/job.sbatch',
                   'end_state': f'chunks/{cid}/states/state.{y + 1}0101_00000.nc', 'expected_outputs': []})
    m = {'run_id': run_id, 'segment_id': run_id, 'status': 'rendered', 'run_dir': f'runs/{campaign}/{run_id}',
         'production': production, 'period': {'start': f'{cs[0]["start_year"]}-01-01', 'end': f'{cs[-1]["end_year"]}-12-31'},
         'parent': {'segment_id': None, 'init_state': parent, 'initialisation': 'cold_start' if not parent else 'state of the parent run'},
         'model': {'executable': 'vic.exe', 'executable_sha256': 'e' * 64}, 'inputs': {'parameters': {}, 'forcing_units': {}},
         'forcing_view': {}, 'forcing_links': {}, 'chunks': cs, 'end_state': cs[-1]['end_state'],
         'rendered_files': {c['job_file']: rm.hashlib.sha256(b'job\n').hexdigest() for c in cs},
         'expected_outputs': [], 'attempts': attempts}
    m['inputs_fingerprint'] = rm.inputs_fingerprint(m)
    m['status'] = rm.run_status(m) if attempts else 'rendered'
    rm.save(rd, m)
    return rd


def attempt(n, job, chunk, status, dependency=None):
    return {'attempt': n, 'slurm_job_id': job, 'chunk': chunk, 'status': status, 'dependency': dependency,
            'submitted_at': '2026-11-02T00:00:00Z'}


class ReconcileTest(unittest.TestCase):
    """Attempts still 'submitted' or 'running' are compared with the scheduler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.rd = make_run(self.W, 'c', 'r', [
            attempt(1, 11, '2015-2015', 'running'), attempt(2, 12, '2016-2016', 'submitted', dependency='11')])
        self.cancelled = []

    def tearDown(self):
        self.tmp.cleanup()

    def reconcile(self, rows):
        with mock.patch.object(rm, 'sacct', side_effect=lambda j: rows.get(int(j), [])), \
                contextlib.redirect_stdout(io.StringIO()):
            return rm.reconcile(self.rd, cancel=lambda j: self.cancelled.append(int(j)))

    def test_timeout_and_dependency_never_satisfied(self):
        rows = {11: [row(11, 'TIMEOUT', exit_code='0:0'), dict(row(11, 'CANCELLED'), JobID='11.batch')],
                12: [row(12, 'PENDING', reason='DependencyNeverSatisfied', end='Unknown')]}
        changed = self.reconcile(rows)
        self.assertEqual([(c['attempt'], c['status']) for c in changed], [(1, 'timeout'), (2, 'cancelled')])
        self.assertEqual(self.cancelled, [12])
        m = rm.load(self.rd)
        a1, a2 = m['attempts']
        self.assertEqual((a1['status'], a1['scheduler'][0]['State'], a1['reconciled']['nodes']), ('timeout', 'TIMEOUT', 'node1'))
        self.assertIn('TIMEOUT', a1['failure_reason'])
        self.assertEqual(a2['status'], 'cancelled'); self.assertIn('DependencyNeverSatisfied', a2['failure_reason'])
        self.assertEqual(m['status'], 'failed')
        self.assertEqual(rm.first_incomplete_chunk(m), 0)
        # a second reconciliation changes nothing
        self.assertEqual(self.reconcile(rows), [])

    def test_live_jobs_left_alone(self):
        rows = {11: [row(11, 'RUNNING', end='Unknown')], 12: [row(12, 'PENDING', reason='Dependency', end='Unknown')]}
        before = rm.load(self.rd)
        self.assertEqual(self.reconcile(rows), [])
        self.assertEqual(rm.load(self.rd), before); self.assertEqual(self.cancelled, [])

    def test_failed_node_fail_and_unknown(self):
        rows = {11: [row(11, 'NODE_FAIL', exit_code='1:0')]}                  # job 12 unknown to sacct
        changed = self.reconcile(rows)
        self.assertEqual([(c['attempt'], c['status']) for c in changed], [(1, 'failed')])
        m = rm.load(self.rd)
        self.assertIn('NODE_FAIL', m['attempts'][0]['failure_reason'])
        self.assertEqual(m['attempts'][1]['status'], 'submitted')

    def test_cancelled_by_user_and_completed_without_manifest(self):
        rows = {11: [row(11, 'CANCELLED by 1000')], 12: [row(12, 'COMPLETED')]}
        changed = self.reconcile(rows)
        self.assertEqual([c['status'] for c in changed], ['cancelled', 'failed'])
        self.assertIn('not completed', rm.load(self.rd)['attempts'][1]['failure_reason'])

    def test_inside_the_job_rows_are_kept(self):
        m = rm.load(self.rd); m['attempts'][0]['scheduler'] = [row(11, 'RUNNING', end='Unknown')]; rm.save(self.rd, m)
        self.reconcile({11: [row(11, 'TIMEOUT')]})
        a = rm.load(self.rd)['attempts'][0]
        self.assertEqual(a['scheduler_at_completion'][0]['State'], 'RUNNING')
        self.assertEqual(a['scheduler'][0]['State'], 'TIMEOUT')


class RecordSchedulerTest(unittest.TestCase):
    """R16: the check job stores the final sacct rows of an ended run job; rows of a live job are not stored."""

    def test_final_rows(self):
        with tempfile.TemporaryDirectory() as W:
            rd = make_run(W, 'c', 'r', [attempt(1, 11, '2015-2015', 'completed'), attempt(2, 12, '2016-2016', 'running')])
            m = rm.load(rd); m['attempts'][0]['scheduler'] = [row(11, 'RUNNING', end='Unknown')]; rm.save(rd, m)
            rows = {11: [row(11, 'COMPLETED'), dict(row(11, 'COMPLETED'), JobID='11.batch')], 12: [row(12, 'RUNNING', end='Unknown')]}
            with mock.patch.object(rm, 'sacct', side_effect=lambda j: rows[int(j)]):
                self.assertEqual(rm.record_scheduler(rd, [11, 12]), [11])
                m = rm.load(rd)
                self.assertEqual(m['attempts'][0]['scheduler'][0]['State'], 'COMPLETED')
                self.assertEqual(m['attempts'][0]['scheduler_at_completion'][0]['State'], 'RUNNING')
                self.assertNotIn('scheduler', m['attempts'][1])
                self.assertEqual(rm.record_scheduler(rd, [11, 12]), [])      # already final: nothing to do


class TermTrapTest(unittest.TestCase):
    """The run job template: 900 s before the time limit Slurm sends TERM to the batch shell (--signal=B:TERM@900);
    VIC is stopped and the completion step records exit code 143 and the reason."""

    def script(self):
        with open(SLURM_TEMPLATE) as fh:
            text = fh.read()
        self.assertIn('#SBATCH --signal=B:TERM@900', text)
        # the part of the template from the trap definition on, with the manifest steps and VIC replaced
        body = text[text.index('TERM_SEEN=0'):]
        body = body.replace('$MANIFEST verify-inputs --run-dir "$RUN_DIR" --job-id "$SLURM_JOB_ID" --processes {{CHECK_PROCESSES}}{{CHUNK_OPTION}}',
                            'true')
        body = body.replace('{{LAUNCHER}} {{EXECUTABLE}} -g "$CHUNK_DIR/config/vic_global.txt" \\\n      > "$CHUNK_DIR/logs/vic_stdout_${SLURM_JOB_ID}.txt" 2>&1 &',
                            'sleep 30 &')
        body = body.replace('{{LAUNCHER}} bash -c \'echo "rank $SLURM_PROCID on $(hostname) cpus $(grep Cpus_allowed_list /proc/self/status | cut -f2)"\'', 'true')
        for k in ('conda deactivate', 'source /etc/profile.d/z00_lmod.sh', 'module purge', 'module -t list 2>&1 | sed \'s/^/module: /\'',
                  '{{MODULE_LOADS}}', 'conda activate isimip4b'):
            body = body.replace(k, 'true')
        body = body.replace('{{CHUNK_OPTION}}', '').replace('cd "$CHUNK_DIR"', 'true')
        import re
        body = re.sub(r'\{\{[A-Z_]+\}\}', '/x', body).replace('source /x/etc/profile.d/conda.sh', 'true')
        body = body.replace('MANIFEST="python3 /x/workflow/05_simulation/submit/run_manifest.py"', 'MANIFEST="echo MANIFEST"')
        self.assertNotIn('{{', body)
        return ('set -uo pipefail\nRUN_DIR=/x\nCHUNK_DIR=/x\nSLURM_JOB_ID=1\nSLURM_CPUS_PER_TASK=1\nMANIFEST="echo MANIFEST"\n'
                + body)

    def test_term_records_143_and_the_reason(self):
        p = subprocess.Popen(['bash', '-c', self.script()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        import time; time.sleep(1.0)
        p.send_signal(subprocess.signal.SIGTERM)
        out, _ = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143, out)
        self.assertIn('TERM received', out)
        self.assertIn('MANIFEST complete --run-dir /x --job-id 1 --exit-code 143 --reason signal TERM: time limit or cancel', out)

    def test_without_term_vic_result_is_recorded(self):
        script = self.script().replace('sleep 30 &', 'true &')
        r = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('MANIFEST complete --run-dir /x --job-id 1 --exit-code 0', r.stdout)
        self.assertNotIn('--reason', r.stdout)


class KillOnInvalidDepTest(unittest.TestCase):
    """R2 (3), R18: every submission with a dependency asks Slurm to cancel the job when the dependency fails."""

    def test_sbatch_options(self):
        with tempfile.TemporaryDirectory() as W:
            rd = make_run(W, 'c', 'r', [])
            cmds = []

            def fake_run(cmd, **kw):
                cmds.append(cmd)
                return types.SimpleNamespace(returncode=0, stdout='77\n', stderr='')
            with mock.patch.object(sr.subprocess, 'run', side_effect=fake_run), \
                    mock.patch.object(sr.rr, 'git_state', return_value=('c' * 40, False)), \
                    contextlib.redirect_stdout(io.StringIO()):
                sr.submit(rd, dependency='41', chunk='2015-2015')
                sr.submit(rd, chunk='2016-2016')
            sbatch = [c for c in cmds if c[0] == 'sbatch']
            self.assertIn('--dependency=afterok:41', sbatch[0]); self.assertIn('--kill-on-invalid-dep=yes', sbatch[0])
            self.assertNotIn('--kill-on-invalid-dep=yes', sbatch[1])


class LedgerAndResumeTest(unittest.TestCase):
    """The campaign ledger runs/<campaign-id>/recovery.json and --resume: parents first, with dependencies."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        # parent p: chunk 1 timed out (job 11, still 'running' in the manifest), chunk 2 pending on it (job 12)
        self.p = make_run(self.W, 'c', 'p', [attempt(1, 11, '2015-2015', 'running'),
                                             attempt(2, 12, '2016-2016', 'submitted', dependency='11')])
        # child k: its only job waited for p's last chunk; grandchild g waits for k
        self.k = make_run(self.W, 'c', 'k', [attempt(1, 13, '2017-2017', 'submitted', dependency='12')],
                          chunks=('2017-2017',), parent='runs/c/p/chunks/2016-2016/states/state.20170101_00000.nc')
        self.g = make_run(self.W, 'c', 'g', [attempt(1, 14, '2018-2018', 'submitted', dependency='13')],
                          chunks=('2018-2018',), parent='runs/c/k/chunks/2017-2017/states/state.20180101_00000.nc')
        # an unrelated run still running normally, and a completed one
        self.o = make_run(self.W, 'c', 'o', [attempt(1, 15, '2015-2015', 'running')], chunks=('2015-2015',))
        self.d = make_run(self.W, 'c', 'd', [attempt(1, 16, '2015-2015', 'completed')], chunks=('2015-2015',))
        self.rows = {11: [row(11, 'TIMEOUT')], 12: [row(12, 'PENDING', reason='DependencyNeverSatisfied', end='Unknown')],
                     13: [row(13, 'PENDING', reason='DependencyNeverSatisfied', end='Unknown')],
                     14: [row(14, 'PENDING', reason='DependencyNeverSatisfied', end='Unknown')],
                     15: [row(15, 'RUNNING', end='Unknown')], 16: [row(16, 'COMPLETED')]}
        self.cancelled = []
        self.patches = [mock.patch.object(rm, 'sacct', side_effect=lambda j: self.rows.get(int(j), [])),
                        mock.patch.object(rm.subprocess, 'run', side_effect=lambda cmd, **k: self.cancelled.append(cmd[-1]))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def main(self, *argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': self.W}), mock.patch.object(sys, 'argv', ['submit_run', *argv]), \
                contextlib.redirect_stdout(out):
            sr.main()
        return out.getvalue()

    def ledger(self):
        with open(os.path.join(self.W, 'runs', 'c', 'recovery.json')) as fh:
            return json.load(fh)

    def test_reconcile_campaign_writes_the_ledger(self):
        out = self.main('--reconcile', 'c')
        self.assertEqual(sorted(self.cancelled), ['12', '13', '14'])
        led = self.ledger()
        self.assertEqual(led['campaign_id'], 'c')
        entries = {e['slurm_job_id']: e for e in led['entries']}
        self.assertEqual(sorted(entries), [11, 12, 13, 14])
        self.assertEqual((entries[11]['status'], entries[11]['state'], entries[11]['chunk'], entries[11]['years']),
                         ('timeout', 'TIMEOUT', '2015-2015', [2015, 2015]))
        self.assertEqual(entries[11]['downstream_cancelled'], [12])
        self.assertEqual(entries[12]['downstream_cancelled'], [13]); self.assertEqual(entries[13]['downstream_cancelled'], [14])
        self.assertIn('--retry runs/c/p', entries[11]['resume_command']); self.assertIn('--resume c', entries[11]['resume_command'])
        self.assertIsNone(entries[11]['resumed_by'])
        self.assertEqual(rm.load(self.o)['attempts'][0]['status'], 'running')           # left alone
        self.assertIn('4 entries of the ledger not resumed yet', out)
        self.assertIn('4 attempt(s) changed', out)
        # one run directory as target, and a second call that changes nothing
        out = self.main('--reconcile', 'runs/c/p')
        self.assertIn('0 attempt(s) changed', out)

    def test_resume_parents_first_with_dependencies(self):
        submitted = []

        def fake_submit_run(rd, dependency=None, check=True, from_chunk=0):
            job = str(100 + len(submitted)); submitted.append((os.path.basename(rd), dependency, from_chunk, job))
            m = rm.load(rd); cs = m['chunks']
            for c in cs[from_chunk:]:
                m['attempts'].append(attempt(len(m['attempts']) + 1, int(job), c['id'], 'submitted', dependency))
            m['status'] = rm.run_status(m); rm.save(rd, m)
            return job
        with mock.patch.object(sr, 'submit_run', side_effect=fake_submit_run):
            out = self.main('--resume', 'c')
        self.assertEqual(submitted, [('p', None, 0, '100'), ('k', '100', 0, '101'), ('g', '101', 0, '102')])
        self.assertIn('resumed 3 run(s)', out)
        led = self.ledger()
        entries = {e['slurm_job_id']: e for e in led['entries']}
        self.assertEqual(entries[11]['resumed_by']['slurm_job_id'], 100)
        self.assertEqual(entries[13]['resumed_by']['dependency'], '100')
        self.assertEqual(entries[14]['resumed_by']['slurm_job_id'], 102)
        self.assertEqual(rm.load(self.p)['status'], 'submitted')
        # nothing is stranded any more
        with mock.patch.object(sr, 'submit_run', side_effect=fake_submit_run):
            self.main('--resume', 'c')
        self.assertEqual(len(submitted), 3)

    def test_child_of_a_running_parent_waits_for_its_job(self):
        """k's parent p is still running its last chunk (job 12 pending normally): k waits for job 12."""
        self.rows[11] = [row(11, 'RUNNING', end='Unknown')]; self.rows[12] = [row(12, 'PENDING', reason='Dependency', end='Unknown')]
        m = rm.load(self.k); m['attempts'][0]['status'] = 'failed'; m['status'] = 'failed'; rm.save(self.k, m)
        self.rows[13] = [row(13, 'FAILED', exit_code='1:0')]
        submitted = []
        with mock.patch.object(sr, 'submit_run', side_effect=lambda rd, dependency=None, check=True, from_chunk=0:
                               submitted.append((os.path.basename(rd), dependency)) or '200'):
            self.main('--resume', 'c')
        self.assertEqual(submitted[0], ('k', '12'))

    def test_retry_reconciles_first_and_takes_a_dependency(self):
        """--retry of a run whose attempt is 'running' but whose job timed out: reconciled, then resubmitted."""
        q = make_run(self.W, 'c', 'q', [attempt(1, 17, '2015-2015', 'running')], chunks=('2015-2015',))
        self.rows[17] = [row(17, 'TIMEOUT')]
        calls = []
        with mock.patch.object(sr, 'submit_run', side_effect=lambda rd, dependency=None, check=True, from_chunk=0:
                               calls.append((dependency, from_chunk)) or '300'), \
                mock.patch.object(sr.rr, 'git_state', return_value=('c' * 40, False)):
            self.main('--retry', 'runs/c/q', '--dependency', '99')
        self.assertEqual(calls, [('99', 0)])
        self.assertEqual(rm.load(q)['attempts'][0]['status'], 'timeout')
        self.assertEqual([e['slurm_job_id'] for e in self.ledger()['entries']], [17])


if __name__ == '__main__':
    unittest.main()
