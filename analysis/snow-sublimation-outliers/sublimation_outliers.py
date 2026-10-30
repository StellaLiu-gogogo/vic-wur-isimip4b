#!/usr/bin/env python3
"""Rare snow sublimation outliers of VIC-WUR 39e21ff5 in the natural run (task T).

Question: why does the monthly OUT_SUB_SNOW (and so OUT_EVAP) of the natural run 1850-2021 have a few absurd values
(one cell in one month, up to 8.7e16 mm), with an equally absurd OUT_ENERGY_ERROR and a normal snow water equivalent,
and which cell-months must be masked (user, 2026-10-30: the outliers are masked, the model is not changed)?

Steps (every computation on a compute node):
  render-run   test run `jan1990` = January 1990 of the natural run again, from the same initial state (end state of
               chunk 1970-1989, dated 1990-01-01), with daily snow and energy-balance diagnostics; the VIC file is
               the rendered file of chunk 1990-2009 with the dates, the state output and the outputs changed (its
               forcing view and parameter files are read only)
  submit-run   submit the VIC job of the test run (login node: only sbatch)
  check        daily diagnostics of the test run at the outlier cell (50.042 N, 121.792 W) and every cell whose
               daily sublimation exceeds DAILY_LIMIT; the January total against the monthly value of the natural run
  scan         every monthly file of the natural run: cell-months by monthly sublimation and by |OUT_WATER_ERROR|
               (monthly mean), the candidate mask list and the largest values that stay unmasked

Writes to workdir/analysis/snow-sublimation-outliers/:
  runs/jan1990/{config,logs,output}/, runs/jan1990/run_record.yaml (contract exception, README)
  tables/   jan1990_cell_daily.csv, jan1990_cells_over_limit.csv, scan_by_year.csv, mask_cell_months.csv,
            largest_unmasked.csv
  logs/<step>_<slurm-job-id>/ and logs/run-jan1990_<slurm-job-id>/   job records

Usage:
  sublimation_outliers.py render-run | submit-run | check --submit | scan --submit
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
import yaml
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
TASK = 'snow-sublimation-outliers'
COMMIT = '39e21ff5015d01d9bc20407a8f50006831417aff'
RUN = 'runs/natural-run/ec-earth3-esm-1-1_historical_histsoc_default_historical__natural1850-2021'
TEMPLATE_CHUNK = '1990-2009'
CELL = (50.042, -121.792)                    # January 1990: monthly OUT_SUB_SNOW 6840 mm in the natural run
DAILY_LIMIT = 50.0                           # mm per day; a daily sublimation above it is listed by `check`
# Mask rule (README, 2026-10-30): a cell-month is masked when its monthly mean |OUT_WATER_ERROR| exceeds this value
WATER_ERROR_LIMIT = 1.0                      # mm (monthly mean of the daily water-balance error)
DAILY_VARS = ['OUT_SUB_SNOW', 'OUT_EVAP', 'OUT_SWE', 'OUT_SNOW_DEPTH', 'OUT_SNOW_COVER', 'OUT_SNOW_SURF_TEMP',
              'OUT_SNOW_PACK_TEMP', 'OUT_SNOWT_FBFLAG', 'OUT_SURFT_FBFLAG', 'OUT_SURF_TEMP', 'OUT_LATENT_SUB',
              'OUT_SENSIBLE', 'OUT_SNOW_FLUX', 'OUT_DELTACC', 'OUT_SNOW_MELT', 'OUT_SNOWF', 'OUT_PREC', 'OUT_AIR_TEMP',
              'OUT_WIND', 'OUT_REL_HUMID', 'OUT_WATER_ERROR', 'OUT_ENERGY_ERROR']
SCAN_LIMITS = {'OUT_SUB_SNOW': [100, 500, 1000, 1e4], 'OUT_WATER_ERROR': [0.5, 1, 10, 100]}
STEP_SBATCH = """#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=main
#SBATCH --time=04:00:00
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
/usr/bin/time -v python3 analysis/{task}/sublimation_outliers.py {step}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
VIC_SBATCH = """#!/bin/bash
# VIC-WUR test run `{label}` of analysis {task} (written by analysis/{task}/sublimation_outliers.py submit-run).
#SBATCH --job-name={task}-{label}
#SBATCH --partition={partition}
#SBATCH --nodes={nodes}
#SBATCH --ntasks={ntasks}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --time=03:00:00
#SBATCH --constraint={constraint}
#SBATCH --exclusive
#SBATCH --output={logs}/slurm-%j.out
#SBATCH --error={logs}/slurm-%j.err
set -uo pipefail
JOB_DIR={logs}/run-{label}_${{SLURM_JOB_ID}}
mkdir -p "$JOB_DIR"
mv {logs}/slurm-${{SLURM_JOB_ID}}.out {logs}/slurm-${{SLURM_JOB_ID}}.err "$JOB_DIR"/
RUN_DIR={run}
echo "test run {label} job ${{SLURM_JOB_ID}} host $(hostname) start $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# the initial state comes from another run: checked against the checksum recorded by that run before VIC starts
cd "$RUN_DIR"
sha256sum -c config/inputs.sha256 || {{ echo "input checksum mismatch"; exit 3; }}
set +u
source /etc/profile.d/z00_lmod.sh
module purge
{modules}
module -t list 2>&1 | sed 's/^/module: /'
set -u
export OMP_NUM_THREADS=${{SLURM_CPUS_PER_TASK}}
{launcher} {exe} -g "$RUN_DIR/config/vic_global.txt" > "$RUN_DIR/logs/vic_stdout_${{SLURM_JOB_ID}}.txt" 2>&1
rc=$?
echo "VIC exit code $rc at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit $rc
"""


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def products():
    return f'{workdir()}/analysis/{TASK}'


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def conda_base():
    return subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))


