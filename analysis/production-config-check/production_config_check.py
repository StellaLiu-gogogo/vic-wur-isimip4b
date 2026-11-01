#!/usr/bin/env python3
"""Check run of the production configuration (campaign production-config-check, 2015-2016, cold start in 2015).

Question: do VIC-WUR a826251b, the D19 dam files with their FILE decomposition, non-renewable withdrawal with
OUT_NONREN_DEFICIT and 16 ranks x 8 threads on a whole node run as intended together (analysis/production-config-check/
README.md)? The run check of the workflow (check_run.py) and the comparison of compare_runs.py come first; this script
adds what they do not compute.

Runs:
  check   runs/production-config-check/<segment>__check-2015-2016   non-renewable withdrawal on
  ref     runs/snow-density-test/<segment>__ranks16-2015-2016        the same code tree, years, cold start, dam files,
                                                                     decomposition and ranks; non-renewable off
  timing reference: runs/dam-test/<segment>__ranks16-2015-2016 (16 x 8, whole node)

Steps (every computation on a compute node):
  nonrenewable  run check: non-renewable withdrawal by sector and month, the deficit at the end of each month and
                the water repaid in the month (non-renewable withdrawal minus the increase of the deficit, deficit 0
                at the cold start); 2016 by country (ISIMIP fractional country masks, 5 arcmin)
  balance       both runs, per year: global precipitation, evapotranspiration, qtot, withdrawal, consumption,
                non-renewable withdrawal and deficit, and their differences; cell-months with a monthly mean
                |OUT_WATER_ERROR| above 1 mm (mask rule of analysis/snow-sublimation-outliers/)
  dams          both runs: global monthly inflow, demand, release and storage of global and local dams, withdrawal
                from dams; the key dams month by month
  cells         2016: cells whose discharge, qtot or evapotranspiration differ between the runs, split into cells
                with water use (demand or withdrawal in either run), cells downstream of them, and other cells
                (within 2 cells of the first two groups or farther)
  timing        VIC timing table and sacct memory of the VIC step for run check and the timing reference; output
                volume; the hours per model year they imply

Writes to workdir/analysis/production-config-check/:
  tables/   nonrenewable_monthly.csv, nonrenewable_countries_2016.csv, balance_annual.csv, dams_global_monthly.csv,
            key_dams_monthly.csv, cells_2016.csv, timing.csv, <step>_summary.json
  figures/  nonrenewable_monthly.png, dams_global.png, key_dams.png
  logs/<step>_<slurm-job-id>/   job records

Usage:
  production_config_check.py nonrenewable | balance | dams | cells | timing [--submit] [--processes N]
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

import numpy as np
import pandas as pd
import yaml
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'workflow', '05_simulation', 'monitor'))
import grdc   # noqa: E402

TASK = 'production-config-check'
SEGMENT = 'ec-earth3-esm-1-1_historical_histsoc_default_historical'
RUNS = {'check': f'runs/production-config-check/{SEGMENT}__check-2015-2016',
        'ref': f'runs/snow-density-test/{SEGMENT}__ranks16-2015-2016'}
TIMING_REF = f'runs/dam-test/{SEGMENT}__ranks16-2015-2016'
YEARS = (2015, 2016)
YEAR = 2016                                    # the judged year: the dams operate from 2016 after the cold start
SECTORS = ['municipal', 'energy', 'manufacturing', 'livestock', 'irrigation']     # wu_class 0-4
SOURCES = ['GW', 'SURF', 'DAM', 'TREM', 'NREN']                                     # OUT_WI_<source>_SECT
JUDGE = {'nonrenewable': (1300, 2400), 'irrigation': (2300, 3300)}                  # km3/yr, 2016 (user, 2026-10-31)
WATER_ERROR_MM = 1.0
COUNTRY_MASKS = 'raw/ISIMIP4b/InputData/geo_conditions/countrymasks/countrymasks-fractional_5arcmin.nc'
TOP_COUNTRIES = 20
KEY_DAMS = ['Ust-Ilim', 'Bratsk', 'Brokopondo', 'Three Gorges Dam', 'Kariba', 'Akosombo Main Dam']
GDAM = ['OUT_GDAM_INFLOW', 'OUT_GDAM_DEMAND', 'OUT_GDAM_RELEASE', 'OUT_GDAM_STORAGE']   # hm3 (storage: mean)
LDAM = ['OUT_LDAM_INFLOW', 'OUT_LDAM_DEMAND', 'OUT_LDAM_RELEASE', 'OUT_LDAM_STORAGE']
# a cell differs when |a - b| > ABS + REL x max(|a|, |b|) (float32 output)
DIFF_TOL = {'discharge_m3_s': (1e-3, 1e-5), 'qtot_mm': (1e-3, 1e-5), 'evap_mm': (1e-3, 1e-5)}
NEAR_CELLS = 2
RESOURCES = {'nonrenewable': (4, '48G', '01:00:00'), 'balance': (4, '32G', '01:00:00'),
             'dams': (4, '32G', '01:00:00'), 'cells': (4, '48G', '01:00:00'), 'timing': (1, '4G', '00:15:00')}
STEP_SBATCH = """#!/bin/bash
#SBATCH --job-name={task}-{step}
#SBATCH --partition=main
#SBATCH --time={time}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -eo pipefail
JOB_DIR={logs}/{step}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
source {conda}/etc/profile.d/conda.sh
conda activate isimip4b
export ISIMIP4B_WORKDIR={workdir}
cd {repo}
echo "host $(hostname), start $(date -u +%Y-%m-%dT%H:%M:%SZ), commit $(git rev-parse HEAD), dirty $(git status --porcelain | wc -l)"
/usr/bin/time -v python3 analysis/{task}/production_config_check.py {step} --processes {cpus}
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
        ['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
        'runs': RUNS, **summary}
    with open(f'{products("tables")}/{step}_summary.json', 'w') as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(json.dumps(summary, indent=1, default=float))


