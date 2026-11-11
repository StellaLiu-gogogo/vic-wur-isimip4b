"""The product set of a campaign (D11): its expected product units, derived from the campaign and the protocol commit it
pins, and the state of every unit, of its source chunk and of every segment. Used by submit.py, collect_set.py and
check_set.py.

Expected units. The stage is self-contained (user, 2026-11-10), so this module holds its own copy of the rules by
which workflow/05_simulation/render/resolve_campaign.py and render_run.py derive the reported segments and their
chunks, with the same behaviour (tests/unit/test_postprocessing_set.py compares the two on the campaign files):

- the experiments of the campaign (ids, priority or all) among those of the protocol for its sector and simulation
  round, without the campaign's exclusions;
- per GCM, experiment and reported period (pre-industrial, historical, future) the period entry of the experiment: a
  mapping {climate, soc[, soc_sens | climate_sens]} is the segment <climate>_<soc>_<sens>_<period>; "Identical to the
  similar **<climate>/<soc>[/<sens>]** run above." is the segment of that composition, which some experiment of the
  sector must define explicitly; "Does not have to be simulated ..." in the pre-industrial period is no segment; the
  campaign's sensitivity_equivalence maps a sens scenario to another one; spin-ups are not reported;
- the years of a segment from definitions/period.yaml; a restricted campaign (non-production) has one run per label,
  `<segment-id>__<label>`, over the label's years, for the segments of the restricted periods;
- a run longer than chunk_years (the campaign's resources file, or the restriction label's own value) is split into
  chunks of chunk_years years starting at its first year, the last one shorter; each chunk is one product unit, and
  an unchunked run is one unit.
The run manifest of every run that exists must name the same period and chunks; otherwise the derivation stops.

Unit status (D11): `missing` (no unit directory), `present` (made, not accepted: not checked yet, check warning or
not_checked, a source that is not accepted), `accepted` (check passed from a clean repository on the unchanged unit
record, made and checked from a clean repository, source accepted and still the latest completed attempt with its
passed chunk check), `failed` (check failed, the unit record changed after its check, a product file whose size
differs from the record, or a newer attempt of the source chunk). A check whose only warning is the range check
(values outside the protocol's valid range, kept unclipped) counts as passed (D11 amendment 2026-11-11, user); the
number of such values per product file is recorded with the unit. A segment is accepted when every unit is accepted
and the whole-run check of its run has passed, bound to the latest completed attempt of every chunk.
"""
import json
import os
import re

import support

PERIODS = ('pre-industrial', 'historical', 'future')
IDENTICAL = re.compile(r'Identical to the similar \*\*([^*]+)\*\* run', re.I)
NOT_SIMULATED = re.compile(r'Does not have to be simulated, spin-up should be based on the (\d{4}) DHF', re.I)
UNIT_STATUSES = ('missing', 'present', 'accepted', 'failed')
RANGE_CHECK = 'valid_range'          # its warning alone does not hold back acceptance (D11 amendment 2026-11-11)
DECISIONS = ('D07', 'D08', 'D09', 'D10', 'D11')
DECISION_TABLE = os.path.join(support.REPO, 'docs', 'decisions', 'open-decisions.md')


# ------------------------------------------------------------------------------------------------ expected units
def protocol(camp, W):
    """(experiments, {period: (first year, last year)}) of the protocol commit the campaign pins; stops unless the
    snapshot's COMMIT file names that commit."""
    p = os.path.join(W, camp['protocol']['path'])
    rnd = camp['protocol']['simulation_round']
    with open(os.path.join(p, 'COMMIT')) as fh:
        have = fh.read().strip()
    if have != camp['protocol']['commit']:
        raise SystemExit(f'protocol snapshot {p} is commit {have}, the campaign pins {camp["protocol"]["commit"]}')
    experiments = support.load_yaml(os.path.join(p, 'definitions', 'experiments', f'{rnd}.yaml'))
    years = {}
    for e in support.load_yaml(os.path.join(p, 'definitions', 'period.yaml')):
        if 'simulation_rounds' in e and rnd not in e['simulation_rounds']:
            continue
        pick = (lambda v: v[rnd] if isinstance(v, dict) else v)  # noqa: E731
        years[e['specifier']] = (int(pick(e['start_year'])), int(pick(e['end_year'])))
    return experiments, years


