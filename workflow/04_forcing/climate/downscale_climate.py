#!/usr/bin/env python3
"""ISIMIP4b daily 0.5 degree bias-adjusted atmosphere -> VIC-WUR 5 arcmin daily climate forcing.

One forcing unit per VIC variable, forcing/climate/<gcm>/<input-alias>/<variable>/, with one file
<variable>_<gcm>_<input-alias>_<year>.nc per year and provenance.yaml (docs/directory-contracts.md,
"Forcing unit and provenance record").

Grid relation: the VIC 5' grid (domain file of the parameter set, 1680 x 4320, south to north) is an
exact 6 x 6 subdivision of the ISIMIP 0.5 degree grid (360 x 720, north to south). The code derives
this relation from the coordinates of both grids and stops if it does not hold.

Method (version METHOD_VERSION):
  prec   [mm/day] = pr * 86400, block replication (each 5' cell takes its 0.5 degree cell's value; for an
                    exact subdivision this equals first-order conservative and nearest-neighbour remapping)
  tair   [degC]   = tas_rep - 0.0065 K/m * dz - 273.15
  psurf  [kPa]    = ps_rep * exp(-dz / ((Rd/g) * Tv_mean)) / 1000        (hypsometric equation)
  vp     [kPa]    = min(r / (0.622 + r) * psurf, svp(tair)),  r = huss_bil / (1 - huss_bil) (mixing ratio
                    constant with height, capped at saturation with VIC's own svp formula, as VIC itself does)
  swdown [W m-2], wind [m s-1] = bilinear interpolation of rsds, sfcwind
  lwdown [W m-2]  = R * rlds_bil, ratio method of Cosgrove et al. (2003, eq. 15) as used by WATCH/WFDE5
                    (Weedon et al. 2010, WATCH Technical Report 22, eqs. 30-32):
                    R = eps(T1, e1) T1^4 / (eps(T0, e0) T0^4),  eps(T, e) = 1.08 (1 - exp(-e^(T / 2016)))
                    (Satterlund 1979; T in K, e in hPa), with T0 = tas_rep, e0 = min(r / (0.622 + r) * ps_rep,
                    svp(T0)) (0.5 degree level, the vp method without elevation change), T1 = corrected tair [K]
                    and e1 = vp [hPa] exactly as written to the tair and vp units; R = 1 where dz = 0
                    (D16, decided 2026-10-01; cap at both levels, user 2026-10-01)
  with dz = elev (5' mean cell elevation, `elev` of the parameter bundle, the elevation VIC uses)
          - ERA5 surface height (geopotential / g, first-order conservative to the 0.5 degree grid,
            block-replicated to 5'),
       Tv = T (1 + 0.61 r) at the 0.5 degree and the 5' elevation, Tv_mean their average, Rd/g = 287.05/9.80665.
  VIC cells outside the ISIMIP water_global mask use their own 0.5 degree cell (D08, amended 2026-09-30).
  Values outside the domain mask are _FillValue (1e20). lat/lon are copied from the domain file.
  Time: calendar proleptic_gregorian (as ISIMIP), units days since <year>-01-01 00:00:00, one value per day
  at 00:00 of the day it averages (the ISIMIP time stamps are at 12:00).

Rule 14 of the contract: accepted forcing is produced only from a clean repository. With --scratch or
from a repository that is not clean, everything is written under scratch/climate-forcing/ instead.

An existing unit is never overwritten; it may be extended with years it does not contain yet under
the conditions in docs/directory-contracts.md, "Forcing unit and provenance record".

Usage: downscale_climate.py --gcm ec-earth3-esm-1-1 --alias esm-hist --years 2011-2020
       [--variables tair,prec,...] [--parameter-set ID] [--parameter-status candidates|production]
       [--processes N] [--scratch [--scratch-label LABEL]]
  --scratch-label puts a test run under scratch/climate-forcing/runs/<LABEL>/ so that it does not replace
  an earlier test run.
"""
import argparse, calendar, datetime, glob, hashlib, json, os, platform, re, subprocess, sys, time
from multiprocessing import Pool

import numpy as np
import netCDF4 as nc
import yaml

CREATED_BY = 'workflow/04_forcing/climate/downscale_climate.py'
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
METHOD_VERSION = '1.1'   # bump when results change for identical inputs (1.1: lwdown elevation correction, D16)

ISIMIP_DIR = 'raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily/{alias}/{gcm_dir}'
ISIMIP_MANIFEST = 'manifests/inputs/isimip4b-dkrz-2026-09-21/inventory.tsv'
ISIMIP_MD5SUMS = 'manifests/inputs/isimip4b-dkrz-2026-09-21/MD5SUMS'
ERA5_FILE = 'raw/external/era5-surface-geopotential/cds-2026-09-30/6a36300ce2ed8bb87d44c30f32304dcd.nc'
ERA5_MANIFEST = 'manifests/inputs/era5-surface-geopotential.yaml'
DOMAIN_FILE = 'parameters/{status}/{pset}/domain/vic_global_5min_domain_nogl.nc'
BUNDLE_FILE = 'parameters/{status}/{pset}/bundle/vic_global_5min_natural_static_root-b-zeng2001.nc'
PARAMETER_MANIFEST = 'manifests/parameters/{pset}.yaml'
SCRATCH = 'scratch/climate-forcing'
GCM_DIR = {'ec-earth3-esm-1-1': 'EC-Earth3-ESM-1-1', 'ukesm1-3-ll': 'UKESM1-3-LL'}

