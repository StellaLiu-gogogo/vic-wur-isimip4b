#!/usr/bin/env python3
"""Run manifest of one VIC-WUR run: runs/<campaign-id>/<run-id>/run_manifest.json.

The renderer writes the manifest (status `rendered`) with the identity of the run: campaign, segment, years,
workflow commit, executable and its sha256, and the input identities (parameter files with the md5 of the
parameter manifest, forcing files with the sha256 of their unit's provenance.yaml, every forcing-view link
with its source year and rule). submit_run.py adds one attempt per submission (scheduler job id, time,
inputs fingerprint). The job itself calls this script twice:

  verify-inputs  before VIC starts: every input file must still have the recorded checksum (parallel), every
                 forcing unit must still be accepted (qc.status passed), every
                 link of the forcing view must point to its recorded source file, and the parent state file
                 (INIT_STATE) must belong to a completed parent run and have the recorded checksum; the attempt
                 records the result and the job stops on a mismatch
  complete       after VIC ends: scheduler state and exit code, elapsed time, the VIC timing table and
                 log warnings, the expected outputs and state file present, every requested OUTVAR in the output
                 files of its stream, and the run status; ends with exit
                 status 1 (common.qc.EXIT_CODES['failed']) when the attempt failed, so the Slurm job fails too

A retry with identical inputs is a new attempt in the same manifest (docs/glossary.md, "Run").

Usage: run_manifest.py verify-inputs --run-dir DIR --job-id ID [--processes 8]
       run_manifest.py complete --run-dir DIR --job-id ID --exit-code N [--reason TEXT]
       run_manifest.py rescan-logs --run-dir DIR --job-id ID
"""
import argparse, contextlib, datetime, fcntl, glob, hashlib, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

import yaml

from common import qc

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


class ManifestConflict(RuntimeError):
    pass


def attempt_ids(manifest):
    return [(a['attempt'], str(a['slurm_job_id'])) for a in manifest['attempts']]


def save(run_dir, manifest):
    """Write atomically: a crash never leaves a truncated manifest. The attempts on disk must be the first attempts
    of `manifest`: a writer that read the manifest before another one added an attempt is refused, so no recorded
    attempt is ever lost."""
    path = os.path.join(run_dir, NAME); tmp = path + '.tmp'
    if os.path.exists(path):
        on_disk = attempt_ids(load(run_dir))
        if attempt_ids(manifest)[:len(on_disk)] != on_disk:
            raise ManifestConflict(f'{path} has attempts {on_disk} that this write would drop or replace '
                                   f'({attempt_ids(manifest)}); another process changed the run')
    with open(tmp, 'w') as fh:
        json.dump(manifest, fh, indent=1, sort_keys=False)
        fh.write('\n'); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


@contextlib.contextmanager
def run_lock(run_dir):
    """Hold the lock of a run directory (flock on the directory itself, so the run layout gets no extra file) for
    one submission: check, submit, record and release. A second submission of the same run stops at once."""
    fd = os.open(run_dir, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f'{run_dir}: another submission of this run is in progress')
        yield
    finally:
        os.close(fd)


JOB_FILE = 'config/job.sbatch'


def inputs_fingerprint(manifest):
    """sha256 over the recorded input identities, the executable and the rendered model files (not the Slurm
    job file, which only says how the run is executed); equal fingerprints mean identical inputs, so a
    resubmission is an attempt of the same run."""
    keys = {'executable_sha256': manifest['model']['executable_sha256'],
            'inputs': manifest['inputs'], 'forcing_view': manifest['forcing_view'],
            'rendered': {k: v for k, v in manifest['rendered_files'].items() if k != JOB_FILE}}
    if (manifest.get('parent') or {}).get('init_state'):   # parent state: path, run, attempt and sha256 when known
        keys['parent'] = manifest['parent']
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()


def attempt(manifest, job_id):
    for a in manifest['attempts']:
        if str(a['slurm_job_id']) == str(job_id):
            return a
    raise SystemExit(f'no attempt with job id {job_id} in the manifest')


