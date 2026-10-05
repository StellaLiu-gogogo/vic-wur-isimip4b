"""Unit tests for workflow/05_simulation/render/render_run.py and submit/run_manifest.py (templates, output
streams, start-year rule, task check, forcing view on a small synthetic workdir, timing-table parsing).

The protocol-coverage test reads the pinned protocol from $ISIMIP4B_WORKDIR and is skipped without it.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import os, sys, tempfile, unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'render'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'submit'))
import render_run as rr      # noqa: E402
import run_manifest as rm    # noqa: E402

SMOKE = os.path.join(REPO, 'configs', 'campaigns', 'smoke.yaml')
G = 'ec-earth3-esm-1-1'


def smoke():
    with open(SMOKE) as fh:
        return yaml.safe_load(fh)


class TemplateTest(unittest.TestCase):
    def test_fill_requires_exact_placeholders(self):
        self.assertEqual(rr.fill('a {{X}} b', {'X': 1}), 'a 1 b')
        with self.assertRaises(rr.RenderError):
            rr.fill('a {{X}} {{Y}}', {'X': 1})
        with self.assertRaises(rr.RenderError):
            rr.fill('a {{X}}', {'X': 1, 'Z': 2})

    def test_vic_template_placeholders(self):
        with open(os.path.join(REPO, rr.VIC_TEMPLATE)) as fh:
            text = fh.read()
        names = set(rr.PLACEHOLDER.findall(text))
        self.assertIn('FORCE_TYPES', names)
        self.assertNotIn('LAI_SRC', names)
        for opt in ('LAI_SRC                 FROM_VEGPARAM', 'FCAN_SRC                FROM_VEGPARAM',
                    'ALB_SRC                 FROM_VEGPARAM', 'CALENDAR                PROLEPTIC_GREGORIAN',
                    'GWM                     FALSE'):
            self.assertIn(opt, text)
        self.assertNotIn('DAM_ALPHA', text)                                # only read from a constants file
        self.assertFalse(any(l.startswith(('OUT_FORMAT', 'COMPRESS')) for l in text.splitlines()))   # per OUTFILE


class OutputTest(unittest.TestCase):
    def test_streams(self):
        text, streams = rr.output_streams(smoke(), '/x')
        self.assertEqual(list(streams), ['daily', 'monthly'])
        daily = text.split('OUTFILE                 monthly')[0]
        self.assertIn('OUTVAR                  OUT_RUNOFF', daily)
        self.assertIn('OUTVAR                  OUT_BASEFLOW', daily)
        self.assertIn('OUTVAR                  OUT_DISCHARGE', daily)
        self.assertEqual(daily.count('OUTVAR'), 3)                          # qtot and dis only
        for block in text.split('OUTFILE')[1:]:                             # format and compression per stream
            self.assertIn('OUT_FORMAT              NETCDF4', block)
            self.assertIn('COMPRESS                2', block)
            self.assertIn('HISTFREQ                NYEARS 1', block)
        self.assertIn('OUTVAR                  OUT_SOIL_MOIST  * * * AGG_TYPE_AVG', text)
        monthly = text.split('OUTFILE                 monthly')[1]
        self.assertEqual(monthly.count('OUTVAR                  OUT_BASEFLOW\n'), 1)   # no duplicates
        self.assertNotIn('OUT_GWRECHARGE', text)

    def test_baseflow_mapping(self):
        iso = smoke()['output']['isimip']
        for v in ('qr', 'qg', 'qsb'):
            self.assertEqual(iso[v]['vic'], ['OUT_BASEFLOW'])
        self.assertTrue(all('OUT_RECHARGE' not in x['vic'] for x in iso.values()))
        self.assertEqual(iso['qtot']['vic'], ['OUT_RUNOFF', 'OUT_BASEFLOW'])
        self.assertEqual(iso['qtot']['streams'], ['daily', 'monthly'])

    @unittest.skipUnless(os.path.isdir(os.path.join(os.environ.get('ISIMIP4B_WORKDIR', '/nonexistent'), 'raw')),
                         'workdir not available')
    def test_protocol_coverage(self):
        c = smoke()
        n = rr.check_outputs_cover_protocol(c, os.path.join(os.environ['ISIMIP4B_WORKDIR'], c['protocol']['path']))
        self.assertEqual(n, 105)
        c['output']['not_provided'].pop('qrf')
        with self.assertRaises(rr.RenderError):
            rr.check_outputs_cover_protocol(c, os.path.join(os.environ['ISIMIP4B_WORKDIR'], c['protocol']['path']))


class RulesTest(unittest.TestCase):
    def test_start_year_must_be_identity(self):
        run = {'run_id': 'r', 'start_year': 1601}
        ok = {'climate/tair': {1601: {'rule': 'identity'}}, 'landuse': {1601: {'rule': 'identity'}}}
        rr.check_start_year(run, ok)
        bad = {'climate/tair': {1601: {'rule': 'identity'}}, 'landuse': {1601: {'rule': 'constant'}}}
        with self.assertRaises(rr.RenderError):
            rr.check_start_year(run, bad)

    def test_tasks(self):
        dec = {'groups': 128, 'largest_group_cells': 372255, 'smallest_group_cells': 2525, 'active_cells': 2188551}
        self.assertEqual(rr.check_tasks(8, dict(dec))['largest_rank_cells_lower_bound'], 372255)
        self.assertEqual(rr.check_tasks(2, dict(dec))['largest_rank_cells_lower_bound'], 1094276)
        with self.assertRaises(rr.RenderError):
            rr.check_tasks(129, dict(dec))


def fake_unit(W, rel, names, status='passed', dirty=False):
    d = os.path.join(W, 'forcing', rel); os.makedirs(d)
    files = []
    for n in names:
        open(os.path.join(d, n), 'w').close()
        files.append({'path': n, 'sha256': 'x' * 64})
    with open(os.path.join(d, 'provenance.yaml'), 'w') as fh:
        yaml.safe_dump({'forcing_unit': rel, 'code_commit': 'c' * 40, 'code_dirty': dirty, 'created_at': 't',
                        'qc': {'status': status}, 'files': files}, fh)


class ForcingPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        for var in rr.CLIMATE_VARIABLES:
            fake_unit(self.W, f'climate/{G}/esm-hist/{var}', [f'{var}_{G}_esm-hist_{y}.nc' for y in (2015, 2016)])
        fake_unit(self.W, 'landuse/histsoc', [f'coverage_histsoc_{y}.nc' for y in (2015, 2016)])
        fake_unit(self.W, 'water_use/histsoc', [f'{s}_{v}_histsoc_{y}.nc' for s in ('municipal', 'manufacturing')
                                                for v in ('demand', 'groundwater_fraction', 'consumption_fraction')
                                                for y in (2015, 2016)])
        self.run = {'run_id': 'r', 'start_year': 2015, 'end_year': 2016,
                    'segment': {'gcm': G, 'soc': 'histsoc', 'period': 'historical'}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan(self):
        links, units, mapping = rr.forcing_plan(self.W, smoke(), self.run, 'esm-hist')
        self.assertEqual(len(links), 2 * (7 + 1 + 6))
        self.assertEqual(len(units), 9)                                     # 7 climate + land use + water use
        self.assertEqual(len(units['water_use/histsoc']['files']), 12)
        self.assertEqual(mapping['landuse'][2016], {'source': 'forcing/landuse/histsoc/coverage_histsoc_2016.nc',
                                                    'rule': 'identity'})
        self.assertIn(('water_use/municipal_demand_histsoc_2015.nc',
                       os.path.join(self.W, 'forcing/water_use/histsoc/municipal_demand_histsoc_2015.nc')), links)

    def test_unaccepted_unit_fails(self):
        p = os.path.join(self.W, 'forcing/landuse/histsoc/provenance.yaml')
        with open(p) as fh:
            d = yaml.safe_load(fh)
        d['qc']['status'] = 'not_checked'
        with open(p, 'w') as fh:
            yaml.safe_dump(d, fh)
        with self.assertRaises(rr.RenderError):
            rr.forcing_plan(self.W, smoke(), self.run, 'esm-hist')

    def test_missing_year_fails(self):
        run = dict(self.run, end_year=2017)
        with self.assertRaises(ValueError):
            rr.forcing_plan(self.W, smoke(), run, 'esm-hist')


class ManifestTest(unittest.TestCase):
    TABLE = """
    Model Cost       : 312.5 pe-hrs/simulated_year
    Model Throughput : 11.2 simulated_years/day
  MPI Processes             : 8
  OPENMP Threads            : 16
