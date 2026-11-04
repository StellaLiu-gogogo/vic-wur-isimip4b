#!/usr/bin/env python3
"""Block-structure screening of the VIC-WUR inputs and outputs (analysis block-structure; task Z follow-up, user
2026-11-04): which parameter fields and forcing fields are piecewise constant on a coarser grid (2-degree calibration
blocks, 1-degree, 0.5-degree ISIMIP cells, 0.25-degree), and which run outputs inherit that structure.

Method. For every 2-D field (and every layer, class, snow band or month mean of a 3-D or 4-D field) the absolute
difference between horizontally and vertically adjacent active cells is averaged separately for cell pairs that
straddle a 2-degree calibration-block edge (the version-a rule: latitude edges on even degrees, longitude edges on
even degrees east of 0 and odd degrees west of 0), a 1-degree line, a 0.5-degree line (the ISIMIP grid), a
0.25-degree line, and for every other pair (interior). The ratio of a line class to the interior mean is the block
signal: about 1 for a field without that structure, large for a field that is piecewise constant on that grid.
share_05 is the share of the total cell-to-cell variation that lies on lines of 0.5 degree or coarser (such pairs
are 1/6 of all pairs). The verbal signal (2deg-blocks, 1deg-lines, 0.5deg-blocks, 0.5deg-weak, none, constant) is a
fixed rule on the ratios (function flag).

Groups (column `group` of the table):
  param-b      every variable of the version-b image-driver file (the set without the 2-degree blocks), the
               irrigation file (groundwater_fraction, irrigation_efficiency)
  param-a      the five calibration fields of version-a and max_moist, init_moist (the 2-degree blocks)
  param-mpr    the soil fields of the MPR candidate of vic_parameter (the soil of version-c); also mpr_vs_a.csv
               (the MPR file against version-a, field by field) and mpr_depth_percentiles.json
  forcing-clim the seven climate forcing variables, annual mean of FORCING_YEAR
  forcing-lu   the land-use coverage of FORCING_YEAR per class
  forcing-wu   the water-use forcing of FORCING_YEAR (demands, consumption and groundwater fractions)
  output-<v>   the 2011-2020 mean of the monthly output of the comparison run with parameter set <v> (--runs)

Outputs (workdir/analysis/block-structure/): tables/block_screen.csv (one row per field slice), tables/mpr_vs_a.csv,
tables/mpr_depth_percentiles.json, tables/summary.json, figures/<group>_<field>[_<index>].png (two zoom regions,
Europe and Central Asia, for every field with a signal and for the fields listed in the report), logs/.

Usage: block_screen.py [--runs b c] [--mpr-file FILE] [--submit [--time 01:30:00] [--mem 96G] [--partition main]]
The MPR file defaults to the soil_source recorded in the provenance of the version-c soil component.
"""
import argparse, csv, glob, json, os, subprocess, sys, time

import numpy as np
import xarray as xr
import yaml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow'))
from common import workdir   # noqa: E402

TASK = 'block-structure'
SETS = {'a': 'parameters/production/vic-global-5arcmin-version-a', 'b': 'parameters/candidates/vic-global-5arcmin-version-b',
        'c': 'parameters/candidates/vic-global-5arcmin-version-c'}
BUNDLE = 'bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
IRRIGATION = 'irrigation/vic_global_5min_irrigation_parameters.nc'
SOIL_PROVENANCE = 'parameters/candidates/vic-global-5arcmin-version-c/soil/provenance.yaml'
RUN_ID = 'ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020'
RUNS = {v: f'runs/soil-comparison-version-{v}/{RUN_ID}' for v in SETS}
GCM, CLIMATE_UNIT = 'ec-earth3-esm-1-1', 'esm-hist'
FORCING_YEAR = 2015
CALIBRATION_FIELDS = ['depth', 'Ds', 'Dsmax', 'Ws', 'c', 'max_moist', 'init_moist']
MPR_SOIL = ['expt', 'Ksat', 'bubble', 'quartz', 'bulk_density', 'soil_density', 'depth', 'init_moist', 'max_moist',
            'Wcr_FRACT', 'Wpwp_FRACT', 'Wfc_FRACT', 'resid_moist', 'infilt', 'Ds', 'Dsmax', 'Ws', 'c', 'elev']
MPR_TEMPLATE = ['run_cell', 'AreaFract', 'Pfactor', 'elevation', 'Nelev', 'avg_T', 'annual_prec', 'dp', 'rough',
                'snow_rough', 'fs_active', 'Nlayer']