def sbatch(text, job_dir_of):
    """Submit on hold, keep the job file in the record directory, release. Returns the job ID."""
    r = subprocess.run(['sbatch', '--parsable', '--hold'], input=text, capture_output=True, text=True, check=True)
    job_id = r.stdout.strip().split(';')[0]
    d = job_dir_of(job_id); os.makedirs(d, exist_ok=True)
    with open(f'{d}/job.sbatch', 'w') as fh:
        fh.write(text)
    subprocess.run(['scontrol', 'release', job_id], check=True)
    print(f'submitted {job_id}; job record {d}/')
    return job_id


def submit_step(step, cpus=1, mem='16G'):
    logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    text = STEP_SBATCH.format(job=f'{TASK}-{step}', cpus=cpus, mem=mem, logs=logs, step=step, conda=conda_base(),
                              workdir=workdir(), repo=REPO, task=TASK)
    sbatch(text, lambda j: f'{logs}/{step}_{j}')


def manifest():
    with open(f'{workdir()}/{RUN}/run_manifest.json') as fh:
        return json.load(fh)


def year_dirs():
    """{year: chunk directory (workdir path) holding that year's output} of the natural run."""
    return {y: f'{workdir()}/{RUN}/{c["dir"]}' for c in manifest()['chunks']
            for y in range(c['start_year'], c['end_year'] + 1)}


# ----------------------------------------------------------------------------------------------- test run
def render_run(label='jan1990'):
    """Run directory of the test run: the VIC file of chunk 1990-2009 with these lines changed."""
    W = workdir(); run = f'{products()}/runs/{label}'
    if os.path.exists(run):
        sys.exit(f'{run} exists; a test run directory is never rendered again')
    m = manifest()
    chunk = next(c for c in m['chunks'] if c['id'] == TEMPLATE_CHUNK)
    att = [a for a in m['attempts'] if a.get('chunk') == TEMPLATE_CHUNK and a['status'] == 'completed'][-1]
    state = att['input_verification']['chunk_state']             # end state of 1970-1989 with its sha256
    template = f'{W}/{RUN}/{chunk["dir"]}/config/vic_global.txt'
    text = open(template).read()
    head, tail = text.split('# --- output', 1)
    rep = [(r'^ENDYEAR\s+\d+$', 'ENDYEAR                 1990'), (r'^ENDMONTH\s+\d+$', 'ENDMONTH                1'),
           (r'^STATENAME\s+.*$', '# no end state is written (test run)'),
           (r'^CONSTANTS\s+.*$', f'CONSTANTS               {run}/config/vic_constants.txt')]
    for pat, new in rep:
        head, n = re.subn(pat, new, head, flags=re.M)
        if n != 1:
            sys.exit(f'template line {pat} found {n} times')
    head, n = re.subn(r'^STATE(YEAR|MONTH|DAY|SEC)\s+.*\n', '', head, flags=re.M)
    if f'INIT_STATE              {W}/{RUN}/{state["path"]}' not in head:
        sys.exit('the template does not start from the recorded end state of chunk 1970-1989')
    for sub in ('config', 'logs', 'output'):
        os.makedirs(f'{run}/{sub}')
    head = f'# Test run `{label}` of analysis {TASK}, derived by analysis/{TASK}/sublimation_outliers.py from\n' \
           f'# {template} (end date, state output, outputs changed).\n' + head
    out = ['# --- output (daily snow and energy-balance diagnostics of the test) ' + '-' * 33,
           f'RESULT_DIR              {run}/output/', f'LOG_DIR                 {run}/logs/',
           'OUTFILE                 daily', 'AGGFREQ                 NDAYS 1', 'HISTFREQ                NYEARS 1',
           'OUT_FORMAT              NETCDF4', 'COMPRESS                2'] + [f'OUTVAR                  {v}' for v in DAILY_VARS]
    with open(f'{run}/config/vic_global.txt', 'w') as fh:
        fh.write(head + '\n'.join(out) + '\n')
    shutil.copyfile(f'{W}/{RUN}/{chunk["dir"]}/config/vic_constants.txt', f'{run}/config/vic_constants.txt')
    with open(f'{run}/config/inputs.sha256', 'w') as fh:
        fh.write(f'{state["sha256"]}  {W}/{RUN}/{state["path"]}\n')
    bm = json.load(open(f'{W}/builds/vic/{COMMIT}/build_manifest.json'))
    rec = {'label': label, 'analysis': TASK, 'status': 'rendered', 'rendered_at': utcnow(), 'model_commit': COMMIT,
           'executable_sha256': bm['executable']['sha256'], 'period': ['1990-01-01', '1990-01-31'],
           'init_state': {'path': f'{RUN}/{state["path"]}', 'sha256': state['sha256']},
           'template_config': os.path.relpath(template, W), 'forcing_view': f'{RUN}/{chunk["dir"]}/forcing (read only)',
           'attempts': []}
    with open(f'{run}/run_record.yaml', 'w') as fh:
        yaml.safe_dump(rec, fh, sort_keys=False)
    print(f'rendered {run}')


