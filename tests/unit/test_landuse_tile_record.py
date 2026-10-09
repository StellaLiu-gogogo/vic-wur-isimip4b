"""Unit tests for the link between the vegetation component's tile union and the land-use forcing a run reads:
verify_vegetation.py records the land-use files (with sha256) its forcing_tiles check read, and render_run.py stops
when the land-use files of a run are not among them. Synthetic workdirs in temporary directories.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import json, os, sys, tempfile, unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, '..', '..', 'workflow')
sys.path.insert(0, os.path.join(WF, '03_parameters', 'vegetation'))
sys.path.insert(0, os.path.join(WF, '05_simulation', 'render'))
import verify_vegetation as vv   # noqa: E402
import render_run as rr          # noqa: E402

PSET = 'parameters/candidates/test-set'
BUNDLE = f'{PSET}/bundle/bundle_16class.nc'
VEG = f'{PSET}/vegetation/vegetation_16class.nc'


def write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        yaml.safe_dump(data, fh)


class Workdir(unittest.TestCase):
    """Five land-use units of two yearly files each, a bundle built from a vegetation component, and its QC."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = W = self.tmp.name
        self.sha = {}
        for soc in vv.bv.SOC:
            files = []; os.makedirs(self.unit(soc))
            for y in (2015, 2016):
                name = f'coverage_{soc}_{y}.nc'
                open(os.path.join(self.unit(soc), name), 'w').close()
                files.append({'path': name, 'sha256': f'{soc}-{y}'})
                self.sha[f'forcing/landuse/{soc}/{name}'] = f'{soc}-{y}'
            write_yaml(f'{self.unit(soc)}/provenance.yaml', {'forcing_unit': f'landuse/{soc}', 'files': files})
        write_yaml(f'{W}/{PSET}/bundle/provenance.yaml', {'object': BUNDLE, 'inputs': {'vegetation_component': VEG}})
        write_yaml(f'{W}/{PSET}/vegetation/provenance.yaml',
                   {'object': f'{PSET}/vegetation', 'qc': {'status': 'passed', 'evidence': f'qc/{PSET}/vegetation'}})
        self.write_qc(dict(self.sha))
        self.params = {'parameters': {'path': BUNDLE}}

    def tearDown(self):
        self.tmp.cleanup()

    def unit(self, soc):
        return f'{self.W}/forcing/landuse/{soc}'

    def write_qc(self, checked):
        p = f'{self.W}/qc/{PSET}/vegetation/reports/verify.json'
        os.makedirs(os.path.dirname(p), exist_ok=True)
        forcing = {'files': 10, 'violations': 0, 'status': 'passed'}
        if checked is not None:
            forcing['checked_files'] = checked
        with open(p, 'w') as fh:
            json.dump({'checked_at': 't', 'checks': {'forcing_tiles': forcing}}, fh)

    def run_units(self, soc='histsoc', years=(2015, 2016), sha=None):
        """The record forcing_plan() makes of the land-use unit a run reads."""
        files = {f'coverage_{soc}_{y}.nc': {'path': f'forcing/landuse/{soc}/coverage_{soc}_{y}.nc',
                                            'sha256': (sha or {}).get(y, f'{soc}-{y}')} for y in years}
        return {f'landuse/{soc}': {'forcing_unit': f'landuse/{soc}', 'files': files}}


class VerifierRecordTest(Workdir):
    def test_records_every_file_read_with_its_sha256(self):
        files, checked = vv.landuse_files(self.W)
        self.assertEqual(len(files), 10)
        self.assertEqual(checked, self.sha)


class RenderCheckTest(Workdir):
    def test_checked_files_pass(self):
        rr.check_landuse_tiles(self.W, self.params, self.run_units(), 'histsoc')

    def test_changed_unit_stops(self):
        with self.assertRaises(rr.RenderError):
            rr.check_landuse_tiles(self.W, self.params, self.run_units(sha={2016: 'regenerated'}), 'histsoc')

    def test_qc_without_record_stops(self):
        self.write_qc(None)                                            # QC written before the files were recorded
        with self.assertRaises(rr.RenderError):
            rr.check_landuse_tiles(self.W, self.params, self.run_units(), 'histsoc')

    def test_vegetation_not_accepted_stops(self):
        write_yaml(f'{self.W}/{PSET}/vegetation/provenance.yaml',
                   {'object': f'{PSET}/vegetation', 'qc': {'status': 'failed', 'evidence': f'qc/{PSET}/vegetation'}})
        with self.assertRaises(rr.RenderError):
            rr.check_landuse_tiles(self.W, self.params, self.run_units(), 'histsoc')

    def test_bundle_without_vegetation_record_stops(self):
        write_yaml(f'{self.W}/{PSET}/bundle/provenance.yaml', {'object': 'parameters/candidates/test-set/bundle/other.nc'})
        with self.assertRaises(rr.RenderError):
            rr.check_landuse_tiles(self.W, self.params, self.run_units(), 'histsoc')


if __name__ == '__main__':
    unittest.main()
