"""Unit tests for workflow/common/qc.py: combined status, exit status, summary writing, and the binding of
per-file reports to their data files and verifier version (code review of 2026-10-05, #3 and #8).

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import json, os, tempfile, unittest
from unittest import mock

from common import qc

CLEAN = {'verifier_commit': 'a' * 40, 'verifier_dirty': False, 'verifier_code_tree': {'workflow/x': 't1'}}


class StatusTest(unittest.TestCase):
    def test_combine(self):
        self.assertEqual(qc.combine([]), 'passed')
        self.assertEqual(qc.combine(['passed', 'passed']), 'passed')
        self.assertEqual(qc.combine(['passed', 'warning']), 'warning')
        self.assertEqual(qc.combine(['warning', 'not_checked']), 'not_checked')
        self.assertEqual(qc.combine(['passed', 'missing']), 'not_checked')
        self.assertEqual(qc.combine(['not_checked', 'failed', 'passed']), 'failed')
        self.assertEqual(qc.combine(iter(['passed'])), 'passed')
        with self.assertRaises(ValueError):
            qc.combine(['ok'])

    def test_exit_status(self):
        for status, code in (('passed', 0), ('failed', 1), ('warning', 3), ('not_checked', 4)):
            with self.assertRaises(SystemExit) as cm:
                qc.exit_with(status)
            self.assertEqual(cm.exception.code, code)
        self.assertEqual(set(qc.EXIT_CODES), set(qc.STATUSES))
        self.assertNotIn(2, qc.EXIT_CODES.values())         # 2 is Python's command-line error

    def test_summary(self):
        with tempfile.TemporaryDirectory() as d:
            qc.write_summary(d, {'object': 'forcing/x', 'status': 'passed'})
            self.assertEqual(os.listdir(d), ['summary.json'])
            self.assertEqual(open(f'{d}/summary.json').read(), json.dumps({'object': 'forcing/x', 'status': 'passed'},
                                                                         indent=1))


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.tmp.name
        self.files = [f'{d}/b_2015.nc', f'{d}/a_2015.nc']
        for p in self.files:
            open(p, 'w').write(p)
        self.report = f'{d}/verify_2015.json'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, status='passed', verifier=CLEAN, binding=True):
        rec = {'status': status}
        if binding:
            rec['binding'] = qc.binding(self.files, verifier)
        qc.write_json(self.report, rec)

    def test_binding_content(self):
        b = qc.binding(self.files, CLEAN)
        self.assertEqual(list(b['data_sha256']), ['a_2015.nc', 'b_2015.nc'])
        self.assertEqual(b['verifier_code_tree'], CLEAN['verifier_code_tree'])

    def test_current_report_counts(self):
        self.write('failed')
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN), 'failed')
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN, this_run=True), 'failed')

    def test_missing_or_unbound_report(self):
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN), 'not_checked')
        self.write(binding=False)
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN, this_run=True), 'not_checked')

    def test_changed_data_file(self):
        self.write()
        open(self.files[0], 'a').write('changed')
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN, this_run=True), 'not_checked')
        self.write()
        self.assertEqual(qc.report_status(self.report, self.files[:1], CLEAN), 'not_checked')   # file set differs

    def test_other_verifier_version(self):
        self.write()
        other = dict(CLEAN, verifier_code_tree={'workflow/x': 't2'})
        self.assertEqual(qc.report_status(self.report, self.files, other), 'not_checked')
        later_commit = dict(CLEAN, verifier_commit='b' * 40)     # unrelated commit, same verifier code
        self.assertEqual(qc.report_status(self.report, self.files, later_commit), 'passed')

    def test_repository_not_clean(self):
        dirty = dict(CLEAN, verifier_dirty=True)
        self.write(verifier=dirty)
        self.assertEqual(qc.report_status(self.report, self.files, CLEAN), 'not_checked')
        self.assertEqual(qc.report_status(self.report, self.files, dirty), 'not_checked')
        self.assertEqual(qc.report_status(self.report, self.files, dirty, this_run=True), 'passed')
        self.write()
        self.assertEqual(qc.report_status(self.report, self.files, dirty), 'not_checked')

    def test_verifier_state(self):
        with mock.patch.object(qc.gitstate, 'state', return_value=('c' * 40, False)), \
                mock.patch.object(qc.gitstate, 'tree_hashes', return_value={'workflow/x': 't', 'workflow/common': 'u'}) as th:
            v = qc.verifier_state('/repo', 'workflow/x')
        th.assert_called_once_with('/repo', ['workflow/x', 'workflow/common'])
        self.assertEqual(v, {'verifier_commit': 'c' * 40, 'verifier_dirty': False,
                             'verifier_code_tree': {'workflow/x': 't', 'workflow/common': 'u'}})


if __name__ == '__main__':
    unittest.main()