LAPSE_RATE = 0.0065        # K m-1
G = 9.80665                # m s-2
RD = 287.05                # J kg-1 K-1, dry air
EPS = 0.622                # ratio of the molar masses of water vapour and dry air
FILL = np.float32(1e20)
SECONDS_PER_DAY = 86400.0

# VIC variable -> ISIMIP source variables, horizontal method, units, long name
VARIABLES = {
    'tair':   {'sources': ('tas',), 'horizontal': 'replication', 'units': 'degC',
               'long_name': 'near-surface air temperature, elevation-corrected'},
    'prec':   {'sources': ('pr',), 'horizontal': 'replication', 'units': 'mm/day',
               'long_name': 'total precipitation'},
    'psurf':  {'sources': ('tas', 'ps', 'huss'), 'horizontal': 'replication (tas, ps), bilinear (huss)', 'units': 'kPa',
               'long_name': 'surface air pressure, elevation-corrected'},
    'vp':     {'sources': ('tas', 'ps', 'huss'), 'horizontal': 'replication (tas, ps), bilinear (huss)', 'units': 'kPa',
               'long_name': 'near-surface vapour pressure, elevation-corrected'},
    'swdown': {'sources': ('rsds',), 'horizontal': 'bilinear', 'units': 'W m-2',
               'long_name': 'surface downwelling shortwave radiation'},
    'lwdown': {'sources': ('rlds', 'tas', 'ps', 'huss'), 'horizontal': 'bilinear (rlds, huss), replication (tas, ps)',
               'units': 'W m-2', 'long_name': 'surface downwelling longwave radiation, elevation-corrected'},
    'wind':   {'sources': ('sfcwind',), 'horizontal': 'bilinear', 'units': 'm s-1',
               'long_name': 'near-surface wind speed'},
}
BLOCKED_OUTSIDE_SCRATCH = {}   # variable -> open decision that keeps it out of forcing/ (empty since D16)


# ----------------------------------------------------------------------------------------------- utilities
def workdir():
    w = os.environ.get('ISIMIP4B_WORKDIR')
    if not w:
        sys.exit('set ISIMIP4B_WORKDIR')
    return w


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def file_hashes(path, n=1 << 24):
    """(md5, sha256) of a file in one read pass."""
    m, s = hashlib.md5(), hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(n), b''):
            m.update(b); s.update(b)
    return m.hexdigest(), s.hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', REPO, *args], capture_output=True, text=True)


def git_state():
    """(commit, dirty); dirty means `git status --porcelain` prints anything."""
    commit = git('rev-parse', 'HEAD').stdout.strip()
    dirty = bool(git('status', '--porcelain').stdout.strip())
    return commit, dirty


def code_tree_hashes():
    """Git tree hashes of the producing code at HEAD (None when the path does not exist)."""
    out = {}
    for p in ('workflow/04_forcing/climate', 'workflow/common'):
        r = git('rev-parse', f'HEAD:{p}')
        out[p] = r.stdout.strip() if r.returncode == 0 else None
    return out


def software_versions():
    return {'python': platform.python_version(), 'numpy': np.__version__, 'netCDF4': nc.__version__,
            'netcdf_c': nc.__netcdf4libversion__, 'hdf5': nc.__hdf5libversion__, 'pyyaml': yaml.__version__}


# ----------------------------------------------------------------------------------------------- grids
def subdivision_index(fine, coarse, tol=1e-6):
    """Index of the coarse cell containing each fine cell, for regular grids where the fine grid is an
    exact subdivision of the coarse one. `coarse` must be ascending. Stops if the relation does not hold."""
    fine = np.asarray(fine, 'f8'); coarse = np.asarray(coarse, 'f8')
    dc = np.diff(coarse); df = np.diff(fine)
    if not (np.allclose(dc, dc[0], atol=tol) and np.allclose(df, df[0], atol=tol) and dc[0] > 0 and df[0] > 0):
        raise ValueError('grids are not regular and ascending')
    dc, df = dc[0], df[0]; ratio = int(round(dc / df))
    if abs(ratio * df - dc) > tol:
        raise ValueError(f'coarse spacing {dc} is not a multiple of fine spacing {df}')
    pos = (fine - (coarse[0] - dc / 2)) / df            # position in fine cells from the first coarse edge
    k = np.floor(pos).astype(np.int64)
    if np.abs(pos - (k + 0.5)).max() > tol:
        raise ValueError('fine cell edges do not coincide with a subdivision of the coarse cells')
    idx = k // ratio
    if idx.min() < 0 or idx.max() >= len(coarse):
        raise ValueError('fine grid extends beyond the coarse grid')
    return idx, ratio


def linear_weights(fine, coarse, period=None):
    """1-D linear interpolation from `coarse` (ascending) to `fine` points: (i0, i1, w1) with
    value = (1 - w1) * c[i0] + w1 * c[i1]. With `period`, the coarse axis wraps around."""
    fine = np.asarray(fine, 'f8'); coarse = np.asarray(coarse, 'f8'); n = len(coarse)
    if period is not None:
        ext = np.concatenate([[coarse[-1] - period], coarse, [coarse[0] + period]])
        eidx = np.concatenate([[n - 1], np.arange(n), [0]])
    else:
        ext, eidx = coarse, np.arange(n)
    j = np.searchsorted(ext, fine, side='right') - 1
    if j.min() < 0 or j.max() >= len(ext) - 1:
        raise ValueError('fine points outside the coarse axis; extrapolation is not allowed')
    w1 = (fine - ext[j]) / (ext[j + 1] - ext[j])
    return eidx[j], eidx[j + 1], w1


