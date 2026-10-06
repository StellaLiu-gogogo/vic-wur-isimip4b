"""Regression tests for the verifier status rules (code review of 2026-10-05, findings #8 and #3).

#8: a verifier ends with the exit status of its result (common/qc.py: passed 0, failed 1, warning 3,
    not_checked 4), so that a Slurm job whose verifier finds a failure does not end COMPLETED.
#3: a per-year report counts only for the data file it was written for (SHA-256) and the verifier code that wrote
    it; a stale report (no binding, or a replaced data file) counts as not_checked.

The expensive per-file checks are replaced by a stand-in that writes a report; the tests exercise the summary,
the binding, and the exit status of the real main() of each verifier. The vegetation verifier runs on a tiny
synthetic component.

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from unittest import mock

import numpy as np
import netCDF4 as nc
import yaml

from common import qc

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, '..', '..', 'workflow')
VERIFIER = {'verifier_commit': '0' * 40, 'verifier_dirty': True, 'verifier_code_tree': {}}   # of the stand-in


def load(path, name, workdir):
    with mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}):
        spec = importlib.util.spec_from_file_location(name, os.path.join(WF, path))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def write_report(reports, year, status, data_files):
    """What a verifier writes for one year: its result and the binding to the data files."""
    qc.write_json(f'{reports}/verify_{year}.json', {'year': year, 'status': status,
                                                     'binding': qc.binding(data_files, VERIFIER)})


def run_main(mod, argv, workdir):
    """main() of a verifier; returns its exit status (None when it returns normally)."""
    with mock.patch.object(sys, 'argv', ['verifier'] + argv), contextlib.redirect_stdout(io.StringIO()), \
            mock.patch.dict(os.environ, {'ISIMIP4B_WORKDIR': workdir}):
        try:
            mod.main()
        except SystemExit as e:
            return e.code if e.code is not None else 0
    return None


def touch(path, content):
    with open(path, 'w') as fh:
        fh.write(content)


class LanduseVerifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.vf = load('04_forcing/landuse/verify_forcing.py', 'lu_verifier', self.W)
        self.unit = f'{self.W}/unit'; os.makedirs(self.unit)
        for y in (2015, 2016):
            touch(f'{self.unit}/coverage_histsoc_{y}.nc', f'data {y}')
        self.reports = f'{self.unit}/qc/reports'; os.makedirs(self.reports)
        self.status = {}

    def tearDown(self):
        self.tmp.cleanup()

    def fake_verify(self, fn, *args):
        y = int(fn[:-3].rsplit('_', 1)[1]); write_report(args[2], y, self.status[y], [fn])
        return y, self.status[y]

    def main(self, years):
        with mock.patch.object(self.vf, 'verify_file', self.fake_verify):
            code = run_main(self.vf, ['--scenario', 'histsoc', '--unit-dir', self.unit] + (['--years', years] if years else []), self.W)
        return code, json.load(open(f'{self.unit}/qc/summary.json'))

    def test_all_passed_exits_0(self):
        self.status = {2015: 'passed', 2016: 'passed'}
        code, s = self.main(None)
        self.assertEqual((code, s['status']), (0, 'passed'))

    def test_failed_exits_1(self):
        self.status = {2015: 'passed', 2016: 'failed'}
        code, s = self.main(None)
        self.assertEqual((code, s['status']), (1, 'failed'))

    def test_report_without_binding_is_not_checked(self):
        qc.write_json(f'{self.reports}/verify_2015.json', {'year': 2015, 'status': 'passed'})   # old report
        self.status = {2016: 'passed'}
        code, s = self.main('2016')
        self.assertEqual(s['per_year']['2015'], 'not_checked')
        self.assertEqual((code, s['status']), (4, 'not_checked'))

    def test_replaced_file_is_not_checked(self):
        write_report(self.reports, 2015, 'passed', [f'{self.unit}/coverage_histsoc_2015.nc'])
        touch(f'{self.unit}/coverage_histsoc_2015.nc', 'replaced data')
        self.status = {2016: 'passed'}
        code, s = self.main('2016')
        self.assertEqual((code, s['per_year']['2015'], s['status']), (4, 'not_checked', 'not_checked'))


class WaterUseVerifierTest(unittest.TestCase):
    SECTORS = ('municipal', 'manufacturing')
    VARS = ('demand', 'consumption_fraction', 'groundwater_fraction')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.vf = load('04_forcing/water_use/verify_forcing.py', 'wu_verifier', self.W)
        self.unit = f'{self.W}/unit'; os.makedirs(self.unit)
        for y in (2015, 2016):
            for s in self.SECTORS:
                for v in self.VARS:
                    touch(f'{self.unit}/{s}_{v}_histsoc_{y}.nc', f'{s} {v} {y}')
        self.reports = f'{self.unit}/qc/reports'; os.makedirs(self.reports)
        self.status = {}

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, y):
        return [f'{self.unit}/{s}_{v}_histsoc_{y}.nc' for s in self.SECTORS for v in self.VARS]

    def fake_verify(self, job):
        y, reports = job[0], job[5]; write_report(reports, y, self.status[y], self.files(y))
        return y, self.status[y]

    def main(self, years):
        with mock.patch.object(self.vf, 'verify_year', self.fake_verify), \
                mock.patch.dict(self.vf.YEARS, {'histsoc': (2015, 2016)}):
            code = run_main(self.vf, ['--scenario', 'histsoc', '--unit-dir', self.unit] + (['--years', years] if years else []), self.W)
        return code, json.load(open(f'{self.unit}/qc/summary.json'))

    def test_all_passed_exits_0(self):
        self.status = {2015: 'passed', 2016: 'passed'}
        self.assertEqual(self.main(None)[0], 0)

    def test_failed_exits_1(self):
        self.status = {2015: 'failed', 2016: 'passed'}
        code, s = self.main(None)
        self.assertEqual((code, s['status']), (1, 'failed'))

    def test_report_without_binding_is_not_checked(self):
        qc.write_json(f'{self.reports}/verify_2015.json', {'year': 2015, 'status': 'passed'})
        self.status = {2016: 'passed'}
        code, s = self.main('2016')
        self.assertEqual((code, s['per_year']['2015'], s['status']), (4, 'not_checked', 'not_checked'))

    def test_replaced_file_is_not_checked(self):
        write_report(self.reports, 2015, 'passed', self.files(2015))
        touch(self.files(2015)[3], 'replaced')
        self.status = {2016: 'passed'}
        code, s = self.main('2016')
        self.assertEqual((code, s['per_year']['2015']), (4, 'not_checked'))


class FakePool:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def imap_unordered(self, f, jobs): return map(f, jobs)


class ClimateVerifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        self.vf = load('04_forcing/climate/verify_forcing.py', 'cl_verifier', self.W)
        self.unit = f'{self.W}/scratch/climate-forcing/ec-earth3-esm-1-1/esm-hist/prec'; os.makedirs(self.unit)
        for y in (2015, 2016):
            touch(f'{self.unit}/prec_ec-earth3-esm-1-1_esm-hist_{y}.nc', f'prec {y}')
        provenance = {'forcing_unit': 'climate/ec-earth3-esm-1-1/esm-hist/prec', 'qc': {'status': 'not_checked'}}
        with open(f'{self.unit}/provenance.yaml', 'w') as fh:
            yaml.safe_dump(provenance, fh, sort_keys=False)
        self.reports = f'{self.unit}/qc/reports'; os.makedirs(self.reports)
        self.status = {}

    def tearDown(self):
        self.tmp.cleanup()

    def fake_verify(self, args):
        fn, var, reports = args[0], args[1], args[4]
        y = int(fn[:-3].rsplit('_', 1)[1]); write_report(reports, y, self.status[y], [fn])
        return var, y, self.status[y]

    def main(self, years):
        argv = ['--gcm', 'ec-earth3-esm-1-1', '--alias', 'esm-hist', '--variables', 'prec', '--scratch']
        with mock.patch.object(self.vf, 'verify_file', self.fake_verify), mock.patch.object(self.vf, 'Pool', FakePool), \
                mock.patch.object(self.vf, 'Context', lambda *a: None), mock.patch.dict(os.environ):
            code = run_main(self.vf, argv + (['--years', years] if years else []), self.W)
        prov = yaml.safe_load(open(f'{self.unit}/provenance.yaml'))
        return code, json.load(open(f'{self.unit}/qc/summary.json')), prov['qc']['status']

    def test_all_passed_exits_0(self):
        self.status = {2015: 'passed', 2016: 'passed'}
        self.assertEqual(self.main(None)[::2], (0, 'passed'))

    def test_failed_exits_1(self):
        self.status = {2015: 'passed', 2016: 'failed'}
        self.assertEqual(self.main(None)[::2], (1, 'failed'))

    def test_report_without_binding_is_not_checked(self):
        qc.write_json(f'{self.reports}/verify_2015.json', {'year': 2015, 'status': 'passed'})
        self.status = {2016: 'passed'}
        code, s, prov = self.main('2016')
        self.assertEqual((code, s['per_year']['2015'], prov), (4, 'not_checked', 'not_checked'))

    def test_replaced_file_is_not_checked(self):
        write_report(self.reports, 2015, 'passed', [f'{self.unit}/prec_ec-earth3-esm-1-1_esm-hist_2015.nc'])
        touch(f'{self.unit}/prec_ec-earth3-esm-1-1_esm-hist_2015.nc', 'replaced')
        self.status = {2016: 'passed'}
        code, s, prov = self.main('2016')
        self.assertEqual((code, s['per_year']['2015'], prov), (4, 'not_checked', 'not_checked'))


class VegetationVerifierTest(unittest.TestCase):
    """A 2 x 2 component with one active-cell tile per cell and no land-use forcing files: forcing_tiles fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        self.bv = load('03_parameters/vegetation/build_vegetation.py', 'build_vegetation', W)
        sys.modules['build_vegetation'] = self.bv          # the verifier imports it by name
        self.vf = load('03_parameters/vegetation/verify_vegetation.py', 'veg_verifier', W)
        pset = f'{W}/parameters/candidates/vic-global-5arcmin-version-a'
        os.makedirs(f'{pset}/domain'); os.makedirs(f'{pset}/bundle')
        self.comp = f'{W}/component'; os.makedirs(self.comp)
        for soc in self.bv.SOC:
            os.makedirs(f'{W}/forcing/landuse/{soc}')
        mask = np.array([[1, 1], [1, 0]]); lat = np.array([10.0, 10.1]); lon = np.array([20.0, 20.1])
        with nc.Dataset(f'{pset}/{self.bv.DOMAIN}', 'w') as d:
            d.createDimension('lat', 2); d.createDimension('lon', 2)
            for n, x in (('lat', lat), ('lon', lon)):
                d.createVariable(n, 'f8', (n,))[:] = x
            d.createVariable('mask', 'i4', ('lat', 'lon'))[:] = mask
        base = f'{pset}/{self.bv.BASE_BUNDLE}'
        for path, extra in ((base, False), (f'{self.comp}/{self.bv.OUT_NAME}', True)):
            self.parameter_file(path, mask.astype(bool), extra)
        with open(f'{self.comp}/backfill_tiles.csv', 'w') as fh:
            fh.write('class,row,col,lat,lon,level,donor_row,donor_col,donor_lat,donor_lon,distance_km,koppen,donor_koppen,'
                     'soc_bits\n')
        with open(f'{self.comp}/provenance.yaml', 'w') as fh:
            yaml.safe_dump({'inputs': {'base_bundle': os.path.relpath(base, W)}}, fh)

    def parameter_file(self, path, mask, component):
        n = self.bv.NCLASS
        with nc.Dataset(path, 'w') as d:
            for dim, size in (('veg_class', n), ('month', 12), ('root_zone', 3), ('lat', 2), ('lon', 2)):
                d.createDimension(dim, size)
            cv = np.zeros((n, 2, 2)); cv[0] = 1.0; cv[:, ~mask] = np.nan
            d.createVariable('Cv', 'f8', ('veg_class', 'lat', 'lon'))[:] = cv
            for f in self.bv.FIELDS:
                dims = (('veg_class', 'month', 'lat', 'lon') if f in self.bv.MONTHLY else
                        ('veg_class', 'root_zone', 'lat', 'lon') if f in self.bv.ROOT else ('veg_class', 'lat', 'lon'))
                x = np.full([d.dimensions[k].size for k in dims], {'overstory': 1.0, 'root_fract': 1 / 3}.get(f, 0.5))
                d.createVariable(f, 'f8', dims)[:] = x
            if component:
                d.createVariable('Nveg', 'i4', ('lat', 'lon'))[:] = np.where(mask, 1, -1)
                d.createVariable('added_tile_bits', 'u2', ('lat', 'lon'))[:] = 0
                d.createVariable('backfill_level', 'i1', ('veg_class', 'lat', 'lon'))[:] = 0

    def tearDown(self):
        sys.modules.pop('build_vegetation', None)
        self.tmp.cleanup()

    def test_failed_exits_1(self):
        code = run_main(self.vf, ['--component-dir', self.comp, '--processes', '1'], self.W)
        summary = json.load(open(f'{self.comp}/qc/summary.json'))
        self.assertEqual(summary['checks']['forcing_tiles'], 'failed')
        self.assertEqual((code, summary['status']), (1, 'failed'))


if __name__ == '__main__':
    unittest.main()
