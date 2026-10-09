#!/usr/bin/env python3
"""ISIMIP3a/3b non-irrigation water abstraction (0.5 deg, m3/yr) -> VIC-WUR 5' wateruse plugin forcing (D05).

Produces one forcing unit, forcing/water_use/<soc-scenario>/, with one file per sector, variable and year and a
provenance.yaml (docs/directory-contracts.md, "Forcing unit and provenance record"). Decision D05 as amended on
2026-10-03 (docs/decisions/D05-non-irrigation-water-use.md).

Sectors (VIC wateruse plugin types; no livestock, no separate energy sector):
  municipal      MUN_*  from ISIMIP domestic   (domww, domwc), groundwater fraction G_FRACTGW_DOM
  manufacturing  MAN_*  from ISIMIP industrial (indww, indwc), groundwater fraction G_FRACTGW_MAN
Files: <sector>_<variable>_<soc>_<year>.nc with <variable> one of
  demand                 withdrawal in mm per day over the 5' cell area (float32)
  consumption_fraction   consumed share of the withdrawal [-]
  groundwater_fraction   share of the withdrawal taken from groundwater [-] (static, repeated every year)
so that the plugin prefix <unit>/<sector>_<variable>_<soc>_ plus the year (%4d.nc) names the file of each year
(VIC plugins/general/src/plugin_forcing_utils.c). Global parameter file lines:
  PLUGIN_FORCE_TYPE MUN_DEMAND demand YEAR <unit>/municipal_demand_<soc>_  (and _GROUNDWATER, _CONSUMPTION, MAN_*)

Demand unit. The plugin stores the forcing value as the sector demand (plugins/wateruse/src/wu_force.c:110) and
splits it into groundwater and surface demand without any conversion (wu_run.c:101-108); the demand is then met
from available water expressed in mm per model step over the cell area (wu_run_local.c:142-145, discharge * dt /
area * 1000; plugins/general/include/plugin_def.h:200 documents the demand as [mm]). The demand is therefore mm
per model step; with MODEL_STEPS_PER_DAY = 1 that is mm per day:
  demand_child [mm/day] = V_child [m3/yr] / A_child [m2] * 1000 / days_in_year   (365 or 366, proleptic_gregorian)
A run with more than one model step per day would need demand / MODEL_STEPS_PER_DAY.

Sources (raw/external/isimip3-water-abstraction/dkrz-2026-10-02/, manifest manifests/inputs/isimip3-water-abstraction.yaml):
  unit                withdrawal                               consumption fraction           years
  histsoc             ISIMIP3a histsoc, same year              ISIMIP3a wc/ww, same year      1850-2021
  1850soc             ISIMIP3b 1850soc (the 1901 field)        ISIMIP3b 1850soc wc/ww         1850-2021
  2021soc             ISIMIP3a histsoc 2021, constant          ISIMIP3a 2021 wc/ww            2022-2100
  ssp1vlsoc-noadapt   ISIMIP3b ssp126soc-noadapt modelavg      ISIMIP3b 2015soc wc/ww         2022-2100
  ssp3hsoc-noadapt    ISIMIP3b ssp370soc-noadapt modelavg      ISIMIP3b 2015soc wc/ww         2022-2100
The SSP series are used raw (no rescaling, no join to 2021); the 2021/2022 step and the one-year redistribution of
industrial withdrawal in 2005 are properties of the source and are recorded in provenance.yaml.

Method:
  source handling   historical and fixed files: time `years since 1901-1-1 03:00:00`, year = 1901 + round(value),
                    years must be contiguous; SSP files: `days since 1901-01-01`, 360 rows. All sources run north
                    to south; the 280 rows of the VIC parent grid (55.75S-83.75N) are selected by latitude and
                    flipped to south-to-north. Zero (historical) and 1e20 fill (SSP) both mean no demand; SSP fill
                    cells among parents with active VIC cells are counted. A negative value stops the producer.
  volume split      each 0.5 deg parent hands its volume to its 36 children in proportion to the ISIMIP4b 5'
                    total population of the same soc scenario and year, restricted to active VIC cells; parents
                    whose active children have no population split evenly over them; parents without an active
                    child are lost and recorded per year (count, km3) in the QC reports.
  consumption       wc/ww of the source cell capped to [0, 1]; where ww = 0 the fraction of the cell's continent
                    (dominant continent of the ISIMIP4b fractional country masks, continents.csv) for the same
                    field, the global fraction where the cell belongs to no country; replicated to the children.
  groundwater       WaterGAP table value of the 0.5 deg cell (Arc_ID lookup); parents with active children but no
                    Arc_ID (VIC cells outside the WaterGAP/ISIMIP land mask) take the value of the nearest cell with
                    one within GW_MAX_KM (great-circle distance), else 0 (all surface water); counts, distances and
                    the demand in parents beyond the bound are recorded; replicated to the children.
  output            float32, (time=1, lat, lon) of the domain file, _FillValue 1e20 outside the domain mask, 0 on
                    active cells without demand, zlib + shuffle; time `days since <year>-01-01 00:00:00`, value 0,
                    calendar proleptic_gregorian.

Outputs:
  forcing/water_use/<soc>/<sector>_<variable>_<soc>_<year>.nc, provenance.yaml (qc.status: not_checked)
  qc/forcing/water_use/<soc>/reports/qa_<year>.json, lost_parents_<year>.csv, lost_demand_ledger.csv
Rule 14 of the contract: accepted forcing is produced only from a clean repository. If the repository is not clean,
or with --scratch, everything goes to scratch/water-use-forcing/<soc>/ (with --scratch-label L:
scratch/water-use-forcing/runs/L/<soc>/) and provenance records code_dirty. A forcing unit is generated as a whole:
the producer refuses to write into an existing, non-empty forcing/water_use/<soc>/.

Usage: downscale_water_use.py --scenario histsoc --years 1850-2021 [--processes N]
       [--parameter-set ID] [--parameter-status candidates|production] [--scratch [--scratch-label LABEL]]
"""
import argparse, calendar, json, os, re, sys, time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import yaml
from scipy.spatial import cKDTree