def overlap_matrix(src_edges, dst_edges, period=None, transform=None):
    """Matrix M[d, s] = measure of the overlap of source cell s and destination cell d. Edges ascending;
    `transform` (e.g. sin of latitude) turns lengths into area factors; `period` wraps the source cells."""
    src_edges = np.asarray(src_edges, 'f8'); dst_edges = np.asarray(dst_edges, 'f8')
    shifts = [0.0] if period is None else [-period, 0.0, period]
    f = transform or (lambda x: x)
    M = np.zeros((len(dst_edges) - 1, len(src_edges) - 1))
    for sh in shifts:
        lo = np.maximum(dst_edges[:-1, None], src_edges[None, :-1] + sh)
        hi = np.minimum(dst_edges[1:, None], src_edges[None, 1:] + sh)
        M += np.where(hi > lo, f(hi) - f(np.minimum(lo, hi)), 0.0)
    return M


def conservative_remap(field, src_lat_edges, src_lon_edges, dst_lat_edges, dst_lon_edges):
    """First-order conservative remapping of a full-coverage field between regular lat-lon grids
    (south to north, west to east); exact because the spherical cell area factorizes."""
    sinlat = lambda x: np.sin(np.deg2rad(x))
    A = overlap_matrix(src_lat_edges, dst_lat_edges, transform=sinlat)
    B = overlap_matrix(src_lon_edges, dst_lon_edges, period=360.0)
    return (A @ field @ B.T) / (A.sum(axis=1)[:, None] * B.sum(axis=1)[None, :])


def edges_from_centres(c, lo=None, hi=None):
    c = np.asarray(c, 'f8'); d = np.diff(c)
    e = np.concatenate([[c[0] - d[0] / 2], (c[:-1] + c[1:]) / 2, [c[-1] + d[-1] / 2]])
    if lo is not None: e = np.maximum(e, lo)
    if hi is not None: e = np.minimum(e, hi)
    return e


class GridRelation:
    """ISIMIP 0.5 degree (stored south to north here) <-> VIC 5' relation, with the reference elevation."""

    def __init__(self, clat, clon, flat, flon):
        # clat, clon: ISIMIP centres ascending (south to north, west to east); flat, flon: domain centres
        self.ry, self.ratio_y = subdivision_index(flat, clat)
        self.rx, self.ratio_x = subdivision_index(flon, clon)
        if (self.ratio_y, self.ratio_x) != (6, 6):
            raise ValueError(f'expected a 6 x 6 subdivision, found {self.ratio_y} x {self.ratio_x}')
        self.by = linear_weights(flat, clat)
        self.bx = linear_weights(flon, clon, period=360.0)

    def replicate(self, c):
        return c[self.ry][:, self.rx]

    def bilinear(self, c):
        i0, i1, wx = self.bx; j0, j1, wy = self.by
        rows = np.unique(np.concatenate([j0, j1]))
        t = np.zeros((c.shape[0], len(wx)))
        t[rows] = c[rows][:, i0] * (1 - wx) + c[rows][:, i1] * wx
        return t[j0] * (1 - wy)[:, None] + t[j1] * wy[:, None]


# ----------------------------------------------------------------------------------------------- physics
def tair_downscaled(tas_k, dz):
    return tas_k - LAPSE_RATE * dz


def mixing_ratio(q):
    return q / (1.0 - q)


def psurf_downscaled(ps, tas_k, q, dz):
    """Hypsometric equation between the 0.5 degree reference height and the 5' cell height."""
    r = mixing_ratio(q)
    tv0 = tas_k * (1 + 0.61 * r)
    tv1 = tair_downscaled(tas_k, dz) * (1 + 0.61 * r)
    return ps * np.exp(-dz * G / (RD * 0.5 * (tv0 + tv1)))


def vapour_pressure(q, p):
    r = mixing_ratio(q)
    return r / (EPS + r) * p


def svp_vic(t_c):
    """Saturated vapour pressure [kPa] as computed by VIC 5 (svp.c), t in degC."""
    es = 0.61078 * np.exp(17.269 * t_c / (237.3 + t_c))
    return np.where(t_c < 0, es * (1.0 + 0.00972 * t_c + 0.000042 * t_c * t_c), es)


def emissivity(t_k, e_hpa):
    """Clear-sky atmospheric emissivity of Satterlund (1979), T in K, e in hPa."""
    return 1.08 * (1.0 - np.exp(-e_hpa ** (t_k / 2016.0)))


def lwdown_ratio(t1_k, e1_hpa, t0_k, e0_hpa):
    """R of Cosgrove et al. (2003, eq. 15): longwave at the 5' level over longwave at the 0.5 degree level."""
    return (emissivity(t1_k, e1_hpa) * t1_k ** 4) / (emissivity(t0_k, e0_hpa) * t0_k ** 4)


def thermo(src, rel, dz):
    """0.5 degree level (tas, ps, huss on the 5' grid) and corrected 5' level (tair [K], psurf [Pa], vp [kPa])."""
    tas = rel.replicate(src['tas']); t1 = tair_downscaled(tas, dz)
    if 'ps' not in src:
        return {'tas': tas, 't1': t1}
    ps = rel.replicate(src['ps']); q = rel.bilinear(src['huss'])
    p1 = psurf_downscaled(ps, tas, q, dz)
    vp1 = np.minimum(vapour_pressure(q, p1) / 1000.0, svp_vic(t1 - 273.15))
    return {'tas': tas, 't1': t1, 'ps': ps, 'q': q, 'p1': p1, 'vp1': vp1}


