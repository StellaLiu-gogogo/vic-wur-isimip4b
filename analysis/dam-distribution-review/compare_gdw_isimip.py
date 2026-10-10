#!/usr/bin/env python3
"""Dam-by-dam comparison of the GDW v1.0 database with the ISIMIP4b reservoirs-dams histsoc data (D19, dam list).

Question: is every ISIMIP4b histsoc dam present in GDW, and what would candidate GDW selection rules remove?

Reads (read-only):
  - the corrected GDW reservoir table at 5' (GDW v1.0 reservoirs layer plus MODEL_* columns of the 5' snapping,
    01CreateDamDatabase.py of the legacy area), the table the model dam file was selected from;
  - the GDW v1.0 shapefile attribute tables (.dbf) of the reservoirs layer and of the barriers layer (all dams,
    also those without a mapped reservoir), legacy area, not yet in raw/ (D15);
  - the ISIMIP4b reservoirs-dams histsoc workbook (raw/ISIMIP4b/...);
  - the model dam file (5' grid and active cells, for the cell count only).
Matching, one to one (every GDW record used at most once):
  1. GRanD ID: ISIMIP dams whose SOURCE is empty (GRanD records) with ID = GDW GRAND_ID; a pair farther apart
     than 10 km or with a capacity ratio outside [0.5, 2] is kept but labelled grand_id_suspect;
  2. location: ISIMIP LAT_ORIG/LON_ORIG against GDW LAT_DAM/LONG_DAM, capacity ratio in [0.5, 2], tiers 2, 5 and
     10 km in turn, nearest pairs first;
  steps 1-2 run on the corrected table, then for the remaining ISIMIP dams on the GDW records that are not in it
  (barriers layer and the reservoir records the corrected table lost);
  3. name hints for the rest (GDW records within 50 km, similarity of dam, reservoir and river names), listed for
     manual review and not counted as matched.
Writes to workdir/analysis/dam-distribution-review/:
  tables/   gdw_layers.csv, gdw_reservoirs_not_in_corrected.csv, gdw_isimip_match.csv, gdw_isimip_suspect_reasons.csv, gdw_isimip_match_summary.csv, gdw_isimip_unmatched_largest.csv,
            gdw_isimip_name_hints.csv, gdw_rule_effects.csv, gdw_offstream_largest.csv, gdw_dor_missing_largest.csv,
            gdw_isimip_year_comparison.csv, gdw_cell_multiplicity.csv, gdw_cell_multiple_dams.csv
  figures/  gdw_isimip_match_map.png, gdw_isimip_distance.png, gdw_rule_effects.png,
            gdw_offstream_dor_missing_map.png, gdw_isimip_year_scatter.png, gdw_cell_multiplicity_map.png

Usage (always on a compute node):
  compare_gdw_isimip.py --submit     render the Slurm job, keep its record, submit it
  compare_gdw_isimip.py              the computation itself
"""
import argparse, difflib, os, re, struct, sys

import numpy as np
import pandas as pd
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import review_dams as rd   # noqa: E402  (readers, paths, plotting helpers, Slurm submission)

GDW_DIR = '/lustre/nobackup/WUR/ESG/liu297/vic_global/00pre_analysis/downscaling5min/08HumanImpact/01Dam/Data'
GDW_CORRECTED = f'{GDW_DIR}/GDW_reservoirs_corrected_5min.csv'
GDW_DBF = {'reservoirs': f'{GDW_DIR}/GDW_v1_0_shp/GDW_reservoirs_v1_0.dbf',
           'barriers': f'{GDW_DIR}/GDW_v1_0_shp/GDW_barriers_v1_0.dbf'}
TIERS_KM = (2.0, 5.0, 10.0)
RATIO = (0.5, 2.0)
HINT_KM = 50.0
EARTH_KM = 6371.0
NUMERIC = ('GDW_ID', 'GRAND_ID', 'CAP_MCM', 'DOR_PC', 'LAT_DAM', 'LONG_DAM', 'YEAR_DAM', 'MODEL_LAT_DD',
           'MODEL_LONG_DD', 'MODEL_CATCH_FRAC', 'MODEL_AREA_FRAC')
METHOD_ORDER = ['grand_id', 'grand_id_suspect', 'location_2km', 'location_5km', 'location_10km',
                'other_layer_grand_id', 'other_layer_grand_id_suspect', 'other_layer_location_2km',
                'other_layer_location_5km', 'other_layer_location_10km', 'unmatched']


