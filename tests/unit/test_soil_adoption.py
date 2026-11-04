"""Unit tests for workflow/03_parameters/soil/adopt_soil_fields.py and verify_adopted_soil.py on a small synthetic
base set and external soil file (the producer and the verifier run end to end in a temporary workdir with --scratch
and --component-dir), and for the soil-file binding of vegetation/recompute_roots.py.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import workflow_paths  # noqa: F401,E402  (repo/workflow on sys.path, tests/unit/workflow_paths.py)
import importlib.util, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

import numpy as np
import netCDF4 as nc

from common import hashing, provenance

HERE = os.path.dirname(os.path.abspath(__file__))
SOIL_DIR = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'soil')


def load(name, path):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


ad = load('adopt_soil_fields', os.path.join(SOIL_DIR, 'adopt_soil_fields.py'))
va = load('verify_adopted_soil', os.path.join(SOIL_DIR, 'verify_adopted_soil.py'))
rr = load('recompute_roots', os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'vegetation', 'recompute_roots.py'))

NY, NX = 3, 4
LAT = -56 + 1 / 24 + np.arange(NY) / 12; LON = -180 + 1 / 24 + np.arange(NX) / 12
MASK = np.array([[1, 1, 0, 1], [1, 0, 1, 1], [0, 1, 1, 1]], 'i4')
FILL = -9999.0
L3 = {'depth': (0.3, 1.0, 0.5), 'bulk_density': (1300.0, 1350.0, 1400.0), 'soil_density': (2650.0, 2650.0, 2650.0),
      'expt': (10.0, 11.0, 12.0), 'Ksat': (100.0, 80.0, 60.0), 'bubble': (20.0, 22.0, 24.0), 'quartz': (0.4, 0.4, 0.3),
      'Wcr_FRACT': (0.3, 0.3, 0.3), 'Wpwp_FRACT': (0.2, 0.2, 0.2), 'Wfc_FRACT': (0.4, 0.4, 0.4), 'resid_moist': (0.03, 0.03, 0.03)}
L2 = {'Ds': 0.1, 'Dsmax': 0.1, 'Ws': 20.0, 'c': 2.0, 'infilt': 0.2, 'elev': 500.0, 'avg_T': 8.0}
NATURAL = ['run_cell', 'elev', 'phi_s', 'avg_T', 'depth', 'bulk_density', 'soil_density', 'max_moist', 'init_moist',
           'expt', 'Ksat', 'bubble', 'quartz', 'Wcr_FRACT', 'Wpwp_FRACT', 'Wfc_FRACT', 'resid_moist',
           'Ds', 'Dsmax', 'Ws', 'c', 'infilt']


def soil_values(scale):
    """Closed soil values (3-layer and 2-d), scaled to make two different but valid soils."""
    v = {k: np.array(x)[:, None, None] * np.ones((3, NY, NX)) * scale for k, x in L3.items()}
    v['soil_density'] = np.array(L3['soil_density'])[:, None, None] * np.ones((3, NY, NX))   # porosity stays in (0, 1)
    v['quartz'] = np.minimum(v['quartz'], 1.0); v['Wfc_FRACT'] = np.minimum(v['Wfc_FRACT'], 1.0)
    por = 1 - v['bulk_density'] / v['soil_density']
    v['max_moist'] = v['depth'] * por * 1000.0; v['init_moist'] = 0.5 * v['max_moist']
    v.update({k: np.full((NY, NX), x) for k, x in L2.items()})
    v['Ds'] *= scale; v['Ws'] *= scale; v['phi_s'] = np.zeros((3, NY, NX))
    return v


def write_file(path, values, names, extra_attrs=None, fill_inactive=True):
    with nc.Dataset(path, 'w') as d:
        d.createDimension('lat', NY); d.createDimension('lon', NX); d.createDimension('nlayer', 3)
        d.createVariable('lat', 'f8', ('lat',))[:] = LAT; d.createVariable('lon', 'f8', ('lon',))[:] = LON
        for n in names:
            if n == 'run_cell':
                d.createVariable(n, 'i4', ('lat', 'lon'), fill_value=0)[:] = MASK; continue
            x = values[n]; dims = ('nlayer', 'lat', 'lon') if x.ndim == 3 else ('lat', 'lon')
            v = d.createVariable(n, 'f8', dims, fill_value=FILL)
            y = x.copy()
            if fill_inactive:
                y[np.broadcast_to(MASK == 0, y.shape)] = FILL
            v[:] = y
        d.setncatts(extra_attrs or {})


def make_workdir(root, ext_values=None, ext_attrs=None):
    base = os.path.join(root, 'parameters', 'candidates', 'base-set')
    os.makedirs(os.path.join(base, 'bundle')); os.makedirs(os.path.join(base, 'domain'))
    write_file(os.path.join(base, 'bundle', ad.ab.OUT_NAME), soil_values(1.0), NATURAL)
    with nc.Dataset(os.path.join(base, 'domain', 'vic_global_5min_domain_nogl.nc'), 'w') as d:
        d.createDimension('lat', NY); d.createDimension('lon', NX)
        d.createVariable('lat', 'f8', ('lat',))[:] = LAT; d.createVariable('lon', 'f8', ('lon',))[:] = LON
        d.createVariable('mask', 'i4', ('lat', 'lon'))[:] = MASK
        d.createVariable('area', 'f4', ('lat', 'lon'))[:] = np.full((NY, NX), 1.0e6)
    provenance.write(os.path.join(base, 'bundle', 'provenance.yaml'),
                     {'object': 'parameters/candidates/base-set/bundle', 'code_dirty': False,
                      'method': {'natural_variables': NATURAL}, 'qc': {'status': 'passed'}})
    ext = os.path.join(root, 'external', 'mpr.nc'); os.makedirs(os.path.dirname(ext))
    values = ext_values or soil_values(1.5)
    values['avg_T'] = np.full((NY, NX), 9.0)                      # a template variable that differs
    write_file(ext, values, [n for n in NATURAL if n != 'phi_s'],
               ext_attrs or {'product_id': 'synthetic', 'not_authorized_for_global_production': 'true'}, fill_inactive=False)
    return base, ext


def jload(path):
    with open(path) as fh:
        return json.load(fh)


def run_main(mod, argv, workdir):
    out = io.StringIO()
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}), mock.patch.object(sys, 'argv', argv), \
            redirect_stdout(out), redirect_stderr(out):
        try:
            mod.main(); code = 0
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


class LabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(ad.out_name('mpr-reproduced'), 'vic_global_5min_soil_mpr-reproduced.nc')
        for bad in ('mpr_v2', 'new-soil', 'Soil', 'soil-final', 'fix'):
            with self.assertRaises(SystemExit):
                ad.out_name(bad)


class EndToEndTest(unittest.TestCase):
    def build(self, root, **kw):
        base, ext = make_workdir(root, **kw)
        code, log = run_main(ad, ['adopt_soil_fields.py', '--soil-source', ext, '--soil-label', 'synthetic',
                                  '--parameter-set', 'new-set', '--base-set', 'base-set', '--scratch'], root)
        comp = os.path.join(root, ad.sm.SCRATCH, 'soil')
        return base, ext, comp, code, log

    def test_producer_replaces_the_fields_on_active_cells_only(self):
        with tempfile.TemporaryDirectory() as t:
            base, ext, comp, code, log = self.build(t)
            self.assertEqual(code, 0, log)
            f = os.path.join(comp, 'vic_global_5min_soil_synthetic.nc'); self.assertTrue(os.path.isfile(f))
            with nc.Dataset(f) as o, nc.Dataset(ext) as e, nc.Dataset(os.path.join(base, 'bundle', ad.ab.OUT_NAME)) as b:
                for d in (o, e, b):
                    d.set_auto_mask(False)
                m = MASK == 1
                for v in ad.FIELDS:
                    xo, xe, xb = o[v][:], e[v][:], b[v][:]
                    mm = np.broadcast_to(m, xo.shape)
                    self.assertTrue(np.array_equal(xo[mm], xe[mm]), v)
                    self.assertTrue(np.array_equal(xo[~mm], xb[~mm]), v)       # inactive cells keep the base fill
                for v in ('avg_T', 'elev', 'phi_s', 'run_cell'):
                    self.assertTrue(np.array_equal(o[v][:], b[v][:]), v)         # kept bitwise, avg_T of ext not used
                self.assertEqual(o.getncattr('not_authorized_for_global_production'), 'true')
                self.assertEqual(o.getncattr('soil_source_product_id'), 'synthetic')
            prov = provenance.read(os.path.join(comp, 'provenance.yaml'))
            self.assertEqual(prov['input_sha256']['soil_source'], hashing.sha256(ext))
            self.assertEqual(prov['files'][0]['path'], 'vic_global_5min_soil_synthetic.nc')
            self.assertEqual(prov['qc']['status'], 'not_checked')
            rep = jload(os.path.join(comp, 'qc', 'reports', 'build_report.json'))
            self.assertEqual(rep['external_template_variables']['avg_T']['cells_differ'], int(MASK.sum()))
            self.assertEqual(rep['external_template_variables']['elev']['cells_differ'], 0)
            self.assertAlmostEqual(rep['fields']['Ds']['value']['area_mean_new'], 0.15)
            # the root recomputation finds the component file through the provenance
            self.assertEqual(rr.soil_file(comp), f)

    def test_verifier_passes_and_catches_a_changed_value(self):
        with tempfile.TemporaryDirectory() as t:
            base, ext, comp, code, log = self.build(t)
            self.assertEqual(code, 0, log)
            code, log = run_main(va, ['verify_adopted_soil.py', '--component-dir', comp], t)
            self.assertEqual(code, 0, log)
            summary = jload(os.path.join(comp, 'qc', 'summary.json'))
            self.assertEqual(summary['status'], 'passed')
            self.assertEqual(set(summary['checks']), {'grid', 'unchanged', 'replaced', 'elev', 'closure', 'vic_rules',
                                                      'global_means', 'external_template'})
            report = jload(os.path.join(comp, 'qc', 'reports', 'verify.json'))
            self.assertIn('avg_T', report['checks']['external_template']['variables'])
            self.assertTrue(os.path.isfile(os.path.join(comp, 'qc', 'figures', 'depth2_global.png')))
            # one active value changed in the component: the replaced check fails
            with nc.Dataset(os.path.join(comp, 'vic_global_5min_soil_synthetic.nc'), 'a') as o:
                o['Ds'][0, 0] = 0.123
            code, log = run_main(va, ['verify_adopted_soil.py', '--component-dir', comp], t)
            self.assertEqual(code, 1, log)
            summary = jload(os.path.join(comp, 'qc', 'summary.json'))
            self.assertEqual(summary['checks']['replaced'], 'failed'); self.assertEqual(summary['checks']['unchanged'], 'passed')

    def test_producer_stops_on_a_different_elev_or_a_missing_value(self):
        with tempfile.TemporaryDirectory() as t:
            v = soil_values(1.5); v['elev'] = np.full((NY, NX), 501.0)
            base, ext, comp, code, log = self.build(t, ext_values=v)
            self.assertNotEqual(code, 0); self.assertIn('elev', str(code))
        with tempfile.TemporaryDirectory() as t:
            v = soil_values(1.5); v['Ksat'][1, 0, 0] = FILL
            base, ext, comp, code, log = self.build(t, ext_values=v)
            self.assertNotEqual(code, 0); self.assertIn('Ksat', str(code))


if __name__ == '__main__':
    unittest.main()
