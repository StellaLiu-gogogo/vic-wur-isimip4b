#!/usr/bin/env python3
"""Independent verification of climate forcing units produced by downscale_climate.py.

For every file <variable>_<gcm>_<alias>_<year>.nc of a unit (or the years given) the checks are:
  structure   dimensions (time, lat, lon), float32, chunking (1, 1680, 4320), zlib 5 with shuffle,
              _FillValue 1e20, units attribute
  grid        lat and lon arrays equal the domain file's arrays exactly (same order)
  time        calendar proleptic_gregorian, units days since <year>-01-01 00:00:00, values 0 .. n-1 with
              n = 365 or 366
  mask        every day: finite values on exactly the active domain cells, _FillValue elsewhere
  range       physical bounds per variable on active cells
  mean        land-area-weighted mean over the active cells (domain `area`) versus the 0.5 degree input,
              whose cells are weighted by the area of their active 5' cells, every day:
                prec                    |relative difference| <= 1e-6 (conservative remapping)
                swdown, wind            |relative difference| <= 5e-3 (bilinear)
                lwdown                  |difference| <= 0.5 W m-2 (the ratio correction nearly conserves)
                tair                    |difference - lapse-rate term| <= 1e-3 K, where the lapse-rate term
                                        -0.0065 K/m * mean(dz) is computed from an independent dz
                psurf                   |relative difference| <= 5e-3;  vp  |relative difference| <= 2e-2
  sample days on the first, middle and last day the 5' field is recomputed with cdo (remapcon for pr and the
              ERA5 orography, remapnn for tas and ps, remapbil for huss, rsds, rlds, sfcwind) and the physics
              coded again here; max |difference| on active cells <= 1e-3 in the file's units
              (relative 1e-5 for prec, relative 5e-3 for lwdown, whose ratio R (D16, Cosgrove et al. 2003) is
              computed here from the input files and the elevations without the producer's code)
  lwdown      on the sample days: R = lwdown / bilinear rlds equals 1 within 1e-6 where |dz| < R1_DZ_M (the
              lapse-rate term alone changes R by about 1e-4 per metre); the regression slope of
              (lwdown - bilinear rlds) on dz is reported (expected -25 to -50 W m-2 km-1), not checked
  saturation  vp only: no active cell-day with vp > saturated vapour pressure at tair (VIC's svp) beyond
              float32 rounding (relative 1e-5); the producer caps vp at saturation
Writes <qc>/reports/verify_<year>.json, <qc>/figures/verify_<year>.png, and <qc>/summary.json, where <qc> is
qc/forcing/climate/<gcm>/<alias>/<variable>/, and sets qc.status in the unit's provenance.yaml: `failed` if any
file fails, `passed` or `warning` when every file of the unit is checked, `not_checked` otherwise. Each report
records the SHA-256 of its data file and the verifier version; a report of an earlier run counts only while both
still match (common/qc.py), otherwise its year is not_checked. Exit status: 0 passed, 1 failed, 3 warning,
4 not_checked (common/qc.py), over all variables.

Usage: verify_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-hist --variables tair,prec [--years 2011-2020]
       [--scratch [--scratch-label LABEL]] [--processes N]
  --scratch verifies the test output under scratch/climate-forcing/[runs/<LABEL>/] and writes its QC next to it.
"""
import argparse, glob, os, re, shutil, subprocess, tempfile
from multiprocessing import Pool

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

from common import provenance, qc, workdir

