"""Unit tests for render_run.check_unit_parameters (review P3 B3): a run reads forcing units only when they were made
on the campaign's domain file and, for climate, with the elevation of the campaign's parameter file (the natural
bundle the assembled bundle was built from); synthetic workdir in a temporary directory.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import hashlib, os, sys, tempfile, unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow', '05_simulation', 'render'))
import render_run as rr   # noqa: E402

PSET = 'parameters/candidates/test-set'
DOMAIN = f'{PSET}/domain/domain.nc'
NATURAL = f'{PSET}/bundle/natural.nc'
BUNDLE = f'{PSET}/bundle/assembled.nc'


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class UnitParametersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        for rel, text in ((DOMAIN, 'domain'), (NATURAL, 'natural'), (BUNDLE, 'assembled')):
            os.makedirs(os.path.dirname(f'{W}/{rel}'), exist_ok=True)
            with open(f'{W}/{rel}', 'w') as fh:
                fh.write(text)
        self.write(f'{PSET}/bundle/provenance.yaml', {'object': BUNDLE, 'input_sha256': {'natural_bundle': sha('natural')}})
        self.params = {'domain': {'path': DOMAIN}, 'parameters': {'path': BUNDLE}}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, data):
        os.makedirs(os.path.dirname(f'{self.W}/{rel}'), exist_ok=True)
        with open(f'{self.W}/{rel}', 'w') as fh:
            yaml.safe_dump(data, fh)

    def units(self, climate_domain='domain', climate_bundle='natural', landuse_domain='domain', water_domain='domain'):
        self.write('forcing/climate/g/a/prec/provenance.yaml', {'input_sha256': {
            DOMAIN: sha(climate_domain), NATURAL: sha(climate_bundle), 'raw/ISIMIP4b/x.nc': sha('raw')}})
        self.write('forcing/landuse/histsoc/provenance.yaml', {'input_sha256': {'domain': sha(landuse_domain),
                                                                                'landuse-15crops': sha('x')}})
        self.write('forcing/water_use/histsoc/provenance.yaml', {'input_sha256': {DOMAIN: sha(water_domain)}})
        return {u: {'forcing_unit': u} for u in ('climate/g/a/prec', 'landuse/histsoc', 'water_use/histsoc')}

    def test_same_parameter_files_pass(self):
        rr.check_unit_parameters(self.W, self.params, self.units())

    def test_other_domain_stops(self):
        for kw in ({'climate_domain': 'other'}, {'landuse_domain': 'other'}, {'water_domain': 'other'}):
            with self.subTest(**kw):
                with self.assertRaises(rr.RenderError):
                    rr.check_unit_parameters(self.W, self.params, self.units(**kw))

    def test_other_elevation_stops(self):
        with self.assertRaises(rr.RenderError):
            rr.check_unit_parameters(self.W, self.params, self.units(climate_bundle='other natural bundle'))

    def test_natural_bundle_as_parameter_file(self):
        """A campaign that uses the natural bundle itself: its own sha256 is the elevation source."""
        params = {'domain': {'path': DOMAIN}, 'parameters': {'path': NATURAL}}
        rr.check_unit_parameters(self.W, params, self.units())

    def test_unit_without_domain_record_stops(self):
        units = self.units()
        self.write('forcing/water_use/histsoc/provenance.yaml', {'input_sha256': {}})
        with self.assertRaises(rr.RenderError):
            rr.check_unit_parameters(self.W, self.params, units)


if __name__ == '__main__':
    unittest.main()
