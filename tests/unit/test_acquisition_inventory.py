"""Unit tests for workflow/01_acquisition/build_inventory.py and make_batch_lists.py on a tiny synthetic DKRZ listing:
classification into datasets and transfer priorities (A, B, C), sizes of directory symlinks resolved from the
dereferenced listing, the summary tables, and the split into transfer batches 1-6 with relative paths and expected
sizes. Both scripts run as the user runs them, in temporary directories; nothing outside them is read or written.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import csv, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, '..', '..', 'workflow', '01_acquisition')
ROOT = '/work/bb0820/ISIMIP/ISIMIP4b/'
ATM = 'InputData/climate/atmosphere/bias-adjusted/global/daily'
EC, UK = 'EC-Earth3-ESM-1-1', 'UKESM1-3-LL'


def atm(scen, gcm, var, years):
    return f'{ATM}/{scen}/{gcm}/{gcm.lower()}_r1i1p1f1_era5_{scen}_{var}_global_30arcmin_daily_{years}.nc'


# relative path -> (type, size, mtime, link target, expected priority, expected batch or None)
FILES = {
    atm('esm-hist', EC, 'pr', '2011_2020'): ('f', 100, '2026-01-01', '', 'A', 2),            # QA decade
    atm('esm-scen7-vl', EC, 'tas', '2022_2030'): ('f', 110, '2026-01-02', '', 'A', 2),       # QA decade
    atm('esm-hist', EC, 'tas', '1851_1860'): ('f', 200, '2026-01-03', '', 'A', 3),
    atm('esm-picontrol', EC, 'rsds', '1601_1610'): ('f', 300, '2026-01-04', '', 'A', 4),
    atm('esm-hist', UK, 'huss', '2011_2020'): ('f', 400, '2026-01-05', '', 'A', 5),
    atm('esm-hist', EC, 'prsn', '2011_2020'): ('f', 50, '2026-01-06', '', 'B', 6),
    atm('esm-hist', EC, 'hurs', '2011_2020'): ('f', 60, '2026-01-07', '', 'C', None),
    'InputData/socioeconomic/landuse/histsoc/landuse-totals_histsoc_15arcmin_annual_1850_2021.nc':
        ('f', 70, '2026-02-01', '', 'A', 1),
    'InputData/socioeconomic/landuse/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc':
        ('f', 80, '2026-02-02', '', 'C', None),
    'InputData/socioeconomic/population/histsoc/population_histsoc_national_annual_1850_2021.csv':
        ('f', 5, '2026-02-03', '', 'B', 1),
    'InputData/geo_conditions/soil/soil_30arcmin.nc': ('f', 90, '2026-03-01', '', 'C', 1),   # soil and lakes go to 1
    'InputData/geo_conditions/landseamask': ('l', 4096, '2026-03-02', '../shared/landseamask', 'A', 1),   # directory link
    'SecondaryInputData/climate/atmosphere/x.nc': ('f', 10, '2026-04-01', '', 'C', None),
}
DEREF_SIZE, DEREF_DATE = 12345, '2025-12-31'


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        self.listing_dir = os.path.join(t, 'listing'); os.makedirs(self.listing_dir)
        self.out = os.path.join(t, 'inventory'); self.batches = os.path.join(t, 'batches')
        lines = ['#type\tsize\tmtime\tpath\tlink', f'd\t4096\t2026-01-01\t{ROOT}InputData\t']
        for rel, (typ, size, mtime, link, _, _) in FILES.items():
            if rel.startswith('SecondaryInputData'):
                lines.append('#SECONDARY')
            lines.append(f'{typ}\t{size}\t{mtime}\t{ROOT}{rel}\t{link}')
        lines += ['#OUTPUT', 'OutputData/water_global 3']
        self.listing = os.path.join(self.listing_dir, 'dkrz_find_raw_2026-09-21.tsv')
        with open(self.listing, 'w') as fh:
            fh.write('\n'.join(lines) + '\n')
        with open(os.path.join(self.listing_dir, 'dkrz_deref_2026-09-21.tsv'), 'w') as fh:   # find -L of the links
            fh.write(f'#GEO_DEREF\n{DEREF_SIZE}\t{DEREF_DATE}\t{ROOT}InputData/geo_conditions/landseamask/mask.nc\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, *args):
        r = subprocess.run([sys.executable, os.path.join(STAGE, name), *args], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def inventory(self):
        rc, out = self.run_script('build_inventory.py', '--listing', self.listing, '--out-dir', self.out,
                                  '--date', '2026-09-21')
        self.assertEqual(rc, 0, out)
        self.csv = os.path.join(self.out, 'dkrz_isimip4b_inventory_2026-09-21.csv')
        with open(self.csv) as fh:
            return {r['path'][len(ROOT):]: r for r in csv.DictReader(fh)}

    def test_inventory_rows_and_priorities(self):
        rows = self.inventory()
        self.assertEqual(set(rows), set(FILES))                             # files and links, no directories
        self.assertEqual({p: r['priority'] for p, r in rows.items()}, {p: v[4] for p, v in FILES.items()})
        pr = rows[atm('esm-hist', EC, 'pr', '2011_2020')]
        self.assertEqual((pr['dataset'], pr['subset'], pr['scenario'], pr['gcm_or_res']), ('atmosphere', 'pr', 'esm-hist', EC))
        self.assertEqual(rows['InputData/socioeconomic/landuse/histsoc/landuse-totals_histsoc_15arcmin_annual_1850_2021.nc']
                         ['dataset'], 'landuse-totals')
        link = rows['InputData/geo_conditions/landseamask']
        self.assertEqual((link['type'], link['size_bytes'], link['mtime'], link['link_target']),
                         ('l', str(DEREF_SIZE), DEREF_DATE, '../shared/landseamask'))   # size of the linked files

    def test_summary(self):
        self.inventory()
        with open(os.path.join(self.out, 'dkrz_isimip4b_inventory_2026-09-21.md')) as fh:
            md = fh.read()
        sizes = {p: (DEREF_SIZE if v[0] == 'l' else v[1]) for p, v in FILES.items()}
        for pri in 'ABC':
            n = sum(v[4] == pri for v in FILES.values()); b = sum(sizes[p] for p, v in FILES.items() if v[4] == pri)
            self.assertIn(f'| {pri} | {n} | {b / 1e9:.1f} | {b / 1e12:.2f} |', md)
        self.assertIn(f'| **all** | {len(FILES)} |', md)
        self.assertIn('OutputData/water_global 3', md)                      # the #OUTPUT section is kept as text

    def test_empty_listing_stops(self):
        with open(self.listing, 'w') as fh:
            fh.write('#type\tsize\tmtime\tpath\tlink\n')
        rc, out = self.run_script('build_inventory.py', '--listing', self.listing, '--out-dir', self.out)
        self.assertNotEqual(rc, 0)
        self.assertIn('no file rows found in the listing', out)

    def test_batch_lists(self):
        rows = self.inventory()
        rc, out = self.run_script('make_batch_lists.py', '--inventory', self.csv, '--out-dir', self.batches)
        self.assertEqual(rc, 0, out)
        for k in range(1, 7):
            want = sorted(p for p, v in FILES.items() if v[5] == k)
            with open(os.path.join(self.batches, f'batch_{k}_files.txt')) as fh:
                self.assertEqual(fh.read().splitlines(), want, f'batch {k}')   # relative to the DKRZ root, sorted
            with open(os.path.join(self.batches, f'batch_{k}_expected_sizes.tsv')) as fh:
                lines = fh.read().splitlines()
            self.assertEqual(lines, [f"{rows[p]['size_bytes']}\t{rows[p]['mtime']}\t{p}\t{rows[p]['link_target']}"
                                     for p in want], f'batch {k}')
            if k == 1:                                                  # the link with the size of its files
                self.assertIn(f'{DEREF_SIZE}\t{DEREF_DATE}\tInputData/geo_conditions/landseamask\t../shared/landseamask',
                              lines)


if __name__ == '__main__':
    unittest.main()
