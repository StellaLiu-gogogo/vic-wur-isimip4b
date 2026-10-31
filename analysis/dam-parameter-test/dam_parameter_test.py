#!/usr/bin/env python3
"""Test of the D19 dam parameters and the matching FILE decomposition in VIC-WUR 39e21ff5 (task L5).

Question: do the ISIMIP4b dam files (D19) and the new FILE decomposition run as intended, i.e. do 8 and 16 ranks
give the same result, do the dams receive, store and release water plausibly, and how does the discharge at the
GRDC stations change against the smoke run with the old dam file?

Runs (campaign configs/campaigns/dam-test.yaml, 2015-2016, cold start in 2015, histsoc):
  ranks8   8 ranks x 16 threads (job 43522174)      ranks16  16 ranks x 8 threads (job 43522179)
  ranks8-threads8-shared   8 ranks x 8 threads on a shared node (job 43530364)
Reference: smoke run 2011-2020 (old dam file t3-extended-merged and old decomposition, cold start in 2011).
The runs are compared with each other by workflow/05_simulation/monitor/compare_runs.py (qc/<run>/reports/).

Steps (every computation on a compute node):
  dams          global dams active in 2016 (run ranks16): inflow, demand and release in 2016 at the dam cell,
                inflow against the natural mean discharge of the dam file, storage at the end of 2016 (end state)
                against capacity; local dams in total; the key dams month by month, with the storage of the matching
                old dam in the smoke run
  grdc          2016 at the GRDC stations of the run check: simulated monthly discharge of ranks16 and of the smoke
                run against the GRDC climatology 2005-2024 (ratio of means, seasonal correlation); the stations
                downstream of the key dams

Writes to workdir/analysis/dam-parameter-test/:
  tables/   dams_global_2016.csv, key_dams_monthly.csv, key_dams.csv, grdc_2016.csv,
            grdc_key_dams.csv, <step>_summary.json
  figures/  key_dams.png, grdc_ratio_2016.png, grdc_key_dams.png
  logs/<step>_<slurm-job-id>/   job records

Usage:
  dam_parameter_test.py dams | grdc [--submit] [--processes N]
"""
import argparse, datetime, json, os, subprocess, sys

import numpy as np
import pandas as pd
import yaml
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'monitor'))
import grdc   # noqa: E402