CLIMATE_VARS = ('prec', 'tair', 'psurf', 'vp', 'swdown', 'lwdown', 'wind')
OUT_VARS = ['OUT_RUNOFF', 'OUT_BASEFLOW', 'OUT_EVAP', 'OUT_PET', 'OUT_SOIL_MOIST', 'OUT_ROOTMOIST', 'OUT_SOIL_TEMP',
            'OUT_SWE', 'OUT_SNOW_MELT', 'OUT_SUB_SNOW', 'OUT_RECHARGE', 'OUT_EVAP_BARE', 'OUT_EVAP_CANOP',
            'OUT_TRANSP_VEG', 'OUT_LAI', 'OUT_PREC', 'OUT_AIR_TEMP', 'OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_APPLIED',
            'OUT_REQUIREMENT', 'OUT_SURFSTOR', 'OUT_STREAM_MOIST']
REGIONS = {'Europe 40-56N 5W-30E': (40, 56, -5, 30), 'Central Asia 35-50N 60-95E': (35, 50, 60, 95)}
SKIP_SUFFIX = ('_valid_fraction', '_distance_km', '_distance_degrees')
MIN_CELLS = 1000                 # slices with fewer finite active cells are not screened
NLAT, NLON = 1680, 4320          # the 5-arcmin grid: 12 cells per degree from -56 N and -180 E


def out_dir(W, sub):
    d = f'{W}/analysis/{TASK}/{sub}'
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------------- grid classes
def line_classes():
    """Class of the line between row i and i+1 (array over i) and between column j and j+1 (array over j):
    0 interior, 1 = 0.25-degree line, 2 = 0.5-degree, 3 = 1-degree, 4 = 2-degree calibration-block edge."""
    ky = np.arange(1, NLAT)                       # edge k lies at -56 + k/12 degrees
    cy = np.zeros(NLAT - 1, int)
    cy[ky % 3 == 0] = 1; cy[ky % 6 == 0] = 2; cy[ky % 12 == 0] = 3; cy[ky % 24 == 0] = 4
    kx = np.arange(1, NLON)                       # edge k lies at -180 + k/12 degrees
    cx = np.zeros(NLON - 1, int)
    cx[kx % 3 == 0] = 1; cx[kx % 6 == 0] = 2; cx[kx % 12 == 0] = 3
    m = kx // 12                                  # whole degrees east of -180
    east = (kx % 12 == 0) & (m >= 180) & (m % 2 == 0)
    west = (kx % 12 == 0) & (m < 180) & (m % 2 == 1)
    cx[east | west] = 4
    return cy, cx


CY, CX = line_classes()
CLASS_NAMES = {0: 'interior', 1: 'l025', 2: 'l05', 3: 'l1', 4: 'l2'}


def screen(f, mask):
    """Block statistics of one 2-D field on the active cells."""
    f = np.where(mask, f, np.nan).astype('f8')
    dy = np.abs(f[1:, :] - f[:-1, :]); dx = np.abs(f[:, 1:] - f[:, :-1])
    oky = np.isfinite(dy); okx = np.isfinite(dx)
    r = {}
    tot = 0.0; tot_coarse = 0.0
    for c in range(5):
        sy = dy[CY == c][oky[CY == c]]; sx = dx[:, CX == c][okx[:, CX == c]]
        s = np.concatenate([sy, sx])
        r[f'mean_{CLASS_NAMES[c]}'] = float(s.mean()) if s.size else np.nan
        r[f'n_{CLASS_NAMES[c]}'] = int(s.size)
        r[f'zero_{CLASS_NAMES[c]}'] = float((s == 0).mean()) if s.size else np.nan
        tot += s.sum()
        if c >= 2:
            tot_coarse += s.sum()
    base = r['mean_interior']
    for c in (1, 2, 3, 4):
        r[f'ratio_{CLASS_NAMES[c]}'] = float(r[f'mean_{CLASS_NAMES[c]}'] / base) if base and base > 0 else np.nan
    r['share_05'] = float(tot_coarse / tot) if tot > 0 else np.nan
    r['n_active'] = int(np.isfinite(f).sum())
    r['field_mean'] = float(np.nanmean(f)); r['field_std'] = float(np.nanstd(f))
    r['constant'] = bool(r['field_std'] == 0)
    return r


