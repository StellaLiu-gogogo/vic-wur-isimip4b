#!/usr/bin/env python3
"""Run manifest of one VIC-WUR run: runs/<campaign-id>/<run-id>/run_manifest.json.

The renderer writes the manifest (status `rendered`) with the identity of the run: campaign, segment, years,
workflow commit, executable and its sha256, and the input identities (parameter files with the md5 of the
parameter manifest, forcing files with the sha256 of their unit's provenance.yaml, every forcing-view link
with its source year and rule). submit_run.py adds one attempt per submission (scheduler job id, time,
inputs fingerprint). The job itself calls this script twice:

  verify-inputs  before VIC starts: every input file must still have the recorded checksum (parallel);
                 the attempt records the result and the job stops on a mismatch
  complete       after VIC ends: scheduler state and exit code, elapsed time, the VIC timing table and
                 log warnings, the expected outputs and state file present, and the run status

A retry with identical inputs is a new attempt in the same manifest (docs/glossary.md, "Run").

Usage: run_manifest.py verify-inputs --run-dir DIR --job-id ID [--processes 8]
       run_manifest.py complete --run-dir DIR --job-id ID --exit-code N
"""
import argparse, datetime, glob, hashlib, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

SCHEMA = 'isimip4b-run-manifest-1'
NAME = 'run_manifest.json'


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def file_hash(path, algo, n=1 << 24):
    h = hashlib.new(algo)
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(n), b''):
            h.update(b)
    return h.hexdigest()


def load(run_dir):
    with open(os.path.join(run_dir, NAME)) as fh:
        return json.load(fh)


def save(run_dir, manifest):
    """Write atomically: a crash never leaves a truncated manifest."""
    path = os.path.join(run_dir, NAME); tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(manifest, fh, indent=1, sort_keys=False)
        fh.write('\n'); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def inputs_fingerprint(manifest):
    """sha256 over the recorded input identities, the executable and the rendered files; equal fingerprints
    mean identical inputs, so a resubmission is an attempt of the same run."""
    keys = {'executable_sha256': manifest['model']['executable_sha256'],
            'inputs': manifest['inputs'], 'forcing_view': manifest['forcing_view'],
            'rendered': manifest['rendered_files']}
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()


def attempt(manifest, job_id):
    for a in manifest['attempts']:
        if str(a['slurm_job_id']) == str(job_id):
            return a
    raise SystemExit(f'no attempt with job id {job_id} in the manifest')


# ------------------------------------------------------------------------------------------- verify-inputs
def checks(manifest, workdir):
    """(workdir path, algorithm, expected) of every input file."""
    out = []
    for p in manifest['inputs']['parameters'].values():
        out.append((p['path'], 'md5', p['md5']))
    for u in manifest['inputs']['forcing_units'].values():
        for f in u['files'].values():
            out.append((f['path'], 'sha256', f['sha256']))
    out.append((manifest['model']['executable'], 'sha256', manifest['model']['executable_sha256']))
    return out


def verify_inputs(run_dir, job_id, workdir, processes):
    m = load(run_dir); a = attempt(m, job_id)
    todo = checks(m, workdir)

    def one(item):
        rel, algo, want = item
        got = file_hash(os.path.join(workdir, rel), algo)
        return rel, got == want
    t0 = datetime.datetime.now()
    with ThreadPoolExecutor(processes) as ex:
        res = list(ex.map(one, todo))
    bad = [rel for rel, ok in res if not ok]
    a['input_verification'] = {'files': len(res), 'mismatches': bad, 'passed': not bad, 'checked_at': utcnow(),
                               'seconds': round((datetime.datetime.now() - t0).total_seconds(), 1)}
    if bad:
        a['status'] = 'failed'; a['failure_reason'] = 'input checksum mismatch'
    else:
        a['status'] = 'running'
    a['started_at'] = utcnow()
    m['status'] = a['status']
    save(run_dir, m)
    if bad:
        sys.exit(f'{len(bad)} input files differ from the recorded checksums, e.g. {bad[:3]}')


# ------------------------------------------------------------------------------------------- complete
TIMING_KEYS = ('Init Time', 'Run Time', 'Final Time', 'Total Time', 'Force Time', 'Write Time')
NUM = r'\s*([-+0-9.eE]+|nan|inf)\s*'
WARNING_PATTERNS = {
    'error': re.compile(r'\[ERROR\]|ERROR', re.I),
    'warning': re.compile(r'\[WARN', re.I),
    'tile_allocation': re.compile(r'tile|no vegetation|veg_class', re.I),
    'nveg': re.compile(r'Nveg', re.I),
    'fcanopy': re.compile(r'fcanopy|MIN_FCANOPY', re.I),
    'water_use': re.compile(r'withdraw|demand|consum|wateruse|water use', re.I),
    'missing_cells': re.compile(r'missing|nan|fill', re.I),
}


