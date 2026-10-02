"""Shared definitions of the land-use visualisation analysis: paths, 15' grid, class groups, regions, frame years.

Imported by build_cache.py and the plotting scripts of analysis/landuse-visualization/.
"""
import os

import numpy as np

TASK = 'landuse-visualization'
SOC = ('histsoc', '1850soc', '2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt')
FUTURES = ('2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt')
FIRST_YEAR = {'histsoc': 1850, '1850soc': 1850, '2021soc': 2022, 'ssp1vlsoc-noadapt': 2022, 'ssp3hsoc-noadapt': 2022}
LAST_YEAR = {s: 2021 if FIRST_YEAR[s] == 1850 else 2100 for s in SOC}
ISIMIP_TAG = {'histsoc': 'histsoc', '1850soc': '1850soc', '2021soc': '2021soc', 'ssp1vlsoc-noadapt': 'ssp1vl',
              'ssp3hsoc-noadapt': 'ssp3h'}

# class groups (D04): VIC 0-based class indices; the ISIMIP side is defined in build_cache.isimip_groups()
GROUPS = ('urban', 'rainfed', 'irrigated', 'paddy', 'natural', 'barren')
VIC_GROUP = {'urban': [12], 'rainfed': [11], 'irrigated': [13, 14], 'paddy': [14], 'natural': list(range(11)), 'barren': [15]}
LABEL = {'urban': 'urban', 'rainfed': 'rainfed crop', 'irrigated': 'irrigated crop', 'paddy': 'irrigated paddy',
         'natural': 'natural vegetation', 'barren': 'barren'}

# regions: (south, north, west, east) in degrees; a 15' cell belongs to a region when its centre is inside
REGIONS = {
    'europe': (35.0, 71.0, -10.0, 40.0),
    'south_asia': (6.0, 36.0, 66.0, 92.0),
    'east_china': (20.0, 42.0, 105.0, 123.0),
    'us_midwest_high_plains': (33.0, 49.0, -105.0, -85.0),
    'brazil_cerrado_amazon_arc': (-25.0, -2.0, -65.0, -40.0),
    'sahel_west_central_africa': (5.0, 18.0, -18.0, 40.0),
}
REGION_LABEL = {'global': 'global', 'europe': 'Europe', 'south_asia': 'South Asia', 'east_china': 'East China',
                'us_midwest_high_plains': 'US Midwest / High Plains',
                'brazil_cerrado_amazon_arc': 'Brazil cerrado-Amazon arc', 'sahel_west_central_africa': 'Sahel / West-Central Africa'}

# frame years of the maps: histsoc 1850-2020 every 10 years (+2021 as baseline), futures 2030-2100
HIST_FRAMES = list(range(1850, 2021, 10))
FUT_FRAMES = list(range(2030, 2101, 10))
FIELD_YEARS = {s: (HIST_FRAMES + [2021] if FIRST_YEAR[s] == 1850 else FUT_FRAMES) for s in SOC}

# WGS84 ellipsoid (the domain file's cell area is the WGS84 area of each 5' cell)
_A, _F = 6378137.0, 1 / 298.257223563
_B = _A * (1 - _F); _E = np.sqrt(1 - (_B / _A) ** 2)


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or exit('set ISIMIP4B_WORKDIR')


def products():
    return f'{workdir()}/analysis/{TASK}'


def ellipsoid_cell_area(lat, dlat, dlon):
    """WGS84 area (m2) of cells centred at lat with sizes dlat x dlon degrees."""
    def q(phi):
        s = np.sin(np.deg2rad(phi))
        return s / (1 - _E ** 2 * s ** 2) + np.log((1 + _E * s) / (1 - _E * s)) / (2 * _E)
    return (_B ** 2 * np.deg2rad(dlon) / 2) * (q(np.asarray(lat) + dlat / 2) - q(np.asarray(lat) - dlat / 2))


def region_masks(lat, lon):
    """{region: bool (lat, lon)} for cell centres; 'global' is all True."""
    LA, LO = np.meshgrid(lat, lon, indexing='ij')
    out = {'global': np.ones(LA.shape, bool)}
    for r, (s, n, w, e) in REGIONS.items():
        out[r] = (LA >= s) & (LA <= n) & (LO >= w) & (LO <= e)
    return out
