#!/usr/bin/env python3
"""Independent verification of a land-use forcing unit produced by isimip_landuse_to_vic_annual.py.

For every coverage_<soc>_<year>.nc of the unit (or the years given), the targets are re-derived from the
ISIMIP files with a separate code path and compared: closure, per-class parent conservation, global totals,
tile counts, and a comparison with the VIC coverage dataset of the same year when it exists. Writes
  qc/forcing/landuse/<soc>/reports/verify_<year>.json   and   .../figures/verify_<year>.png
  qc/forcing/landuse/<soc>/summary.json                 (per-year status, unit status)
and sets qc.status in the unit's provenance.yaml to `passed` when every file of the unit has a passing
verification, `failed` when any file fails, and leaves `not_checked` while the unit is only partly verified.

Pass criteria per file: max |sum(Cv) - 1| <= 1e-6 on active cells, no negative or NaN active values, no finite
inactive values, conservation error <= 1e-3 km2 for every parent within capacity, and no area allocated where
the target is zero.

Usage: verify_forcing.py --scenario histsoc [--years 1850-2021] [--unit-dir DIR]
  --unit-dir overrides the unit location (for outputs written to scratch by a dirty repository); results then
  go to <unit-dir>/qc/ and provenance is not updated.
"""
import argparse, datetime, json, os, sys

import numpy as np
import netCDF4 as nc
import yaml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

WORKDIR = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
RAW = f'{WORKDIR}/raw/ISIMIP4b/InputData/socioeconomic/landuse'
COVERAGE = f'{WORKDIR}/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_{{y}}.nc'
R = 6371000.0
FILES = {'histsoc': ('histsoc', 'histsoc', 1850), '1850soc': ('1850soc', '1850soc', 1850), '2021soc': ('2021soc', '2021soc', 2022),
         'ssp1vlsoc-noadapt': ('ssp1vlsoc-noadapt', 'ssp1vl', 2022), 'ssp3hsoc-noadapt': ('ssp3hsoc-noadapt', 'ssp3h', 2022)}
TOL_CLOSURE, TOL_CONS_KM2 = 1e-6, 1e-3


