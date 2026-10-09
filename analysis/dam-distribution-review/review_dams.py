#!/usr/bin/env python3
"""Figures and tables of the dams in the model's dam parameter file and in the ISIMIP4b reservoir data (D19).

Reads (read-only) the dam parameter file of the candidate parameter set (vic-global-5arcmin-version-a, role
`dams`), the GDW tier tables it was built from (vic_parameter T3_extended, unmerged records with source,
GRanD ID and name), the ISIMIP4b reservoirs_dams files (histsoc xlsx; ssp1/ssp3 future hydropower csv) and the
Natural Earth 1:50m countries (continent of each dam), and writes to workdir/analysis/dam-distribution-review/:
  tables/   dams_by_period.csv, scenario_summary.csv, unknown_year_by_source.csv, unknown_year_largest.csv,
            model_isimip_match.csv, model_isimip_year_differences.csv, isimip_not_in_model_largest.csv,
            ssp_future_dams.csv, ssp_future_dams_largest.csv,
            capacity_by_continent.csv, gdw_tier_exclusions.csv, gdw_excluded_by_dor_largest.csv
  figures/  map_model_dams.png, cumulative_capacity.png, scenario_dams.png, unknown_year_dams.png,
            model_vs_isimip_map.png, model_vs_isimip_scatter.png, ssp_future_dams.png, capacity_by_continent.png,
            gdw_excluded_by_dor.png

Usage (always on a compute node):
  review_dams.py --submit     render the Slurm job, keep its record, submit it
  review_dams.py              the computation itself
"""
import argparse, os, re, subprocess, sys, zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
TASK = 'dam-distribution-review'
DAM_FILE = 'parameters/candidates/vic-global-5arcmin-version-a/dams/vic_global_5min_dam_parameters_t3-extended-merged.nc'
# source of the dam file (manifests/parameters/vic-global-5arcmin-version-a.yaml, entry dams): the per-tier
# tables written by vic_parameter tools/build_dam_tier_tables.py from the corrected GDW database
GDW_TABLES = ('/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/candidates/dams/'
              'dam_parameter_candidate_v1/T3_extended')
# the corrected GDW database the tiers are selected from (tier T3_extended: quality <= 4, DOR >= 10 %, capacity
# >= 20 hm3; vic_parameter src/vic_parameter/dams/selection.py)
GDW_ALL = ('/lustre/nobackup/WUR/ESG/liu297/vic_global/00pre_analysis/downscaling5min/08HumanImpact/01Dam/'
           'Data/GDW_reservoirs_corrected_5min.csv')
RES = 'raw/ISIMIP4b/InputData/socioeconomic/reservoirs_dams'
ISIMIP_HIST = f'{RES}/histsoc/reservoirs-dams_1850_2021.xlsx'
SSP = {'ssp1vlsoc-noadapt': f'{RES}/ssp1vlsoc-noadapt/reservoirs-dams_watergap2-2e_gswp3-w5e5_ssp1_2022_2100.csv',
       'ssp3hsoc-noadapt': f'{RES}/ssp3hsoc-noadapt/reservoirs-dams_watergap2-2e_gswp3-w5e5_ssp3_2022_2100.csv'}
PERIODS = [('unknown (0)', 0, 0), ('before 1850', 1, 1849), ('1850', 1850, 1850), ('1851-1899', 1851, 1899),
           ('1900-1949', 1900, 1949), ('1950-1979', 1950, 1979), ('1980-1999', 1980, 1999),
           ('2000-2010', 2000, 2010), ('2011-2020', 2011, 2020), ('2021', 2021, 2021), ('after 2021', 2022, 9998)]
PERIOD_COLOURS = {'before 1850': '#3b0f70', '1850': '#3b0f70', '1851-1899': '#5c2a8f', '1900-1949': '#2c7fb8',
                  '1950-1979': '#41b6c4', '1980-1999': '#a1d99b', '2000-2010': '#fdae61', '2011-2020': '#f46d43',
                  '2021': '#d73027', 'after 2021': '#7f0000'}