def submit_run(label='jan1990'):
    W = workdir(); run = f'{products()}/runs/{label}'; logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    rec = yaml.safe_load(open(f'{run}/run_record.yaml'))
    if rec['status'] != 'rendered':
        sys.exit(f'{label}: status {rec["status"]}, not submitted')
    res = yaml.safe_load(open(f'{REPO}/configs/resources/vic-global-5arcmin.yaml'))
    bm = json.load(open(f'{W}/builds/vic/{COMMIT}/build_manifest.json'))
    if [str(m) for m in res['modules']] != [str(m) for m in bm['runtime_modules']]:
        sys.exit('resources modules differ from the build runtime modules')
    text = VIC_SBATCH.format(task=TASK, label=label, partition=res['partition'], nodes=res['nodes'],
                             ntasks=res['ntasks'], cpus=res['cpus_per_task'], mem=res['mem'],
                             constraint=res['constraint'], run=run, logs=logs, launcher=res['launcher'],
                             modules='\n'.join(f'module load {m}' for m in res['modules']),
                             exe=f'{W}/builds/vic/{COMMIT}/{bm["executable"]["path"]}')
    job_id = sbatch(text, lambda j: f'{logs}/run-{label}_{j}')
    rec['status'] = 'submitted'
    rec['attempts'].append({'slurm_job_id': int(job_id), 'job_record': f'logs/run-{label}_{job_id}',
                            'submitted_at': utcnow()})
    with open(f'{run}/run_record.yaml', 'w') as fh:
        yaml.safe_dump(rec, fh, sort_keys=False)


# ------------------------------------------------------------------------------------------------ check
def nearest(ds, lat, lon):
    return int(np.argmin(np.abs(ds['lat'][:] - lat))), int(np.argmin(np.abs(ds['lon'][:] - lon)))


def values(var):
    a = np.asarray(var[:], 'f8')
    a[np.abs(a) > 1e30] = np.nan                                  # NetCDF fill value of VIC output
    return a


def check(label='jan1990'):
    run = f'{products()}/runs/{label}'; tab = f'{products()}/tables'; os.makedirs(tab, exist_ok=True)
    with Dataset(f'{run}/output/daily.1990-01-01.nc') as d:
        d.set_auto_mask(False)
        i, j = nearest(d, *CELL)
        dates = pd.date_range('1990-01-01', periods=len(d.dimensions['time']))
        cell = pd.DataFrame({v: np.asarray(d[v][:, i, j], 'f8') if d[v].ndim == 3 else
                             np.asarray(d[v][:, :, i, j], 'f8').tolist() for v in DAILY_VARS if v in d.variables},
                            index=dates)
        cell.to_csv(f'{tab}/{label}_cell_daily.csv')
        sub = values(d['OUT_SUB_SNOW'])
        t, r, c = np.where(sub > DAILY_LIMIT)
        rows = [{'date': dates[k].date(), 'lat': float(d['lat'][a]), 'lon': float(d['lon'][b]),
                 **{v: float(np.asarray(d[v][k, a, b])) for v in DAILY_VARS if v in d.variables and d[v].ndim == 3}}
                for k, a, b in zip(t, r, c)]
        pd.DataFrame(rows).to_csv(f'{tab}/{label}_cells_over_limit.csv', index=False)
        missing = [v for v in DAILY_VARS if v not in d.variables]
    with Dataset(f'{year_dirs()[1990]}/output/monthly.1990-01.nc') as m:
        m.set_auto_mask(False)
        ref = float(m['OUT_SUB_SNOW'][0, i, j])
    print(f'cell {CELL}: daily sublimation of the test run summed over January {cell["OUT_SUB_SNOW"].sum():.6g} mm, '
          f'monthly value of the natural run {ref:.6g} mm (reproduced: {np.isclose(cell["OUT_SUB_SNOW"].sum(), ref)})')
    print(f'cells with a daily sublimation above {DAILY_LIMIT} mm: {len(rows)}; OUTVARs not written: {missing}')
    with pd.option_context('display.width', 250, 'display.max_columns', 30):
        print(cell[cell['OUT_SUB_SNOW'].abs() > 1].T if (cell['OUT_SUB_SNOW'].abs() > 1).any() else cell.head())


