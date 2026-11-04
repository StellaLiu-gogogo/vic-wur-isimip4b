#!/usr/bin/env python3
"""Comparison of the parameter sets vic-global-5arcmin-version-a, -b and -c (task Z): the smoothed calibration fields
(b) and the MPR soil (c) against version-a, and their effect on the 2011-2020 comparison runs (campaigns
soil-comparison-version-a, -b and -c). Version-a is the reference of every difference; --versions selects the sets.

Steps (each a Slurm job with --submit; job script and output in workdir/analysis/soil-comparison/logs/<step>_<id>/):
  fields  the image-driver parameter files: area-weighted global and regional means of depth[2], Ds, Dsmax, Ws,
          c, max_moist[2], init_moist[2], Wcr_FRACT[2] and of root_fract[2] of the grassland class per set, the share of
          active cells that differ from version-a, difference maps of depth[2] and Ds for the two regions
          (tables/fields.csv, one row per field, region and set; figures/fields_<field>_<region>_<set>.png)
  runs    the monthly output of the runs over their common years: global area-weighted monthly series of the
          layer-2 soil moisture, baseflow, runoff, evaporation and the baseflow share of total runoff; annual means
          per run and their difference to version-a (tables/annual_global.csv, tables/annual_regions.csv); maps of the
          2016-2020 mean and its difference to version-a (global, West Siberia, Alps) of the layer-2 soil moisture,
          baseflow and baseflow share (figures/runs_<variable>_<region>_<set>.png); the GRDC station tables of the run
          checks joined (tables/grdc_stations.csv: observed and simulated mean discharge, ratio and seasonal correlation
          per run; stations improved and worsened against version-a per set); the water-balance error of the run checks
          (tables/run_checks.json)
Regions: West Siberia 58-66 N, 78-90 E; the Alps 42-50 N, 2-14 E (user, 2026-11-02). Years 2011-2015 are the settling
years of the cold start; the maps and the station comparison use 2016-2020, the series the whole period.

Usage: soil_comparison.py --step fields|runs [--versions a b c] [--submit [--time 04:00:00] [--mem 96G] [--partition main]]
"""
import argparse, csv, glob, json, os, subprocess, sys

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import workdir   # noqa: E402

TASK = 'soil-comparison'
SETS = {'a': 'parameters/production/vic-global-5arcmin-version-a', 'b': 'parameters/candidates/vic-global-5arcmin-version-b',
        'c': 'parameters/candidates/vic-global-5arcmin-version-c'}
REF = 'a'                        # every difference is against version-a
BUNDLE = 'bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
RUN_ID = 'ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020'
RUNS = {v: f'runs/soil-comparison-version-{v}/{RUN_ID}' for v in SETS}
QC = {v: f'qc/runs/soil-comparison-version-{v}/{RUN_ID}' for v in SETS}
REGIONS = {'global': None, 'west_siberia': (58, 66, 78, 90), 'alps': (42, 50, 2, 14)}
MAP_YEARS = (2016, 2020)
FIELDS = ('depth', 'Ds', 'Dsmax', 'Ws', 'c', 'max_moist', 'init_moist', 'Wcr_FRACT')
KEYS = ('sm2_mm', 'baseflow_mm', 'runoff_mm', 'evap_mm', 'baseflow_share')
LAYER = 1
GRASS = 10                       # veg_class of grasslands (1-based)


def out_dir(W, sub):
    d = f'{W}/analysis/{TASK}/{sub}'
    os.makedirs(d, exist_ok=True)
    return d


def read_domain(W):
    with nc.Dataset(f'{W}/{SETS["a"]}/{DOMAIN}') as d:
        d.set_auto_mask(False)
        return (np.asarray(d['mask'][:]) == 1, np.asarray(d['lat'][:], 'f8'), np.asarray(d['lon'][:], 'f8'),
                np.asarray(d['area'][:], 'f8'))


def region_mask(name, mask, lat, lon):
    box = REGIONS[name]
    if box is None:
        return mask
    la0, la1, lo0, lo1 = box
    return mask & ((lat >= la0) & (lat <= la1))[:, None] & ((lon >= lo0) & (lon <= lo1))[None, :]


