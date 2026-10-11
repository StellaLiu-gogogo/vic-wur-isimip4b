#!/usr/bin/env python3
"""Dam component of a parameter set (decision D19): one dam list, one VIC dam file per DHF scenario.

Builds parameters/<status>/<set>/dams/ from
  * ISIMIP4b reservoirs-dams histsoc (7 331 dams; identical to 2021soc) and the SSP future hydropower dams of
    ssp1vlsoc-noadapt and ssp3hsoc-noadapt (river-power dams with a lake volume only);
  * GDW v1.0 barriers layer (raw/external/global-dam-watch/1.0/) for dam locations, catchment areas and purposes;
  * the domain and routing files of the parameter set;
  * the mean discharge of a natural run (all water-management plugins off) for the service maps;
  * the hand decisions of dam_decisions.yaml (manual locations, combined records, reviewed capacities and
    locations; every entry with its reason).

Method (see the README of this directory for the rules and their sources)
  dam list     every ISIMIP4b histsoc dam, located with GDW (dam_sources.match_isimip_gdw), plus every SSP site;
               records combined by the decisions file are one dam
  point        GDW point (barriers layer), else ISIMIP LAT_ORIG/LON_ORIG; SSP: latitude/longitude
  catchment    GDW CATCH_SKM, else ISIMIP CATCH_SKM_GranD, else ISIMIP CATCH_SKM_DDM30 (flagged); SSP: the DDM30
               routing area
  cell, type   dam_grid.snap on the routing of the set; SSP future dams are global
  one per cell dam_grid.place, largest first, historical before future
  capacity     ISIMIP CAP_MCM (hm3) unless the decisions file says otherwise; SSP: lake volume / 1e6
  purpose      a global dam whose ISIMIP PURPOSE and GDW uses name a purpose without irrigation or water supply
               gets Nservice = 0 and an empty service map; every SSP future dam too; others are traced
  service      dam_grid.trace_service on the mean discharge of the natural run over --discharge-years
  year         per DHF scenario (D19): histsoc = ISIMIP YEAR (SSP future 9999); 1850soc = 0 for YEAR <= 1850, else
               9999; 2021soc = 0 for every historical dam, 9999 for SSP future dams. 9999 = never (user, 2026-10-11)

Outputs in <out>: vic_global_5min_dam_parameters_isimip4b_<scenario>.nc for histsoc, 1850soc, 2021soc (same
dam list and order, only `year` differs), dam_list_isimip4b.csv (one row per dam_class), dam_sources_isimip4b.csv
(one row per source record and what became of it), review_pairs.csv (pairs for the hand review),
mean_discharge_natural.nc (the field used for the service maps), provenance.yaml; build report
<qc>/reports/build_report.json. <out> is parameters/<status>/<set>/dams/ (whose adopted files stay), <qc> is
qc/parameters/<status>/<set>/dams/. From a repository that is not clean, or with --scratch, everything goes to
scratch/dam-parameters/dams/ (qc under its qc/). --review stops before the service maps and writes the tables to
scratch/dam-parameters/review/ (no discharge needed).

Usage: build_dams.py [--parameter-set ID] [--parameter-status candidates] [--review | --discharge-run RUN_DIR
       [--discharge-years 1992 2021]] [--scratch] [--expect-commit SHA]
"""
import argparse, glob, json, os, sys, time

import numpy as np
import netCDF4 as nc
import pandas as pd
import yaml

from common import gitstate, hashing, provenance, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import dam_grid as dg       # noqa: E402
import dam_sources as ds    # noqa: E402

