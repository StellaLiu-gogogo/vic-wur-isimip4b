#!/usr/bin/env python3
"""Independent verification of the adopted domain file of a parameter set (component `domain`, read by VIC with
DOMAIN; drivers/shared_image/src/get_global_domain.c at VIC 39e21ff5).

Checks (each with its own status; the component passes only when all pass):
  integrity      md5 and size of the file equal the manifest; not modified after adoption (see adopted.py)
  vic_variables  mask (int), area, frac (lat, lon) and lat (lat), lon (lon) present; lat 1680, lon 4320
  grid           lat and lon strictly monotonic with a constant step of 1/12 degree, cell centres at
                 k/12 + 1/24 degree; lon within [-180, 180] (VIC wraps other longitudes)
  forcing_grid   lat and lon equal exactly those of the first file of every forcing unit under forcing/
                 (every directory with a provenance.yaml)
  mask           only the values 0 and 1, and ACTIVE_CELLS cells with 1 (D08: the domain is fixed)
  area           area > 0, finite and not fill on every active cell, and within AREA_TOLERANCE (relative) of an
                 own cell area: the spherical cell area R^2 dlon (sin lat_n - sin lat_s) with the authalic radius
                 R = 6 371 007.2 m, and the WGS84 ellipsoidal cell area; the file passes when every active cell is
                 within the tolerance of at least one of them, the report says which one fits
  frac           frac in [0, 1], finite and not fill on every active cell; number of cells with frac < 1 and = 0
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{area_deviation,frac}.png, where <qc> is
qc/parameters/<status>/<set>/domain/.

Usage: verify_domain.py [--parameter-set ID] [--parameter-status candidates]
"""
import glob, os, sys

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import adopted   # noqa: E402

ACTIVE_CELLS = 2188551          # D08 and the manifest (run_cell of the bundle equals the mask on these cells)
STEP = 1.0 / 12.0
AREA_TOLERANCE = 1e-3           # relative
R_AUTHALIC = 6371007.2          # m, authalic radius of WGS84
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
VIC_READS = {'mask': (('lat', 'lon'), 'i'), 'area': (('lat', 'lon'), 'f'), 'frac': (('lat', 'lon'), 'f'),
             'lat': (('lat',), 'f'), 'lon': (('lon',), 'f')}


def edges(centres, step):
    return centres - step / 2, centres + step / 2


def sphere_area(lat, lon, step=STEP, r=R_AUTHALIC):
    """Cell area (m2) on a sphere of radius r, (lat, lon) array."""
    s, n = np.radians(edges(np.asarray(lat, 'f8'), step))
    band = np.abs(r * r * np.radians(step) * (np.sin(n) - np.sin(s)))
    return np.repeat(band[:, None], len(lon), axis=1)


def ellipsoid_area(lat, lon, step=STEP, a=WGS84_A, f=WGS84_F):
    """Cell area (m2) on the WGS84 ellipsoid: b^2 dlon / 2 [q(lat_n) - q(lat_s)] with
    q(x) = sin x / (1 - e^2 sin^2 x) + ln((1 + e sin x) / (1 - e sin x)) / (2 e)."""
    e2 = f * (2 - f); e = np.sqrt(e2); b2 = a * a * (1 - e2)

    def q(x):
        s = np.sin(x)
        return s / (1 - e2 * s * s) + np.log((1 + e * s) / (1 - e * s)) / (2 * e)
    s, n = np.radians(edges(np.asarray(lat, 'f8'), step))
    band = np.abs(b2 * np.radians(step) / 2 * (q(n) - q(s)))
    return np.repeat(band[:, None], len(lon), axis=1)


def grid_check(lat, lon, step=STEP):
    res = {}
    for name, c in (('lat', lat), ('lon', lon)):
        d = np.diff(c)
        k = (c - step / 2) / step
        order = 'increasing' if (d > 0).all() else 'decreasing' if (d < 0).all() else 'not monotonic'
        res[name] = {'n': int(c.size), 'first': float(c[0]), 'last': float(c[-1]), 'order': order,
                     'max_step_error_deg': float(np.abs(np.abs(d) - step).max()),
                     'max_centre_offset_deg': float(np.abs(k - np.round(k)).max() * step)}
    ok = all(r['order'] != 'not monotonic' and r['max_step_error_deg'] < 1e-9 and r['max_centre_offset_deg'] < 1e-9
             for r in res.values())
    ok &= bool(lon.min() >= -180 and lon.max() <= 180)
    return {**res, 'status': 'passed' if ok else 'failed'}


def forcing_units(W):
    return sorted({os.path.dirname(p) for depth in range(2, 6)
                   for p in glob.glob(f'{W}/forcing/' + '*/' * depth + 'provenance.yaml')})