def run_dir(name):
    return f'{workdir()}/{RUNS[name]}'


def monthly_path(name, year):
    return f'{run_dir(name)}/output/monthly.{year}-01.nc'


def resolved(name='check'):
    with open(f'{run_dir(name)}/config/resolved.yaml') as fh:
        return yaml.safe_load(fh)


def grid():
    """Domain mask and cell area (m2, 0 off the domain) of the parameter set of run check; the reference run must
    use the same domain file (same MD5: the production set holds a copy of the candidate file)."""
    doms = {n: resolved(n)['parameters']['domain'] for n in RUNS}
    paths = {n: d['path'] for n, d in doms.items()}
    if len({d['md5'] for d in doms.values()}) != 1:
        sys.exit(f'the runs use different domain files: {paths}')
    with Dataset(f'{workdir()}/{paths["check"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool)
        area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
    return mask, area


def field(ds, var, t, *index):
    """One time step (and sector) of an output variable, NaN for fill values."""
    v = ds[var]; a = np.asarray(v[(t, *index)], dtype='f8')
    fill = getattr(v, '_FillValue', None)
    if fill is not None:
        a[a == fill] = np.nan
    a[np.abs(a) > 1e30] = np.nan
    return a


def km3(mm, area):
    return float(np.nansum(mm * area) * 1e-12)


def months():
    return pd.date_range(f'{YEARS[0]}-01-01', periods=12 * len(YEARS), freq='MS')


def _plt():
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


# ----------------------------------------------------------------------------------------------- nonrenewable
def country_fractions(lat, lon):
    """(names, iso codes, row and column index into the mask file for the output grid)."""
    with Dataset(f'{workdir()}/{COUNTRY_MASKS}') as d:
        mlat = np.asarray(d['lat'][:]); mlon = np.asarray(d['lon'][:])
        codes = [v for v in d.variables if v not in ('lat', 'lon', 'world')]
        names = {c: getattr(d[c], 'long_name', c) for c in codes}
    ri = np.abs(mlat[None, :] - lat[:, None]).argmin(1); ci = np.abs(mlon[None, :] - lon[:, None]).argmin(1)
    if np.abs(mlat[ri] - lat).max() > 1e-3 or np.abs(mlon[ci] - lon).max() > 1e-3:
        sys.exit('the country masks are not on the output grid')
    return codes, names, ri, ci


def nonrenewable_step(processes):
    mask, area = grid()
    recs, deficit_prev = [], 0.0
    with Dataset(monthly_path('check', YEARS[0])) as m:
        if 'OUT_NONREN_DEFICIT' not in m.variables:
            sys.exit('run check has no OUT_NONREN_DEFICIT')
        deficit_method = getattr(m['OUT_NONREN_DEFICIT'], 'cell_methods', '')
        lat = np.asarray(m['lat'][:]); lon = np.asarray(m['lon'][:])
    year_fields = {}
    for y in YEARS:
        with Dataset(monthly_path('check', y)) as m:
            m.set_auto_mask(False)
            nren_y = np.zeros((len(SECTORS),) + mask.shape); irr_y = np.zeros(mask.shape)
            wd_y = np.zeros(mask.shape)
            for t in range(len(m.dimensions['time'])):
                rec = {'month': f'{y}-{t + 1:02d}'}
                for i, s in enumerate(SECTORS):
                    f = np.nan_to_num(field(m, 'OUT_WI_NREN_SECT', t, i))
                    nren_y[i] += f; rec[f'nonrenewable_{s}_km3'] = km3(f, area)
                    if s == 'irrigation':
                        for src in SOURCES:
                            irr_y += np.nan_to_num(field(m, f'OUT_WI_{src}_SECT', t, i))
                wd_y += np.nan_to_num(field(m, 'OUT_WITHDRAWN', t))
                d = np.nan_to_num(field(m, 'OUT_NONREN_DEFICIT', t))
                rec['nonrenewable_km3'] = sum(rec[f'nonrenewable_{s}_km3'] for s in SECTORS)
                rec['deficit_end_km3'] = km3(d, area)
                rec['deficit_increase_km3'] = rec['deficit_end_km3'] - deficit_prev
                rec['repaid_km3'] = rec['nonrenewable_km3'] - rec['deficit_increase_km3']
                rec['cells_with_deficit'] = int((d[mask] > 0).sum())
                deficit_prev = rec['deficit_end_km3']
                recs.append(rec)
            year_fields[y] = {'nren': nren_y, 'irr': irr_y, 'withdrawn': wd_y, 'deficit_end': d}
    mon = pd.DataFrame(recs)
    mon.to_csv(f'{products("tables")}/nonrenewable_monthly.csv', index=False)
    # 2016 by country
    f16 = year_fields[YEAR]
    stack = {f'nonrenewable_{s}_km3': f16['nren'][i] for i, s in enumerate(SECTORS) if f16['nren'][i].any()}
    stack.update({'nonrenewable_km3': f16['nren'].sum(0), 'irrigation_withdrawal_km3': f16['irr'],
                  'withdrawal_km3': f16['withdrawn'], 'deficit_end_km3': f16['deficit_end']})
    keys = list(stack)
    F = np.array([(stack[k] * area).ravel() * 1e-12 for k in keys])          # km3 per cell
    codes, names, ri, ci = country_fractions(lat, lon)
    rows = []
    with Dataset(f'{workdir()}/{COUNTRY_MASKS}') as d:
        d.set_auto_mask(False)
        for c in codes:
            fr = np.nan_to_num(np.asarray(d[c][:], 'f8')[np.ix_(ri, ci)]).ravel()
            if not fr.any():
                continue
            rows.append({'iso': c, 'country': names[c], **dict(zip(keys, F @ fr))})
    ctab = pd.DataFrame(rows).sort_values('nonrenewable_km3', ascending=False)
    ctab['nonrenewable_share_of_withdrawal'] = ctab['nonrenewable_km3'] / ctab['withdrawal_km3'].where(ctab['withdrawal_km3'] > 0)
    ctab.to_csv(f'{products("tables")}/nonrenewable_countries_2016.csv', index=False)
    g = mon[mon['month'].str.startswith(str(YEAR))]
    tot = {k: float(F[i].sum()) for i, k in enumerate(keys)}
    figure_nonrenewable(mon, ctab)
    nren16, irr16 = tot['nonrenewable_km3'], tot['irrigation_withdrawal_km3']
    write_summary('nonrenewable', {
        'year': YEAR, 'deficit_cell_methods': deficit_method,
        'deficit_note': 'deficit 0 at the cold start of 2015-01-01; repaid = non-renewable withdrawal - deficit increase',
        'global_2016_km3': tot,
        'nonrenewable_by_year_km3': {int(y): float(mon[mon['month'].str.startswith(str(y))]['nonrenewable_km3'].sum())
                                     for y in YEARS},
        'repaid_by_year_km3': {int(y): float(mon[mon['month'].str.startswith(str(y))]['repaid_km3'].sum()) for y in YEARS},
        'deficit_end_of_year_km3': {int(y): float(mon[mon['month'] == f'{y}-12']['deficit_end_km3'].iloc[0]) for y in YEARS},
        'months_with_negative_repaid': mon.loc[mon['repaid_km3'] < -1e-6, 'month'].tolist(),
        'repaid_share_2016': float(g['repaid_km3'].sum() / g['nonrenewable_km3'].sum()),
        'judgement_lines_km3': JUDGE,
        'within_judgement_lines': {'nonrenewable': JUDGE['nonrenewable'][0] <= nren16 <= JUDGE['nonrenewable'][1],
                                   'irrigation': JUDGE['irrigation'][0] <= irr16 <= JUDGE['irrigation'][1]},
        'country_sum_over_global_nonrenewable': float(ctab['nonrenewable_km3'].sum() / nren16) if nren16 else None,
        'top_countries': ctab.head(TOP_COUNTRIES)[['iso', 'country', 'nonrenewable_km3', 'irrigation_withdrawal_km3',
                                                   'withdrawal_km3', 'deficit_end_km3']].to_dict('records')})


def figure_nonrenewable(mon, ctab):
    plt = _plt()
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))
    ax = axs[0]; x = pd.to_datetime(mon['month'])
    ax.plot(x, mon['nonrenewable_km3'], 'r-', marker='o', ms=3, label='non-renewable withdrawal')
    ax.plot(x, mon['repaid_km3'], 'b-', marker='o', ms=3, label='repaid from baseflow')
    ax.set_ylabel('km3 per month'); ax.legend(loc='upper left', fontsize=8)
    a2 = ax.twinx(); a2.plot(x, mon['deficit_end_km3'], 'k--', label='deficit, end of month')
    a2.set_ylabel('km3 (deficit)'); a2.legend(loc='upper right', fontsize=8)
    ax.set_title(f'global, run check-2015-2016 (cold start {YEARS[0]})', fontsize=10)
    ax = axs[1]; top = ctab.head(TOP_COUNTRIES)[::-1]
    ax.barh(top['iso'], top['nonrenewable_km3'], color='0.4')
    ax.set_xlabel(f'non-renewable withdrawal {YEAR} (km3)'); ax.set_title(f'{TOP_COUNTRIES} largest countries', fontsize=10)
    fig.tight_layout(); fig.savefig(f'{products("figures")}/nonrenewable_monthly.png', dpi=110); plt.close(fig)


