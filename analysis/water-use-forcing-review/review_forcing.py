#!/usr/bin/env python3
"""Figures and statistics of the five water-use forcing units (task D2-review of D05).

Reads forcing/water_use/<soc>/ (demand in mm/day, consumption and groundwater fractions per sector and year), the
producer's lost-demand records under qc/forcing/water_use/<soc>/reports/, the ISIMIP3a/3b source files, the
domain file and the ISIMIP4b 5' population, and writes to workdir/analysis/water-use-forcing-review/:
  tables/   totals_by_region.csv (written, source and lost volumes per unit, sector, quantity, year, region, with
            the balance residual), balance_summary.csv, per_capita_by_continent.csv, even_split_cells.csv,
            within_parent_distribution.csv, year_step_cell_changes.csv, balance_by_region.csv,
            country_join_2021_2022.csv (source withdrawal per country, ISIMIP3a 2021 versus SSP 2022)
  figures/  totals_<sector>_<quantity>.png, maps_<unit>_<year>_<sector>.png, join_ratio_<unit>.png,
            per_capita_<unit>_<year>.png, within_parent_<unit>_<year>.png, anomaly_2005_manufacturing.png,
            year_step_cell_changes.png
Reused code: analysis/isimip3-water-abstraction-review/review_water_abstraction.py (file_table, read_file, region
weights of the six continents, REGIONS, plotting style) and analysis/landuse-visualization/ (region boxes
lu_vis.REGIONS, Natural Earth lines plot_maps.natural_earth_lines, land colour).

Usage (always on a compute node):
  review_forcing.py --submit [--processes 5]     render the Slurm job, keep its record, submit it
  review_forcing.py [--processes 5]              the computation itself (one process per unit)
"""
import argparse, calendar, datetime, glob, importlib.util, json, os, re, subprocess, sys

import numpy as np
import pandas as pd
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
TASK = 'water-use-forcing-review'
UNITS = {'histsoc': (1850, 2021), '1850soc': (1850, 2021), '2021soc': (2022, 2100),
         'ssp1vlsoc-noadapt': (2022, 2100), 'ssp3hsoc-noadapt': (2022, 2100)}
SECTORS = {'municipal': 'dom', 'manufacturing': 'ind'}
MAP_YEAR = {'histsoc': 2021, '2021soc': 2100, 'ssp1vlsoc-noadapt': 2100, 'ssp3hsoc-noadapt': 2100}
POP = {'histsoc': ('histsoc', 'population_histsoc'), '1850soc': ('1850soc', 'population_1850soc'),
       '2021soc': ('2021soc', 'population_2021soc'), 'ssp1vlsoc-noadapt': ('ssp1vlsoc-noadapt', 'population_ssp1'),
       'ssp3hsoc-noadapt': ('ssp3hsoc-noadapt', 'population_ssp3')}
FACTOR = 6
SBATCH = """#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=main
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task={proc}
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/review_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={workdir}
export OMP_NUM_THREADS=1
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
/usr/bin/time -v python3 analysis/{task}/review_forcing.py --processes {proc}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


D1 = load('d1_review', os.path.join(REPO, 'analysis', 'isimip3-water-abstraction-review', 'review_water_abstraction.py'))
sys.path.insert(0, os.path.join(REPO, 'analysis', 'landuse-visualization'))
import lu_vis   # noqa: E402  (region boxes)


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def products():
    return f'{workdir()}/analysis/{TASK}'


# ----------------------------------------------------------------------------------------------- grids
class Grid:
    """VIC 5' domain (south to north) and its relation to the ISIMIP 360 x 720 grid (north to south)."""
    def __init__(self):
        d = nc.Dataset(f'{workdir()}/parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc')
        self.lat = np.asarray(d['lat'][:], 'f8'); self.lon = np.asarray(d['lon'][:], 'f8')
        self.mask = d['mask'][:].filled(0) == 1; self.area = np.asarray(d['area'][:].filled(0), 'f8'); d.close()
        self.ny, self.nx = self.mask.shape
        self.npy, self.npx = self.ny // FACTOR, self.nx // FACTOR
        plat = self.lat.reshape(self.npy, FACTOR).mean(1)
        self.row360 = np.round((89.75 - plat) / 0.5).astype(int)        # parent row -> row of the 360 grid
        self.nact = self.psum(self.mask.astype('f8'))

    def psum(self, x):
        """5' field -> parent sums on the VIC parent grid (south to north)."""
        return x.reshape(self.npy, FACTOR, self.npx, FACTOR).sum(axis=(1, 3))

    def to360(self, p):
        out = np.zeros((360, 720)); out[self.row360, :] = p
        return out


