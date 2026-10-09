"""Unit tests for workflow/01_acquisition/transfer_batch.sh against a local stand-in for DKRZ: a temporary "remote"
directory reached through a stand-in `ssh` that runs the remote command on this machine (so the real rsync protocol
is used), and a wrapper around rsync that can emulate an interrupted transfer or an upstream change during the
transfer. Nothing outside the temporary directory is read or written; no network access. MD5SUMS (accepted files,
`<md5>  <path>`, readable by `md5sum -c` in the destination root) is checked too.

Run from the repository root in the isimip4b environment:
    python -m unittest discover -s tests/unit -v
"""
import hashlib, os, shutil, stat, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', '..', 'workflow', '01_acquisition', 'transfer_batch.sh')
REAL_RSYNC = shutil.which('rsync')

SSH = r'''#!/bin/bash
# stand-in for ssh: drop the options and the host, run the remote command here
while [ $# -gt 0 ]; do case $1 in -o|-l|-p|-i) shift 2;; -*) shift;; *) break;; esac; done
shift
exec bash -c "$*"
'''
RSYNC = r'''#!/bin/bash
# wrapper around rsync: FAKE_INTERRUPT=<path> leaves the first 1000 bytes of that file at the destination and stops
# like an interrupted rsync --partial (exit 20); FAKE_TOUCH=<remote file> changes its mtime after the transfer
if [ -n "${FAKE_INTERRUPT:-}" ]; then
  src=${@: -2:1}; dest=${@: -1}
  mkdir -p "$dest/$(dirname "$FAKE_INTERRUPT")"
  head -c 1000 "${src#*:}/$FAKE_INTERRUPT" > "$dest/$FAKE_INTERRUPT"
  exit 20
fi
"$REAL_RSYNC" "$@"; rc=$?
if [ -n "${FAKE_TOUCH:-}" ]; then touch -d '2001-01-01 00:00:00' "$FAKE_TOUCH"; fi
exit $rc
'''


