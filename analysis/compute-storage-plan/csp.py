"""Shared definitions of the compute-storage-plan analysis: paths, the smoke runs used as measurements, constants.

Imported by measure_files.py, plan.py and submit.py of analysis/compute-storage-plan/.
"""
import os

TASK = 'compute-storage-plan'
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

# smoke runs whose records are the measurements (workdir-relative)
SMOKE_RUNS = {
    'smoke2015': 'runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2015',
    'smoke2011-2020': 'runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2011-2020',
}
# the run whose files are measured by measure_files.py (complete, one model year)
SIZE_RUN = 'smoke2015'
SIZE_FILES = {'daily': 'output/daily.2015-01-01.nc', 'monthly': 'output/monthly.2015-01.nc',
              'state': 'states/state.20160101_00000.nc'}


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or exit('set ISIMIP4B_WORKDIR')


def products():
    return f'{workdir()}/analysis/{TASK}'


def tables():
    d = f'{products()}/tables'
    os.makedirs(d, exist_ok=True)
    return d


def figures():
    d = f'{products()}/figures'
    os.makedirs(d, exist_ok=True)
    return d


def scratch():
    d = f'{workdir()}/scratch/{TASK}'
    os.makedirs(d, exist_ok=True)
    return d