UNKNOWN_COLOUR = '#7a7a7a'
SBATCH = """#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=main
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
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
/usr/bin/time -v python3 analysis/{task}/review_dams.py
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def products():
    return f'{workdir()}/analysis/{TASK}'


def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.alpha': 0.3, 'savefig.dpi': 150})
    return plt


def period_of(year):
    """Period label of one construction year (0 = unknown)."""
    for label, a, b in PERIODS:
        if a <= year <= b:
            return label
    return 'after 2021'


# ---------------------------------------------------------------------------------------------- readers
def read_model():
    """One row per dam of the parameter file: index, cell, lat, lon, type, year, capacity."""
    with nc.Dataset(f'{workdir()}/{DAM_FILE}') as ds:
        lat = ds['lat'][:].astype(float); lon = ds['lon'][:].astype(float)
        id_map = np.ma.filled(ds['id_map'][:], -1).astype(np.int64)
        ids = ds['id'][:].astype(np.int64)
        d = pd.DataFrame({'dam_index': np.arange(len(ids)), 'cell_id': ids,
                          'type': np.where(ds['type'][:] == 1, 'global', 'local'),
                          'year': ds['year'][:].astype(int), 'capacity_hm3': ds['capacity'][:].astype(float),
                          'inflow_fraction': ds['inflow_fraction'][:].astype(float)})
    flat = id_map.ravel()
    order = np.argsort(flat); sorted_ids = flat[order]
    k = np.searchsorted(sorted_ids, ids)
    if not np.all(sorted_ids[k] == ids):
        sys.exit('a dam id is not in id_map')
    r, c = np.unravel_index(order[k], id_map.shape)
    d['row'] = r; d['col'] = c; d['lat'] = lat[r]; d['lon'] = lon[c]
    d['period'] = [period_of(y) for y in d.year]
    return d, lat, lon


def read_gdw(lat, lon):
    """Unmerged GDW records of the T3_extended tier with their 5' cell (nearest grid centre of MODEL_LAT/LON)."""
    frames = []
    for name, t in (('globalDams.csv', 'global'), ('localDams.csv', 'local')):
        f = pd.read_csv(f'{GDW_TABLES}/{name}', low_memory=False)
        f['type'] = t
        frames.append(f)
    g = pd.concat(frames, ignore_index=True)
    for c in ('YEAR', 'CAP_MCM', 'GRAND_ID', 'MODEL_LAT_DD', 'MODEL_LONG_DD', 'LAT_DAM', 'LONG_DAM'):
        g[c] = pd.to_numeric(g[c], errors='coerce')
    g['row'] = np.abs(lat[None, :] - g.MODEL_LAT_DD.to_numpy()[:, None]).argmin(axis=1)
    g['col'] = np.abs(lon[None, :] - g.MODEL_LONG_DD.to_numpy()[:, None]).argmin(axis=1)
    return g


def read_xlsx(path):
    """The data table of the ISIMIP reservoirs-dams workbook (one sheet; header row has YEAR and CAP_MCM)."""
    z = zipfile.ZipFile(path)
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    shared = [''.join(x.text or '' for x in si.iter(f'{{{ns["m"]}}}t')) for si in root.findall('m:si', ns)]
    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows = []
    for row in root.iter(f'{{{ns["m"]}}}row'):
        d = {}
        for cell in row.findall('m:c', ns):
            col = re.match(r'[A-Z]+', cell.get('r')).group(0)
            v = cell.find('m:v', ns)
            if v is not None:
                d[col] = shared[int(v.text)] if cell.get('t') == 's' else v.text
        rows.append(d)
    i = next(j for j, r in enumerate(rows) if 'YEAR' in r.values() and 'CAP_MCM' in r.values())
    cols = sorted(rows[i], key=lambda s: (len(s), s))
    t = pd.DataFrame([[r.get(k) for k in cols] for r in rows[i + 1:]], columns=[rows[i][k] for k in cols])
    for c in ('ID', 'YEAR', 'FLAG_ART', 'CAP_MCM', 'LAT_ORIG', 'LON_ORIG', 'LAT_DDM30', 'LON_DDM30'):
        t[c] = pd.to_numeric(t[c], errors='coerce')
    return t.dropna(subset=['CAP_MCM'])      # a few IDs are not numeric (kept; matched by location only)


def continent_lookup():
    """Function (lat, lon arrays) -> Natural Earth continent; points off land go to the nearest country."""
    import shapely
    from cartopy.io import shapereader as shp
    rd = shp.Reader(shp.natural_earth(resolution='50m', category='cultural', name='admin_0_countries'))
    geoms, conts = [], []
    for rec in rd.records():
        geoms.append(rec.geometry); conts.append(rec.attributes['CONTINENT'])
    tree = shapely.STRtree(geoms)

    def lookup(la, lo):
        pts = shapely.points(np.asarray(lo, float), np.asarray(la, float))
        hit = np.full(len(pts), -1)
        pi, gi = tree.query(pts, predicate='within')
        hit[pi] = gi
        miss = np.where(hit < 0)[0]
        if len(miss):
            hit[miss] = tree.query_nearest(pts[miss], all_matches=False)[1]
        out = np.array([conts[g] for g in hit], dtype=object)
        out[out == 'Seven seas (open ocean)'] = 'Oceania'
        return out
    return lookup


# ---------------------------------------------------------------------------------------------- analysis
def attach_gdw(model, gdw):
    """Source attributes of each model dam: the largest GDW record of the same type in its cell."""
    g = gdw.sort_values('CAP_MCM', ascending=False).drop_duplicates(['row', 'col', 'type'])
    keep = ['row', 'col', 'type', 'GDW_ID', 'DAM_NAME', 'RES_NAME', 'COUNTRY', 'ORIG_SRC', 'GRAND_ID', 'LAKE_CTRL',
            'QUALITY', 'YEAR', 'LAT_DAM', 'LONG_DAM']
    m = model.merge(g[keep], on=['row', 'col', 'type'], how='left')
    n = gdw.groupby(['row', 'col', 'type']).size().rename('n_gdw_records').reset_index()
    m = m.merge(n, on=['row', 'col', 'type'], how='left')
    if m.GDW_ID.isna().any():
        print(f'warning: {int(m.GDW_ID.isna().sum())} model dams without a GDW record in their cell')
    return m


