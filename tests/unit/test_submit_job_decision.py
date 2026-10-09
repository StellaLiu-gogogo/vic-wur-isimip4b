"""Unit tests for the submit scripts of the producers (04_forcing climate, land use, water use; 03_parameters
vegetation, bundle): where the job writes is decided once, at submission, and passed to the producer; a producer
started for an accepted output stops when the repository is no longer the submitted one; every submit script can
submit a verification-only job (--verify-only). Jobs are rendered with --dry-run; Git and conda are mocked.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import contextlib, importlib, io, os, re, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, '..', '..', 'workflow')
os.environ.setdefault('ISIMIP4B_WORKDIR', tempfile.gettempdir())   # paths only; nothing is read or written
for d in ('04_forcing/climate', '04_forcing/landuse', '04_forcing/water_use', '03_parameters/vegetation',
          '03_parameters/bundle'):
    sys.path.insert(0, os.path.join(WF, d))

CLEAN, DIRTY = ('a' * 40, False), ('b' * 40, True)
# submit script, producer module, base arguments, line of the job that runs the producer
STAGES = {
    'climate': ('submit_climate_forcing', 'downscale_climate',
                ['--gcm', 'ec-earth3-esm-1-1', '--alias', 'esm-hist', '--years', '2015', '--variables', 'prec'],
                'downscale_climate.py'),
    'landuse': ('submit_landuse_forcing', 'isimip_landuse_to_vic_annual', ['--scenario', 'histsoc', '--years', '2015'],
                'isimip_landuse_to_vic_annual.py'),
    'water_use': ('submit_water_use_forcing', 'downscale_water_use', ['--scenario', 'histsoc', '--years', '2015'],
                  'downscale_water_use.py'),
    'vegetation': ('submit_vegetation_component', 'build_vegetation', [], 'build_vegetation.py'),
    'bundle': ('submit_bundle', 'assemble_bundle', [], 'assemble_bundle.py'),
}


def render(stage, git, extra=()):
    """Job text rendered by the stage's submit script with --dry-run and the given Git state."""
    sub, prod, args, _ = STAGES[stage]
    s = importlib.import_module(sub); p = importlib.import_module(prod)
    out = io.StringIO()
    patches = [mock.patch.object(p, 'git_state', return_value=git),
               mock.patch.object(sys, 'argv', [sub] + args + list(extra) + ['--dry-run'])]
    if hasattr(s, 'jobrecord'):
        patches.append(mock.patch.object(s.jobrecord, 'conda_base', return_value='/conda'))
    if stage == 'bundle':
        patches.append(mock.patch.object(s.subprocess, 'run',
                                         return_value=mock.Mock(stdout='/conda\n', returncode=0)))
    with contextlib.ExitStack() as st, contextlib.redirect_stdout(out):
        for x in patches:
            st.enter_context(x)
        s.main()
    return out.getvalue()


def producer_args(stage, text):
    """Arguments of the producer line in the job, or None when the job does not run the producer."""
    line = [l for l in text.splitlines() if STAGES[stage][3] in l and 'python3' in l]
    if not line:
        return None
    body = text.split(line[0])[0]
    if re.search(r'if \[ "no" = yes \]; then\s*$', body):        # producer switched off in the job
        return None
    return line[0].split(STAGES[stage][3], 1)[1].split()


class SubmissionDecisionTest(unittest.TestCase):
    """P2-3: the producer gets the decision of the submit script."""

    def test_dirty_at_submission_goes_to_scratch(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                args = producer_args(stage, render(stage, DIRTY))
                self.assertIn('--scratch', args)
                self.assertNotIn('--expect-commit', args)

    def test_clean_at_submission_expects_the_commit(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                args = producer_args(stage, render(stage, CLEAN))
                self.assertNotIn('--scratch', args)
                self.assertEqual(args[args.index('--expect-commit') + 1], CLEAN[0])


class ProducerStopsTest(unittest.TestCase):
    """P2-3: a producer started for an accepted output stops when the repository changed after submission."""

    def run_producer(self, stage, git):
        sub, prod, args, _ = STAGES[stage]
        p = importlib.import_module(prod)
        with mock.patch.object(p, 'git_state', return_value=git), \
                mock.patch.object(sys, 'argv', [prod] + args + ['--expect-commit', CLEAN[0]]):
            with self.assertRaises(SystemExit) as cm:
                p.main()
        return cm.exception.code

    def test_stops_when_not_clean_or_other_commit(self):
        for stage in STAGES:
            for git in (DIRTY, ('c' * 40, False)):
                with self.subTest(stage=stage, git=git):
                    code = self.run_producer(stage, git)
                    self.assertIsInstance(code, str)                       # our message, not an argument error
                    self.assertIn('submitted', code)


class VerifyOnlyTest(unittest.TestCase):
    """P2-2: every submit script can submit a job that runs only the verifier on the existing output."""

    def test_verify_only_job(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                text = render(stage, CLEAN, ['--verify-only'])
                self.assertIsNone(producer_args(stage, text))
                self.assertIn('-verify', re.search(r'--job-name=(\S+)', text).group(1))

    def test_verify_only_does_not_redirect_existing_output(self):
        """As for land use: a repository that is not clean redirects the producer, not existing files."""
        for stage in STAGES:
            with self.subTest(stage=stage):
                text = render(stage, DIRTY, ['--verify-only'])
                self.assertNotIn('-scratch', re.search(r'--job-name=(\S+)', text).group(1))


if __name__ == '__main__':
    unittest.main()