def period_entry(exp, period):
    """('explicit' | 'identical', (climate, soc, sens)) or ('not_simulated', None)."""
    e = exp.get(period)
    if isinstance(e, dict):
        return 'explicit', (e['climate'], e['soc'], e.get('soc_sens') or e.get('climate_sens') or 'default')
    if isinstance(e, str):
        e = ' '.join(e.split())
        m = IDENTICAL.search(e)
        if m:
            parts = m.group(1).strip().split('/')
            if len(parts) not in (2, 3):
                raise SystemExit(f'{exp["specifier"]} {period}: cannot read reference "{m.group(1)}"')
            return 'identical', (parts[0], parts[1], parts[2] if len(parts) == 3 else 'default')
        if period == 'pre-industrial' and NOT_SIMULATED.search(e):
            return 'not_simulated', None
    raise SystemExit(f'{exp["specifier"]} {period}: unsupported period entry {e!r}')


def experiments_of(camp, experiments):
    """(chosen experiments, pool of the sector and round) of the campaign."""
    sel = camp['experiments']
    rnd, sector = camp['protocol']['simulation_round'], camp['protocol']['sector']
    pool = [e for e in experiments if sector in e.get('sectors', []) and rnd in e.get('simulation_rounds', [rnd])]
    by_id = {e['specifier']: e for e in pool}
    if 'ids' in sel:
        unknown = [i for i in sel['ids'] if i not in by_id]
        if unknown:
            raise SystemExit(f'experiments not defined for {sector} in {rnd}: {unknown}')
        chosen = [by_id[i] for i in sel['ids']]
    elif 'priority' in sel:
        chosen = [e for e in pool if e.get('priority') in sel['priority']]
    elif sel.get('all'):
        chosen = list(pool)
    else:
        raise SystemExit('experiments: give ids, priority, or all: true')
    excluded = {x['experiment'] for x in camp.get('exclusions') or []}
    unknown = sorted(excluded - set(by_id))
    if unknown:
        raise SystemExit(f'exclusion of unknown experiments {unknown}')
    return [e for e in chosen if e['specifier'] not in excluded], pool


def chunk_plan(start_year, end_year, chunk_years):
    """[(first, last)] of the chunks of a run (render_run.chunk_plan): one piece when the run is not longer than
    chunk_years."""
    if not chunk_years or end_year - start_year + 1 <= chunk_years:
        return [(start_year, end_year)]
    return [(y, min(y + chunk_years - 1, end_year)) for y in range(start_year, end_year + 1, chunk_years)]


def expected_runs(camp, W):
    """Reported runs of the campaign in segment order, each {run_id, segment_id, gcm, segment_key, period,
    start_year, end_year, chunked, units: [{chunk, years}]}; `chunk` is the chunk ID or None for an unchunked run."""
    experiments, years = protocol(camp, W)
    chosen, pool = experiments_of(camp, experiments)
    equiv = {k: v['same_as'] for k, v in (camp.get('sensitivity_equivalence') or {}).items()}
    eq = (lambda c: (c[0], c[1], equiv.get(c[2], c[2])))  # noqa: E731
    defined = {p: {eq(v) for e in pool for k, v in [period_entry(e, p)] if k == 'explicit'} for p in PERIODS}
    segments = {}
    for gcm in camp['gcms']:
        for e in chosen:
            for p in PERIODS:
                kind, comp = period_entry(e, p)
                if kind == 'not_simulated':
                    continue
                comp = eq(comp)
                if kind == 'identical' and comp not in defined[p]:
                    raise SystemExit(f'{e["specifier"]}: reference {"/".join(comp)} in {p} is not defined')
                key = '_'.join((*comp, p))
                segments.setdefault(f'{gcm}_{key}', (gcm, key, p))
    resources = support.load_yaml(os.path.join(support.REPO, camp['resources']))
    restriction = camp.get('restriction')
    runs = []
    order = {p: i for i, p in enumerate(PERIODS)}
    for sid, (gcm, key, p) in sorted(segments.items(), key=lambda kv: (kv[1][0], order[kv[1][2]], kv[0])):
        if restriction:
            if p not in restriction['periods']:
                continue
            variants = [(f'{sid}__{label}', [int(v) for v in r['years']], r.get('chunk_years',
                                                                                 resources.get('chunk_years')))
                        for label, r in sorted(restriction['runs'].items())]
        else:
            variants = [(sid, list(years[p]), resources.get('chunk_years'))]
        for run_id, (y0, y1), cy in variants:
            if not years[p][0] <= y0 <= y1 <= years[p][1]:
                raise SystemExit(f'{run_id}: years {y0}-{y1} outside the segment {years[p][0]}-{years[p][1]}')
            plan = chunk_plan(y0, y1, cy)
            chunked = len(plan) > 1
            runs.append({'run_id': run_id, 'segment_id': sid, 'gcm': gcm, 'segment_key': key, 'period': p,
                         'start_year': y0, 'end_year': y1, 'chunked': chunked,
                         'units': [{'chunk': f'{a:04d}-{b:04d}' if chunked else None, 'years': [a, b]}
                                   for a, b in plan]})
    return runs