def match_isimip(model, gdw, isi):
    """Match ISIMIP histsoc dams to model dams: GRanD ID first, then the nearest GDW dam location within 0.1 deg
    with capacity within a factor 2. Returns the ISIMIP table with the matched model dam_index (or -1)."""
    rec = gdw[['row', 'col', 'type', 'GRAND_ID', 'LAT_DAM', 'LONG_DAM', 'CAP_MCM']].merge(
        model[['row', 'col', 'type', 'dam_index']], on=['row', 'col', 'type'], how='inner')
    by_grand = rec[rec.GRAND_ID > 0].drop_duplicates('GRAND_ID').set_index('GRAND_ID').dam_index
    isi = isi.copy()
    isi['dam_index'] = isi.ID.map(by_grand).fillna(-1).astype(int)
    isi['match'] = np.where(isi.dam_index >= 0, 'grand_id', 'none')
    used = set(isi.dam_index[isi.dam_index >= 0])
    la, lo, cap = rec.LAT_DAM.to_numpy(), rec.LONG_DAM.to_numpy(), rec.CAP_MCM.to_numpy()
    for i in np.where(isi.dam_index < 0)[0]:
        x = isi.iloc[i]
        dist = np.hypot(la - x.LAT_ORIG, (lo - x.LON_ORIG) * np.cos(np.radians(x.LAT_ORIG)))
        ok = (dist < 0.1) & (cap > 0.5 * x.CAP_MCM) & (cap < 2 * x.CAP_MCM)
        if ok.any():
            j = np.where(ok)[0][np.argmin(dist[ok])]
            if rec.dam_index.iloc[j] not in used:
                isi.iloc[i, isi.columns.get_loc('dam_index')] = int(rec.dam_index.iloc[j])
                isi.iloc[i, isi.columns.get_loc('match')] = 'location'
                used.add(int(rec.dam_index.iloc[j]))
    return isi


def scenario_table(model):
    """Dams operating in each DHF scenario under the two rules for unknown years (0)."""
    rows = []
    y = model.year.to_numpy(); cap = model.capacity_hm3.to_numpy(); t = model.type.to_numpy()
    unknown = y == 0
    for rule, unknown_in_1850 in (('unknown = 1850 (ISIMIP convention)', True),
                                  ('unknown = recent (not in 1850soc)', False)):
        for scen, sel in (('1850soc', ((y > 0) & (y <= 1850)) | (unknown & unknown_in_1850)),
                          ('2021soc, 2021soc-from-histsoc, SSP default', y <= 2021),
                          ('histsoc in 1850', ((y > 0) & (y <= 1850)) | (unknown & unknown_in_1850)),
                          ('histsoc in 2021', y <= 2021),
                          ('current file, simulation year >= 2022', np.ones(len(y), bool))):
            rows.append({'unknown_year_rule': rule, 'scenario': scen, 'n_dams': int(sel.sum()),
                         'n_global': int((sel & (t == 'global')).sum()), 'n_local': int((sel & (t == 'local')).sum()),
                         'capacity_km3': round(cap[sel].sum() / 1000, 1),
                         'share_of_file_capacity': round(cap[sel].sum() / cap.sum(), 4)})
    return pd.DataFrame(rows)


def gdw_exclusions():
    """The GDW database against the T3_extended selection rules: which rule removes how much capacity."""
    g = pd.read_csv(GDW_ALL, low_memory=False)
    for c in ('CAP_MCM', 'DOR_PC', 'MODEL_LAT_DD', 'MODEL_LONG_DD', 'GRAND_ID'):
        g[c] = pd.to_numeric(g[c], errors='coerce')
    q = pd.to_numeric(g.QUALITY.astype(str).str[0], errors='coerce')
    big, dor_ok, good = g.CAP_MCM >= 20, g.DOR_PC >= 10, q <= 4
    rows = [('all GDW records', np.ones(len(g), bool)), ('capacity < 20 hm3', ~big),
            ('quality worse than 4', big & ~good), ('DOR < 10 % (capacity >= 20, quality <= 4)', big & good & ~dor_ok),
            ('passing the three rules', big & good & dor_ok)]
    tab = pd.DataFrame([{'records': k, 'n': int(m.sum()), 'capacity_km3': round(g.CAP_MCM[m].sum() / 1000, 1)}
                        for k, m in rows])
    excl = g[big & good & ~dor_ok].copy()
    return tab, excl