# ---------------------------------------------------------------------------------------------- readers
def read_dbf(path):
    """Attribute table of a shapefile (.dbf, dBASE III) as strings; the encoding comes from the .cpg file."""
    cpg = path[:-4] + '.cpg'
    enc = open(cpg).read().strip() if os.path.exists(cpg) else 'latin-1'
    with open(path, 'rb') as fh:
        head = fh.read(32)
        n, header_len, record_len = struct.unpack('<IHH', head[4:12])
        fields = []
        while True:
            d = fh.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b'\0')[0].decode('ascii'), d[16]))
        fh.seek(header_len)
        raw = fh.read(n * record_len)
    rows = []
    for i in range(n):
        rec = raw[i * record_len:(i + 1) * record_len]
        pos, row = 1, [rec[:1] == b'*']
        for _, width in fields:
            row.append(rec[pos:pos + width].decode(enc, errors='replace').strip())
            pos += width
        rows.append(row)
    return pd.DataFrame(rows, columns=['deleted'] + [f for f, _ in fields])


def read_shp_points(path):
    """x, y of every record of a point shapefile (shape type 1), in record order."""
    with open(path, 'rb') as fh:
        data = fh.read()
    if struct.unpack('<i', data[32:36])[0] != 1:
        return None
    xs, ys, pos = [], [], 100
    while pos < len(data):
        _, words = struct.unpack('>ii', data[pos:pos + 8])
        st = struct.unpack('<i', data[pos + 8:pos + 12])[0]
        x, y = struct.unpack('<dd', data[pos + 12:pos + 28]) if st == 1 else (np.nan, np.nan)
        xs.append(x); ys.append(y)
        pos += 8 + 2 * words
    return np.array(xs), np.array(ys)


def read_layer(path):
    """Attribute table of a GDW layer; for a point layer, a missing LAT_DAM/LONG_DAM is taken from the geometry."""
    t = read_dbf(path)
    pts = read_shp_points(path[:-4] + '.shp')
    t = prepare(t)
    t['latlon_from_geometry'] = False
    if pts is not None:
        if len(pts[0]) != len(t):
            sys.exit(f'{path}: {len(pts[0])} shapes, {len(t)} attribute records')
        bad = t.LAT_DAM.isna() | t.LONG_DAM.isna() | (t.LAT_DAM.abs() > 90) | (t.LONG_DAM.abs() > 180) | \
            ((t.LAT_DAM == 0) & (t.LONG_DAM == 0))
        t.loc[bad, 'LONG_DAM'] = pts[0][bad.to_numpy()]
        t.loc[bad, 'LAT_DAM'] = pts[1][bad.to_numpy()]
        t['latlon_from_geometry'] = bad
    return t[~t.deleted].drop(columns='deleted')


def prepare(g):
    for c in NUMERIC:
        if c in g:
            g[c] = pd.to_numeric(g[c], errors='coerce')
    g['CAP_MCM'] = g.CAP_MCM.where(g.CAP_MCM > 0)          # -99 = missing in the barriers layer
    g['quality'] = pd.to_numeric(g['QUALITY'].astype(str).str[0], errors='coerce')
    g['offstream'] = g['INSTREAM'].astype(str).str.strip().str.lower() == 'offstream'
    g['dor_missing'] = g.DOR_PC.isna() | (g.DOR_PC <= -99)
    g['year_gdw'] = g.YEAR_DAM.where(g.YEAR_DAM > 0)
    return g


def unit_vectors(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def great_circle_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ---------------------------------------------------------------------------------------------- matching
def match_pool(isi, pool, prefix):
    """Steps 1 and 2 of the matching against one GDW pool. Fills isi columns for the dams not yet matched."""
    from scipy.spatial import cKDTree
    used = set()
    todo = isi.method.isna()
    # 1. GRanD ID (GRanD-sourced ISIMIP records only)
    grand = pool[pool.GRAND_ID > 0]
    for i in isi.index[todo & isi.is_grand & isi.ID.notna()]:
        cand = grand[grand.GRAND_ID == isi.at[i, 'ID']]
        cand = cand[~cand.index.isin(used)]
        if cand.empty:
            continue
        d = great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], cand.LAT_DAM.to_numpy(), cand.LONG_DAM.to_numpy())
        j = cand.index[int(np.nanargmin(np.where(np.isnan(d), np.inf, d)))]
        dist = float(great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], pool.at[j, 'LAT_DAM'], pool.at[j, 'LONG_DAM']))
        ratio = pool.at[j, 'CAP_MCM'] / isi.at[i, 'CAP_MCM'] if isi.at[i, 'CAP_MCM'] > 0 else np.nan
        ok = dist <= TIERS_KM[-1] and RATIO[0] <= ratio <= RATIO[1]
        assign(isi, i, pool, j, f'{prefix}grand_id' if ok else f'{prefix}grand_id_suspect', dist, ratio)
        used.add(j)
    # 2. location tiers, nearest pairs first
    ok_pool = pool[pool.LAT_DAM.notna() & pool.LONG_DAM.notna()]
    tree = cKDTree(unit_vectors(ok_pool.LAT_DAM, ok_pool.LONG_DAM))
    for tier in TIERS_KM:
        todo = isi.index[isi.method.isna()]
        if not len(todo):
            break
        xyz = unit_vectors(isi.loc[todo, 'LAT_ORIG'], isi.loc[todo, 'LON_ORIG'])
        chord = 2 * np.sin(tier / EARTH_KM / 2)
        pairs = []
        for k, cands in enumerate(tree.query_ball_point(xyz, chord)):
            i = todo[k]
            for c in cands:
                j = ok_pool.index[c]
                if j in used or not isi.at[i, 'CAP_MCM'] > 0:
                    continue
                ratio = pool.at[j, 'CAP_MCM'] / isi.at[i, 'CAP_MCM']
                if not RATIO[0] <= ratio <= RATIO[1]:
                    continue
                d = float(great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], pool.at[j, 'LAT_DAM'], pool.at[j, 'LONG_DAM']))
                if d <= tier:
                    pairs.append((d, i, j, ratio))
        done = set()
        for d, i, j, ratio in sorted(pairs, key=lambda p: p[0]):
            if i in done or j in used:
                continue
            assign(isi, i, pool, j, f'{prefix}location_{tier:.0f}km', d, ratio)
            done.add(i); used.add(j)
    return used


