"""Regression tests for the grid-relation and dz cache of downscale_climate.py (code review of 2026-10-05, #11).

Two jobs that build the same cache at the same time must not share a temporary file, the cache is published by an
atomic rename that tolerates a concurrent winner, and a cache file is validated after reading (a damaged or
mismatching file is rebuilt, never used). The static inputs are replaced by small synthetic grids.

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import glob, importlib.util, os, tempfile, unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', '..', 'workflow', '04_forcing', 'climate', 'downscale_climate.py')
spec = importlib.util.spec_from_file_location('downscale_climate_cache', SRC)
dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)

CLAT = CLON = np.array([-0.25, 0.25, 0.75])            # 0.5 degree centres, ascending
FINE = 1 / 24 + np.arange(6) / 12                      # 6 x 6 subdivision of the cell centred at 0.25
HASHES = {p: ('md5', f'sha256-{p}') for p in ('dom', 'bundle', 'era5')}


class WeightsCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.W = self.tmp.name
        mask = np.ones((6, 6), bool)
        self.patches = [mock.patch.object(dc, 'isimip_grid', lambda p: (CLAT, CLON)),
                        mock.patch.object(dc, 'read_domain', lambda p: (FINE, FINE, mask, np.ones((6, 6)))),
                        mock.patch.object(dc, 'read_elev', lambda *a: np.full((6, 6), 100.0)),
                        mock.patch.object(dc, 'era5_height_05', lambda *a: np.full((3, 3), 40.0))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def build(self):
        return dc.static_reference(self.W, 'isimip', 'dom', 'bundle', 'era5', HASHES)

    def files(self):
        return sorted(os.path.basename(f) for f in glob.glob(f'{self.W}/{dc.SCRATCH}/weights/*'))

    def test_concurrent_builders(self):
        """A second job builds and publishes the same cache while the first is between writing and publishing."""
        real_savez = np.savez; state = {'raced': False}

        def racing_savez(path, *args, **kw):
            real_savez(path, *args, **kw)
            if not state['raced']:
                state['raced'] = True
                self.assertTrue(np.allclose(self.build()[7], 60.0))     # the other job, complete
        with mock.patch.object(dc.np, 'savez', racing_savez):
            dz = self.build()[7]
        self.assertTrue(state['raced'])
        self.assertTrue(np.allclose(dz, 60.0))
        self.assertEqual(len(self.files()), 1, self.files())            # one cache, no temporary file left

    def test_damaged_cache_is_rebuilt(self):
        cache = self.build()[9]
        with open(cache, 'wb') as fh:
            fh.write(b'not a numpy archive')
        r = self.build(); dz, cache2 = r[7], r[9]
        self.assertEqual(cache2, cache)
        self.assertTrue(np.allclose(dz, 60.0))

    def test_mismatching_cache_is_rebuilt(self):
        cache = self.build()[9]
        z = dict(np.load(cache)); z['dz'] = np.zeros((2, 2))          # right key, wrong content
        np.savez(cache[:-4], **z)
        dz = self.build()[7]
        self.assertEqual(dz.shape, (6, 6))
        self.assertTrue(np.allclose(dz, 60.0))


if __name__ == '__main__':
    unittest.main()