def flag(r):
    """Verbal block signal from the ratios (the rule of the scratch screening of 2026-11-04, unchanged)."""
    if r['constant']:
        return 'constant'
    s = []
    if r['ratio_l2'] > 2 and r['ratio_l2'] > 1.5 * max(r['ratio_l1'], 1):
        s.append('2deg-blocks')
    if r['ratio_l05'] > 2 and r['ratio_l025'] < 1.5:
        s.append('0.5deg-blocks')
    elif r['ratio_l05'] > 1.3 and r['ratio_l025'] < 1.2:
        s.append('0.5deg-weak')
    if r['ratio_l1'] > 2 and r['ratio_l1'] > 1.5 * r['ratio_l05']:
        s.append('1deg-lines')
    return ' '.join(s) if s else 'none'


# ---------------------------------------------------------------------------------------------- figures
def zoom(f, mask, lat, lon, path, title):
    f = np.where(mask, f, np.nan)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    for ax, (rn, (s, n, w, e)) in zip(axes, REGIONS.items()):
        iy = (lat >= s) & (lat <= n); ix = (lon >= w) & (lon <= e)
        sub = f[np.ix_(iy, ix)]
        lo, hi = np.nanpercentile(sub, [2, 98]) if np.isfinite(sub).any() else (0, 1)
        im = ax.imshow(sub, origin='lower', extent=[w, e, s, n], vmin=lo, vmax=hi, cmap='viridis', aspect='auto',
                       interpolation='nearest')
        ax.set_xticks(np.arange(w, e + 1, 5)); ax.set_yticks(np.arange(s, n + 1, 5)); ax.grid(alpha=0.25)
        ax.set_title(rn, fontsize=10)
        plt.colorbar(im, ax=ax, shrink=0.9)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def figure_name(group, name, idx):
    s = f"{group}_{name}{('_' + idx.replace(' ', '_').replace('=', '')) if idx else ''}"
    return s.replace('(', '').replace(')', '')


# ---------------------------------------------------------------------------------------------- field sources
def slices(ds, names, group):
    """Yield (group, name, index, field) for every 2-D slice of the named variables of a dataset."""
    for v in names:
        if v not in ds or v in ('lat', 'lon') or v.endswith(SKIP_SUFFIX):
            continue
        da = ds[v]
        if da.dims[-2:] != ('lat', 'lon'):
            continue
        extra = da.dims[:-2]
        if len(extra) == 0:
            yield group, v, '', da.values
        elif len(extra) == 1:
            for k in range(da.shape[0]):
                yield group, v, f'{extra[0]}={k}', da[k].values
        elif len(extra) == 2:                       # (veg_class, month), (veg_class, root_zone) or (time, x)
            if extra[0] == 'time':
                for k in range(da.shape[1]):
                    yield group, v, f'{extra[1]}={k}', da[:, k].mean('time').values
            elif extra[1] == 'month':
                for k in range(da.shape[0]):
                    yield group, v, f'{extra[0]}={k} (month mean)', da[k].mean('month').values
            else:
                for k in range(da.shape[0]):
                    for m in range(da.shape[1]):
                        yield group, v, f'{extra[0]}={k} {extra[1]}={m}', da[k, m].values


def mpr_file(W, arg):
    if arg:
        return arg
    with open(f'{W}/{SOIL_PROVENANCE}') as fh:
        return yaml.safe_load(fh)['inputs']['soil_source']