def read_unit(unit, sector, var, year):
    d = nc.Dataset(f'{workdir()}/forcing/water_use/{unit}/{sector}_{var}_{unit}_{year}.nc'); d.set_auto_mask(False)
    x = np.asarray(d[var][0], 'f8'); d.close()
    return np.where(x >= 1e19, 0.0, x)


def read_population(unit, year, g):
    pdir, prefix = POP[unit]
    for f in sorted(os.listdir(f'{workdir()}/raw/ISIMIP4b/InputData/socioeconomic/population/{pdir}')):
        m = re.fullmatch(prefix + r'_5arcmin_annual_(\d{4})_(\d{4})\.nc', f)
        if m and int(m.group(1)) <= year <= int(m.group(2)):
            d = nc.Dataset(f'{workdir()}/raw/ISIMIP4b/InputData/socioeconomic/population/{pdir}/{f}'); d.set_auto_mask(False)
            yrs = [x.year for x in nc.num2date(d['time'][:], d['time'].units, getattr(d['time'], 'calendar', 'standard'))]
            glat = np.asarray(d['lat'][:]); rows = [int(np.argmin(np.abs(glat - la))) for la in g.lat]
            p = np.asarray(d['total-population'][yrs.index(year)], 'f8')[rows, :]; d.close()
            return np.where(np.isfinite(p) & (p < 1e19), np.maximum(p, 0.0), 0.0)
    raise SystemExit(f'no population for {unit} {year}')


# ----------------------------------------------------------------------------------------------- sources
def source_fields(unit, land):
    """{sector: (withdrawal by year, consumption-fraction source (ww, wc) by year)} on the 360 grid (m3/yr)."""
    ft = D1.file_table()
    cache = {}
    y0, y1 = UNITS[unit]

    def series(series_id, s, q, stat='value'):
        key = (series_id, s, q, stat)
        keep = {2015} if series_id == '3b-2015soc' else ({2021} if unit == '2021soc' else set(range(y0, y1 + 1)))
        if key not in cache:
            out = {}
            for _, row in ft[(ft.series == series_id) & (ft.sector == s) & (ft.quantity == q) & (ft.stat == stat)].iterrows():
                if not keep & set(range(int(re.findall(r'_(\d{4})_\d{4}\.nc$', row['path'])[0]),
                                        int(re.findall(r'_(\d{4})\.nc$', row['path'])[0]) + 1)):
                    continue
                yrs, a, _ = D1.read_file(row, land)
                for i, y in enumerate(yrs):
                    if int(y) in keep:
                        out[int(y)] = np.nan_to_num(a[i])
            cache[key] = out
        return cache[key]
    res = {}
    for sec, s in SECTORS.items():
        if unit == 'histsoc':
            ww, wc = series('3a-histsoc', s, 'ww'), series('3a-histsoc', s, 'wc')
            res[sec] = (ww, lambda y, ww=ww, wc=wc: (ww[y], wc[y]))
        elif unit == '1850soc':
            ww, wc = series('3b-1850soc', s, 'ww'), series('3b-1850soc', s, 'wc')
            res[sec] = (ww, lambda y, ww=ww, wc=wc: (ww[y], wc[y]))
        elif unit == '2021soc':
            w3, c3 = series('3a-histsoc', s, 'ww'), series('3a-histsoc', s, 'wc')
            ww = {y: w3[2021] for y in range(2022, 2101)}
            res[sec] = (ww, lambda y, w3=w3, c3=c3: (w3[2021], c3[2021]))
        else:
            sid = '3b-ssp126' if unit.startswith('ssp1') else '3b-ssp370'
            ww = series(sid, s, 'ww', 'modelavg')
            w15, c15 = series('3b-2015soc', s, 'ww')[2015], series('3b-2015soc', s, 'wc')[2015]
            res[sec] = (ww, lambda y, w15=w15, c15=c15: (w15, c15))
    return res