def timing_table(text):
    """The VIC timing table and overall metrics (drivers/shared_image/src/vic_image_timing.c): rows
    '| Init Time  | wall | cpu | wall/day | cpu/day |' and 'Model Cost : x pe-hrs/simulated_year'."""
    out = {}
    for key in TIMING_KEYS:
        m = re.search(rf'\|\s*{key}\s*\|' + r'\|'.join([NUM] * 4) + r'\|', text)
        if m:
            out[key] = dict(zip(('wall_s', 'cpu_s', 'wall_s_per_day', 'cpu_s_per_day'), map(float, m.groups())))
    for key, rx in (('model_cost_pe_hours_per_year', r'Model Cost\s*:\s*([-+0-9.eE]+)'),
                    ('throughput_years_per_day', r'Model Throughput\s*:\s*([-+0-9.eE]+)'),
                    ('mpi_processes', r'MPI Processes\s*:\s*(\d+)'), ('openmp_threads', r'OPENMP Threads\s*:\s*(\d+)')):
        m = re.search(rx, text)
        if m:
            out[key] = float(m.group(1))
    return out


def scan_logs(paths):
    """Counts and first examples of warning lines per category over the VIC logs."""
    found = {k: {'count': 0, 'examples': []} for k in WARNING_PATTERNS}
    for p in paths:
        with open(p, errors='replace') as fh:
            for line in fh:
                if not re.search(r'warn|error', line, re.I):
                    continue
                for k, rx in WARNING_PATTERNS.items():
                    if rx.search(line):
                        found[k]['count'] += 1
                        if len(found[k]['examples']) < 5:
                            found[k]['examples'].append(line.strip()[:300])
    return found


def sacct(job_id):
    """Scheduler state, exit code, elapsed time, MaxRSS and nodes of the job and its steps."""
    fmt = 'JobID,State,ExitCode,Elapsed,ElapsedRaw,MaxRSS,NNodes,NCPUS,NodeList,Start,End'
    r = subprocess.run(['sacct', '-j', str(job_id), '-P', '-n', f'--format={fmt}'], capture_output=True, text=True)
    rows = [dict(zip(fmt.split(','), line.split('|'))) for line in r.stdout.splitlines() if line.strip()]
    return rows


def complete(run_dir, job_id, exit_code, workdir):
    m = load(run_dir); a = attempt(m, job_id)
    a['ended_at'] = utcnow(); a['vic_exit_code'] = int(exit_code)
    a['scheduler'] = sacct(job_id)
    logs = sorted(glob.glob(os.path.join(run_dir, 'logs', '*.txt')))
    text = ''
    for p in logs:
        with open(p, errors='replace') as fh:
            text += fh.read()
    a['vic_timing'] = timing_table(text)
    a['log_scan'] = {'files': [os.path.relpath(p, run_dir) for p in logs], 'categories': scan_logs(logs)}
    present = {}
    for rel in m['expected_outputs']:
        hits = sorted(glob.glob(os.path.join(run_dir, rel)))
        present[rel] = [{'path': os.path.relpath(h, run_dir), 'size_bytes': os.path.getsize(h)} for h in hits]
    a['outputs_present'] = present
    a['outputs_complete'] = all(present.values())
    a['output_bytes'] = sum(f['size_bytes'] for v in present.values() for f in v)
    a['completed_by_commit'] = subprocess.run(['git', '-C', os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    ok = int(exit_code) == 0 and a['outputs_complete'] and a.get('input_verification', {}).get('passed', False)
    a['status'] = 'completed' if ok else 'failed'
    if not ok and 'failure_reason' not in a:
        a['failure_reason'] = 'VIC exit code {}; outputs complete: {}'.format(exit_code, a['outputs_complete'])
    m['status'] = a['status']
    save(run_dir, m)
    print(f'run {m["run_id"]} attempt {a["attempt"]}: {a["status"]}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('action', choices=['verify-inputs', 'complete'])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--job-id', required=True)
    ap.add_argument('--exit-code', type=int, default=None)
    ap.add_argument('--processes', type=int, default=8)
    a = ap.parse_args()
    workdir = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
    if a.action == 'verify-inputs':
        verify_inputs(a.run_dir, a.job_id, workdir, a.processes)
    else:
        if a.exit_code is None:
            sys.exit('complete needs --exit-code')
        complete(a.run_dir, a.job_id, a.exit_code, workdir)


if __name__ == '__main__':
    main()