class Screening:
    def __init__(self, W):
        self.W = W
        self.tables = out_dir(W, 'tables'); self.figures = out_dir(W, 'figures')
        with xr.open_dataset(f'{W}/{SETS["a"]}/{DOMAIN}') as dom:
            self.lat = dom.lat.values; self.lon = dom.lon.values
            self.mask = dom.mask.values == 1
        assert self.mask.shape == (NLAT, NLON)
        assert abs(self.lat[0] - (-56 + 1 / 24)) < 1e-6 and abs(self.lon[0] - (-180 + 1 / 24)) < 1e-6
        self.rows = []
        self.t0 = time.time()
        print(f'active cells {self.mask.sum()}', flush=True)

    def record(self, group, name, idx, field, fig_always=False):
        if np.isfinite(np.where(self.mask, field, np.nan)).sum() < MIN_CELLS:
            return
        r = screen(field, self.mask)
        r.update({'group': group, 'field': name, 'index': idx})
        r['signal'] = flag(r)
        self.rows.append(r)
        tag = f"{name}{('[' + idx + ']') if idx else ''}"
        print(f"{time.time() - self.t0:7.0f}s {group:12s} {tag:45s} r2={r['ratio_l2']:6.2f} r1={r['ratio_l1']:6.2f} "
              f"r05={r['ratio_l05']:6.2f} r025={r['ratio_l025']:6.2f} share05={r['share_05']:5.3f} {r['signal']}", flush=True)
        if fig_always or r['signal'] not in ('none', 'constant'):
            zoom(field, self.mask, self.lat, self.lon, f'{self.figures}/{figure_name(group, name, idx)}.png',
                 f"{group}: {tag}   ratios 2deg {r['ratio_l2']:.2f}, 1deg {r['ratio_l1']:.2f}, "
                 f"0.5deg {r['ratio_l05']:.2f}, 0.25deg {r['ratio_l025']:.2f}")

    # -- steps
    def parameters(self, mpr):
        W = self.W
        with xr.open_dataset(f'{W}/{SETS["b"]}/{BUNDLE}') as b:
            for g, v, i, f in slices(b, list(b.data_vars), 'param-b'):
                self.record(g, v, i, f)
        with xr.open_dataset(f'{W}/{SETS["b"]}/{IRRIGATION}') as ir:
            self.record('param-b', 'groundwater_fraction (irrigation)', '', ir.groundwater_fraction.values, fig_always=True)
            self.record('param-b', 'irrigation_efficiency', '', ir.irrigation_efficiency.values, fig_always=True)
        a = xr.open_dataset(f'{W}/{SETS["a"]}/{BUNDLE}')
        for g, v, i, f in slices(a, CALIBRATION_FIELDS, 'param-a'):
            self.record(g, v, i, f, fig_always=True)
        self.mpr(xr.open_dataset(mpr), a)
        a.close()

    def mpr(self, m, a):
        mask = self.mask
        for g, v, i, f in slices(m, MPR_SOIL, 'param-mpr'):
            self.record(g, v, i, f, fig_always=True)
        rows = []
        for v in MPR_TEMPLATE + MPR_SOIL:
            if v not in m or v not in a:
                rows.append({'field': v, 'in_mpr': v in m, 'in_a': v in a}); continue
            xm = m[v].values.astype('f8'); xa = a[v].values.astype('f8')
            mm = np.broadcast_to(mask, xm.shape)
            d = np.where(mm, xm - xa, np.nan)
            rows.append({'field': v, 'in_mpr': True, 'in_a': True, 'kind': 'template' if v in MPR_TEMPLATE else 'soil',
                         'mean_mpr': float(np.nanmean(np.where(mm, xm, np.nan))), 'mean_a': float(np.nanmean(np.where(mm, xa, np.nan))),
                         'max_abs_diff': float(np.nanmax(np.abs(d))), 'cells_differ': int((np.abs(d) > 1e-9).sum()),
                         'cells_compared': int(np.isfinite(d).sum())})
            print(f'mpr vs a {v:14s} mean {rows[-1]["mean_mpr"]:12.5g} {rows[-1]["mean_a"]:12.5g} '
                  f'maxdiff {rows[-1]["max_abs_diff"]:10.4g} differ {rows[-1]["cells_differ"]}', flush=True)
        with open(f'{self.tables}/mpr_vs_a.csv', 'w', newline='') as fh:
            wr = csv.DictWriter(fh, ['field', 'kind', 'in_mpr', 'in_a', 'mean_mpr', 'mean_a', 'max_abs_diff', 'cells_differ',
                                     'cells_compared'])
            wr.writeheader(); wr.writerows(rows)
        dep = np.where(mask, m['depth'].values, np.nan)
        with open(f'{self.tables}/mpr_depth_percentiles.json', 'w') as fh:
            json.dump({f'layer{k}': {str(p): float(np.nanpercentile(dep[k], p)) for p in (1, 5, 25, 50, 75, 95, 99)}
                       for k in range(dep.shape[0])}, fh, indent=1)
        m.close()

    def forcing(self):
        W = self.W; y = FORCING_YEAR
        for v in CLIMATE_VARS:
            with xr.open_dataset(f'{W}/forcing/climate/{GCM}/{CLIMATE_UNIT}/{v}/{v}_{GCM}_{CLIMATE_UNIT}_{y}.nc') as ds:
                self.record('forcing-clim', v, f'{y} mean', ds[v].mean('time').values, fig_always=True)
        with xr.open_dataset(f'{W}/forcing/landuse/histsoc/coverage_histsoc_{y}.nc') as lu:
            for k in range(lu.sizes['veg_class']):
                self.record('forcing-lu', 'coverage', f'class={k}', lu.coverage[0, k].values)
        for p in sorted(glob.glob(f'{W}/forcing/water_use/histsoc/*_histsoc_{y}.nc')):
            with xr.open_dataset(p) as ds:
                v = [x for x in ds.data_vars if ds[x].dims[-2:] == ('lat', 'lon')][0]
                self.record('forcing-wu', os.path.basename(p).replace(f'_histsoc_{y}.nc', ''), '', ds[v][0].values, fig_always=True)

    def run_output(self, v):
        files = sorted(glob.glob(f'{self.W}/{RUNS[v]}/output/monthly.*.nc'))
        if not files:
            raise SystemExit(f'no monthly output of run {v}: {self.W}/{RUNS[v]}/output')
        acc = {}
        for p in files:
            with xr.open_dataset(p) as ds:
                for k in OUT_VARS:
                    acc[k] = acc.get(k, 0) + ds[k].mean('time').values.astype('f8') / len(files)
            print(f'{time.time() - self.t0:7.0f}s read {os.path.basename(p)}', flush=True)
        for k, x in acc.items():
            if x.ndim == 2:
                self.record(f'output-{v}', k, '2011-2020 mean', x, fig_always=True)
            else:
                for layer in range(x.shape[0]):
                    self.record(f'output-{v}', k, f'layer={layer} 2011-2020 mean', x[layer], fig_always=True)
        return len(files)

    def write(self, extra):
        keys = ['group', 'field', 'index', 'signal'] + [k for k in self.rows[0] if k not in ('group', 'field', 'index', 'signal')]
        with open(f'{self.tables}/block_screen.csv', 'w', newline='') as fh:
            wr = csv.DictWriter(fh, keys); wr.writeheader(); wr.writerows(self.rows)
        signals = sorted(set(r['signal'] for r in self.rows))
        summary = {'rows': len(self.rows), 'seconds': round(time.time() - self.t0), 'regions': REGIONS,
                   'signals': {s: int(sum(r['signal'] == s for r in self.rows)) for s in signals}, **extra}
        with open(f'{self.tables}/summary.json', 'w') as fh:
            json.dump(summary, fh, indent=1)
        print(f'done {len(self.rows)} rows in {summary["seconds"]} s -> {self.tables}', flush=True)


