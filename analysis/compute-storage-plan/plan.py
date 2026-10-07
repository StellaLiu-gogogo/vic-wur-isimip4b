#!/usr/bin/env python3
"""Compute and storage plan of the ISIMIP4b water_global campaigns on Anunna (evidence for decisions D02 and D03).

Everything is computed from records, so the script is re-run when the smoke run 2011-2020 has more years:
  segments     workflow/05_simulation/render/resolve_campaign.py on configs/campaigns/smoke.yaml with the experiment
               selection replaced (all 18, 1st priority, Group I-II, ...) and the spin-up length set
  speed        run manifests and output-file times of the smoke runs (per model year, initialisation)
  sizes        output files of the smoke runs; per-variable and compression tables of measure_files.py
  forcing      file sizes of the forcing units and raw inputs; climate producer job record in logs/04_forcing/
  cluster      sinfo / sshare at the time of the run (gen3 nodes of partition main, fair share)
and writes tables/*.csv, figures/*.png and report.md under workdir/analysis/compute-storage-plan/.

Usage: plan.py [--spinup-years 50] [--start 2026-11-02] [--nodes 6] [--queue-wait-hours 0] [--no-report]
"""
import argparse, copy, csv, datetime as dt, glob, json, math, os, re, subprocess, sys
from collections import defaultdict

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csp   # noqa: E402

sys.path.insert(0, os.path.join(csp.REPO, 'workflow', '05_simulation', 'render'))
import resolve_campaign as rc   # noqa: E402

GB, TB = 1e9, 1e12
GCMS = ('ec-earth3-esm-1-1', 'ukesm1-3-ll')
CAMPAIGN = 'configs/campaigns/smoke.yaml'
RESOURCES = 'configs/resources/vic-global-5arcmin.yaml'
CORES_PER_NODE = 128
# Anunna tariffs (wiki.anunna.wur.nl/Tariffs, read 2026-10-05): charged on requested resources and claimed time
EUR_CORE_HOUR, EUR_GB_HOUR, EUR_TB_YEAR_NOBACKUP = 0.0150, 0.0011, 100.0
AR7_DEADLINE = dt.date(2027, 5, 1)       # "AR7 submission deadline expected in May 2027" (ISIMIP4b start e-mail)
# assumptions that no record settles (named in the report)
PRODUCT_FRACTION = 0.05     # 0.5 degree products / 5' output (1/36 of the cells, more files and derived variables)
POSTPROCESS_LAG_DAYS = 3    # from the end of a run until its 0.5 degree products have passed QC
SLOW_FACTOR = 1.3           # slow case: several concurrent runs and a busier filesystem (not measured)
MAX_JOB_HOURS = 480         # longest job planned (partition limit 21 days = 504 h, minus a margin)
CLIMATE_ALIASES = {'picontrol': 'esm-picontrol', 'historical': 'esm-hist', 'vl': 'esm-scen7-vl', 'h': 'esm-scen7-h'}
SPINUP_WINDOW = (1601, 1650)  # picontrol years cycled by the spin-up (inside the pre-industrial years)

# ISIMIP variable -> VIC outputs, for the daily-output options (smoke.yaml output.isimip)
DAILY_SETS = {
    'protocol': ['OUT_RUNOFF', 'OUT_BASEFLOW', 'OUT_DISCHARGE'],                         # qtot, dis
    'if-possible': ['OUT_RUNOFF', 'OUT_BASEFLOW', 'OUT_DISCHARGE', 'OUT_SOIL_MOIST', 'OUT_SOIL_TEMP',
                    'OUT_SNOW_DEPTH', 'OUT_SNOW_MELT', 'OUT_LAI'],                       # + soilmoist tsl snd snm lai
}


# ------------------------------------------------------------------------------------------------ helpers
def W(*p):
    return os.path.join(csp.workdir(), *p)


def write_csv(name, rows, fields=None):
    path = f'{csp.tables()}/{name}'
    fields = fields or list(rows[0])
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)
    return path


def read_csv(name):
    path = f'{csp.tables()}/{name}'
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return list(csv.DictReader(fh))


def stat_times(path):
    """(birth, modification) as POSIX seconds; birth from `stat -c %W` (0 when the filesystem does not keep it)."""
    out = subprocess.run(['stat', '-c', '%W %Y', path], capture_output=True, text=True, check=True).stdout.split()
    return float(out[0]), float(out[1])


