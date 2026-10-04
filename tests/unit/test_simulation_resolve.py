"""Unit tests for workflow/05_simulation/render/resolve_campaign.py and forcing_years.py.

The resolver tests use the pinned protocol definitions (raw/external/isimip-protocol-4/<commit>/definitions,
small YAML text files) from $ISIMIP4B_WORKDIR and are skipped when they are absent; the rule and failure tests
use small synthetic protocol entries.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import importlib.util, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'render')
sys.path.insert(0, RENDER)
import resolve_campaign as rc   # noqa: E402
import forcing_years as fy      # noqa: E402

PROTOCOL_COMMIT = 'f9be7b0cdf83409315d9fa7da8581cc6fd6ff3e1'
PROTOCOL = os.path.join(os.environ.get('ISIMIP4B_WORKDIR', '/nonexistent'), 'raw', 'external',
                        'isimip-protocol-4', PROTOCOL_COMMIT)
G = 'ec-earth3-esm-1-1'


def campaign(**kw):
    c = {'campaign_id': 'test', 'production': True,
         'protocol': {'path': '', 'commit': PROTOCOL_COMMIT, 'simulation_round': 'ISIMIP4b', 'sector': 'water_global'},
         'gcms': {G: {'climate_input': 'emission-driven'}}, 'experiments': {'all': True}, 'exclusions': [],
         'sensitivity_equivalence': {'2021co2': {'same_as': 'default', 'reason': 'no CO2 response'}},
         'spinup': {'length_years': 300}}
    c.update(kw)
    return c


# expected segments of the 18 water_global experiments for one GCM: segment -> parent
EXPECTED = {
    'picontrol_1850soc_default_spinup': None,
    'picontrol_2021soc_default_spinup': None,
    'picontrol_1850soc_default_pre-industrial': 'picontrol_1850soc_default_spinup',
    'picontrol_histsoc_default_historical': 'picontrol_1850soc_default_pre-industrial',
    'picontrol_1850soc_default_historical': 'picontrol_1850soc_default_pre-industrial',
    'picontrol_2021soc_default_historical': 'picontrol_2021soc_default_spinup',
    'historical_histsoc_default_historical': 'picontrol_1850soc_default_pre-industrial',
    'historical_1850soc_default_historical': 'picontrol_1850soc_default_pre-industrial',
    'historical_2021soc_default_historical': 'picontrol_2021soc_default_spinup',
    'picontrol_2021soc-from-histsoc_default_future': 'picontrol_histsoc_default_historical',
    'picontrol_ssp1vlsoc-noadapt_default_future': 'picontrol_histsoc_default_historical',
    'picontrol_ssp3hsoc-noadapt_default_future': 'picontrol_histsoc_default_historical',
    'picontrol_1850soc_default_future': 'picontrol_1850soc_default_historical',
    'picontrol_2021soc_default_future': 'picontrol_2021soc_default_historical',
    'vl_2021soc-from-histsoc_default_future': 'historical_histsoc_default_historical',
    'vl_ssp1vlsoc-noadapt_default_future': 'historical_histsoc_default_historical',
    'vl_ssp1vlsoc-noadapt_extrasoc_future': 'historical_histsoc_default_historical',
    'vl_1850soc_default_future': 'historical_1850soc_default_historical',
    'vl_2021soc_default_future': 'historical_2021soc_default_historical',
    'h_2021soc-from-histsoc_default_future': 'historical_histsoc_default_historical',
    'h_ssp3hsoc-noadapt_default_future': 'historical_histsoc_default_historical',
    'h_ssp3hsoc-noadapt_extrasoc_future': 'historical_histsoc_default_historical',
    'h_1850soc_default_future': 'historical_1850soc_default_historical',
    'h_2021soc_default_future': 'historical_2021soc_default_historical',
}


@unittest.skipUnless(os.path.isdir(PROTOCOL), 'pinned protocol not available ($ISIMIP4B_WORKDIR)')
class ProtocolResolveTest(unittest.TestCase):
    def test_water_global_experiments(self):
        exps, _, _ = rc.load_protocol(PROTOCOL, 'ISIMIP4b')
        chosen, _, _ = rc.select_experiments(campaign(), exps)
        self.assertEqual(len(chosen), 18)

    def test_eighteen_experiments_segments_and_parents(self):
        segs, chains = rc.resolve(campaign(), PROTOCOL)
        self.assertEqual(len(chains), 18)
        got = {k[len(G) + 1:]: (v.parent[len(G) + 1:] if v.parent else None) for k, v in segs.items()}
        self.assertEqual(got, EXPECTED)

    def test_years(self):
        segs, _ = rc.resolve(campaign(), PROTOCOL)
        y = {k[len(G) + 1:]: (s.start_year, s.end_year) for k, s in segs.items()}
        self.assertEqual(y['picontrol_1850soc_default_spinup'], (1301, 1600))
        self.assertEqual(y['picontrol_2021soc_default_spinup'], (1550, 1849))   # links directly to 1850
        self.assertEqual(y['picontrol_1850soc_default_pre-industrial'], (1601, 1849))
        self.assertEqual(y['historical_histsoc_default_historical'], (1850, 2021))
        self.assertEqual(y['h_ssp3hsoc-noadapt_default_future'], (2022, 2100))

    def test_co2_sensitivity_shares_default_segments(self):
        _, chains = rc.resolve(campaign(), PROTOCOL)
        self.assertEqual(chains[(G, 'h_2021soc_2021co2')], chains[(G, 'h_2021soc_default')])
        self.assertEqual(chains[(G, 'h_1850soc_2021co2')], chains[(G, 'h_1850soc_default')])

    def test_chains(self):
        _, chains = rc.resolve(campaign(), PROTOCOL)
        self.assertEqual([s[len(G) + 1:] for s in chains[(G, 'h_ssp3hsoc-noadapt_default')]],
                         ['picontrol_1850soc_default_spinup', 'picontrol_1850soc_default_pre-industrial',
                          'historical_histsoc_default_historical', 'h_ssp3hsoc-noadapt_default_future'])
        self.assertEqual([s[len(G) + 1:] for s in chains[(G, 'vl_2021soc_default')]],
                         ['picontrol_2021soc_default_spinup', 'historical_2021soc_default_historical',
                          'vl_2021soc_default_future'])

    def test_smoke_restriction(self):
        c = campaign(production=False, experiments={'ids': ['h_ssp3hsoc-noadapt_default']}, spinup=None,
                     restriction={'periods': ['historical'],
                                  'runs': {'smoke2015': {'years': [2015, 2015]},
                                           'smoke2011-2020': {'years': [2011, 2020]}}})
        segs, _ = rc.resolve(c, PROTOCOL)
        self.assertEqual(len(segs), 4)                                     # spin-up, pre-industrial, historical, future
        r = rc.runs(c, segs, 'smoke2015')
        self.assertEqual([x['run_id'] for x in r], [f'{G}_historical_histsoc_default_historical__smoke2015'])
        self.assertEqual((r[0]['start_year'], r[0]['end_year']), (2015, 2015))
        r = rc.runs(c, segs, 'smoke2011-2020')
        self.assertEqual(r[0]['run_id'], f'{G}_historical_histsoc_default_historical__smoke2011-2020')
        with self.assertRaises(rc.CampaignError):
            rc.runs(c, segs, None)                                         # a restricted campaign needs a label
        with self.assertRaises(rc.CampaignError):
            rc.runs(c, segs, 'smoke1990')

    def test_restricted_years_outside_period(self):
        c = campaign(production=False, experiments={'ids': ['h_ssp3hsoc-noadapt_default']},
                     restriction={'periods': ['historical'], 'runs': {'late': {'years': [2020, 2023]}}})
        segs, _ = rc.resolve(c, PROTOCOL)
        with self.assertRaises(rc.CampaignError):
            rc.runs(c, segs, 'late')

    def test_input_alias(self):
        _, _, aliases = rc.load_protocol(PROTOCOL, 'ISIMIP4b')
        self.assertEqual(rc.input_alias(aliases, 'historical', 'emission-driven'), 'esm-hist')
        self.assertEqual(rc.input_alias(aliases, 'picontrol', 'emission-driven'), 'esm-picontrol')
        self.assertEqual(rc.input_alias(aliases, 'h', 'concentration-driven'), 'scen7-h')

    def test_exclusion_needs_reason_and_known_experiment(self):
        exps, _, _ = rc.load_protocol(PROTOCOL, 'ISIMIP4b')
        with self.assertRaises(rc.CampaignError):
            rc.select_experiments(campaign(exclusions=[{'experiment': 'h_ssp3hsoc-noadapt_extrasoc', 'reason': ''}]), exps)
        with self.assertRaises(rc.CampaignError):
            rc.select_experiments(campaign(exclusions=[{'experiment': 'h_nonsense_default', 'reason': 'x'}]), exps)
        chosen, excl, _ = rc.select_experiments(
            campaign(exclusions=[{'experiment': 'h_ssp3hsoc-noadapt_extrasoc', 'reason': 'D06 open'}]), exps)
        self.assertEqual(len(chosen), 17)


class PeriodEntryTest(unittest.TestCase):
    def test_entries(self):
        e = {'specifier': 'x',
             'pre-industrial': 'Does not have to be simulated, spin-up should be based on the 2021\n    DHF (see note).',
             'historical': 'Identical to the similar **historical/histsoc/nofire** run above.',
             'future': {'climate': 'h', 'climate_sens': '2021co2', 'soc': '2021soc'}}
        self.assertEqual(rc.period_entry(e, 'pre-industrial'), ('spinup', '2021soc'))
        self.assertEqual(rc.period_entry(e, 'historical'), ('identical', ('historical', 'histsoc', 'nofire')))
        self.assertEqual(rc.period_entry(e, 'future'), ('explicit', ('h', '2021soc', '2021co2')))

    def test_unknown_entry_fails(self):
        with self.assertRaises(rc.CampaignError):
            rc.period_entry({'specifier': 'x', 'historical': 'something else'}, 'historical')

    def test_conflicting_parent_fails(self):
        segs = {}
        exp = {'specifier': 'a'}
        rc._add(segs, rc.Segment(G, 'historical', 'histsoc', 'default', 'historical', 1850, 2021), 'p1', exp)
        with self.assertRaises(rc.CampaignError):
            rc._add(segs, rc.Segment(G, 'historical', 'histsoc', 'default', 'historical', 1850, 2021), 'p2',
                    {'specifier': 'b'})

    def test_label_only_for_restricted(self):
        segs = {'s': rc.Segment(G, 'historical', 'histsoc', 'default', 'historical', 1850, 2021)}
        with self.assertRaises(rc.CampaignError):
            rc.runs(campaign(), segs, 'x')
        r = rc.runs(campaign(), segs)[0]
        self.assertEqual(r['run_id'], r['segment_id'])                     # production runs carry no label
        self.assertIsNone(r['label'])

    def test_production_campaign_rejects_restriction(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'test.yaml')
            import yaml
            c = campaign(restriction={'periods': ['historical'], 'runs': {}})
            c.update({k: {} for k in rc.CAMPAIGN_REQUIRED if k not in c})
            with open(p, 'w') as fh:
                yaml.safe_dump(c, fh)
            with self.assertRaises(rc.CampaignError):
                rc.load_campaign(p)


class YearMappingTest(unittest.TestCase):
    def test_identity(self):
        m = fy.map_identity_or_constant(range(2011, 2021), range(1850, 2022), constant=False)
        self.assertTrue(all(src == y and rule == 'identity' for y, (src, rule) in m.items()))

    def test_missing_year_of_varying_scenario_fails(self):
        with self.assertRaises(ValueError):
            fy.map_identity_or_constant([2022], range(1850, 2022), constant=False)

    def test_constant_keeps_year_length(self):
        # 1850soc in the pre-industrial period: 1601-1849 -> the first 1850soc year of the same length
        m = fy.map_identity_or_constant(range(1601, 1850), range(1850, 2022), constant=True)
        self.assertEqual(m[1601], (1850, 'constant'))
        self.assertEqual(m[1604], (1852, 'constant'))                      # leap year -> 1852 (leap)
        self.assertEqual(m[1700], (1850, 'constant'))                      # 1700 is not a leap year
        for y, (src, _) in m.items():
            self.assertEqual(fy.days(y), fy.days(src))
        # 2021soc in the historical period: unit 2022-2100
        m = fy.map_identity_or_constant(range(1850, 2022), range(2022, 2101), constant=True)
        self.assertEqual(m[1850], (2022, 'constant'))
        self.assertEqual(m[2020], (2024, 'constant'))
        # covered years stay identity
        m = fy.map_identity_or_constant(range(2020, 2024), range(2022, 2101), constant=True)
        self.assertEqual(m[2022], (2022, 'identity'))

    def test_cycle(self):
        m = fy.map_cycle(range(1301, 1601), (1601, 1700), range(1601, 2101))
        self.assertEqual(m[1301], (1601, 'cycle'))
        self.assertEqual(m[1400], (1700, 'cycle'))                         # both 365 days
        self.assertEqual(m[1304], (1604, 'cycle'))
        self.assertEqual(m[1600], (1604, 'cycle'))                         # 1600 leap, 1700 not: next leap year
        for y, (src, _) in m.items():
            self.assertEqual(fy.days(y), fy.days(src))
            self.assertTrue(1601 <= src <= 1700)

    def test_cycle_window_must_be_covered(self):
        with self.assertRaises(ValueError):
            fy.map_cycle([1500], (1590, 1610), range(1601, 2101))

    def test_view_links(self):
        with tempfile.TemporaryDirectory() as d:
            unit = os.path.join(d, 'forcing', 'landuse', '1850soc'); os.makedirs(unit)
            for y in (1850, 1852):
                open(os.path.join(unit, f'coverage_1850soc_{y}.nc'), 'w').close()
            m = fy.map_identity_or_constant([1601, 1604], [1850, 1852], constant=True)
            view = os.path.join(d, 'runs', 'c', 'r', 'forcing')
            n = fy.build_view(view, [(f'landuse/coverage_1850soc_{y}.nc', os.path.join(unit, f'coverage_1850soc_{s}.nc'))
                                     for y, (s, _) in m.items()])
            self.assertEqual(n, 2)
            link = os.path.join(view, 'landuse', 'coverage_1850soc_1604.nc')
            self.assertTrue(os.path.islink(link) and not os.path.isabs(os.readlink(link)))
            self.assertEqual(os.path.realpath(link), os.path.realpath(os.path.join(unit, 'coverage_1850soc_1852.nc')))
            fy.build_view(view, [('landuse/coverage_1850soc_1604.nc', os.path.join(unit, 'coverage_1850soc_1852.nc'))])
            with self.assertRaises(FileExistsError):                       # an existing link is never redirected
                fy.build_view(view, [('landuse/coverage_1850soc_1604.nc', os.path.join(unit, 'coverage_1850soc_1850.nc'))])
            with self.assertRaises(FileNotFoundError):                     # nothing is linked to a missing file
                fy.build_view(view, [('landuse/coverage_1850soc_1605.nc', os.path.join(unit, 'missing.nc'))])
            self.assertFalse(os.path.lexists(os.path.join(view, 'landuse', 'coverage_1850soc_1605.nc')))


if __name__ == '__main__':
    unittest.main()
