"""Unit tests for workflow/03_parameters/bundle/assemble_bundle.py (variable split and bitwise copy on small
synthetic NetCDF files) and for the soil and snow-band value checks of verify_bundle.py.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, os, tempfile, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'bundle', 'assemble_bundle.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('assemble_bundle', SRC)
    ab = importlib.util.module_from_spec(spec); spec.loader.exec_module(ab)

LAT = np.array([-1.0, 0.0, 1.0]); LON = np.array([10.0, 11.0])


def make(path, nveg, extra_soil=True, lat=LAT, veg_only_vars=()):
    with nc.Dataset(path, 'w') as d:
        d.createDimension('lat', 3); d.createDimension('lon', 2); d.createDimension('veg_class', nveg)
        d.createDimension('month', 12)
        d.createVariable('lat', 'f8', ('lat',))[:] = lat
        d.createVariable('lon', 'f8', ('lon',))[:] = LON
        d.createVariable('veg_class', 'i4', ('veg_class',))[:] = np.arange(1, nveg + 1)
        cv = d.createVariable('Cv', 'f8', ('veg_class', 'lat', 'lon'), fill_value=np.nan, zlib=True)
        cv[:] = np.full((nveg, 3, 2), 1.0 / nveg); cv[0, 0, 0] = np.nan
        d.createVariable('LAI', 'f8', ('veg_class', 'month', 'lat', 'lon'))[:] = np.random.default_rng(nveg).random((nveg, 12, 3, 2))
        d.createVariable('Nveg', 'i4', ('lat', 'lon'))[:] = nveg - 1
        if extra_soil:
            d.createDimension('nlayer', 3)
            d.createVariable('run_cell', 'i4', ('lat', 'lon'))[:] = 1
            k = d.createVariable('Ksat', 'f8', ('nlayer', 'lat', 'lon'), fill_value=-9999.0)
            k[:] = np.arange(18).reshape(3, 3, 2); k.units = 'mm/day'
            d.createVariable('flag', 'u1', ('nlayer', 'lat', 'lon'))[:] = 7
        for name in veg_only_vars:
            d.createVariable(name, 'f8', ('veg_class', 'lat', 'lon'))[:] = 0.5


def raw(path, name):
    with nc.Dataset(path) as d:
        d.set_auto_maskandscale(False)
        return d[name][:].copy(), d[name].dtype, d[name].dimensions


class PlanTest(unittest.TestCase):
    def test_split_and_copy_is_bitwise(self):
        with tempfile.TemporaryDirectory() as t:
            nat, veg, out = (os.path.join(t, n) for n in ('nat.nc', 'veg.nc', 'out.nc'))
            make(nat, 14); make(veg, 16, extra_soil=False)
            with nc.Dataset(nat) as n, nc.Dataset(veg) as v:
                split, dims = ab.plan(n, v)
                self.assertEqual(sorted(split['natural']), ['Ksat', 'flag', 'run_cell'])
                self.assertEqual(sorted(split['replaced']), ['Cv', 'LAI', 'Nveg', 'veg_class'])
                self.assertEqual(dims['veg_class'], 16)
                with nc.Dataset(out, 'w') as o:
                    for k, n_ in dims.items():
                        o.createDimension(k, n_)
                    for c in ab.COORDS + tuple(split['natural']):
                        ab.copy_variable(n, o, c)
                    for c in split['vegetation']:
                        ab.copy_variable(v, o, c)
            for name, src in (('Ksat', nat), ('flag', nat), ('run_cell', nat), ('Cv', veg), ('LAI', veg),
                              ('Nveg', veg), ('veg_class', veg)):
                a, ad, adim = raw(out, name); b, bd, bdim = raw(src, name)
                self.assertEqual((ad, adim), (bd, bdim))
                self.assertEqual(np.ascontiguousarray(a).tobytes(), np.ascontiguousarray(b).tobytes(), name)
            with nc.Dataset(out) as o:
                self.assertEqual(o['Ksat'].units, 'mm/day')
                self.assertEqual(o['Ksat'].getncattr('_FillValue'), -9999.0)
                o.set_auto_mask(False); self.assertTrue(np.isnan(o['Cv'][0, 0, 0]))

    def test_vegetation_variable_missing_from_component_fails(self):
        with tempfile.TemporaryDirectory() as t:
            nat, veg = os.path.join(t, 'nat.nc'), os.path.join(t, 'veg.nc')
            make(nat, 14, veg_only_vars=('rarc',)); make(veg, 16, extra_soil=False)
            with nc.Dataset(nat) as n, nc.Dataset(veg) as v:
                with self.assertRaises(ValueError):
                    ab.plan(n, v)

    def test_grid_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as t:
            nat, veg = os.path.join(t, 'nat.nc'), os.path.join(t, 'veg.nc')
            make(nat, 14); make(veg, 16, extra_soil=False, lat=LAT + 1e-9)
            with nc.Dataset(nat) as n, nc.Dataset(veg) as v:
                with self.assertRaises(ValueError):
                    ab.plan(n, v)



class SourcesTest(unittest.TestCase):
    """Review P3 B2: the bundle is assembled only from an accepted vegetation component, and the restrictions of the
    natural bundle (not authorized for global production, product stage) are carried into the assembled file."""

    def component(self, d, status='passed', dirty=False):
        os.makedirs(f'{d}/vegetation', exist_ok=True)
        with open(f'{d}/vegetation/provenance.yaml', 'w') as fh:
            fh.write(f'code_dirty: {str(dirty).lower()}\nqc:\n  status: {status}\n')

    def test_vegetation_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            self.component(d)
            self.assertIsNone(ab.vegetation_not_accepted(d))
            for status, dirty in (('failed', False), ('not_checked', False), ('passed', True)):
                self.component(d, status, dirty)
                self.assertIn('not accepted', ab.vegetation_not_accepted(d))
            os.remove(f'{d}/vegetation/provenance.yaml')
            self.assertIn('no provenance', ab.vegetation_not_accepted(d))

    def test_restrictions_carried(self):
        with tempfile.TemporaryDirectory() as d:
            make(f'{d}/nat.nc', 14)
            with nc.Dataset(f'{d}/nat.nc', 'a') as n:
                n.not_authorized_for_global_production = 'true'; n.product_stage = 'image_driver_smoke_candidate'
                n.title = 'not a restriction'
            with nc.Dataset(f'{d}/nat.nc') as n:
                self.assertEqual(ab.source_restrictions(n), {'not_authorized_for_global_production': 'true',
                                                             'product_stage': 'image_driver_smoke_candidate'})


VB_SRC = os.path.join(HERE, '..', '..', 'workflow', '03_parameters', 'bundle', 'verify_bundle.py')
with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': '/nonexistent'}):
    spec = importlib.util.spec_from_file_location('verify_bundle', VB_SRC)
    vb = importlib.util.module_from_spec(spec); spec.loader.exec_module(vb)


def soil(n=4):
    """Valid soil values for n cells (3 layers)."""
    one = np.ones(n); lay = np.ones((3, n))
    return {'infilt': 0.2 * one, 'Ds': 0.01 * one, 'Dsmax': 10 * one, 'Ws': 50 * one, 'c': 2 * one,
            'elev': 100 * one, 'avg_T': 10 * one, 'dp': 4 * one, 'rough': 0.001 * one, 'snow_rough': 0.0005 * one,
            'annual_prec': 800 * one, 'fs_active': one,
            'expt': 10 * lay, 'Ksat': 100 * lay, 'init_moist': 50 * lay, 'phi_s': -999 * lay,
            'depth': np.array([0.1, 0.3, 1.0])[:, None] * lay, 'bubble': 20 * lay, 'quartz': 0.5 * lay,
            'bulk_density': 1300 * lay, 'soil_density': 2650 * lay, 'Wcr_FRACT': 0.6 * lay, 'Wpwp_FRACT': 0.3 * lay,
            'resid_moist': 0.02 * lay, 'Wfc_FRACT': 0.8 * lay}


class SoilValueTest(unittest.TestCase):
    def check(self, v):
        vic, pl, der = vb.soil_checks(v)
        return vic, pl, vb.status_of(vic, pl)

    def test_valid(self):
        vic, pl, st = self.check(soil())
        self.assertEqual(st, 'passed', (vic, pl))

    def test_vic_rules(self):
        cases = {'depth_below_min': ('depth', (0, 1), 0.0005), 'Wpwp_above_Wcr': ('Wpwp_FRACT', (2, 0), 0.7),
                 'Wfc_above_1': ('Wfc_FRACT', (1, 3), 1.2), 'porosity_outside_0_1': ('bulk_density', (0, 2), 2700),
                 'wilting_point_below_residual': ('resid_moist', (2, 1), 0.2),
                 'Ws_not_below_bottom_max_moist': ('Ws', (1,), 600.0)}
        for rule, (k, idx, val) in cases.items():
            with self.subTest(rule=rule):
                v = soil(); v[k][idx] = val
                vic, pl, st = self.check(v)
                self.assertEqual(vic[rule], 1); self.assertEqual(st, 'failed')

    def test_fill_and_layer_order(self):
        v = soil(); v['Ksat'][1, 0] = np.nan; v['depth'][0, 3] = 0.5
        vic, _, st = self.check(v)
        self.assertEqual(vic['fill_or_nan'], {'Ksat': 1}); self.assertEqual(vic['layer1_thicker_than_layer2'], 1)
        self.assertEqual(st, 'failed')

    def test_annual_prec_reported_only(self):
        v = soil(); v['annual_prec'][0] = np.nan; v['annual_prec'][1] = -5
        vic, pl, st = self.check(v)
        self.assertEqual(st, 'passed', (vic, pl))
        self.assertEqual(vb.soil_checks(v)[2]['unused'], {'annual_prec': {'fill_or_nan': 1, 'not_positive': 1}})

    def test_plausibility_is_warning(self):
        v = soil(); v['expt'][0, 0] = 2.5; v['avg_T'][1] = 55; v['init_moist'][0, 2] = 1000
        vic, pl, st = self.check(v)
        self.assertEqual((pl['expt_below_3'], pl['avg_T_outside_range'], pl['init_moist_above_max_moist']), (1, 1, 1))
        self.assertEqual(st, 'warning')

    def test_baseflow_conversion(self):
        v = soil(1)
        _, _, der = vb.soil_checks(v)
        mm = 1.0 * (1 - 1300 / 2650) * 1000
        dsmax = 10 * (mm - 50) ** 2 + 0.01 * mm
        self.assertAlmostEqual(der['Dsmax_converted'][0], dsmax)
        self.assertAlmostEqual(der['Ds_converted'][0], 0.01 * 50 / dsmax)
        self.assertAlmostEqual(der['Ws_converted'][0], 50 / mm)


class BandValueTest(unittest.TestCase):
    def bands(self):
        af = np.array([[0.5, 1.0], [0.5, 0.0]]); el = np.array([[90.0, 100.0], [110.0, 0.0]])
        return af, el, af.copy(), np.array([100.0, 100.0])

    def test_valid(self):
        vic, silent, diff = vb.band_checks(*self.bands())
        self.assertEqual(vb.status_of(vic, silent), 'passed', (vic, silent))
        np.testing.assert_allclose(diff, 0)

    def test_pfactor_without_area_stops(self):
        af, el, pf, elev = self.bands(); pf[1, 1] = 0.1
        vic, silent, _ = vb.band_checks(af, el, pf, elev)
        self.assertEqual(vic['Pfactor_on_band_without_area'], 1)
        self.assertEqual(vb.status_of(vic, silent), 'failed')

    def test_silent_changes(self):
        af, el, pf, elev = self.bands(); af[0, 0] = 0.6; elev[1] = 101.0
        vic, silent, diff = vb.band_checks(af, el, pf, elev)
        # cell 0: the rescaled band mean moves away from elev; cell 1: elev itself differs
        self.assertEqual((silent['AreaFract_sum_not_1'], silent['band_mean_elevation_not_elev']), (1, 2))
        # VIC rescales AreaFract to (0.6, 0.5) / 1.1 before the mean: (54 + 55) / 1.1
        self.assertAlmostEqual(diff[0], (0.6 * 90 + 0.5 * 110) / 1.1 - 100)
        self.assertEqual(vb.status_of(vic, silent), 'warning')


if __name__ == '__main__':
    unittest.main()