def forcing_grid_check(W, lat, lon):
    units = []; bad = []
    for u in forcing_units(W):
        files = sorted(glob.glob(f'{u}/*.nc'))
        rel = os.path.relpath(u, W)
        if not files:
            units.append({'unit': rel, 'file': None}); continue
        with nc.Dataset(files[0]) as d:
            eq = bool(np.array_equal(adopted.raw(d, 'lat'), lat) and np.array_equal(adopted.raw(d, 'lon'), lon))
        units.append({'unit': rel, 'file': os.path.basename(files[0]), 'equal': eq})
        if not eq:
            bad.append(rel)
    checked = [x for x in units if x.get('file')]
    status = 'failed' if bad else 'passed' if checked else 'not_checked'
    return {'units': units, 'units_checked': len(checked), 'units_differ': bad, 'status': status}


def area_check(dom):
    m = dom['mask']; area = dom['area']
    bad = adopted.is_fill(area, dom['area_fill']) | ~(area > 0)
    ref = {'sphere': sphere_area(dom['lat'], dom['lon']), 'wgs84_ellipsoid': ellipsoid_area(dom['lat'], dom['lon'])}
    dev = {k: np.where(m & ~bad, area / r - 1, np.nan) for k, r in ref.items()}
    best = np.fmin(np.abs(dev['sphere']), np.abs(dev['wgs84_ellipsoid']))
    res = {'active_cells_fill_or_not_positive': int((m & bad).sum()), 'tolerance_relative': AREA_TOLERANCE,
           'stored_dtype': 'float32',
           'area_m2_active': adopted.stats(area[m & ~bad])}
    for k, d in dev.items():
        a = np.abs(d[m & ~bad])
        res[f'relative_deviation_{k}'] = {'max_abs': float(a.max()), 'mean_abs': float(a.mean()),
                                         'mean': float(d[m & ~bad].mean()),
                                         'cells_beyond_tolerance': int((a > AREA_TOLERANCE).sum())}
    res['fits'] = min(dev, key=lambda k: res[f'relative_deviation_{k}']['max_abs'])
    res['cells_beyond_tolerance_of_both'] = int((best[m & ~bad] > AREA_TOLERANCE).sum())
    ok = res['active_cells_fill_or_not_positive'] == 0 and res['cells_beyond_tolerance_of_both'] == 0
    res['status'] = 'passed' if ok else 'failed'
    return res, dev[res['fits']]


def frac_check(dom):
    m = dom['mask']; f = dom['frac']
    bad = adopted.is_fill(f, dom['frac_fill'])
    v = f[m & ~bad]
    res = {'active_cells_fill': int((m & bad).sum()), 'active_cells_outside_0_1': int(((v < 0) | (v > 1)).sum()),
           'active_cells_below_1': int((v < 1).sum()), 'active_cells_0': int((v == 0).sum()),
           'frac_active': adopted.stats(v),
           'cells_outside_mask_not_fill': int((~m & ~bad).sum())}
    ok = res['active_cells_fill'] == 0 and res['active_cells_outside_0_1'] == 0
    res['status'] = 'passed' if ok else 'failed'
    return res


def main():
    run = adopted.Run('domain', __doc__.splitlines()[0])
    path = f'{run.pset}/{adopted.DOMAIN}'
    checks = {'integrity': run.integrity('domain')}
    with nc.Dataset(path) as d:
        checks['vic_variables'] = adopted.variables_check(d, VIC_READS, {'lat': 1680, 'lon': 4320})
    dom = adopted.read_domain(path)
    checks['grid'] = grid_check(dom['lat'], dom['lon'])
    checks['forcing_grid'] = forcing_grid_check(run.W, dom['lat'], dom['lon'])
    mr = dom['mask_raw']
    vals, counts = np.unique(mr, return_counts=True)
    n = int(dom['mask'].sum())
    checks['mask'] = {'values': {str(int(v)): int(c) for v, c in zip(vals, counts)}, 'active_cells': n,
                      'expected_active_cells': ACTIVE_CELLS,
                      'status': 'passed' if set(vals.tolist()) <= {0, 1} and n == ACTIVE_CELLS else 'failed'}
    checks['area'], dev = area_check(dom)
    checks['frac'] = frac_check(dom)
    adopted.save_map(f'{run.qc}/figures/area_deviation.png', dev, dom['lat'], dom['lon'],
                     f'domain area / {checks["area"]["fits"]} cell area - 1 (active cells)', 'relative deviation',
                     cmap='RdBu_r', vmin=-AREA_TOLERANCE, vmax=AREA_TOLERANCE)
    adopted.save_map(f'{run.qc}/figures/frac.png', np.where(dom['mask'], dom['frac'], np.nan), dom['lat'],
                     dom['lon'], 'domain frac (active cells)', 'frac', vmin=0, vmax=1)
    run.finish([adopted.DOMAIN], checks, 'workflow/03_parameters/domain/verify_domain.py')


if __name__ == '__main__':
    main()