def run_manifest(W, camp, run):
    """The run manifest of an expected run, or None when the run has not been rendered; stops when its period or
    chunks differ from the derivation."""
    p = os.path.join(W, 'runs', camp['campaign_id'], run['run_id'], 'run_manifest.json')
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        man = json.load(fh)
    have = (int(man['period']['start'][:4]), int(man['period']['end'][:4]),
            [(c['id'], c['start_year'], c['end_year']) for c in man.get('chunks') or []])
    want = (run['start_year'], run['end_year'],
            [(u['chunk'], *u['years']) for u in run['units']] if run['chunked'] else [])
    if have != want or man.get('segment_id') != run['segment_id']:
        raise SystemExit(f'{run["run_id"]}: the run manifest (years {have[0]}-{have[1]}, chunks {have[2]}) differs '
                         f'from the units derived from the campaign (years {want[0]}-{want[1]}, chunks {want[2]})')
    return man


# ------------------------------------------------------------------------------------------------ sources
def latest_attempt(man, chunk):
    at = [x for x in man.get('attempts') or [] if x.get('chunk') == chunk]
    return at[-1] if at else {}


def source_state(W, man, chunk):
    """The attempt and the check a unit relies on, and what keeps them from being accepted (problems): the run must be
    a production run, the latest attempt of the chunk completed, and the chunk check (the run check of an unchunked
    run) passed from a clean repository and bound to that attempt."""
    att = latest_attempt(man, chunk)
    qc = os.path.join(W, 'qc', man['run_dir'], *(['chunks', chunk] if chunk else []), 'summary.json')
    check = {'summary': os.path.relpath(qc, W), 'status': 'not_checked', 'bound': False}
    if os.path.exists(qc):
        with open(qc) as fh:
            s = json.load(fh)
        b = s.get('binding') or {}
        check.update({'sha256': support.sha256(qc), 'status': s.get('status', 'not_checked'),
                      'bound': b.get('attempt') == att.get('attempt') and
                      b.get('slurm_job_id') == att.get('slurm_job_id') and s.get('code_dirty') is False})
    problems = []
    if not man.get('production'):
        problems.append('not a production run')
    if att.get('status') != 'completed':
        problems.append(f'latest attempt is {att.get("status")}')
    if check['status'] != 'passed' or not check['bound']:
        problems.append(f'check {check["status"]}, bound to the attempt: {check["bound"]}')
    attempt = {k: att.get(k) for k in ('attempt', 'slurm_job_id', 'status', 'ended_at')}
    return attempt, check, problems


def whole_run_check(W, man):
    """State of the whole-run check of a run: {summary, status, bound}. For a chunked run it must be bound to the
    latest attempt of every chunk (binding.chunk_attempts), each completed; for an unchunked run to its attempt."""
    p = os.path.join(W, 'qc', man['run_dir'], 'summary.json')
    out = {'summary': os.path.relpath(p, W), 'status': 'not_checked', 'bound': False}
    if not os.path.exists(p):
        return out
    with open(p) as fh:
        s = json.load(fh)
    b = s.get('binding') or {}
    chunks = [c['id'] for c in man.get('chunks') or []]
    if chunks:
        latest = {c: latest_attempt(man, c) for c in chunks}
        bound = all(a.get('status') == 'completed' for a in latest.values()) and \
            b.get('chunk_attempts') == {c: a.get('attempt') for c, a in latest.items()}
    else:
        a = latest_attempt(man, None)
        bound = a.get('status') == 'completed' and b.get('attempt') == a.get('attempt') and \
            b.get('slurm_job_id') == a.get('slurm_job_id')
    out.update({'status': s.get('status', 'not_checked'), 'bound': bool(bound and s.get('code_dirty') is False),
                'sha256': support.sha256(p)})
    return out


