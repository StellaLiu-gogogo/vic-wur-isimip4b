#!/usr/bin/env python3
"""Compare the output and end states of two completed VIC-WUR runs over their common years.

Used to show that a chunked run gives the same result as the same run in one job (task L4b, campaign chunk-test):
a chunk after the first starts from the previous chunk's end state, so any model quantity that VIC does not keep
in its state would make the two runs differ from the second chunk on. Works for chunked and unchunked runs (the
output of a year is read from the chunk that holds it).

For every stream (daily, monthly), common year, variable present in both files and time step: the number of
active-domain values that differ, the largest absolute difference and the largest absolute value; for the end
states with the same date: the same per state variable. Status: passed when every compared value is bitwise
identical, warning otherwise (the report gives the size of the differences), failed when a file or variable is
missing in one run. Writes qc/<run A>/reports/compare_<run B id>.json and prints a summary.

Usage: compare_runs.py --run-dir A --other B [--years 2016 2016] [--submit [--time 04:00:00] [--mem 64G]]
"""
import argparse, json, os, sys

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
TEMPLATE = os.path.join(HERE, 'compare_runs.sbatch')
sys.path.insert(0, HERE)


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def load(rd):
    with open(os.path.join(rd, 'run_manifest.json')) as fh:
        return json.load(fh)


def year_dirs(rd, man):
    """{year: directory whose output/ holds that year} (the run directory, or the chunk of each year)."""
    chunks = man.get('chunks') or []
    if not chunks:
        y0, y1 = int(man['period']['start'][:4]), int(man['period']['end'][:4])
        return {y: rd for y in range(y0, y1 + 1)}
    return {y: os.path.join(rd, c['dir']) for c in chunks for y in range(c['start_year'], c['end_year'] + 1)}


def end_state(rd, man):
    rel = man.get('end_state') or f'states/state.{int(man["period"]["end"][:4]) + 1}0101_00000.nc'
    return os.path.join(rd, rel)


def compare_arrays(a, b, mask=None):
    """(differing values, largest |a - b|, largest |a|) over finite-or-not values; NaN equals NaN."""
    a = np.asarray(a); b = np.asarray(b)
    if mask is not None and a.shape[-2:] == mask.shape:
        a, b = a[..., mask], b[..., mask]
    same = (a == b) | (np.isnan(a) & np.isnan(b)) if a.dtype.kind == 'f' else (a == b)
    diff = int((~same).sum())
    if a.dtype.kind in 'fiu' and diff:
        d = np.abs(a.astype('f8') - b.astype('f8'))
        dmax = float(np.nanmax(np.where(same, 0, d)))
    else:
        dmax = 0.0
    amax = float(np.nanmax(np.abs(a.astype('f8')))) if a.size and a.dtype.kind in 'fiu' else 0.0
    return diff, dmax, amax


def compare_files(pa, pb, mask, time_dim='time'):
    """{variable: {values_differing, max_abs_diff, max_abs_value}} and the variables missing in one file."""
    out, missing = {}, []
    with nc.Dataset(pa) as A, nc.Dataset(pb) as B:
        A.set_auto_mask(False); B.set_auto_mask(False)
        names = [v for v in A.variables if v not in A.dimensions and v not in ('time_bnds',)]
        missing = sorted((set(names) ^ {v for v in B.variables if v not in B.dimensions and v != 'time_bnds'}))
        for v in names:
            if v not in B.variables:
                continue
            va, vb = A[v], B[v]
            if va.shape != vb.shape:
                out[v] = {'shape_differs': [list(va.shape), list(vb.shape)]}; continue
            tot = [0, 0.0, 0.0]
            steps = range(va.shape[0]) if va.ndim >= 3 and va.dimensions[0] == time_dim else [None]
            for t in steps:
                a = va[t] if t is not None else va[:]
                b = vb[t] if t is not None else vb[:]
                # VIC writes the fill value outside the domain; it is compared like any value
                d, dm, am = compare_arrays(a, b, mask)
                tot[0] += d; tot[1] = max(tot[1], dm); tot[2] = max(tot[2], am)
            out[v] = {'values_differing': tot[0], 'max_abs_diff': tot[1], 'max_abs_value': tot[2]}
    return out, missing


