"""Unit tests for workflow/03_parameters/bundle/assemble_bundle.py (variable split and bitwise copy on small
synthetic NetCDF files).

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


if __name__ == '__main__':
    unittest.main()