def tree_bytes(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            if not os.path.islink(p):
                total += os.path.getsize(p)
    return total


def utc(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


# ------------------------------------------------------------------------------------------------ segments
def protocol_pool(c):
    exps, _, _ = rc.load_protocol(W(c['protocol']['path']), c['protocol']['simulation_round'])
    sector = c['protocol']['sector']
    return [e for e in exps if sector in e.get('sectors', [])]


def future_soc_sens(e):
    f = e['future']
    return f['soc'], f.get('soc_sens') or f.get('climate_sens') or 'default'


def subsets(pool):
    """Experiment selections of the plan: name -> (description, experiment ids)."""
    ids = [e['specifier'] for e in pool]
    by = {e['specifier']: e for e in pool}
    grp12 = [i for i in ids if not future_soc_sens(by[i])[0].startswith('ssp')]
    p1 = [i for i in ids if by[i]['priority'] == '1st priority']
    noextra = [i for i in ids if future_soc_sens(by[i])[1] != 'extrasoc']
    return {
        'all-18': ('all 18 water_global experiments', ids),
        'all-but-extrasoc': ('all experiments except the two extrasoc ones (D06 open)', noextra),
        'priority-1': ('1st priority only', p1),
        'group-I-II': ('Group I and II only (no SSP DHF)', grp12),
        'priority-1-group-I-II': ('1st priority, Group I and II only', [i for i in p1 if i in grp12]),
    }


def resolve_subset(base, ids, spinup_years, gcms):
    c = copy.deepcopy(base)
    c['experiments'] = {'ids': list(ids)}
    c.pop('restriction', None)
    c['spinup'] = {'length_years': spinup_years, 'climate_cycle': None}
    c['gcms'] = {g: {'climate_input': 'emission-driven'} for g in gcms}
    segs, _ = rc.resolve(c, W(c['protocol']['path']))
    return segs


def segment_rows(segs):
    rows = []
    for sid, s in segs.items():
        rows.append(dict(segment_id=sid, gcm=s.gcm, period=s.period, climate=s.climate, soc=s.soc, sens=s.sens,
                         start_year=s.start_year, end_year=s.end_year, years=s.end_year - s.start_year + 1,
                         parent=s.parent or '', n_experiments=len(s.experiments),
                         experiments=' '.join(sorted(s.experiments))))
    return rows


# ------------------------------------------------------------------------------------------------ speed and sizes
def run_records():
    """Per run: identity, node, init seconds, per-year durations and file sizes (complete years only)."""
    out = {}
    for key, rel in csp.SMOKE_RUNS.items():
        rd = W(rel)
        if not os.path.exists(f'{rd}/run_manifest.json'):
            continue
        m = json.load(open(f'{rd}/run_manifest.json'))
        att = m['attempts'][-1]
        job = att.get('slurm_job_id')
        start = None
        for f in sorted(glob.glob(f'{rd}/logs/slurm-{job}.out')):
            mm = re.search(r'start (\S+Z)', open(f).read())
            start = utc(mm.group(1)).timestamp() if mm else None
        y0, y1 = int(m['expected_outputs'][0].split('.')[1][:4]), None
        daily = {int(os.path.basename(p)[6:10]): p for p in glob.glob(f'{rd}/output/daily.*.nc')}
        monthly = {int(os.path.basename(p)[8:12]): p for p in glob.glob(f'{rd}/output/monthly.*.nc')}
        years = sorted(monthly)
        y1 = max(int(e.split('.')[1][:4]) for e in m['expected_outputs'] if e.startswith('output/'))
        done = m['status'] == 'completed'
        complete = [y for y in years if done or (y + 1) in daily]
        rows, prev_end = [], None
        init_s = None
        if years:
            b0, _ = stat_times(daily[years[0]])
            init_s = b0 - start if start and b0 else None
            prev_end = b0
        for y in complete:
            _, mt = stat_times(monthly[y])
            rows.append(dict(run=key, year=y, hours=(mt - prev_end) / 3600, daily_bytes=os.path.getsize(daily[y]),
                             monthly_bytes=os.path.getsize(monthly[y]), t0=prev_end, t1=mt))
            prev_end = mt
        vt = att.get('vic_timing') or {}
        node = (att.get('scheduler') or [{}])[0].get('NodeList') or ''
        if not node:
            mm = re.search(r'host (\S+)', open(glob.glob(f'{rd}/logs/slurm-{job}.out')[0]).read())
            node = mm.group(1) if mm else ''
        states = sorted(glob.glob(f'{rd}/states/*.nc'))
        # the end state is written after the last model day by one process: birth -> last modification
        state_write_s = None
        if states and done:
            sb, sm = stat_times(states[-1])
            state_write_s = sm - sb if sb else None
        out[key] = dict(run_id=m['run_id'], status=m['status'], job=job, node=node, years_planned=(y0, y1),
                        init_s=vt.get('Init Time', {}).get('wall_s') or init_s, init_from_files_s=init_s,
                        vic_timing=vt, years=rows, state_write_s=state_write_s, state_bytes=os.path.getsize(states[-1]) if states else None,
                        maxrss_kb=max([int(r['MaxRSS'][:-1]) for r in att.get('scheduler') or []
                                       if r.get('MaxRSS', '').endswith('K')] or [0]))
    return out


def measure_windows():
    """(start, end) POSIX times of this task's measurement jobs (they load /lustre while the smoke run works)."""
    out = []
    for f in glob.glob(f'{csp.products()}/logs/measure_*/slurm-*.out'):
        t = open(f).read()
        s, e = re.search(r'start (\S+Z)', t), re.search(r'^end (\S+Z)', t, re.M)
        if s:
            out.append((utc(s.group(1)).timestamp(),
                        utc(e.group(1)).timestamp() if e else os.path.getmtime(f)))
    return out


def speed_and_size(recs):
    all_years = [r for v in recs.values() for r in v['years']]
    win = measure_windows()
    for r in all_years:
        ov = sum(max(0.0, min(r['t1'], e) - max(r['t0'], s)) for s, e in win)
        r['measure_overlap'] = ov / (r['t1'] - r['t0'])
    quiet = [r for r in all_years if r['measure_overlap'] < 0.05]
    plan_rows = all_years   # every complete model year of both runs (one year = last-day file time differences)
    h_plan = sum(r['hours'] for r in plan_rows) / len(plan_rows)
    h_high = max(r['hours'] for r in all_years)
    inits = [v['init_s'] for v in recs.values() if v['init_s']]
    sw = [v['state_write_s'] for v in recs.values() if v['state_write_s']]
    nonleap = [r for r in all_years if r['year'] % 4]
    sp = dict(hours_per_year=h_plan, hours_per_year_high=h_high, hours_per_year_low=min(r['hours'] for r in all_years),
              basis=f'mean of {len(plan_rows)} complete model years of the smoke runs ' +
                    ', '.join(f'{r["run"]} {r["year"]}' for r in plan_rows),
              init_hours=sum(inits) / len(inits) / 3600,
              state_write_hours=sum(sw) / len(sw) / 3600,
              hours_per_year_slow=h_plan * SLOW_FACTOR,
              hours_per_year_quiet=(sum(r['hours'] for r in quiet) / len(quiet)) if quiet else None,
              quiet_years=len(quiet),
              daily_bytes=sum(r['daily_bytes'] for r in nonleap) / len(nonleap),
              monthly_bytes=sum(r['monthly_bytes'] for r in nonleap) / len(nonleap),
              state_bytes=max(v['state_bytes'] for v in recs.values() if v['state_bytes']),
              maxrss_gb_per_rank=max(v['maxrss_kb'] for v in recs.values()) / 1e6)
    return sp


# ------------------------------------------------------------------------------------------------ measured tables
def variable_tables(sp):
    """Output per variable and time step (bytes per model year) and daily-size factors per output set."""
    vs = read_csv('variable_storage.csv')
    if not vs:
        return None, None
    rows = []
    per_step = {}
    for r in vs:
        if r['file'] not in ('daily', 'monthly') or not r['variable'].startswith('OUT_'):
            continue
        nt = int(r['shape'].split(',')[0].split('/')[0])
        b = int(r['allocated_bytes'])
        per_step[(r['file'], r['variable'])] = b / nt
        rows.append(dict(stream=r['file'], variable=r['variable'], shape=r['shape'], bytes_per_year=b,
                         share_of_stream=0.0))
    for s in ('daily', 'monthly'):
        tot = sum(x['bytes_per_year'] for x in rows if x['stream'] == s)
        for x in rows:
            if x['stream'] == s:
                x['share_of_stream'] = round(x['bytes_per_year'] / tot, 4)
    # a daily time step of a variable compresses differently from a monthly one: calibrate with the variables
    # that are in both streams
    both = [v for (s, v) in per_step if s == 'daily' and ('monthly', v) in per_step]
    k = sum(per_step[('daily', v)] for v in both) / sum(per_step[('monthly', v)] for v in both)
    est = []
    for (s, v), b in per_step.items():
        if s != 'monthly':
            continue
        measured = per_step.get(('daily', v))
        est.append(dict(variable=v, monthly_bytes_per_year=round(b * 12),
                        daily_bytes_per_year=round((measured or b * k) * 365),
                        daily_basis='measured' if measured else f'estimated: monthly step x {k:.3f} x 365'))
    return rows, dict(k=k, est={e['variable']: e for e in est})


def daily_set_bytes(var_est, name, sp):
    if var_est is None:
        return sp['daily_bytes']
    names = DAILY_SETS.get(name) or list(var_est['est'])
    return sum(var_est['est'][v]['daily_bytes_per_year'] for v in names if v in var_est['est'])


def post_run(variant):
    """Settings VIC cannot apply when it writes (rounding of significant digits, zstd, chunk shapes)."""
    return '-gbr' in variant or variant.startswith('zstd') or '-chunk-' in variant


def compression_factors():
    """{(stream, variant): (size factor vs VIC zlib2, extra write seconds per model year)}."""
    rows = read_csv('compression_samples.csv')
    if not rows:
        return {}
    base = {r['file']: r for r in rows if r['variant'] == 'zlib2-shuffle (VIC)'}
    f = {}
    for r in rows:
        b = base[r['file']]
        f[(r['file'], r['variant'])] = (int(r['bytes_per_year']) / int(b['bytes_per_year']),
                                        float(r['write_s_per_year']) - float(b['write_s_per_year']))
        f[(r['file'], r['variant'] + '#rw')] = float(b['read_s_per_year']) + float(r['write_s_per_year'])
    return f


# ------------------------------------------------------------------------------------------------ forcing and cluster
def forcing_sizes():
    clim = W('forcing/climate/ec-earth3-esm-1-1/esm-hist')
    files = glob.glob(f'{clim}/*/*.nc')
    years = sorted({int(f[-7:-3]) for f in files})
    per_year = sum(os.path.getsize(f) for f in files) / len(years)
    dhf = {fam: {d: tree_bytes(W('forcing', fam, d)) for d in sorted(os.listdir(W('forcing', fam)))}
           for fam in ('landuse', 'water_use')}
    raw = {}
    base = W('raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily')
    for alias in sorted(os.listdir(base)):
        for gcm in sorted(os.listdir(f'{base}/{alias}')):
            raw[(alias, gcm)] = tree_bytes(f'{base}/{alias}/{gcm}')
    return dict(climate_bytes_per_year=per_year, climate_years_measured=years, dhf=dhf, raw=raw)


def producer_speed():
    """Climate forcing producer: wall and core hours per forcing year (all 7 variables), from its job records."""
    rows = []
    for d in sorted(glob.glob(W('logs/04_forcing/climate-forcing-*_*'))):
        if 'scratch' in d:
            continue
        job = yaml.safe_load(open(f'{d}/job.yaml'))
        m = re.search(r'--years (\d+)-(\d+)', job['commands']['producer'])
        if not m:
            continue
        n = int(m.group(2)) - int(m.group(1)) + 1
        err = open(glob.glob(f'{d}/slurm-*.err')[0]).read()
        el = re.findall(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)', err)
        secs = []
        for e in el:
            p = [float(x) for x in e.split(':')]
            secs.append(p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1])
        cpus = int(job['resources']['cpus_per_task'])
        rows.append(dict(job=os.path.basename(d), years=n, cpus=cpus, producer_h=secs[0] / 3600,
                         verifier_h=(secs[1] / 3600 if len(secs) > 1 else 0.0),
                         wall_h_per_year=sum(secs) / 3600 / n, core_h_per_year=sum(secs) / 3600 * cpus / n))
    return rows


def cluster_state():
    st = dict(time=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'))
    try:
        out = subprocess.run(['sinfo', '-p', 'main', '-N', '-h', '-o', '%N|%f|%m|%T'], capture_output=True,
                             text=True, timeout=60).stdout
        nodes = {}
        for line in out.splitlines():
            n, f, mem, state = line.split('|')
            nodes[n] = (f, int(mem), state)
        gen3 = {n: v for n, v in nodes.items() if 'gen3' in v[0].split(',') and v[1] >= 1000000}
        st['gen3_1tb_nodes'] = len(gen3)
        st['gen3_states'] = dict(sorted(defaultdict(int, {}).items()))
        cnt = defaultdict(int)
        for v in gen3.values():
            cnt[v[2].rstrip('*~^#')] += 1
        st['gen3_states'] = dict(cnt)
        part = subprocess.run(['scontrol', 'show', 'partition', 'main'], capture_output=True, text=True,
                              timeout=60).stdout
        st['max_time'] = re.search(r'MaxTime=(\S+)', part).group(1)
        st['total_nodes'] = int(re.search(r'TotalNodes=(\d+)', part).group(1))
        sh = subprocess.run(['sshare', '-U', '-h', '-P', '-o', 'Account,User,NormShares,EffectvUsage,FairShare'],
                            capture_output=True, text=True, timeout=60).stdout.strip().splitlines()
        if sh:
            a, u, ns, eu, fs = sh[0].split('|')
            st['fairshare'] = dict(account=a, user=u, norm_shares=float(ns), effective_usage=float(eu),
                                   fairshare=float(fs))
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError) as e:
        st['error'] = str(e)
    return st


# ------------------------------------------------------------------------------------------------ demand
def runs_of(segs, sp, hours_per_year):
    """Jobs of the segments: (job id, segment id, parent job, years, hours); a segment longer than one job is split
    into chunks (docs/glossary.md, chunk), each with its own initialisation and end state."""
    jobs = []
    overhead = sp['init_hours'] + sp['state_write_hours']
    per_job = max(1, int((MAX_JOB_HOURS - overhead) // hours_per_year))
    last_job = {}
    for sid, s in segs.items():
        n = s.end_year - s.start_year + 1
        parent = last_job.get(s.parent)
        k = 0
        for y0 in range(s.start_year, s.end_year + 1, per_job):
            y1 = min(s.end_year, y0 + per_job - 1)
            jid = sid if n <= per_job else f'{sid}/{y0}-{y1}'
            jobs.append(dict(job=jid, segment=sid, gcm=s.gcm, period=s.period, parent=parent, years=y1 - y0 + 1,
                             hours=overhead + (y1 - y0 + 1) * hours_per_year))
            parent = jid; k += 1
        last_job[sid] = parent
    return jobs


def demand(segs, sp, fs, var_est, daily='protocol', hours_per_year=None, compress=None, cf=None,
           spinup_output='state'):
    h = hours_per_year or sp['hours_per_year']
    cf = cf or {}
    dsize = daily_set_bytes(var_est, daily, sp)
    msize = sp['monthly_bytes']
    extra_write_h = post_h = 0.0
    if compress:
        fd, wd = cf.get(('daily', compress), (1.0, 0.0)); fm, wm = cf.get(('monthly', compress), (1.0, 0.0))
        dsize, msize = dsize * fd, msize * fm
        if post_run(compress):
            # a separate one-core step reads the VIC files and writes them again (sample times, per model year)
            post_h = sum(cf.get((k, compress + '#rw'), 0.0) for k in ('daily', 'monthly')) / 3600
        else:
            # VIC compresses every field on one rank: the extra write time adds to the run time
            extra_write_h = (wd + wm) / 3600   # the samples hold the protocol daily set and every monthly variable
    h = h + extra_write_h
    jobs = runs_of(segs, sp, h)
    years = sum(s.end_year - s.start_year + 1 for s in segs.values())
    spin = sum(s.end_year - s.start_year + 1 for s in segs.values() if s.period == 'spinup')
    rep = years - spin
    gcms = sorted({s.gcm for s in segs.values()})
    # climate forcing years per GCM: union of the years each climate scenario is used (spin-up reads the window)
    need = defaultdict(set)
    for s in segs.values():
        if s.period == 'spinup':
            need['picontrol'].update(range(SPINUP_WINDOW[0], SPINUP_WINDOW[1] + 1))
        else:
            need[s.climate].update(range(s.start_year, s.end_year + 1))
    clim_years = sum(len(v) for v in need.values())
    node_h = sum(j['hours'] for j in jobs)
    spin_diag = 0.0 if spinup_output == 'state' else spin * msize / 12
    return dict(model_years=years, spinup_years=spin, reported_years=rep, segments=len(segs), jobs=len(jobs),
                node_hours=node_h, core_hours=node_h * CORES_PER_NODE + (years - spin) * post_h,
                postrun_core_hours=(years - spin) * post_h,
                daily_tb=rep * dsize / TB, monthly_tb=(rep * msize + spin_diag) / TB,
                output_tb=(rep * (dsize + msize) + spin_diag) / TB,
                state_tb=len(jobs) * sp['state_bytes'] / TB,
                climate_forcing_years=clim_years,
                climate_forcing_tb=clim_years * fs['climate_bytes_per_year'] / TB,
                climate_years_by_scenario={k: len(v) for k, v in need.items()},
                dhf_forcing_tb=sum(sum(v.values()) for v in fs['dhf'].values()) / TB,
                hours_per_year=h, daily_bytes_per_year=dsize, monthly_bytes_per_year=msize, gcms=len(gcms), jobs_list=jobs)


# ------------------------------------------------------------------------------------------------ schedule
def schedule(jobs, nodes, queue_wait_h=0.0, release=None, priority_order=None):
    """List scheduling on `nodes` identical nodes: a job is ready when its parent has ended (plus the queue wait);
    among ready jobs the one with the longest remaining chain (then the priority order) starts first.
    release: {gcm: earliest start hour}. Returns {job: (start_h, end_h)}."""
    release = release or {}
    by = {j['job']: j for j in jobs}
    kids = defaultdict(list)
    for j in jobs:
        if j['parent']:
            kids[j['parent']].append(j['job'])
    tail = {}

    def chain(jid):
        if jid not in tail:
            tail[jid] = by[jid]['hours'] + max([chain(k) for k in kids[jid]] or [0.0])
        return tail[jid]
    for j in jobs:
        chain(j['job'])
    pr = priority_order or {}
    ready_at = {j['job']: release.get(j['gcm'], 0.0) + queue_wait_h for j in jobs if not j['parent']}
    free = [0.0] * nodes
    done, out = {}, {}
    pending = set(by)
    while pending:
        cand = [(ready_at[j], j) for j in pending if j in ready_at]
        t_node = min(free)
        i = free.index(t_node)
        t = max(t_node, min(c[0] for c in cand))
        ready = [j for r, j in cand if r <= t + 1e-9]
        j = sorted(ready, key=lambda x: (pr.get(by[x]['segment'], 9), -tail[x], x))[0]
        s = t; e = s + by[j]['hours']
        free[i] = e; out[j] = (s, e); pending.discard(j)
        for k in kids[j]:
            ready_at[k] = e + queue_wait_h
    return out


def critical_path_hours(jobs, queue_wait_h=0.0):
    sch = schedule(jobs, len(jobs), queue_wait_h)
    return max(e for _, e in sch.values())


# ------------------------------------------------------------------------------------------------ storage timeline
def storage_timeline(jobs, sch, d, sp, fs, rule, gcm_release, forcing_mode='full', step_h=24.0):
    """Project storage (TB) over time: climate forcing, states, 5' monthly and daily output, 0.5 degree products.
    rule: keep (all 5' output stays), delete-daily (daily deleted after its products pass QC),
    delete-5min (daily and monthly deleted after QC; states and run records kept)."""
    end = max(e for _, e in sch.values()) + POSTPROCESS_LAG_DAYS * 24 + step_h
    ts = [i * step_h for i in range(int(end // step_h) + 2)]
    lag = POSTPROCESS_LAG_DAYS * 24
    dsz, msz = d['daily_bytes_per_year'], d['monthly_bytes_per_year']
    per_gcm_forcing = d['climate_forcing_tb']   # climate forcing of one GCM
    rows = []
    jl = [(j, sch[j['job']]) for j in jobs]
    # rolling forcing: years of each climate scenario exist from the start of their first user until the end of their
    # last user (production before use, removal after use; the pre-industrial block holds the spin-up window)
    blocks = []
    if forcing_mode == 'rolling':
        use = defaultdict(lambda: [math.inf, -math.inf, 0])
        for j, (s, e) in jl:
            seg = j['segment']
            parts = seg.split('_')
            clim, period = parts[1], parts[-1].split('/')[0]
            key = (j['gcm'], clim if period != 'spinup' else 'picontrol', 'pre' if period in ('spinup', 'pre-industrial') else period)
            u = use[key]; u[0] = min(u[0], s); u[1] = max(u[1], e)
        for (g, clim, blk), (s, e, _) in use.items():
            ny = {'pre': 249, 'historical': 172, 'future': 79}[blk]
            blocks.append((s - 24.0, e, ny * fs['climate_bytes_per_year'] / TB))
    for t in ts:
        daily = monthly = states = prod = 0.0
        for j, (s, e) in jl:
            reported = j['period'] != 'spinup'
            frac = min(1.0, max(0.0, (t - s) / (e - s))) if t > s else 0.0
            yrs = j['years'] * frac
            if reported:
                if not (rule in ('delete-daily', 'delete-5min') and t >= e + lag):
                    daily += yrs * dsz
                if not (rule == 'delete-5min' and t >= e + lag):
                    monthly += yrs * msz
                if t >= e + lag:
                    prod += j['years'] * (dsz + msz) * PRODUCT_FRACTION
            if t >= e:
                states += sp['state_bytes']
        if forcing_mode == 'rolling':
            forcing = sum(b for s, e, b in blocks if s <= t <= e + lag)
        else:
            forcing = sum(per_gcm_forcing for g, r in gcm_release.items() if t >= r - 24.0)
        rows.append(dict(hour=t, forcing_tb=forcing, states_tb=states / TB, monthly_tb=monthly / TB,
                         daily_tb=daily / TB, products_tb=prod / TB,
                         total_tb=forcing + (states + monthly + daily + prod) / TB))
    return rows


# ------------------------------------------------------------------------------------------------ scenarios
SCENARIOS = {
    'S1': dict(title="All 18 experiments, two GCMs, daily output 'if possible', all 5' output kept",
               subset='all-18', gcms=2, daily='if-possible', compress=None, rule='keep', forcing='full',
               short="all 18, 2 GCMs, daily 'if possible', keep all"),
    'S2': dict(title="1st priority, two GCMs, protocol-daily only, 5' daily deleted after aggregation",
               subset='priority-1', gcms=2, daily='protocol', compress=None, rule='delete-daily', forcing='full',
               short='1st priority, 2 GCMs, protocol-daily, delete daily after QC'),
    'S3': dict(title="Group I-II, EC-Earth3-ESM-1-1 first (one GCM), protocol-daily, 5' daily deleted after "
                     "aggregation", subset='group-I-II', gcms=1, daily='protocol', compress=None,
               rule='delete-daily', forcing='full', short='Group I-II, EC-Earth only, protocol-daily, delete daily after QC'),
    'S4': dict(title="All except extrasoc (D06), two GCMs staggered, 1st priority first, protocol-daily, "
                     "5' daily deleted after aggregation",
               subset='all-but-extrasoc', gcms=2, daily='protocol', compress=None, rule='delete-daily',
               forcing='full', priority_first=True,
               short='all but extrasoc, 2 GCMs, 1st priority first, protocol-daily, delete daily after QC'),
}


def run_scenario(name, sc, base, sub, sp, fs, var_est, cf, a, hours_per_year=None):
    gcms = GCMS[:sc['gcms']]
    segs = resolve_subset(base, sub[sc['subset']][1], a.spinup_years, gcms)
    d = demand(segs, sp, fs, var_est, sc['daily'], hours_per_year, sc.get('compress'), cf)
    release = {g: i * a.second_gcm_offset_days * 24.0 for i, g in enumerate(gcms)}
    prio = {}
    if sc.get('priority_first'):
        p1 = set(sub['priority-1'][1])
        for sid, s in segs.items():
            prio[sid] = 0 if any(e in p1 for e in s.experiments) else 1
    sch = schedule(d['jobs_list'], a.nodes, a.queue_wait_hours, release, prio)
    tl = storage_timeline(d['jobs_list'], sch, d, sp, fs, sc['rule'], release, sc['forcing'])
    finish_h = max(e for _, e in sch.values())
    final = tl[-1]
    return dict(segs=segs, d=d, sch=sch, tl=tl, finish_h=finish_h, release=release,
                peak_tb=max(r['total_tb'] for r in tl), final_tb=final['total_tb'], final=final)


# ------------------------------------------------------------------------------------------------ figures
def fig_storage(results, a):
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    comps = [('forcing_tb', 'climate forcing', '#8c8c8c'), ('states_tb', 'states', '#6a3d9a'),
             ('monthly_tb', "5' monthly", '#1f78b4'), ('daily_tb', "5' daily", '#a6cee3'),
             ('products_tb', '0.5° products', '#33a02c')]
    n = len(results)
    fig, axes = plt.subplots(n, 1, figsize=(10, 2.6 * n), sharex=True)
    t0 = dt.datetime.combine(a.start, dt.time())
    ymax = max(r['peak_tb'] for r in results.values()) * 1.1
    for ax, (name, r) in zip(axes, results.items()):
        x = [t0 + dt.timedelta(hours=row['hour']) for row in r['tl']]
        ys = [[row[c] for row in r['tl']] for c, _, _ in comps]
        ax.stackplot(x, ys, labels=[l for _, l, _ in comps], colors=[c for _, _, c in comps], alpha=0.9)
        ax.axhline(a.free_tb, color='#d62728', lw=1, ls='--')
        ax.text(x[0], a.free_tb, f' /lustre free on {a.free_date}: {a.free_tb:.0f} TB', color='#d62728',
                va='bottom', fontsize=8)
        ax.set_ylim(0, max(ymax, a.free_tb * 1.15))
        ax.set_ylabel('TB')
        ax.set_title(f'{name}: {SCENARIOS[name]["short"]} — peak {r["peak_tb"]:.1f} TB, end {r["final_tb"]:.1f} TB',
                     fontsize=9, loc='left')
    axes[0].legend(loc='upper left', fontsize=8, ncol=5)
    fig.autofmt_xdate()
    fig.tight_layout()
    p = f'{csp.figures()}/storage_over_time.png'
    fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_gantt(results, a):
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    col = {'spinup': '#b15928', 'pre-industrial': '#ff7f00', 'historical': '#1f78b4', 'future': '#33a02c'}
    n = len(results)
    heights = [max(3, 0.12 * len(r['sch'])) for r in results.values()]
    fig, axes = plt.subplots(n, 1, figsize=(11, sum(heights) + 0.6 * n), gridspec_kw=dict(height_ratios=heights))
    t0 = dt.datetime.combine(a.start, dt.time())
    for ax, (name, r) in zip(axes, results.items()):
        jobs = sorted(r['d']['jobs_list'], key=lambda j: r['sch'][j['job']][0])
        crit = critical_jobs(r)
        for i, j in enumerate(jobs):
            s, e = r['sch'][j['job']]
            ax.barh(i, (e - s) / 24, left=(s / 24), color=col[j['period']], height=0.8,
                    hatch='////' if j['gcm'] != GCMS[0] else None,
                    edgecolor='k' if j['job'] in crit else ('white' if j['gcm'] != GCMS[0] else 'none'), lw=0.8)
        ax.set_yticks([])
        ax.set_ylim(len(jobs), -1)
        fin = t0 + dt.timedelta(hours=r['finish_h'])
        ax.set_title(f'{name}: {len(jobs)} jobs on {a.nodes} nodes, finish day {r["finish_h"] / 24:.0f} '
                     f'({fin:%Y-%m-%d} if started {a.start}); outlined = chain that ends last; hatched = {GCMS[1]}', fontsize=9, loc='left')
        ax.set_xlabel('days after start')
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in col.values()]
    axes[0].legend(handles, list(col), fontsize=8, loc='lower right')
    fig.tight_layout()
    p = f'{csp.figures()}/critical_path_gantt.png'
    fig.savefig(p, dpi=130); plt.close(fig)
    return p


def critical_jobs(r):
    """Jobs of the chain that ends last (following parents back from the last job)."""
    by = {j['job']: j for j in r['d']['jobs_list']}
    last = max(r['sch'], key=lambda k: r['sch'][k][1])
    out = set()
    while last:
        out.add(last); last = by[last]['parent']
    return out


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--spinup-years', type=int, default=50)
    ap.add_argument('--start', type=dt.date.fromisoformat, default=dt.date(2026, 11, 2),
                    help='assumed first production day (D01 frozen, forcing of the first segments accepted)')
    ap.add_argument('--nodes', type=int, default=6)
    ap.add_argument('--queue-wait-hours', type=float, default=0.0)
    ap.add_argument('--second-gcm-offset-days', type=float, default=14.0)
    ap.add_argument('--free-tb', type=float, default=133.0)
    ap.add_argument('--free-date', default='2026-10-05')
    ap.add_argument('--mem-gb', type=float, default=None, help='memory request per run (default: resources file)')
    ap.add_argument('--no-report', action='store_true')
    a = ap.parse_args()
    os.chdir(csp.REPO)
    base = rc.load_campaign(CAMPAIGN)
    res_cfg = yaml.safe_load(open(RESOURCES))
    a.mem_gb = a.mem_gb or float(str(res_cfg['mem']).rstrip('G'))
    pool = protocol_pool(base)
    sub = subsets(pool)

    recs = run_records()
    sp = speed_and_size(recs)
    var_rows, var_est = variable_tables(sp)
    cf = compression_factors()
    fs = forcing_sizes()
    prod = producer_speed()
    cl = cluster_state()
    eur_node_h = CORES_PER_NODE * EUR_CORE_HOUR + a.mem_gb * EUR_GB_HOUR
    T = {}   # everything the report uses

    # --- measured speed
    T['years'] = [dict(run=r['run'], year=r['year'], hours=round(r['hours'], 3), core_hours=round(r['hours'] * 128, 1),
                       start_utc=dt.datetime.fromtimestamp(r['t0'], dt.timezone.utc).strftime('%Y-%m-%d %H:%M'),
                       overlap_with_measurement=round(r.get('measure_overlap', 0.0), 2),
                       daily_gb=round(r['daily_bytes'] / GB, 3), monthly_gb=round(r['monthly_bytes'] / GB, 3))
                  for v in recs.values() for r in v['years']]
    write_csv('model_year_timing.csv', T['years'])
    T['runs'] = [dict(run=k, run_id=v['run_id'], status=v['status'], job=v['job'], node=v['node'],
                      init_h=round(v['init_s'] / 3600, 3) if v['init_s'] else '',
                      state_write_h=round(v['state_write_s'] / 3600, 3) if v['state_write_s'] else '',
                      complete_years=len(v['years']), state_gb=round((v['state_bytes'] or 0) / GB, 3),
                      maxrss_gb_per_rank=round(v['maxrss_kb'] / 1e6, 1) if v['maxrss_kb'] else '',
                      vic_run_s=v['vic_timing'].get('Run Time', {}).get('wall_s', ''),
                      vic_force_s=v['vic_timing'].get('Force Time', {}).get('wall_s', ''),
                      vic_write_s=v['vic_timing'].get('Write Time', {}).get('wall_s', ''))
                 for k, v in recs.items()]
    write_csv('smoke_runs.csv', T['runs'])
    per_year = dict(hours_planning=sp['hours_per_year'], hours_low=sp['hours_per_year_low'],
                    hours_high=sp['hours_per_year_high'], hours_slow_case=sp['hours_per_year_slow'],
                    hours_without_measurement_load=sp['hours_per_year_quiet'], years_without_measurement_load=sp['quiet_years'],
                    init_hours=sp['init_hours'], state_write_hours=sp['state_write_hours'], basis=sp['basis'],
                    core_hours_planning=sp['hours_per_year'] * 128, core_hours_high=sp['hours_per_year_high'] * 128,
                    daily_gb=sp['daily_bytes'] / GB, monthly_gb=sp['monthly_bytes'] / GB,
                    state_gb=sp['state_bytes'] / GB, eur_per_node_hour=eur_node_h, mem_gb=a.mem_gb,
                    maxrss_gb_per_rank=sp['maxrss_gb_per_rank'])
    write_csv('per_model_year.csv', [per_year])
    if var_rows:
        write_csv('output_by_variable.csv', sorted(var_rows, key=lambda r: (r['stream'], -r['bytes_per_year'])))
        write_csv('daily_cost_by_variable.csv', sorted(var_est['est'].values(), key=lambda r: -r['daily_bytes_per_year']))

    # --- segments and demand per subset
    seg_tables, dem_rows = {}, []
    for key, (desc, ids) in sub.items():
        segs1 = resolve_subset(base, ids, a.spinup_years, GCMS[:1])
        seg_tables[key] = segment_rows(segs1)
        write_csv(f'segments_{key}.csv', seg_tables[key])
        for ng in (1, 2):
            segs = resolve_subset(base, ids, a.spinup_years, GCMS[:ng])
            d = demand(segs, sp, fs, var_est)
            cp = critical_path_hours(d['jobs_list'])
            dem_rows.append(dict(subset=key, description=desc, experiments=len(ids), gcms=ng,
                                 segments=d['segments'], jobs=d['jobs'], model_years=d['model_years'],
                                 spinup_years=d['spinup_years'], reported_years=d['reported_years'],
                                 core_hours=round(d['core_hours']), node_hours=round(d['node_hours']),
                                 eur=round(d['node_hours'] * eur_node_h),
                                 output_5min_tb=round(d['output_tb'], 2), daily_tb=round(d['daily_tb'], 2),
                                 monthly_tb=round(d['monthly_tb'], 2), state_tb=round(d['state_tb'], 3),
                                 climate_forcing_tb=round(d['climate_forcing_tb'] * ng, 2),
                                 dhf_forcing_tb=round(d['dhf_forcing_tb'], 3),
                                 critical_path_days=round(cp / 24, 1)))
    write_csv('demand.csv', dem_rows)
    T['demand'] = dem_rows

    # --- spin-up length (option d) and finishing dates by node count
    spin_rows = []
    for n in (30, 50, 100, 200):
        for key in ('all-18', 'priority-1'):
            segs = resolve_subset(base, sub[key][1], n, GCMS[:1])
            d = demand(segs, sp, fs, var_est)
            spin_rows.append(dict(spinup_years=n, subset=key, spinup_model_years_per_gcm=d['spinup_years'],
                                  core_hours_per_gcm=round(d['core_hours']),
                                  spinup_share=round(d['spinup_years'] / d['model_years'], 3),
                                  critical_path_days=round(critical_path_hours(d['jobs_list']) / 24, 1)))
    write_csv('option_spinup.csv', spin_rows)
    T['spin'] = spin_rows

    # --- scenarios
    results = {k: run_scenario(k, sc, base, sub, sp, fs, var_est, cf, a) for k, sc in SCENARIOS.items()}
    high = {k: run_scenario(k, sc, base, sub, sp, fs, var_est, cf, a, sp['hours_per_year_slow'])
            for k, sc in SCENARIOS.items()}
    sc_rows = []
    for k, r in results.items():
        d = r['d']
        fin = a.start + dt.timedelta(hours=r['finish_h'])
        fin_hi = a.start + dt.timedelta(hours=high[k]['finish_h'])
        sc_rows.append(dict(scenario=k, title=SCENARIOS[k]['title'], experiments=len(sub[SCENARIOS[k]['subset']][1]),
                            gcms=SCENARIOS[k]['gcms'], model_years=d['model_years'], jobs=d['jobs'],
                            core_hours=round(d['core_hours']), eur=round(d['node_hours'] * eur_node_h),
                            nodes=a.nodes, wall_days=round(r['finish_h'] / 24, 1), finish=str(fin),
                            wall_days_slow=round(high[k]['finish_h'] / 24, 1), finish_slow=str(fin_hi),
                            peak_tb=round(r['peak_tb'], 1), final_tb=round(r['final_tb'], 1),
                            final_5min_tb=round(r['final']['daily_tb'] + r['final']['monthly_tb'], 1),
                            final_states_tb=round(r['final']['states_tb'], 2),
                            final_products_tb=round(r['final']['products_tb'], 2),
                            final_forcing_tb=round(r['final']['forcing_tb'], 1),
                            weeks_before_ar7=round((AR7_DEADLINE - fin).days / 7, 1)))
        write_csv(f'schedule_{k}.csv', [dict(job=j['job'], period=j['period'], gcm=j['gcm'], years=j['years'],
                                             start_day=round(r['sch'][j['job']][0] / 24, 2),
                                             end_day=round(r['sch'][j['job']][1] / 24, 2))
                                        for j in sorted(d['jobs_list'], key=lambda j: r['sch'][j['job']][0])])
        write_csv(f'storage_timeline_{k}.csv', [{kk: (round(v, 3) if isinstance(v, float) else v)
                                                 for kk, v in row.items()} for row in r['tl']])
    write_csv('scenarios.csv', sc_rows)
    T['scenarios'] = sc_rows

    # finish day by node count (one row per scenario and node count)
    nodes_rows = []
    for k, sc in SCENARIOS.items():
        for n in (3, 4, 6, 8, 12, 16):
            aa = copy.copy(a); aa.nodes = n
            r = run_scenario(k, sc, base, sub, sp, fs, var_est, cf, aa)
            nodes_rows.append(dict(scenario=k, nodes=n, wall_days=round(r['finish_h'] / 24, 1),
                                   finish=str(a.start + dt.timedelta(hours=r['finish_h'])),
                                   peak_tb=round(r['peak_tb'], 1)))
    write_csv('finish_by_nodes.csv', nodes_rows)
    T['nodes'] = nodes_rows

    # --- options (one change at a time against the reference: all-18, two GCMs, protocol daily, keep, full forcing)
    ref = dict(subset='all-18', gcms=2, daily='protocol', compress=None, rule='keep', forcing='full')
    opts = [('reference', 'all 18, two GCMs, protocol-daily, zlib 2 (as now), all kept', {})]
    opts += [('a: daily if possible', "daily soilmoist, tsl, snd, snm, lai added", dict(daily='if-possible')),
             ('a: all daily', 'every VIC output of the monthly stream also daily', dict(daily='all'))]
    for v in ('zlib1-shuffle', 'zlib4-shuffle', 'zlib6-shuffle', 'zlib9-shuffle', 'zlib4-shuffle-gbr4',
              'zlib4-shuffle-gbr3', 'zstd3-shuffle'):
        if ('daily', v) in cf:
            how = 'post-run rewrite (one core per file)' if post_run(v) else 'VIC COMPRESS level at write time'
            opts.append((f'b: {v}', how, dict(compress=v)))
    opts += [('c: delete daily after QC', "5' daily deleted after the 0.5° products pass QC", dict(rule='delete-daily')),
             ('c: delete daily and monthly', "only states, run records and 0.5° products kept", dict(rule='delete-5min')),
             ('e: rolling climate forcing', 'climate forcing years exist only while used', dict(forcing='rolling'))]
    opt_rows = []
    for name, desc, ch in opts:
        sc = dict(ref, **ch, title=desc)
        SCENARIOS['_opt'] = sc
        r = run_scenario('_opt', sc, base, sub, sp, fs, var_est, cf, a)
        d = r['d']
        opt_rows.append(dict(option=name, description=desc, core_hours=round(d['core_hours']),
                             postrun_core_hours=round(d['postrun_core_hours']),
                             hours_per_model_year=round(d['hours_per_year'], 3),
                             output_5min_tb=round(d['output_tb'], 1), daily_tb=round(d['daily_tb'], 1),
                             monthly_tb=round(d['monthly_tb'], 1), state_tb=round(d['state_tb'], 2),
                             climate_forcing_tb=round(d['climate_forcing_tb'] * 2, 1),
                             peak_tb=round(r['peak_tb'], 1), final_tb=round(r['final_tb'], 1),
                             wall_days=round(r['finish_h'] / 24, 1)))
    SCENARIOS.pop('_opt')
    write_csv('options.csv', opt_rows)
    T['options'] = opt_rows

    # --- forcing
    T['forcing'] = dict(climate_gb_per_year=fs['climate_bytes_per_year'] / GB,
                        dhf={f: {k: v / GB for k, v in d.items()} for f, d in fs['dhf'].items()},
                        raw={f'{k[0]}/{k[1]}': v / GB for k, v in fs['raw'].items()}, producer=prod)
    write_csv('forcing_sizes.csv', [dict(item=f'forcing/{f}/{k}', gb=round(v, 2)) for f, d in T['forcing']['dhf'].items()
                                    for k, v in d.items()] +
              [dict(item='forcing/climate per model year (7 variables, measured esm-hist 2011-2020)',
                    gb=round(T['forcing']['climate_gb_per_year'], 2))] +
              [dict(item=f'raw climate {k}', gb=round(v, 1)) for k, v in T['forcing']['raw'].items()])
    if prod:
        write_csv('forcing_producer.csv', prod)
    T['cluster'] = cl
    json.dump(dict(cluster=cl, per_year=per_year, args={k: str(v) for k, v in vars(a).items()}),
              open(f'{csp.tables()}/inputs.json', 'w'), indent=1)

    figs = [fig_storage(results, a), fig_gantt(results, a)]
    print('\n'.join(figs))
    if not a.no_report:
        import report
        report.write(T, sp, var_est, cf, results, sub, seg_tables, a, eur_node_h)


if __name__ == '__main__':
    main()