from common import gitstate, hashing, provenance, workdir

WORKDIR = workdir.root()
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
CREATED_BY = 'workflow/04_forcing/water_use/downscale_water_use.py'
METHOD_VERSION = '1.0'   # bump when results change for identical inputs
CODE_DIRS = ('workflow/04_forcing/water_use', 'workflow/common')   # code fingerprint (Git tree hashes)

WA_MANIFEST = 'manifests/inputs/isimip3-water-abstraction.yaml'
GW_MANIFEST = 'manifests/inputs/watergap-groundwater-fractions.yaml'
ISIMIP4B_MD5SUMS = 'manifests/inputs/isimip4b-dkrz-2026-09-21/MD5SUMS'
PARAMETER_MANIFEST = 'manifests/parameters/{pset}.yaml'
WA = 'raw/external/isimip3-water-abstraction/dkrz-2026-10-02'
GW = 'raw/external/watergap-groundwater-fractions/snapshot-2026-10-02'
POP = 'raw/ISIMIP4b/InputData/socioeconomic/population'
COUNTRYMASK = 'raw/ISIMIP4b/InputData/geo_conditions/countrymasks/countrymasks-fractional_30arcmin.nc'
DOMAIN = 'parameters/{status}/{pset}/domain/vic_global_5min_domain_nogl.nc'
CONTINENTS = os.path.join(HERE, 'continents.csv')
SCRATCH = 'scratch/water-use-forcing'
WA3A = f'{WA}/ISIMIP3a/InputData/socioeconomic/water_abstraction'
WA3B = f'{WA}/ISIMIP3b/InputData/socioeconomic/water_abstraction'

FACTOR = 6                         # 0.5 deg parent = 6 x 6 children of 5'
NPY, NPX = 280, 720                # VIC parent grid: 55.75S..83.75N, 179.75W..179.75E
FILL = np.float32(1e20)
GW_MAX_KM = 300.0                 # bound of the nearest-cell search for the groundwater fraction
R_EARTH_KM = 6371.0
SECTORS = {'municipal': {'src': 'dom', 'gw_table': 'domestic/input/G_FRACTGW_DOM.txt', 'plugin': 'MUN'},
           'manufacturing': {'src': 'ind', 'gw_table': 'industrial/input/G_FRACTGW_MAN.txt', 'plugin': 'MAN'}}
VARIABLES = {'demand': ('mm/day', 'water withdrawal demand per day over the cell area'),
             'consumption_fraction': ('1', 'consumed fraction of the withdrawal'),
             'groundwater_fraction': ('1', 'fraction of the withdrawal taken from groundwater')}
PLUGIN_TYPE = {'demand': 'DEMAND', 'consumption_fraction': 'CONSUMPTION', 'groundwater_fraction': 'GROUNDWATER'}
# soc scenario -> years, population (directory, file prefix)
SCEN = {'histsoc': ((1850, 2021), ('histsoc', 'population_histsoc')),
        '1850soc': ((1850, 2021), ('1850soc', 'population_1850soc')),
        '2021soc': ((2022, 2100), ('2021soc', 'population_2021soc')),
        'ssp1vlsoc-noadapt': ((2022, 2100), ('ssp1vlsoc-noadapt', 'population_ssp1')),
        'ssp3hsoc-noadapt': ((2022, 2100), ('ssp3hsoc-noadapt', 'population_ssp3'))}
SSP_SOURCE = {'ssp1vlsoc-noadapt': 'ssp126', 'ssp3hsoc-noadapt': 'ssp370'}


# ----------------------------------------------------------------------------------------------- sources
def source_spec(scen, src, year):
    """Withdrawal and consumption-fraction sources of one sector and unit year.

    Returns {'ww': (path, variable, source_year), 'cf_ww': (...), 'cf_wc': (...)} with workdir-relative paths."""
    def hist3a(q, y):
        span = '1850_1900' if y <= 1900 else '1901_2021'
        return (f'{WA3A}/histsoc/{src}w{q}_histsoc_annual_{span}.nc', f'{src}w{q}', y)

    def soc1850(q, y):
        span = '1850_2014' if y <= 2014 else '2015_2100'
        return (f'{WA3B}/1850soc/{src}w{q}_1850soc_annual_{span}.nc', f'{src}w{q}', y)
    if scen == 'histsoc':
        return {'ww': hist3a('w', year), 'cf_ww': hist3a('w', year), 'cf_wc': hist3a('c', year)}
    if scen == '1850soc':
        return {'ww': soc1850('w', year), 'cf_ww': soc1850('w', year), 'cf_wc': soc1850('c', year)}
    if scen == '2021soc':
        return {'ww': hist3a('w', 2021), 'cf_ww': hist3a('w', 2021), 'cf_wc': hist3a('c', 2021)}
    ssp = SSP_SOURCE[scen]
    return {'ww': (f'{WA3B}/{ssp}soc-noadapt/{src}ww-modelavg_{ssp}_annual_2015_2100.nc', f'{src}ww', year),
            'cf_ww': (f'{WA3B}/2015soc/{src}ww_2015soc_annual_2015_2100.nc', f'{src}ww', 2015),
            'cf_wc': (f'{WA3B}/2015soc/{src}wc_2015soc_annual_2015_2100.nc', f'{src}wc', 2015)}