W = workdir.root()
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
RAW = f'{W}/raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily/{{alias}}/{{gcm_dir}}'
ERA5 = f'{W}/raw/external/era5-surface-geopotential/cds-2026-09-30/6a36300ce2ed8bb87d44c30f32304dcd.nc'
GCM_DIR = {'ec-earth3-esm-1-1': 'EC-Earth3-ESM-1-1', 'ukesm1-3-ll': 'UKESM1-3-LL'}
CHECKED_BY = 'workflow/04_forcing/climate/verify_forcing.py'
FILL = np.float32(1e20)
SPEC = {   # units, sources, physical range, mean check (kind, tolerance)
    'tair':   ('degC', ('tas',), (-90, 60), ('lapse', 1e-3)),
    'prec':   ('mm/day', ('pr',), (0, 2000), ('rel', 1e-6)),
    'psurf':  ('kPa', ('ps',), (30, 110), ('rel', 5e-3)),
    'vp':     ('kPa', ('huss', 'ps'), (0, 8), ('rel', 2e-2)),
    'swdown': ('W m-2', ('rsds',), (0, 600), ('rel', 5e-3)),
    'lwdown': ('W m-2', ('rlds',), (30, 600), ('abs', 0.5)),
    'wind':   ('m s-1', ('sfcwind',), (0, 60), ('rel', 5e-3)),
}
SAMPLE_TOL = 1e-3
LWDOWN_SAMPLE_RTOL = 5e-3
R1_DZ_M, R1_TOL = 0.005, 1e-6     # |dz| below which R must equal 1 within R1_TOL
SUPERSAT_RTOL = 1e-5


def svp(t):
    """VIC 5 svp.c, kPa."""
    es = 0.61078 * np.exp(17.269 * t / (237.3 + t))
    return np.where(t < 0, es * (1.0 + 0.00972 * t + 0.000042 * t * t), es)


def isimip_path(gcm, alias, var, year):
    for f in glob.glob(RAW.format(alias=alias, gcm_dir=GCM_DIR[gcm]) + f'/{gcm}_*_era5_{alias}_{var}_global_30arcmin_daily_*_*.nc'):
        a, b = map(int, re.search(r'_(\d{4})_(\d{4})\.nc$', f).groups())
        if a <= year <= b:
            return f
    raise SystemExit(f'no ISIMIP file for {var} {year}')


