"""File checksums (SHA-256 for provenance records, MD5 for comparison with upstream manifests).

Files are read in blocks of BLOCK bytes, so that multi-gigabyte forcing files never sit in memory at once.
"""
import hashlib

BLOCK = 1 << 24     # 16 MiB


def _digest(path, *algorithms):
    hs = [hashlib.new(a) for a in algorithms]
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(BLOCK), b''):
            for h in hs:
                h.update(b)
    return tuple(h.hexdigest() for h in hs)


def sha256(path):
    return _digest(path, 'sha256')[0]


def md5(path):
    return _digest(path, 'md5')[0]


def file_hashes(path):
    """(md5, sha256) of a file in one read pass."""
    return _digest(path, 'md5', 'sha256')