def decode_years(units, values, cal='standard'):
    """Calendar year of every time step of a water-abstraction file.

    `years since 1901-1-1 03:00:00` is not decodable by netCDF4/cftime (CF years for the standard calendar); its
    values count whole years after 1901, some of them 0.000336 years (about 3 hours) short of the integer, so the
    year is 1901 + round(value). Other units are decoded by netCDF4. The years must be contiguous."""
    v = np.asarray(values, 'f8')
    if re.match(r'years since 1901-0?1-0?1', units):
        if np.abs(v - np.round(v)).max() > 0.01:
            raise ValueError(f'time values are not whole years: {v[:5]}')
        yrs = 1901 + np.round(v).astype(int)
    else:
        yrs = np.array([d.year for d in nc.num2date(v, units, cal)])
    if len(yrs) > 1 and not np.all(np.diff(yrs) == 1):
        raise ValueError(f'years are not contiguous: {yrs[:5]}..{yrs[-5:]}')
    return yrs


def parent_lats():
    """Latitudes of the VIC parent rows, south to north."""
    return -55.75 + 0.5 * np.arange(NPY)


def read_source(path, var, year):
    """One year of a source file on the VIC parent grid (south to north), in m3/yr; fill and NaN become 0.

    Returns (field, n_fill) where n_fill counts the fill or non-finite cells of the selected rows."""
    d = nc.Dataset(path); d.set_auto_mask(False)
    t = d['time']
    yrs = decode_years(t.units, t[:], getattr(t, 'calendar', 'standard'))
    if year not in yrs:
        raise SystemExit(f'{path}: year {year} not in {yrs[0]}-{yrs[-1]}')
    lat = np.asarray(d['lat'][:], 'f8'); lon = np.asarray(d['lon'][:], 'f8')
    if not np.allclose(lon, -179.75 + 0.5 * np.arange(NPX), atol=1e-4):
        raise SystemExit(f'{path}: longitudes are not the 0.5 deg grid from -179.75')
    want = parent_lats()
    rows = []
    for la in want:
        hit = np.nonzero(np.abs(lat - la) < 1e-4)[0]
        if len(hit) != 1:
            raise SystemExit(f'{path}: latitude {la} not found once in the source grid')
        rows.append(hit[0])
    raw = np.asarray(d[var][list(yrs).index(year)], 'f8')[rows, :]
    d.close()
    bad = ~np.isfinite(raw) | (raw >= 1e19)
    field = np.where(bad, 0.0, raw)
    if (field < 0).any():
        raise SystemExit(f'{path} {var} {year}: {int((field < 0).sum())} negative values')
    return field, bad


def read_population(scen, year, vic_lat):
    """ISIMIP4b 5' total population of the soc scenario and year on the VIC rows (south to north)."""
    pdir, prefix = SCEN[scen][1]
    for f in sorted(os.listdir(f'{WORKDIR}/{POP}/{pdir}')):
        m = re.fullmatch(prefix + r'_5arcmin_annual_(\d{4})_(\d{4})\.nc', f)
        if m and int(m.group(1)) <= year <= int(m.group(2)):
            path = f'{WORKDIR}/{POP}/{pdir}/{f}'
            break
    else:
        raise SystemExit(f'no {prefix} 5arcmin file for {year}')
    d = nc.Dataset(path); d.set_auto_mask(False)
    t = d['time']
    yrs = [x.year for x in nc.num2date(t[:], t.units, getattr(t, 'calendar', 'standard'))]
    glat = np.asarray(d['lat'][:], 'f8')
    i0 = int(np.argmin(np.abs(glat - vic_lat[-1])))           # global grid runs north to south
    rows = np.arange(i0, i0 + len(vic_lat))[::-1]
    if not np.allclose(glat[rows], vic_lat, atol=1e-6):
        raise SystemExit(f'{path}: rows do not match the VIC latitudes')
    p = np.asarray(d['total-population'][yrs.index(year)], 'f8')[rows, :]
    d.close()
    p = np.where(np.isfinite(p) & (p < 1e19), p, 0.0)
    if (p < 0).any():
        raise SystemExit(f'{path} {year}: negative population')
    return p, os.path.relpath(path, WORKDIR)


