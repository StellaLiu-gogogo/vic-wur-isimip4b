"""Unit tests for warm starts from an earlier run (render_run.py, initialisation.state_of_run): VIC restores a state
by array position and checks only its dimensions, so the earlier run must have the same model executable and the
same parameter files; and, with NONRENEWABLE_WITHDRAWAL, the monthly output must contain OUT_NONREN_DEFICIT.
Uses the render harness of test_simulation_render.py (temporary workdir, build/parameter/forcing steps replaced).

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, unittest

import yaml

import test_simulation_render as tsr
from test_simulation_render import FUT, HIST, rr


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

    def test_other_dam_file_with_same_list_renders(self):
        """D19: the dam file may differ (another DHF scenario) when the dam list is the same."""
        self.earlier_with(lambda m: m['inputs']['parameters']['dams'].update(md5='0' * 32))
        self.render(HIST)

    def test_other_dam_list_stops(self):
        tsr.write_dam_file(os.path.join(self.W, 'parameters', 'other_dams.nc'), ids=[1, 2, 4, 3])
        self.earlier_with(lambda m: m['inputs']['parameters']['dams'].update(path='parameters/other_dams.nc'))
        with self.assertRaisesRegex(rr.RenderError, 'id differs for 2 dams'):
            self.render(HIST)

    def test_other_parameter_file_stops(self):
        self.assert_stops(lambda m: m['inputs']['parameters']['irrigation'].update(md5='0' * 32))

    def test_earlier_run_without_record_stops(self):
        self.assert_stops(lambda m: m.pop('model'))

    def test_parent_record_names_the_earlier_run(self):
        """Review P3 D4: a warm start records the earlier run, not the protocol parent, as where the state comes from."""
        self.earlier_with(lambda m: None)
        self.render(HIST)
        p = self.manifest(HIST)['parent']
        self.assertIsNone(p['segment_id'])
        self.assertEqual(p['protocol_parent_segment'], tsr.PRE)
        self.assertEqual((p['run_id'], p['run_dir']), ('earlier__smoke2011-2020', 'runs/smoke/earlier__smoke2011-2020'))


class WarmStartRuleTest(tsr.StateOfRunTest):
    """D19 warm-start rule (a)-(d), checked before a run is rendered from another run's end state."""

    def assert_stops(self, reason):
        with self.assertRaisesRegex(rr.RenderError, reason):
            self.render(HIST)
        self.assertFalse(os.path.exists(os.path.join(self.W, 'runs', 'smoke', HIST)))

    def test_other_plugins_stop(self):
        plugins = {**self.campaign['plugins'], 'irrigation': {**self.campaign['plugins']['irrigation'], 'enabled': False}}
        self.earlier(plugins=plugins)
        self.assert_stops('same plugins')

    def test_active_dam_that_does_not_operate_stops(self):
        """The state has dam 2030 active (written after 2030), the run starts 1850 where it does not operate."""
        self.earlier(active=(1, 1, 1, 0))
        self.assert_stops('dam_class \\[2\\]')

    def test_dam_able_to_operate_in_earlier_run_stops(self):
        """The earlier run's dam 1 (1800) operates by its end in 2020; in this run's dam file it is built in 1900, after
        the start in 1850. The renderer stops even when the state does not mark it active."""
        tsr.write_dam_file(os.path.join(self.W, 'parameters', 'dams_child.nc'), years=(0, 1900, 2030, 9999))
        self.params['dams']['histsoc'] = {'path': 'parameters/dams_child.nc', 'md5': 'f' * 32}
        self.earlier(active=(1, 0, 0, 0))
        self.src_dams('parameters/dams.nc')
        self.assert_stops('dam_class \\[1\\]')

    def src_dams(self, rel):
        """The earlier run's dam file."""
        with open(os.path.join(self.src, 'run_manifest.json')) as fh:
            m = json.load(fh)
        m['inputs']['parameters']['dams'] = {'path': rel, 'md5': 'd' * 32}
        with open(os.path.join(self.src, 'run_manifest.json'), 'w') as fh:
            json.dump(m, fh)

    def test_start_not_on_1_january_stops(self):
        self.earlier()
        with self.assertRaises(rr.RenderError):
            rr.check_start_january('STARTYEAR 1850\nSTARTMONTH              7\nSTARTDAY                1\n', HIST)
        rr.check_start_january('STARTMONTH              1\nSTARTDAY                1\n', HIST)

    def test_state_with_other_number_of_dams_stops(self):
        self.earlier(active=(1, 0, 0))
        self.assert_stops('has 3 dams')