def area_mean(x, m, area):
    w = np.where(m & np.isfinite(x), area, 0.0)
    return float(np.nansum(np.where(w > 0, x, 0.0) * w) / w.sum()) if w.sum() > 0 else float('nan')


def stored(ds, name, idx=None):
    v = ds[name]; v.set_auto_maskandscale(False)
    x = np.asarray(v[:] if idx is None else v[idx]).astype('f8')
    f = v.getncattr('_FillValue') if '_FillValue' in v.ncattrs() else None
    if f is not None and not np.isnan(f):
        x = np.where(x == f, np.nan, x)
    x[np.abs(x) > 1e19] = np.nan
    return x


def draw_maps(path, panels, lat, lon, box, title, units, cmap='viridis', diverging=False):
    """One row of maps (label, field) over the region box (lat0, lat1, lon0, lon1) or the globe."""
    if box is None:
        r = np.arange(len(lat)); c = np.arange(len(lon))
    else:
        la0, la1, lo0, lo1 = box
        r = np.flatnonzero((lat >= la0) & (lat <= la1)); c = np.flatnonzero((lon >= lo0) & (lon <= lo1))
    fig, axs = plt.subplots(1, len(panels), figsize=(6.5 * len(panels), 5 if box else 4), dpi=110, squeeze=False)
    for ax, (lab, x, vmin, vmax, cm) in zip(axs[0], panels):
        img = x[np.ix_(r, c)]
        im = ax.imshow(img[::-1], extent=(lon[c].min(), lon[c].max(), lat[r].min(), lat[r].max()), cmap=cm or cmap,
                       vmin=vmin, vmax=vmax, aspect='auto', interpolation='nearest')
        ax.set_title(lab, fontsize=10); fig.colorbar(im, ax=ax, shrink=0.8, label=units)
    fig.suptitle(title, fontsize=11); fig.tight_layout(); fig.savefig(path); plt.close(fig)


# ---------------------------------------------------------------------------------------------- step fields
def field_rows(label, x, mask, lat, lon, area, versions):
    """One row per region and set: the area-weighted mean, and against version-a the relative change, the share of
    cells that differ and the size of the difference."""
    rows = []
    for reg in REGIONS:
        m = region_mask(reg, mask, lat, lon)
        ref = area_mean(x[REF], m, area)
        for v in versions:
            mv = area_mean(x[v], m, area)
            row = {'field': label, 'region': reg, 'cells': int(m.sum()), 'version': v, 'mean': mv}
            if v == REF:
                row.update({'relative_change': '', 'cells_changed_share': '', 'max_abs_change': '', 'p50_abs_change': '', 'p90_abs_change': ''})
            else:
                d = (x[v] - x[REF])[m]
                row.update({'relative_change': mv / ref - 1 if ref else float('nan'), 'cells_changed_share': float((d != 0).mean()),
                            'max_abs_change': float(np.nanmax(np.abs(d))), 'p50_abs_change': float(np.nanpercentile(np.abs(d), 50)),
                            'p90_abs_change': float(np.nanpercentile(np.abs(d), 90))})
            rows.append(row)
    return rows