def compute(var, src, rel, dz):
    """5' field (float64, unmasked) of VIC variable `var` from 0.5 degree fields `src` (south to north)."""
    if var == 'prec':
        return rel.replicate(src['pr']) * SECONDS_PER_DAY
    if var in ('swdown', 'wind'):
        return rel.bilinear(src[VARIABLES[var]['sources'][0]])
    th = thermo(src, rel, dz)
    if var == 'tair':
        return th['t1'] - 273.15
    if var == 'psurf':
        return th['p1'] / 1000.0
    if var == 'vp':
        return th['vp1']
    if var == 'lwdown':
        e0_hpa = np.minimum(vapour_pressure(th['q'], th['ps']) / 1000.0, svp_vic(th['tas'] - 273.15)) * 10.0
        return lwdown_ratio(th['t1'], th['vp1'] * 10.0, th['tas'], e0_hpa) * rel.bilinear(src['rlds'])
    raise KeyError(var)


# ----------------------------------------------------------------------------------------------- time
def year_indices(time_var, year):
    """Indices of the daily steps of `year` in an ISIMIP time variable, checked for completeness and
    continuity. Returns (indices, number of days)."""
    cal = time_var.calendar
    if cal != 'proleptic_gregorian':
        raise ValueError(f'unexpected calendar {cal}')
    dates = nc.num2date(time_var[:], time_var.units, calendar=cal, only_use_cftime_datetimes=True)
    idx = np.array([i for i, d in enumerate(dates) if d.year == year])
    ndays = 366 if calendar.isleap(year) else 365      # proleptic Gregorian leap rule
    if len(idx) != ndays:
        raise ValueError(f'{year}: {len(idx)} time steps, expected {ndays}')
    doy = np.array([dates[i].timetuple().tm_yday for i in idx])
    if not (np.array_equal(doy, np.arange(1, ndays + 1)) and np.all(np.diff(idx) == 1)):
        raise ValueError(f'{year}: time axis is not one continuous step per day')
    return idx, ndays


# ----------------------------------------------------------------------------------------------- inputs
def isimip_file(W, gcm, alias, var, year):
    d = f'{W}/' + ISIMIP_DIR.format(alias=alias, gcm_dir=GCM_DIR[gcm])
    hits = []
    for f in glob.glob(f'{d}/{gcm}_*_era5_{alias}_{var}_global_30arcmin_daily_*_*.nc'):
        m = re.search(r'_(\d{4})_(\d{4})\.nc$', f)
        if m and int(m.group(1)) <= year <= int(m.group(2)):
            hits.append(f)
    if len(hits) != 1:
        raise SystemExit(f'expected one ISIMIP file for {gcm} {alias} {var} {year}, found {hits}')
    return hits[0]


def read_domain(path):
    d = nc.Dataset(path)
    lat = np.array(d['lat'][:], 'f8'); lon = np.array(d['lon'][:], 'f8')
    mask = d['mask'][:].filled(0) > 0; area = np.array(d['area'][:].filled(0), 'f8')
    d.close()
    return lat, lon, mask, area


def read_elev(path, lat, lon, mask):
    d = nc.Dataset(path)
    if not (np.array_equal(d['lat'][:], lat) and np.array_equal(d['lon'][:], lon)):
        raise SystemExit(f'{path}: lat/lon differ from the domain file')
    e = d['elev'][:].filled(np.nan).astype('f8'); d.close()
    if np.isnan(e[mask]).any():
        raise SystemExit(f'{path}: elev missing on active cells')
    return np.where(mask, e, 0.0)


def era5_height_05(path, clat, clon):
    """ERA5 surface height [m] on the ISIMIP 0.5 degree grid (south to north), conservative remapping."""
    d = nc.Dataset(path)
    z = np.array(d['z'][0].filled(np.nan), 'f8') / G
    la = np.array(d['latitude'][:], 'f8'); lo = np.array(d['longitude'][:], 'f8'); d.close()
    if np.isnan(z).any():
        raise SystemExit(f'{path}: missing values in z')
    if la[0] > la[-1]:
        z, la = z[::-1], la[::-1]
    return conservative_remap(z, edges_from_centres(la, -90, 90), edges_from_centres(lo),
                              edges_from_centres(clat, -90, 90), edges_from_centres(clon))


def isimip_grid(path):
    d = nc.Dataset(path)
    lat = np.array(d['lat'][:], 'f8'); lon = np.array(d['lon'][:], 'f8'); d.close()
    if lat[0] < lat[-1]:
        raise SystemExit(f'{path}: expected latitude north to south')
    return lat[::-1], lon      # ascending