# ------------------------------------------------------------------------------------------- verify-inputs
def checks(manifest, workdir):
    """(workdir path, algorithm, expected) of every input file; the parent state file when its sha256 was recorded
    at rendering (a parent rendered in the same call is bound by parent_state())."""
    out = []
    for p in manifest['inputs']['parameters'].values():
        out.append((p['path'], 'md5', p['md5']))
    for u in manifest['inputs']['forcing_units'].values():
        for f in u['files'].values():
            out.append((f['path'], 'sha256', f['sha256']))
    out.append((manifest['model']['executable'], 'sha256', manifest['model']['executable_sha256']))
    parent = manifest['parent']
    if parent.get('init_state') and parent.get('state_sha256'):
        out.append((parent['init_state'], 'sha256', parent['state_sha256']))
    return out


def link_mismatches(manifest, run_dir, workdir):
    """Links of the forcing view (forcing_links: run-relative link -> workdir-relative source, recorded at rendering;
    absent in manifests rendered before 2026-10-07) that are missing or do not point to their source file. VIC opens
    the links, not the unit files."""
    bad = []
    for link, source in (manifest.get('forcing_links') or {}).items():
        p = os.path.join(run_dir, link)
        if not os.path.islink(p) or os.path.realpath(p) != os.path.realpath(os.path.join(workdir, source)):
            bad.append(link)
    return bad


def units_not_accepted(manifest, workdir):
    """provenance.yaml of every forcing unit of the run that is no longer accepted (code_dirty false and qc.status
    passed, as at rendering), e.g. after a verifier judged it failed."""
    bad = []
    for unit in manifest['inputs']['forcing_units']:
        rel = f'forcing/{unit}/provenance.yaml'
        p = os.path.join(workdir, rel)
        prov = {}
        if os.path.exists(p):
            with open(p) as fh:
                prov = yaml.safe_load(fh) or {}
        if prov.get('code_dirty') is not False or (prov.get('qc') or {}).get('status') != 'passed':
            bad.append(rel)
    return bad


def parent_state(manifest, workdir):
    """Parent state of a run whose parent was rendered in the same call: the parent run's last attempt must have
    completed and its state file exist; returns (record, problem). Earlier attempts of this run that recorded a
    parent state fix its sha256, so a retry starts from the same state."""
    parent = manifest['parent']
    if not parent.get('init_state') or parent.get('state_sha256'):
        return None, None
    path = os.path.join(workdir, parent['init_state'])
    prd = os.path.dirname(os.path.dirname(path))
    pm = load(prd) if os.path.exists(os.path.join(prd, NAME)) else {'attempts': []}
    last = pm['attempts'][-1] if pm['attempts'] else {}
    if last.get('status') != 'completed' or not os.path.isfile(path):
        return None, parent['init_state']
    rec = {'run_id': pm.get('run_id'), 'attempt': last['attempt'], 'path': parent['init_state'],
           'sha256': file_hash(path, 'sha256')}
    for a in manifest['attempts']:
        b = (a.get('input_verification') or {}).get('parent_state')
        if b and b['sha256'] != rec['sha256']:
            return rec, parent['init_state']
    return rec, None


def verify_inputs(run_dir, job_id, workdir, processes):
    m = load(run_dir); a = attempt(m, job_id)
    todo = checks(m, workdir)

    def one(item):
        rel, algo, want = item
        p = os.path.join(workdir, rel)
        got = file_hash(p, algo) if os.path.isfile(p) else None
        return rel, got == want
    t0 = datetime.datetime.now()
    with ThreadPoolExecutor(processes) as ex:
        res = list(ex.map(one, todo))
    bad = [rel for rel, ok in res if not ok] + link_mismatches(m, run_dir, workdir) + units_not_accepted(m, workdir)
    pstate, problem = parent_state(m, workdir)
    bad += [problem] if problem else []
    a['input_verification'] = {'files': len(res), 'mismatches': bad, 'passed': not bad, 'checked_at': utcnow(),
                               'seconds': round((datetime.datetime.now() - t0).total_seconds(), 1)}
    if pstate:
        a['input_verification']['parent_state'] = pstate
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
    'error': re.compile(r'\[ERROR\]|\berror:', re.I),
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


def attempt_logs(run_dir, a):
    """Log files of one attempt: the scheduler and VIC stdout files named by its job id, and the VIC rank logs
    created after it started (earlier attempts share logs/)."""
    jid = str(a['slurm_job_id'])
    start = datetime.datetime.strptime(a.get('started_at') or a['submitted_at'], '%Y-%m-%dT%H:%M:%SZ').replace(
        tzinfo=datetime.timezone.utc).timestamp()
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, 'logs', '*'))):
        name = os.path.basename(p)
        if jid in name or (name.startswith('vic.log.') and os.path.getmtime(p) >= start - 60):
            out.append(p)
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