CREATED_BY = 'workflow/03_parameters/dams/build_dams.py'
METHOD_VERSION = '1.0'
DECISIONS = os.path.join(HERE, 'dam_decisions.yaml')
SCRATCH = 'scratch/dam-parameters'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
ROUTING = 'routing/vic_global_5min_routing.nc'
GDW_DIR = 'raw/external/global-dam-watch/1.0'
GDW_MANIFEST = 'manifests/inputs/global-dam-watch.yaml'
ISIMIP_MD5 = 'manifests/inputs/isimip4b-dkrz-2026-09-21/MD5SUMS'
RES = 'InputData/socioeconomic/reservoirs_dams'
HISTSOC = f'{RES}/histsoc/reservoirs-dams_1850_2021.xlsx'
SSP = {'ssp1vlsoc-noadapt': f'{RES}/ssp1vlsoc-noadapt/reservoirs-dams_watergap2-2e_gswp3-w5e5_ssp1_2022_2100.csv',
       'ssp3hsoc-noadapt': f'{RES}/ssp3hsoc-noadapt/reservoirs-dams_watergap2-2e_gswp3-w5e5_ssp3_2022_2100.csv'}
N_HISTSOC = 7331
SCENARIOS = ('histsoc', '1850soc', '2021soc')
YEAR_NEVER = 9999
OUT_NC = 'vic_global_5min_dam_parameters_isimip4b_{scenario}.nc'
DAM_LIST = 'dam_list_isimip4b.csv'
DAM_SOURCES = 'dam_sources_isimip4b.csv'
REVIEW = 'review_pairs.csv'
DISCHARGE = 'mean_discharge_natural.nc'
NATURAL_OFF = ('irrigation', 'dams', 'water_use')
SCENARIO_USE = {'histsoc': 'segments with soc scenario histsoc',
                '1850soc': 'segments with soc scenario 1850soc',
                '2021soc': 'segments with soc scenario 2021soc or 2021soc-from-histsoc, and SSP units without '
                           'extrasoc dams (D19)'}


def git_state():
    return gitstate.state(REPO)


# ------------------------------------------------------------------------------------------------------- inputs
def check_md5(W, items):
    """items: [(relative path, expected md5, where the md5 is recorded)]; stops on a mismatch."""
    for rel, md5, src in items:
        got = hashing.md5(f'{W}/{rel}')
        if got != md5:
            raise SystemExit(f'{rel}: md5 {got} differs from {md5} recorded in {src}')


def input_md5s(W, pset_rel):
    items = []
    gm = yaml.safe_load(open(f'{REPO}/{GDW_MANIFEST}'))
    for f in gm['files']:
        if f['path'].startswith('GDW_v1_0_shp/GDW_barriers_v1_0.'):
            items.append((f'{GDW_DIR}/{f["path"]}', f['md5'], GDW_MANIFEST))
    md5 = {}
    for line in open(f'{REPO}/{ISIMIP_MD5}'):
        h, p = line.split(maxsplit=1); md5[p.strip()] = h
    for rel in [HISTSOC] + list(SSP.values()):
        items.append((f'raw/ISIMIP4b/{rel}', md5[rel], ISIMIP_MD5))
    pm = yaml.safe_load(open(f'{REPO}/manifests/parameters/{os.path.basename(pset_rel)}.yaml'))
    for comp in pm['components'].values():
        for f in comp.get('files', []):
            if f['path'] in (DOMAIN, ROUTING):
                items.append((f'{pset_rel}/{f["path"]}', f['md5'], f'manifests/parameters/{os.path.basename(pset_rel)}.yaml'))
    if len([i for i in items if i[0].endswith((DOMAIN, ROUTING))]) != 2:
        raise SystemExit('domain or routing file not found in the parameter manifest')
    return items


def load_decisions(path=DECISIONS):
    d = yaml.safe_load(open(path)) or {}
    for k in ('manual_locations', 'combined', 'reviews'):
        d[k] = d.get(k) or []
        for e in d[k]:
            if not str(e.get('reason', '')).strip():
                raise SystemExit(f'{path}: every entry of {k} needs a reason ({e})')
    return d


