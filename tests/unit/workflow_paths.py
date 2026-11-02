"""Puts repo/workflow on sys.path for the unit tests, so that `from common import ...` in the stage scripts and the
tests works without PYTHONPATH (review 2026-11-01, R20). Every test module that imports workflow code imports this
module first; the tests run with `python -m unittest discover -s tests/unit` from the repository root, which puts
this directory on sys.path."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
WORKFLOW = os.path.join(REPO, 'workflow')
if WORKFLOW not in sys.path:
    sys.path.insert(0, WORKFLOW)
