"""Workdir resolution: the sibling workdir is found only through ISIMIP4B_WORKDIR (environments/README.md).

Used by every producer, verifier and submit script; paths below the workdir follow docs/directory-contracts.md.
"""
import os
import sys

ENV = 'ISIMIP4B_WORKDIR'


def root():
    """Absolute path of the workdir; stops with a message when ISIMIP4B_WORKDIR is not set."""
    w = os.environ.get(ENV)
    if not w:
        sys.exit(f'set {ENV}')
    return w


def logs(stage, w=None):
    """Directory of the job records of a non-simulation stage, logs/<stage>/ (contract, `logs/`)."""
    return f'{w or root()}/logs/{stage}'