# ----------------------------------------------------------------------------------------------- balance
def balance_step(processes):
    mask, area = grid()
    recs, err = [], {}
    for name in RUNS:
        for y in YEARS:
            with Dataset(monthly_path(name, y)) as m:
                m.set_auto_mask(False)
                acc = {k: 0.0 for k in ('precipitation', 'evapotranspiration', 'qtot', 'baseflow', 'withdrawal',
                                        'consumption', 'nonrenewable', 'irrigation_withdrawal')}
                n_err = 0; worst = 0.0
                for t in range(len(m.dimensions['time'])):
                    acc['precipitation'] += km3(field(m, 'OUT_PREC', t), area)
                    acc['evapotranspiration'] += km3(field(m, 'OUT_EVAP', t), area)
                    b = km3(field(m, 'OUT_BASEFLOW', t), area)
                    acc['qtot'] += km3(field(m, 'OUT_RUNOFF', t), area) + b; acc['baseflow'] += b
                    acc['withdrawal'] += km3(field(m, 'OUT_WITHDRAWN', t), area)
                    acc['consumption'] += km3(field(m, 'OUT_CONSUMED', t), area)
                    acc['nonrenewable'] += sum(km3(field(m, 'OUT_WI_NREN_SECT', t, i), area) for i in range(len(SECTORS)))
                    acc['irrigation_withdrawal'] += sum(km3(field(m, f'OUT_WI_{s}_SECT', t, 4), area) for s in SOURCES)
                    we = np.abs(field(m, 'OUT_WATER_ERROR', t))[mask]
                    n_err += int((we > WATER_ERROR_MM).sum()); worst = max(worst, float(np.nanmax(we)))
                deficit = km3(np.nan_to_num(field(m, 'OUT_NONREN_DEFICIT', len(m.dimensions['time']) - 1)), area) \
                    if 'OUT_NONREN_DEFICIT' in m.variables else 0.0
            acc['p_minus_et_minus_qtot'] = acc['precipitation'] - acc['evapotranspiration'] - acc['qtot']
            recs.append({'run': name, 'year': y, **{f'{k}_km3': v for k, v in acc.items()},
                         'deficit_end_km3': deficit, 'cell_months_water_error_above_1mm': n_err,
                         'max_abs_water_error_mm': worst})
    tab = pd.DataFrame(recs)
    tab.to_csv(f'{products("tables")}/balance_annual.csv', index=False)
    diff = {}
    cols = [c for c in tab.columns if c.endswith('_km3')]
    for y in YEARS:
        a = tab[(tab['run'] == 'check') & (tab['year'] == y)].iloc[0]; b = tab[(tab['run'] == 'ref') & (tab['year'] == y)].iloc[0]
        diff[int(y)] = {f'{c}_check_minus_ref': float(a[c] - b[c]) for c in cols}
    write_summary('balance', {
        'note': 'same climate and cold start: precipitation must be equal; the non-renewable water of run check is '
                'withdrawn on top, part of it evaporates (consumption) and part returns; qtot contains the repaid baseflow',
        'water_error_threshold_mm': WATER_ERROR_MM, 'annual': tab.to_dict('records'), 'check_minus_ref': diff})


