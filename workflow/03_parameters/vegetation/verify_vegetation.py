#!/usr/bin/env python3
"""Independent verification of the 16-class vegetation component written by build_vegetation.py.

Checks (each with its own status; the component passes only when all pass):
  cv_closure          active cells: Cv finite, >= 0, |sum - 1| <= 1e-12; inactive cells: Cv NaN
  nveg                Nveg = number of tiles (Cv > 0) among classes 1-15; tiles in [Nveg, Nveg + 1]; -1 off the domain
  forcing_tiles       for every coverage file of the five land-use units (re-read here): coverage > 0 only on tiles
  complete_parameters every tile has finite values of every vegetation parameter, all months and root zones
  ranges              physical bounds on tiles (BOUNDS below); fcanopy > 1e-4 (VIC MIN_FCANOPY, strict);
                      root_fract sums to 1 per tile (1e-6) for classes 1-15 (class 16 is bare soil without
                      roots); albedo = 0 is counted and reported (inherited from the base bundle)
  base_unchanged      base-bundle tiles keep the base Cv (to 1e-10) and every base parameter, except fcanopy raised
                      to the floor where it was below
  added_tiles         added tiles = tiles not in the base; their Cv is the placeholder (< 2e-12), backfill_level > 0
                      exactly on them, and every parameter equals that of the donor recorded in backfill_tiles.csv,
                      which is a base tile of the same class; level 2 donors within 500 km, level 3 donors of the
                      same Koppen class
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/added_tiles.png, where <qc> is
qc/parameters/<status>/<set>/vegetation/ (or <component-dir>/qc/ with --component-dir), and sets qc.status in the
component's provenance.yaml (not with --component-dir). Exit status: 0 passed, 1 failed (common/qc.py).

Usage: verify_vegetation.py [--parameter-set ID] [--parameter-status candidates] [--component-dir DIR] [--processes 16]
"""
import argparse, csv, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

from common import provenance, qc, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_vegetation as bv   # noqa: E402  (names and constants only; every check is computed here)

# inclusive physical bounds on tiles; fcanopy is checked separately (> 1e-4 and <= 1)
BOUNDS = {'LAI': (0, 20), 'albedo': (0, 1), 'displacement': (0, 100), 'veg_rough': (0, 50), 'root_depth': (0, 20),
          'root_fract': (0, 1), 'overstory': (0, 1), 'rarc': (0, 1000), 'rmin': (0, 10000), 'RGL': (0, 1000),
          'rad_atten': (0, 1), 'wind_atten': (0, 1), 'trunk_ratio': (0, 1), 'wind_h': (0, 100)}
_SHARED = {}