@unittest.skipUnless(REAL_RSYNC, 'rsync not available')
class TransferTest(unittest.TestCase):
    FILES = {'a/clean.nc': b'c' * 3000, 'a/big.nc': bytes(range(256)) * 400, 'b/sized.nc': b'123456789'}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = self.tmp.name
        self.remote = os.path.join(t, 'remote'); self.W = os.path.join(t, 'workdir')
        self.dst = os.path.join(self.W, 'raw', 'ISIMIP4b'); self.mandir = os.path.join(t, 'manifest')
        self.bin = os.path.join(t, 'bin'); os.makedirs(self.bin)
        for name, text in (('ssh', SSH), ('rsync', RSYNC)):
            p = os.path.join(self.bin, name)
            with open(p, 'w') as fh:
                fh.write(text)
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        for rel, data in self.FILES.items():
            p = os.path.join(self.remote, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as fh:
                fh.write(data)

    def tearDown(self):
        self.tmp.cleanup()

    def batch(self, files, approved=None):
        """Write batch_t_files.txt and batch_t_expected_sizes.tsv (size, mtime, path, link target)."""
        approved = approved or {}
        lst = os.path.join(self.tmp.name, 'batch_t_files.txt')
        with open(lst, 'w') as fh:
            fh.write(''.join(f'{p}\n' for p in files))
        with open(os.path.join(self.tmp.name, 'batch_t_expected_sizes.tsv'), 'w') as fh:
            for p in files:
                fh.write(f'{approved.get(p, len(self.FILES[p]))}\t2026-10-01\t{p}\t\n')
        return lst

    def run_batch(self, lst, **env):
        e = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}', ISIMIP4B_WORKDIR=self.W, REAL_RSYNC=REAL_RSYNC,
                 **env)
        r = subprocess.run(['bash', SCRIPT, 't', lst, self.mandir, 'dkrz', self.remote, self.dst], env=e,
                           capture_output=True, text=True)
        rows = {}
        man = os.path.join(self.mandir, 'transfer_manifest_batch_t.txt')
        if os.path.exists(man):
            with open(man) as fh:
                head = fh.readline().lstrip('#').rstrip('\n').split('\t')
                for line in fh:
                    row = dict(zip(head, line.rstrip('\n').split('\t')))
                    rows[os.path.relpath(row['target'], self.dst)] = row
        return r.returncode, rows, r.stdout + r.stderr

    def raw(self, rel):
        p = os.path.join(self.dst, rel)
        if not os.path.exists(p):
            return None
        with open(p, 'rb') as fh:
            return fh.read()

    def test_clean_batch(self):
        rc, rows, out = self.run_batch(self.batch(['a/clean.nc', 'a/big.nc']))
        self.assertEqual(rc, 0, out)
        self.assertEqual({p: r['status'] for p, r in rows.items()}, {'a/clean.nc': 'OK', 'a/big.nc': 'OK'})
        self.assertEqual(self.raw('a/big.nc'), self.FILES['a/big.nc'])

    def test_interrupted_file_resumes(self):
        lst = self.batch(['a/big.nc'])
        rc, _, out = self.run_batch(lst, FAKE_INTERRUPT='a/big.nc')
        self.assertNotEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.dst, 'a/big.nc')), 'an incomplete file is in the raw area')
        rc, rows, out = self.run_batch(lst)
        self.assertEqual(rc, 0, out)
        self.assertEqual(rows['a/big.nc']['status'], 'OK')
        self.assertEqual(self.raw('a/big.nc'), self.FILES['a/big.nc'])

    def test_approved_size_differs(self):
        rc, rows, out = self.run_batch(self.batch(['a/clean.nc', 'b/sized.nc'], approved={'b/sized.nc': 5}))
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(rows['a/clean.nc']['status'], 'OK')
        self.assertNotEqual(rows['b/sized.nc']['status'], 'OK')
        self.assertIn('approved size', rows['b/sized.nc'].get('reason', ''))
        self.assertIsNone(self.raw('b/sized.nc'))

    def test_upstream_change_during_transfer(self):
        rc, rows, out = self.run_batch(self.batch(['a/clean.nc']), FAKE_TOUCH=os.path.join(self.remote, 'a/clean.nc'))
        self.assertNotEqual(rc, 0, out)
        self.assertNotEqual(rows['a/clean.nc']['status'], 'OK')
        self.assertIn('changed during the transfer', rows['a/clean.nc'].get('reason', ''))
        self.assertIsNone(self.raw('a/clean.nc'))

    def test_existing_raw_file_is_kept(self):
        p = os.path.join(self.dst, 'a', 'clean.nc'); os.makedirs(os.path.dirname(p))
        with open(p, 'wb') as fh:
            fh.write(b'x' * 3000)                                      # same size, other content
        rc, rows, out = self.run_batch(self.batch(['a/clean.nc']))
        self.assertNotEqual(rc, 0, out)
        self.assertNotEqual(rows['a/clean.nc']['status'], 'OK')
        self.assertEqual(self.raw('a/clean.nc'), b'x' * 3000)


    def md5sums(self):
        p = os.path.join(self.mandir, 'MD5SUMS')
        if not os.path.exists(p):
            return []
        with open(p) as fh:
            return fh.read().splitlines()

    def test_md5sums_lists_accepted_files(self):
        rc, rows, out = self.run_batch(self.batch(['b/sized.nc', 'a/clean.nc', 'a/big.nc'], approved={'b/sized.nc': 5}))
        self.assertNotEqual(rc, 0, out)                                 # b/sized.nc is not accepted
        expected = [f'{hashlib.md5(self.FILES[p]).hexdigest()}  {p}' for p in ('a/big.nc', 'a/clean.nc')]
        self.assertEqual(self.md5sums(), expected)                      # accepted files only, sorted by path
        self.assertEqual(rows['a/big.nc']['md5_local'], hashlib.md5(self.FILES['a/big.nc']).hexdigest())
        r = subprocess.run(['md5sum', '-c', os.path.join(self.mandir, 'MD5SUMS')], cwd=self.dst,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_md5sums_without_accepted_files(self):
        rc, _, out = self.run_batch(self.batch(['a/big.nc']), FAKE_INTERRUPT='a/big.nc')
        self.assertNotEqual(rc, 0, out)
        self.assertEqual(self.md5sums(), [])

    def test_md5sums_after_resumed_batch(self):
        lst = self.batch(['a/clean.nc', 'a/big.nc'])
        self.run_batch(lst, FAKE_INTERRUPT='a/big.nc')
        rc, _, out = self.run_batch(lst)
        self.assertEqual(rc, 0, out)
        self.assertEqual([l.split('  ', 1)[1] for l in self.md5sums()], ['a/big.nc', 'a/clean.nc'])

    # Review of 2026-10-07, finding P3 (not fixed in task J): MD5SUMS is opened for appending, so running a batch
    # again (e.g. to re-verify it) appends a second line for every file accepted again. Remove the decorator when
    # transfer_batch.sh writes each accepted file once.
    def test_md5sums_once_per_file_after_rerun(self):
        lst = self.batch(['a/clean.nc', 'a/big.nc'])
        for _ in range(2):
            rc, _, out = self.run_batch(lst)
            self.assertEqual(rc, 0, out)
        self.assertEqual([l.split('  ', 1)[1] for l in self.md5sums()], ['a/big.nc', 'a/clean.nc'])

if __name__ == '__main__':
    unittest.main()
