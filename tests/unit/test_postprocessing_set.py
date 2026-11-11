"""Unit tests for the product set of stage 06_postprocessing (workflow/06_postprocessing/product_set.py, collect_set.py,
check_set.py, submit.py; D11):

- the expected product units of every campaign file equal the runs and chunks of stage 05 (resolve_campaign.py and
  render_run.chunk_plan), when the protocol snapshots of the workdir are available;
- the segment rules on a tiny protocol: explicit, identical and not-simulated period entries, exclusions,
  sensitivity equivalence, restriction labels, chunks;
- on the synthetic one-year run of test_postprocessing_unit.py: the unit submission selects the ready unit, the
  collecting step records it as present (a scratch source) or accepted (production source with a passed bound check)
  and the segment as accepted; the set check passes, finds an unlisted product file, and warns about a unit whose
  source chunk has a newer attempt; a run manifest that differs from the derivation stops the collecting step.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import argparse, glob, json, os, re, sys, unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'workflow', '06_postprocessing'))
import test_postprocessing_unit as synthetic   # noqa: E402
from test_postprocessing_unit import RUN, YEAR   # noqa: E402
import check_set      # noqa: E402
import collect_set    # noqa: E402
import product_set    # noqa: E402
import submit         # noqa: E402
import support        # noqa: E402

JOB_NAME = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')            # tests/check_layout.py, JOB_RECORD without the ID
NOT_SIMULATED = 'Does not have to be simulated, spin-up should be based on the 2021 DHF.'


def write_protocol(W, experiments, commit='b' * 40):
    d = f'{W}/protocol/definitions'
    os.makedirs(f'{d}/experiments', exist_ok=True)
    with open(f'{W}/protocol/COMMIT', 'w') as fh:
        fh.write(commit + '\n')
    with open(f'{d}/experiments/ISIMIP4b.yaml', 'w') as fh:
        yaml.safe_dump(experiments, fh)
    with open(f'{d}/period.yaml', 'w') as fh:
        yaml.safe_dump([{'specifier': 'pre-industrial', 'start_year': 1601, 'end_year': 1849},
                        {'specifier': 'historical', 'start_year': 1850, 'end_year': 2021},
                        {'specifier': 'future', 'start_year': {'ISIMIP4b': 2022, 'ISIMIP4a': 2030},
                         'end_year': 2100}], fh)


def experiment(spec, pre, hist, fut):
    return {'specifier': spec, 'sectors': ['water_global'], 'simulation_rounds': ['ISIMIP4b'],
            'pre-industrial': pre, 'historical': hist, 'future': fut}


@unittest.skipUnless(os.environ.get('ISIMIP4B_WORKDIR'), 'needs ISIMIP4B_WORKDIR with the protocol snapshots')
class SameAsStage05Test(unittest.TestCase):
    def test_every_campaign(self):
        sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'render'))
        import render_run as rr
        import resolve_campaign as rc
        W = os.environ['ISIMIP4B_WORKDIR']
        compared = 0
        for f in sorted(glob.glob(f'{REPO}/configs/campaigns/*.yaml')):
            camp = support.load_yaml(f)
            if not os.path.isdir(os.path.join(W, camp['protocol']['path'])):
                continue
            segs, _ = rc.resolve(camp, os.path.join(W, camp['protocol']['path']))
            res = support.load_yaml(os.path.join(REPO, camp['resources']))
            ref = sorted((r['run_id'], tuple(rr.chunk_plan(r['start_year'], r['end_year'], rr.run_chunk_years(r, res))))
                         for lab in (sorted((camp.get('restriction') or {}).get('runs', {})) or [None])
                         for r in rc.runs(camp, segs, lab) if r['segment']['period'] != 'spinup')
            got = sorted((r['run_id'], tuple(tuple(u['years']) for u in r['units']))
                         for r in product_set.expected_runs(camp, W))
            self.assertEqual(got, ref, f)
            compared += 1
        if not compared:
            self.skipTest('no protocol snapshot in the workdir')


class SegmentRulesTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.W = self.tmp.name
        write_protocol(self.W, [
            experiment('a', {'climate': 'picontrol', 'soc': '1850soc'}, {'climate': 'historical', 'soc': 'histsoc'},
                       {'climate': 'h', 'soc': 'h-soc', 'soc_sens': '2021co2'}),
            experiment('b', NOT_SIMULATED, {'climate': 'historical', 'soc': '2021soc'},
                       'Identical to the similar **h/h-soc** run above.'),
            experiment('c', {'climate': 'picontrol', 'soc': '1850soc'}, {'climate': 'picontrol', 'soc': '1850soc'},
                       {'climate': 'vl', 'soc': 'vl-soc'}),
            {**experiment('d', NOT_SIMULATED, {'climate': 'historical', 'soc': 'x'}, {'climate': 'h', 'soc': 'x'}),
             'sectors': ['agriculture']}])
        self.res = f'{self.W}/resources.yaml'
        with open(self.res, 'w') as fh:
            yaml.safe_dump({'chunk_years': 100}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def campaign(self, **extra):
        return {'campaign_id': 't', 'gcms': {'g': {}}, 'experiments': {'all': True}, 'resources': self.res,
                'protocol': {'path': 'protocol', 'commit': 'b' * 40, 'simulation_round': 'ISIMIP4b',
                             'sector': 'water_global'},
                'sensitivity_equivalence': {'2021co2': {'same_as': 'default'}}, **extra}

    def test_segments_and_chunks(self):
        runs = {r['run_id']: r for r in product_set.expected_runs(self.campaign(), self.W)}
        self.assertEqual(sorted(runs), sorted([
            'g_picontrol_1850soc_default_pre-industrial', 'g_historical_histsoc_default_historical',
            'g_h_h-soc_default_future', 'g_historical_2021soc_default_historical',
            'g_picontrol_1850soc_default_historical', 'g_vl_vl-soc_default_future']))
        pre = runs['g_picontrol_1850soc_default_pre-industrial']
        self.assertEqual([u['years'] for u in pre['units']], [[1601, 1700], [1701, 1800], [1801, 1849]])
        self.assertEqual(pre['units'][2]['chunk'], '1801-1849')
        fut = runs['g_h_h-soc_default_future']
        self.assertFalse(fut['chunked'])
        self.assertEqual(fut['units'], [{'chunk': None, 'years': [2022, 2100]}])

    def test_exclusion_restriction_and_errors(self):
        camp = self.campaign(exclusions=[{'experiment': 'c', 'reason': 'test'}],
                             restriction={'periods': ['future'], 'runs': {'y10': {'years': [2031, 2040]},
                                                                           'y2': {'years': [2022, 2023],
                                                                                  'chunk_years': 1}}})
        runs = {r['run_id']: r for r in product_set.expected_runs(camp, self.W)}
        self.assertEqual(sorted(runs), ['g_h_h-soc_default_future__y10', 'g_h_h-soc_default_future__y2'])
        self.assertEqual([u['chunk'] for u in runs['g_h_h-soc_default_future__y2']['units']], ['2022-2022', '2023-2023'])
        with self.assertRaises(SystemExit):
            product_set.expected_runs(self.campaign(exclusions=[{'experiment': 'zz', 'reason': 'x'}]), self.W)
        write_protocol(self.W, [], commit='e' * 40)
        with self.assertRaisesRegex(SystemExit, 'the campaign pins'):
            product_set.expected_runs(self.campaign(), self.W)

    def test_reference_must_be_defined(self):
        write_protocol(self.W, [experiment('b', NOT_SIMULATED, {'climate': 'historical', 'soc': '2021soc'},
                                           'Identical to the similar **h/h-soc** run above.')])
        with self.assertRaisesRegex(SystemExit, 'is not defined'):
            product_set.expected_runs(self.campaign(), self.W)


class ProductSetTest(synthetic.SyntheticRun):
    """The synthetic run of test_postprocessing_unit.py as the one reported run of a restricted campaign."""

    def setUp(self):
        super().setUp()
        W = self.W
        write_protocol(W, [experiment('h_x', NOT_SIMULATED, {'climate': 'historical', 'soc': 'histsoc'},
                                      {'climate': 'h', 'soc': '2021soc'})])
        with open(f'{W}/resources.yaml', 'w') as fh:
            yaml.safe_dump({'chunk_years': 25}, fh)
        camp = support.load_yaml(self.campaign)
        camp.update({'experiments': {'all': True}, 'resources': f'{W}/resources.yaml',
                     'restriction': {'periods': ['historical'], 'runs': {'t': {'years': [YEAR, YEAR]}}}})
        camp['protocol'].update({'simulation_round': 'ISIMIP4b', 'sector': 'water_global'})
        with open(self.campaign, 'w') as fh:
            yaml.safe_dump(camp, fh)
        self.man_path = f'{W}/runs/test-campaign/{RUN}/run_manifest.json'
        self.set_dir = f'{W}/scratch/test-task/postprocessed/test-campaign'
        self.set_qc = f'{W}/scratch/test-task/qc/postprocessed/test-campaign'

    def manifest(self, **changes):
        with open(self.man_path) as fh:
            man = json.load(fh)
        man.update(changes)
        with open(self.man_path, 'w') as fh:
            json.dump(man, fh)
        return man

    def accept_source(self):
        """Production run with a passed run check bound to its attempt (an unchunked run: the run check is the
        chunk check and the whole-run check)."""
        man = self.manifest(production=True)
        qc = f'{self.W}/qc/{man["run_dir"]}'
        os.makedirs(qc, exist_ok=True)
        with open(f'{qc}/summary.json', 'w') as fh:
            json.dump({'status': 'passed', 'code_dirty': False, 'binding': {'attempt': 1, 'slurm_job_id': 1}}, fh)

    def collect(self):
        return self.run_main(collect_set), self.run_main(check_set)

    def record(self):
        return support.load_yaml(f'{self.set_dir}/product-set.yaml')

    def test_submission_selects_the_ready_unit(self):
        a = argparse.Namespace(run=None, chunk=None, scratch='test-task')
        camp = support.load_yaml(self.campaign)
        [(run, unit, why)] = submit.ready_units(self.W, camp, a, set())
        self.assertIsNone(why)
        self.assertTrue(JOB_NAME.match(submit.unit_job_name(run, unit, 'test-task')))
        rel = os.path.relpath(f'{self.set_dir}/{product_set.unit_rel(run, unit)}', self.W)
        self.assertEqual(submit.ready_units(self.W, camp, a, {rel})[0][2], 'job active')
        a.scratch = None                                          # outside scratch the source must be accepted
        self.assertIn('not a production run', submit.ready_units(self.W, camp, a, set())[0][2])
        a.scratch = 'test-task'
        self.assertEqual(self.produce(), 0)
        self.assertEqual(submit.ready_units(self.W, camp, a, set())[0][2], 'made')

    def test_scratch_unit_is_present(self):
        self.assertEqual(self.produce(), 0)
        self.assertEqual(self.check(), 0)
        self.assertEqual(self.collect(), (0, 0))
        rec = self.record()
        self.assertEqual(rec['counts']['units_expected'], 1)
        self.assertEqual(rec['counts']['present'], 1)
        self.assertEqual(rec['counts']['segments_accepted'], 0)
        unit = rec['segments'][0]['units'][0]
        self.assertIn('made from a source that was not accepted', unit['reasons'])
        self.assertEqual(rec['decisions']['D09'], 'open')
        with open(f'{self.set_dir}/checksums.sha256') as fh:
            names = [line.split('  ')[1].strip() for line in fh]
        self.assertIn('static/dis-outlets.nc', names)
        self.assertIn(f'ec-earth3-esm-1-1/historical_histsoc_default_historical/{YEAR}-{YEAR}/'
                      f'qtot_daily_{YEAR}_{YEAR}.nc', names)
        self.assertEqual(support.load_yaml(f'{self.set_qc}/summary.json')['status'], 'passed')

    def test_accepted_unit_and_segment(self):
        self.accept_source()
        self.assertEqual(self.produce(), 0)
        self.assertEqual(self.check(), 0)
        self.assertEqual(self.collect(), (0, 0))
        rec = self.record()
        self.assertEqual(rec['segments'][0]['units'][0]['status'], 'accepted', rec['segments'][0]['units'][0])
        self.assertTrue(rec['segments'][0]['accepted'])
        self.assertEqual(rec['counts']['segments_accepted'], 1)
        # a newer attempt of the source: the unit fails, the set check warns
        man = self.manifest()
        man['attempts'].append({'attempt': 2, 'slurm_job_id': 2, 'status': 'completed'})
        self.manifest(attempts=man['attempts'])
        self.assertEqual(self.collect(), (0, 3))
        self.assertEqual(self.record()['segments'][0]['units'][0]['status'], 'failed')

    def test_set_check_finds_an_unlisted_file(self):
        self.assertEqual(self.produce(), 0)
        self.assertEqual(self.run_main(collect_set), 0)
        unit = f'{self.set_dir}/ec-earth3-esm-1-1/historical_histsoc_default_historical/{YEAR}-{YEAR}'
        with open(f'{unit}/extra_monthly_{YEAR}_{YEAR}.nc', 'w') as fh:
            fh.write('x')
        self.assertEqual(self.run_main(check_set), 1)
        self.assertEqual(support.load_yaml(f'{self.set_qc}/summary.json')['checks']['inventory'], 'failed')

    def test_manifest_that_differs_stops(self):
        self.manifest(period={'start': f'{YEAR}-01-01', 'end': f'{YEAR + 1}-12-31'})
        self.assertIn('differs from the units derived', str(self.run_main(collect_set)))


if __name__ == '__main__':
    unittest.main()