def _violations(path):
    """Per-class count of cells with coverage > 0 but no tile, for one coverage file."""
    with nc.Dataset(path) as d:
        cov = np.nan_to_num(d['coverage'][0].filled(np.nan))
    tiles = _SHARED['tiles']
    return [int(((cov[k] > 0) & ~tiles[k]).sum()) for k in range(cov.shape[0])]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--component-dir', default=None, help='verify a component in this directory (scratch test)')
    ap.add_argument('--processes', type=int, default=16)
    a = ap.parse_args(); W = workdir.root()
    pset = f'{W}/parameters/{a.parameter_status}/{a.parameter_set}'
    rel_obj = f'parameters/{a.parameter_status}/{a.parameter_set}/vegetation'
    comp = a.component_dir or f'{W}/{rel_obj}'
    qc_dir = f'{comp}/qc' if a.component_dir else f'{W}/qc/{rel_obj}'
    os.makedirs(f'{qc_dir}/reports', exist_ok=True); os.makedirs(f'{qc_dir}/figures', exist_ok=True)
    prov = provenance.read(f'{comp}/provenance.yaml')
    with nc.Dataset(f'{pset}/{bv.DOMAIN}') as d:
        mask = d['mask'][:].filled(0).astype(bool); lat = d['lat'][:].filled(np.nan); lon = d['lon'][:].filled(np.nan)
    v = nc.Dataset(f'{comp}/{bv.OUT_NAME}'); v.set_auto_mask(False)
    b = nc.Dataset(f'{W}/{prov["inputs"]["base_bundle"]}'); b.set_auto_mask(False)
    checks = {}

    # ---- Cv and Nveg
    cv = v['Cv'][:]; s = np.nansum(cv, axis=0); tiles = np.nan_to_num(cv) > 0
    act = cv[:, mask]
    checks['cv_closure'] = {'max_abs_sum_minus_1': float(np.abs(s[mask] - 1).max()), 'nan_active': int(np.isnan(act).sum()),
                            'negative_active': int((act < 0).sum()), 'finite_inactive': int(np.isfinite(cv[:, ~mask]).sum())}
    c = checks['cv_closure']
    c['status'] = 'passed' if c['max_abs_sum_minus_1'] <= 1e-12 and c['nan_active'] == c['negative_active'] == c['finite_inactive'] == 0 else 'failed'
    nveg = v['Nveg'][:]; n15 = tiles[:15].sum(axis=0); nall = tiles.sum(axis=0)
    checks['nveg'] = {'cells_nveg_ne_tiles_1_15': int((mask & (nveg != n15)).sum()),
                      'cells_tiles_outside_nveg_nveg_plus_1': int((mask & ((nall < nveg) | (nall > nveg + 1))).sum()),
                      'inactive_not_minus_1': int((~mask & (nveg != -1)).sum()), 'nveg_max': int(nveg[mask].max()),
                      'tiles_total': int(tiles.sum())}
    c = checks['nveg']
    c['status'] = 'passed' if c['cells_nveg_ne_tiles_1_15'] == c['cells_tiles_outside_nveg_nveg_plus_1'] == c['inactive_not_minus_1'] == 0 else 'failed'
    del cv, act

    # ---- every forcing tile is a parameter tile (all files of all five units, re-read here)
    files = []
    for soc in bv.SOC:
        u = f'{W}/forcing/landuse/{soc}'
        files += [(soc, f'{u}/{f}') for f in sorted(os.listdir(u)) if f.startswith(f'coverage_{soc}_') and f.endswith('.nc')]
    _SHARED['tiles'] = tiles
    per_soc = {soc: {'files': 0, 'violations_by_class': [0] * bv.NCLASS} for soc in bv.SOC}
    with ProcessPoolExecutor(a.processes, mp_context=get_context('fork')) as ex:   # fails at once if a worker dies
        for (soc, _), viol in zip(files, ex.map(_violations, [p for _, p in files], chunksize=4)):
            per_soc[soc]['files'] += 1
            per_soc[soc]['violations_by_class'] = [x + y for x, y in zip(per_soc[soc]['violations_by_class'], viol)]
    total = sum(sum(p['violations_by_class']) for p in per_soc.values())
    checks['forcing_tiles'] = {'per_soc': per_soc, 'files': len(files), 'violations': total,
                               'status': 'passed' if total == 0 and len(files) == 172 * 2 + 79 * 3 else 'failed'}

    # ---- parameters per class
    added = np.zeros(tiles.shape, bool); ab = v['added_tile_bits'][:]
    for k in range(bv.NCLASS):
        added[k] = ((ab >> np.uint16(k)) & 1).astype(bool)
    base_cv = np.nan_to_num(b['Cv'][:]); base_tiles = base_cv > 0
    rows = {k: [] for k in range(1, bv.NCLASS + 1)}
    with open(f'{comp}/backfill_tiles.csv') as fh:
        for r in csv.DictReader(fh):
            rows[int(r['class'])].append((int(r['row']), int(r['col']), int(r['level']), int(r['donor_row']), int(r['donor_col']),
                                          float(r['distance_km']), int(r['koppen']), int(r['donor_koppen'])))
    comp_c = {'tiles_missing_values': {}}; rng = {}; base_c = {}; add_c = {'by_class': {}}
    fail_complete = fail_range = fail_base = fail_add = False
    for k in range(bv.NCLASS):
        t = tiles[k]; kk = str(k + 1)
        if not t.any():
            continue
        missing = 0; rng[kk] = {}; base_c[kk] = {}
        lev = v['backfill_level'][k]
        R = np.array(rows[k + 1], dtype='f8').reshape(-1, 8)
        tr, tc, lv, dr, dc = (R[:, i].astype(int) for i in range(5))
        for f in bv.FIELDS:
            x = v[f][k]; xb = b[f][k]
            fin = np.isfinite(x).all(axis=0) if x.ndim == 3 else np.isfinite(x)
            missing += int((t & ~fin).sum())
            xt = x[..., t]
            if f == 'fcanopy':
                rng[kk][f] = [float(np.nanmin(xt)), float(np.nanmax(xt))]
                bad = int(((xt <= 1e-4) | (xt > 1)).sum())
            else:
                lo, hi = BOUNDS[f]; rng[kk][f] = [float(np.nanmin(xt)), float(np.nanmax(xt))]
                bad = int(((xt < lo) | (xt > hi)).sum())
            if f == 'root_fract' and k < 15:                 # class 16 is bare soil: no roots, not checked by VIC
                sm = xt.sum(axis=0); rng[kk]['root_fract_sum'] = [float(sm.min()), float(sm.max())]
                bad += int((np.abs(sm - 1) > 1e-6).sum())
            if f == 'albedo':                                   # reported, not a failure: inherited from the base
                rng[kk]['albedo_zero_tile_months'] = int((xt == 0).sum())
            if f == 'overstory':
                bad += int((~np.isin(xt, (0, 1))).sum())
            rng[kk][f + '_out_of_bounds'] = bad; fail_range |= bad > 0
            # base tiles unchanged (fcanopy: raised to the floor only where below)
            bt = base_tiles[k]
            exp = np.where(np.isfinite(xb) & (xb < bv.FCANOPY_FLOOR), bv.FCANOPY_FLOOR, xb) if f == 'fcanopy' else xb
            diff = int((~(x[..., bt] == exp[..., bt])).sum())
            base_c[kk][f] = diff; fail_base |= diff > 0
            # added tiles copy their donor
            same = x[..., tr, tc] == x[..., dr, dc]         # the donor's own value (fcanopy floored on both)
            nd = int((~same).sum()); add_c['by_class'].setdefault(kk, {})[f'{f}_differs_from_donor'] = nd; fail_add |= nd > 0
        comp_c['tiles_missing_values'][kk] = missing; fail_complete |= missing > 0
        cvk = np.nan_to_num(v['Cv'][k])
        base_c[kk]['Cv_max_abs_diff'] = float(np.abs(cvk[base_tiles[k]] - base_cv[k][base_tiles[k]]).max()) if base_tiles[k].any() else 0.0
        fail_base |= base_c[kk]['Cv_max_abs_diff'] > 1e-10
        ad = added[k]; cnt = add_c['by_class'][kk]
        cnt.update({'added': int(ad.sum()), 'added_equals_tiles_minus_base': bool(np.array_equal(ad, t & ~base_tiles[k])),
                    'added_cv_max': float(cvk[ad].max()) if ad.any() else 0.0,
                    'level_where_not_added': int(((lev > 0) & ~ad).sum()), 'added_without_level': int((ad & (lev == 0)).sum()),
                    'csv_rows': len(tr), 'csv_rows_not_added': int((~ad[tr, tc]).sum()) if len(tr) else 0,
                    'donor_not_base_tile': int((~base_tiles[k][dr, dc]).sum() if len(tr) else 0) - int((lv == 1).sum()),
                    'level2_beyond_radius': int(((lv == 2) & (R[:, 5] > bv.RADIUS_KM)).sum()),
                    'level3_koppen_differs': int(((lv == 3) & (R[:, 6] != R[:, 7])).sum()),
                    'levels': {f'L{L}': int((lev == L).sum()) for L in bv.LEVELS},
                    'csv_levels_match': all(int((lv == L).sum()) == int((lev == L).sum()) for L in bv.LEVELS)})
        fail_add |= not (cnt['added_equals_tiles_minus_base'] and cnt['csv_levels_match'] and cnt['added_cv_max'] < 2e-12
                         and cnt['level_where_not_added'] == cnt['added_without_level'] == cnt['csv_rows_not_added'] == 0
                         and cnt['donor_not_base_tile'] == cnt['level2_beyond_radius'] == cnt['level3_koppen_differs'] == 0
                         and cnt['csv_rows'] == cnt['added'])
        print(f'class {k + 1}: checked', flush=True)
    checks['complete_parameters'] = {**comp_c, 'status': 'failed' if fail_complete else 'passed'}
    checks['ranges'] = {'bounds': BOUNDS, 'fcanopy': '(1e-4, 1]', 'by_class': rng, 'status': 'failed' if fail_range else 'passed'}
    checks['base_unchanged'] = {'differences_by_class': base_c, 'status': 'failed' if fail_base else 'passed'}
    checks['added_tiles'] = {**add_c, 'status': 'failed' if fail_add else 'passed'}

    # ---- figure: added tiles by donor level (highest level over classes)
    lv_map = np.zeros(mask.shape, np.int8)
    for k in range(bv.NCLASS):
        lv_map = np.maximum(lv_map, v['backfill_level'][k])
    fig, ax = plt.subplots(figsize=(14, 6.5))
    ax.imshow(np.where(mask, 0, np.nan), origin='lower', extent=[-180, 180, lat[0], lat[-1]], cmap='Greys', vmin=0, vmax=4,
              interpolation='nearest')
    cols = ['#009E73', '#0072B2', '#E69F00', '#D55E00', '#000000']
    im = ax.imshow(np.where(lv_map > 0, lv_map, np.nan), origin='lower', extent=[-180, 180, lat[0], lat[-1]],
                   cmap=mcolors.ListedColormap(cols), norm=mcolors.BoundaryNorm(np.arange(0.5, 6), 5), interpolation='nearest')
    cb = fig.colorbar(im, ax=ax, fraction=0.02, ticks=range(1, 6)); cb.ax.set_yticklabels([f'L{L} {n}' for L, n in bv.LEVELS.items()], fontsize=7)
    ax.set_title(f'cells with tiles added for the land-use union, highest donor level ({int(added.sum()):,} tiles)', loc='left', fontsize=10)
    fig.tight_layout(); fig.savefig(f'{qc_dir}/figures/added_tiles.png', dpi=130); plt.close(fig)

    status = qc.combine(c['status'] for c in checks.values())
    now = provenance.utcnow()
    qc.write_json(f'{qc_dir}/reports/verify.json', {'object': rel_obj, 'checked_at': now, 'checks': checks})
    summary = {'object': rel_obj if not a.component_dir else os.path.relpath(comp, W), 'status': status,
               'checked_by': 'workflow/03_parameters/vegetation/verify_vegetation.py', 'updated_at': now,
               'checks': {n: c['status'] for n, c in checks.items()}}
    qc.write_summary(qc_dir, summary)
    if not a.component_dir:
        provenance.set_qc(f'{comp}/provenance.yaml', status, f'qc/{rel_obj}')
    print(json.dumps(summary, indent=1))
    qc.exit_with(status)


if __name__ == '__main__':
    main()