def consumption_from_source(ww, cfw, cfc, W):
    """Source-side consumption: ww x min(wc/ww, 1) of the consumption-fraction field; where that field has no
    withdrawal, the continental fraction of the same field (region weights of D1, fractional)."""
    pos = cfw > 0
    f = np.where(pos, np.minimum(cfc / np.where(pos, cfw, 1.0), 1.0), np.nan)
    wcont = W[1:1 + len(D1.CONTINENTS)]
    num = np.array([(np.minimum(cfc, cfw) * w).sum() for w in wcont]); den = np.array([(cfw * w).sum() for w in wcont])
    cont = np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
    g = np.minimum(cfc, cfw).sum() / cfw.sum() if cfw.sum() > 0 else 0.0
    share = wcont.sum(axis=0)
    fb = np.where(share > 0, np.tensordot(cont, wcont, 1) / np.where(share > 0, share, 1), g)
    return ww * np.where(pos, f, fb)


# ----------------------------------------------------------------------------------------------- drawing
def coastlines():
    pm = load('lu_plot_maps', os.path.join(REPO, 'analysis', 'landuse-visualization', 'plot_maps.py'))
    return pm.natural_earth_lines(), pm.LAND


def draw(ax, data, g, cmap, norm, box, coast, land, title=None):
    from matplotlib.collections import LineCollection
    from matplotlib import colors as mcolors
    s, n, w, e = box
    r = (g.lat >= s - 0.2) & (g.lat <= n + 0.2); c = (g.lon >= w - 0.2) & (g.lon <= e + 0.2)
    ext = [g.lon[c][0] - 1 / 24, g.lon[c][-1] + 1 / 24, g.lat[r][0] - 1 / 24, g.lat[r][-1] + 1 / 24]
    ax.imshow(np.where(g.mask[np.ix_(r, c)], 0.0, np.nan), origin='lower', extent=ext,
              cmap=mcolors.ListedColormap([land]), vmin=0, vmax=1, interpolation='nearest')
    im = ax.imshow(data[np.ix_(r, c)], origin='lower', extent=ext, cmap=cmap, norm=norm, interpolation='nearest')
    ax.add_collection(LineCollection(coast['borders'], colors='#a0a0a0', linewidths=0.25))
    ax.add_collection(LineCollection(coast['coast'], colors='#505050', linewidths=0.35))
    ax.set_xlim(w, e); ax.set_ylim(s, n); ax.set_xticks([]); ax.set_yticks([])
    if title:
        ax.set_title(title, fontsize=10, loc='left', pad=3)
    return im