# ----------------------------------------------------------------------------------------------- dams
def dam_list(name='check'):
    dams = {n: resolved(n)['parameters']['dams'] for n in RUNS}
    paths = {n: d['path'] for n, d in dams.items()}
    if len({d['md5'] for d in dams.values()}) != 1:
        sys.exit(f'the runs use different dam files: {paths}')
    return pd.read_csv(f'{workdir()}/{os.path.dirname(paths[name])}/dam_list_isimip4b.csv').set_index('dam_class')


def dams_step(processes):
    mask, area = grid()
    dams = dam_list()
    key, klat = [], []
    for nm in KEY_DAMS:
        hit = dams[(dams['name'] == nm) & (dams['type'] == 1)]
        if len(hit) != 1:
            sys.exit(f'key dam {nm}: {len(hit)} global dams with this name')
        key.append((nm, int(hit['row'].iloc[0]), int(hit['col'].iloc[0]), float(hit['capacity_mcm'].iloc[0])))
        klat.append(float(hit['cell_lat'].iloc[0]))
    krows = np.array([k[1] for k in key]); kcols = np.array([k[2] for k in key])
    glob_recs, key_recs = [], []
    for name in RUNS:
        for y in YEARS:
            with Dataset(monthly_path(name, y)) as m:
                m.set_auto_mask(False)
                if np.abs(np.asarray(m['lat'][:])[krows] - np.array(klat)).max() > 1e-3:
                    sys.exit('dam list rows do not match the output grid')
                for t in range(len(m.dimensions['time'])):
                    rec = {'run': name, 'month': f'{y}-{t + 1:02d}'}
                    kv = {}
                    for v in GDAM + LDAM:
                        f = field(m, v, t)
                        rec[v.replace('OUT_', '').lower() + '_km3'] = float(np.nansum(f[mask]) / 1e3)
                        if v in GDAM:
                            kv[v] = f[krows, kcols]
                    rec['withdrawal_from_dams_km3'] = sum(km3(field(m, 'OUT_WI_DAM_SECT', t, i), area)
                                                          for i in range(len(SECTORS)))
                    glob_recs.append(rec)
                    for j, (nm, r, c, cap) in enumerate(key):
                        key_recs.append({'run': name, 'name': nm, 'month': f'{y}-{t + 1:02d}', 'capacity_hm3': cap,
                                         **{v.replace('OUT_GDAM_', '').lower() + '_hm3': float(kv[v][j]) for v in GDAM}})
    gtab = pd.DataFrame(glob_recs); ktab = pd.DataFrame(key_recs)
    gtab.to_csv(f'{products("tables")}/dams_global_monthly.csv', index=False)
    ktab.to_csv(f'{products("tables")}/key_dams_monthly.csv', index=False)
    figures_dams(gtab, ktab)
    y16 = gtab[gtab['month'].str.startswith(str(YEAR))]
    by_run = {}
    for name in RUNS:
        g = y16[y16['run'] == name]
        by_run[name] = {'global_inflow_km3': float(g['gdam_inflow_km3'].sum()),
                        'global_release_km3': float(g['gdam_release_km3'].sum()),
                        'global_demand_km3': float(g['gdam_demand_km3'].sum()),
                        'global_storage_mean_km3': float(g['gdam_storage_km3'].mean()),
                        'local_inflow_km3': float(g['ldam_inflow_km3'].sum()),
                        'local_release_km3': float(g['ldam_release_km3'].sum()),
                        'local_storage_mean_km3': float(g['ldam_storage_km3'].mean()),
                        'withdrawal_from_dams_km3': float(g['withdrawal_from_dams_km3'].sum())}
    k16 = ktab[ktab['month'].str.startswith(str(YEAR))]
    keys = {}
    for nm, *_ in key:
        a = k16[(k16['run'] == 'check') & (k16['name'] == nm)]; b = k16[(k16['run'] == 'ref') & (k16['name'] == nm)]
        keys[nm] = {f'{q}_{YEAR}_hm3': {'check': float(a[f'{q}_hm3'].sum()), 'ref': float(b[f'{q}_hm3'].sum())}
                    for q in ('inflow', 'demand', 'release')}
        keys[nm]['storage_dec_frac'] = {r: float(k16[(k16['run'] == r) & (k16['name'] == nm)]['storage_hm3'].iloc[-1]
                                                 / a['capacity_hm3'].iloc[0]) for r in RUNS}
    write_summary('dams', {'year': YEAR, 'by_run_2016': by_run, 'key_dams': keys})