def cdo(*args):
    r = subprocess.run(['cdo', '-s', '-O', *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'cdo {" ".join(args)}: {r.stderr[-2000:]}')


def to_array(path, var):
    d = nc.Dataset(path); lat = d['lat'][:]; x = np.ma.filled(d[var][0].astype('f8'), np.nan)
    d.close()
    return x[::-1] if lat[0] > lat[-1] else x


class Context:
    """Domain, independent coarse-cell mapping and reference elevation, shared by the checks."""

    def __init__(self, dom_path, bundle_path, tmp):
        d = nc.Dataset(dom_path)
        self.lat = np.array(d['lat'][:]); self.lon = np.array(d['lon'][:])
        self.mask = d['mask'][:].filled(0) > 0; self.area = np.where(self.mask, d['area'][:].filled(0), 0.0)
        d.close()
        # coarse cell of each 5' row/column, from the cell-centre coordinates (ISIMIP rows north to south)
        self.crow = (359 - np.floor((self.lat + 90) / 0.5)).astype(int)
        self.ccol = np.floor((self.lon + 180) / 0.5).astype(int)
        # area of active 5' cells per 0.5 degree cell
        self.w05 = np.zeros((360, 720))
        np.add.at(self.w05, (self.crow[:, None].repeat(len(self.lon), 1), self.ccol[None, :].repeat(len(self.lat), 0)),
                  self.area)
        self.griddes = f'{tmp}/vic5.grid'
        with open(self.griddes, 'w') as fh:
            fh.write(f'gridtype = lonlat\nxsize = {len(self.lon)}\nysize = {len(self.lat)}\n'
                     f'xfirst = {float(self.lon[0])!r}\nxinc = {1 / 12!r}\nyfirst = {float(self.lat[0])!r}\n'
                     f'yinc = {1 / 12!r}\n')
        b = nc.Dataset(bundle_path); self.elev = np.array(b['elev'][:].filled(np.nan)); b.close()
        # reference elevation with cdo: ERA5 z / g, conservative to the ISIMIP grid, nearest neighbour to 5'
        isimip_grid = f'{tmp}/isimip.grid'
        with open(isimip_grid, 'w') as fh:
            fh.write('gridtype = lonlat\nxsize = 720\nysize = 360\nxfirst = -179.75\nxinc = 0.5\n'
                     'yfirst = 89.75\nyinc = -0.5\n')
        cdo('-f', 'nc4', '-divc,9.80665', f'-remapcon,{isimip_grid}', '-selname,z', ERA5, f'{tmp}/zref05.nc')
        cdo('-f', 'nc4', f'-remapnn,{self.griddes}', f'{tmp}/zref05.nc', f'{tmp}/zref5.nc')
        self.dz = np.where(self.mask, self.elev - to_array(f'{tmp}/zref5.nc', 'z'), 0.0)
        self.tmp = tmp

    def mean5(self, x):
        return float((x * self.area).sum() / self.area.sum())

    def mean05(self, x05):
        return float((x05 * self.w05).sum() / self.w05.sum())


def recompute_day(ctx, var, gcm, alias, year, step_in_file, tmpd):
    """Independent 5' field of one day with cdo remapping and the physics coded here."""
    def remap(src_var, op):
        f = isimip_path(gcm, alias, src_var, year)
        t = nc.Dataset(f)['time']
        dates = nc.num2date(t[:], t.units, calendar=t.calendar, only_use_cftime_datetimes=True)
        first = [i for i, dd in enumerate(dates) if dd.year == year][0]
        out = f'{tmpd}/{src_var}_{op}.nc'
        cdo('-f', 'nc4', f'-{op},{ctx.griddes}', f'-seltimestep,{first + step_in_file + 1}', f, out)
        return to_array(out, src_var)
    if var == 'prec':
        return remap('pr', 'remapcon') * 86400.0, None
    if var in ('swdown', 'wind'):
        return remap({'swdown': 'rsds', 'wind': 'sfcwind'}[var], 'remapbil'), None
    tas = remap('tas', 'remapnn'); t1 = tas - 0.0065 * ctx.dz
    if var == 'tair':
        return t1 - 273.15, None
    ps = remap('ps', 'remapnn'); q = remap('huss', 'remapbil'); r = q / (1 - q)
    tvm = 0.5 * (tas + t1) * (1 + 0.61 * r)
    p = ps * np.exp(-ctx.dz * 9.80665 / (287.05 * tvm))
    if var == 'psurf':
        return p / 1000.0, None
    vp_kpa = np.minimum(r / (0.622 + r) * p / 1000.0, svp(t1 - 273.15))
    if var == 'vp':
        return vp_kpa, None
    # lwdown: Satterlund emissivity, e in hPa, T in K, ratio of the 5' and 0.5 degree levels
    rl = remap('rlds', 'remapbil')
    emis = lambda tk, e_hpa: 1.08 * (1.0 - np.exp(-e_hpa ** (tk / 2016.0)))
    e0 = np.minimum(r / (0.622 + r) * ps / 1000.0, svp(tas - 273.15)) * 10.0
    ratio = emis(t1, vp_kpa * 10.0) * t1 ** 4 / (emis(tas, e0) * tas ** 4)
    return ratio * rl, rl


CTX = None     # Context, set before the worker pool is forked


def verify_file(args):
    fn, var, gcm, alias, reports, figs, unit_dir, verifier = args
    ctx = CTX
    binding = qc.binding([fn], verifier)          # before the checks: the file that is checked
    d = nc.Dataset(fn); d.set_auto_mask(False)
    year = int(d.year); x = d[var]; units, srcs, (lo, hi), (kind, tol) = SPEC[var]
    res = {'file': os.path.basename(fn), 'variable': var, 'year': year, 'checked_at': provenance.utcnow(), 'checks': {}}
    C = res['checks']
    # structure
    filt = x.filters()
    C['structure'] = {'dims': list(x.dimensions), 'dtype': str(x.dtype), 'chunking': x.chunking(),
                      'zlib': filt.get('zlib'), 'complevel': filt.get('complevel'), 'shuffle': filt.get('shuffle'),
                      'fill_value': float(x._FillValue), 'units': x.units}
    C['structure']['ok'] = (list(x.dimensions) == ['time', 'lat', 'lon'] and x.dtype == np.float32
                            and x.chunking() == [1, len(ctx.lat), len(ctx.lon)] and filt.get('zlib')
                            and filt.get('complevel') == 5 and filt.get('shuffle') and x._FillValue == FILL
                            and x.units == units)
    # grid
    C['grid'] = {'lat_equal': bool(np.array_equal(d['lat'][:], ctx.lat)),
                 'lon_equal': bool(np.array_equal(d['lon'][:], ctx.lon))}
    C['grid']['ok'] = C['grid']['lat_equal'] and C['grid']['lon_equal']
    # time
    t = d['time']; n = len(t); nexp = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
    C['time'] = {'calendar': t.calendar, 'units': t.units, 'steps': n, 'expected_steps': nexp,
                 'continuous': bool(np.array_equal(t[:], np.arange(n)))}
    C['time']['ok'] = (t.calendar == 'proleptic_gregorian' and t.units == f'days since {year}-01-01 00:00:00'
                       and n == nexp and C['time']['continuous'])
    # source files (ISIMIP) for the mean check
    sd = {s: nc.Dataset(isimip_path(gcm, alias, s, year)) for s in set(srcs) | ({'tas'} if var == 'vp' else set())}
    tt = next(iter(sd.values()))['time']
    dates = nc.num2date(tt[:], tt.units, calendar=tt.calendar, only_use_cftime_datetimes=True)
    first = [i for i, dd in enumerate(dates) if dd.year == year][0]
    tair_f = None
    if var == 'vp':
        tp = os.path.join(os.path.dirname(unit_dir), 'tair', os.path.basename(fn).replace('vp_', 'tair_', 1))
        tair_f = nc.Dataset(tp) if os.path.exists(tp) else None
    mask_bad = range_bad = 0; mean_err = []; vmin, vmax = np.inf, -np.inf; supersat = 0; ncell = 0
    lapse = -0.0065 * ctx.mean5(ctx.dz)
    for k in range(n):
        a = x[k]
        fin = a != FILL
        if not np.array_equal(fin, ctx.mask) or not np.isfinite(a[ctx.mask]).all():
            mask_bad += 1
        v = a[ctx.mask].astype('f8'); vmin = min(vmin, v.min()); vmax = max(vmax, v.max())
        range_bad += int(((v < lo) | (v > hi)).sum())
        full = np.where(ctx.mask, a, 0.0).astype('f8')
        m5 = ctx.mean5(full)
        s05 = {s: np.array(sd[s][s][first + k], 'f8') for s in sd}
        if var == 'tair':
            m05 = ctx.mean05(s05['tas'] - 273.15); err = m5 - m05 - lapse
        elif var == 'prec':
            m05 = ctx.mean05(s05['pr'] * 86400.0); err = m5 / m05 - 1
        elif var == 'psurf':
            m05 = ctx.mean05(s05['ps'] / 1000.0); err = m5 / m05 - 1
        elif var == 'lwdown':
            m05 = ctx.mean05(s05['rlds']); err = m5 - m05
        elif var == 'vp':
            q = s05['huss']; r = q / (1 - q); m05 = ctx.mean05(r / (0.622 + r) * s05['ps'] / 1000.0); err = m5 / m05 - 1
        else:
            m05 = ctx.mean05(s05[srcs[0]]); err = m5 / m05 - 1
        mean_err.append(err)
        if tair_f is not None:
            ta = np.array(tair_f['tair'][k], 'f8')[ctx.mask]
            supersat += int((v > svp(ta) * (1 + SUPERSAT_RTOL)).sum()); ncell += v.size
    mean_err = np.array(mean_err)
    C['mask'] = {'days_with_mask_mismatch': mask_bad, 'ok': mask_bad == 0}
    C['range'] = {'bounds': [lo, hi], 'min': float(vmin), 'max': float(vmax), 'values_outside': range_bad,
                  'ok': range_bad == 0}
    C['mean'] = {'kind': {'lapse': 'difference minus lapse-rate term [K]', 'abs': f'difference [{units}]'}.get(
                     kind, 'relative difference'),
                 'tolerance': tol, 'max_abs': float(np.abs(mean_err).max()), 'annual_mean': float(mean_err.mean()),
                 'ok': bool(np.abs(mean_err).max() <= tol)}
    if var == 'tair':
        C['mean']['lapse_rate_term_K'] = lapse
    if var == 'vp':
        C['saturation'] = ({'cell_days_vp_gt_svp': supersat, 'cell_days': ncell, 'relative_tolerance': SUPERSAT_RTOL,
                            'ok': supersat == 0} if ncell else
                           {'note': 'tair file not found; not checked', 'ok': False})
    # sample days recomputed independently
    samples = {}; r1_dev = []; r1m_dev = []; dz_pool = []; dl_pool = []
    small = ctx.mask & (np.abs(ctx.dz) < R1_DZ_M); onem = ctx.mask & (np.abs(ctx.dz) < 1.0)
    with tempfile.TemporaryDirectory(dir=ctx.tmp) as tmpd:
        for k in (0, n // 2, n - 1):
            ref, rl = recompute_day(ctx, var, gcm, alias, year, k, tmpd)
            got = np.array(x[k], 'f8')
            diff = np.abs(got - ref)[ctx.mask]
            if var == 'prec':
                diff = diff / np.maximum(np.abs(ref[ctx.mask]), 1.0)
            if var == 'lwdown':
                diff = diff / np.abs(ref[ctx.mask])
                ratio = got / rl
                r1_dev.append(float(np.abs(ratio[small] - 1).max())); r1m_dev.append(float(np.abs(ratio[onem] - 1).max()))
                dz_pool.append(ctx.dz[ctx.mask] / 1000.0); dl_pool.append((got - rl)[ctx.mask])
            samples[str(k)] = float(diff.max())
            if k == n // 2:
                fig_day, fig_got, fig_ref = k, got, ref
    if var == 'lwdown':
        slope = float(np.polyfit(np.concatenate(dz_pool), np.concatenate(dl_pool), 1)[0])
        C['lwdown_physics'] = {
            'r_equals_1': {'dz_abs_below_m': R1_DZ_M, 'cells': int(small.sum()), 'max_abs_r_minus_1': max(r1_dev),
                           'tolerance': R1_TOL, 'ok': max(r1_dev) <= R1_TOL},
            'max_abs_r_minus_1_for_dz_abs_below_1m': max(r1m_dev),
            'slope_lwdown_minus_rlds_on_dz_W_m2_per_km': slope, 'slope_expected_range': [-50, -25],
            'slope_note': 'reported, not checked; Marty et al. (2002) observed -29 W m-2 km-1 in the Alps'}
        C['lwdown_physics']['ok'] = C['lwdown_physics']['r_equals_1']['ok']
    stol = 1e-5 if var == 'prec' else LWDOWN_SAMPLE_RTOL if var == 'lwdown' else SAMPLE_TOL
    C['sample_days'] = {'max_abs_diff_by_day_index': samples, 'tolerance': stol,
                        'ok': all(v <= stol for v in samples.values())}
    ok = all(c.get('ok', True) for c in C.values())
    status = 'passed' if ok else 'failed'
    res['status'] = status
    # figure: 0.5 degree input versus 5' output on the middle day, global and one mountain zoom
    s = srcs[0] if var != 'vp' else 'ps'
    conv = {'tair': lambda z: z - 273.15, 'prec': lambda z: z * 86400.0, 'psurf': lambda z: z / 1000.0}.get(var, lambda z: z)
    if var == 'vp':
        q = np.array(sd['huss']['huss'][first + fig_day], 'f8'); r = q / (1 - q)
        c05 = r / (0.622 + r) * np.array(sd['ps']['ps'][first + fig_day], 'f8') / 1000.0
    else:
        c05 = conv(np.array(sd[s][s][first + fig_day], 'f8'))
    c05 = np.where(ctx.w05 > 0, c05, np.nan)
    f5 = np.where(ctx.mask, fig_got, np.nan)
    vals = f5[ctx.mask]; vlo, vhi = np.percentile(vals, [1, 99])
    cmap = {'prec': 'YlGnBu', 'tair': 'RdYlBu_r'}.get(var, 'viridis')
    fig, axs = plt.subplots(2, 2, figsize=(16, 9))
    ext05 = [-180, 180, -90, 90]; ext5 = [-180, 180, ctx.lat[0] - 1 / 24, ctx.lat[-1] + 1 / 24]
    date = f'{year}-{fig_day + 1:03d} (day of year)'
    for ax, fld, ext, orig, ttl in ((axs[0, 0], c05, ext05, 'upper', f'ISIMIP 0.5° input, cells with active VIC cells'),
                                    (axs[0, 1], f5, ext5, 'lower', '5′ forcing, active domain cells')):
        im = ax.imshow(fld, origin=orig, extent=ext, cmap=cmap, vmin=vlo, vmax=vhi, interpolation='nearest')
        ax.set_ylim(-56, 84); ax.set_title(f'{var} [{units}] {ttl}\n{date}', fontsize=9); fig.colorbar(im, ax=ax, fraction=0.025)
    zoom = (80, 100, 25, 40)    # Himalaya / Tibetan Plateau
    for ax, fld, ext, orig, ttl in ((axs[1, 0], c05, ext05, 'upper', '0.5° input'), (axs[1, 1], f5, ext5, 'lower', '5′ forcing')):
        sub = fld
        im = ax.imshow(sub, origin=orig, extent=ext, cmap=cmap, interpolation='nearest',
                       vmin=np.nanpercentile(f5[(ctx.lat[:, None] > zoom[2]) & (ctx.lat[:, None] < zoom[3])
                                                & (ctx.lon[None, :] > zoom[0]) & (ctx.lon[None, :] < zoom[1])], 1),
                       vmax=np.nanpercentile(f5[(ctx.lat[:, None] > zoom[2]) & (ctx.lat[:, None] < zoom[3])
                                                & (ctx.lon[None, :] > zoom[0]) & (ctx.lon[None, :] < zoom[1])], 99))
        ax.set_xlim(zoom[0], zoom[1]); ax.set_ylim(zoom[2], zoom[3])
        ax.set_title(f'{var} [{units}] {ttl}, Himalaya zoom, {date}', fontsize=9); fig.colorbar(im, ax=ax, fraction=0.025)
    for ax in axs.flat:
        ax.set_facecolor('#dddddd')
    fig.suptitle(f'{os.path.basename(fn)}: {status}', fontsize=11); fig.tight_layout()
    fig.savefig(f'{figs}/verify_{year}.png', dpi=110); plt.close(fig)
    for dd in sd.values():
        dd.close()
    if tair_f is not None:
        tair_f.close()
    d.close()
    res['binding'] = binding
    qc.write_json(f'{reports}/verify_{year}.json', res)
    return var, year, status


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--gcm', required=True, choices=list(GCM_DIR))
    ap.add_argument('--alias', required=True)
    ap.add_argument('--variables', required=True, help='comma-separated VIC variables')
    ap.add_argument('--years', default=None, help='single year or START-END (default: every file of the unit)')
    ap.add_argument('--scratch', action='store_true', help='verify the test output under scratch/climate-forcing/')
    ap.add_argument('--scratch-label', default=None, help='with --scratch: scratch/climate-forcing/runs/<label>/')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    ap.add_argument('--processes', type=int, default=None)
    a = ap.parse_args()
    variables = a.variables.split(',')
    if a.scratch:
        os.environ.setdefault('TMPDIR', f'{W}/scratch/climate-forcing/tmp')
    os.makedirs(os.environ.get('TMPDIR', tempfile.gettempdir()), exist_ok=True)
    pdir = f'{W}/parameters/{a.parameter_status}/{a.parameter_set}'
    tmp = tempfile.mkdtemp(prefix='verify-climate-')
    global CTX
    ctx = CTX = Context(f'{pdir}/domain/vic_global_5min_domain_nogl.nc',
                  f'{pdir}/bundle/vic_global_5min_natural_static_root-b-zeng2001.nc', tmp)
    verifier = qc.verifier_state(REPO, 'workflow/04_forcing/climate')
    jobs, dirs = [], {}
    for v in variables:
        unit = f'climate/{a.gcm}/{a.alias}/{v}'
        sbase = f'{W}/scratch/climate-forcing' + (f'/runs/{a.scratch_label}' if a.scratch_label else '')
        unit_dir = f'{sbase}/{a.gcm}/{a.alias}/{v}' if a.scratch else f'{W}/forcing/{unit}'
        qc_dir = f'{unit_dir}/qc' if a.scratch else f'{W}/qc/forcing/{unit}'
        reports, figs = f'{qc_dir}/reports', f'{qc_dir}/figures'
        os.makedirs(reports, exist_ok=True); os.makedirs(figs, exist_ok=True)
        files = sorted(glob.glob(f'{unit_dir}/{v}_{a.gcm}_{a.alias}_*.nc'))
        if a.years:
            y = a.years.split('-'); want = set(range(int(y[0]), int(y[-1]) + 1))
            files = [f for f in files if int(f[:-3].rsplit('_', 1)[1]) in want]
        if not files:
            raise SystemExit(f'no files for {v} in {unit_dir}')
        dirs[v] = (unit, unit_dir, qc_dir)
        jobs += [(f, v, a.gcm, a.alias, reports, figs, unit_dir, verifier) for f in files]
    checked = set()
    with Pool(a.processes or min(len(jobs), 8)) as pool:
        for v, yr, st in pool.imap_unordered(verify_file, jobs):
            checked.add((v, yr))
            print(f'{v} {yr}: {st}', flush=True)
    unit_status = []
    for v, (unit, unit_dir, qc_dir) in dirs.items():
        per_year = {}
        for f in sorted(glob.glob(f'{unit_dir}/{v}_{a.gcm}_{a.alias}_*.nc')):
            yr = int(f[:-3].rsplit('_', 1)[1])
            per_year[yr] = qc.report_status(f'{qc_dir}/reports/verify_{yr}.json', [f], verifier, (v, yr) in checked)
        vals = list(per_year.values())
        status = qc.combine(vals); unit_status.append(status)
        summary = {'object': f'forcing/{unit}' if not a.scratch else os.path.relpath(unit_dir, W), 'status': status,
                   'checked_by': CHECKED_BY, 'updated_at': provenance.utcnow(), 'files': len(vals),
                   **{s: vals.count(s) for s in ('passed', 'warning', 'failed', 'not_checked')},
                   'per_year': {str(k): s for k, s in sorted(per_year.items())}}
        qc.write_summary(qc_dir, summary)
        prov_path = f'{unit_dir}/provenance.yaml'
        if os.path.exists(prov_path):
            provenance.set_qc(prov_path, status, os.path.relpath(qc_dir, W))
        print(f'{unit}: {status} ({summary["passed"]} passed, {summary["warning"]} warning, {summary["failed"]} failed, '
              f'{summary["not_checked"]} not checked)')
    shutil.rmtree(tmp, ignore_errors=True)
    qc.exit_with(qc.combine(unit_status))


if __name__ == '__main__':
    main()