def requested_outputs(vic_global):
    """{stream: [OUTVAR names]} of a VIC global-parameter file (OUTFILE blocks)."""
    out, stream = {}, None
    for line in vic_global.splitlines():
        f = line.split()
        if len(f) >= 2 and f[0] == 'OUTFILE':
            stream = f[1]; out[stream] = []
        elif len(f) >= 2 and f[0] == 'OUTVAR' and stream:
            out[stream].append(f[1])
    return out


def output_variables(run_dir, present):
    """{stream: {requested, missing}}: VIC drops an OUTVAR it does not know with only a warning
    (drivers/shared_image/src/vic_history.c), so the variables of the first output file of every stream are compared
    with the OUTVARs of config/vic_global.txt."""
    import netCDF4 as nc
    with open(os.path.join(run_dir, 'config', 'vic_global.txt')) as fh:
        requested = requested_outputs(fh.read())
    files = sorted(f['path'] for v in present.values() for f in v)
    out = {}
    for stream, names in requested.items():
        first = next((p for p in files if os.path.basename(p).startswith(f'{stream}.')), None)
        if first is None:
            continue                                       # missing files are counted by outputs_complete
        with nc.Dataset(os.path.join(run_dir, first)) as d:
            have = set(d.variables)
        out[stream] = {'file': first, 'requested': len(names), 'missing': [n for n in names if n not in have]}
    return out


def complete(run_dir, job_id, exit_code, workdir, reason=None):
    m = load(run_dir); a = attempt(m, job_id)
    if reason:
        a['failure_reason'] = reason
    a['ended_at'] = utcnow(); a['vic_exit_code'] = int(exit_code)
    a['scheduler'] = sacct(job_id)
    logs = attempt_logs(run_dir, a)
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
    a['output_variables'] = output_variables(run_dir, present)
    dropped = {s: v['missing'] for s, v in a['output_variables'].items() if v['missing']}
    a['output_bytes'] = sum(f['size_bytes'] for v in present.values() for f in v)
    a['completed_by_commit'] = subprocess.run(['git', '-C', os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    ok = int(exit_code) == 0 and a['outputs_complete'] and not dropped and \
        a.get('input_verification', {}).get('passed', False)
    if dropped and 'failure_reason' not in a:
        a['failure_reason'] = f'requested output variables missing in the output files: {dropped}'
    a['status'] = 'completed' if ok else 'failed'
    if not ok and 'failure_reason' not in a:
        a['failure_reason'] = 'VIC exit code {}; outputs complete: {}'.format(exit_code, a['outputs_complete'])
    m['status'] = a['status']
    save(run_dir, m)
    print(f'run {m["run_id"]} attempt {a["attempt"]}: {a["status"]}')
    if not ok:
        qc.exit_with('failed')


def rescan_logs(run_dir, job_id):
    """Recompute the log scan of an attempt (e.g. after the scan rules changed); nothing else is touched."""
    m = load(run_dir); a = attempt(m, job_id)
    logs = attempt_logs(run_dir, a)
    a['log_scan'] = {'files': [os.path.relpath(p, run_dir) for p in logs], 'categories': scan_logs(logs),
                     'rescanned_at': utcnow()}
    save(run_dir, m)
    print(json.dumps({k: v['count'] for k, v in a['log_scan']['categories'].items()}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('action', choices=['verify-inputs', 'complete', 'rescan-logs'])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--job-id', required=True)
    ap.add_argument('--exit-code', type=int, default=None)
    ap.add_argument('--processes', type=int, default=8)
    ap.add_argument('--reason', default=None, help='complete: why the attempt ended (e.g. cancelled, and why)')
    a = ap.parse_args()
    workdir = os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')
    if a.action == 'verify-inputs':
        verify_inputs(a.run_dir, a.job_id, workdir, a.processes)
    elif a.action == 'rescan-logs':
        rescan_logs(a.run_dir, a.job_id)
    else:
        if a.exit_code is None:
            sys.exit('complete needs --exit-code')
        complete(a.run_dir, a.job_id, a.exit_code, workdir, a.reason)


if __name__ == '__main__':
    main()