def natural_run(W, run_rel, years, require_natural):
    """Monthly discharge files of a completed run for `years` and its identity."""
    run = f'{W}/{run_rel}'
    man = json.load(open(f'{run}/run_manifest.json'))
    if man.get('status') != 'completed':
        raise SystemExit(f'{run_rel}: run status {man.get("status")}, not completed')
    res = yaml.safe_load(open(f'{run}/config/resolved.yaml')) if os.path.exists(f'{run}/config/resolved.yaml') else {}
    plugins = (res.get('campaign') or {}).get('plugins') or {}
    on = [p for p in NATURAL_OFF if (plugins.get(p) or {}).get('enabled')]
    if require_natural and on:
        raise SystemExit(f'{run_rel}: not a natural run ({", ".join(on)} switched on)')
    files = []
    for y in range(years[0], years[1] + 1):
        cands = [f'{run}/output/monthly.{y}-01.nc'] + sorted(glob.glob(f'{run}/chunks/*/output/monthly.{y}-01.nc'))
        hit = [p for p in cands if os.path.isfile(p)]
        if len(hit) != 1:
            raise SystemExit(f'{run_rel}: {len(hit)} monthly files for {y}')
        files.append(hit[0])
    return files, {'run_dir': run_rel, 'run_id': man.get('run_id'), 'campaign_id': man.get('campaign_id'),
                   'run_manifest_sha256': hashing.sha256(f'{run}/run_manifest.json'),
                   'plugins_on': [p for p in plugins if (plugins.get(p) or {}).get('enabled')]}


def mean_discharge(files, shape):
    """Mean of all monthly OUT_DISCHARGE values (m3 s-1; each month weighs the same, as in vic_parameter); NaN where
    a cell has no valid value."""
    tot = np.zeros(shape); cnt = np.zeros(shape)
    for p in files:
        with nc.Dataset(p) as d:
            v = d['OUT_DISCHARGE']; v.set_auto_mask(False)
            fill = float(getattr(v, '_FillValue', np.nan))
            for t in range(v.shape[0]):
                x = np.asarray(v[t], float)
                ok = np.isfinite(x) & (x < 0.5 * fill if np.isfinite(fill) and fill > 1e30 else True)
                tot += np.where(ok, x, 0); cnt += ok
    return np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan), int(cnt.max())


# --------------------------------------------------------------------------------------------------- dam records
def historical_dams(isi, gdw, match, dec):
    """List of dam dicts (one per historical dam after combining) and per-record source rows."""
    by_key = {k: i for i, k in zip(isi.index, isi.key)}
    reviews = {e['isimip']: e for e in dec['reviews']}
    absorbed, combined = {}, {}
    for e in dec['combined']:
        for k in [e['keep']] + list(e['absorb']):
            if k not in by_key:
                raise SystemExit(f'decisions file: unknown ISIMIP key {k!r} in combined')
        combined[e['keep']] = e
        for k in e['absorb']:
            absorbed[k] = e['keep']
    dams, src = [], []
    for i in isi.index:
        r = isi.loc[i]; m = match.loc[i]
        g = gdw.loc[m.gdw_row] if m.gdw_row >= 0 else None
        row = {'source': 'histsoc', 'source_row': int(r.row), 'key': r.key, 'name': r.DAM_NAME, 'country': r.COUNTRY,
               'isimip_cap_mcm': r.CAP_MCM, 'isimip_year': r.YEAR, 'isimip_lat': r.LAT_ORIG, 'isimip_lon': r.LON_ORIG,
               'match_method': m.method or 'unmatched', 'gdw_id': int(g.GDW_ID) if g is not None else None,
               'gdw_cap_mcm': g.CAP_MCM if g is not None else np.nan, 'distance_km': m.distance_km,
               'capacity_ratio_gdw_to_isimip': m.capacity_ratio, 'review': m.review}
        src.append(row)
        if r.key in absorbed:
            row['outcome'] = f'combined into {absorbed[r.key]}'; continue
        rv = reviews.get(r.key)
        use_isimip = g is None or (rv is not None and rv.get('location') == 'isimip')
        lat, lon = (r.LAT_ORIG, r.LON_ORIG) if use_isimip else (g.lat, g.lon)
        loc_src = 'isimip' if use_isimip else f'gdw:{int(g.GDW_ID)}'
        for val, how in ((None if use_isimip else g.CATCH_SKM, 'gdw'), (r.CATCH_SKM_GranD, 'isimip_grand'),
                         (r.CATCH_SKM_DDM30, 'isimip_ddm30')):
            if val is not None and pd.notna(val) and val > 0:
                catch, catch_src = float(val), how; break
        else:
            raise SystemExit(f'{r.key} {r.DAM_NAME}: no catchment area in GDW or ISIMIP')
        cap, cap_src, year = float(r.CAP_MCM), 'isimip', int(r.YEAR)
        members = [r.key]
        rules = [ds.purpose_rule(r.PURPOSE, g)]
        if r.key in combined:
            e = combined[r.key]
            cap, year, cap_src = float(e['capacity_mcm']), int(e['year']), 'decisions:combined'
            for k in e['absorb']:
                j = by_key[k]; mj = match.loc[j]
                rules.append(ds.purpose_rule(isi.at[j, 'PURPOSE'], gdw.loc[mj.gdw_row] if mj.gdw_row >= 0 else None))
                members.append(k)
        if rv is not None and 'capacity_mcm' in rv:
            cap, cap_src = float(rv['capacity_mcm']), 'decisions:review'
        rule = ds.combine_rules(rules)
        dams.append({'name': r.DAM_NAME, 'key': r.key, 'members': members, 'country': r.COUNTRY, 'future': False,
                     'lat': float(lat), 'lon': float(lon), 'location_source': loc_src, 'catchment_km2': catch,
                     'catchment_source': catch_src, 'capacity_mcm': cap, 'capacity_source': cap_src,
                     'year_isimip': year, 'purpose_isimip': r.PURPOSE,
                     'purpose_gdw': None if g is None else (g.MAIN_USE or '') + ' | ' +
                     ','.join(c for c in ds.GDW_USE if ds._filled(g.get(c))),
                     'purpose_rule': rule})
        row['outcome'] = 'dam'
    return dams, src


