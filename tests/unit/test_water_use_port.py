"""Port test of the water-use split against the sibling project vic_parameter (D05 item 6), and a comparison of
the sibling's population proxy with the ISIMIP4b population used by the units.

With the sibling's population proxy (Yan et al. 2022, outputs/water_use/sectors/v1.1.0_20260818/population/)
as the weight, the split of the ISIMIP3a 2015 domestic withdrawal by downscale_water_use.py must equal the
sibling's product domestic_demand_5min_2015.nc within float32 round-off. The proxy is used only here, never in a
forcing unit. The test reads production-size data (about 2 GB of memory) and writes nothing; it is skipped unless
ISIMIP4B_PORT_TEST=1. Run it on a compute node:

    ISIMIP4B_PORT_TEST=1 srun -p main -c 1 --mem 8G python -m unittest discover -s tests/unit -p test_water_use_port.py -v
"""
import os, unittest

import numpy as np
import netCDF4 as nc

from test_water_use_forcing import load_producer   # noqa: E402

SIBLING = '/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/outputs/water_use/sectors/v1.1.0_20260818'


@unittest.skipUnless(os.environ.get('ISIMIP4B_PORT_TEST') == '1' and os.path.isdir(SIBLING),
                     'port test: set ISIMIP4B_PORT_TEST=1 (needs the vic_parameter outputs)')
class PortTest(unittest.TestCase):
    def test_domestic_2015_equals_vic_parameter(self):
        W = os.environ['ISIMIP4B_WORKDIR']
        wu = load_producer(W)
        dom = nc.Dataset(f'{W}/' + wu.DOMAIN.format(status='candidates', pset='vic-global-5arcmin-version-a'))
        mask = dom['mask'][:].filled(0) == 1; area = np.asarray(dom['area'][:].filled(0), 'f8'); dom.close()
        proxy = np.asarray(nc.Dataset(f'{SIBLING}/population/population_5min_2015.nc')['population'][:].filled(np.nan), 'f8')
        spec = wu.source_spec('histsoc', 'dom', 2015)
        ww, _ = wu.read_source(f'{W}/{spec["ww"][0]}', spec['ww'][1], 2015)
        child, cls, rep = wu.split_volume(ww, proxy, mask)
        ours = wu.volume_to_mm_per_day(child, area, 2015).astype('f4')      # 2015 has 365 days, as the sibling
        theirs = nc.Dataset(f'{SIBLING}/histsoc/domestic/demand/domestic_demand_5min_2015.nc')['demand'][0].filled(np.nan)
        a, b = ours[mask].astype('f8'), np.asarray(theirs, 'f8')[mask]
        self.assertTrue(np.isfinite(b).all())
        diff = np.abs(a - b)
        tol = 2 * np.finfo(np.float32).eps * np.maximum(np.abs(b), 1e-30)
        print(f'\nport test: {mask.sum()} active cells, max |diff| {diff.max():.3e} mm/day, max relative '
              f'{(diff[b > 0] / b[b > 0]).max():.3e}, cells outside float32 round-off {int((diff > tol).sum())}, '
              f'totals {rep["child_km3"]:.4f} km3 (ours, float64)')
        self.assertEqual(int((diff > tol).sum()), 0)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(os.environ.get('ISIMIP4B_PORT_TEST') == '1' and os.path.isdir(SIBLING),
                     'population comparison: set ISIMIP4B_PORT_TEST=1 (needs the vic_parameter outputs)')
class PopulationComparisonTest(unittest.TestCase):
    """Yan et al. (2022) population (the sibling's proxy) versus the ISIMIP4b histsoc population used by the units.

    Compared on the active VIC cells for 2000, 2010, 2015 and 2020: global totals, agreement of the 0.5 deg
    parent totals, population present in one dataset but not in the other, and how much of the 2015 domestic and
    industrial demand ends up in different 5' cells when one proxy replaces the other (half the sum of absolute
    child differences). The numbers are printed; the assertions only check that both datasets are usable and
    that their global totals agree within 10 %."""

    def test_yan_versus_isimip4b(self):
        W = os.environ['ISIMIP4B_WORKDIR']
        wu = load_producer(W)
        dom = nc.Dataset(f'{W}/' + wu.DOMAIN.format(status='candidates', pset='vic-global-5arcmin-version-a'))
        lat = np.asarray(dom['lat'][:], 'f8'); mask = dom['mask'][:].filled(0) == 1; dom.close()
        print('\nyear  yan_bn  isimip4b_bn  ratio  parent_corr_log  isimip4b_pop_where_yan_0  yan_pop_where_isimip4b_0'
              '  parents_only_yan  parents_only_isimip4b')
        for year in (2000, 2010, 2015, 2020):
            yan = np.asarray(nc.Dataset(f'{SIBLING}/population/population_5min_{year}.nc')['population'][:].filled(np.nan), 'f8')
            yan = np.where(mask & np.isfinite(yan), np.maximum(yan, 0.0), 0.0)
            isi, _ = wu.read_population('histsoc', year, lat)
            isi = np.where(mask, isi, 0.0)
            self.assertTrue(np.isfinite(isi).all() and (isi >= 0).all())
            ty, ti = yan.sum(), isi.sum()
            py, pi_ = wu.blocks(yan).sum(axis=1), wu.blocks(isi).sum(axis=1)
            both = (py > 0) & (pi_ > 0)
            corr = np.corrcoef(np.log10(py[both]), np.log10(pi_[both]))[0, 1]
            print(f'{year}  {ty / 1e9:6.3f}  {ti / 1e9:11.3f}  {ti / ty:5.3f}  {corr:15.3f}  '
                  f'{isi[yan == 0].sum() / ti * 100:23.2f}%  {yan[isi == 0].sum() / ty * 100:23.2f}%  '
                  f'{int(((py > 0) & (pi_ == 0)).sum()):16d}  {int(((pi_ > 0) & (py == 0)).sum()):21d}')
            self.assertLess(abs(ti / ty - 1), 0.10)
            if year == 2015:
                for s in ('dom', 'ind'):
                    spec = wu.source_spec('histsoc', s, 2015)
                    ww, _ = wu.read_source(f'{W}/{spec["ww"][0]}', spec['ww'][1], 2015)
                    a, _, ra = wu.split_volume(ww, yan, mask)
                    b, _, rb = wu.split_volume(ww, isi, mask)
                    moved = 0.5 * np.abs(a - b).sum() / b.sum()
                    pm = 0.5 * np.abs(wu.blocks(a).sum(axis=1) - wu.blocks(b).sum(axis=1)).sum() / b.sum()
                    print(f'      2015 {s}: {moved * 100:.1f} % of the volume sits in different 5\' cells '
                          f'(parent totals differ by {pm * 100:.2e} %); even-split parents yan {ra["parents_even_split"]} '
                          f'({ra["even_split_km3"]:.3f} km3), isimip4b {rb["parents_even_split"]} ({rb["even_split_km3"]:.3f} km3)')