def verify_file(fn, scen, f_dom, out_reports, out_figs):
    d = nc.Dataset(fn); yr = int(d.year); cov = d['coverage'][0].filled(np.nan).astype('f8'); vlat = d['lat'][:]; vlon = d['lon'][:]; d.close()
    dom = nc.Dataset(f_dom); mask = dom['mask'][:].filled(0).astype(bool); dom.close(); NY, NX = mask.shape; NB = (NY // 3, NX // 3)
    A5 = ((R ** 2) * np.deg2rad(1 / 12.) * (np.sin(np.deg2rad(vlat + 1 / 24.)) - np.sin(np.deg2rad(vlat - 1 / 24.))))[:, None] * np.ones((1, NX))
    land = np.where(mask, A5, 0)
    psum = lambda x: x.reshape(NB[0], 3, NB[1], 3).sum(axis=(1, 3))
    sub, tag, y0 = FILES[scen]; span = '1850_2021' if y0 == 1850 else '2022_2100'; t = yr - y0
    f15 = nc.Dataset(f'{RAW}/{sub}/landuse-15crops_{tag}_15arcmin_annual_{span}.nc'); fu = nc.Dataset(f'{RAW}/{sub}/landuse-urbanareas_{tag}_15arcmin_annual_{span}.nc')
    ilat = f15['lat'][:]; A15 = ((R ** 2) * np.deg2rad(0.25) * (np.sin(np.deg2rad(ilat + 0.125)) - np.sin(np.deg2rad(ilat - 0.125))))[:, None] * np.ones((1, 1440))
    S = lambda x: (x * A15)[24:584][::-1]
    rf = S(sum(f15[v][t].filled(0).astype('f8') for v in f15.variables if '_rainfed' in v))
    ir = sum(f15[v][t].filled(0).astype('f8') for v in f15.variables if '_irrigated' in v); rc = f15['rice_irrigated'][t].filled(0).astype('f8')
    T = {12: rf, 15: S(rc), 14: S(ir - rc), 13: S(fu['urbanareas'][t].filled(0).astype('f8'))}; f15.close(); fu.close()
    capn = psum(land); tot = sum(T.values())
    c = np.nan_to_num(cov); s = c.sum(axis=0)
    res = {'file': os.path.basename(fn), 'scenario': scen, 'year': yr, 'checked_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    res['closure'] = {'max_abs_sum_minus_1_active': float(np.abs(s[mask] - 1).max()), 'min_value_active': float(c[:, mask].min()),
                      'nan_in_active': int(np.isnan(cov[:, mask]).sum()), 'finite_in_inactive': int(np.isfinite(cov[:, ~mask]).sum())}
    res['conservation'] = {}
    for k, Tn in T.items():
        got = psum(c[k - 1] * land); okp = (Tn > 0) & (tot <= capn + 1e-6); err = np.abs(got - Tn)
        res['conservation'][f'class{k}'] = {
            'target_Mkm2': float(Tn.sum() * 1e-12), 'allocated_Mkm2': float(got.sum() * 1e-12),
            'max_abs_err_km2_capacity_ok_parents': float(err[okp].max() * 1e-6) if okp.any() else 0.0,
            'parents_err_gt_tol_capacity_ok': int((err[okp] > TOL_CONS_KM2 * 1e6).sum()),
            'unplaced_km2': float((Tn.sum() - got.sum()) * 1e-6), 'allocated_where_target_zero_km2': float(got[Tn == 0].sum() * 1e-6),
            'tiles_gt0': int((c[k - 1][mask] > 0).sum())}
    nat_idx = [i for i in range(16) if i + 1 not in T]
    res['natural_Mkm2'] = float((c[nat_idx].sum(axis=0) * land).sum() * 1e-12)
    fv = COVERAGE.format(y=yr); v5 = None
    if os.path.exists(fv):
        v5 = np.nan_to_num(nc.Dataset(fv)['coverage'][0].filled(np.nan).astype('f8'))
        res['vs_vic_coverage_same_year'] = {f'class{k}': {'vic_Mkm2': float((v5[k - 1] * land).sum() * 1e-12),
                                                          'half_sum_abs_diff_Mkm2': float((np.abs(c[k - 1] - v5[k - 1]) * land).sum() * 1e-12 / 2)} for k in (12, 13, 14, 15)}
    cl = res['closure']; cons = res['conservation']
    passed = (cl['max_abs_sum_minus_1_active'] <= TOL_CLOSURE and cl['min_value_active'] >= 0 and cl['nan_in_active'] == 0
              and cl['finite_in_inactive'] == 0 and all(v['parents_err_gt_tol_capacity_ok'] == 0 for v in cons.values())
              and all(v['allocated_where_target_zero_km2'] == 0 for v in cons.values()))
    res['status'] = 'passed' if passed else 'failed'
    json.dump(res, open(f'{out_reports}/verify_{yr}.json', 'w'), indent=1)
    # figure
    ext = [-180, 180, vlat[0], vlat[-1]]; fig, axs = plt.subplots(3, 2, figsize=(16, 13)); axs = axs.ravel()
    for ax, (k, nm) in zip(axs, ((12, 'rainfed crop'), (14, 'irrigated non-paddy'), (15, 'irrigated paddy'), (13, 'urban'))):
        im = ax.imshow(np.where(mask & (c[k - 1] > 0), c[k - 1], np.nan), origin='lower', extent=ext, cmap='YlOrBr',
                       norm=mcolors.LogNorm(vmin=1e-4, vmax=1), interpolation='nearest')
        ax.set_title(f'{scen} {yr}: class {k} {nm} Cv ({T[k].sum() * 1e-12:.3f} Mkm2)', loc='left', fontsize=9); fig.colorbar(im, ax=ax, fraction=0.025)
    nat = c[nat_idx].sum(axis=0)
    im = axs[4].imshow(np.where(mask, nat, np.nan), origin='lower', extent=ext, cmap='Greens', vmin=0, vmax=1, interpolation='nearest')
    axs[4].set_title('natural + barren remainder', loc='left', fontsize=9); fig.colorbar(im, ax=axs[4], fraction=0.025)
    if v5 is not None:
        dd = (c[11] + c[13] + c[14]) - (v5[11] + v5[13] + v5[14])
        im = axs[5].imshow(np.where(mask & (np.abs(dd) > 1e-6), dd, np.nan), origin='lower', extent=ext, cmap='RdBu_r',
                           norm=mcolors.SymLogNorm(linthresh=0.01, vmin=-1, vmax=1), interpolation='nearest')
        axs[5].set_title(f'cropland (12+14+15): forcing - VIC coverage {yr}', loc='left', fontsize=9); fig.colorbar(im, ax=axs[5], fraction=0.025)
    for ax in axs: ax.set_facecolor('#f4f4f4')
    fig.tight_layout(); fig.savefig(f'{out_figs}/verify_{yr}.png', dpi=120); plt.close(fig)
    return yr, res['status']


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--scenario', required=True, choices=list(FILES))
    ap.add_argument('--years', default=None, help='single year or START-END (default: every file of the unit)')
    ap.add_argument('--unit-dir', default=None, help='verify outputs in this directory instead of the forcing unit')
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates', 'production'])
    a = ap.parse_args()
    unit = f'landuse/{a.scenario}'; unit_dir = a.unit_dir or f'{WORKDIR}/forcing/{unit}'
    qc = f'{unit_dir}/qc' if a.unit_dir else f'{WORKDIR}/qc/forcing/{unit}'
    reports, figs = f'{qc}/reports', f'{qc}/figures'; os.makedirs(reports, exist_ok=True); os.makedirs(figs, exist_ok=True)
    f_dom = f'{WORKDIR}/parameters/{a.parameter_status}/{a.parameter_set}/domain/vic_global_5min_domain_nogl.nc'
    files = sorted(f for f in os.listdir(unit_dir) if f.startswith(f'coverage_{a.scenario}_') and f.endswith('.nc'))
    if a.years:
        y = a.years.split('-'); want = set(range(int(y[0]), int(y[-1]) + 1))
        files = [f for f in files if int(f[:-3].rsplit('_', 1)[1]) in want]
    if not files: raise SystemExit(f'no coverage files in {unit_dir}')
    for f in files:
        yr, st = verify_file(f'{unit_dir}/{f}', a.scenario, f_dom, reports, figs); print(f'{f}: {st}', flush=True)
    # unit summary from every verify_<year>.json present
    all_files = sorted(f for f in os.listdir(unit_dir) if f.startswith(f'coverage_{a.scenario}_') and f.endswith('.nc'))
    per_year = {}
    for f in all_files:
        yr = int(f[:-3].rsplit('_', 1)[1]); p = f'{reports}/verify_{yr}.json'
        per_year[yr] = json.load(open(p))['status'] if os.path.exists(p) else 'not_checked'
    if any(v == 'failed' for v in per_year.values()): status = 'failed'
    elif all(v == 'passed' for v in per_year.values()): status = 'passed'
    else: status = 'not_checked'
    summary = {'object': f'forcing/{unit}', 'status': status, 'checked_by': 'workflow/04_forcing/landuse/verify_forcing.py',
               'updated_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'files': len(all_files), 'passed': sum(v == 'passed' for v in per_year.values()),
               'failed': sum(v == 'failed' for v in per_year.values()), 'not_checked': sum(v == 'not_checked' for v in per_year.values()),
               'per_year': {str(k): v for k, v in sorted(per_year.items())}}
    json.dump(summary, open(f'{qc}/summary.json', 'w'), indent=1)
    prov_path = f'{unit_dir}/provenance.yaml'
    if not a.unit_dir and os.path.exists(prov_path):
        prov = yaml.safe_load(open(prov_path)); prov['qc'] = {'status': status, 'evidence': f'qc/forcing/{unit}'}
        with open(prov_path, 'w') as fh: yaml.safe_dump(prov, fh, sort_keys=False)
    print(f'unit {unit}: {status} ({summary["passed"]} passed, {summary["failed"]} failed, {summary["not_checked"]} not checked of {len(all_files)})')


if __name__ == '__main__':
    main()