# ---------------------------------------------------------------------------------------------- figures
def fig_dor(excl, m, figd, plt):
    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(14, 7.5))
    ax = _map_axes(fig, (1, 1, 1), f'GDW reservoirs left out of the model dam file by the rule DOR >= 10 % '
                                   f'(capacity >= 20 hm3, quality <= 4): {len(excl)} dams, '
                                   f'{excl.CAP_MCM.sum() / 1000:,.0f} km3')
    ax.scatter(m.lon, m.lat, s=_size(m.capacity_hm3), c='#bdbdbd', alpha=0.5, linewidth=0,
               transform=ccrs.PlateCarree(), zorder=2, label='in the model file')
    d = excl.sort_values('CAP_MCM', ascending=False)
    ax.scatter(d.MODEL_LONG_DD, d.MODEL_LAT_DD, s=_size(d.CAP_MCM), c='#e31a1c', alpha=0.75, linewidth=0.2,
               edgecolor='k', transform=ccrs.PlateCarree(), zorder=3, label='left out (DOR < 10 %)')
    for _, r in d.head(10).iterrows():
        ax.annotate(f'{r.DAM_NAME} ({r.CAP_MCM / 1000:.0f} km3, DOR {r.DOR_PC:.0f} %)', (r.MODEL_LONG_DD, r.MODEL_LAT_DD),
                    xycoords=ccrs.PlateCarree()._as_mpl_transform(ax), fontsize=7, xytext=(4, 4),
                    textcoords='offset points')
    _size_legend(ax, loc='lower right')
    hs = [plt.Line2D([], [], marker='o', ls='', color='#bdbdbd', label='in the model file'),
          plt.Line2D([], [], marker='o', ls='', color='#e31a1c', label='left out (DOR < 10 %)')]
    fig.legend(handles=hs, loc='lower center', ncol=2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1)); fig.savefig(f'{figd}/gdw_excluded_by_dor.png'); plt.close(fig)


def _map_axes(fig, pos, title):
    import cartopy.crs as ccrs
    ax = fig.add_subplot(*pos, projection=ccrs.Robinson())
    ax.set_global()
    ax.add_feature(__import__('cartopy.feature', fromlist=['LAND']).LAND, facecolor='#f2efe9', edgecolor='none')
    ax.coastlines(resolution='50m', linewidth=0.3, color='#606060')
    ax.set_title(title, fontsize=10, loc='left')
    return ax


def _size(cap_hm3, scale=1.0):
    """Marker area in points^2 from capacity: proportional to sqrt(capacity), at least 1."""
    return np.maximum(1.0, scale * np.sqrt(np.asarray(cap_hm3, float)) / 4.0)


def _size_legend(ax, scale=1.0, values=(100, 1000, 10000, 100000), unit='hm3', loc='lower left'):
    hs = [ax.scatter([], [], s=_size(v, scale), facecolor='none', edgecolor='k', linewidth=0.6) for v in values]
    ax.legend(hs, [f'{v:,} {unit}' for v in values], loc=loc, fontsize=7, frameon=True, title='capacity',
              title_fontsize=7, scatterpoints=1)


def fig_map_model(m, figd, plt):
    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(14, 10.5))
    for k, t in enumerate(('global', 'local')):
        d = m[m.type == t].sort_values('capacity_hm3', ascending=False)
        ax = _map_axes(fig, (2, 1, k + 1),
                       f'{t} dams in the model dam file: {len(d)} dams, {d.capacity_hm3.sum() / 1000:,.0f} km3 '
                       f'({(d.year == 0).sum()} with unknown year, grey)')
        col = [UNKNOWN_COLOUR if p == 'unknown (0)' else PERIOD_COLOURS[p] for p in d.period]
        ax.scatter(d.lon, d.lat, s=_size(d.capacity_hm3), c=col, alpha=0.75, linewidth=0.2, edgecolor='k',
                   transform=ccrs.PlateCarree(), zorder=3)
        _size_legend(ax)
    hs = [plt.Line2D([], [], marker='o', ls='', color=UNKNOWN_COLOUR, label='unknown year (0)')] + \
         [plt.Line2D([], [], marker='o', ls='', color=c, label=p) for p, c in PERIOD_COLOURS.items() if p != '1850']
    fig.legend(handles=hs, loc='lower center', ncol=6, fontsize=8, title='construction year')
    fig.suptitle('Dams of vic_global_5min_dam_parameters_t3-extended-merged.nc (GDW, tier T3_extended); '
                 'marker area ~ sqrt(capacity)', fontsize=11)
    fig.tight_layout(rect=(0, 0.06, 1, 0.97)); fig.savefig(f'{figd}/map_model_dams.png'); plt.close(fig)


def fig_cumulative(m, isi, figd, plt):
    years = np.arange(1800, 2026)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.8))
    series = [('model file, unknown year counted from 1850', m.year.replace(0, 1850), m.capacity_hm3, '#1f77b4', '-'),
              ('model file, known years only', m.year.where(m.year > 0), m.capacity_hm3, '#1f77b4', '--'),
              ('ISIMIP4b histsoc (unknown set to 1850 by ISIMIP)', isi.YEAR.where(isi.YEAR > 0, 1850), isi.CAP_MCM,
               '#d62728', '-')]
    for label, y, cap, c, ls in series:
        y = np.asarray(y, float); cap = np.asarray(cap, float)
        n = [(y <= yr).sum() for yr in years]
        v = [cap[y <= yr].sum() / 1000 for yr in years]
        axs[0].plot(years, n, color=c, ls=ls, label=label)
        axs[1].plot(years, v, color=c, ls=ls, label=label)
    for ax, t in zip(axs, ('number of dams built by the year', 'cumulative capacity (km3)')):
        ax.set_title(t, loc='left'); ax.set_xlim(1840, 2025); ax.axvline(1850, color='0.5', lw=0.6)
        ax.axvline(2021, color='0.5', lw=0.6)
    axs[0].legend(fontsize=8, loc='upper left')
    fig.suptitle('Dams by construction year: model dam file (GDW T3_extended) and ISIMIP4b reservoirs-dams histsoc',
                 fontsize=10)
    fig.tight_layout(); fig.savefig(f'{figd}/cumulative_capacity.png'); plt.close(fig)