class DamListTest(unittest.TestCase):
    """D19 (amended 2026-10-16): id, type and order of every dam; capacity of the dams that can operate in the parent."""

    def lists(self, **child):
        import numpy as np
        p = {'id': np.array([1, 2, 3]), 'type': np.array([1, 0, 1]), 'capacity': np.array([5., 6., 7.]),
             'year': np.array([0, 1900, 9999])}
        c = {k: np.array(child.get(k, v)) for k, v in p.items()}
        return p, c

    def test_same_list(self):
        self.assertEqual(rr.dam_list_problems(*self.lists(), 2021), [])

    def test_order_and_type(self):
        self.assertTrue(rr.dam_list_problems(*self.lists(id=[2, 1, 3]), 2021))
        self.assertTrue(rr.dam_list_problems(*self.lists(type=[1, 1, 1]), 2021))
        self.assertTrue(rr.dam_list_problems(*self.lists(id=[1, 2]), 2021))

    def test_capacity_only_of_dams_that_can_operate(self):
        self.assertEqual(rr.dam_list_problems(*self.lists(capacity=[5., 6., 70.]), 2021), [])     # 9999: never
        self.assertTrue(rr.dam_list_problems(*self.lists(capacity=[5., 60., 7.]), 2021))
        self.assertEqual(rr.dam_list_problems(*self.lists(capacity=[5., 60., 7.]), 1899), [])     # not yet built

    def test_switched_off(self):
        p, c = self.lists(year=[0, 2000, 9999])
        self.assertEqual(rr.dams_switched_off(p['year'] <= 1950, c, 1950).tolist(), [1])
        self.assertEqual(rr.dams_switched_off(p['year'] <= 1950, c, 2000).tolist(), [])


class ParentDamTest(tsr.RenderHarness):
    """Parent and child of the campaign may use other dam files (other DHF scenarios) with the same dam list."""

    def test_child_with_other_dam_file_and_same_list(self):
        tsr.write_dam_file(os.path.join(self.W, 'parameters', 'dams_2021soc.nc'), years=(0, 0, 0, 9999))
        self.params['dams']['ssp3hsoc-noadapt'] = {'path': 'parameters/dams_2021soc.nc', 'md5': 'f' * 32}
        self.render()
        self.assertEqual(self.manifest(FUT)['inputs']['parameters']['dams']['path'], 'parameters/dams_2021soc.nc')
        self.assertEqual(self.manifest(HIST)['inputs']['parameters']['dams']['path'], 'parameters/dams.nc')

    def test_child_where_a_parent_dam_stops_operating(self):
        tsr.write_dam_file(os.path.join(self.W, 'parameters', 'dams_late.nc'), years=(0, 2050, 2030, 9999))
        self.params['dams']['ssp3hsoc-noadapt'] = {'path': 'parameters/dams_late.nc', 'md5': 'f' * 32}
        with self.assertRaisesRegex(rr.RenderError, r'dam_class \[1\]'):
            self.render()

    def test_missing_scenario_stops(self):
        del self.params['dams']['ssp3hsoc-noadapt']
        with self.assertRaisesRegex(rr.RenderError, 'no dam file for soc scenario ssp3hsoc-noadapt'):
            self.render()


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