def figures_dams(gtab, ktab):
    plt = _plt()
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))
    for ax, kind in zip(axs, ('gdam', 'ldam')):
        for name, ls in (('check', '-'), ('ref', '--')):
            g = gtab[gtab['run'] == name]; x = pd.to_datetime(g['month'])
            ax.plot(x, g[f'{kind}_inflow_km3'], 'b' + ls, label=f'inflow, {name}')
            ax.plot(x, g[f'{kind}_release_km3'], 'r' + ls, label=f'release, {name}')
            ax.plot(x, g[f'{kind}_demand_km3'], 'g' + ls, label=f'demand, {name}')
        ax.set_ylabel('km3 per month')
        a2 = ax.twinx()
        for name, ls in (('check', '-'), ('ref', '--')):
            g = gtab[gtab['run'] == name]
            a2.plot(pd.to_datetime(g['month']), g[f'{kind}_storage_km3'], 'k' + ls, label=f'storage, {name}')
        a2.set_ylabel('km3 (storage, monthly mean)')
        ax.set_title({'gdam': 'global dams', 'ldam': 'local dams'}[kind], fontsize=10)
        ax.legend(loc='upper left', fontsize=7); a2.legend(loc='upper right', fontsize=7)
    fig.tight_layout(); fig.savefig(f'{products("figures")}/dams_global.png', dpi=110); plt.close(fig)
    fig, axs = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
    for ax, nm in zip(axs.ravel(), KEY_DAMS):
        cap = ktab[ktab['name'] == nm]['capacity_hm3'].iloc[0]
        a2 = ax.twinx()
        for name, ls in (('check', '-'), ('ref', '--')):
            k = ktab[(ktab['run'] == name) & (ktab['name'] == nm)]; x = pd.to_datetime(k['month'])
            ax.plot(x, k['inflow_hm3'], 'b' + ls, label=f'inflow, {name}')
            ax.plot(x, k['release_hm3'], 'r' + ls, label=f'release, {name}')
            a2.plot(x, 100 * k['storage_hm3'] / cap, 'k' + ls, label=f'storage, {name}')
        ax.set_ylabel('hm3 per month'); a2.set_ylim(0, 105); a2.set_ylabel('storage (% of capacity)')
        ax.set_title(f'{nm} (capacity {cap:.0f} hm3)', fontsize=10)
        if ax is axs[0, 0]:
            ax.legend(loc='upper left', fontsize=7); a2.legend(loc='upper right', fontsize=7)
    fig.suptitle(f'key dams, check-2015-2016 (solid) and snow-density-test ranks16 (dashed), cold start {YEARS[0]}; '
                 'inflow and release are 0 before the first operation month of the dam')
    fig.autofmt_xdate()
    fig.tight_layout(); fig.savefig(f'{products("figures")}/key_dams.png', dpi=110); plt.close(fig)