def step_fields(W, versions):
    mask, lat, lon, area = read_domain(W)
    tabs, figs = out_dir(W, 'tables'), out_dir(W, 'figures')
    ds = {v: nc.Dataset(f'{W}/{SETS[v]}/{BUNDLE}') for v in versions}
    rows = []; fields = {}
    for name in FIELDS:
        x = {v: stored(ds[v], name) for v in versions}
        layered = x[REF].ndim == 3
        if layered:
            x = {v: x[v][LAYER] for v in versions}
        fields[name] = x
        rows += field_rows(f'{name}[2]' if layered else name, x, mask, lat, lon, area, versions)
    # root fraction of layer 2, grassland
    rf = {v: stored(ds[v], 'root_fract', (GRASS - 1, LAYER)) for v in versions}
    tiles = mask & (np.nan_to_num(stored(ds[REF], 'Cv', GRASS - 1)) > 0)
    rows += field_rows(f'root_fract[2] class {GRASS}', rf, tiles, lat, lon, area, versions)
    with open(f'{tabs}/fields.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for name in ('depth', 'Ds', 'Wcr_FRACT'):
        xa = fields[name][REF]
        for v in versions:
            if v == REF:
                continue
            xv = fields[name][v]
            for reg, box in REGIONS.items():
                if box is None:
                    continue
                lim = float(np.nanmax(np.abs((xv - xa)[region_mask(reg, mask, lat, lon)]))) or 1e-9
                draw_maps(f'{figs}/fields_{name}_{reg}_{v}.png',
                          [(f'version-{REF}', np.where(mask, xa, np.nan), None, None, None), (f'version-{v}', np.where(mask, xv, np.nan), None, None, None),
                           (f'{v} - {REF}', np.where(mask, xv - xa, np.nan), -lim, lim, 'RdBu_r')],
                          lat, lon, box, f'{name}{"[2]" if name in ("depth", "Wcr_FRACT") else ""} ({reg})', 'm' if name == 'depth' else '')
    for d in ds.values():
        d.close()
    print(f'fields: {len(rows)} rows -> {tabs}/fields.csv')


# ---------------------------------------------------------------------------------------------- step runs
def year_files(W, run_rel):
    """{year: monthly output file} of a run (from its chunks when it has them)."""
    rd = f'{W}/{run_rel}'
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    chunks = man.get('chunks') or []
    dirs = {y: f'{rd}/{c["dir"]}' for c in chunks for y in range(c['start_year'], c['end_year'] + 1)} if chunks else \
        {y: rd for y in range(int(man['period']['start'][:4]), int(man['period']['end'][:4]) + 1)}
    out = {}
    for y, d in dirs.items():
        f = f'{d}/output/monthly.{y}-01.nc'
        if os.path.isfile(f):
            out[y] = f
    return out


def read_year(path):
    """Monthly fields of one year: soil moisture of layer 2 (mm), baseflow, runoff, evaporation (mm/month),
    discharge (m3/s), water error (mm)."""
    with nc.Dataset(path) as d:
        return {'sm2': stored(d, 'OUT_SOIL_MOIST')[:, LAYER], 'baseflow': stored(d, 'OUT_BASEFLOW'),
                'runoff': stored(d, 'OUT_RUNOFF'), 'evap': stored(d, 'OUT_EVAP'), 'discharge': stored(d, 'OUT_DISCHARGE'),
                'water_error': stored(d, 'OUT_WATER_ERROR')}


def step_runs(W, versions):
    mask, lat, lon, area = read_domain(W)
    tabs, figs = out_dir(W, 'tables'), out_dir(W, 'figures')
    others = [v for v in versions if v != REF]
    files = {v: year_files(W, RUNS[v]) for v in versions}
    years = sorted(set.intersection(*(set(files[v]) for v in versions)))
    if not years:
        raise SystemExit('no common year with monthly output in the runs')
    print(f'common years {years[0]}-{years[-1]}', flush=True)
    series = {v: {k: [] for k in ('sm2', 'baseflow', 'runoff', 'evap', 'baseflow_share')} for v in versions}
    annual = []; acc = {v: {k: np.zeros(mask.shape) for k in ('sm2', 'baseflow', 'runoff')} for v in versions}; n_map = 0
    for y in years:
        data = {v: read_year(files[v][y]) for v in versions}
        for v in versions:
            d = data[v]
            for mth in range(12):
                bf, ro = d['baseflow'][mth], d['runoff'][mth]
                series[v]['sm2'].append(area_mean(d['sm2'][mth], mask, area))
                series[v]['baseflow'].append(area_mean(bf, mask, area)); series[v]['runoff'].append(area_mean(ro, mask, area))
                series[v]['evap'].append(area_mean(d['evap'][mth], mask, area))
                series[v]['baseflow_share'].append(series[v]['baseflow'][-1] / (series[v]['baseflow'][-1] + series[v]['runoff'][-1]))
            ysum = {k: np.nansum(d[k], axis=0) for k in ('baseflow', 'runoff', 'evap')}
            ysm = np.nanmean(d['sm2'], axis=0)
            for reg in REGIONS:
                m = region_mask(reg, mask, lat, lon)
                bf, ro = area_mean(ysum['baseflow'], m, area), area_mean(ysum['runoff'], m, area)
                annual.append({'year': y, 'run': v, 'region': reg, 'sm2_mm': area_mean(ysm, m, area), 'baseflow_mm': bf,
                               'runoff_mm': ro, 'evap_mm': area_mean(ysum['evap'], m, area), 'baseflow_share': bf / (bf + ro),
                               'cell_months_water_error_above_1mm': int((np.abs(d['water_error'][:, m]) > 1).sum())})
            if MAP_YEARS[0] <= y <= MAP_YEARS[1]:
                acc[v]['sm2'] += ysm; acc[v]['baseflow'] += ysum['baseflow']; acc[v]['runoff'] += ysum['runoff']
        if MAP_YEARS[0] <= y <= MAP_YEARS[1]:
            n_map += 1
        print(f'year {y} read', flush=True)
    # tables
    with open(f'{tabs}/annual_regions.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(annual[0])); w.writeheader(); w.writerows(annual)
    rows = []
    for y in years:
        g = {v: next(r for r in annual if r['year'] == y and r['run'] == v and r['region'] == 'global') for v in versions}
        rows.append({'year': y, **{f'{k}_{v}': g[v][k] for v in versions for k in KEYS},
                     **{f'{k}_{v}_minus_{REF}': g[v][k] - g[REF][k] for v in others for k in KEYS}})
    with open(f'{tabs}/annual_global.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # series figure
    t = np.arange(len(series[REF]['sm2'])) / 12 + years[0]
    fig, axs = plt.subplots(4, 1, figsize=(11, 11), dpi=110, sharex=True)
    for ax, (k, lab) in zip(axs, (('sm2', 'soil moisture layer 2 (mm)'), ('baseflow', 'baseflow (mm/month)'),
                                  ('runoff', 'surface runoff (mm/month)'), ('baseflow_share', 'baseflow / (baseflow + runoff)'))):
        for v in versions:
            ax.plot(t, series[v][k], label=f'version-{v}', lw=1)
        ax2 = ax.twinx()
        for v, ls in zip(others, ('--', ':', '-.')):
            ax2.plot(t, np.array(series[v][k]) - np.array(series[REF][k]), color='k', lw=0.8, ls=ls, label=f'{v} - {REF}')
        ax2.set_ylabel(f'difference to version-{REF}'); ax2.legend(loc='upper right', fontsize=8)
        ax.set_ylabel(lab); ax.legend(loc='upper left', fontsize=8); ax.grid(alpha=0.3)
    axs[0].set_title('global area-weighted means of the active cells'); fig.tight_layout()
    fig.savefig(f'{figs}/runs_global_series.png'); plt.close(fig)
    # maps of the mean over MAP_YEARS
    if n_map:
        for v in versions:
            for k in acc[v]:
                acc[v][k] /= n_map
        with np.errstate(invalid='ignore', divide='ignore'):
            for v in versions:
                acc[v]['baseflow_share'] = acc[v]['baseflow'] / (acc[v]['baseflow'] + acc[v]['runoff'])
        for reg, box in REGIONS.items():
            m = region_mask(reg, mask, lat, lon)
            for k, units in (('sm2', 'mm'), ('baseflow', 'mm/yr'), ('baseflow_share', '-')):
                xa = acc[REF][k]; vmax = float(np.nanpercentile(xa[m], 99))
                for v in others:
                    xv = acc[v][k]
                    diff = np.where(mask, xv - xa, np.nan); lim = float(np.nanpercentile(np.abs(diff[m]), 99)) or 1e-9
                    draw_maps(f'{figs}/runs_{k}_{reg}_{v}.png',
                              [(f'version-{REF}', np.where(mask, xa, np.nan), 0, vmax, None), (f'version-{v}', np.where(mask, xv, np.nan), 0, vmax, None),
                               (f'{v} - {REF}', diff, -lim, lim, 'RdBu_r')], lat, lon, box,
                              f'{k}, mean {MAP_YEARS[0]}-{MAP_YEARS[1]} ({reg})', units)
    # GRDC stations of the two run checks
    st = {}
    for v in versions:
        p = f'{W}/{QC[v]}/reports/grdc_stations.csv'
        if os.path.isfile(p):
            with open(p) as fh:
                st[v] = {r['grdc_no']: r for r in csv.DictReader(fh)}
    grdc = {'stations': 0}
    if len(st) == len(versions):
        def f(x):
            try:
                return float(x)
            except ValueError:
                return float('nan')
        rows = []
        for no in sorted(set.intersection(*(set(st[v]) for v in versions))):
            ra = st[REF][no]
            row = {'grdc_no': no, 'river': ra['river'], 'station': ra['station'], 'area_km2': ra['area_km2'],
                   'obs_mean_m3_s': f(ra['obs_mean_m3_s'])}
            for v in versions:
                row.update({f'sim_mean_{v}': f(st[v][no]['sim_mean_m3_s']), f'ratio_{v}': f(st[v][no]['ratio_sim_obs']),
                            f'seasonal_r_{v}': f(st[v][no]['seasonal_r'])})
            rows.append(row)
        with open(f'{tabs}/grdc_stations.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        grdc = {'stations': len(rows), 'reference': REF, 'by_set': {}}
        for v in others:
            ok = [r for r in rows if np.isfinite(r[f'ratio_{REF}']) and np.isfinite(r[f'ratio_{v}'])]
            la = [abs(np.log(r[f'ratio_{REF}'])) for r in ok]; lv = [abs(np.log(r[f'ratio_{v}'])) for r in ok]
            sr = [(r[f'seasonal_r_{REF}'], r[f'seasonal_r_{v}']) for r in ok if np.isfinite(r[f'seasonal_r_{REF}'])]
            # counts as Python ints (numpy ints are not JSON serialisable; the first runs job 43585332 failed here)
            grdc['by_set'][v] = {'stations_with_observations': len(ok),
                                 'bias_improved': int(sum(y < x for x, y in zip(la, lv))), 'bias_worsened': int(sum(y > x for x, y in zip(la, lv))),
                                 f'median_abs_log_ratio_{REF}': float(np.median(la)) if ok else None,
                                 f'median_abs_log_ratio_{v}': float(np.median(lv)) if ok else None,
                                 'seasonal_r_improved': int(sum(y > x for x, y in sr)), 'seasonal_r_worsened': int(sum(y < x for x, y in sr))}
    checks = {}
    for v in versions:
        p = f'{W}/{QC[v]}/reports/check.json'
        if os.path.isfile(p):
            with open(p) as fh:
                c = json.load(fh)
            checks[v] = {'status': c.get('status'), 'checked_at': c.get('checked_at'), 'grdc': c.get('grdc')}
    with open(f'{tabs}/run_checks.json', 'w') as fh:
        json.dump({'versions': list(versions), 'years': years, 'map_years': list(MAP_YEARS), 'grdc_comparison': grdc, 'run_checks': checks},
                  fh, indent=1)
    print(f'runs: {len(years)} years -> {tabs}')


# ---------------------------------------------------------------------------------------------- submit
SBATCH = """#!/bin/bash
#SBATCH --job-name=soil-comparison-{step}
#SBATCH --partition={partition}
#SBATCH --time={time}
#SBATCH --cpus-per-task=1
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/{step}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
set +u
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
set -u
export ISIMIP4B_WORKDIR={workdir}
export PYTHONPATH={repo}/workflow
export OMP_NUM_THREADS=1
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
/usr/bin/time -v python3 analysis/soil-comparison/soil_comparison.py --step {step} --versions {versions}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def submit(W, step, versions, time, mem, partition):
    logs = out_dir(W, 'logs')
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    text = SBATCH.format(step=step, versions=' '.join(versions), partition=partition, time=time, mem=mem, logs=logs, conda=conda,
                         workdir=W, repo=REPO)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job = r.stdout.strip().split(';')[0]
    d = f'{logs}/{step}_{job}'; os.makedirs(d, exist_ok=True)
    with open(f'{d}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job], check=True)
    print(f'submitted {job}; {d}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--step', required=True, choices=['fields', 'runs'])
    ap.add_argument('--versions', nargs='+', default=list(SETS), choices=list(SETS), help='sets compared; version-a is the reference')
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='96G')
    ap.add_argument('--partition', default='main')
    a = ap.parse_args(); W = workdir.root()
    if a.submit:
        submit(W, a.step, a.versions, a.time, a.mem, a.partition); return
    if REF not in a.versions:
        raise SystemExit(f'--versions must include the reference {REF}')
    {'fields': step_fields, 'runs': step_runs}[a.step](W, a.versions)


if __name__ == '__main__':
    main()
