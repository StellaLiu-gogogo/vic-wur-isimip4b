#!/usr/bin/env python3
"""Short global VIC-WUR test of dams without service cells (Nservice = 0), for open decision D19.

Question: does VIC-WUR 39e21ff5 run with global dams whose Nservice is 0 and whose service map is empty, and do
those dams then operate without demand (release planned from the mean inflow, Hanasaki et al. 2006)?

Steps (every computation on a compute node):
  prepare        test dam file = copy of the candidate dam file (same 7 925 dams in the same order) in which the
                 global dams whose GDW purposes are known and include neither irrigation nor water supply get
                 Nservice = 0 and an empty service/service_fraction slice; two run directories, `control`
                 (candidate dam file) and `test` (test dam file), 2016-01-01 to 2016-12-31, both started from the
                 end state of the smoke run 2015 (dated 2016-01-01); VIC files derived from the rendered
                 configuration of the smoke run 2011-2020 (its forcing view covers 2016, read only)
  submit-runs    submit the two VIC jobs (login node: only sbatch)
  check          read the logs and outputs of both runs, write tables and figures

Writes to workdir/analysis/dam-nservice-test/:
  inputs/   dam_parameters_nservice-zero.nc, dam_selection.csv, inputs.yaml (checksums)
  runs/<control|test>/{config,logs,output}/, runs/<label>/run_record.yaml (contract exception, README);
            the Slurm job of a run is kept in logs/run-<label>_<slurm-job-id>/
  tables/   checks.csv, selected_dams_operation.csv, discharge_change_largest.csv
  figures/  release_examples.png, discharge_change_map.png, op_release_flatness.png
  logs/<step>_<slurm-job-id>/   job records of prepare and check

Usage:
  nservice_test.py prepare --submit | nservice_test.py submit-runs | nservice_test.py check --submit
"""
import argparse, datetime, hashlib, json, os, re, shutil, subprocess, sys

import numpy as np
import pandas as pd
import yaml
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
TASK = 'dam-nservice-test'
COMMIT = '39e21ff5015d01d9bc20407a8f50006831417aff'
PARAM_SET = 'parameters/candidates/vic-global-5arcmin-version-a'
DAM_FILE = f'{PARAM_SET}/dams/vic_global_5min_dam_parameters_t3-extended-merged.nc'
SMOKE = 'runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke'
TEMPLATE_RUN = f'{SMOKE}2011-2020'                       # rendered config, forcing view 2011-2020
INIT_STATE = f'{SMOKE}2015/states/state.20160101_00000.nc'
GDW_TABLES = ('/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/candidates/dams/'
              'dam_parameter_candidate_v1/T3_extended')
YEAR = 2016
TEST_FILE_NAME = 'dam_parameters_nservice-zero.nc'
SUPPLY_MAIN_USE = {'Irrigation', 'Water supply'}
USE_FIELDS = ['USE_IRRI', 'USE_ELEC', 'USE_SUPP', 'USE_FCON', 'USE_RECR', 'USE_NAVI', 'USE_FISH', 'USE_PCON',
              'USE_LIVE', 'USE_OTHR']
DAILY_VARS = ['OUT_DISCHARGE', 'OUT_GDAM_INFLOW', 'OUT_GDAM_DEMAND', 'OUT_GDAM_STORAGE', 'OUT_GDAM_RELEASE',
              'OUT_GDAM_OP_RELEASE']
MONTHLY_VARS = ['OUT_DISCHARGE', 'OUT_LDAM_STORAGE  * * * AGG_TYPE_AVG', 'OUT_LDAM_RELEASE', 'OUT_WI_DAM_SECT',
                'OUT_WI_SURF_SECT', 'OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_WATER_ERROR']
STEP_SBATCH = """#!/bin/bash
#SBATCH --job-name={job}
#SBATCH --partition=main
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
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
/usr/bin/time -v python3 analysis/{task}/nservice_test.py {step}
echo "end $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
VIC_SBATCH = """#!/bin/bash
# VIC-WUR test run `{label}` of analysis {task} (written by analysis/{task}/nservice_test.py submit-runs).
#SBATCH --job-name={task}-{label}
#SBATCH --partition={partition}
#SBATCH --nodes={nodes}
#SBATCH --ntasks={ntasks}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --time={hours:02d}:00:00
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
# inputs that differ between the runs or come from another run: checked before VIC starts
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


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


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


