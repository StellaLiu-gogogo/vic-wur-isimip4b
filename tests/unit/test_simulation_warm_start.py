"""Unit tests for warm starts from an earlier run (render_run.py, initialisation.state_of_run): VIC restores a state
by array position and checks only its dimensions, so the earlier run must have the same model executable and the
same parameter files; and, with NONRENEWABLE_WITHDRAWAL, the monthly output must contain OUT_NONREN_DEFICIT.
Uses the render harness of test_simulation_render.py (temporary workdir, build/parameter/forcing steps replaced).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, unittest

import test_simulation_render as tsr
from test_simulation_render import HIST, rr


class SameIdentityTest(tsr.StateOfRunTest):
    """P2-6: the earlier run of a warm start must have the same model and parameter files as the new run."""

    def earlier_with(self, change):
        path = self.earlier()
        with open(os.path.join(self.src, 'run_manifest.json')) as fh:
            m = json.load(fh)
        change(m)
        with open(os.path.join(self.src, 'run_manifest.json'), 'w') as fh:
            json.dump(m, fh)
        return path

    def assert_stops(self, change):
        self.earlier_with(change)
        with self.assertRaises(rr.RenderError):
            self.render(HIST)
        self.assertFalse(os.path.exists(os.path.join(self.W, 'runs', 'smoke', HIST)))

    def test_same_identity_renders(self):
        self.earlier_with(lambda m: None)
        self.render(HIST)

    def test_other_model_commit_stops(self):
        self.assert_stops(lambda m: m['model'].update(commit='0' * 40))

    def test_other_executable_stops(self):
        self.assert_stops(lambda m: m['model'].update(executable_sha256='0' * 64))

    def test_other_dam_file_stops(self):
        self.assert_stops(lambda m: m['inputs']['parameters']['dams'].update(md5='0' * 32))

    def test_earlier_run_without_record_stops(self):
        self.assert_stops(lambda m: m.pop('model'))


class NonrenewableDeficitOutputTest(tsr.RenderHarness):
    """P2-5: with NONRENEWABLE_WITHDRAWAL the deficit removed from the baseflow must be written (monthly)."""

    def test_missing_deficit_output_stops(self):
        self.campaign['plugins']['water_use']['nonrenewable_withdrawal'] = True
        with self.assertRaises(rr.RenderError):
            self.render(HIST)

    def test_deficit_in_monthly_diagnostics_renders(self):
        self.campaign['plugins']['water_use']['nonrenewable_withdrawal'] = True
        self.campaign['output']['diagnostics']['monthly'].append('OUT_NONREN_DEFICIT')
        self.render(HIST)
        with open(os.path.join(self.W, 'runs', 'smoke', HIST, 'config', 'vic_global.txt')) as fh:
            monthly = fh.read().split('OUTFILE                 monthly')[1]
        self.assertIn('OUTVAR                  OUT_NONREN_DEFICIT', monthly)

    def test_without_nonrenewable_nothing_required(self):
        self.render(HIST)


if __name__ == '__main__':
    unittest.main()