def static_reference(W, isimip_any, dom_path, bundle_path, era5_path, hashes):
    """Grid relation and dz on the 5' grid; cached under scratch/climate-forcing/weights/ (rebuilt when the
    key, derived from both grids, the static inputs and METHOD_VERSION, does not match)."""
    clat, clon = isimip_grid(isimip_any)
    flat, flon, mask, area = read_domain(dom_path)
    key = hashlib.sha256(b''.join([clat.tobytes(), clon.tobytes(), flat.tobytes(), flon.tobytes(),
                                   hashes[dom_path][1].encode(), hashes[bundle_path][1].encode(),
                                   hashes[era5_path][1].encode(), METHOD_VERSION.encode()])).hexdigest()
    cache = f'{W}/{SCRATCH}/weights/grid-relation-and-dz_{key[:16]}.npz'
    rel = GridRelation(clat, clon, flat, flon)
    if os.path.exists(cache):
        z = np.load(cache)
        if str(z['key']) == key:
            return rel, clat, clon, flat, flon, mask, area, z['dz'], z['zref05'], cache
    zref05 = era5_height_05(era5_path, clat, clon)
    elev = read_elev(bundle_path, flat, flon, mask)
    dz = np.where(mask, elev - rel.replicate(zref05), 0.0)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    tmp = cache[:-4] + '.part.npz'
    np.savez(tmp, key=key, dz=dz, zref05=zref05, ry=rel.ry, rx=rel.rx,
             by_i0=rel.by[0], by_i1=rel.by[1], by_w=rel.by[2], bx_i0=rel.bx[0], bx_i1=rel.bx[1], bx_w=rel.bx[2])
    os.replace(tmp, cache)
    return rel, clat, clon, flat, flon, mask, area, dz, zref05, cache


# ----------------------------------------------------------------------------------------------- output
def out_name(var, gcm, alias, year):
    return f'{var}_{gcm}_{alias}_{year}.nc'


def create_output(path, var, flat, flon, year, ndays, attrs):
    o = nc.Dataset(path, 'w', format='NETCDF4')
    o.createDimension('time', ndays); o.createDimension('lat', len(flat)); o.createDimension('lon', len(flon))
    t = o.createVariable('time', 'f8', ('time',))
    t.units = f'days since {year}-01-01 00:00:00'; t.calendar = 'proleptic_gregorian'
    t.standard_name = 'time'; t.long_name = 'time (00:00 of the day whose daily mean is stored)'; t.axis = 'T'
    t[:] = np.arange(ndays, dtype='f8')
    v = o.createVariable('lat', 'f8', ('lat',)); v[:] = flat
    v.units = 'degrees_north'; v.standard_name = 'latitude'; v.long_name = 'latitude of grid cell center'; v.axis = 'Y'
    v = o.createVariable('lon', 'f8', ('lon',)); v[:] = flon
    v.units = 'degrees_east'; v.standard_name = 'longitude'; v.long_name = 'longitude of grid cell center'; v.axis = 'X'
    x = o.createVariable(var, 'f4', ('time', 'lat', 'lon'), zlib=True, complevel=5, shuffle=True,
                         chunksizes=(1, len(flat), len(flon)), fill_value=FILL)
    x.missing_value = FILL; x.units = VARIABLES[var]['units']; x.long_name = VARIABLES[var]['long_name']
    x.source_variables = ','.join(VARIABLES[var]['sources'])
    for k, val in attrs.items():
        setattr(o, k, val)
    return o, x


def produce_variable(job):
    """Worker: write every requested year of one VIC variable. Returns file records."""
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    var, years, ctx = job['var'], job['years'], job['ctx']
    ref = np.load(ctx['static_cache'])
    dz = ref['dz']; mask = job['mask']
    rel = GridRelation(ctx['clat'], ctx['clon'], ctx['flat'], ctx['flon'])
    records = []
    for year in years:
        t0 = time.time()
        srcs = {s: nc.Dataset(ctx['sources'][year][s]) for s in VARIABLES[var]['sources']}
        idx = None
        for s, d in srcs.items():
            d.set_auto_mask(True)
            i, ndays = year_indices(d['time'], year)
            if idx is not None and not np.array_equal(i, idx):
                raise SystemExit(f'{var} {year}: source time axes differ')
            idx = i
        final = f'{ctx["out_dir"][var]}/{out_name(var, ctx["gcm"], ctx["alias"], year)}'
        part = final + '.part'
        attrs = dict(ctx['attrs'], forcing_unit=ctx['unit'][var], year=np.int32(year),
                     source_files='; '.join(os.path.relpath(ctx['sources'][year][s], ctx['W']) for s in srcs))
        o, x = create_output(part, var, ctx['flat'], ctx['flon'], year, ndays, attrs)
        vmin, vmax = np.inf, -np.inf
        for k, ti in enumerate(idx):
            src = {}
            for s, d in srcs.items():
                a = d[s][ti]
                if np.ma.is_masked(a) and np.ma.getmaskarray(a).any():
                    raise SystemExit(f'{s} {year} step {ti}: missing values in the ISIMIP input')
                src[s] = np.asarray(a, 'f8')[::-1]        # north-south -> south-north
            y = compute(var, src, rel, dz)
            if not np.isfinite(y[mask]).all():
                raise SystemExit(f'{var} {year} day {k}: non-finite result on active cells')
            vmin = min(vmin, float(y[mask].min())); vmax = max(vmax, float(y[mask].max()))
            x[k] = np.where(mask, y, FILL).astype('f4')
        o.close()
        for d in srcs.values():
            d.close()
        os.replace(part, final)
        md5, sha = file_hashes(final)
        records.append({'path': os.path.basename(final), 'year': year, 'size_bytes': os.path.getsize(final),
                        'sha256': sha, 'created_at': utcnow(), 'code_commit': ctx['commit'],
                        'min_active': vmin, 'max_active': vmax})
        print(f'{var} {year}: {time.time() - t0:.0f} s, {os.path.getsize(final) / 1e9:.2f} GB, '
              f'range {vmin:.4g} .. {vmax:.4g}', flush=True)
    return var, records