def submit_step(step, mem='16G'):
    logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    text = STEP_SBATCH.format(job=f'{TASK}-{step}', mem=mem, logs=logs, step=step, conda=conda_base(),
                              workdir=workdir(), repo=REPO, task=TASK)
    sbatch(text, lambda j: f'{logs}/{step}_{j}')


# ---------------------------------------------------------------------------------------------- selection
def dam_cells():
    """Model dams with their grid cell (row, col), type and capacity."""
    with Dataset(f'{workdir()}/{DAM_FILE}') as ds:
        lat = ds['lat'][:].astype(float); lon = ds['lon'][:].astype(float)
        id_map = np.ma.filled(ds['id_map'][:], -1).astype(np.int64)
        d = pd.DataFrame({'dam_index': np.arange(ds.dimensions['dam_class'].size),
                          'cell_id': ds['id'][:].astype(np.int64),
                          'type': np.where(ds['type'][:] == 1, 'global', 'local'),
                          'year': ds['year'][:].astype(int), 'capacity_hm3': ds['capacity'][:].astype(float),
                          'Nservice': ds['Nservice'][:].astype(int)})
    flat = id_map.ravel(); order = np.argsort(flat); k = np.searchsorted(flat[order], d.cell_id)
    r, c = np.unravel_index(order[k], id_map.shape)
    return d.assign(row=r, col=c, lat=lat[r], lon=lon[c]), lat, lon


def purposes(lat, lon):
    """Purpose flags per (row, col, type) from the unmerged GDW records of the T3_extended tier."""
    frames = []
    for name, t in (('globalDams.csv', 'global'), ('localDams.csv', 'local')):
        f = pd.read_csv(f'{GDW_TABLES}/{name}', low_memory=False, dtype=str).fillna('')
        f['type'] = t
        frames.append(f)
    g = pd.concat(frames, ignore_index=True)
    la = pd.to_numeric(g.MODEL_LAT_DD).to_numpy(); lo = pd.to_numeric(g.MODEL_LONG_DD).to_numpy()
    g['row'] = np.abs(lat[None, :] - la[:, None]).argmin(axis=1)
    g['col'] = np.abs(lon[None, :] - lo[:, None]).argmin(axis=1)
    use = g[USE_FIELDS].apply(lambda s: s.str.strip() != '')
    g['supply'] = use.USE_IRRI | use.USE_SUPP | g.MAIN_USE.isin(SUPPLY_MAIN_USE)
    g['known'] = use.any(axis=1) | (g.MAIN_USE.str.strip() != '')
    g['hydro'] = use.USE_ELEC | (g.MAIN_USE == 'Hydroelectricity')
    agg = g.groupby(['row', 'col', 'type']).agg(gdw_records=('GDW_ID', 'size'), supply=('supply', 'any'),
                                                known=('known', 'any'), hydro=('hydro', 'any'),
                                                main_use=('MAIN_USE', lambda s: ';'.join(sorted(set(s) - {''}))),
                                                names=('DAM_NAME', lambda s: ';'.join(sorted(set(s) - {''}))[:80]))
    return agg.reset_index()