TASK = 'dam-parameter-test'
SEGMENT = 'ec-earth3-esm-1-1_historical_histsoc_default_historical'
MAIN_LABEL = 'ranks16-2015-2016'                        # the run whose dams and discharge are evaluated
MAIN = f'runs/dam-test/{SEGMENT}__{MAIN_LABEL}'
SMOKE = f'runs/smoke/{SEGMENT}__smoke2011-2020'
OLD_DAMS = 'parameters/candidates/vic-global-5arcmin-version-a/dams/vic_global_5min_dam_parameters_t3-extended-merged.nc'
YEARS = (2015, 2016)
YEAR = 2016
END_STATE = 'states/state.20170101_00000.nc'
GRDC_REF = list(range(2005, 2025))            # the reference years of the run check of the test runs
KEY_DAMS = ['Ust-Ilim', 'Bratsk', 'Brokopondo', 'Three Gorges Dam', 'Kariba', 'Akosombo Main Dam']
OLD_RADIUS = 5                                # cells searched for the matching old dam of a key dam
DOWNSTREAM_STATIONS = 2                       # stations listed per key dam along its downstream path
DAM_VARS = ['OUT_GDAM_INFLOW', 'OUT_GDAM_DEMAND', 'OUT_GDAM_RELEASE', 'OUT_GDAM_STORAGE']   # hm3 (storage: mean)
LOCAL_VARS = ['OUT_LDAM_INFLOW', 'OUT_LDAM_DEMAND', 'OUT_LDAM_RELEASE', 'OUT_LDAM_STORAGE']
RESOURCES = {'dams': (4, '32G', '01:00:00'), 'grdc': (4, '32G', '02:00:00')}
STEP_SBATCH = """#!/bin/bash
#SBATCH --job-name={task}-{step}
#SBATCH --partition=main
#SBATCH --time={time}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -euo pipefail
JOB_DIR={logs}/{step}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={workdir}
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
/usr/bin/time -v python3 analysis/{task}/dam_parameter_test.py {step} --processes {cpus}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def products(sub=''):
    d = f'{workdir()}/analysis/{TASK}' + (f'/{sub}' if sub else '')
    os.makedirs(d, exist_ok=True)
    return d


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def conda_base():
    return subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))


def submit_step(step):
    """Submit on hold, keep the job file in the record directory, release."""
    cpus, mem, time = RESOURCES[step]; logs = products('logs')
    text = STEP_SBATCH.format(task=TASK, step=step, time=time, cpus=cpus, mem=mem, logs=logs, conda=conda_base(),
                              workdir=workdir(), repo=REPO)
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]
    d = f'{logs}/{step}_{job_id}'; os.makedirs(d, exist_ok=True)
    with open(f'{d}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {d}/')


def write_summary(step, summary):
    summary = {'step': step, 'created_at': utcnow(), 'code_commit': subprocess.run(
        ['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(), **summary}
    with open(f'{products("tables")}/{step}_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(json.dumps(summary, indent=1, default=float))


def run_dir():
    return f'{workdir()}/{MAIN}'


def resolved():
    with open(f'{run_dir()}/config/resolved.yaml') as fh:
        return yaml.safe_load(fh)


def field(ds, var, t):
    """One time step of a (time, lat, lon) output variable, NaN for fill values."""
    v = ds[var]; a = np.asarray(v[t], dtype='f8')
    fill = getattr(v, '_FillValue', None)
    if fill is not None:
        a[a == fill] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    return a


def _plt():
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


# ----------------------------------------------------------------------------------------------- dams
def dam_inputs():
    params = resolved()['parameters']
    dam_file = f'{workdir()}/{params["dams"]["path"]}'
    dams = pd.read_csv(f'{os.path.dirname(dam_file)}/dam_list_isimip4b.csv').set_index('dam_class')
    with Dataset(f'{os.path.dirname(dam_file)}/mean_discharge_natural.nc') as d:
        d.set_auto_mask(False)
        qnat = np.asarray(d['discharge'][:], 'f8')
    return params, dams, qnat


def monthly_at(path_of_year, variables, rows, cols):
    """{var: array (months, cells)} for the years in YEARS, read one month at a time."""
    out = {v: [] for v in variables}
    for y in YEARS:
        with Dataset(path_of_year(y)) as m:
            m.set_auto_mask(False)
            lat = np.asarray(m['lat'][:])
            for t in range(len(m.dimensions['time'])):
                for v in variables:
                    out[v].append(field(m, v, t)[rows, cols])
    return {v: np.array(a) for v, a in out.items()}, lat


def old_dam_cells():
    """(row, col, capacity) of every global dam of the old dam file."""
    with Dataset(f'{workdir()}/{OLD_DAMS}') as d:
        d.set_auto_mask(False)
        idm = np.asarray(d['id_map'][:]); ids = np.asarray(d['id'][:]); typ = np.asarray(d['type'][:])
        cap = np.asarray(d['capacity'][:], 'f8')
    flat = np.flatnonzero(idm.ravel() >= 0)
    lut = np.full(idm.max() + 1, -1, 'i8'); lut[idm.ravel()[flat]] = flat
    pos = lut[ids]; g = (typ == 1) & (pos >= 0)
    return pos[g] // idm.shape[1], pos[g] % idm.shape[1], cap[g]


def dams_step(processes):
    params, dams, qnat = dam_inputs()
    rd = run_dir()
    with Dataset(f'{rd}/{END_STATE}') as s:
        s.set_auto_mask(False)
        active = np.asarray(s['STATE_DAM_ACTIVE'][:]) > 0
        storage_end = np.asarray(s['STATE_DAM_STORAGE'][:], 'f8')
    if len(active) != len(dams):
        sys.exit(f'end state has {len(active)} dams, the dam list {len(dams)}')
    dams = dams.assign(active_end_2016=active, storage_end_2016_hm3=storage_end)
    act = dams[dams['active_end_2016']]
    glob_ = act[act['type'] == 1]; loc = act[act['type'] == 0]
    rows, cols = glob_['row'].values, glob_['col'].values
    shared = pd.Series(list(zip(rows, cols))).duplicated(keep=False).values
    series, lat = monthly_at(lambda y: f'{rd}/output/monthly.{y}-01.nc', DAM_VARS, rows, cols)
    if np.abs(lat[rows] - glob_['cell_lat'].values).max() > 1e-3:
        sys.exit('dam list rows do not match the output grid')
    y16 = slice(12 * YEARS.index(YEAR), 12 * YEARS.index(YEAR) + 12)
    seconds = (pd.Timestamp(YEAR + 1, 1, 1) - pd.Timestamp(YEAR, 1, 1)).total_seconds()
    expected = qnat[rows, cols] * glob_['inflow_fraction'].values * seconds / 1e6          # hm3 per year
    # After a cold start a dam only records its inflow for a year and starts to operate at the first month of its
    # operational year; before that its inflow and release are zero. Inflow is compared over the operating months.
    operating = (series['OUT_GDAM_INFLOW'][y16] > 0) | (series['OUT_GDAM_RELEASE'][y16] > 0)          # (12, dams)
    days = pd.date_range(f'{YEAR}-01-01', periods=12, freq='MS').days_in_month.values[:, None]
    op_days = (operating * days).sum(0)
    first = np.where(operating.any(0), operating.argmax(0) + 1, 0)
    tab = pd.DataFrame({
        'name': glob_['name'].values, 'country': glob_['country'].values, 'row': rows, 'col': cols,
        'capacity_hm3': glob_['capacity_mcm'].values, 'year_histsoc': glob_['year_histsoc'].values,
        'purpose_rule': glob_['purpose_rule'].values, 'nservice': glob_['nservice'].values, 'shared_cell': shared,
        'natural_mean_inflow_hm3': expected, 'first_operating_month_2016': first, 'operating_days_2016': op_days,
        'inflow_2016_hm3': series['OUT_GDAM_INFLOW'][y16].sum(0), 'demand_2016_hm3': series['OUT_GDAM_DEMAND'][y16].sum(0),
        'release_2016_hm3': series['OUT_GDAM_RELEASE'][y16].sum(0),
        'storage_min_frac_2016': series['OUT_GDAM_STORAGE'][y16].min(0) / glob_['capacity_mcm'].values,
        'storage_max_frac_2016': series['OUT_GDAM_STORAGE'][y16].max(0) / glob_['capacity_mcm'].values,
        'storage_end_2016_hm3': glob_['storage_end_2016_hm3'].values}, index=glob_.index)
    # inflow per operating day against the natural mean inflow per day
    tab['inflow_ratio'] = (tab['inflow_2016_hm3'] / tab['operating_days_2016'].where(tab['operating_days_2016'] > 0)) / \
        (tab['natural_mean_inflow_hm3'].where(tab['natural_mean_inflow_hm3'] > 0) * 86400 / seconds)
    tab['storage_end_frac'] = tab['storage_end_2016_hm3'] / tab['capacity_hm3']
    tab.to_csv(f'{products("tables")}/dams_global_2016.csv')
    single = tab[~tab['shared_cell']]
    cap = single['capacity_hm3']; r = single['inflow_ratio']; f = single['storage_end_frac']
    started = single['first_operating_month_2016']

    def share(mask):
        return {'dams': int(mask.sum()), 'capacity_km3': float(cap[mask].sum() / 1e3)}

    # local dams: totals at their cells
    lser, _ = monthly_at(lambda y: f'{rd}/output/monthly.{y}-01.nc', LOCAL_VARS, loc['row'].values, loc['col'].values)
    lin = lser['OUT_LDAM_INFLOW'][y16].sum(0)
    lfrac = loc['storage_end_2016_hm3'].values / loc['capacity_mcm'].values
    key = key_dams(dams, tab, series, rows, cols)
    write_summary('dams', {
        'run': MAIN, 'dam_file': params['dams']['path'], 'year': YEAR,
        'global_dams_active': len(tab), 'global_capacity_km3': float(tab['capacity_hm3'].sum() / 1e3),
        'global_dams_sharing_a_cell': int(tab['shared_cell'].sum()),
        'first_operating_month_2016': {int(m): share(started == m) for m in range(13)},
        'inflow_ratio_note': 'inflow per operating day / natural mean inflow per day; dams operating in 2016 only',
        'inflow_ratio_quantiles_10_50_90': [float(q) for q in r.quantile([0.1, 0.5, 0.9])],
        'inflow_ratio_below_0.1': share(r < 0.1), 'inflow_ratio_0.5_to_2': share((r >= 0.5) & (r <= 2)),
        'inflow_ratio_above_2': share(r > 2),
        'storage_end_below_5pct': share(f < 0.05), 'storage_end_above_95pct': share(f > 0.95),
        'storage_end_frac_quantiles_10_50_90': [float(q) for q in f.quantile([0.1, 0.5, 0.9])],
        'capacity_weighted_storage_end_frac': float((f * cap).sum() / cap.sum()),
        'release_over_inflow_2016': float(single['release_2016_hm3'].sum() / single['inflow_2016_hm3'].sum()),
        'local_dams_active': len(loc), 'local_capacity_km3': float(loc['capacity_mcm'].sum() / 1e3),
        'local_inflow_2016_km3': float(np.nansum(lin) / 1e3), 'local_dams_without_inflow': int((lin <= 0).sum()),
        'local_storage_end_frac_quantiles_10_50_90': [float(q) for q in np.nanquantile(lfrac, [0.1, 0.5, 0.9])],
        'key_dams': key})


def key_dams(dams, tab, series, rows, cols):
    """Monthly series of the key dams, the matching old dam and its storage in the smoke run; table and figure."""
    orow, ocol, ocap = old_dam_cells()
    sel = []
    for name in KEY_DAMS:
        hit = tab[tab['name'] == name]
        if len(hit) != 1:
            sys.exit(f'key dam {name}: {len(hit)} active global dams with this name')
        dc = hit.index[0]; r, c = int(hit.at[dc, 'row']), int(hit.at[dc, 'col'])
        near = np.flatnonzero((np.abs(orow - r) <= OLD_RADIUS) & (np.abs(ocol - c) <= OLD_RADIUS))
        o = near[np.argmax(ocap[near])] if near.size else None
        sel.append({'name': name, 'dam_class': int(dc), 'k': int(np.flatnonzero(tab.index == dc)[0]), 'row': r, 'col': c,
                    'old_row': int(orow[o]) if o is not None else None, 'old_col': int(ocol[o]) if o is not None else None,
                    'old_capacity_hm3': float(ocap[o]) if o is not None else None})
    have_old = [s for s in sel if s['old_row'] is not None]
    old, _ = monthly_at(lambda y: f'{workdir()}/{SMOKE}/output/monthly.{y}-01.nc', ['OUT_GDAM_STORAGE'],
                        np.array([s['old_row'] for s in have_old], int), np.array([s['old_col'] for s in have_old], int))
    months = pd.date_range(f'{YEARS[0]}-01-01', periods=12 * len(YEARS), freq='MS')
    days = months.days_in_month.values
    recs = []
    for s in sel:
        k = s['k']
        for t, mth in enumerate(months):
            recs.append({'name': s['name'], 'month': mth.strftime('%Y-%m'),
                         **{v.replace('OUT_GDAM_', '').lower() + '_hm3': float(series[v][t, k]) for v in DAM_VARS},
                         'smoke_storage_hm3': float(old['OUT_GDAM_STORAGE'][t, have_old.index(s)]) if s in have_old else np.nan})
    mon = pd.DataFrame(recs)
    mon.to_csv(f'{products("tables")}/key_dams_monthly.csv', index=False)
    out = []
    for s in sel:
        row = tab.loc[s['dam_class']]
        out.append({**{k: v for k, v in s.items() if k != 'k'}, 'capacity_hm3': float(row['capacity_hm3']),
                    'natural_mean_inflow_hm3': float(row['natural_mean_inflow_hm3']),
                    'first_operating_month_2016': int(row['first_operating_month_2016']),
                    'inflow_2016_hm3': float(row['inflow_2016_hm3']), 'inflow_ratio': float(row['inflow_ratio']),
                    'release_2016_hm3': float(row['release_2016_hm3']), 'demand_2016_hm3': float(row['demand_2016_hm3']),
                    'storage_end_frac': float(row['storage_end_frac'])})
    pd.DataFrame(out).to_csv(f'{products("tables")}/key_dams.csv', index=False)
    plt = _plt()
    fig, axs = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    for ax, s, o in zip(axs.ravel(), sel, out):
        m = mon[mon['name'] == s['name']]
        x = pd.to_datetime(m['month'])
        ax.plot(x, m['inflow_hm3'], 'b-', marker='o', ms=3, label='inflow')
        ax.plot(x, m['release_hm3'], 'r-', marker='o', ms=3, label='release')
        ax.plot(x, o['natural_mean_inflow_hm3'] / 366 * days, 'b:', label='natural mean inflow')
        ax.set_ylabel('hm3 per month'); ax.set_title(f'{s["name"]} (capacity {o["capacity_hm3"]:.0f} hm3)', fontsize=10)
        a2 = ax.twinx()
        a2.plot(x, 100 * m['storage_hm3'] / o['capacity_hm3'], 'k-', label='storage, new dam file')
        if o['old_capacity_hm3']:
            a2.plot(x, 100 * m['smoke_storage_hm3'] / o['old_capacity_hm3'], 'k--', label='storage, smoke (old file)')
        a2.set_ylim(0, 105); a2.set_ylabel('storage (% of capacity)')
        if ax is axs[0, 0]:
            ax.legend(loc='upper left', fontsize=7); a2.legend(loc='upper right', fontsize=7)
    fig.suptitle(f'key dams, run {MAIN_LABEL} {YEARS[0]}-{YEARS[-1]} (cold start {YEARS[0]})')
    fig.tight_layout(); fig.savefig(f'{products("figures")}/key_dams.png', dpi=110); plt.close(fig)
    return out


# ----------------------------------------------------------------------------------------------- grdc
def grdc_step(processes):
    W = workdir()
    with open(f'{run_dir()}/run_manifest.json') as fh:
        man = json.load(fh)
    st = pd.read_csv(f'{W}/qc/{man["run_dir"]}/reports/grdc_stations.csv').set_index('grdc_no')
    files = grdc.station_files(W)
    clim = {}
    for no in st.index:
        _, daily = grdc.read_station(files[no])
        c, lo, hi, _ = grdc.climatology(grdc.monthly_means(daily), GRDC_REF)
        if np.isfinite(c).all() and c.mean() > 0:
            clim[no] = (c, lo, hi)
    st = st.loc[list(clim)]
    rows, cols = st['row'].values.astype(int), st['col'].values.astype(int)
    sim = {}
    for label, path in (('test', f'{run_dir()}/output/monthly.{YEAR}-01.nc'),
                        ('smoke', f'{W}/{SMOKE}/output/monthly.{YEAR}-01.nc')):
        with Dataset(path) as m:
            m.set_auto_mask(False)
            sim[label] = np.array([field(m, 'OUT_DISCHARGE', t)[rows, cols] for t in range(12)])   # (12, stations)
    obs = np.array([clim[no][0] for no in st.index]).T
    tab = st[['river', 'station', 'lat', 'lon', 'area_km2', 'row', 'col']].copy()
    tab['obs_mean_m3_s'] = obs.mean(0)
    for label in sim:
        tab[f'{label}_mean_m3_s'] = sim[label].mean(0)
        tab[f'{label}_ratio'] = tab[f'{label}_mean_m3_s'] / tab['obs_mean_m3_s']
        tab[f'{label}_seasonal_r'] = [np.corrcoef(sim[label][:, i], obs[:, i])[0, 1] if np.std(sim[label][:, i]) > 0
                                      else np.nan for i in range(len(tab))]
    tab['test_over_smoke'] = tab['test_mean_m3_s'] / tab['smoke_mean_m3_s']
    tab['closer_to_obs'] = np.abs(np.log(tab['test_ratio'])) < np.abs(np.log(tab['smoke_ratio']))
    tab.to_csv(f'{products("tables")}/grdc_2016.csv')
    down = downstream_stations(tab)
    summ = {}
    for label in sim:
        r = tab[f'{label}_ratio']
        summ[label] = {'median_ratio': float(r.median()), 'share_within_0.8_1.25': float(((r >= 0.8) & (r <= 1.25)).mean()),
                       'median_seasonal_r': float(tab[f'{label}_seasonal_r'].median())}
    ch = np.abs(np.log(tab['test_over_smoke']))
    write_summary('grdc', {
        'year': YEAR, 'reference_years': [GRDC_REF[0], GRDC_REF[-1]], 'stations': len(tab), 'by_run': summ,
        'stations_changed_over_5pct': int((ch > np.log(1.05)).sum()),
        'stations_changed_over_20pct': int((ch > np.log(1.2)).sum()),
        'changed_over_5pct_closer_to_obs': int((tab['closer_to_obs'] & (ch > np.log(1.05))).sum()),
        'largest_changes': tab.assign(ch=ch).nlargest(15, 'ch')[
            ['river', 'station', 'area_km2', 'obs_mean_m3_s', 'smoke_mean_m3_s', 'test_mean_m3_s']].reset_index()
            .to_dict('records'),
        'key_dams': down})
    figures_grdc(tab, sim, obs, clim, down)


def downstream_stations(tab):
    """The first stations on the downstream path of each key dam."""
    params, dams, _ = dam_inputs()
    W = workdir()
    with Dataset(f'{W}/{params["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool)
    with Dataset(f'{W}/{params["routing"]["path"]}') as r:
        r.set_auto_mask(False)
        nxt = grdc.network(r['downstream'][:], r['downstream_id'][:], mask)
    nx = mask.shape[1]
    at = {int(r * nx + c): no for no, r, c in zip(tab.index, tab['row'], tab['col'])}
    out = []
    for name in KEY_DAMS:
        d = dams[(dams['name'] == name) & (dams['type'] == 1)].iloc[0]
        cell = int(d['row'] * nx + d['col']); steps = 0; found = []
        while len(found) < DOWNSTREAM_STATIONS:
            if cell in at:
                found.append({'grdc_no': int(at[cell]), 'cells_downstream': steps})
            if nxt[cell] == cell or nxt[cell] < 0:
                break
            cell = int(nxt[cell]); steps += 1
        for f in found:
            s = tab.loc[f['grdc_no']]
            f.update({'river': s['river'], 'station': s['station'], 'area_km2': float(s['area_km2']),
                      'obs_mean_m3_s': float(s['obs_mean_m3_s']), 'smoke_mean_m3_s': float(s['smoke_mean_m3_s']),
                      'test_mean_m3_s': float(s['test_mean_m3_s']), 'smoke_seasonal_r': float(s['smoke_seasonal_r']),
                      'test_seasonal_r': float(s['test_seasonal_r'])})
        out.append({'dam': name, 'stations': found})
    pd.DataFrame([{'dam': o['dam'], **f} for o in out for f in o['stations']]).to_csv(
        f'{products("tables")}/grdc_key_dams.csv', index=False)
    return out


def figures_grdc(tab, sim, obs, clim, down):
    plt = _plt()
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.5))
    ax = axs[0]
    ax.scatter(tab['smoke_ratio'], tab['test_ratio'], s=6, c=np.log10(tab['area_km2']), cmap='viridis')
    lim = [0.05, 20]
    ax.plot(lim, lim, 'k-', lw=0.8); ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel(f'smoke {YEAR}: simulated / GRDC mean'); ax.set_ylabel(f'test {YEAR}: simulated / GRDC mean')
    ax = axs[1]
    ax.hist(np.log2(tab['test_over_smoke'].clip(1 / 16, 16)), bins=80, color='0.4')
    ax.set_yscale('log'); ax.set_xlabel(f'log2(test / smoke), mean discharge {YEAR}'); ax.set_ylabel('stations')
    fig.suptitle(f'GRDC stations, {YEAR}: new dam file (run {MAIN_LABEL}) against the smoke run; GRDC {GRDC_REF[0]}-{GRDC_REF[-1]}')
    fig.tight_layout(); fig.savefig(f'{products("figures")}/grdc_ratio_2016.png', dpi=110); plt.close(fig)
    first = [(o['dam'], o['stations'][0]) for o in down if o['stations']]
    if not first:
        return
    fig, axs = plt.subplots(int(np.ceil(len(first) / 2)), 2, figsize=(13, 3.3 * np.ceil(len(first) / 2)), squeeze=False)
    idx = {no: i for i, no in enumerate(tab.index)}
    for ax, (dam, s) in zip(axs.ravel(), first):
        i = idx[s['grdc_no']]; c, lo, hi = clim[s['grdc_no']]
        ax.fill_between(range(12), lo, hi, color='0.85', label=f'GRDC range {GRDC_REF[0]}-{GRDC_REF[-1]}')
        ax.plot(range(12), c, 'k-', marker='o', ms=3, label='GRDC mean')
        ax.plot(range(12), sim['smoke'][:, i], 'g--', label=f'smoke {YEAR} (old dam file)')
        ax.plot(range(12), sim['test'][:, i], 'b-', label=f'test {YEAR} (new dam file)')
        ax.set_xticks(range(12)); ax.set_xticklabels('JFMAMJJASOND'); ax.set_ylabel('m3/s')
        ax.set_title(f'{s["river"]} at {s["station"]}, {s["cells_downstream"]} cells below {dam}', fontsize=9)
        if ax is axs[0, 0]:
            ax.legend(fontsize=7)
    for ax in axs.ravel()[len(first):]:
        ax.set_visible(False)
    fig.tight_layout(); fig.savefig(f'{products("figures")}/grdc_key_dams.png', dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=list(RESOURCES))
    ap.add_argument('--submit', action='store_true', help='submit the step as a Slurm job')
    ap.add_argument('--processes', type=int, default=1)
    a = ap.parse_args()
    if a.submit:
        return submit_step(a.step)
    {'dams': dams_step, 'grdc': grdc_step}[a.step](a.processes)


if __name__ == '__main__':
    main()