# ------------------------------------------------------------------------------------------------ units
def set_paths(W, camp, scratch):
    """(product-set directory, its QC directory) below the workdir or scratch/<task>/."""
    root = support.output_root(W, scratch)
    pset = camp['campaign_id']
    return os.path.join(root, 'postprocessed', pset), os.path.join(root, 'qc', 'postprocessed', pset)


def unit_rel(run, unit):
    return f'{run["gcm"]}/{run["segment_key"]}/{unit["years"][0]}-{unit["years"][1]}'


def unit_state(W, set_dir, qc_dir, run, unit, man):
    """{unit, status, reasons, check, ...} of one expected unit (statuses in the module docstring)."""
    rel = unit_rel(run, unit)
    d = os.path.join(set_dir, rel)
    y0, y1 = unit['years']
    out = {'unit': rel, 'chunk': unit['chunk'], 'years': [y0, y1], 'status': 'missing', 'reasons': []}
    staging = os.path.join(set_dir, run['gcm'], run['segment_key'], f'.writing-{y0}-{y1}')
    if os.path.exists(staging):
        out['reasons'].append(f'staging directory {os.path.relpath(staging, W)} of an interrupted job')
    if not os.path.isdir(d):
        return out
    rec = support.load_yaml(os.path.join(d, 'provenance.yaml'))
    out['files'] = rec['files']
    failed, present = [], []
    for f in rec['files']:
        p = os.path.join(d, f['name'])
        if not os.path.exists(p) or os.path.getsize(p) != f['size_bytes']:
            failed.append(f'{f["name"]} is absent or differs in size from the unit record')
    src = rec['source']
    if man is None:
        failed.append('the run manifest of the source no longer exists')
    else:
        att = latest_attempt(man, unit['chunk'])
        if att.get('attempt') != src['attempt']['attempt'] or att.get('slurm_job_id') != src['attempt']['slurm_job_id']:
            failed.append(f'the source chunk has a newer attempt ({att.get("attempt")}) than the one the unit was '
                          f'made from ({src["attempt"]["attempt"]})')
        _, _, problems = source_state(W, man, unit['chunk'])
        present += [f'source: {p}' for p in problems]
    qc = os.path.join(qc_dir, rel, 'summary.json')
    check = {'summary': os.path.relpath(qc, W), 'status': 'not_checked'}
    if os.path.exists(qc):
        with open(qc) as fh:
            s = json.load(fh)
        check['status'] = s.get('status', 'not_checked')
        check['checked_at'] = s.get('checked_at')
        checks = s.get('checks') or {}
        check['range_only'] = check['status'] == 'warning' and checks.get(RANGE_CHECK) == 'warning' and \
            all(v == 'passed' for k, v in checks.items() if k != RANGE_CHECK)
        if checks.get(RANGE_CHECK) == 'warning':
            report = support.load_yaml(os.path.join(qc_dir, rel, 'reports', 'check.json'))
            check['values_outside_valid_range'] = {
                f: v['values_outside'] for f, v in report['details'][RANGE_CHECK]['files'].items()
                if v.get('values_outside')}
        if s.get('record_sha256') != support.sha256(os.path.join(d, 'provenance.yaml')):
            failed.append('the unit record changed after its check')
        if (s.get('checked_by') or {}).get('dirty') is not False:
            present.append('checked from a repository that was not clean')
    if check['status'] == 'failed':
        failed.append('unit check failed')
    elif check['status'] != 'passed' and not check.get('range_only'):
        present.append(f'unit check {check["status"]}')
    if rec['code'].get('dirty') is not False:
        present.append('made from a repository that was not clean')
    if not src.get('accepted_source'):
        present.append('made from a source that was not accepted')
    out['check'] = check
    out['reasons'] += failed + present
    out['status'] = 'failed' if failed else ('present' if present else 'accepted')
    return out


def decisions():
    """{decision ID: status} of the decisions the products depend on, from docs/decisions/open-decisions.md (the
    status column up to its first parenthesis)."""
    out = {}
    with open(DECISION_TABLE) as fh:
        for line in fh:
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if cells and cells[0] in DECISIONS:
                out[cells[0]] = cells[-1].split('(')[0].strip()
    missing = [d for d in DECISIONS if d not in out]
    if missing:
        raise SystemExit(f'{DECISION_TABLE} has no row for {missing}')
    return out