def map_figure(path, columns, g, coast, land, stamp):
    """columns: list of (header, data, cmap, norm, colour-bar label); a global row and the six region insets."""
    plt = D1._plt()
    ncol = len(columns); regions = list(lu_vis.REGIONS)
    fig = plt.figure(figsize=(5.4 * ncol, 13.5))
    gs = fig.add_gridspec(4, 2 * ncol, height_ratios=[1.4, 1, 1, 1], hspace=0.25, wspace=0.08,
                          left=0.012, right=0.988, top=0.93, bottom=0.10)
    for j, (head, data, cmap, norm, lab) in enumerate(columns):
        ax = fig.add_subplot(gs[0, 2 * j:2 * j + 2])
        draw(ax, data, g, cmap, norm, (-56, 84, -180, 180), coast, land, head)
        for r in regions:
            s, n, w, e = lu_vis.REGIONS[r]
            ax.plot([w, e, e, w, w], [s, s, n, n, s], color='#333333', lw=0.6)
        for i, r in enumerate(regions):
            ax2 = fig.add_subplot(gs[1 + i // 2, 2 * j + i % 2])
            draw(ax2, data, g, cmap, norm, lu_vis.REGIONS[r], coast, land, lu_vis.REGION_LABEL[r] if j == 0 else None)
        cax = fig.add_axes([0.02 + j / ncol, 0.05, 1 / ncol - 0.04, 0.012])
        cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation='horizontal')
        cb.set_label(lab, fontsize=10)
    fig.suptitle(stamp, fontsize=14, x=0.012, ha='left', y=0.985)
    fig.savefig(path, dpi=110); plt.close(fig)


def cmaps():
    plt = D1._plt()
    from matplotlib import colors as mcolors
    def cut(name):
        cm = mcolors.LinearSegmentedColormap.from_list(f'{name}_cut', plt.get_cmap(name)(np.linspace(0.12, 1.0, 256)))
        cm.set_bad((0, 0, 0, 0)); return cm
    div = plt.get_cmap('RdBu_r').copy(); div.set_bad((0, 0, 0, 0))
    return cut, div, mcolors


# ----------------------------------------------------------------------------------------------- per unit
def gini(x):
    """Gini coefficient of each row of x (non-negative), rows with zero sum -> nan."""
    xs = np.sort(x, axis=1); n = x.shape[1]; s = xs.sum(axis=1)
    k = np.arange(1, n + 1)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(s > 0, (2 * (xs * k).sum(axis=1) / (n * s)) - (n + 1) / n, np.nan)


def review_unit(unit):
    t0 = datetime.datetime.now()
    g = Grid(); W = D1.region_weights(); land = D1.water_global_mask()
    src = source_fields(unit, land)
    y0, y1 = UNITS[unit]
    rows, steps = [], []
    figd = f'{products()}/figures'; tabd = f'{products()}/tables'
    led = pd.read_csv(f'{workdir()}/qc/forcing/water_use/{unit}/reports/lost_demand_ledger.csv')
    prev = {}
    extra = {}
    coast = land_col = None
    for year in range(y0, y1 + 1):
        days = 366 if calendar.isleap(year) else 365
        lost = pd.read_csv(f'{workdir()}/qc/forcing/water_use/{unit}/reports/lost_parents_{year}.csv')
        vol5 = {}
        for sec, s in SECTORS.items():
            d = read_unit(unit, sec, 'demand', year); cf = read_unit(unit, sec, 'consumption_fraction', year)
            v = np.where(g.mask, d * g.area * days / 1000.0, 0.0); vol5[sec] = v
            wv, wcn = g.to360(g.psum(v)), g.to360(g.psum(v * cf))
            sww = src[sec][0][year]; cfw, cfc = src[sec][1](year)
            scons = consumption_from_source(sww, cfw, cfc, W)
            lostmask = np.zeros((360, 720), bool)
            ls = lost[lost.sector == sec]
            if len(ls):
                lostmask[np.round((89.75 - ls.parent_lat.values) / 0.5).astype(int),
                         np.round((ls.parent_lon.values + 179.75) / 0.5).astype(int)] = True
            for q, written, source, lostf in (('withdrawal', wv, sww, sww * lostmask), ('consumption', wcn, scons, scons * lostmask)):
                rw, rs, rl = D1.regional(written, W)[0], D1.regional(source, W)[0], D1.regional(lostf, W)[0]
                for k, reg in enumerate(D1.REGIONS):
                    rows.append(dict(unit=unit, sector=sec, quantity=q, year=year, region=reg, written_km3=rw[k],
                                     source_km3=rs[k], lost_km3=rl[k], residual_km3=rs[k] - rw[k] - rl[k]))
            lrow = led[(led.year == year) & (led.sector == sec)]
            rows[-2 * len(D1.REGIONS)]['ledger_lost_km3'] = float(lrow.lost_km3.iloc[0]) if len(lrow) else np.nan
            # year-to-year change at 5' (share of the earlier volume in cells that halve or double)
            if sec in prev:
                steps.append(step_row(unit, sec, f'{unit} year to year', year - 1, prev[sec], v))
            prev[sec] = v
        if unit in MAP_YEAR and year == MAP_YEAR[unit]:
            if coast is None:
                coast, land_col = coastlines()
            extra['maps'] = maps_for(unit, year, g, vol5, coast, land_col, W, figd, tabd)
        if unit == 'histsoc' and year in (2004, 2005, 2006, 2010, 2011, 2021):
            extra.setdefault('hist', {})[year] = {s: vol5[s].astype('f4') for s in SECTORS}
    print(f'{unit}: {y1 - y0 + 1} years in {(datetime.datetime.now() - t0).seconds} s', flush=True)
    return unit, rows, steps, extra


def step_row(unit, sec, name, year_before, before, after):
    pos = before > 0
    r = np.where(pos, after / np.where(pos, before, 1), np.nan)
    big = pos & ((r < 0.5) | (r > 2))
    return dict(unit=unit, sector=sec, step=name, year_before=int(year_before),
                global_change=float(after.sum() / before.sum() - 1),
                share_before_in_cells_halved_or_doubled=float(before[big].sum() / before.sum()),
                share_before_in_cells_going_to_zero=float(before[pos & (after <= 0)].sum() / before.sum()),
                share_after_in_new_cells=float(after[~pos & (after > 0)].sum() / after.sum()))


def maps_for(unit, year, g, vol5, coast, land, W, figd, tabd):
    """Maps of the map year, per-capita demand, even-split cells, within-parent distribution."""
    cut, div, mcolors = cmaps()
    out = {'per_capita': [], 'even_split': [], 'within': []}
    pop = read_population(unit, year, g)
    stamp = f'{unit} {year}'
    for sec in SECTORS:
        d = np.where(g.mask, read_unit(unit, sec, 'demand', year), np.nan)
        cf = np.where(g.mask, read_unit(unit, sec, 'consumption_fraction', year), np.nan)
        gw = np.where(g.mask, read_unit(unit, sec, 'groundwater_fraction', year), np.nan)
        map_figure(f'{figd}/maps_{unit}_{year}_{sec}.png',
                   [(f'{sec} demand (mm/day)', np.where(d > 0, d, np.nan), cut('viridis'), mcolors.LogNorm(1e-4, 10), 'mm/day'),
                    (f'{sec} consumption fraction', cf, cut('magma_r'), mcolors.Normalize(0, 1), 'consumed / withdrawn'),
                    (f'{sec} groundwater fraction', gw, cut('YlGnBu'), mcolors.Normalize(0, 1), 'groundwater / withdrawn')],
                   g, coast, land, f'{stamp}: {sec} water use (5 arcmin)')
        v = vol5[sec]
        pc = np.where(pop > 0, v / np.where(pop > 0, pop, 1), np.nan)
        noppl = g.mask & (v > 0) & (pop <= 0)
        out['even_split'].append(dict(unit=unit, year=year, sector=sec, cells_with_demand=int((v > 0).sum()),
                                      cells_with_demand_without_population=int(noppl.sum()),
                                      volume_km3_without_population=float(v[noppl].sum() / 1e9),
                                      share_of_total=float(v[noppl].sum() / v.sum())))
        # continental per capita: volumes and population summed to parents, then weighted like the totals
        pv, pp = D1.regional(g.to360(g.psum(v)), W)[0], D1.regional(g.to360(g.psum(np.where(g.mask, pop, 0.0))), W)[0]
        for k, reg in enumerate(D1.REGIONS):
            # D1.regional returns sums divided by 1e9: km3 for volumes, billions for population
            out['per_capita'].append(dict(unit=unit, year=year, sector=sec, region=reg, volume_km3=pv[k],
                                          population_millions=pp[k] * 1e3,
                                          m3_per_person=(pv[k] / pp[k]) if pp[k] > 0 else np.nan))
        # within-parent spread over the active children
        blk = lambda x: x.reshape(g.npy, FACTOR, g.npx, FACTOR).transpose(0, 2, 1, 3).reshape(-1, FACTOR * FACTOR)
        vb, ab = blk(v), blk(g.mask)
        tot = vb.sum(axis=1); has = (tot > 0) & (ab.sum(axis=1) > 0)
        nact = ab.sum(axis=1)
        zero_share = np.where(has, ((vb <= 0) & ab).sum(axis=1) / np.maximum(nact, 1), np.nan)
        max_share = np.where(has, vb.max(axis=1) / np.where(tot > 0, tot, 1), np.nan)
        gi = np.full(len(tot), np.nan)
        for n in range(1, 37):                                          # Gini over the active children only
            sel = has & (nact == n)
            if sel.any():
                vals = np.where(ab[sel], vb[sel], -1.0)
                vals = np.sort(vals, axis=1)[:, -n:]
                gi[sel] = gini(vals) if n > 1 else 0.0
        out['within'].append((sec, tot[has], zero_share[has], max_share[has], gi[has], nact[has]))
        out[f'pc_{sec}'] = pc; out[f'noppl_{sec}'] = noppl
    pcfig = [(f'{sec} demand per person (m3/yr)', np.where(out[f'pc_{sec}'] > 0, out[f'pc_{sec}'], np.nan),
              cut('viridis'), mcolors.LogNorm(1, 1000), 'm3 per person per year') for sec in SECTORS]
    flag = np.where(out['noppl_municipal'] | out['noppl_manufacturing'], 1.0, np.nan)
    pcfig.append(('demand without population (even split)', flag, mcolors.ListedColormap(['#d62728']),
                  mcolors.Normalize(0, 1), 'cells with demand but no ISIMIP4b population'))
    map_figure(f'{figd}/per_capita_{unit}_{year}.png', pcfig, g, coast, land, f'{stamp}: demand per person (5 arcmin)')
    plt = D1._plt()
    fig, axs = plt.subplots(2, 3, figsize=(14, 7))
    for i, (sec, tot, zs, ms, gi, na) in enumerate(out['within']):
        w = tot / tot.sum()
        for ax, x, lab, bins in ((axs[i, 0], zs, 'share of active children with zero demand', np.linspace(0, 1, 37)),
                                 (axs[i, 1], ms, 'largest child share of the parent total', np.linspace(0, 1, 41)),
                                 (axs[i, 2], gi, 'Gini of the child volumes', np.linspace(0, 1, 41))):
            ax.hist(x, bins=bins, weights=w, color='#1f4e9c', alpha=0.85)
            ax.set_xlabel(lab); ax.set_ylabel('share of the volume'); ax.set_title(f'{sec}', loc='left', fontsize=9)
    fig.suptitle(f'{stamp}: how the 0.5 deg totals are spread over the active 5\' children (weighted by volume)')
    fig.tight_layout(); fig.savefig(f'{figd}/within_parent_{unit}_{year}.png', dpi=120); plt.close(fig)
    within = []
    for sec, tot, zs, ms, gi, na in out['within']:
        w = tot / tot.sum()
        within.append(dict(unit=unit, year=year, sector=sec, parents=int(len(tot)),
                           volume_weighted_mean_zero_child_share=float((zs * w).sum()),
                           volume_weighted_mean_max_child_share=float((ms * w).sum()),
                           volume_weighted_mean_gini=float(np.nansum(gi * w)),
                           parents_one_child_takes_over_half=int((ms > 0.5).sum()),
                           volume_share_parents_one_child_over_half=float(w[ms > 0.5].sum())))
    return {'per_capita': out['per_capita'], 'even_split': out['even_split'], 'within': within}


def country_join(land, tabd):
    """Source withdrawal per country (ISIMIP4b fractional country masks): ISIMIP3a 2021 versus SSP 2022."""
    ft = D1.file_table()
    d = nc.Dataset(f'{workdir()}/raw/ISIMIP4b/InputData/geo_conditions/countrymasks/countrymasks-fractional_30arcmin.nc')
    d.set_auto_mask(False)
    masks = {v: np.nan_to_num(np.asarray(d[v][:], 'f8')) for v in d.variables if v not in ('lat', 'lon', 'world')}
    d.close()
    rows = []
    for sec, s in SECTORS.items():
        f = {}
        for key, sid, stat, year in (('hist2021', '3a-histsoc', 'value', 2021), ('ssp126_2022', '3b-ssp126', 'modelavg', 2022),
                                     ('ssp370_2022', '3b-ssp370', 'modelavg', 2022)):
            row = ft[(ft.series == sid) & (ft.sector == s) & (ft.quantity == 'ww') & (ft.stat == stat) &
                     ft.path.str.contains('2021|2100')].iloc[0]
            yrs, a, _ = D1.read_file(row, land)
            f[key] = np.nan_to_num(a[list(yrs).index(year)])
        for iso, w in masks.items():
            v = {k: float((x * w).sum() / 1e9) for k, x in f.items()}
            rows.append(dict(sector=sec, iso3=iso, **{f'{k}_km3': x for k, x in v.items()},
                             ratio_ssp126=v['ssp126_2022'] / v['hist2021'] if v['hist2021'] > 0 else np.nan,
                             ratio_ssp370=v['ssp370_2022'] / v['hist2021'] if v['hist2021'] > 0 else np.nan))
    pd.DataFrame(rows).to_csv(f'{tabd}/country_join_2021_2022.csv', index=False)


# ----------------------------------------------------------------------------------------------- main
def run(nproc):
    figd, tabd = f'{products()}/figures', f'{products()}/tables'
    os.makedirs(figd, exist_ok=True); os.makedirs(tabd, exist_ok=True)
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    order = ['histsoc', '1850soc', '2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt']
    with ProcessPoolExecutor(max(1, min(nproc, 5)), mp_context=get_context('fork')) as ex:
        results = list(ex.map(review_unit, order))
    rows, steps, extra = [], [], {}
    for u, r, s, e in results:
        rows += r; steps += s; extra[u] = e
    tot = pd.DataFrame(rows)
    tot.to_csv(f'{tabd}/totals_by_region.csv', index=False)
    g = tot[tot.region == 'global']
    bal = g.groupby(['unit', 'sector', 'quantity']).agg(
        years=('year', 'count'), max_abs_residual_km3=('residual_km3', lambda x: float(np.abs(x).max())),
        max_relative_residual=('residual_km3', lambda x: float((np.abs(x) / g.loc[x.index, 'source_km3']).max())),
        max_abs_lost_minus_ledger_km3=('lost_km3', lambda x: float(np.nanmax(np.abs(x - g.loc[x.index, 'ledger_lost_km3']))
                                                                     if g.loc[x.index, 'ledger_lost_km3'].notna().any() else np.nan)),
        written_first_km3=('written_km3', 'first'), written_last_km3=('written_km3', 'last')).reset_index()
    bal.to_csv(f'{tabd}/balance_summary.csv', index=False)
    regbal = tot.groupby(['unit', 'sector', 'quantity', 'region']).residual_km3.apply(lambda x: float(np.abs(x).max())).reset_index()
    regbal.to_csv(f'{tabd}/balance_by_region.csv', index=False)
    # joins and the 2005 anomaly at 5'
    g5 = Grid()
    hist = extra['histsoc']['hist']
    for sec in SECTORS:
        for y in (2004, 2005, 2010):
            steps.append(step_row('histsoc', sec, f'histsoc {y} -> {y + 1} (5 arcmin)', y, hist[y][sec].astype('f8'),
                                  hist[y + 1][sec].astype('f8')))
    ratio_maps = {}
    for u in ('2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt'):
        for sec in SECTORS:
            a = hist[2021][sec].astype('f8')
            b = np.where(g5.mask, read_unit(u, sec, 'demand', 2022) * g5.area * 365 / 1000.0, 0.0)
            steps.append(step_row(u, sec, f'histsoc 2021 -> {u} 2022 (5 arcmin)', 2021, a, b))
            ratio_maps[(u, sec)] = np.where(g5.mask & (a > 0), b / np.where(a > 0, a, 1), np.nan)
    pd.DataFrame(steps).to_csv(f'{tabd}/year_step_cell_changes.csv', index=False)
    pc = pd.DataFrame([r for u in extra.values() if 'maps' in u for r in u['maps']['per_capita']])
    pc.to_csv(f'{tabd}/per_capita_by_continent.csv', index=False)
    pd.DataFrame([r for u in extra.values() if 'maps' in u for r in u['maps']['even_split']]).to_csv(f'{tabd}/even_split_cells.csv', index=False)
    pd.DataFrame([r for u in extra.values() if 'maps' in u for r in u['maps']['within']]).to_csv(f'{tabd}/within_parent_distribution.csv', index=False)
    country_join(D1.water_global_mask(), tabd)
    figures(tot, steps, ratio_maps, hist, g5, figd)
    print('done', datetime.datetime.now(datetime.timezone.utc).isoformat())


def figures(tot, steps, ratio_maps, hist, g, figd):
    plt = D1._plt()
    cut, div, mcolors = cmaps()
    coast, land = coastlines()
    col = {'histsoc': '#1f4e9c', '1850soc': '#8c8c8c', '2021soc': '#2e2e2e', 'ssp1vlsoc-noadapt': '#2a9d5c',
           'ssp3hsoc-noadapt': '#d1495b'}
    regions = ['global'] + list(D1.CONTINENTS)
    for sec in SECTORS:
        for q in ('withdrawal', 'consumption'):
            fig, axs = plt.subplots(2, 4, figsize=(17, 7.5)); axs = axs.ravel()
            for ax, reg in zip(axs, regions):
                for u in UNITS:
                    d = tot[(tot.unit == u) & (tot.sector == sec) & (tot.quantity == q) & (tot.region == reg)].sort_values('year')
                    ax.plot(d.year, d.written_km3, color=col[u], lw=1.4, label=f'{u} (forcing)')
                    ax.plot(d.year, d.source_km3, color=col[u], lw=0.9, ls='--', label=f'{u} (source)')
                ax.set_title(reg, loc='left', fontsize=9); ax.set_xlim(1850, 2100)
            axs[-1].axis('off')
            h, l = axs[0].get_legend_handles_labels(); axs[-1].legend(h, l, fontsize=7, loc='center')
            fig.suptitle(f'{sec} {q} (km3/yr): forcing units (solid) and sources (dashed); the gap is the lost demand')
            fig.tight_layout(); fig.savefig(f'{figd}/totals_{sec}_{q}.png', dpi=120); plt.close(fig)
    for u in ('2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt'):
        map_figure(f'{figd}/join_ratio_{u}.png',
                   [(f'{sec}: {u} 2022 / histsoc 2021', np.log2(ratio_maps[(u, sec)]), div, mcolors.TwoSlopeNorm(0, -2, 2),
                     'log2 ratio of the 5\' demand') for sec in SECTORS], g, coast, land,
                   f'2021 -> 2022 at 5 arcmin: {u}')
    a4, a5, a6 = (hist[y]['manufacturing'].astype('f8') for y in (2004, 2005, 2006))
    map_figure(f'{figd}/anomaly_2005_manufacturing.png',
               [('manufacturing 2005 / 2004', np.log2(np.where(g.mask & (a4 > 0), a5 / np.where(a4 > 0, a4, 1), np.nan)), div,
                 mcolors.TwoSlopeNorm(0, -2, 2), 'log2 ratio'),
                ('manufacturing 2006 / 2005', np.log2(np.where(g.mask & (a5 > 0), a6 / np.where(a5 > 0, a5, 1), np.nan)), div,
                 mcolors.TwoSlopeNorm(0, -2, 2), 'log2 ratio')], g, coast, land, 'histsoc: the 2005 industrial anomaly at 5 arcmin')
    st = pd.DataFrame(steps)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4), sharey=True)
    for ax, sec in zip(axs, SECTORS):
        for u in UNITS:
            d = st[(st.step == f'{u} year to year') & (st.sector == sec)]
            ax.plot(d.year_before + 0.5, 100 * d.share_before_in_cells_halved_or_doubled, color=col[u], lw=1.1, label=u)
        for u in ('2021soc', 'ssp1vlsoc-noadapt', 'ssp3hsoc-noadapt'):
            d = st[(st.step == f'histsoc 2021 -> {u} 2022 (5 arcmin)') & (st.sector == sec)]
            ax.plot([2021.5], 100 * d.share_before_in_cells_halved_or_doubled, 'o', color=col[u])
        ax.set_xlim(1850, 2100); ax.set_title(sec, loc='left')
        ax.set_ylabel('% of the volume in 5\' cells that halve or double')
    axs[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f'{figd}/year_step_cell_changes.png', dpi=120); plt.close(fig)


def submit(nproc):
    logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip()
    text = SBATCH.format(job=f'{TASK}-review', logs=logs, conda=conda, workdir=workdir(), repo=REPO, task=TASK,
                         proc=nproc, mem=f'{8 * nproc}G')
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]
    job_dir = f'{logs}/review_{job_id}'; os.makedirs(job_dir, exist_ok=True)
    with open(f'{job_dir}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {job_dir}/')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--processes', type=int, default=5)
    a = ap.parse_args()
    submit(a.processes) if a.submit else run(a.processes)


if __name__ == '__main__':
    main()