# ----------------------------------------------------------------------------------------------- cells
def annual_fields(name):
    """2016 fields of one run: mean discharge, qtot, evapotranspiration, demand and withdrawal."""
    with Dataset(monthly_path(name, YEAR)) as m:
        m.set_auto_mask(False)
        nt = len(m.dimensions['time'])
        out = {'discharge_m3_s': 0.0, 'qtot_mm': 0.0, 'evap_mm': 0.0, 'demand_mm': 0.0, 'withdrawn_mm': 0.0}
        for t in range(nt):
            out['discharge_m3_s'] = out['discharge_m3_s'] + field(m, 'OUT_DISCHARGE', t) / nt
            out['qtot_mm'] = out['qtot_mm'] + field(m, 'OUT_RUNOFF', t) + field(m, 'OUT_BASEFLOW', t)
            out['evap_mm'] = out['evap_mm'] + field(m, 'OUT_EVAP', t)
            out['demand_mm'] = out['demand_mm'] + np.nan_to_num(field(m, 'OUT_DEMAND', t))
            out['withdrawn_mm'] = out['withdrawn_mm'] + np.nan_to_num(field(m, 'OUT_WITHDRAWN', t))
    return out


def downstream_of(seed, nxt):
    """Cells on the downstream paths of the seed cells (flat indices), the seed cells excluded."""
    marked = np.zeros(nxt.size, bool); marked[seed] = True
    front = np.flatnonzero(marked)
    while front.size:
        down = nxt[front]; down = np.unique(down[(down >= 0) & (down != front)])
        front = down[~marked[down]]; marked[front] = True
    marked[seed] = False
    return marked