| Init Time  |                  600 |                 5000 |                 1.64 |                13.7 |
| Run Time   |                 7000 |               800000 |                 19.2 |                2190 |
| Final Time |                   10 |                   20 |                    0 |                   0 |
| Total Time |                 7610 |               805020 |                 20.8 |                2200 |
| Force Time |                 5500 |                 6000 |                 15.1 |                16.4 |
| Write Time |                  400 |                  500 |                  1.1 |                 1.4 |
"""

    def test_timing(self):
        t = rm.timing_table(self.TABLE)
        self.assertEqual(t['Run Time']['wall_s'], 7000.0)
        self.assertEqual(t['Force Time']['cpu_s'], 6000.0)
        self.assertEqual(t['mpi_processes'], 8.0)
        self.assertAlmostEqual(t['model_cost_pe_hours_per_year'], 312.5)

    def test_fingerprint_ignores_job_file(self):
        m = {'model': {'executable_sha256': 'a'}, 'inputs': {}, 'forcing_view': {},
             'rendered_files': {'config/vic_global.txt': 'v', rm.JOB_FILE: 'j1'}}
        f1 = rm.inputs_fingerprint(m); m['rendered_files'][rm.JOB_FILE] = 'j2'
        self.assertEqual(f1, rm.inputs_fingerprint(m))                     # how the run is executed
        m['rendered_files']['config/vic_global.txt'] = 'w'
        self.assertNotEqual(f1, rm.inputs_fingerprint(m))                  # what is simulated

    def test_job_has_no_openmp_binding(self):
        with open(os.path.join(REPO, rr.SLURM_TEMPLATE)) as fh:
            text = fh.read()
        self.assertNotIn('export OMP_PLACES', text)
        self.assertNotIn('export OMP_PROC_BIND', text)
        with open(os.path.join(REPO, 'configs', 'resources', 'vic-global-5arcmin.yaml')) as fh:
            self.assertNotIn('--cpu-bind', yaml.safe_load(fh)['launcher'])

    def test_fingerprint_changes_with_inputs(self):
        m = {'model': {'executable_sha256': 'a'}, 'inputs': {'x': 1}, 'forcing_view': {}, 'rendered_files': {}}
        f1 = rm.inputs_fingerprint(m); m['inputs']['x'] = 2
        self.assertNotEqual(f1, rm.inputs_fingerprint(m))


if __name__ == '__main__':
    unittest.main()