def prepare():
    out = products(); inp = f'{out}/inputs'; os.makedirs(inp, exist_ok=True)
    d, lat, lon = dam_cells()
    d = d.merge(purposes(lat, lon), on=['row', 'col', 'type'], how='left')
    d[['supply', 'known', 'hydro']] = d[['supply', 'known', 'hydro']].fillna(False).astype(bool)
    d['category'] = np.select([d.type == 'local', ~d.known, d.supply], ['local (not changed)', 'global, purpose unknown',
                                                                       'global, irrigation or water supply'],
                              'global, no supply purpose -> Nservice 0')
    d['selected'] = d.category == 'global, no supply purpose -> Nservice 0'
    d['gdw_matched'] = d.gdw_records.notna()
    print(f'model dams without a GDW record in their cell: {int((~d.gdw_matched).sum())}')
    d.to_csv(f'{inp}/dam_selection.csv', index=False)
    print(d.groupby('category').agg(n=('dam_index', 'size'), capacity_km3=('capacity_hm3', lambda x: x.sum() / 1000))
          .round(1).to_string())

    # test dam file
    src = f'{workdir()}/{DAM_FILE}'; dst = f'{inp}/{TEST_FILE_NAME}'
    shutil.copyfile(src, dst)
    with Dataset(dst, 'r+') as ds:
        ns = ds['Nservice'][:].copy()
        for j in d.index[d.selected]:
            s = np.ma.getmaskarray(ds['service'][j, :, :])
            rows, cols = np.where(~s)
            if len(rows):
                r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
                ds['service'][j, r0:r1, c0:c1] = np.ma.masked_all((r1 - r0, c1 - c0), dtype='i4')
                ds['service_fraction'][j, r0:r1, c0:c1] = np.ma.masked_all((r1 - r0, c1 - c0), dtype='f8')
            ns[j] = 0
        ds['Nservice'][:] = ns
        ds.setncattr('history', ds.getncattr('history') + f'; {datetime.date.today()}: analysis {TASK}: Nservice 0 '
                     f'and empty service map for {int(d.selected.sum())} global dams without a supply purpose '
                     '(test file, not a parameter-set file)')
    # verification of the test file against the candidate file
    bad = []
    with Dataset(dst) as t, Dataset(src) as s:
        for j in range(len(d)):
            n_t = int((~np.ma.getmaskarray(t['service'][j, :, :])).sum()) if d.selected[j] or j % 500 == 0 else None
            if d.selected[j]:
                if t['Nservice'][j] != 0 or n_t != 0:
                    bad.append(j)
            elif n_t is not None:
                if t['Nservice'][j] != s['Nservice'][j] or n_t != int((~np.ma.getmaskarray(s['service'][j, :, :])).sum()):
                    bad.append(j)
        for v in ('id', 'type', 'year', 'capacity', 'inflow_fraction', 'id_map'):
            if not np.array_equal(np.ma.filled(t[v][:], -9), np.ma.filled(s[v][:], -9)):
                bad.append(v)
    if bad:
        sys.exit(f'test file check failed: {bad[:10]}')
    info = {'dam_file_candidate': {'path': DAM_FILE, 'sha256': sha256(src)},
            'dam_file_test': {'path': os.path.relpath(dst, workdir()), 'sha256': sha256(dst),
                              'n_dams_nservice_zero': int(d.selected.sum())},
            'init_state': {'path': INIT_STATE, 'sha256': sha256(f'{workdir()}/{INIT_STATE}')},
            'template_config': f'{TEMPLATE_RUN}/config/vic_global.txt'}
    with open(f'{inp}/inputs.yaml', 'w') as fh:
        yaml.safe_dump(info, fh, sort_keys=False)
    for label, dam in (('control', src), ('test', dst)):
        render(label, dam, info)
    print('done')