def future_dams(sites, scenarios):
    out = []
    for _, s in sites.iterrows():
        out.append({'name': s['name'], 'key': s['name'], 'members': [s['name']], 'country': '', 'future': True,
                    'lat': float(s.lat), 'lon': float(s.lon), 'location_source': 'ssp',
                    'catchment_km2': float(s.catchment_km2), 'catchment_source': 'ssp_ddm30',
                    'capacity_mcm': float(s.capacity_mcm), 'capacity_source': 'ssp_lake_volume',
                    'year_isimip': None, 'purpose_isimip': '', 'purpose_gdw': None, 'purpose_rule': 'ssp_future',
                    **{f'year_{sc}': (None if pd.isna(s[f'year_{sc}']) else int(s[f'year_{sc}'])) for sc in scenarios}})
    return out


def scenario_years(dams):
    hist = np.array([YEAR_NEVER if d['future'] else d['year_isimip'] for d in dams], np.int32)
    fut = np.array([d['future'] for d in dams])
    return {'histsoc': hist,
            '1850soc': np.where(~fut & (hist <= 1850), 0, YEAR_NEVER).astype(np.int32),
            '2021soc': np.where(fut, YEAR_NEVER, 0).astype(np.int32)}


def review_rows(isi, gdw, match):
    m = match[match.review != '']
    rows = []
    for i in m.index:
        r, g = isi.loc[i], gdw.loc[m.at[i, 'gdw_row']]
        rows.append({'isimip': r.key, 'name': r.DAM_NAME, 'country': r.COUNTRY, 'reason': m.at[i, 'review'],
                     'isimip_cap_mcm': r.CAP_MCM, 'gdw_cap_mcm': g.CAP_MCM, 'ratio_gdw_to_isimip': m.at[i, 'capacity_ratio'],
                     'isimip_year': r.YEAR, 'gdw_year': g.YEAR_DAM, 'isimip_lat': r.LAT_ORIG, 'isimip_lon': r.LON_ORIG,
                     'gdw_id': int(g.GDW_ID), 'gdw_name': g.DAM_NAME, 'gdw_lat': g.lat, 'gdw_lon': g.lon,
                     'distance_km': m.at[i, 'distance_km'], 'isimip_catch_km2': r.CATCH_SKM_GranD,
                     'gdw_catch_km2': g.CATCH_SKM})
    return pd.DataFrame(rows)