def near(m, n):
    """Cells within n cells (in rows and columns, columns wrapping around) of the cells of the boolean map m."""
    out = m.copy()
    for dr in range(-n, n + 1):
        sh = np.zeros_like(m)
        if dr >= 0:
            sh[dr:] = m[:m.shape[0] - dr]
        else:
            sh[:dr] = m[-dr:]
        for dc in range(-n, n + 1):
            out |= np.roll(sh, dc, axis=1)
    return out


def year_sum(name, year, var):
    """Sum over the months (and sectors) of one year of a monthly output variable of one run."""
    with Dataset(monthly_path(name, year)) as m:
        m.set_auto_mask(False)
        v = m[var]; nk = v.shape[1] if v.ndim == 4 else 0
        out = 0.0
        for t in range(len(m.dimensions['time'])):
            for k in (range(nk) if nk else [None]):
                out = out + np.nan_to_num(field(m, var, t, *([k] if nk else [])))
    return out


def cause_maps(mask, nxt, b_demand_2015):
    """Boolean maps of the known reasons why a cell without water use in 2016 and not downstream of one can differ
    between the runs: it gives water to other cells (OUT_DE_REM_SECT of run check), it had water use in 2015 (the
    state carries the difference into 2016), it is a dam cell or downstream of one (the release of a supply dam
    follows the surface-water demand of its service cells, which differs between the runs)."""
    rem = (year_sum('check', YEARS[0], 'OUT_DE_REM_SECT') > 0) | (year_sum('check', YEAR, 'OUT_DE_REM_SECT') > 0)
    wu15 = (year_sum('check', YEARS[0], 'OUT_DEMAND') > 0) | (b_demand_2015 > 0)
    dams = dam_list()
    dam = np.zeros(mask.shape, bool); dam[dams['row'].astype(int), dams['col'].astype(int)] = True
    dam_down = downstream_of(np.flatnonzero(dam.ravel()), nxt).reshape(mask.shape)
    return {'gives_water_to_other_cells': rem & mask, 'water_use_2015': wu15 & mask, 'dam_cell': dam & mask,
            'downstream_of_dam': dam_down & mask}