# ---------------------------------------------------------------------------------------------- submit
SBATCH = """#!/bin/bash
#SBATCH --job-name=block-structure
#SBATCH --partition={partition}
#SBATCH --time={time}
#SBATCH --cpus-per-task=1
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/screen_${{SLURM_JOB_ID}}
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
/usr/bin/time -v python3 analysis/block-structure/block_screen.py --runs {runs}{mpr}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def submit(W, a):
    logs = out_dir(W, 'logs')
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    text = SBATCH.format(partition=a.partition, time=a.time, mem=a.mem, logs=logs, conda=conda, workdir=W, repo=REPO,
                         runs=' '.join(a.runs), mpr=f' --mpr-file {a.mpr_file}' if a.mpr_file else '')
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sbatch failed: {r.stderr}')
    job = r.stdout.strip().split(';')[0]
    d = f'{logs}/screen_{job}'; os.makedirs(d, exist_ok=True)
    with open(f'{d}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job], check=True)
    print(f'submitted {job}; {d}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--runs', nargs='+', default=['b'], choices=list(SETS), help='comparison runs whose output is screened')
    ap.add_argument('--mpr-file', help='the MPR candidate file; default: the soil_source of the version-c soil provenance')
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--time', default='01:30:00')
    ap.add_argument('--mem', default='96G')
    ap.add_argument('--partition', default='main')
    a = ap.parse_args(); W = workdir.root()
    if a.submit:
        submit(W, a); return
    mpr = mpr_file(W, a.mpr_file)
    s = Screening(W)
    s.parameters(mpr)
    s.forcing()
    files = {v: s.run_output(v) for v in a.runs}
    s.write({'inputs': {'domain': f'{SETS["a"]}/{DOMAIN}', 'bundles': {v: f'{SETS[v]}/{BUNDLE}' for v in 'ab'},
                        'irrigation': f'{SETS["b"]}/{IRRIGATION}', 'mpr_file': mpr, 'forcing_year': FORCING_YEAR,
                        'runs': {v: {'path': RUNS[v], 'monthly_files': n} for v, n in files.items()}}})


if __name__ == '__main__':
    main()