def check_reviews(review, dec):
    """Every pair flagged for review must have a decision with capacity_mcm and location ('gdw' or 'isimip')."""
    have = {e['isimip']: e for e in dec['reviews']}
    missing = [k for k in review.isimip if k not in have or 'capacity_mcm' not in have[k] or
               have[k].get('location') not in ('gdw', 'isimip')]
    extra = [k for k in have if k not in set(review.isimip)]
    return missing, extra


# --------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--parameter-set', default='vic-global-5arcmin-version-a')
    ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
    ap.add_argument('--review', action='store_true', help='stop before the service maps; tables to scratch/.../review/')
    ap.add_argument('--discharge-run', help='run directory (under the workdir) of the natural run')
    ap.add_argument('--discharge-years', type=int, nargs=2, default=[1992, 2021])
    ap.add_argument('--scratch', action='store_true')
    ap.add_argument('--expect-commit', default=None)
    a = ap.parse_args(); t0 = time.time(); W = workdir.root()
    commit, dirty = git_state()
    if a.expect_commit and (dirty or commit != a.expect_commit):
        raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the repository '
                         f'is now at {commit} and {"not clean" if dirty else "clean"}; submit the job again')
    to_scratch = a.scratch or dirty or a.review
    pset_rel = f'parameters/{a.parameter_status}/{a.parameter_set}'; pset = f'{W}/{pset_rel}'
    rel_obj = f'{pset_rel}/dams'
    out = f'{W}/{SCRATCH}/review' if a.review else f'{W}/{SCRATCH}/dams' if to_scratch else f'{W}/{rel_obj}'
    qc = f'{out}/qc' if to_scratch else f'{W}/qc/{rel_obj}'
    names = [OUT_NC.format(scenario=s) for s in SCENARIOS] + [DAM_LIST, DAM_SOURCES, REVIEW, DISCHARGE, 'provenance.yaml']
    clash = [n for n in names if os.path.exists(f'{out}/{n}')]
    if clash and not to_scratch:
        raise SystemExit(f'{out}: {clash} exist; a component file is replaced only with the user\'s authorization')
    if not a.review and not a.discharge_run:
        raise SystemExit('--discharge-run is required unless --review')
    if to_scratch:
        print(f'{"review" if a.review else "--scratch" if a.scratch else "repository is not clean"}: writing to {out}',
              file=sys.stderr)
    md5_items = input_md5s(W, pset_rel)
    check_md5(W, md5_items)
    dec = load_decisions()

    gdw = ds.read_gdw_barriers(f'{W}/{GDW_DIR}/GDW_v1_0_shp')
    isi = ds.read_isimip_histsoc(f'{W}/raw/ISIMIP4b/{HISTSOC}')
    if len(isi) != N_HISTSOC:
        raise SystemExit(f'ISIMIP histsoc: {len(isi)} dams, expected {N_HISTSOC}')
    match = ds.match_isimip_gdw(isi, gdw, dec['manual_locations'], skip=[k for e in dec['combined'] for k in e['absorb']])
    review = review_rows(isi, gdw, match)
    missing, extra = check_reviews(review, dec)
    unmatched = isi.key[match.method == ''].tolist()
    if not to_scratch and (missing or extra or unmatched):
        raise SystemExit(f'decisions incomplete: reviews missing {missing}, reviews not flagged {extra}, '
                         f'unmatched dams without a manual location {unmatched}')
    ssp_tab = {s: ds.read_ssp(f'{W}/raw/ISIMIP4b/{p}') for s, p in SSP.items()}
    sites, ssp_rows = ds.ssp_sites(ssp_tab)
    print(f'GDW barriers {len(gdw)}; ISIMIP histsoc {len(isi)}: ' +
          ', '.join(f'{k} {v}' for k, v in match.method.replace('', 'unmatched').value_counts().items()) +
          f'; review pairs {len(review)}; SSP sites {len(sites)}', flush=True)

    grid = dg.load_grid(f'{pset}/{DOMAIN}', f'{pset}/{ROUTING}')
    print(f'grid {grid.ny}x{grid.nx}, {int(grid.mask.sum())} active cells, {time.time() - t0:.0f} s', flush=True)
    hist, src_rows = historical_dams(isi, gdw, match, dec)
    hist.sort(key=lambda d: (-d['capacity_mcm'], d['key']))
    fut = future_dams(sites, list(SSP))
    dams = hist + fut
    for d in dams:
        d.update(dg.snap(grid, d['lat'], d['lon'], d['catchment_km2'], force_global=d['future']))
        d['snap_row'], d['snap_col'] = d['row'], d['col']
    kept = dg.place(grid, dams)
    for d in dams:
        if d.get('merged'):
            d['purpose_rule'] = ds.combine_rules([d['purpose_rule']] + [dams[k]['purpose_rule'] for k in d['merged']])
        d['keeps_service'] = ds.keeps_service(d['type'], d['purpose_rule'])
    final = [dams[k] for k in kept]
    hist_final = sorted([d for d in final if not d['future']], key=lambda d: (-d['capacity_mcm'], d['key']))
    fut_final = sorted([d for d in final if d['future']], key=lambda d: (-d['capacity_mcm'], d['key']))
    final = hist_final + fut_final
    index = {id(d): i for i, d in enumerate(final)}
    years = scenario_years(final)

    os.makedirs(out, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)
    networks, q, qinfo = None, None, None
    if not a.review:
        files, qinfo = natural_run(W, a.discharge_run, a.discharge_years, require_natural=not to_scratch)
        q, nmonths = mean_discharge(files, grid.mask.shape)
        qinfo.update({'years': a.discharge_years, 'months': nmonths,
                      'files': [{'path': os.path.relpath(p, W), 'sha256': hashing.sha256(p)} for p in files]})
        networks = [dg.trace_service(grid, d['row'], d['col'], q) if d['keeps_service']
                    else (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0)) for d in final]
        print(f'service maps traced, {time.time() - t0:.0f} s', flush=True)

    # tables
    lst = []
    for i, d in enumerate(final):
        lst.append({'dam_class': i, 'name': d['name'], 'kind': 'ssp_future' if d['future'] else 'histsoc',
                    'members': ';'.join(d['members'] + [m for k in d.get('merged', []) for m in dams[k]['members']]),
                    'country': d['country'], 'point_lat': d['lat'], 'point_lon': d['lon'],
                    'location_source': d['location_source'], 'row': d['row'], 'col': d['col'],
                    'cell_lat': grid.lat[d['row']], 'cell_lon': grid.lon[d['col']],
                    'cell_id': int(grid.cell_id[d['row'], d['col']]), 'snap_method': d['method'],
                    'placement': d['placement'], 'catchment_km2': d['catchment_km2'],
                    'catchment_source': d['catchment_source'],
                    'upstream_area_km2': grid.upstream_m2[d['row'], d['col']] / 1e6,
                    'cell_area_km2': grid.area_m2[d['row'], d['col']] / 1e6, 'area_ratio': d['ratio'],
                    'type': d['type'], 'inflow_fraction': d['inflow_fraction'], 'capacity_mcm': d['capacity_mcm'],
                    'capacity_source': d['capacity_source'],
                    'year_isimip': d['year_isimip'],
                    **{f'year_{s}': int(years[s][i]) for s in SCENARIOS},
                    **{f'built_{s}': d.get(f'year_{s}') for s in SSP},
                    'purpose_isimip': d['purpose_isimip'], 'purpose_gdw': d['purpose_gdw'],
                    'purpose_rule': d['purpose_rule'], 'keeps_service': d['keeps_service'],
                    'nservice': None if networks is None else len(networks[i][0])})
    dam_list = pd.DataFrame(lst)
    key_dam = {}
    for d in dams:
        for m in d['members']:
            key_dam[m] = d
    for row in src_rows:
        d = key_dam.get(row['key'])
        if row.get('outcome') == 'dam' and d is not None:
            if d['placement'] == 'merged':
                host = dams[d['merged_into']]
                row['outcome'] = f'merged into {host["name"]}'; row['dam_class'] = index[id(host)]
            elif d['placement'] == 'not_placed':
                row['outcome'] = f'not placed: {d.get("reason")}'
            else:
                row['outcome'] = d['placement']; row['dam_class'] = index[id(d)]
        elif str(row.get('outcome', '')).startswith('combined into'):
            host = key_dam[row['outcome'].split()[-1]]
            if host['placement'] == 'merged':
                host = dams[host['merged_into']]
            row['dam_class'] = index.get(id(host))
    site_dam = {(d['lat'], d['lon']): d for d in dams if d['future']}
    for _, r in ssp_rows.iterrows():
        row = {'source': r.source, 'source_row': r.source_row, 'key': None, 'name': None,
               'isimip_lat': r.lat, 'isimip_lon': r.lon, 'outcome': r.outcome}
        if r.outcome == 'site':
            d = site_dam[r.site]; row['name'] = d['name']
            if d['placement'] in ('as_snapped', 'moved'):
                row['outcome'] = d['placement']; row['dam_class'] = index[id(d)]
            else:
                row['outcome'] = f'not placed: {d.get("reason")}'
        src_rows.append(row)
    sources = pd.DataFrame(src_rows)

    def write_csv(df, name):
        df.to_csv(f'{out}/{name}.part', index=False); os.replace(f'{out}/{name}.part', f'{out}/{name}')
    write_csv(dam_list, DAM_LIST); write_csv(sources, DAM_SOURCES); write_csv(review, REVIEW)

    created_at = provenance.utcnow()
    report = {
        'method_version': METHOD_VERSION, 'created_at': created_at, 'code_commit': commit, 'code_dirty': dirty,
        'gdw_barriers': len(gdw), 'isimip_histsoc': len(isi),
        'match_methods': match.method.replace('', 'unmatched').value_counts().to_dict(),
        'review_pairs': len(review), 'reviews_missing': missing, 'reviews_not_flagged': extra, 'unmatched': unmatched,
        'ssp_records': {s: len(t) for s, t in ssp_tab.items()},
        'ssp_records_excluded_no_reservoir': int(ssp_rows.outcome.str.startswith('excluded').sum()),
        'ssp_sites': len(sites),
        'placement': pd.Series([d['placement'] for d in dams]).value_counts().to_dict(),
        'placement_future': pd.Series([d['placement'] for d in dams if d['future']]).value_counts().to_dict(),
        'dams': len(final), 'dams_historical': len(hist_final), 'dams_future': len(fut_final),
        'types': {'local': int(sum(d['type'] == 0 for d in final)), 'global': int(sum(d['type'] == 1 for d in final))},
        'purpose_rule': dam_list.purpose_rule.value_counts().to_dict(),
        'catchment_source': dam_list.catchment_source.value_counts().to_dict(),
        'capacity_km3': {'histsoc_input': float(isi.CAP_MCM.sum() / 1e3),
                         'historical_dams': float(sum(d['capacity_mcm'] for d in hist_final) / 1e3),
                         'future_dams': float(sum(d['capacity_mcm'] for d in fut_final) / 1e3)},
        'snap_methods': dam_list.snap_method.value_counts().to_dict(),
        'area_ratio_global_quantiles': {str(p): float(np.nanpercentile(dam_list.area_ratio[dam_list.type == 1], p))
                                        for p in (50, 90, 99)},
    }
    if networks is not None:
        ns = np.array([len(n[0]) for n in networks])
        report.update({'nservice_zero': int((ns == 0).sum()), 'nservice_max': int(ns.max()),
                       'service_links': int(ns.sum()), 'discharge': qinfo})
    report['runtime_s'] = round(time.time() - t0)
    json.dump(report, open(f'{qc}/reports/build_report.json', 'w'), indent=1, default=str)
    if a.review:
        print(json.dumps(report, indent=1, default=str)); return

    # mean discharge and the dam files
    f_q = f'{out}/{DISCHARGE}'
    with nc.Dataset(f_q + '.part', 'w') as o:
        o.createDimension('lat', grid.ny); o.createDimension('lon', grid.nx)
        o.createVariable('lat', 'f8', ('lat',))[:] = grid.lat
        o.createVariable('lon', 'f8', ('lon',))[:] = grid.lon
        v = o.createVariable('discharge', 'f4', ('lat', 'lon'), zlib=True, complevel=4, fill_value=np.float32(np.nan))
        v[:] = q.astype(np.float32); v.units = 'm3 s-1'
        v.long_name = f'mean of the monthly OUT_DISCHARGE {a.discharge_years[0]}-{a.discharge_years[1]} of the natural run'
        o.source_run = a.discharge_run; o.created_by = CREATED_BY; o.code_commit = commit
    os.replace(f_q + '.part', f_q)
    base_attrs = {'title': 'VIC-WUR dam parameters (DAMS_PARAMETERS), ISIMIP4b dams located with GDW v1.0 (D19)',
                  'created_by': CREATED_BY, 'code_commit': commit, 'code_dirty': str(dirty).lower(),
                  'created_at': created_at, 'method_version': METHOD_VERSION,
                  'parameter_set': f'{a.parameter_status}/{a.parameter_set}', 'dam_list': DAM_LIST,
                  'n_dams': len(final), 'n_historical': len(hist_final), 'n_future': len(fut_final),
                  'service_min_frac': dg.MIN_FRAC, 'service_max_cells': dg.MAX_SERVICE,
                  'service_discharge': f'{DISCHARGE} ({a.discharge_run}, {a.discharge_years[0]}-{a.discharge_years[1]})',
                  'year_never': YEAR_NEVER}
    paths = []
    for s in SCENARIOS:
        p = f'{out}/{OUT_NC.format(scenario=s)}'
        dg.write_dam_file(p + '.part', grid, final, years[s], networks,
                          {**base_attrs, 'dhf_scenario': s, 'used_for': SCENARIO_USE[s]})
        os.replace(p + '.part', p); paths.append(p)
        print(f'wrote {p}, {time.time() - t0:.0f} s', flush=True)

    files = [{'path': os.path.basename(p), 'size_bytes': os.path.getsize(p), 'sha256': hashing.sha256(p),
              'md5': hashing.md5(p)} for p in paths + [f'{out}/{n}' for n in (DAM_LIST, DAM_SOURCES, REVIEW, DISCHARGE)]]
    prov = {'object': rel_obj if not to_scratch else os.path.relpath(out, W), 'created_by': CREATED_BY,
            'code_commit': commit, 'code_dirty': dirty, 'created_at': created_at, 'method_version': METHOD_VERSION,
            'note': 'covers only the files listed here; the adopted files of this component are recorded in '
                    f'manifests/parameters/{a.parameter_set}.yaml',
            'inputs': {rel: {'md5': md5, 'recorded_in': where} for rel, md5, where in md5_items},
            'decisions': {'file': os.path.relpath(DECISIONS, REPO), 'sha256': hashing.sha256(DECISIONS)},
            'discharge_run': qinfo,
            'method': {'match_km': ds.MATCH_KM, 'review_km': ds.REVIEW_KM, 'capacity_ratio': list(ds.RATIO),
                       'max_area_ratio': dg.MAX_RATIO, 'service_min_frac': dg.MIN_FRAC,
                       'service_max_cells': dg.MAX_SERVICE, 'year_never': YEAR_NEVER},
            'scenarios': {s: OUT_NC.format(scenario=s) for s in SCENARIOS},
            'rebuild_command': f'python3 {CREATED_BY} --parameter-set {a.parameter_set} --parameter-status '
                               f'{a.parameter_status} --discharge-run {a.discharge_run} --discharge-years '
                               f'{a.discharge_years[0]} {a.discharge_years[1]}' + (' --scratch' if a.scratch else ''),
            'files': files, 'qc': {'status': 'not_checked', 'evidence': os.path.relpath(qc, W)}}
    provenance.write(f'{out}/provenance.yaml', prov)
    print(f'done in {time.time() - t0:.0f} s -> {out}')


if __name__ == '__main__':
    main()