def run(a, W):
    ra, rb = os.path.abspath(a.run_dir), os.path.abspath(a.other)
    ma, mb = load(ra), load(rb)
    ya, yb = year_dirs(ra, ma), year_dirs(rb, mb)
    years = sorted(set(ya) & set(yb))
    if a.years:
        years = [y for y in years if a.years[0] <= y <= a.years[1]]
    if not years:
        sys.exit('the runs have no common year')
    import yaml
    first = (ma.get('chunks') or [{'dir': '.'}])[0]['dir']
    with open(os.path.join(ra, first, 'config', 'resolved.yaml')) as fh:
        res = yaml.safe_load(fh)
    with nc.Dataset(os.path.join(W, res['parameters']['domain']['path'])) as d:
        mask = np.asarray(d['mask'][:].filled(0)) == 1
    report = {'run': ma['run_dir'], 'other': mb['run_dir'], 'years': years, 'files': {}, 'missing': {}}
    for y in years:
        for stream, name in (('daily', f'daily.{y}-01-01.nc'), ('monthly', f'monthly.{y}-01.nc')):
            pa, pb = os.path.join(ya[y], 'output', name), os.path.join(yb[y], 'output', name)
            key = f'{stream} {y}'
            if not (os.path.isfile(pa) and os.path.isfile(pb)):
                report['missing'][key] = [p for p in (pa, pb) if not os.path.isfile(p)]; continue
            report['files'][key], miss = compare_files(pa, pb, mask)
            if miss:
                report['missing'][key] = miss
            print(f'{key}: {sum(1 for v in report["files"][key].values() if v.get("values_differing"))} of '
                  f'{len(report["files"][key])} variables differ', flush=True)
    sa, sb = end_state(ra, ma), end_state(rb, mb)
    if os.path.basename(sa) == os.path.basename(sb) and os.path.isfile(sa) and os.path.isfile(sb):
        report['files']['end state ' + os.path.basename(sa)], miss = compare_files(sa, sb, None, time_dim='-')
        if miss:
            report['missing']['end state'] = miss
    else:
        report['missing']['end state'] = [sa, sb]
    differ = {k: {v: r for v, r in f.items() if r.get('values_differing') or 'shape_differs' in r}
              for k, f in report['files'].items()}
    report['differing'] = {k: v for k, v in differ.items() if v}
    report['status'] = 'failed' if report['missing'] else ('warning' if report['differing'] else 'passed')
    qc = os.path.join(W, 'qc', ma['run_dir'], 'reports')
    os.makedirs(qc, exist_ok=True)
    out = os.path.join(qc, f'compare_{mb["run_id"]}.json')
    with open(out + '.part', 'w') as fh:
        json.dump(report, fh, indent=1)
    os.replace(out + '.part', out)
    print(json.dumps({'status': report['status'], 'missing': report['missing'],
                      'differing': {k: sorted(v) for k, v in report['differing'].items()}}, indent=1))
    print(f'report {out}')
    from common import qc as qcm
    qcm.exit_with(report['status'])


def submit(a, W):
    from common import gitstate, jobrecord
    ra = os.path.relpath(os.path.abspath(a.run_dir), W); rb = os.path.relpath(os.path.abspath(a.other), W)
    label = lambda r: os.path.basename(r).split('__')[-1]
    name = f'compare-runs-{os.path.basename(os.path.dirname(ra))}-{label(ra)}-{label(rb)}'
    opts = f' --years {a.years[0]} {a.years[1]}' if a.years else ''
    stage_logs = os.path.join(W, 'logs', '05_simulation')
    text = jobrecord.render(TEMPLATE, {'JOB_NAME': name, 'PARTITION': a.partition, 'TIME': a.time, 'MEM': a.mem,
                                       'STAGE_LOGS': stage_logs, 'CONDA_BASE': jobrecord.conda_base(), 'WORKDIR': W,
                                       'REPO': REPO, 'RUN_A': os.path.join(W, ra), 'RUN_B': os.path.join(W, rb),
                                       'OPTIONS': opts})
    commit, dirty = gitstate.state(REPO)
    jobrecord.submit(text, stage_logs, name, 'workflow/05_simulation/monitor/compare_runs.py',
                     'workflow/05_simulation/monitor/compare_runs.sbatch', commit, dirty,
                     {'resources': {'partition': a.partition, 'time': a.time, 'cpus_per_task': 1, 'mem': a.mem},
                      'inputs': [ra, rb], 'outputs': [f'qc/{ra}/reports/compare_{os.path.basename(rb)}.json']})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--other', required=True)
    ap.add_argument('--years', type=int, nargs=2, default=None)
    ap.add_argument('--submit', action='store_true', help='run as a Slurm job (job record in logs/05_simulation/)')
    ap.add_argument('--time', default='04:00:00')
    ap.add_argument('--mem', default='64G')
    ap.add_argument('--partition', default='main')
    a = ap.parse_args(); W = workdir()
    submit(a, W) if a.submit else run(a, W)


if __name__ == '__main__':
    main()