def fig_scenarios(m, figd, plt):
    import cartopy.crs as ccrs
    known_1850 = (m.year > 0) & (m.year <= 1850)
    unknown = m.year == 0
    added = (m.year > 1850) & (m.year <= 2021)
    after = m.year > 2021
    fig = plt.figure(figsize=(14, 10.5))
    panels = [
        ('1850soc: dams built by 1850', [(known_1850, '#3b0f70', 'known year <= 1850'),
                                         (unknown, UNKNOWN_COLOUR, 'unknown year (in or out: rule to decide)')]),
        ('2021soc (and SSP default, 2021soc-from-histsoc): dams built by 2021',
         [(known_1850 | unknown, '#9e9ac8', 'by 1850 or unknown'), (added, '#e6550d', 'built 1851-2021'),
          (after, '#000000', 'built after 2021 (never operating)')]),
    ]
    for k, (title, layers) in enumerate(panels):
        sel = np.zeros(len(m), bool)
        for s, _, _ in layers:
            sel |= s.to_numpy()
        ax = _map_axes(fig, (2, 1, k + 1), title)
        hs = []
        for s, c, lab in layers:
            d = m[s].sort_values('capacity_hm3', ascending=False)
            ax.scatter(d.lon, d.lat, s=_size(d.capacity_hm3), c=c, alpha=0.75, linewidth=0.2, edgecolor='k',
                       transform=ccrs.PlateCarree(), zorder=3)
            hs.append(plt.Line2D([], [], marker='o', ls='', color=c,
                                 label=f'{lab}: {len(d)} dams, {d.capacity_hm3.sum() / 1000:,.0f} km3'))
        ax.legend(handles=hs, loc='lower left', fontsize=8)
    fig.suptitle('Dams operating per DHF scenario (proposal for D19), model dam file', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97)); fig.savefig(f'{figd}/scenario_dams.png'); plt.close(fig)