# ----------------------------------------------------------------------------------------------- provenance
def method_record(var, rel_paths):
    m = {'name': 'ISIMIP4b 0.5 degree daily -> VIC-WUR 5 arcmin daily', 'version': METHOD_VERSION,
         'target_grid': 'vic-5arcmin (grid, lat, lon of the domain file)',
         'source_variables': list(VARIABLES[var]['sources']),
         'horizontal': VARIABLES[var]['horizontal'],
         'horizontal_note': 'the 5 arcmin grid is an exact 6 x 6 subdivision of the 0.5 degree grid; block replication '
                            'equals first-order conservative and nearest-neighbour remapping; bilinear uses separable '
                            'linear weights in latitude and (periodic) longitude, no extrapolation',
         'mask': f'{rel_paths["domain"]}: mask (D08, option a)',
         'outside_isimip_mask': 'own 0.5 degree cell value (D08, amended 2026-09-30)',
         'units': VARIABLES[var]['units'],
         'calendar': 'proleptic_gregorian',
         'time_axis': 'days since <year>-01-01 00:00:00, one step per day at 00:00; value = daily mean of that day '
                      '(ISIMIP stamps 12:00)',
         'fill_value': float(FILL), 'dtype': 'float32', 'chunking': [1, 1680, 4320],
         'compression': 'zlib level 5 with shuffle'}
    if var in ('tair', 'psurf', 'vp', 'lwdown'):
        m['elevation_correction'] = {
            'target_elevation': f'{rel_paths["bundle"]}: elev (5 arcmin mean cell elevation used by VIC)',
            'reference_elevation': f'{rel_paths["era5"]}: z / {G}, first-order conservative to the ISIMIP 0.5 degree '
                                   'grid, block-replicated to 5 arcmin',
            'lapse_rate_K_per_m': LAPSE_RATE, 'Rd_J_per_kg_K': RD, 'g_m_per_s2': G, 'epsilon': EPS,
            'virtual_temperature': 'T (1 + 0.61 r), r = q / (1 - q), q = bilinear huss',
            'pressure': 'hypsometric equation with the mean virtual temperature of the 0.5 degree and 5 arcmin levels',
            'vapour_pressure': 'min(r / (epsilon + r) * psurf, svp(tair)): mixing ratio constant with height, capped '
                               'at the saturated vapour pressure of the corrected tair with the VIC 5 svp formula '
                               '(0.61078 exp(17.269 T / (237.3 + T)) kPa, ice factor below 0 degC), as VIC applies '
                               'when reading forcing (drivers/image/src/vic_force.c)'}
    if var == 'lwdown':
        m['corrections'] = {'lwdown': {
            'decision': 'D16, option A (user, 2026-10-01), docs/decisions/D16-lwdown-elevation-correction.md',
            'formula': 'lwdown = R * rlds_bil, R = eps(T1, e1) T1^4 / (eps(T0, e0) T0^4)',
            'emissivity': 'eps(T, e) = 1.08 (1 - exp(-e^(T / 2016))), T in K, e in hPa (Satterlund 1979)',
            'level_0p5deg': 'T0 = tas block-replicated [K]; e0 = min(r / (0.622 + r) * ps_rep, svp(T0)) [hPa], r from '
                            'bilinear huss: the vp method at the 0.5 degree level, capped like vp so that R = 1 '
                            'where dz = 0',
            'level_5arcmin': 'T1 = corrected tair [K], e1 = vp [hPa] (capped at saturation), as written to the tair '
                             'and vp units',
            'horizontal': 'rlds bilinear as in method 1.0; R = 1 where dz = 0',
            'references': ['Cosgrove et al. (2003), J. Geophys. Res. 108(D22), 8842, doi:10.1029/2002JD003118, eq. 15',
                           'Weedon et al. (2010), WATCH Technical Report 22, eqs. 30-32',
                           'Satterlund (1979), Water Resour. Res. 15(6), 1649-1650, doi:10.1029/WR015i006p01649',
                           'Cucchi et al. (2020), Earth Syst. Sci. Data 12, 2097-2120 (WFDE5)']}}
    conv = {'tair': 'K -> degC (- 273.15)', 'prec': 'kg m-2 s-1 -> mm/day (* 86400)', 'psurf': 'Pa -> kPa (/ 1000)',
            'vp': 'Pa -> kPa (/ 1000)', 'swdown': 'none', 'lwdown': 'none', 'wind': 'none'}
    m['unit_conversion'] = conv[var]
    return m


def check_extension(prov, out_dir, current):
    """Conditions of docs/directory-contracts.md for extending a unit; returns a list of violations."""
    bad = []
    fp = prov.get('fingerprint', {})
    if prov.get('method', {}).get('version') != METHOD_VERSION:
        bad.append(f'method version {prov.get("method", {}).get("version")} != {METHOD_VERSION}')
    if fp.get('code_tree') != current['code_tree']:
        bad.append(f'code tree {fp.get("code_tree")} != {current["code_tree"]}')
    if fp.get('software') != current['software']:
        bad.append(f'software {fp.get("software")} != {current["software"]}')
    old = prov.get('input_sha256', {})
    for p, sha in current['input_sha256'].items():
        if p in old and old[p] != sha:
            bad.append(f'input {p} changed (sha256)')
    for p in current['static_inputs']:
        if p not in old:
            bad.append(f'static input {p} not recorded in the unit')
    for f in prov.get('files', []):
        fp_ = f'{out_dir}/{f["path"]}'
        if not os.path.exists(fp_):
            bad.append(f'{f["path"]} missing')
        elif file_hashes(fp_)[1] != f['sha256']:
            bad.append(f'{f["path"]} sha256 differs from provenance')
    return bad


