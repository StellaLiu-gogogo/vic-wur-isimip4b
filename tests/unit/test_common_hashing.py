"""Unit tests for workflow/common/hashing.py (against hashlib on whole files, across the block boundary).

Run from the repository root in the isimip4b environment (PYTHONPATH including workflow/):
    python -m unittest discover -s tests/unit -v
"""
import hashlib, os, tempfile, unittest
from unittest import mock

from common import hashing


class HashingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, data):
        p = os.path.join(self.tmp.name, 'f')
        with open(p, 'wb') as fh:
            fh.write(data)
        md5, sha = hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest()
        self.assertEqual(hashing.sha256(p), sha)
        self.assertEqual(hashing.md5(p), md5)
        self.assertEqual(hashing.file_hashes(p), (md5, sha))

    def test_empty_and_small(self):
        self.check(b'')
        self.check(b'VIC-WUR')

    def test_several_blocks(self):
        with mock.patch.object(hashing, 'BLOCK', 7):        # 3 full blocks and a partial one
            self.check(bytes(range(25)))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            hashing.sha256(os.path.join(self.tmp.name, 'missing'))


if __name__ == '__main__':
    unittest.main()
