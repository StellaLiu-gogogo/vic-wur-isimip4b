"""Unit tests for the open-decisions reminder of tests/check_layout.py (check_open_decisions): a decision counts as
open when its status starts with the word "open", also with a note ("open (provisional: ...)"); it is reported at
every stage with code at or after its due stage; decided rows, rows without a due stage, and stages with only a
README.md are not reported.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import check_layout

HEADER = ('| ID | Decision | Due stage | Trigger | Owner | Status |\n'
          '|----|----------|-----------|---------|-------|--------|\n')


class OpenDecisionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / 'docs' / 'decisions').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def warnings(self, rows, files):
        (self.repo / 'docs' / 'decisions' / 'open-decisions.md').write_text(HEADER + ''.join(
            f'| {i} | something | {stage} | | user | {status} |\n' for i, stage, status in rows))
        report = check_layout.Report()
        check_layout.check_open_decisions(self.repo, files, report)
        self.assertEqual(report.errors, [])
        return {w.split(':')[0].split()[1]: w.split('this stage: ')[1].split(';')[0] for w in report.warnings}

    def test_open_with_note_is_reported(self):
        rows = [('D01', '03_parameters', 'open (provisional: branch `b`, head `39e21ff5`)'),
                ('D02', '05_simulation', 'open')]
        files = ['workflow/03_parameters/bundle/a.py', 'workflow/04_forcing/b.py', 'workflow/05_simulation/c.py']
        self.assertEqual(self.warnings(rows, files), {'workflow/03_parameters': 'D01', 'workflow/04_forcing': 'D01',
                                                      'workflow/05_simulation': 'D01, D02'})

    def test_decided_and_no_due_stage_are_not_reported(self):
        rows = [('D04', '03_parameters', 'decided 2026-09-30 ([D04-x.md](D04-x.md))'),
                ('D13', '-', 'open'),
                ('D15', '-', 'decided ([D15-x.md](D15-x.md))')]
        self.assertEqual(self.warnings(rows, ['workflow/05_simulation/c.py']), {})

    def test_status_must_start_with_the_word_open(self):
        rows = [('D01', '03_parameters', 'opened elsewhere'),
                ('D02', '03_parameters', 'reopen later'),
                ('D03', '03_parameters', 'decided, was open (provisional)')]
        self.assertEqual(self.warnings(rows, ['workflow/03_parameters/a.py']), {})

    def test_stage_with_only_readme_is_not_reported(self):
        rows = [('D01', '01_acquisition', 'open')]
        files = ['workflow/02_preprocessing/README.md', 'workflow/03_parameters/a.py']
        self.assertEqual(self.warnings(rows, files), {'workflow/03_parameters': 'D01'})

    def test_later_stage_decision_not_reported_early(self):
        rows = [('D07', '06_postprocessing', 'open')]
        self.assertEqual(self.warnings(rows, ['workflow/05_simulation/c.py']), {})


if __name__ == '__main__':
    unittest.main()