def fig_unknown(m, figd, plt):
    import cartopy.crs as ccrs
    u = m[m.year == 0].copy()
    u['ORIG_SRC'] = u.ORIG_SRC.fillna('n/a')
    srcs = u.groupby('ORIG_SRC').capacity_hm3.agg(['size', 'sum']).sort_values('sum', ascending=False)
    colours = dict(zip(srcs.index, ['#1b9e77', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d']))
    fig = plt.figure(figsize=(14, 10))
    ax = _map_axes(fig, (2, 1, 1), f'dams with unknown construction year (year 0): {len(u)} dams, '
                                   f'{u.capacity_hm3.sum() / 1000:,.0f} km3, by GDW source')
    for s in srcs.index:
        d = u[u.ORIG_SRC == s]
        ax.scatter(d.lon, d.lat, s=_size(d.capacity_hm3), c=colours[s], alpha=0.75, linewidth=0.2, edgecolor='k',
                   transform=ccrs.PlateCarree(), zorder=3, label=f'{s}: {len(d)} dams, {d.capacity_hm3.sum() / 1000:,.0f} km3')
    big = u.nlargest(8, 'capacity_hm3')
    for _, r in big.iterrows():
        name = r.DAM_NAME if isinstance(r.DAM_NAME, str) else (r.RES_NAME if isinstance(r.RES_NAME, str) else r.COUNTRY)
        ax.annotate(f'{name} ({r.capacity_hm3 / 1000:.1f} km3)', (r.lon, r.lat), xycoords=ccrs.PlateCarree()._as_mpl_transform(ax),
                    fontsize=7, xytext=(4, 4), textcoords='offset points')
    ax.legend(loc='lower left', fontsize=8)
    ax2 = fig.add_subplot(2, 2, 3)
    bins = np.logspace(1, 5, 25)
    for s in srcs.index:
        ax2.hist(u.capacity_hm3[u.ORIG_SRC == s], bins=bins, color=colours[s], alpha=0.7, label=s)
    ax2.hist(m.capacity_hm3[m.year > 0], bins=bins, histtype='step', color='k', label='dams with known year')
    ax2.set_xscale('log'); ax2.set_xlabel('capacity (hm3)'); ax2.set_ylabel('number of dams')
    ax2.set_title('capacity of unknown-year dams', loc='left'); ax2.legend(fontsize=7)
    ax3 = fig.add_subplot(2, 2, 4)
    top = u.nlargest(15, 'capacity_hm3').iloc[::-1]
    lab = [f'{(a if isinstance(a, str) else (b if isinstance(b, str) else "unnamed"))}, {c}'
           for a, b, c in zip(top.DAM_NAME, top.RES_NAME, top.COUNTRY)]
    ax3.barh(lab, top.capacity_hm3 / 1000, color=[colours[s] for s in top.ORIG_SRC])
    ax3.set_xlabel('capacity (km3)'); ax3.set_title('15 largest unknown-year dams', loc='left')
    ax3.tick_params(axis='y', labelsize=7)
    fig.tight_layout(); fig.savefig(f'{figd}/unknown_year_dams.png'); plt.close(fig)


def fig_model_vs_isimip(m, isi, figd, plt):
    import cartopy.crs as ccrs
    matched = set(isi.dam_index[isi.dam_index >= 0])
    only_model = m[~m.dam_index.isin(matched)]
    both = m[m.dam_index.isin(matched)]
    only_isi = isi[isi.dam_index < 0]
    fig = plt.figure(figsize=(14, 7.5))
    ax = _map_axes(fig, (1, 1, 1), 'model dam file (GDW T3_extended) against ISIMIP4b histsoc reservoirs-dams')
    for d, la, lo, cap, c, lab in (
            (both, 'lat', 'lon', 'capacity_hm3', '#2b8cbe', 'in both'),
            (only_model, 'lat', 'lon', 'capacity_hm3', '#f03b20', 'only in the model file'),
            (only_isi, 'LAT_ORIG', 'LON_ORIG', 'CAP_MCM', '#31a354', 'only in ISIMIP4b')):
        ax.scatter(d[lo], d[la], s=_size(d[cap]), c=c, alpha=0.6, linewidth=0.2, edgecolor='k',
                   transform=ccrs.PlateCarree(), zorder=3,
                   label=f'{lab}: {len(d)} dams, {d[cap].sum() / 1000:,.0f} km3')
    ax.legend(loc='lower left', fontsize=8)
    fig.tight_layout(); fig.savefig(f'{figd}/model_vs_isimip_map.png'); plt.close(fig)

    j = isi[isi.dam_index >= 0].merge(m[['dam_index', 'year', 'capacity_hm3']], on='dam_index')
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.8))
    real = j[(j.FLAG_ART != 1) & (j.YEAR > 0)]
    k = real[real.year > 0]
    axs[0].scatter(k.YEAR, k.year, s=6, alpha=0.5)
    axs[0].plot([1800, 2025], [1800, 2025], color='0.4', lw=0.6)
    axs[0].set_xlim(1800, 2025); axs[0].set_ylim(1800, 2025)
    axs[0].set_xlabel('ISIMIP4b YEAR'); axs[0].set_ylabel('model file year')
    axs[0].set_title(f'construction year, matched dams with known years ({len(k)}; same year {(k.YEAR == k.year).sum()})',
                     loc='left', fontsize=9)
    axs[1].scatter(j.CAP_MCM, j.capacity_hm3, s=6, alpha=0.5)
    axs[1].plot([1, 3e5], [1, 3e5], color='0.4', lw=0.6)
    axs[1].set_xscale('log'); axs[1].set_yscale('log')
    axs[1].set_xlabel('ISIMIP4b CAP_MCM (hm3)'); axs[1].set_ylabel('model file capacity (hm3)')
    axs[1].set_title(f'capacity of matched dams ({len(j)})', loc='left', fontsize=9)
    cats = pd.crosstab(np.where(j.year == 0, 'model: unknown', 'model: known'),
                       np.where(j.FLAG_ART == 1, 'ISIMIP: set to 1850', 'ISIMIP: real year'))
    cats.index.name = None; cats.columns.name = None
    cats.plot.bar(ax=axs[2], rot=0)
    axs[2].set_title('year status of matched dams', loc='left', fontsize=9); axs[2].set_ylabel('number of dams')
    fig.tight_layout(); fig.savefig(f'{figd}/model_vs_isimip_scatter.png'); plt.close(fig)


def fig_ssp(ssp, figd, plt):
    import cartopy.crs as ccrs
    from matplotlib import colors as mcolors
    fig = plt.figure(figsize=(14, 13))
    norm = mcolors.Normalize(2022, 2100); cmap = plt.get_cmap('viridis')
    for k, (scen, d) in enumerate(ssp.items()):
        ax = _map_axes(fig, (3, 1, k + 1), f'{scen}: {len(d)} future hydropower dams (WaterGAP2-2e), '
                                           f'{d.volume_hm3.sum() / 1000:,.0f} km3, built {d.year_built.min()}-{d.year_built.max()}')
        d = d.sort_values('volume_hm3', ascending=False)
        sc = ax.scatter(d.longitude, d.latitude, s=_size(d.volume_hm3), c=d.year_built, cmap=cmap, norm=norm,
                        alpha=0.8, linewidth=0.2, edgecolor='k', transform=ccrs.PlateCarree(), zorder=3)
        _size_legend(ax, values=(100, 1000, 10000, 50000), unit='hm3')
    cax = fig.add_axes((0.92, 0.42, 0.012, 0.45)); fig.colorbar(sc, cax=cax, label='year built')
    ax = fig.add_subplot(3, 2, 5)
    years = np.arange(2022, 2101)
    for scen, d in ssp.items():
        ax.plot(years, [d.volume_hm3[d.year_built <= y].sum() / 1000 for y in years], label=scen)
    ax.set_title('cumulative volume of new dams (km3)', loc='left'); ax.legend(fontsize=8)
    ax = fig.add_subplot(3, 2, 6)
    t = pd.DataFrame({s: d.groupby('continent').volume_hm3.sum() / 1000 for s, d in ssp.items()}).fillna(0)
    t.sort_values(t.columns[-1]).plot.barh(ax=ax)
    ax.set_xlabel('volume (km3)'); ax.set_title('new dam volume by continent (2022-2100)', loc='left')
    fig.subplots_adjust(left=0.05, right=0.9, top=0.97, bottom=0.04, hspace=0.25)
    fig.savefig(f'{figd}/ssp_future_dams.png'); plt.close(fig)


def fig_continent(tab, figd, plt):
    fig, ax = plt.subplots(figsize=(10, 4.8))
    tab.plot.bar(ax=ax, rot=20)
    ax.set_ylabel('capacity (km3)')
    ax.set_title('capacity by continent: model file (dams by 1850, by 2021) and ISIMIP4b histsoc 2021', loc='left')
    fig.tight_layout(); fig.savefig(f'{figd}/capacity_by_continent.png'); plt.close(fig)


# ---------------------------------------------------------------------------------------------- run
def run():
    out = products(); figd = f'{out}/figures'; tabd = f'{out}/tables'
    os.makedirs(figd, exist_ok=True); os.makedirs(tabd, exist_ok=True)
    plt = _plt()
    model, lat, lon = read_model()
    gdw = read_gdw(lat, lon)
    m = attach_gdw(model, gdw)
    isi = read_xlsx(f'{workdir()}/{ISIMIP_HIST}')
    isi = match_isimip(m, gdw, isi)
    cont = continent_lookup()
    m['continent'] = cont(m.lat, m.lon)
    isi['continent'] = cont(isi.LAT_ORIG, isi.LON_ORIG)
    ssp = {}
    for scen, path in SSP.items():
        d = pd.read_csv(f'{workdir()}/{path}')
        d['volume_hm3'] = pd.to_numeric(d['Lake volume [m3]'], errors='coerce') / 1e6
        d['continent'] = cont(d.latitude, d.longitude)
        ssp[scen] = d
    print(f'model {len(m)} dams; GDW records {len(gdw)}; ISIMIP histsoc {len(isi)}; '
          + '; '.join(f'{s} {len(d)}' for s, d in ssp.items()))

    # tables
    rows = []
    for label, a, b in PERIODS:
        s = m[(m.year >= a) & (m.year <= b)]
        si = isi[(isi.YEAR >= a) & (isi.YEAR <= b)] if a > 0 else isi[isi.YEAR.isna() | (isi.YEAR <= 0)]
        rows.append({'period': label, 'model_n': len(s), 'model_n_global': int((s.type == 'global').sum()),
                     'model_n_local': int((s.type == 'local').sum()),
                     'model_capacity_km3': round(s.capacity_hm3.sum() / 1000, 1),
                     'isimip_n': len(si), 'isimip_n_flag_art': int((si.FLAG_ART == 1).sum()),
                     'isimip_capacity_km3': round(si.CAP_MCM.sum() / 1000, 1)})
    pd.DataFrame(rows).to_csv(f'{tabd}/dams_by_period.csv', index=False)
    scenario_table(m).to_csv(f'{tabd}/scenario_summary.csv', index=False)
    u = m[m.year == 0]
    u.groupby(u.ORIG_SRC.fillna('n/a')).agg(n=('dam_index', 'size'), capacity_km3=('capacity_hm3', lambda x: round(x.sum() / 1000, 1)),
                                            n_global=('type', lambda x: int((x == 'global').sum())),
                                            median_capacity_hm3=('capacity_hm3', 'median')) \
        .sort_values('capacity_km3', ascending=False).to_csv(f'{tabd}/unknown_year_by_source.csv')
    u.nlargest(30, 'capacity_hm3')[['dam_index', 'type', 'capacity_hm3', 'lat', 'lon', 'GDW_ID', 'DAM_NAME', 'RES_NAME',
                                    'COUNTRY', 'ORIG_SRC', 'GRAND_ID', 'LAKE_CTRL', 'QUALITY']] \
        .to_csv(f'{tabd}/unknown_year_largest.csv', index=False)
    matched = set(isi.dam_index[isi.dam_index >= 0])
    j = isi[isi.dam_index >= 0].merge(m[['dam_index', 'year', 'capacity_hm3']], on='dam_index')
    pd.DataFrame([
        {'item': 'model dams', 'n': len(m), 'capacity_km3': m.capacity_hm3.sum() / 1000},
        {'item': 'ISIMIP4b histsoc dams', 'n': len(isi), 'capacity_km3': isi.CAP_MCM.sum() / 1000},
        {'item': 'matched by GRanD ID', 'n': int((isi.match == 'grand_id').sum()),
         'capacity_km3': isi.CAP_MCM[isi.match == 'grand_id'].sum() / 1000},
        {'item': 'matched by location (0.1 deg, capacity within x2)', 'n': int((isi.match == 'location').sum()),
         'capacity_km3': isi.CAP_MCM[isi.match == 'location'].sum() / 1000},
        {'item': 'ISIMIP only', 'n': int((isi.dam_index < 0).sum()), 'capacity_km3': isi.CAP_MCM[isi.dam_index < 0].sum() / 1000},
        {'item': 'model only', 'n': int((~m.dam_index.isin(matched)).sum()),
         'capacity_km3': m.capacity_hm3[~m.dam_index.isin(matched)].sum() / 1000},
        {'item': 'matched, model year unknown, ISIMIP real year', 'n': int(((j.year == 0) & (j.FLAG_ART != 1) & (j.YEAR > 0)).sum()),
         'capacity_km3': j.capacity_hm3[(j.year == 0) & (j.FLAG_ART != 1) & (j.YEAR > 0)].sum() / 1000},
        {'item': 'matched, both years known, same year', 'n': int(((j.year > 0) & (j.YEAR == j.year)).sum()),
         'capacity_km3': j.capacity_hm3[(j.year > 0) & (j.YEAR == j.year)].sum() / 1000},
        {'item': 'matched, both years known, differ by more than 2 years',
         'n': int(((j.year > 0) & (j.FLAG_ART != 1) & ((j.YEAR - j.year).abs() > 2)).sum()),
         'capacity_km3': j.capacity_hm3[(j.year > 0) & (j.FLAG_ART != 1) & ((j.YEAR - j.year).abs() > 2)].sum() / 1000},
    ]).round(1).to_csv(f'{tabd}/model_isimip_match.csv', index=False)
    diff = j[(j.year > 0) & (j.FLAG_ART != 1) & ((j.YEAR - j.year).abs() > 2)]
    diff[['ID', 'DAM_NAME', 'COUNTRY', 'CAP_MCM', 'capacity_hm3', 'YEAR', 'year', 'match']] \
        .rename(columns={'YEAR': 'isimip_year', 'year': 'model_year', 'CAP_MCM': 'isimip_capacity_hm3',
                         'capacity_hm3': 'model_capacity_hm3'}) \
        .sort_values('model_capacity_hm3', ascending=False).to_csv(f'{tabd}/model_isimip_year_differences.csv', index=False)
    isi[isi.dam_index < 0].nlargest(30, 'CAP_MCM')[['ID', 'DAM_NAME', 'COUNTRY', 'CAP_MCM', 'YEAR', 'FLAG_ART',
                                                    'LAT_ORIG', 'LON_ORIG', 'SOURCE']] \
        .to_csv(f'{tabd}/isimip_not_in_model_largest.csv', index=False)
    srows = []
    for scen, d in ssp.items():
        for a, b in ((2022, 2030), (2031, 2050), (2051, 2075), (2076, 2100), (2022, 2100)):
            s = d[(d.year_built >= a) & (d.year_built <= b)]
            srows.append({'scenario': scen, 'years': f'{a}-{b}', 'n_dams': len(s),
                          'volume_km3': round(s.volume_hm3.sum() / 1000, 1),
                          'production_TWh': round(pd.to_numeric(s['Production [GWh]'], errors='coerce').sum() / 1000, 1)})
    pd.DataFrame(srows).to_csv(f'{tabd}/ssp_future_dams.csv', index=False)
    pd.concat([d.assign(scenario=s) for s, d in ssp.items()]).nlargest(30, 'volume_hm3')[
        ['scenario', 'year_built', 'latitude', 'longitude', 'Continent_name', 'country_iso_id', 'volume_hm3',
         'Lake surface [m2]', 'Dam height [m]', 'Production [GWh]', 'DDM30/ISIMIP routing area [km2]']] \
        .to_csv(f'{tabd}/ssp_future_dams_largest.csv', index=False)
    ctab = pd.DataFrame({
        'model, built by 1850 (unknown counted)': m[m.year <= 1850].groupby('continent').capacity_hm3.sum() / 1000,
        'model, built by 2021': m[m.year <= 2021].groupby('continent').capacity_hm3.sum() / 1000,
        'ISIMIP4b histsoc 2021': isi.groupby('continent').CAP_MCM.sum() / 1000}).fillna(0).round(1)
    ctab = ctab.sort_values('model, built by 2021', ascending=False)
    ctab.to_csv(f'{tabd}/capacity_by_continent.csv')

    fig_map_model(m, figd, plt)
    fig_cumulative(m, isi, figd, plt)
    fig_scenarios(m, figd, plt)
    fig_unknown(m, figd, plt)
    fig_model_vs_isimip(m, isi, figd, plt)
    fig_ssp(ssp, figd, plt)
    fig_continent(ctab, figd, plt)
    tab, excl = gdw_exclusions()
    tab.to_csv(f'{tabd}/gdw_tier_exclusions.csv', index=False)
    excl.nlargest(40, 'CAP_MCM')[['GDW_ID', 'GRAND_ID', 'DAM_NAME', 'RES_NAME', 'COUNTRY', 'CAP_MCM', 'DOR_PC', 'QUALITY',
                                  'YEAR_DAM', 'INSTREAM']].to_csv(f'{tabd}/gdw_excluded_by_dor_largest.csv', index=False)
    fig_dor(excl, m, figd, plt)
    print('done')


def submit():
    logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    conda = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip()
    text = SBATCH.format(job=f'{TASK}', logs=logs, conda=conda, workdir=workdir(), repo=REPO, task=TASK)
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
    a = ap.parse_args()
    submit() if a.submit else run()


if __name__ == '__main__':
    main()