# ------------------------------------------------------------------------------------------------- scan
def scan_year(args):
    """Counts and the cell-months above the limits in one monthly file of the natural run."""
    year, ydir = args
    out = {'year': year}; cells = []
    with Dataset(f'{ydir}/output/monthly.{year}-01.nc') as m:
        m.set_auto_mask(False)
        lat, lon = np.asarray(m['lat'][:]), np.asarray(m['lon'][:])
        sub, err = values(m['OUT_SUB_SNOW']), values(m['OUT_WATER_ERROR'])
        eng, evap = values(m['OUT_ENERGY_ERROR']), values(m['OUT_EVAP'])
        swe = values(m['OUT_SWE'])
    for var, a in (('OUT_SUB_SNOW', sub), ('OUT_WATER_ERROR', np.abs(err))):
        for lim in SCAN_LIMITS[var]:
            out[f'{var}>{lim:g}'] = int(np.nansum(a > lim))
        out[f'{var}_max'] = float(np.nanmax(a))
    masked = np.abs(err) > WATER_ERROR_LIMIT
    for t, i, j in zip(*np.where(masked)):
        cells.append({'year': year, 'month': int(t) + 1, 'lat': float(lat[i]), 'lon': float(lon[j]),
                      'OUT_WATER_ERROR': float(err[t, i, j]), 'OUT_SUB_SNOW': float(sub[t, i, j]),
                      'OUT_EVAP': float(evap[t, i, j]), 'OUT_ENERGY_ERROR': float(eng[t, i, j]),
                      'OUT_SWE': float(swe[t, i, j])})
    keep = np.where(masked, np.nan, sub)                          # largest sublimation that stays unmasked
    k = np.unravel_index(np.nanargmax(keep), keep.shape)
    big = {'year': year, 'month': int(k[0]) + 1, 'lat': float(lat[k[1]]), 'lon': float(lon[k[2]]),
           'OUT_SUB_SNOW': float(keep[k]), 'OUT_WATER_ERROR': float(err[k]), 'OUT_ENERGY_ERROR': float(eng[k])}
    out['OUT_ENERGY_ERROR_abs_p99.99'] = float(np.nanpercentile(np.abs(eng), 99.99))
    print(year, 'masked', len(cells), flush=True)
    return out, cells, big


def scan():
    tab = f'{products()}/tables'; os.makedirs(tab, exist_ok=True)
    with Pool(int(os.environ.get('SLURM_CPUS_PER_TASK', '1'))) as p:
        res = p.map(scan_year, sorted(year_dirs().items()), chunksize=1)
    pd.DataFrame([r[0] for r in res]).to_csv(f'{tab}/scan_by_year.csv', index=False)
    pd.DataFrame([c for r in res for c in r[1]]).to_csv(f'{tab}/mask_cell_months.csv', index=False)
    big = pd.DataFrame([r[2] for r in res]).sort_values('OUT_SUB_SNOW', ascending=False)
    big.to_csv(f'{tab}/largest_unmasked.csv', index=False)
    print(f'cell-months masked (|OUT_WATER_ERROR| > {WATER_ERROR_LIMIT} mm): {sum(len(r[1]) for r in res)}')
    print('largest unmasked monthly sublimation:'); print(big.head(10).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=['render-run', 'submit-run', 'check', 'scan'])
    ap.add_argument('--submit', action='store_true', help='run the step as a Slurm job (check, scan)')
    a = ap.parse_args()
    if a.step in ('render-run', 'submit-run'):
        {'render-run': render_run, 'submit-run': submit_run}[a.step]()
    elif a.submit:
        submit_step(a.step, cpus=8 if a.step == 'scan' else 1, mem='96G' if a.step == 'scan' else '32G')
    else:
        {'check': check, 'scan': scan}[a.step]()


if __name__ == '__main__':
    main()