def cells_step(processes):
    mask, area = grid()
    a, b = annual_fields('check'), annual_fields('ref')
    rpath = resolved()['parameters']['routing']['path']
    with Dataset(f'{workdir()}/{rpath}') as r:
        r.set_auto_mask(False)
        nxt = grdc.network(r['downstream'][:], r['downstream_id'][:], mask)
    wu = mask & ((a['demand_mm'] > 0) | (b['demand_mm'] > 0) | (a['withdrawn_mm'] > 0) | (b['withdrawn_mm'] > 0))
    down = downstream_of(np.flatnonzero(wu.ravel()), nxt).reshape(mask.shape) & mask & ~wu
    other = mask & ~wu & ~down
    other_near = other & near(wu | down, NEAR_CELLS)
    groups = {'water_use': wu, 'downstream': down, f'other_within_{NEAR_CELLS}_cells': other_near,
              'other_farther': other & ~other_near}
    causes = cause_maps(mask, nxt, year_sum('ref', YEARS[0], 'OUT_DEMAND'))
    recs, examples, odd = [], {}, []
    for var, (tol_abs, tol_rel) in DIFF_TOL.items():
        x, y = a[var], b[var]
        d = np.abs(x - y); scale = np.fmax(np.abs(x), np.abs(y))
        differs = mask & ((d > tol_abs + tol_rel * scale) | (np.isfinite(x) != np.isfinite(y)))
        rel = np.where(scale > 0, d / scale, 0.0)
        for g, gm in groups.items():
            sel = differs & gm
            recs.append({'variable': var, 'group': g, 'cells': int(gm.sum()), 'cells_differing': int(sel.sum()),
                         'max_abs_difference': float(np.nanmax(d[sel])) if sel.any() else 0.0,
                         'max_rel_difference': float(np.nanmax(rel[sel])) if sel.any() else 0.0})
        # cells that differ outside the water-use cells, except discharge downstream of them, with their reasons
        for g, gm in groups.items():
            if g == 'water_use' or (g == 'downstream' and var == 'discharge_m3_s'):
                continue
            for i, j in zip(*np.nonzero(differs & gm)):
                odd.append({'variable': var, 'group': g, 'row': int(i), 'col': int(j), 'check': float(x[i, j]),
                            'ref': float(y[i, j]), 'reasons': [c for c, cm in causes.items() if cm[i, j]]})
        far = differs & groups['other_farther']
        if far.any():
            i = np.argsort(-np.where(far, d, -1).ravel())[:10]
            examples[var] = [{'row': int(k // mask.shape[1]), 'col': int(k % mask.shape[1]),
                              'check': float(x.ravel()[k]), 'ref': float(y.ravel()[k])} for k in i]
    tab = pd.DataFrame(recs)
    tab.to_csv(f'{products("tables")}/cells_2016.csv', index=False)
    write_summary('cells', {
        'year': YEAR, 'tolerance': {k: f'{v[0]} + {v[1]} x max(|a|, |b|)' for k, v in DIFF_TOL.items()},
        'water_use_cells': 'demand or withdrawal above 0 in 2016 in either run', 'table': tab.to_dict('records'),
        'reasons': {'gives_water_to_other_cells': 'OUT_DE_REM_SECT above 0 in 2015 or 2016 in run check',
                    'water_use_2015': 'demand above 0 in 2015 in either run',
                    'dam_cell': 'cell of a dam of the dam list', 'downstream_of_dam': 'downstream of a dam cell'},
        'cells_outside_water_use': odd, 'cells_outside_water_use_without_reason': sum(not o['reasons'] for o in odd),
        'largest_differences_farther_cells': examples})


# ----------------------------------------------------------------------------------------------- timing
def timing_of(rel):
    """VIC timing table, sacct memory of the VIC step and output volume of one completed run."""
    rd = f'{workdir()}/{rel}'
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    att = [x for x in man['attempts'] if x['status'] == 'completed'][-1]
    job = str(att['slurm_job_id'])
    text = open(f'{rd}/logs/vic_stdout_{job}.txt').read()
    rec = {'run': rel, 'slurm_job_id': job, 'days': None}
    for timer in ('Init', 'Run', 'Final', 'Total', 'Force', 'Write'):
        mt = re.search(rf'\|\s*{timer} Time\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|', text)
        if mt:
            rec[f'{timer.lower()}_s'] = float(mt.group(1)); rec[f'{timer.lower()}_s_per_day'] = float(mt.group(3))
    if 'run_s' in rec and rec.get('run_s_per_day'):
        rec['days'] = round(rec['run_s'] / rec['run_s_per_day'])
    sa = subprocess.run(['sacct', '-j', job, '-P', '-n', '--units=G', '-o', 'JobID,Elapsed,MaxRSS,AveRSS,NTasks,NodeList'],
                        capture_output=True, text=True).stdout.splitlines()
    for line in sa:
        f = line.split('|')
        if f[0] == f'{job}.1':
            rec.update({'vic_step_elapsed': f[1], 'max_rss_per_rank_gb': gb(f[2]), 'ave_rss_gb': gb(f[3]),
                        'ntasks': int(f[4]) if f[4] else None, 'node': f[5]})
        if f[0] == job:
            rec['job_elapsed'] = f[1]
    if rec.get('ave_rss_gb') and rec.get('ntasks'):
        rec['ave_rss_x_ranks_gb'] = rec['ave_rss_gb'] * rec['ntasks']
    for kind in ('daily', 'monthly'):
        files = glob.glob(f'{rd}/output/{kind}.*.nc')
        rec[f'{kind}_output_gb'] = sum(os.path.getsize(p) for p in files) / 1e9
    rec['state_gb'] = sum(os.path.getsize(p) for p in glob.glob(f'{rd}/states/*.nc')) / 1e9
    if rec.get('run_s_per_day'):
        rec['hours_per_model_year_run'] = rec['run_s_per_day'] * 365.25 / 3600
    if rec.get('total_s') and rec.get('days'):
        rec['hours_per_model_year_total'] = rec['total_s'] / (rec['days'] / 365.25) / 3600
    return rec


def gb(s):
    s = s.strip()
    return float(s[:-1]) if s.endswith('G') else (float(s) if s else None)


def timing_step(processes):
    recs = [dict(timing_of(RUNS['check']), name='check'), dict(timing_of(TIMING_REF), name='dam-test ranks16'),
            dict(timing_of(RUNS['ref']), name='snow-density-test ranks16 (shared node)')]
    tab = pd.DataFrame(recs)
    tab.to_csv(f'{products("tables")}/timing.csv', index=False)
    with open(f'{REPO}/configs/resources/vic-global-5arcmin.yaml') as fh:
        current = yaml.safe_load(fh)
    write_summary('timing', {'resources_file_wall_time': current.get('wall_time'), 'timing': recs})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=list(RESOURCES))
    ap.add_argument('--submit', action='store_true', help='submit the step as a Slurm job')
    ap.add_argument('--processes', type=int, default=1)
    a = ap.parse_args()
    if a.submit:
        return submit_step(a.step)
    {'nonrenewable': nonrenewable_step, 'balance': balance_step, 'dams': dams_step, 'cells': cells_step,
     'timing': timing_step}[a.step](a.processes)


if __name__ == '__main__':
    main()