def select_variables(requested, to_scratch):
    """Variables to produce; variables blocked by an open decision only go to scratch."""
    variables = requested.split(',') if requested else \
        [v for v in VARIABLES if to_scratch or v not in BLOCKED_OUTSIDE_SCRATCH]
    for v in variables:
        if v not in VARIABLES:
            raise SystemExit(f'unknown variable {v}; choose from {list(VARIABLES)}')
        if v in BLOCKED_OUTSIDE_SCRATCH and not to_scratch:
            raise SystemExit(f'{v} is written only with --scratch: {BLOCKED_OUTSIDE_SCRATCH[v]}')
    return variables


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--gcm', required=True, choices=list(GCM_DIR))
    ap.add_argument('--alias', required=True, help='climate-scenario input alias, e.g. esm-hist')
    ap.add_argument('--years', required=True, help='single year or START-END')
    ap.add_argument('--variables', default=None,
                    help='comma-separated VIC variables (default: all)')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=None, help='parallel workers (default: one per variable)')
    ap.add_argument('--scratch', action='store_true', help=f'test run: write under {SCRATCH}/ even from a clean repository')
    ap.add_argument('--scratch-label', default=None,
                    help=f'with --scratch: write under {SCRATCH}/runs/<label>/ (lowercase words joined by hyphens)')
    a = ap.parse_args(); t0 = time.time(); W = workdir()
    y = a.years.split('-'); years = list(range(int(y[0]), int(y[-1]) + 1))
    commit, dirty = git_state(); to_scratch = dirty or a.scratch
    variables = select_variables(a.variables, to_scratch)
    if to_scratch:
        print(f'{"repository is not clean" if dirty else "--scratch"}: writing under {W}/{SCRATCH}/ (not forcing units)',
              file=sys.stderr)
    if a.scratch_label and not (to_scratch and re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', a.scratch_label)):
        raise SystemExit('--scratch-label needs a scratch run and lowercase words joined by hyphens')
    base = (f'{W}/{SCRATCH}' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')) if to_scratch \
        else f'{W}/forcing/climate'
    unit = {v: f'climate/{a.gcm}/{a.alias}/{v}' for v in variables}
    out_dir = {v: f'{base}/{a.gcm}/{a.alias}/{v}' if to_scratch else f'{W}/forcing/{unit[v]}' for v in variables}

    # ---------------- inputs and their checksums
    dom = f'{W}/' + DOMAIN_FILE.format(status=a.parameter_status, pset=a.parameter_set)
    bundle = f'{W}/' + BUNDLE_FILE.format(status=a.parameter_status, pset=a.parameter_set)
    era5 = f'{W}/{ERA5_FILE}'
    needed = sorted({s for v in variables for s in VARIABLES[v]['sources']})
    sources = {yy: {s: isimip_file(W, a.gcm, a.alias, s, yy) for s in needed} for yy in years}
    for p in (dom, bundle, era5):
        if not os.path.isfile(p):
            raise SystemExit(f'missing input {p}')
    md5sums = {}
    for line in open(f'{REPO}/{ISIMIP_MD5SUMS}'):
        h, p = line.split(None, 1); md5sums[p.strip()] = h
    all_isimip = sorted({f for yy in years for f in sources[yy].values()})
    print(f'checksumming {len(all_isimip) + 3} input files', flush=True)
    hashes = {p: file_hashes(p) for p in [dom, bundle, era5] + all_isimip}
    for f in all_isimip:
        key = os.path.relpath(f, f'{W}/raw/ISIMIP4b')
        if md5sums.get(key) != hashes[f][0]:
            raise SystemExit(f'{f}: md5 does not match {ISIMIP_MD5SUMS}')
    era5_md5 = yaml.safe_load(open(f'{REPO}/{ERA5_MANIFEST}'))['files'][0]['md5']
    if hashes[era5][0] != era5_md5:
        raise SystemExit(f'{era5}: md5 does not match {ERA5_MANIFEST}')
    pman = yaml.safe_load(open(f'{REPO}/' + PARAMETER_MANIFEST.format(pset=a.parameter_set)))['components']
    for comp, path in (('domain', dom), ('bundle', bundle)):
        if pman[comp]['files'][0]['md5'] != hashes[path][0]:
            raise SystemExit(f'{path}: md5 does not match the parameter manifest')
    rp = lambda p: os.path.relpath(p, W)
    rel_paths = {'domain': rp(dom), 'bundle': rp(bundle), 'era5': rp(era5)}
    current = {'code_tree': code_tree_hashes(), 'software': software_versions(),
               'static_inputs': [rp(dom), rp(bundle), rp(era5)]}

    # ---------------- unit state: new, extension, or refused
    existing = {}
    for v in variables:
        d = out_dir[v]; prov_path = f'{d}/provenance.yaml'
        ins = {rp(p): hashes[p][1] for p in [dom, bundle, era5] + sorted({sources[yy][s] for yy in years
                                                                        for s in VARIABLES[v]['sources']})}
        present = [f for f in os.listdir(d) if f.endswith('.nc')] if os.path.isdir(d) else []
        if to_scratch:
            existing[v] = None
            continue
        if os.path.exists(prov_path):
            prov = yaml.safe_load(open(prov_path))
            have = {f['year'] for f in prov.get('files', [])}
            clash = sorted(have & set(years))
            if clash:
                raise SystemExit(f'{unit[v]} already contains {clash}; an existing unit is never overwritten')
            bad = check_extension(prov, d, dict(current, input_sha256=ins))
            if bad:
                raise SystemExit(f'{unit[v]} cannot be extended:\n  ' + '\n  '.join(bad))
            existing[v] = prov
            print(f'{unit[v]}: extending with {years}', flush=True)
        elif present or (os.path.isdir(d) and os.listdir(d)):
            raise SystemExit(f'{d} contains files but no provenance.yaml (incomplete unit); ask the user')
        else:
            existing[v] = None

    # ---------------- static reference (grid relation, dz)
    rel, clat, clon, flat, flon, mask, area, dz, zref05, cache = static_reference(
        W, all_isimip[0], dom, bundle, era5, hashes)
    print(f'grid relation and dz ready ({cache}); dz on active cells: mean {dz[mask].mean():.1f} m, '
          f'min {dz[mask].min():.0f} m, max {dz[mask].max():.0f} m', flush=True)
    for d in out_dir.values():
        os.makedirs(d, exist_ok=True)
    created_at = utcnow()
    attrs = {'title': 'ISIMIP4b bias-adjusted climate downscaled to the VIC-WUR 5 arcmin domain',
             'gcm': a.gcm, 'climate_scenario_input_alias': a.alias, 'code_commit': commit,
             'code_dirty': str(dirty).lower(), 'created_by': CREATED_BY, 'created_at': created_at,
             'method_version': METHOD_VERSION, 'calendar': 'proleptic_gregorian',
             'domain': rel_paths['domain'], 'target_elevation': rel_paths['bundle'] + ': elev',
             'reference_elevation': rel_paths['era5']}
    ctx = {'W': W, 'gcm': a.gcm, 'alias': a.alias, 'unit': unit, 'out_dir': out_dir, 'sources': sources,
           'static_cache': cache, 'clat': clat, 'clon': clon, 'flat': flat, 'flon': flon,
           'attrs': attrs, 'commit': commit}
    jobs = [{'var': v, 'years': years, 'ctx': ctx, 'mask': mask} for v in variables]
    nproc = a.processes or len(jobs)
    with Pool(nproc) as pool:
        results = dict(pool.map(produce_variable, jobs, chunksize=1))

    # ---------------- provenance per unit, written last
    for v in variables:
        prev = existing[v]
        ins = {rp(p): hashes[p][1] for p in [dom, bundle, era5] + sorted({sources[yy][s] for yy in years
                                                                        for s in VARIABLES[v]['sources']})}
        files = (prev['files'] if prev else []) + [{k: r[k] for k in ('path', 'year', 'size_bytes', 'sha256',
                                                                      'created_at', 'code_commit')}
                                                   for r in results[v]]
        if to_scratch:      # scratch: list whatever is in the directory
            recs = {r['path']: r for r in results[v]}
            files = [recs.get(f) or {'path': f} for f in sorted(os.listdir(out_dir[v])) if f.endswith('.nc')]
            files = [{k: r[k] for k in ('path', 'year', 'size_bytes', 'sha256', 'created_at', 'code_commit') if k in r}
                     for r in files]
        files = sorted(files, key=lambda f: f['path'])
        yrs = sorted(f['year'] for f in files if 'year' in f)
        input_sha = dict(prev['input_sha256']) if prev else {}
        input_sha.update(ins)
        qc_evidence = f'qc/forcing/{unit[v]}' if not to_scratch else rp(f'{out_dir[v]}/qc')
        prov = {
            'forcing_unit': unit[v], 'created_by': CREATED_BY,
            'code_commit': prev['code_commit'] if prev else commit, 'code_dirty': dirty,
            'created_at': prev['created_at'] if prev else created_at,
            'input_manifest': ISIMIP_MANIFEST,
            'other_manifests': [ERA5_MANIFEST, PARAMETER_MANIFEST.format(pset=a.parameter_set)],
            'inputs': sorted(input_sha),
            'input_sha256': dict(sorted(input_sha.items())),
            'method': method_record(v, rel_paths),
            'fingerprint': {'code_tree': current['code_tree'], 'method_version': METHOD_VERSION,
                            'software': current['software'], 'conda_env': os.environ.get('CONDA_DEFAULT_ENV')},
            'years': f'{yrs[0]}-{yrs[-1]}' if yrs else None,
            'rebuild_command': f'python3 {CREATED_BY} --gcm {a.gcm} --alias {a.alias} --variables {v} '
                               f'--years {yrs[0]}-{yrs[-1]} --parameter-set {a.parameter_set} '
                               f'--parameter-status {a.parameter_status}' + (' --scratch' if a.scratch else '')
                               + (f' --scratch-label {a.scratch_label}' if a.scratch_label else ''),
            'caches': [],
            'files': files,
            'qc': {'status': 'not_checked', 'evidence': qc_evidence}}
        if prev:
            prov['extended'] = (prev.get('extended') or []) + [{'at': created_at, 'code_commit': commit, 'years': years}]
        tmp = f'{out_dir[v]}/provenance.yaml.part'
        with open(tmp, 'w') as fh:
            yaml.safe_dump(prov, fh, sort_keys=False)
        os.replace(tmp, f'{out_dir[v]}/provenance.yaml')
    print(f'done: {len(variables)} variable(s) x {len(years)} year(s) in {time.time() - t0:.0f} s -> {base}')


if __name__ == '__main__':
    main()