GDW_KEEP = ['GDW_ID', 'GRAND_ID', 'DAM_NAME', 'RES_NAME', 'COUNTRY', 'CAP_MCM', 'year_gdw', 'INSTREAM', 'QUALITY',
            'DOR_PC', 'LAKE_CTRL', 'MODEL_CATCH_FRAC', 'LAT_DAM', 'LONG_DAM', 'layer']


def assign(isi, i, pool, j, method, dist, ratio):
    isi.at[i, 'method'] = method
    isi.at[i, 'gdw_index'] = j
    isi.at[i, 'distance_km'] = dist
    isi.at[i, 'capacity_ratio_gdw_to_isimip'] = ratio
    for c in GDW_KEEP:
        isi.at[i, f'gdw_{c}'] = pool.at[j, c] if c in pool else np.nan
    isi.at[i, 'gdw_has_model_latlon'] = bool(pd.notna(pool.at[j, 'MODEL_LAT_DD']) and pd.notna(pool.at[j, 'MODEL_LONG_DD'])) \
        if 'MODEL_LAT_DD' in pool else False


def _norm(s):
    s = str(s).lower() if isinstance(s, str) else ''
    s = re.sub(r'\b(dam|reservoir|lake|barrage|res|dike|weir|presa|represa|embalse|barragem|vodokhranilishche)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def name_hints(isi, gdw_all):
    """Up to 3 GDW records within HINT_KM of every unmatched ISIMIP dam, ranked by name similarity."""
    from scipy.spatial import cKDTree
    ok = gdw_all[gdw_all.LAT_DAM.notna() & gdw_all.LONG_DAM.notna()]
    tree = cKDTree(unit_vectors(ok.LAT_DAM, ok.LONG_DAM))
    rows = []
    todo = isi[isi.method == 'unmatched']
    xyz = unit_vectors(todo.LAT_ORIG, todo.LON_ORIG)
    for k, cands in enumerate(tree.query_ball_point(xyz, 2 * np.sin(HINT_KM / EARTH_KM / 2))):
        x = todo.iloc[k]
        scored = []
        for c in cands:
            g = ok.iloc[c]
            name = max(difflib.SequenceMatcher(None, _norm(x.DAM_NAME), _norm(v)).ratio() if _norm(x.DAM_NAME) and _norm(v) else 0.0
                       for v in (g.DAM_NAME, g.RES_NAME, g.get('ALT_NAME', '')))
            river = difflib.SequenceMatcher(None, _norm(x.RIVER), _norm(g.RIVER)).ratio() \
                if _norm(x.RIVER) and _norm(g.RIVER) else 0.0
            d = float(great_circle_km(x.LAT_ORIG, x.LON_ORIG, g.LAT_DAM, g.LONG_DAM))
            scored.append((name + 0.5 * river - d / HINT_KM * 0.2, name, river, d, g))
        for rank, (score, name, river, d, g) in enumerate(sorted(scored, key=lambda s: -s[0])[:3]):
            rows.append({'isimip_ID': x.ID, 'isimip_DAM_NAME': x.DAM_NAME, 'isimip_RIVER': x.RIVER,
                         'isimip_COUNTRY': x.COUNTRY, 'isimip_CAP_MCM': x.CAP_MCM, 'isimip_YEAR': x.YEAR, 'rank': rank + 1,
                         'gdw_layer': g.layer, 'gdw_GDW_ID': g.GDW_ID, 'gdw_DAM_NAME': g.DAM_NAME, 'gdw_RES_NAME': g.RES_NAME,
                         'gdw_RIVER': g.RIVER, 'gdw_COUNTRY': g.COUNTRY, 'gdw_CAP_MCM': g.CAP_MCM, 'gdw_YEAR_DAM': g.YEAR_DAM,
                         'distance_km': round(d, 2), 'name_similarity': round(name, 2), 'river_similarity': round(river, 2),
                         'capacity_ratio_gdw_to_isimip': round(g.CAP_MCM / x.CAP_MCM, 3) if x.CAP_MCM > 0 else np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------- rules
def rule_flags(g):
    """Candidate removal rules on GDW records (True = removed)."""
    cap = g.CAP_MCM.fillna(0)
    f = pd.DataFrame(index=g.index)
    f['quality 5'] = g.quality == 5
    f['DOR missing (-99)'] = g.dor_missing
    f['Offstream'] = g.offstream
    f['capacity < 20 hm3'] = cap < 20
    f['DOR < 10 % (DOR known)'] = ~g.dor_missing & (g.DOR_PC < 10)
    f['current T3_extended (capacity < 20, quality > 4, DOR < 10 or missing)'] = \
        (cap < 20) | ~(g.quality <= 4) | ~(g.DOR_PC >= 10)
    f['proposed A (quality 5, DOR missing, Offstream)'] = f['quality 5'] | f['DOR missing (-99)'] | f['Offstream']
    f['proposed B (A + capacity < 20 hm3)'] = f['proposed A (quality 5, DOR missing, Offstream)'] | f['capacity < 20 hm3']
    return f


def rule_table(groups):
    rows = []
    for label, g in groups.items():
        f = rule_flags(g)
        rows.append({'group': label, 'rule': 'all records', 'n': len(g), 'capacity_km3': g.CAP_MCM.sum() / 1000})
        for r in f.columns:
            m = f[r]
            rows.append({'group': label, 'rule': r, 'n': int(m.sum()), 'capacity_km3': g.CAP_MCM[m].sum() / 1000,
                         'n_kept': int((~m).sum()), 'capacity_kept_km3': g.CAP_MCM[~m].sum() / 1000})
    return pd.DataFrame(rows).round(1)


# ---------------------------------------------------------------------------------------------- cells
def cell_counts(sel, lat, lon, active):
    """Cell (row, col) of each selected record: MODEL_LAT/LONG_DD when present, else the dam location."""
    la = sel.MODEL_LAT_DD.where(sel.MODEL_LAT_DD.notna(), sel.LAT_DAM).to_numpy()
    lo = sel.MODEL_LONG_DD.where(sel.MODEL_LONG_DD.notna(), sel.LONG_DAM).to_numpy()
    dlat, dlon = lat[1] - lat[0], lon[1] - lon[0]
    r = np.clip(np.round((la - lat[0]) / dlat).astype(int), 0, len(lat) - 1)
    c = np.clip(np.round((lo - lon[0]) / dlon).astype(int), 0, len(lon) - 1)
    out = sel.assign(row=r, col=c, cell_active=active[r, c], cell_from_model=sel.MODEL_LAT_DD.notna().to_numpy())
    return out


# ---------------------------------------------------------------------------------------------- figures
COLOURS = {'grand_id': '#2b8cbe', 'grand_id_suspect': '#a6bddb', 'location_2km': '#31a354', 'location_5km': '#74c476',
           'location_10km': '#bae4b3', 'other_layer': '#ff7f00', 'unmatched': '#e31a1c'}


def _group(method):
    if method.startswith('other_layer'):
        return 'other_layer'
    return method


def fig_match_map(isi, figd, plt):
    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(14, 8))
    ax = rd._map_axes(fig, (1, 1, 1), 'ISIMIP4b histsoc dams found in GDW v1.0, by match method')
    g = isi.assign(grp=isi.method.map(_group))
    handles = []
    for k in ['grand_id', 'grand_id_suspect', 'location_2km', 'location_5km', 'location_10km', 'other_layer', 'unmatched']:
        d = g[g.grp == k].sort_values('CAP_MCM', ascending=False)
        top = k == 'unmatched'
        ax.scatter(d.LON_ORIG, d.LAT_ORIG, s=rd._size(d.CAP_MCM), c=COLOURS[k], alpha=0.8 if top else 0.5,
                   linewidth=0.3 if top else 0.1, edgecolor='k', transform=ccrs.PlateCarree(), zorder=4 if top else 3)
        lab = {'other_layer': 'only in GDW records outside the corrected table'}.get(k, k)
        handles.append(plt.Line2D([], [], marker='o', ls='', color=COLOURS[k],
                                  label=f'{lab}: {len(d)} dams, {d.CAP_MCM.sum() / 1000:,.1f} km3'))
    for _, r in g[g.grp == 'unmatched'].nlargest(10, 'CAP_MCM').iterrows():
        ax.annotate(f'{r.DAM_NAME} ({r.CAP_MCM / 1000:.1f} km3)', (r.LON_ORIG, r.LAT_ORIG),
                    xycoords=ccrs.PlateCarree()._as_mpl_transform(ax), fontsize=7, xytext=(4, 4),
                    textcoords='offset points', color='#99000d')
    rd._size_legend(ax, loc='lower right')
    fig.legend(handles=handles, loc='lower center', ncol=3, fontsize=8)
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(f'{figd}/gdw_isimip_match_map.png'); plt.close(fig)


def fig_distance(isi, figd, plt):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
    m = isi[isi.method != 'unmatched']
    for k, c in (('grand_id', COLOURS['grand_id']), ('location', COLOURS['location_2km'])):
        d = m[m.method.str.contains(k)]
        axs[0].hist(np.clip(d.distance_km, 1e-3, None), bins=np.logspace(-3, 3, 49), alpha=0.6, color=c,
                    label=f'{k} ({len(d)})')
        axs[1].hist(np.clip(d.capacity_ratio_gdw_to_isimip, 1e-2, 1e2), bins=np.logspace(-2, 2, 49), alpha=0.6, color=c,
                    label=f'{k} ({len(d)})')
    for ax, t in zip(axs, ('distance ISIMIP LAT/LON_ORIG to GDW LAT/LONG_DAM (km)', 'capacity ratio GDW / ISIMIP')):
        ax.set_xscale('log'); ax.set_yscale('log'); ax.set_title(t, loc='left'); ax.legend(fontsize=8)
        ax.set_ylabel('number of dams (log scale)')
    axs[0].set_xlabel('distances below 1 m are shown at 1 m')
    axs[0].axvline(10, color='0.4', lw=0.6); axs[1].axvline(0.5, color='0.4', lw=0.6); axs[1].axvline(2, color='0.4', lw=0.6)
    fig.tight_layout(); fig.savefig(f'{figd}/gdw_isimip_distance.png'); plt.close(fig)


def fig_rules(tab, figd, plt):
    t = tab[tab.rule != 'all records']
    fig, axs = plt.subplots(1, 2, figsize=(15, 6))
    for ax, col, lab in ((axs[0], 'n', 'records removed'), (axs[1], 'capacity_km3', 'capacity removed (km3)')):
        p = t.pivot(index='rule', columns='group', values=col).loc[t.rule.unique()]
        p.iloc[::-1].plot.barh(ax=ax)
        ax.set_xlabel(lab); ax.set_ylabel('')
        ax.tick_params(axis='y', labelsize=7)
    axs[1].set_yticklabels([])
    axs[0].legend(fontsize=7); axs[1].legend(fontsize=7)
    fig.suptitle('Candidate GDW selection rules: what each removes, among GDW records matched to ISIMIP4b and outside it',
                 fontsize=10)
    fig.tight_layout(); fig.savefig(f'{figd}/gdw_rule_effects.png'); plt.close(fig)


def fig_offstream_dor(g, isimip_gdw, figd, plt):
    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(14, 11))
    for k, (title, m) in enumerate((('Offstream records', g.offstream), ('records with DOR missing (-99)', g.dor_missing))):
        d = g[m].sort_values('CAP_MCM', ascending=False)
        inn = d.index.isin(isimip_gdw)
        ax = rd._map_axes(fig, (2, 1, k + 1), f'GDW corrected table, {title}: {len(d)} records, '
                                              f'{d.CAP_MCM.sum() / 1000:,.0f} km3 ({inn.sum()} in ISIMIP4b, '
                                              f'{d.CAP_MCM[inn].sum() / 1000:,.0f} km3)')
        for sel, c, lab in ((~inn, '#fd8d3c', 'not in ISIMIP4b'), (inn, '#08519c', 'in ISIMIP4b')):
            ax.scatter(d.LONG_DAM[sel], d.LAT_DAM[sel], s=rd._size(d.CAP_MCM[sel]), c=c, alpha=0.7, linewidth=0.2,
                       edgecolor='k', transform=ccrs.PlateCarree(), zorder=3, label=lab)
        for _, r in d.head(6).iterrows():
            name = r.DAM_NAME if isinstance(r.DAM_NAME, str) and r.DAM_NAME else r.RES_NAME
            ax.annotate(f'{name} ({r.CAP_MCM / 1000:.1f} km3)', (r.LONG_DAM, r.LAT_DAM),
                        xycoords=ccrs.PlateCarree()._as_mpl_transform(ax), fontsize=7, xytext=(4, 4),
                        textcoords='offset points')
        ax.legend(loc='lower left', fontsize=8)
    fig.tight_layout(); fig.savefig(f'{figd}/gdw_offstream_dor_missing_map.png'); plt.close(fig)


def fig_years(isi, figd, plt):
    m = isi[(isi.method != 'unmatched')]
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    k = m[m.gdw_year_gdw.notna() & (m.FLAG_ART != 1) & (m.YEAR > 0)]
    axs[0].scatter(k.YEAR, k.gdw_year_gdw, s=6, alpha=0.5)
    axs[0].plot([1600, 2025], [1600, 2025], color='0.4', lw=0.6)
    axs[0].set_xlim(1800, 2025); axs[0].set_ylim(1800, 2025)
    axs[0].set_xlabel('ISIMIP4b YEAR'); axs[0].set_ylabel('GDW YEAR_DAM')
    axs[0].set_title(f'both years known: {len(k)} dams, same year {(k.YEAR == k.gdw_year_gdw).sum()}', loc='left', fontsize=9)
    cat = year_category(m)
    t = cat.value_counts()
    axs[1].barh(t.index[::-1], t.values[::-1], color='#6baed6')
    axs[1].set_xlabel('number of matched dams'); axs[1].set_title('year status of matched dams', loc='left', fontsize=9)
    axs[1].tick_params(axis='y', labelsize=8)
    fig.tight_layout(); fig.savefig(f'{figd}/gdw_isimip_year_scatter.png'); plt.close(fig)


def fig_cells(cells, figd, plt):
    import cartopy.crs as ccrs
    from matplotlib import colors as mcolors
    n = cells.groupby(['row', 'col']).agg(n=('GDW_ID', 'size'), lat=('cell_lat', 'first'), lon=('cell_lon', 'first'),
                                         cap=('CAP_MCM', 'sum')).reset_index()
    multi = n[n.n > 1].sort_values('n')
    fig = plt.figure(figsize=(14, 7))
    ax = rd._map_axes(fig, (1, 1, 1), f'proposed A (all GDW minus quality 5, DOR missing, Offstream): {len(cells)} records '
                                      f'in {len(n)} cells; {len(multi)} cells hold more than one dam '
                                      f'({multi.n.sum()} records)')
    cmap = mcolors.ListedColormap(['#fdae61', '#f46d43', '#d73027', '#a50026'])
    norm = mcolors.BoundaryNorm([1.5, 2.5, 3.5, 5.5, 100], cmap.N)
    sc = ax.scatter(multi.lon, multi.lat, s=rd._size(multi.cap), c=multi.n, cmap=cmap, norm=norm, alpha=0.85,
                    linewidth=0.2, edgecolor='k', transform=ccrs.PlateCarree(), zorder=3)
    cb = fig.colorbar(sc, ax=ax, shrink=0.6, ticks=[2, 3, 4.5, 50]); cb.ax.set_yticklabels(['2', '3', '4-5', '6+'])
    cb.set_label('dams in the 5\' cell')
    fig.tight_layout(); fig.savefig(f'{figd}/gdw_cell_multiplicity_map.png'); plt.close(fig)


def year_category(m):
    g, y, art = m.gdw_year_gdw, m.YEAR, m.FLAG_ART == 1
    return pd.Series(np.select(
        [g.notna() & ~art & (y == g), g.notna() & ~art & ((y - g).abs() <= 2), g.notna() & ~art,
         g.isna() & ~art & (y > 0), g.isna() & art, g.notna() & art],
        ['same year', 'differ by 1-2 years', 'differ by more than 2 years', 'GDW year missing, ISIMIP real year',
         'GDW year missing, ISIMIP set to 1850', 'GDW year known, ISIMIP set to 1850'],
        'other (ISIMIP year missing or 0)'), index=m.index)


# ---------------------------------------------------------------------------------------------- run
def run():
    out = rd.products(); figd = f'{out}/figures'; tabd = f'{out}/tables'
    os.makedirs(figd, exist_ok=True); os.makedirs(tabd, exist_ok=True)
    plt = rd._plt()

    corr = prepare(pd.read_csv(GDW_CORRECTED, low_memory=False)).assign(layer='corrected')
    layers = {k: read_layer(p) for k, p in GDW_DBF.items()}
    in_corr = set(corr.GDW_ID.dropna().astype(int))
    res_ids, bar_ids = set(layers['reservoirs'].GDW_ID.dropna().astype(int)), set(layers['barriers'].GDW_ID.dropna().astype(int))
    lost = layers['reservoirs'][~layers['reservoirs'].GDW_ID.isin(in_corr)].assign(layer='reservoirs (not in corrected)')
    extra = layers['barriers'][~layers['barriers'].GDW_ID.isin(in_corr | set(lost.GDW_ID.dropna().astype(int)))] \
        .assign(layer='barriers (no reservoir record)')
    pd.DataFrame([
        {'item': 'corrected table (reservoirs layer + 5\' snapping)', 'n': len(corr), 'capacity_km3': corr.CAP_MCM.sum() / 1000},
        {'item': 'reservoirs layer', 'n': len(layers['reservoirs']), 'capacity_km3': layers['reservoirs'].CAP_MCM.sum() / 1000},
        {'item': 'barriers layer', 'n': len(layers['barriers']), 'capacity_km3': layers['barriers'].CAP_MCM.sum() / 1000},
        {'item': 'reservoirs layer records not in the corrected table', 'n': len(lost), 'capacity_km3': lost.CAP_MCM.sum() / 1000},
        {'item': 'reservoir GDW_IDs not in the barriers layer', 'n': len(res_ids - bar_ids), 'capacity_km3': np.nan},
        {'item': 'barriers layer records without a reservoir record', 'n': len(extra), 'capacity_km3': extra.CAP_MCM.sum() / 1000},
        {'item': 'barriers layer records without capacity', 'n': int(layers['barriers'].CAP_MCM.isna().sum()), 'capacity_km3': np.nan},
        {'item': 'barriers layer records located from the point geometry (LAT/LONG_DAM = 0 in the attribute table)',
         'n': int(layers['barriers'].latlon_from_geometry.sum()), 'capacity_km3': np.nan},
    ]).round(1).to_csv(f'{tabd}/gdw_layers.csv', index=False)
    lost[['GDW_ID', 'GRAND_ID', 'DAM_NAME', 'RES_NAME', 'COUNTRY', 'CAP_MCM', 'LAT_DAM', 'LONG_DAM', 'INSTREAM', 'QUALITY']] \
        .to_csv(f'{tabd}/gdw_reservoirs_not_in_corrected.csv', index=False)
    other = pd.concat([lost, extra])
    other.index = [f'o{i}' for i in range(len(other))]
    print(f'corrected {len(corr)}, reservoirs {len(layers["reservoirs"])}, barriers {len(layers["barriers"])}, '
          f'lost {len(lost)}, barriers only {len(extra)}')

    isi = rd.read_xlsx(f'{rd.workdir()}/{rd.ISIMIP_HIST}').reset_index(drop=True)
    for c in ('CATCH_SKM_GranD',):
        if c in isi:
            isi[c] = pd.to_numeric(isi[c], errors='coerce')
    src = isi.SOURCE.astype(str).str.strip()
    isi['is_grand'] = src.isin(['NA', 'nan', 'None', ''])
    isi['method'] = pd.Series([None] * len(isi), dtype=object)
    for c in ['gdw_index', 'gdw_has_model_latlon'] + [f'gdw_{c}' for c in GDW_KEEP]:
        isi[c] = pd.Series([None] * len(isi), dtype=object)
    for c in ('distance_km', 'capacity_ratio_gdw_to_isimip'):
        isi[c] = np.nan
    print(f'ISIMIP {len(isi)} dams; GRanD-sourced {isi.is_grand.sum()}; non-numeric ID {isi.ID.isna().sum()}')

    used_corr = match_pool(isi, corr, '')
    match_pool(isi, other, 'other_layer_')
    isi['method'] = isi.method.fillna('unmatched')
    isi['year_category'] = year_category(isi).where(isi.method != 'unmatched')
    r = isi.capacity_ratio_gdw_to_isimip
    isi['suspect_reason'] = np.where(~isi.method.str.contains('suspect'), '',
                                     np.where(isi.distance_km > TIERS_KM[-1], 'distance > 10 km', '') + ' ' +
                                     np.where(r.isna(), 'GDW capacity missing',
                                              np.where((r < RATIO[0]) | (r > RATIO[1]), 'capacity ratio outside [0.5, 2]', '')))
    isi['suspect_reason'] = isi.suspect_reason.str.strip()
    isi['gdw_CAP_MCM'] = pd.to_numeric(isi.gdw_CAP_MCM, errors='coerce')

    cols = ['ID', 'DAM_NAME', 'RIVER', 'COUNTRY', 'SOURCE', 'LAT_ORIG', 'LON_ORIG', 'CAP_MCM', 'YEAR', 'FLAG_ART',
            'method', 'suspect_reason', 'distance_km', 'capacity_ratio_gdw_to_isimip', 'year_category', 'gdw_has_model_latlon'] + \
           [f'gdw_{c}' for c in GDW_KEEP]
    isi[cols].to_csv(f'{tabd}/gdw_isimip_match.csv', index=False)
    summ = isi.groupby('method').agg(n=('CAP_MCM', 'size'), capacity_km3=('CAP_MCM', lambda x: x.sum() / 1000),
                                     gdw_capacity_km3=('gdw_CAP_MCM', lambda x: x.sum() / 1000)) \
        .reindex(METHOD_ORDER).dropna(how='all').fillna(0)
    summ.loc['total'] = [len(isi), isi.CAP_MCM.sum() / 1000, isi.gdw_CAP_MCM.sum() / 1000]
    isi[isi.method.str.contains('suspect')].groupby(['method', 'suspect_reason']).agg(
        n=('CAP_MCM', 'size'), capacity_km3=('CAP_MCM', lambda x: x.sum() / 1000),
        gdw_capacity_km3=('gdw_CAP_MCM', lambda x: x.sum() / 1000)).round(1) \
        .to_csv(f'{tabd}/gdw_isimip_suspect_reasons.csv')
    summ.round(1).to_csv(f'{tabd}/gdw_isimip_match_summary.csv')
    isi[isi.method == 'unmatched'].nlargest(50, 'CAP_MCM')[['ID', 'DAM_NAME', 'RIVER', 'COUNTRY', 'SOURCE', 'CAP_MCM', 'YEAR',
                                                            'FLAG_ART', 'LAT_ORIG', 'LON_ORIG']] \
        .to_csv(f'{tabd}/gdw_isimip_unmatched_largest.csv', index=False)
    name_hints(isi, pd.concat([corr, other])).to_csv(f'{tabd}/gdw_isimip_name_hints.csv', index=False)
    print(summ.round(1).to_string())

    # rules on the corrected table: matched to ISIMIP vs not; other-layer matches separately
    matched_corr = corr.loc[sorted(used_corr)]
    rest = corr.drop(index=list(used_corr))
    other_used = isi.gdw_index[isi.method.str.startswith('other_layer')]
    groups = {'corrected table, matched to ISIMIP4b': matched_corr, 'corrected table, not in ISIMIP4b': rest,
              'other GDW records matched to ISIMIP4b': other.loc[list(other_used)]}
    rules = rule_table(groups)
    rules.to_csv(f'{tabd}/gdw_rule_effects.csv', index=False)
    keep = ['GDW_ID', 'GRAND_ID', 'DAM_NAME', 'RES_NAME', 'RIVER', 'COUNTRY', 'CAP_MCM', 'DOR_PC', 'QUALITY', 'INSTREAM',
            'LAKE_CTRL', 'YEAR_DAM', 'LAT_DAM', 'LONG_DAM']
    for name, m in (('offstream', corr.offstream), ('dor_missing', corr.dor_missing)):
        t = corr[m].assign(in_isimip4b=corr.index[m].isin(used_corr))
        t.nlargest(40, 'CAP_MCM')[keep + ['in_isimip4b']].to_csv(f'{tabd}/gdw_{name}_largest.csv', index=False)
    yc = isi[isi.method != 'unmatched'].groupby('year_category').agg(
        n=('CAP_MCM', 'size'), capacity_km3=('CAP_MCM', lambda x: x.sum() / 1000)).sort_values('n', ascending=False)
    yc.round(1).to_csv(f'{tabd}/gdw_isimip_year_comparison.csv')

    # 5' cells of proposed A
    with nc.Dataset(f'{rd.workdir()}/{rd.DAM_FILE}') as ds:
        lat = ds['lat'][:].astype(float); lon = ds['lon'][:].astype(float)
        active = np.ma.filled(ds['id_map'][:], -1) >= 0
    flags = rule_flags(corr)
    sel = corr[~flags['proposed A (quality 5, DOR missing, Offstream)']].copy()
    sel['in_isimip4b'] = sel.index.isin(used_corr)
    cells = cell_counts(sel, lat, lon, active)
    cells['cell_lat'] = lat[cells.row]; cells['cell_lon'] = lon[cells.col]
    per = cells.groupby(['row', 'col']).agg(n=('GDW_ID', 'size'), n_isimip=('in_isimip4b', 'sum'),
                                            active=('cell_active', 'first'))
    crow = []
    for k, grp in per.groupby(np.minimum(per.n, 6)):
        crow.append({'dams_in_cell': f'{k}' if k < 6 else '6 or more', 'cells': len(grp), 'records': int(grp.n.sum()),
                     'cells_with_2+_isimip_dams': int((grp.n_isimip >= 2).sum()), 'inactive_cells': int((~grp.active).sum())})
    crow.append({'dams_in_cell': 'records placed by dam location (no MODEL_LAT/LONG_DD)',
                 'cells': np.nan, 'records': int((~cells.cell_from_model).sum())})
    pd.DataFrame(crow).to_csv(f'{tabd}/gdw_cell_multiplicity.csv', index=False)
    multi = per[per.n > 1].reset_index()[['row', 'col']]
    cells.merge(multi, on=['row', 'col']).sort_values(['row', 'col', 'CAP_MCM'], ascending=[True, True, False]) \
        [['row', 'col', 'cell_lat', 'cell_lon', 'GDW_ID', 'GRAND_ID', 'DAM_NAME', 'RES_NAME', 'COUNTRY', 'CAP_MCM',
          'in_isimip4b', 'cell_active']] \
        .to_csv(f'{tabd}/gdw_cell_multiple_dams.csv', index=False)
    print(pd.DataFrame(crow).to_string())

    fig_match_map(isi, figd, plt)
    fig_distance(isi, figd, plt)
    fig_rules(rules, figd, plt)
    fig_offstream_dor(corr, set(used_corr), figd, plt)
    fig_years(isi, figd, plt)
    fig_cells(cells, figd, plt)
    print('done')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--submit', action='store_true')
    a = ap.parse_args()
    rd.submit('compare_gdw_isimip.py', 'gdw') if a.submit else run()


if __name__ == '__main__':
    main()