# ---------------------------------------------------------------------------------------------- runs
def render(label, dam, info):
    """Run directory of one test run; the VIC file is the smoke 2011-2020 file with these lines changed."""
    W = workdir(); run = f'{products()}/runs/{label}'
    if os.path.exists(run):
        sys.exit(f'{run} exists; a test run directory is never rendered again')
    for sub in ('config', 'logs', 'output'):
        os.makedirs(f'{run}/{sub}')
    text = open(f'{W}/{TEMPLATE_RUN}/config/vic_global.txt').read()
    head, tail = text.split('# --- output', 1)
    rep = [
        (r'^STARTYEAR\s+\d+$', f'STARTYEAR               {YEAR}'), (r'^ENDYEAR\s+\d+$', f'ENDYEAR                 {YEAR}'),
        (r'^# cold start: no INIT_STATE.*$',
         f'# warm start from the end state of the smoke run 2015 (dated {YEAR}-01-01)\n'
         f'INIT_STATE              {W}/{INIT_STATE}'),
        (r'^STATENAME\s+.*$', '# no end state is written (test run)'),
        (r'^STATE(YEAR|MONTH|DAY|SEC)\s+.*\n', ''),
        (r'^CONSTANTS\s+.*$', f'CONSTANTS               {run}/config/vic_constants.txt'),
        (r'^DAMS_PARAMETERS\s+.*$', f'DAMS_PARAMETERS         {dam}'),
    ]
    for pat, new in rep:
        head, n = re.subn(pat, new, head, flags=re.M)
        if n != 1 and not pat.startswith('^STATE('):
            sys.exit(f'template line {pat} found {n} times')
    head = f'# Test run `{label}` of analysis {TASK}, derived by analysis/{TASK}/nservice_test.py from\n' \
           f'# {W}/{TEMPLATE_RUN}/config/vic_global.txt (dates, initial state, dam file, outputs changed).\n' + head
    out = ['# --- output (reduced to the variables of the test) ' + '-' * 49,
           f'RESULT_DIR              {run}/output/', f'LOG_DIR                 {run}/logs/',
           'OUTFILE                 daily', 'AGGFREQ                 NDAYS 1', 'HISTFREQ                NYEARS 1',
           'OUT_FORMAT              NETCDF4', 'COMPRESS                2'] + [f'OUTVAR                  {v}' for v in DAILY_VARS] + \
          ['OUTFILE                 monthly', 'AGGFREQ                 NMONTHS 1', 'HISTFREQ                NYEARS 1',
           'OUT_FORMAT              NETCDF4', 'COMPRESS                2'] + [f'OUTVAR                  {v}' for v in MONTHLY_VARS]
    with open(f'{run}/config/vic_global.txt', 'w') as fh:
        fh.write(head + '\n'.join(out) + '\n')
    shutil.copyfile(f'{W}/{TEMPLATE_RUN}/config/vic_constants.txt', f'{run}/config/vic_constants.txt')
    with open(f'{run}/config/inputs.sha256', 'w') as fh:
        fh.write(f'{info["dam_file_test" if label == "test" else "dam_file_candidate"]["sha256"]}  {dam}\n')
        fh.write(f'{info["init_state"]["sha256"]}  {W}/{INIT_STATE}\n')
    build = f'{W}/builds/vic/{COMMIT}'
    bm = json.load(open(f'{build}/build_manifest.json'))
    rec = {'label': label, 'analysis': TASK, 'status': 'rendered', 'rendered_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'model_commit': COMMIT, 'executable_sha256': bm['executable']['sha256'], 'period': [f'{YEAR}-01-01', f'{YEAR}-12-31'],
           'dam_file': os.path.relpath(dam, W), 'init_state': INIT_STATE, 'template_config': f'{TEMPLATE_RUN}/config/vic_global.txt',
           'forcing_view': f'{TEMPLATE_RUN}/forcing (read only)', 'attempts': []}
    with open(f'{run}/run_record.yaml', 'w') as fh:
        yaml.safe_dump(rec, fh, sort_keys=False)


def vic_job_text(label, run):
    """Slurm job of one test run from the resources of the campaign runs (configs/resources)."""
    W = workdir(); logs = f'{products()}/logs'
    res = yaml.safe_load(open(f'{REPO}/configs/resources/vic-global-5arcmin.yaml'))
    build = f'{W}/builds/vic/{COMMIT}'
    bm = json.load(open(f'{build}/build_manifest.json'))
    if [str(m) for m in res['modules']] != [str(m) for m in bm['runtime_modules']]:
        sys.exit('resources modules differ from the build runtime modules')
    hours = int(np.ceil(res['wall_time']['setup_hours'] + res['wall_time']['hours_per_model_year']))
    return VIC_SBATCH.format(task=TASK, label=label, partition=res['partition'], nodes=res['nodes'],
                             ntasks=res['ntasks'], cpus=res['cpus_per_task'], mem=res['mem'], hours=hours,
                             constraint=res['constraint'], run=run, logs=logs, launcher=res['launcher'],
                             modules='\n'.join(f'module load {m}' for m in res['modules']),
                             exe=f'{build}/{bm["executable"]["path"]}')


