"""Unit tests for the product units of stage 06_postprocessing (workflow/06_postprocessing/make_unit.py; D07, D11):
on the tiny synthetic workdir of test_postprocessing_static.py, a one-year run with constant VIC outputs is turned into
product files whose values, units, time axes, layers and unit record are checked: rates from mm per step, the
outlet discharge, layer means with depth bounds, reservoir volumes per simulated area, total water storage, sector
sums, consumption from the forcing fraction, degC to K, cm to m; daily products only where the daily stream has the
outputs; recipes that differ from the campaign stop the producer; an existing unit is not overwritten.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import datetime, json, os, sys, unittest

import numpy as np
import netCDF4 as nc
import cftime
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '06_postprocessing'))
from test_postprocessing_static import SyntheticWorkdir, LAT5, LON5, write   # noqa: E402
import make_unit      # noqa: E402
import static_fields  # noqa: E402
import support        # noqa: E402

YEAR = 2011
RUN = 'ec-earth3-esm-1-1_historical_histsoc_default_historical__t'
VARIABLES = {   # the recipes of products.yaml used here, with the protocol unit and frequency
    'qtot': ('kg m-2 s-1', 'daily & monthly'), 'dis': ('m3 s-1', 'daily & monthly'),
    'soilmoist': ('kg m-2', 'daily if possible, else monthly'), 'tsl': ('K', 'daily if possible, else monthly'),
    'snd': ('m', 'daily if possible, else monthly'), 'reservoirstor': ('kg m-2', 'monthly'),
    'tws': ('kg m-2', 'monthly'), 'adomuse': ('kg m-2 s-1', 'monthly'), 'atotwwgw': ('kg m-2 s-1', 'monthly')}
SOURCES = ['OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_DAM_SECT', 'OUT_WI_TREM_SECT', 'OUT_WI_NREN_SECT']


class ProductUnitTest(SyntheticWorkdir):
    def setUp(self):
        super().setUp()
        W = self.W
        self.cfg = cfg = support.config()
        cfg['variables'] = {v: r for v, r in cfg['variables'].items() if v in VARIABLES}
        prot = f'{W}/protocol/definitions/variable'
        with open(f'{prot}/hydrological.yaml', 'w') as fh:
            yaml.safe_dump([{'specifier': v, 'long_name': v.upper(), 'units': u, 'frequency': f}
                            for v, (u, f) in VARIABLES.items()], fh)
        camp = support.load_yaml(self.campaign)
        camp['gcms'] = {'ec-earth3-esm-1-1': {}}
        camp['output'] = {'isimip': {v: {'vic': list(r.get('terms', [])) + list(r.get('volumes', [])),
                                         'rule': 'test rule'} for v, r in cfg['variables'].items()}}
        with open(self.campaign, 'w') as fh:
            yaml.safe_dump(camp, fh)
        self.assertEqual(self.run_main(static_fields), 0)
        self.make_run()

    def make_run(self):
        W = self.W
        ny, nx = LAT5.size, LON5.size
        rd = f'{W}/runs/test-campaign/{RUN}'
        cal = 'proleptic_gregorian'; units = 'days since 0001-01-01 00:00:00'
        days = [cftime.datetime(YEAR, 1, 1, calendar=cal) + datetime.timedelta(days=i) for i in range(366)]
        d_num = cftime.date2num(days, units, cal)
        months = [cftime.datetime(YEAR + (m // 12), m % 12 + 1, 1, calendar=cal) for m in range(13)]
        m_num = cftime.date2num(months, units, cal)
        self.month_days = np.diff(m_num)
        field = np.ones((ny, nx), 'f4')
        col = np.broadcast_to(np.arange(1, nx + 1, dtype='f4'), (ny, nx))   # discharge grows downstream (east)
        dims = {'time': None, 'nv': 2, 'nlayer': 3, 'wu_class': 5, 'lat': ny, 'lon': nx}

        def stream(path, n, t, step_days, layered_soil):
            v = {'time': (('time',), t[:n], {}), 'time_bnds': (('time', 'nv'), np.stack([t[:n], t[1:n + 1]], 1), {}),
                 'lat': (('lat',), LAT5, {}), 'lon': (('lon',), LON5, {})}
            sd = step_days[:, None, None]
            v['OUT_RUNOFF'] = (('time', 'lat', 'lon'), sd * field, {})                # 1 mm per day
            v['OUT_BASEFLOW'] = (('time', 'lat', 'lon'), 2 * sd * field, {})           # 2 mm per day
            v['OUT_DISCHARGE'] = (('time', 'lat', 'lon'), np.broadcast_to(col, (n, ny, nx)), {})
            v['OUT_SOIL_MOIST'] = (('time', 'nlayer', 'lat', 'lon'),
                                   np.broadcast_to(np.array([10, 20, 30], 'f4')[None, :, None, None],
                                                   (n, 3, ny, nx)), {})
            if not layered_soil:
                return v
            v['OUT_SOIL_TEMP'] = (('time', 'nlayer', 'lat', 'lon'), np.full((n, 3, ny, nx), 10, 'f4'), {})
            v['OUT_SNOW_DEPTH'] = (('time', 'lat', 'lon'), np.full((n, ny, nx), 50, 'f4'), {})
            for name, val in (('OUT_SWE', 4), ('OUT_SNOW_CANOPY', 1), ('OUT_WDEW', 2), ('OUT_SURFSTOR', 3),
                              ('OUT_STREAM_MOIST', 5)):
                v[name] = (('time', 'lat', 'lon'), np.full((n, ny, nx), val, 'f4'), {})
            g = np.zeros((n, ny, nx), 'f4'); g[:, 2, 2] = 1.0                           # one reservoir of 1 hm3
            v['OUT_GDAM_STORAGE'] = (('time', 'lat', 'lon'), g, {})
            v['OUT_LDAM_STORAGE'] = (('time', 'lat', 'lon'), np.zeros((n, ny, nx), 'f4'), {})
            for s in SOURCES:
                v[s] = (('time', 'wu_class', 'lat', 'lon'), np.broadcast_to(sd[:, None], (n, 5, ny, nx)) * 1.0, {})
            return v

        unit = {'OUT_DISCHARGE': 'm3 s-1', 'OUT_SOIL_TEMP': 'C', 'OUT_SNOW_DEPTH': 'cm',
                'OUT_GDAM_STORAGE': 'hm3', 'OUT_LDAM_STORAGE': 'hm3'}
        for name, n, t, sd, full in (('daily.2011-01-01.nc', 365, d_num, np.ones(365, 'f4'), False),
                                     ('monthly.2011-01.nc', 12, m_num, self.month_days.astype('f4'), True)):
            path = f'{rd}/output/{name}'
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with nc.Dataset(path, 'w') as d:
                for k, size in dims.items():
                    d.createDimension(k, size)
                for k, (vd, arr, _) in stream(path, n, t, sd, full).items():
                    var = d.createVariable(k, 'f8' if k in ('time', 'time_bnds', 'lat', 'lon') else 'f4', vd)
                    var[:] = arr
                    if k.startswith('OUT_'):
                        var.units = unit.get(k, 'mm')
                d['time'].units = units; d['time'].calendar = cal
        cf = f'forcing/water_use/test/municipal_consumption_fraction_test_{YEAR}.nc'
        write(f'{W}/{cf}', {'time': 1, 'lat': ny, 'lon': nx},
              {'time': (('time',), np.zeros(1), None), 'lat': (('lat',), LAT5, None), 'lon': (('lon',), LON5, None),
               'consumption_fraction': (('time', 'lat', 'lon'), np.full((1, ny, nx), 0.5), None)})
        man = {'campaign_id': 'test-campaign', 'run_id': RUN, 'segment_id': RUN.split('__')[0], 'label': 't',
               'production': False, 'run_dir': f'runs/test-campaign/{RUN}', 'status': 'completed',
               'period': {'start': f'{YEAR}-01-01', 'end': f'{YEAR}-12-31'},
               'attempts': [{'attempt': 1, 'slurm_job_id': 1, 'status': 'completed'}],
               'forcing_view': {'water_use/municipal_consumption_fraction': {str(YEAR): {'source': cf}}}}
        with open(f'{rd}/run_manifest.json', 'w') as fh:
            json.dump(man, fh)
        self.unit = f'{W}/scratch/test-task/postprocessed/test-campaign/ec-earth3-esm-1-1/' \
                    f'historical_histsoc_default_historical/{YEAR}-{YEAR}'

    def produce(self):
        return self.run_main(make_unit, '--run', RUN)

    def values(self, name, var):
        with nc.Dataset(f'{self.unit}/{name}') as d:
            return np.ma.filled(d[var][:].astype('f8'), np.nan), d

    def test_products(self):
        self.assertEqual(self.produce(), 0)
        names = sorted(os.listdir(self.unit))
        self.assertIn('provenance.yaml', names)
        want = {f'{v}_{s}_{YEAR}_{YEAR}.nc' for v in VARIABLES for s in ('monthly',)} | \
            {f'{v}_daily_{YEAR}_{YEAR}.nc' for v in ('qtot', 'dis', 'soilmoist')}
        self.assertEqual(set(names) - {'provenance.yaml'}, want)
        cov = np.isfinite(self.values(f'qtot_monthly_{YEAR}_{YEAR}.nc', 'qtot')[0][0])
        self.assertEqual(int(cov.sum()), 11)
        # rates: 3 mm per day as kg m-2 s-1, daily and monthly
        for step in ('daily', 'monthly'):
            q, _ = self.values(f'qtot_{step}_{YEAR}_{YEAR}.nc', 'qtot')
            np.testing.assert_allclose(q[:, cov], 3 / 86400, rtol=1e-6)
        # outlet discharge: the eastern fine column of each coarse cell (2, 4, 6, 8)
        d, _ = self.values(f'dis_daily_{YEAR}_{YEAR}.nc', 'dis')
        self.assertEqual(d.shape[0], 365)
        np.testing.assert_allclose(d[0, 1], [2, 4, 6, 8])
        # layers with depths
        s, _ = self.values(f'soilmoist_monthly_{YEAR}_{YEAR}.nc', 'soilmoist')
        np.testing.assert_allclose(s[0, :, 1, 1], [10, 20, 30])
        with nc.Dataset(f'{self.unit}/soilmoist_monthly_{YEAR}_{YEAR}.nc') as f:
            self.assertEqual(f.location_varying_layer_depth, 'true')
            self.assertEqual(f['soilmoist'].dimensions, ('time', 'lev', 'lat', 'lon'))
            db = f['depth_bnds'][:, :, 1, 1]
            np.testing.assert_allclose(db[0], [0.0, 0.1, 0.6], atol=1e-6)
            np.testing.assert_allclose(db[1], [0.1, 0.6, db[1, 2]], atol=1e-6)
            t = f['time'][:]
            self.assertEqual(f['time'].units, 'days since 1601-01-01 00:00:00')
            self.assertEqual(t[0], cftime.date2num(cftime.datetime(YEAR, 1, 1, calendar='proleptic_gregorian'),
                                                   'days since 1601-01-01 00:00:00', 'proleptic_gregorian'))
            self.assertEqual(t[1] - t[0], 31)
        # temperature and snow depth
        np.testing.assert_allclose(self.values(f'tsl_monthly_{YEAR}_{YEAR}.nc', 'tsl')[0][0, :, 1, 1], 283.15,
                                   rtol=1e-6)
        np.testing.assert_allclose(self.values(f'snd_monthly_{YEAR}_{YEAR}.nc', 'snd')[0][0, 1, 1], 0.5, rtol=1e-6)
        # reservoir: 1 hm3 in fine cell (2, 2), coarse cell (1, 1) of the product grid (latitudes descending)
        r, _ = self.values(f'reservoirstor_monthly_{YEAR}_{YEAR}.nc', 'reservoirstor')
        with nc.Dataset(f'{self.W}/scratch/test-task/postprocessed/test-campaign/static/cellarea.nc') as f:
            area_km2 = float(f['cellarea'][1, 1])
        np.testing.assert_allclose(r[0, 1, 1], 1e9 / (area_km2 * 1e6), rtol=1e-5)
        self.assertEqual(float(np.nansum(r[0])), float(r[0, 1, 1]))
        tws, _ = self.values(f'tws_monthly_{YEAR}_{YEAR}.nc', 'tws')
        np.testing.assert_allclose(tws[0, 1, 1], 60 + 4 + 1 + 2 + 3 + 5 + r[0, 1, 1], rtol=1e-5)
        # sectors: all five classes of the groundwater source; consumption = 5 sources x fraction 0.5
        a, _ = self.values(f'atotwwgw_monthly_{YEAR}_{YEAR}.nc', 'atotwwgw')
        np.testing.assert_allclose(a[:, cov], 5 / 86400, rtol=1e-6)
        u, _ = self.values(f'adomuse_monthly_{YEAR}_{YEAR}.nc', 'adomuse')
        np.testing.assert_allclose(u[:, cov], 2.5 / 86400, rtol=1e-6)
        # unit record
        rec = support.load_yaml(f'{self.unit}/provenance.yaml')
        self.assertEqual(rec['segment_key'], 'historical_histsoc_default_historical')
        self.assertFalse(rec['source']['accepted_source'])                     # not a production run
        self.assertEqual(len(rec['source']['output_files']), 2)
        self.assertIn('mtime', rec['source']['output_files'][0])
        f0 = [f for f in rec['files'] if f['name'] == f'qtot_daily_{YEAR}_{YEAR}.nc'][0]
        self.assertEqual(f0['identity']['climate_scenario'], 'historical')
        self.assertEqual(f0['identity']['bias_adjustment'], 'era5')
        self.assertIsNone(f0['identity']['model'])

    def test_unit_is_not_overwritten(self):
        self.assertEqual(self.produce(), 0)
        self.assertIn('never overwritten', str(self.produce()))

    def test_recipe_must_match_the_campaign(self):
        self.cfg['variables']['qtot'] = {'terms': ['OUT_RUNOFF']}
        self.assertIn('does not match the campaign', str(self.produce()))


if __name__ == '__main__':
    unittest.main()