# ----------------------------------------------------------------------------------------------- method
def blocks(child):
    """(NY, NX) child grid -> (NY/6 * NX/6, 36) blocks, one row per parent (row-major parents)."""
    ny, nx = child.shape
    return child.reshape(ny // FACTOR, FACTOR, nx // FACTOR, FACTOR).transpose(0, 2, 1, 3).reshape(-1, FACTOR * FACTOR)


def unblocks(b, shape):
    ny, nx = shape
    return b.reshape(ny // FACTOR, nx // FACTOR, FACTOR, FACTOR).transpose(0, 2, 1, 3).reshape(ny, nx)


def split_volume(parent, weight, active):
    """Split each parent volume over its active children in proportion to `weight`.

    Rules: weight restricted to active children; even split over the active children where that weight is zero;
    parents without an active child are lost. Returns (child volume, per-parent class array, report) with classes
    0 no demand, 1 weighted, 2 even split, 3 lost."""
    if parent.shape != (active.shape[0] // FACTOR, active.shape[1] // FACTOR) or weight.shape != active.shape:
        raise ValueError('grid shapes do not match')
    act = blocks(active.astype(bool))
    w = np.where(act, np.maximum(np.nan_to_num(blocks(weight.astype('f8'))), 0.0), 0.0)
    tot = parent.astype('f8').ravel()
    wsum = w.sum(axis=1); nact = act.sum(axis=1)
    has = tot > 0
    even = has & (wsum <= 0) & (nact > 0)
    lost = has & (nact == 0)
    weighted = has & (wsum > 0)
    share = np.zeros_like(w)
    share[weighted] = w[weighted] / wsum[weighted][:, None]
    share[even] = act[even] / nact[even][:, None]
    child = unblocks(share * tot[:, None], active.shape)
    cls = np.zeros(tot.shape, 'i1'); cls[weighted] = 1; cls[even] = 2; cls[lost] = 3
    rep = {'parents_with_demand': int(has.sum()), 'parents_weighted': int(weighted.sum()),
           'parents_even_split': int(even.sum()), 'even_split_km3': float(tot[even].sum() / 1e9),
           'parents_lost': int(lost.sum()), 'lost_km3': float(tot[lost].sum() / 1e9),
           'source_km3': float(tot.sum() / 1e9), 'child_km3': float(child.sum() / 1e9)}
    back = blocks(child).sum(axis=1)
    keep = has & ~lost
    rep['max_parent_relative_residual'] = float(np.max(np.abs(back[keep] - tot[keep]) / tot[keep])) if keep.any() else 0.0
    return child, cls.reshape(parent.shape), rep


def days_in_year(year):
    return 366 if calendar.isleap(year) else 365          # proleptic Gregorian rule


def volume_to_mm_per_day(volume_m3, area_m2, year):
    """m3 per year in a cell -> mm per day over the cell area."""
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(area_m2 > 0, volume_m3 / area_m2 * 1000.0 / days_in_year(year), 0.0)


def consumption_fraction(ww, wc, continent, n_continents):
    """Cell fraction wc/ww capped to [0, 1]; continental (else global) fraction of the same field where ww = 0.

    `continent` holds 0..n_continents-1, or -1 for cells outside every country. Returns (fraction, report)."""
    ww = np.asarray(ww, 'f8'); wc = np.asarray(wc, 'f8')
    pos = ww > 0
    with np.errstate(divide='ignore', invalid='ignore'):
        raw = np.where(pos, wc / np.where(pos, ww, 1.0), 0.0)
    frac = np.clip(raw, 0.0, 1.0)
    g = min(max(wc[pos].sum() / ww[pos].sum(), 0.0), 1.0) if pos.any() else 0.0
    cont = np.full(n_continents, g)
    for k in range(n_continents):
        sel = pos & (continent == k)
        if sel.any():
            cont[k] = min(max(wc[sel].sum() / ww[sel].sum(), 0.0), 1.0)
    fb = np.where(continent >= 0, cont[np.clip(continent, 0, None)], g)
    frac = np.where(pos, frac, fb)
    rep = {'cells_capped_at_1': int((pos & (raw > 1)).sum()), 'cells_fallback': int((~pos).sum()),
           'global_fraction': float(g), 'continental_fraction': [float(x) for x in cont]}
    return frac, rep


def continent_index(countrymask_path, table_path):
    """Dominant continent (index into the sorted continent names) of every 0.5 deg cell on the VIC parent grid."""
    names, cmap = [], {}
    for line in open(table_path):
        if line.startswith('#') or line.startswith('iso3,'):
            continue
        iso, cont = line.strip().split(',', 1)
        cmap[iso] = cont
    names = sorted(set(cmap.values()))
    d = nc.Dataset(countrymask_path); d.set_auto_mask(False)
    lat = np.asarray(d['lat'][:], 'f8')
    rows = [int(np.nonzero(np.abs(lat - la) < 1e-4)[0][0]) for la in parent_lats()]
    frac = np.zeros((len(names), NPY, NPX))
    for v in d.variables:
        if v in ('lat', 'lon', 'world'):
            continue
        if v not in cmap:
            raise SystemExit(f'{table_path} lacks the country {v}')
        x = np.asarray(d[v][:], 'f8')[rows, :]
        frac[names.index(cmap[v])] += np.where(np.isfinite(x) & (x < 1e19), x, 0.0)
    d.close()
    idx = np.where(frac.max(axis=0) > 0, frac.argmax(axis=0), -1)
    return idx, names


def groundwater_parent(table_path, lookup_path, target):
    """WaterGAP Arc_ID table -> parent grid (south to north). Target cells without an Arc_ID take the value of the
    nearest cell with one (great-circle distance between cell centres) when it lies within GW_MAX_KM, else 0 (all
    surface water); the counts and distances are reported. Returns (field, beyond-bound mask, report)."""
    def read(path):
        with open(path) as fh:
            return [l.split() for l in fh.read().splitlines()[1:] if l.strip()]
    lut = {int(r[0]): (float(r[1]), float(r[2])) for r in read(lookup_path)}
    out = np.full((NPY, NPX), np.nan)
    for r in read(table_path):
        lon, lat = lut[int(r[0])]
        i = int(round((lat + 55.75) / 0.5)); j = int(round((lon + 179.75) / 0.5))
        if 0 <= i < NPY:
            out[i, j] = float(r[1])
    if np.nanmin(out) < 0 or np.nanmax(out) > 1:
        raise SystemExit(f'{table_path}: values outside [0, 1]')
    la, lo = np.meshgrid(np.deg2rad(parent_lats()), np.deg2rad(-179.75 + 0.5 * np.arange(NPX)), indexing='ij')
    xyz = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)
    valid = np.isfinite(out); need = target & ~valid
    beyond = np.zeros((NPY, NPX), bool)
    rep = {'target_parents': int(target.sum()), 'target_without_arc_id': int(need.sum()), 'max_km': GW_MAX_KM}
    if need.any():
        dist, idx = cKDTree(xyz[valid]).query(xyz[need])
        km = 2 * R_EARTH_KM * np.arcsin(np.minimum(dist / 2, 1.0))
        near = km <= GW_MAX_KM
        vals = np.where(near, out[valid][idx], 0.0)
        out[need] = vals
        beyond[need] = ~near
        rep.update(filled_nearest=int(near.sum()), beyond_bound_set_to_zero=int((~near).sum()),
                   distance_km_p50=float(np.percentile(km, 50)), distance_km_p99=float(np.percentile(km, 99)),
                   distance_km_max_filled=float(km[near].max()) if near.any() else 0.0,
                   distance_km_max=float(km.max()))
    return out, beyond, rep


def replicate(parent):
    return np.repeat(np.repeat(parent, FACTOR, axis=0), FACTOR, axis=1)


# ----------------------------------------------------------------------------------------------- output
def write_field(path, var, data, mask, lat, lon, year, attrs):
    units, long_name = VARIABLES[var.split('_', 1)[1]]
    o = nc.Dataset(path, 'w', format='NETCDF4')
    o.createDimension('time', 1); o.createDimension('lat', len(lat)); o.createDimension('lon', len(lon))
    t = o.createVariable('time', 'f8', ('time',)); t[:] = [0.0]
    t.units = f'days since {year}-01-01 00:00:00'; t.calendar = 'proleptic_gregorian'; t.standard_name = 'time'
    v = o.createVariable('lat', 'f8', ('lat',)); v[:] = lat; v.units = 'degrees_north'; v.standard_name = 'latitude'
    v = o.createVariable('lon', 'f8', ('lon',)); v[:] = lon; v.units = 'degrees_east'; v.standard_name = 'longitude'
    name = var.split('_', 1)[1]
    v = o.createVariable(name, 'f4', ('time', 'lat', 'lon'), zlib=True, complevel=5, shuffle=True,
                         chunksizes=(1, len(lat), len(lon)), fill_value=FILL)
    v.missing_value = FILL; v.units = units; v.long_name = f'{var.split("_", 1)[0]} {long_name}'
    v[0] = np.where(mask, data, FILL).astype('f4')
    for k, val in attrs.items():
        setattr(o, k, val)
    o.close()


# ----------------------------------------------------------------------------------------------- driver
def git_state():
    """(commit, dirty) of the repository (common/gitstate.py)."""
    return gitstate.state(REPO)


def check_inputs(paths, pset, dom_rel):
    """md5 of every raw input against its manifest; stops on a mismatch."""
    wa = {f['path']: f['md5'] for f in yaml.safe_load(open(f'{REPO}/{WA_MANIFEST}'))['files']}
    gw = {f['path']: f['md5'] for f in yaml.safe_load(open(f'{REPO}/{GW_MANIFEST}'))['files']}
    i4 = {}
    for line in open(f'{REPO}/{ISIMIP4B_MD5SUMS}'):
        h, p = line.split(None, 1); i4[p.strip()] = h
    dman = yaml.safe_load(open(f'{REPO}/' + PARAMETER_MANIFEST.format(pset=pset)))['components']['domain']['files']
    dmd5 = {f['path'].split('/')[-1]: f['md5'] for f in dman}
    for rel in paths:
        h = hashing.md5(f'{WORKDIR}/{rel}')
        if rel.startswith(WA + '/'):
            ref = wa.get(rel[len(WA) + 1:])
        elif rel.startswith(GW + '/'):
            ref = gw.get(rel[len(GW) + 1:])
        elif rel.startswith('raw/ISIMIP4b/'):
            ref = i4.get(rel[len('raw/ISIMIP4b/'):])
        elif rel == dom_rel:
            ref = dmd5.get(os.path.basename(rel))
        else:
            ref = None
        if ref != h:
            raise SystemExit(f'{rel}: md5 {h} does not match its manifest ({ref})')


_JOB = {}   # set by main() before the worker processes are forked; read-only in the workers


def produce_year(year):
    """Write the six files of one year and its QC records (runs in a worker process)."""
    j = _JOB; a = j['args']; t0 = time.time()
    lat, lon, mask, area = j['grid']
    pop, pop_file = read_population(a.scenario, year, lat)
    qa = {'scenario': a.scenario, 'year': year, 'population_file': pop_file, 'days_in_year': days_in_year(year),
          'sectors': {}}
    lost_rows = []
    for sec, sd in SECTORS.items():
        spec = source_spec(a.scenario, sd['src'], year)
        ww, wwfill = read_source(f'{WORKDIR}/{spec["ww"][0]}', spec['ww'][1], spec['ww'][2])
        child, cls, rep = split_volume(ww, pop, mask)
        demand = volume_to_mm_per_day(child, area, year)
        cf, cfrep = j['cf'][sec] if j['cf'][sec] is not None else consumption_parent(spec)
        used_fallback = (ww > 0) & (cls != 3) & (j['cf_ww_zero'][sec] if j['cf_ww_zero'][sec] is not None
                                                 else consumption_zero(spec))
        cfrep = dict(cfrep, parents_with_demand_using_fallback=int(used_fallback.sum()),
                     km3_using_fallback=float(ww[used_fallback].sum() / 1e9))
        base = f"{j['out']}/{sec}_{{v}}_{a.scenario}_{year}.nc"
        for var, data in (('demand', demand), ('consumption_fraction', replicate(cf)),
                          ('groundwater_fraction', j['gw'][sec])):
            fn = base.format(v=var)
            write_field(fn + '.part', f'{sec}_{var}', data, mask, lat, lon, year, j['attrs'])
            os.replace(fn + '.part', fn)
        written_km3 = float((np.where(mask, demand, 0.0) * area * days_in_year(year) / 1000.0).sum() / 1e9)
        active_parent = blocks(mask).any(axis=1).reshape(ww.shape)
        rep.update(written_km3_float64=written_km3,
                   source_fill_cells_in_active_parents=int((wwfill & active_parent).sum()),
                   source_fill_cells=int(wwfill.sum()), consumption_fraction=cfrep,
                   groundwater_beyond_bound_parents_with_demand=int(((ww > 0) & j['gw_beyond'][sec]).sum()),
                   groundwater_beyond_bound_km3=float(ww[j['gw_beyond'][sec]].sum() / 1e9),
                   source=f'{spec["ww"][0]} {spec["ww"][1]} {spec["ww"][2]}')
        qa['sectors'][sec] = rep
        plat = parent_lats()
        for i, k in zip(*np.nonzero(cls == 3)):
            lost_rows.append(f'{sec},{plat[i]:.2f},{-179.75 + 0.5 * k:.2f},{ww[i, k] / 1e9:.9f}')
    qa['runtime_s'] = round(time.time() - t0, 1)
    json.dump(qa, open(f"{j['qcdir']}/qa_{year}.json", 'w'), indent=1)
    with open(f"{j['qcdir']}/lost_parents_{year}.csv", 'w') as fh:
        fh.write('sector,parent_lat,parent_lon,lost_km3\n' + ''.join(r + '\n' for r in lost_rows))
    s = qa['sectors']
    print(f"{a.scenario} {year}: municipal {s['municipal']['child_km3']:.2f} km3, manufacturing "
          f"{s['manufacturing']['child_km3']:.2f} km3, lost {s['municipal']['lost_km3'] + s['manufacturing']['lost_km3']:.3f} km3, "
          f"{qa['runtime_s']:.0f} s", flush=True)
    return year, qa


def consumption_parent(spec):
    ww, _ = read_source(f'{WORKDIR}/{spec["cf_ww"][0]}', spec['cf_ww'][1], spec['cf_ww'][2])
    wc, _ = read_source(f'{WORKDIR}/{spec["cf_wc"][0]}', spec['cf_wc'][1], spec['cf_wc'][2])
    return consumption_fraction(ww, wc, _JOB['continent'], len(_JOB['continent_names']))


def consumption_zero(spec):
    ww, _ = read_source(f'{WORKDIR}/{spec["cf_ww"][0]}', spec['cf_ww'][1], spec['cf_ww'][2])
    return ww <= 0


def method_record(scen, gw_reports, continent_names):
    return {
        'name': 'population-weighted parent-to-child split of ISIMIP3a/3b water abstraction', 'version': METHOD_VERSION,
        'decision': 'docs/decisions/D05-non-irrigation-water-use.md (amended 2026-10-03)',
        'target_grid': 'vic-5arcmin (domain mask)', 'sectors': {s: {'isimip': d['src'], 'plugin': d['plugin'],
                                                                   'groundwater_table': d['gw_table']}
                                                               for s, d in SECTORS.items()},
        'sources': {s: source_spec(scen, d['src'], SCEN[scen][0][0]) for s, d in SECTORS.items()},
        'withdrawal_rule': ('ISIMIP3b SSP modelavg used raw (no rescaling, no join to 2021)' if scen in SSP_SOURCE else
                            'ISIMIP3a histsoc' if scen in ('histsoc', '2021soc') else 'ISIMIP3b 1850soc (1901 field)'),
        'weights': f'ISIMIP4b 5arcmin total-population, {SCEN[scen][1][0]}, same year, active VIC cells only',
        'fallback': 'even split over the active children where they have no population',
        'lost': 'parents without an active VIC cell; recorded per year in qc reports',
        'demand_unit': 'mm/day = mm per model step with MODEL_STEPS_PER_DAY = 1 (wu_force.c, wu_run.c, wu_run_local.c)',
        'demand_conversion': 'V_child [m3/yr] / area_child [m2] * 1000 / days_in_year (proleptic_gregorian)',
        'consumption_fraction': 'wc/ww capped to [0,1]; where ww = 0 the dominant-continent fraction of the same '
                                'field (global outside countries); replicated',
        'continents': continent_names,
        'groundwater_fraction': f'WaterGAP table value; parents without Arc_ID take the nearest cell with one within '
                                f'{GW_MAX_KM:.0f} km (great-circle), else 0; replicated, static',
        'groundwater_fill': gw_reports,
        'time_axis': 'days since <year>-01-01 00:00:00, value 0, proleptic_gregorian; source years: 1901 + '
                     'round(value) for "years since 1901-1-1 03:00:00"',
        'output': 'float32, _FillValue 1e20 outside the domain mask, zlib level 5 with shuffle',
        'plugin_forcing': {f'{d["plugin"]}_{PLUGIN_TYPE[k]}': f'{k} YEAR <unit>/{s}_{k}_{scen}_'
                           for s, d in SECTORS.items() for k in VARIABLES}}


SOURCE_NOTES = [
    'ISIMIP3a histsoc 2006-2021 is the WFaS SSP2 (RCP6.0) projection, not an observation-based reconstruction; '
    'years before 1901 equal 1901 (ISIMIP3b 1850soc is the 1901 field).',
    'ISIMIP3a industrial withdrawal 2005 has 26 618 positive cells instead of about 62 000 (same global total): a '
    'one-year redistribution kept as delivered (D05 amendment 4).',
    'SSP units: the raw SSP series steps down from the ISIMIP3a 2021 value in 2022 (global -9 to -27 %); kept as '
    'delivered (D05 amendment 2).',
    'Livestock and a separate energy sector are not provided; manufacturing carries all industrial withdrawal, with '
    'the WaterGAP manufacturing groundwater fraction (D05 amendment 5).']


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(SCEN), help='ISIMIP soc-scenario specifier')
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=1, help='years produced in parallel (about 3 GB each)')
    ap.add_argument('--scratch', action='store_true', help=f'test run: write under {SCRATCH}/ even from a clean repository')
    ap.add_argument('--expect-commit', default=None,
                    help='set by the submit script for an accepted output: stop unless the repository is clean and at '
                         'this commit')
    ap.add_argument('--scratch-label', default=None, help=f'with --scratch: write under {SCRATCH}/runs/<LABEL>/<soc>/')
    a = ap.parse_args(); t0 = time.time()
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    y0, y1 = SCEN[a.scenario][0]
    if years[0] < y0 or years[-1] > y1:
        raise SystemExit(f'{a.scenario} covers {y0}-{y1}, not {a.years}')
    if a.scratch_label and not (a.scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs --scratch and lowercase words joined by hyphens')
    commit, dirty = git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    unit = f'water_use/{a.scenario}'
    to_scratch = dirty or a.scratch
    sbase = f'{WORKDIR}/{SCRATCH}' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
    out = f'{sbase}/{a.scenario}' if to_scratch else f'{WORKDIR}/forcing/{unit}'
    qcdir = f'{out}/qc/reports' if to_scratch else f'{WORKDIR}/qc/forcing/{unit}/reports'
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing to {out} (not a forcing unit)', file=sys.stderr)
    elif os.path.exists(out) and os.listdir(out):
        raise SystemExit(f'{out} exists and is not empty: a forcing unit is generated as a whole and an existing '
                         f"unit is replaced only with the user's authorization (move it away first)")
    dom_rel = DOMAIN.format(status=a.parameter_status, pset=a.parameter_set)
    # ---------------- inputs and their checksums
    srcs = sorted({spec[k][0] for yy in years for sd in SECTORS.values()
                   for spec in [source_spec(a.scenario, sd['src'], yy)] for k in ('ww', 'cf_ww', 'cf_wc')})
    pops = sorted({os.path.relpath(f'{WORKDIR}/{POP}/{SCEN[a.scenario][1][0]}/{f}', WORKDIR)
                   for f in os.listdir(f'{WORKDIR}/{POP}/{SCEN[a.scenario][1][0]}')
                   for yy in years
                   if (m := re.fullmatch(SCEN[a.scenario][1][1] + r'_5arcmin_annual_(\d{4})_(\d{4})\.nc', f))
                   and int(m.group(1)) <= yy <= int(m.group(2))})
    gws = [f'{GW}/{sd["gw_table"]}' for sd in SECTORS.values()] + [f'{GW}/input/Arc_ID_lon_lat_continentalarea.txt']
    inputs = srcs + pops + gws + [COUNTRYMASK, dom_rel]
    for p in inputs:
        if not os.path.isfile(f'{WORKDIR}/{p}'):
            raise SystemExit(f'missing input {p}')
    print(f'checking {len(inputs)} input files against their manifests', flush=True)
    check_inputs(inputs, a.parameter_set, dom_rel)
    os.makedirs(out, exist_ok=True); os.makedirs(qcdir, exist_ok=True)
    # ---------------- grid, continents, static fields
    dom = nc.Dataset(f'{WORKDIR}/{dom_rel}')
    lat = np.asarray(dom['lat'][:], 'f8'); lon = np.asarray(dom['lon'][:], 'f8')
    mask = dom['mask'][:].filled(0) == 1; area = np.asarray(dom['area'][:].filled(0), 'f8'); dom.close()
    if mask.shape != (NPY * FACTOR, NPX * FACTOR) or not np.allclose(lat.reshape(NPY, FACTOR).mean(1), parent_lats()):
        raise SystemExit('the domain is not the 6 x 6 subdivision of the 280 x 720 parent grid')
    continent, cnames = continent_index(f'{WORKDIR}/{COUNTRYMASK}', CONTINENTS)
    active_parent = blocks(mask).any(axis=1).reshape(NPY, NPX)
    gw, gwrep, gw_beyond = {}, {}, {}
    for sec, sd in SECTORS.items():
        g, beyond, gwrep[sec] = groundwater_parent(f'{WORKDIR}/{GW}/{sd["gw_table"]}',
                                                   f'{WORKDIR}/{GW}/input/Arc_ID_lon_lat_continentalarea.txt', active_parent)
        gw[sec] = replicate(np.nan_to_num(g)); gw_beyond[sec] = beyond
    created_at = provenance.utcnow()
    attrs = {'title': 'non-irrigation water-use forcing for VIC-WUR (ISIMIP3a/3b water abstraction, D05)',
             'soc_scenario': a.scenario, 'code_commit': commit, 'code_dirty': str(dirty).lower(),
             'created_by': CREATED_BY, 'created_at': created_at, 'forcing_unit': unit, 'method_version': METHOD_VERSION,
             'domain': dom_rel, 'calendar': 'proleptic_gregorian'}
    _JOB.update(args=a, grid=(lat, lon, mask, area), out=out, qcdir=qcdir, attrs=attrs, gw=gw, gw_beyond=gw_beyond,
                continent=continent, continent_names=cnames, cf={}, cf_ww_zero={})
    # consumption fractions that do not change with the year are computed once
    for sec, sd in SECTORS.items():
        static = a.scenario != 'histsoc' and a.scenario != '1850soc'
        if static:
            spec = source_spec(a.scenario, sd['src'], years[0])
            _JOB['cf'][sec] = consumption_parent(spec); _JOB['cf_ww_zero'][sec] = consumption_zero(spec)
        else:
            _JOB['cf'][sec] = None; _JOB['cf_ww_zero'][sec] = None
    nproc = max(1, min(a.processes, len(years)))
    if nproc == 1:
        done = [produce_year(yy) for yy in years]
    else:
        # an executor (not a Pool) fails at once if a worker is killed, e.g. by the memory limit
        with ProcessPoolExecutor(nproc, mp_context=get_context('fork')) as ex:
            done = list(ex.map(produce_year, years))
    # ---------------- lost-demand ledger of the whole run
    ledger = ['year,sector,source_km3,written_km3,parents_weighted,parents_even_split,even_split_km3,'
              'parents_lost,lost_km3,source_fill_cells_in_active_parents']
    for yy, qa in sorted(done):
        for sec, r in qa['sectors'].items():
            ledger.append(f"{yy},{sec},{r['source_km3']:.6f},{r['child_km3']:.6f},{r['parents_weighted']},"
                          f"{r['parents_even_split']},{r['even_split_km3']:.6f},{r['parents_lost']},{r['lost_km3']:.6f},"
                          f"{r['source_fill_cells_in_active_parents']}")
    with open(f'{qcdir}/lost_demand_ledger.csv', 'w') as fh:
        fh.write('\n'.join(ledger) + '\n')
    print(f'{len(done)} year(s), {nproc} process(es), {sum(q["runtime_s"] for _, q in done) / len(done):.0f} s per year',
          flush=True)
    # ---------------- provenance of the whole unit, written last
    files = sorted(f for f in os.listdir(out) if f.endswith('.nc'))
    rp_qc = f'qc/forcing/{unit}' if not to_scratch else os.path.relpath(f'{out}/qc', WORKDIR)
    prov = {
        'forcing_unit': unit, 'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': dirty,
        'created_at': created_at, 'input_manifest': WA_MANIFEST,
        'other_manifests': [GW_MANIFEST, ISIMIP4B_MD5SUMS, PARAMETER_MANIFEST.format(pset=a.parameter_set)],
        'inputs': inputs,
        'input_sha256': {p: hashing.sha256(f'{WORKDIR}/{p}') for p in inputs},
        'method': method_record(a.scenario, gwrep, cnames),
        'source_data_notes': SOURCE_NOTES,
        'fingerprint': provenance.fingerprint(gitstate.tree_hashes(REPO, CODE_DIRS), METHOD_VERSION,
                                              provenance.software_versions()),
        'years': f'{years[0]}-{years[-1]}',
        'rebuild_command': f'python3 {CREATED_BY} --scenario {a.scenario} --years {years[0]}-{years[-1]} '
                           f'--parameter-set {a.parameter_set} --parameter-status {a.parameter_status}'
                           + (' --scratch' if a.scratch else '') + (f' --scratch-label {a.scratch_label}' if a.scratch_label else ''),
        'caches': [],
        'files': [{'path': f, 'year': int(f[:-3].rsplit('_', 1)[1]), 'size_bytes': os.path.getsize(f'{out}/{f}'),
                   'sha256': hashing.sha256(f'{out}/{f}')} for f in files],
        'qc': {'status': 'not_checked', 'evidence': rp_qc}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done: {len(years)} year(s) in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