def submit_runs():
    logs = f'{products()}/logs'; os.makedirs(logs, exist_ok=True)
    for label in ('control', 'test'):
        run = f'{products()}/runs/{label}'
        rec = yaml.safe_load(open(f'{run}/run_record.yaml'))
        if rec['status'] != 'rendered':
            print(f'{label}: status {rec["status"]}, not submitted'); continue
        job_id = sbatch(vic_job_text(label, run), lambda j: f'{logs}/run-{label}_{j}')
        rec['status'] = 'submitted'
        rec['attempts'].append({'slurm_job_id': int(job_id), 'job_record': f'logs/run-{label}_{job_id}',
                                'submitted_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})
        with open(f'{run}/run_record.yaml', 'w') as fh:
            yaml.safe_dump(rec, fh, sort_keys=False)


# ---------------------------------------------------------------------------------------------- check
def _plt():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.alpha': 0.3, 'savefig.dpi': 150})
    return plt


def at_cells(path, var, rows, cols, block=31):
    """Values of a (time, lat, lon) output variable at the given cells, read in time blocks."""
    with Dataset(path) as ds:
        v = ds[var]; nt = v.shape[0]; out = np.empty((nt, len(rows)), dtype='f8')
        for t0 in range(0, nt, block):
            a = np.ma.filled(v[t0:t0 + block, :, :].astype('f8'), np.nan)
            out[t0:t0 + block] = a[:, rows, cols]
    return out


def output_grid_rows(path, lat_dam, lon_dam):
    """Output (row, col) of dam cells (the output lat axis may run the other way)."""
    with Dataset(path) as ds:
        lat_out = ds['lat'][:]; lon_out = ds['lon'][:]
    r = np.abs(lat_out[None, :] - lat_dam[:, None]).argmin(axis=1)
    c = np.abs(lon_out[None, :] - lon_dam[:, None]).argmin(axis=1)
    if np.abs(lat_out[r] - lat_dam).max() > 0.01 or np.abs(lon_out[c] - lon_dam).max() > 0.01:
        sys.exit('output grid does not match the dam cells')
    return r, c


def check():
    out = products(); tabd = f'{out}/tables'; figd = f'{out}/figures'
    os.makedirs(tabd, exist_ok=True); os.makedirs(figd, exist_ok=True)
    plt = _plt()
    sel = pd.read_csv(f'{out}/inputs/dam_selection.csv')
    checks = []
    runs = {}
    for label in ('control', 'test'):
        run = f'{out}/runs/{label}'
        rec = yaml.safe_load(open(f'{run}/run_record.yaml'))
        att = rec['attempts'][-1]
        jrec = f'{out}/{att["job_record"]}'
        sl = open(f'{jrec}/slurm-{att["slurm_job_id"]}.out').read() if os.path.exists(f'{jrec}/slurm-{att["slurm_job_id"]}.out') else ''
        m = re.search(r'VIC exit code (\d+) at (\S+)', sl)
        att['vic_exit_code'] = int(m.group(1)) if m else None
        att['ended_at'] = m.group(2) if m else None
        rec['status'] = 'completed' if m and m.group(1) == '0' else 'failed'
        with open(f'{run}/run_record.yaml', 'w') as fh:
            yaml.safe_dump(rec, fh, sort_keys=False)
        checks.append({'run': label, 'check': 'VIC exit code', 'value': att['vic_exit_code']})
        logs = sorted(os.listdir(f'{run}/logs'))
        vic_logs = [f for f in logs if f.startswith('vic.log') or f.startswith('vic_stdout')]
        text = ''.join(open(f'{run}/logs/{f}', errors='replace').read() for f in vic_logs)
        checks += [
            {'run': label, 'check': 'VIC log files', 'value': ';'.join(vic_logs)},
            {'run': label, 'check': '[ERROR] lines', 'value': len(re.findall(r'\[ERROR\]', text))},
            {'run': label, 'check': '[WARN] lines from the dams or water-use plugin',
             'value': len(re.findall(r'\[WARN\][^\n]*plugins/(dams|wateruse)/', text))},
            {'run': label, 'check': '"servicing cells were not found" warnings',
             'value': len(re.findall('servicing cells were not found', text))},
            {'run': label, 'check': '[WARN] lines (all)', 'value': len(re.findall(r'\[WARN\]', text))},
            {'run': label, 'check': 'finished (log mentions "Finished" or "Completed")',
             'value': bool(re.search(r'Finished|Completed|completed', text))},
            {'run': label, 'check': 'daily output', 'value': os.path.exists(f'{run}/output/daily.{YEAR}-01-01.nc')},
        ]
        runs[label] = run
    d_path = {k: f'{v}/output/daily.{YEAR}-01-01.nc' for k, v in runs.items()}
    m_path = {k: f'{v}/output/monthly.{YEAR}-01.nc' for k, v in runs.items()}
    g = sel[sel.type == 'global'].copy()
    rows, cols = output_grid_rows(d_path['test'], g.lat.to_numpy(), g.lon.to_numpy())
    series = {}
    for label in runs:
        for v in ('OUT_GDAM_INFLOW', 'OUT_GDAM_DEMAND', 'OUT_GDAM_STORAGE', 'OUT_GDAM_RELEASE', 'OUT_GDAM_OP_RELEASE'):
            series[(label, v)] = at_cells(d_path[label], v, rows, cols)
    days = series[('test', 'OUT_GDAM_INFLOW')].shape[0]
    month = pd.date_range(f'{YEAR}-01-01', periods=days, freq='D').month.to_numpy()
    rowsum = []
    for k, (i, r) in enumerate(g.iterrows()):
        rec = {'dam_index': r.dam_index, 'selected': r.selected, 'category': r.category, 'capacity_hm3': r.capacity_hm3,
               'names': r.names, 'lat': r.lat, 'lon': r.lon}
        for label in runs:
            inflow = series[(label, 'OUT_GDAM_INFLOW')][:, k]; rel = series[(label, 'OUT_GDAM_RELEASE')][:, k]
            dem = series[(label, 'OUT_GDAM_DEMAND')][:, k]; sto = series[(label, 'OUT_GDAM_STORAGE')][:, k]
            op = series[(label, 'OUT_GDAM_OP_RELEASE')][:, k]
            on = np.isfinite(rel) & (np.abs(np.nan_to_num(rel)) + np.abs(np.nan_to_num(sto)) > 0)
            rec[f'{label}_operating_days'] = int(on.sum())
            rec[f'{label}_demand_hm3'] = float(np.nansum(dem))
            rec[f'{label}_inflow_hm3'] = float(np.nansum(inflow))
            rec[f'{label}_release_hm3'] = float(np.nansum(rel))
            rec[f'{label}_storage_change_hm3'] = float(sto[on][-1] - sto[on][0]) if on.any() else 0.0
            opm = pd.Series(op).groupby(month).mean()
            opm = opm[opm > 0]                         # months after the first operation of 2016
            rec[f'{label}_op_release_cv_over_months'] = float(opm.std() / opm.mean()) if len(opm) > 1 and opm.mean() > 0 else np.nan
            # daily balance of the operating days after the first: storage(t) - storage(t-1) = inflow(t) - release(t)
            if on.sum() > 2:
                idx = np.where(on)[0][1:]
                err = (sto[idx] - sto[idx - 1]) - (inflow[idx] - rel[idx])
                rec[f'{label}_balance_max_abs_hm3'] = float(np.nanmax(np.abs(err)))
            else:
                rec[f'{label}_balance_max_abs_hm3'] = np.nan
        rec['control_demand_share_of_inflow'] = rec['control_demand_hm3'] / rec['control_inflow_hm3'] \
            if rec['control_inflow_hm3'] > 0 else np.nan
        rowsum.append(rec)
    op = pd.DataFrame(rowsum)
    op.to_csv(f'{tabd}/selected_dams_operation.csv', index=False)
    s = op[op.selected]
    checks += [
        {'run': 'test', 'check': 'Nservice-0 dams', 'value': len(s)},
        {'run': 'test', 'check': 'Nservice-0 dams operating in 2016', 'value': int((s.test_operating_days > 0).sum())},
        {'run': 'test', 'check': 'Nservice-0 dams with demand > 0 (expected 0)', 'value': int((s.test_demand_hm3 > 0).sum())},
        {'run': 'control', 'check': 'the same dams with demand > 0 in the control', 'value': int((s.control_demand_hm3 > 0).sum())},
        {'run': 'test', 'check': 'median CV of the planned release over operating months, Nservice-0 dams',
         'value': round(float(s.test_op_release_cv_over_months.median()), 4)},
        {'run': 'control', 'check': 'median CV of the planned release over operating months, same dams',
         'value': round(float(s.control_op_release_cv_over_months.median()), 4)},
        {'run': 'test', 'check': 'Nservice-0 dams whose control demand is >= 10 % of their inflow',
         'value': int((s.control_demand_share_of_inflow >= 0.1).sum())},
        {'run': 'test', 'check': 'median CV of the planned release, those dams, test',
         'value': round(float(s[s.control_demand_share_of_inflow >= 0.1].test_op_release_cv_over_months.median()), 4)},
        {'run': 'control', 'check': 'median CV of the planned release, those dams, control',
         'value': round(float(s[s.control_demand_share_of_inflow >= 0.1].control_op_release_cv_over_months.median()), 4)},
        {'run': 'test', 'check': 'largest daily storage balance error of Nservice-0 dams (hm3)',
         'value': float(s.test_balance_max_abs_hm3.max())},
        {'run': 'test', 'check': 'other global dams: demand differs from control (count)',
         'value': int((~np.isclose(op[~op.selected].test_demand_hm3, op[~op.selected].control_demand_hm3,
                                   rtol=1e-6, atol=1e-9)).sum())},
    ]

    # discharge change
    with Dataset(m_path['control']) as a, Dataset(m_path['test']) as b:
        qa = np.ma.filled(a['OUT_DISCHARGE'][:].astype('f8'), np.nan); qb = np.ma.filled(b['OUT_DISCHARGE'][:].astype('f8'), np.nan)
        lat_o = a['lat'][:]; lon_o = a['lon'][:]
        wd = {k: np.nansum(np.ma.filled(x['OUT_WITHDRAWN'][:].astype('f8'), np.nan)) for k, x in (('control', a), ('test', b))}
    mean_a, mean_b = np.nanmean(qa, 0), np.nanmean(qb, 0)
    low_a, low_b = np.nanmin(qa, 0), np.nanmin(qb, 0)
    rel_mean = (mean_b - mean_a) / np.where(mean_a > 1, mean_a, np.nan)
    rel_low = (low_b - low_a) / np.where(low_a > 1, low_a, np.nan)
    checks += [
        {'run': 'test vs control', 'check': 'cells with annual mean discharge > 1 m3/s changed by more than 1 %',
         'value': int(np.nansum(np.abs(rel_mean) > 0.01))},
        {'run': 'test vs control', 'check': 'cells with lowest monthly discharge > 1 m3/s changed by more than 5 %',
         'value': int(np.nansum(np.abs(rel_low) > 0.05))},
        {'run': 'test vs control', 'check': 'global withdrawal sum of monthly OUT_WITHDRAWN, test / control',
         'value': round(wd['test'] / wd['control'], 5) if wd['control'] else np.nan},
    ]
    diff = np.nan_to_num(np.abs(mean_b - mean_a)).ravel()
    top = np.argsort(diff)[::-1][:30]
    r_, c_ = np.unravel_index(top, mean_a.shape)
    pd.DataFrame({'lat': lat_o[r_], 'lon': lon_o[c_], 'mean_control_m3s': mean_a[r_, c_], 'mean_test_m3s': mean_b[r_, c_],
                  'min_month_control_m3s': low_a[r_, c_], 'min_month_test_m3s': low_b[r_, c_]}) \
        .round(2).to_csv(f'{tabd}/discharge_change_largest.csv', index=False)
    pd.DataFrame(checks).to_csv(f'{tabd}/checks.csv', index=False)
    print(pd.DataFrame(checks).to_string())

    # figures
    ex = pd.concat([s[s.test_operating_days > 100].nlargest(3, 'capacity_hm3'),
                    s[(s.test_operating_days > 100) & (s.control_demand_share_of_inflow >= 0.1)].nlargest(3, 'capacity_hm3')])
    fig, axs = plt.subplots(len(ex), 1, figsize=(11, 2.3 * max(len(ex), 1)), squeeze=False)
    t = pd.date_range(f'{YEAR}-01-01', periods=days, freq='D')
    for ax, (_, r) in zip(axs[:, 0], ex.iterrows()):
        k = int(np.where(g.dam_index.to_numpy() == r.dam_index)[0][0])
        ax.plot(t, series[('test', 'OUT_GDAM_INFLOW')][:, k], color='0.6', lw=0.8, label='inflow (test)')
        ax.plot(t, series[('control', 'OUT_GDAM_RELEASE')][:, k], color='#1f77b4', lw=1, label='release, control (with service)')
        ax.plot(t, series[('test', 'OUT_GDAM_RELEASE')][:, k], color='#d62728', lw=1, label='release, test (Nservice 0)')
        nm = r.names if isinstance(r.names, str) and r.names else 'unnamed dam'
        ax.set_title(f'{nm} ({r.capacity_hm3:,.0f} hm3; control demand {r.control_demand_share_of_inflow:.0%} of inflow)',
                     loc='left', fontsize=9); ax.set_ylabel('hm3/day')
        ax.plot(t, series[('control', 'OUT_GDAM_OP_RELEASE')][:, k], color='#1f77b4', lw=0.8, ls='--',
                label='planned release, control')
        ax.plot(t, series[('test', 'OUT_GDAM_OP_RELEASE')][:, k], color='#d62728', lw=0.8, ls='--',
                label='planned release, test')
    axs[0, 0].legend(fontsize=7, loc='upper right')
    fig.tight_layout(); fig.savefig(f'{figd}/release_examples.png'); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4.5))
    s10 = s[s.control_demand_share_of_inflow >= 0.1]
    ax.hist([s10.control_op_release_cv_over_months.dropna(), s10.test_op_release_cv_over_months.dropna()], bins=30,
            label=['control (with service)', 'test (Nservice 0)'])
    ax.set_xlabel('coefficient of variation of the planned release over the operating months')
    ax.set_ylabel('dams'); ax.legend(fontsize=8)
    ax.set_title(f'Nservice-0 dams whose control demand is >= 10 % of inflow ({len(s10)}):\n'
                 'month-to-month variation of the planned release after the first operation', loc='left', fontsize=9)
    fig.tight_layout(); fig.savefig(f'{figd}/op_release_flatness.png'); plt.close(fig)

    import cartopy.crs as ccrs
    fig = plt.figure(figsize=(14, 7))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson()); ax.set_global(); ax.coastlines(linewidth=0.3)
    m = np.abs(rel_low) > 0.05
    rr, cc = np.where(m)
    sc = ax.scatter(lon_o[cc], lat_o[rr], c=np.clip(rel_low[rr, cc] * 100, -100, 100), s=1.5, cmap='RdBu',
                    vmin=-100, vmax=100, transform=ccrs.PlateCarree())
    fig.colorbar(sc, ax=ax, shrink=0.6, label='change of the lowest monthly discharge, test vs control (%)')
    ax.set_title(f'Cells (> 1 m3/s) whose lowest monthly discharge in {YEAR} changes by more than 5 % '
                 f'when {len(s)} dams have Nservice 0', loc='left', fontsize=9)
    fig.tight_layout(); fig.savefig(f'{figd}/discharge_change_map.png'); plt.close(fig)
    print('done')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=['prepare', 'submit-runs', 'check'])
    ap.add_argument('--submit', action='store_true', help='run the step as a Slurm job (prepare, check)')
    a = ap.parse_args()
    if a.step == 'submit-runs':
        submit_runs()
    elif a.submit:
        submit_step(a.step, mem='16G' if a.step == 'prepare' else '64G')
    else:
        {'prepare': prepare, 'check': check}[a.step]()


if __name__ == '__main__':
    main()
