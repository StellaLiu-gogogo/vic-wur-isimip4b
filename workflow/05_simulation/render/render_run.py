#!/usr/bin/env python3
"""Render one or more runs of a campaign into their run directories.

For each run (resolve_campaign.py) the renderer
  1. checks the model build (builds/vic/<commit>/build_manifest.json: commit of the campaign and of
     model/vic.lock.yaml, build status, runtime modules equal to the resources; the executable sha256 is recorded
     here and checked by the job), the parameter files (present, md5 recorded in manifests/parameters/<set>.yaml;
     the md5 is checked by the job) and every forcing unit it reads (accepted: code_dirty false and qc.status
     passed; made on the campaign's domain and, for climate, elevation);
  2. builds the forcing view <run>/forcing/<family>/ of links named by simulation year (forcing_years.py);
  3. renders the VIC global-parameter file from templates/vic/global_param.txt and the Slurm job from
     templates/slurm/vic_run.sbatch;
  4. writes config/resolved.yaml (campaign, segment, run, resources and resolved inputs) and the run manifest
     run_manifest.json with status `rendered`.

Parents come from the whole campaign: a run whose parent segment is a run of the campaign starts from the parent's
end state. When the parent is not rendered in the same call (--run-id), the parent run must exist and have
completed with its end state, whose sha256 is recorded; otherwise the renderer stops. A run without a parent in the
campaign starts as the campaign's initialisation.without_parent says: `cold_start` (no INIT_STATE) or
`state_of_run` (the end state of an earlier, completed run named by initialisation.state_of_run: run_dir, state and
reason; checked and recorded like a parent state, VIC does not check the date of a state file).

Dam files (D19): parameter_set.files.dams maps soc scenario -> dam file; a run gets the file of its segment's
scenario. A run that starts from a state is checked by the D19 warm-start rule: start on 1 January; for a warm
start, the same model, executable, parameter files except the dam file, and plugins as the earlier run; and, with
the dams plugin on, for warm starts and parents alike, the same dam list (id, type, order; capacity of the dams that
can operate in the earlier run) and no dam active in the state or able to operate by its end that does not operate
in the run at its start year (check_dams_from).

Run directory: runs/<campaign-id>/<run-id>/ with config/, logs/, states/, output/, forcing/ and
run_manifest.json; with --scratch: scratch/<campaign-id>/<run-id>/ (test renders; never submitted as a
campaign run). An existing run directory is never rendered again: a retry of the same run reuses its files
(submit_run.py --retry).

Usage: render_run.py --campaign configs/campaigns/smoke.yaml [--label smoke2015] [--run-id ID] [--scratch]
"""
import argparse, datetime, hashlib, json, math, os, re, subprocess, sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import resolve_campaign as rc   # noqa: E402
import forcing_years as fy      # noqa: E402

RENDERED_BY = 'workflow/05_simulation/render/render_run.py'
VIC_TEMPLATE = 'workflow/05_simulation/templates/vic/global_param.txt'
SLURM_TEMPLATE = 'workflow/05_simulation/templates/slurm/vic_run.sbatch'
CLIMATE_VARIABLES = ('tair', 'prec', 'psurf', 'swdown', 'lwdown', 'vp', 'wind')
WATER_USE_FILES = (('MUN', 'municipal'), ('MAN', 'manufacturing'))
WATER_USE_VARIABLES = (('DEMAND', 'demand'), ('GROUNDWATER', 'groundwater_fraction'),
                       ('CONSUMPTION', 'consumption_fraction'))
PLACEHOLDER = re.compile(r'\{\{([A-Z_]+)\}\}')


class RenderError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ helpers
def file_hash(path, algo='sha256', n=1 << 24):
    h = hashlib.new(algo)
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(n), b''):
            h.update(b)
    return h.hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def git_state():
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', REPO, 'status', '--porcelain'], capture_output=True, text=True, check=True).stdout.strip())
    return commit, dirty


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fill(template, values):
    """Replace {{NAME}} placeholders; every placeholder must have a value and every value a placeholder."""
    used = set(PLACEHOLDER.findall(template))
    missing = used - set(values); unused = set(values) - used
    if missing or unused:
        raise RenderError(f'template placeholders without value {sorted(missing)}, values without placeholder '
                          f'{sorted(unused)}')
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)


def read_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------------------------------------ checks
def check_build(W, campaign, resources):
    lock = read_yaml(os.path.join(REPO, campaign['model']['lock']))
    commit = campaign['model']['commit']
    if lock['commit'] != commit:
        raise RenderError(f'campaign model commit {commit} differs from model/vic.lock.yaml {lock["commit"]}')
    bdir = f'{W}/builds/vic/{commit}'
    with open(f'{bdir}/build_manifest.json') as fh:
        bm = json.load(fh)
    if bm['model']['model_commit'] != commit or bm['status'] not in ('built', 'tested'):
        raise RenderError(f'build {bdir} is not a usable build of {commit} (status {bm["status"]})')
    exe = f'{bdir}/{bm["executable"]["path"]}'
    if [str(m) for m in resources['modules']] != bm['runtime_modules']:
        raise RenderError(f'resources modules {resources["modules"]} differ from the build runtime_modules '
                          f'{bm["runtime_modules"]}')
    if campaign.get('production') and lock.get('freeze_status') != 'frozen':
        raise RenderError('a production campaign needs a frozen model lock (D01)')
    return {'commit': commit, 'freeze_status': lock.get('freeze_status'), 'build': os.path.relpath(bdir, W),
            'build_status': bm['status'], 'build_kind': bm.get('build_kind'),
            'executable': os.path.relpath(exe, W), 'executable_sha256': bm['executable']['sha256'],
            'runtime_modules': bm['runtime_modules'], 'vic_git_tag': bm['executable'].get('vic_git_tag')}


def parameter_files(W, campaign):
    """{role: {path, md5, component, qc_status}} from the campaign and the parameter manifest. The role `dams` is a
    map soc scenario -> record (D19: one dam file per DHF scenario, the same dam list in every file); run_parameters
    picks the file of a run."""
    ps = campaign['parameter_set']
    manifest = read_yaml(os.path.join(REPO, 'manifests', 'parameters', f'{ps["id"]}.yaml'))
    by_path = {}
    for key, comp in manifest['components'].items():
        for f in comp.get('files', []):
            by_path[f['path']] = {'md5': f.get('md5'), 'manifest_entry': key, 'qc_status': comp.get('qc_status')}

    def record(role, rel):
        if rel not in by_path:
            raise RenderError(f'parameter file {rel} ({role}) is not recorded in manifests/parameters/{ps["id"]}.yaml')
        if not by_path[rel]['md5']:
            raise RenderError(f'parameter file {rel} ({role}) has no md5 in the parameter manifest')
        full = f'{W}/parameters/{ps["status"]}/{ps["id"]}/{rel}'
        if not os.path.isfile(full):
            raise RenderError(f'parameter file missing: {full}')
        return {'path': os.path.relpath(full, W), **by_path[rel]}

    out = {}
    for role, rel in ps['files'].items():
        if role == 'dams':
            if not isinstance(rel, dict) or not rel:
                raise RenderError('parameter_set.files.dams must map every soc scenario of the campaign to a dam file '
                                  '(D19: one dam file per DHF scenario)')
            out[role] = {soc: record(f'dams {soc}', f) for soc, f in rel.items()}
        else:
            out[role] = record(role, rel)
    return out


def run_parameters(params, soc):
    """Parameter files of one run: every role, with the dam file of the segment's soc scenario."""
    if soc not in params['dams']:
        raise RenderError(f'parameter_set.files.dams has no dam file for soc scenario {soc}')
    return {**params, 'dams': params['dams'][soc]}


# ------------------------------------------------------------------------------------------------ dams and states
def read_dam_list(path):
    """{id, type, capacity, year} of a dam file (numpy arrays in dam_class order)."""
    import numpy as np
    import netCDF4 as nc
    with nc.Dataset(path) as d:
        d.set_auto_mask(False)
        return {v: np.asarray(d[v][:]) for v in ('id', 'type', 'capacity', 'year')}


def dam_list_problems(parent, child, parent_last_year):
    """D19 (amended 2026-10-16): a state is restored by dam position, so parent and child (or the run that wrote a
    warm-start state and the new run) need the same `id`, `type` and order of every dam, and the same `capacity` for
    every dam that can operate in the parent (its year in the parent's file is not after the parent's last year).
    Returns a list of problems (empty when the lists agree)."""
    import numpy as np
    if len(parent['id']) != len(child['id']):
        return [f'{len(parent["id"])} dams in the parent dam file, {len(child["id"])} in the run\'s dam file']
    out = []
    for v in ('id', 'type'):
        bad = np.flatnonzero(parent[v] != child[v])
        if len(bad):
            out.append(f'{v} differs for {len(bad)} dams (dam_class {bad[:5].tolist()})')
    can = parent['year'] <= parent_last_year
    bad = np.flatnonzero(can & (parent['capacity'] != child['capacity']))
    if len(bad):
        out.append(f'capacity differs for {len(bad)} dams that can operate in the parent (dam_class {bad[:5].tolist()})')
    return out


def dams_switched_off(active, child, start_year):
    """dam_class indices that are active (in a state, or able to operate by the parent's end) but do not operate in
    the run's dam file at its start year: VIC never switches a dam off (D19), so such a dam would keep operating."""
    import numpy as np
    return np.flatnonzero(np.asarray(active, bool) & (child['year'] > start_year))


def state_dams_active(path):
    """STATE_DAM_ACTIVE of a VIC state file (dam_class) as booleans."""
    import numpy as np
    import netCDF4 as nc
    with nc.Dataset(path) as d:
        if 'STATE_DAM_ACTIVE' not in d.variables:
            raise RenderError(f'{path} has no STATE_DAM_ACTIVE; the dam states cannot be checked')
        v = d['STATE_DAM_ACTIVE']; v.set_auto_mask(False)
        a = np.asarray(v[:], float)
    return (a == 1)


def check_dams_from(parent_dam_file, parent_last_year, child_dam_file, start_year, state, run_id, what):
    """Dam checks of a run that starts from the end state of `what` (parent or earlier run): the dam lists agree
    (dam_list_problems), every dam that can operate by the end of `what` operates in the run at its start year, and,
    when the state exists, every dam active in it (STATE_DAM_ACTIVE) too."""
    import numpy as np
    parent, child = read_dam_list(parent_dam_file), read_dam_list(child_dam_file)
    probs = dam_list_problems(parent, child, parent_last_year)
    if probs:
        raise RenderError(f'{run_id}: the dam list of {what} ({parent_dam_file}) and of this run ({child_dam_file}) '
                          f'differ: {"; ".join(probs)}; VIC restores the dam states by position')
    off = dams_switched_off(parent['year'] <= parent_last_year, child, start_year)
    if state and os.path.isfile(state):
        active = state_dams_active(state)
        if len(active) != len(child['id']):
            raise RenderError(f'{run_id}: the state {state} has {len(active)} dams, the dam file {len(child["id"])}')
        off = np.union1d(off, dams_switched_off(active, child, start_year))
    if len(off):
        raise RenderError(f'{run_id}: {len(off)} dams that operate at the end of {what} do not operate in this run\'s '
                          f'dam file in {start_year} (dam_class {off[:5].tolist()}); VIC never switches a dam off (D19)')


def check_start_january(vic_text, run_id):
    """D19 warm-start rule (a): at the first step of a run with an initial state the land-use plugin applies the
    run's coverage only on 1 January (plugins/landuse/src/lu_force.c); on another date the state's coverage stays."""
    m = {k: int(re.search(rf'^{k}\s+(\d+)', vic_text, re.M).group(1)) for k in ('STARTMONTH', 'STARTDAY')}
    if (m['STARTMONTH'], m['STARTDAY']) != (1, 1):
        raise RenderError(f'{run_id}: a run that starts from a state must start on 1 January, not '
                          f'{m["STARTMONTH"]}/{m["STARTDAY"]} (D19)')


def unit_record(W, rel_unit, require_accepted=True):
    prov = read_yaml(f'{W}/forcing/{rel_unit}/provenance.yaml')
    status = prov.get('qc', {}).get('status')
    if require_accepted and (prov.get('code_dirty') is not False or status != 'passed'):
        raise RenderError(f'forcing unit {rel_unit} is not accepted (code_dirty {prov.get("code_dirty")}, '
                          f'qc.status {status})')
    files = {f['path']: f for f in prov['files']}
    return prov, files


# ------------------------------------------------------------------------------------------------ forcing view
def year_of(name):
    return int(re.search(r'_(\d{4})\.nc$', name).group(1))


def forcing_plan(W, campaign, run, alias):
    """Links of the forcing view and the forcing-unit identities: ([(link, target)], {unit: record},
    {family/variable: {sim_year: {source, rule}}})."""
    seg = run['segment']; years = range(run['start_year'], run['end_year'] + 1)
    gcm = seg['gcm']; spinup = seg['period'] == 'spinup'
    dhf = campaign['dhf_forcing']
    links, units, mapping = [], {}, {}

    def add_unit(rel_unit, family_key, link_dir, pattern, year_map):
        prov, files = unit_record(W, rel_unit)
        uyears = sorted(year_of(p) for p in files if re.fullmatch(pattern.format(year=r'\d{4}'), p))
        ymap = year_map(uyears, prov)
        rec = {'forcing_unit': rel_unit, 'code_commit': prov['code_commit'], 'created_at': prov['created_at'],
               'qc_status': prov['qc']['status'], 'files': {}}
        mapping[family_key] = {}
        for y in years:
            src, rule = ymap[y]
            sname = pattern.format(year=src); lname = pattern.format(year=y)
            target = f'{W}/forcing/{rel_unit}/{sname}'
            links.append((f'{link_dir}/{lname}', target))
            rec['files'][sname] = {'path': f'forcing/{rel_unit}/{sname}', 'sha256': files[sname]['sha256']}
            mapping[family_key][y] = {'source': f'forcing/{rel_unit}/{sname}', 'rule': rule}
        units[rel_unit] = rec

    climate_alias = alias
    for var in CLIMATE_VARIABLES:
        rel = f'climate/{gcm}/{climate_alias}/{var}'
        pat = f'{var}_{gcm}_{climate_alias}_' + '{year}.nc'
        if spinup:
            win = (campaign.get('spinup') or {}).get('climate_cycle')
            if not win:
                raise RenderError(f'{run["run_id"]}: a spin-up needs the campaign key spinup.climate_cycle')
            # a start year of the unit made for this window is used as itself (D20, forcing_years.map_cycle)
            add_unit(rel, f'climate/{var}', f'climate/{var}', pat, lambda uy, pv, w=win: fy.map_cycle(
                years, w, uy, pv.get('start_years'), pv.get('cycle_windows')))
        else:
            add_unit(rel, f'climate/{var}', f'climate/{var}', pat,
                     lambda uy, pv: fy.map_identity_or_constant(years, uy, constant=False))
    usoc = dhf['units'][seg['soc']]
    constant = usoc in dhf['constant']
    if spinup and not constant:
        raise RenderError(f'spin-up DHF {usoc} is not declared constant')
    if campaign['plugins']['landuse']['enabled']:
        add_unit(f'landuse/{usoc}', 'landuse', 'landuse', f'coverage_{usoc}_' + '{year}.nc',
                 lambda uy, pv: fy.map_identity_or_constant(years, uy, constant=constant))
    if campaign['plugins']['water_use']['enabled']:
        for _, sector in WATER_USE_FILES:
            if sector not in campaign['plugins']['water_use']['sectors']:
                continue
            for _, var in WATER_USE_VARIABLES:
                stem = f'{sector}_{var}_{usoc}_'
                key = f'water_use/{sector}_{var}'
                prov_rel = f'water_use/{usoc}'
                # all six series live in one unit; record the unit once, files per series
                before = dict(units.get(prov_rel, {}).get('files', {}))
                add_unit(prov_rel, key, 'water_use', stem + '{year}.nc',
                         lambda uy, pv: fy.map_identity_or_constant(years, uy, constant=constant))
                units[prov_rel]['files'] = {**before, **units[prov_rel]['files']}
    return links, units, mapping


def check_same_identity(run_dir, model, params, run_id):
    """D19 warm-start rule (b): VIC restores a state by array position and checks only its dimensions
    (drivers/shared_image/src/vic_restore.c, check_init_state_file); the dams plugin restores its states by dam index
    (plugins/dams/src/dam_state.c). A state of another run is therefore restored only into a run with the same model
    executable and the same parameter files (md5 per role) except the dam file, whose dam list is compared by
    check_dams_from; otherwise the renderer stops. Returns the earlier run's manifest."""
    with open(os.path.join(run_dir, 'run_manifest.json')) as fh:
        pm = json.load(fh)
    def identity(m, p):
        return {'model commit': m.get('commit'), 'executable sha256': m.get('executable_sha256'),
                **{f'parameter file {r} (md5)': v.get('md5') for r, v in p.items() if r != 'dams'}}
    have = identity(pm.get('model') or {}, (pm.get('inputs') or {}).get('parameters') or {})
    want = identity(model, params)
    diff = sorted(k for k in set(have) | set(want) if have.get(k) != want.get(k))
    if diff:
        raise RenderError(f'{run_id}: the earlier run {run_dir} differs from this run in {diff}; its end state would '
                          'be restored into other model parameters (VIC checks only the dimensions)')
    return pm


def enabled_plugins(plugins):
    return sorted(k for k, v in plugins.items() if (v or {}).get('enabled'))


def check_same_plugins(run_dir, campaign, run_id):
    """D19 warm-start rule (c): the earlier run had the same plugins switched on (its config/resolved.yaml; for a
    chunked run the one of its first chunk, chunks/<start>-<end>/config/, which records the same campaign)."""
    p = os.path.join(run_dir, 'config', 'resolved.yaml')
    mp = os.path.join(run_dir, 'run_manifest.json')
    if not os.path.isfile(p) and os.path.isfile(mp):
        chunks = manifest_of(run_dir).get('chunks') or []
        if chunks:
            p = os.path.join(run_dir, chunks[0]['dir'], 'config', 'resolved.yaml')
    if not os.path.isfile(p):
        raise RenderError(f'{run_id}: the earlier run {run_dir} has no config/resolved.yaml; its plugins are unknown')
    have = enabled_plugins((read_yaml(p).get('campaign') or {}).get('plugins') or {})
    want = enabled_plugins(campaign['plugins'])
    if have != want:
        raise RenderError(f'{run_id}: the earlier run {run_dir} ran with the plugins {have}, this run with {want} '
                          '(D19: a warm start needs the same plugins)')


OUT_NONREN_DEFICIT = 'OUT_NONREN_DEFICIT'


def check_nonrenewable_output(campaign):
    """With NONRENEWABLE_WITHDRAWAL the routing plugin repays the non-renewable deficit from the baseflow that enters the
    river, but OUT_BASEFLOW keeps it (plugins/routing/src/rout_run.c); OUT_NONREN_DEFICIT (mm, value at the end of the
    period) must therefore be in the monthly output, for the run check and for qtot in postprocessing."""
    if not campaign['plugins']['water_use']['nonrenewable_withdrawal']:
        return
    o = campaign['output']
    monthly = set(o.get('diagnostics', {}).get('monthly', [])) | \
        {n for v in o['isimip'].values() if 'monthly' in v['streams'] for n in v['vic']}
    if OUT_NONREN_DEFICIT not in monthly:
        raise RenderError(f'plugins.water_use.nonrenewable_withdrawal is true, but {OUT_NONREN_DEFICIT} is not in the '
                          'monthly output (output.diagnostics.monthly): the deficit taken from the baseflow before it '
                          'reaches the river would not be recorded')


def check_unit_parameters(W, params, units):
    """Every forcing unit of the run was made on the campaign's domain file (sha256 recorded in its provenance.yaml,
    input_sha256: key `domain` or a parameters/.../domain/ path), and a climate unit with the elevation of the
    campaign's parameter file (a parameters/.../bundle/ path: the natural bundle the assembled bundle was built from,
    or the parameter file itself). VIC compares only the grid, not the mask, and nothing would notice forcing corrected
    to another elevation."""
    cache = {}

    def sha(key, rel):
        if key not in cache:
            cache[key] = file_hash(f'{W}/{rel}')
        return cache[key]

    def elevation_sources():
        if 'elev' not in cache:
            rel = params['parameters']['path']
            p = f'{W}/{os.path.dirname(rel)}/provenance.yaml'
            bprov = read_yaml(p) if os.path.exists(p) else {}
            nat = (bprov.get('input_sha256') or {}).get('natural_bundle') if bprov.get('object') == rel else None
            cache['elev'] = {nat} if nat else {sha('parameters', rel)}
        return cache['elev']

    for rel_unit in units:
        recorded = read_yaml(f'{W}/forcing/{rel_unit}/provenance.yaml').get('input_sha256') or {}
        domain = [v for k, v in recorded.items() if k == 'domain' or (k.startswith('parameters/') and '/domain/' in k)]
        bundle = [v for k, v in recorded.items() if k.startswith('parameters/') and '/bundle/' in k]
        if not domain:
            raise RenderError(f'forcing unit {rel_unit} records no domain file; it cannot be matched to the campaign')
        if any(v != sha('domain', params['domain']['path']) for v in domain):
            raise RenderError(f'forcing unit {rel_unit} was made on another domain file than {params["domain"]["path"]}')
        if bundle and not set(bundle) <= elevation_sources():
            raise RenderError(f'forcing unit {rel_unit} was made with the elevation of another parameter file than '
                              f'{params["parameters"]["path"]}')


def check_landuse_tiles(W, params, units, usoc):
    """VIC stops in the first year in which a land-use class has coverage > 0 in a cell without a tile of that class
    (plugins/landuse/src/lu_force.c). The vegetation component behind the run's parameter file (bundle provenance,
    inputs.vegetation_component) must be accepted, and its QC (verify_vegetation.py, check forcing_tiles) must have
    checked exactly the land-use files of this run (same sha256); otherwise the QC has to be run again
    (submit_vegetation_component.py --verify-only)."""
    rel = params['parameters']['path']
    bprov = read_yaml(f'{W}/{os.path.dirname(rel)}/provenance.yaml')
    veg = (bprov.get('inputs') or {}).get('vegetation_component')
    if bprov.get('object') != rel or not veg:
        raise RenderError(f'{rel}: its provenance.yaml names no vegetation component, so the land-use tiles cannot be '
                          'checked against the land-use forcing')
    q = read_yaml(f'{W}/{os.path.dirname(veg)}/provenance.yaml').get('qc') or {}
    if q.get('status') != 'passed':
        raise RenderError(f'vegetation component {os.path.dirname(veg)} is not accepted (qc.status {q.get("status")})')
    with open(f'{W}/{q["evidence"]}/reports/verify.json') as fh:
        checked = json.load(fh)['checks']['forcing_tiles'].get('checked_files') or {}
    bad = sorted(f['path'] for f in units[f'landuse/{usoc}']['files'].values() if checked.get(f['path']) != f['sha256'])
    if bad:
        raise RenderError(f'the vegetation QC ({q["evidence"]}) did not check {len(bad)} land-use files this run reads '
                          f'as they are now, e.g. {bad[:2]}; run it again on the current land-use units '
                          '(workflow/03_parameters/vegetation/submit_vegetation_component.py --verify-only)')


def link_record(W, links):
    """{run-relative link: workdir-relative source} of the forcing view, checked by run_manifest.py verify-inputs."""
    return {f'forcing/{name}': os.path.relpath(target, W) for name, target in links}


def parent_run_state(parent_dir, init_state, run_id):
    """Identity of the end state of a parent run that is not rendered in this call: its last attempt completed and the
    state file exists. Returns {run_id, attempt, state_sha256}; stops otherwise."""
    try:
        with open(os.path.join(parent_dir, 'run_manifest.json')) as fh:
            pm = json.load(fh)
    except FileNotFoundError:
        pm = {'attempts': []}
    last = pm['attempts'][-1] if pm['attempts'] else {}
    sys.path.insert(0, os.path.join(HERE, '..', 'submit'))
    import run_manifest as rm
    if not rm.is_completed(pm) or not os.path.isfile(init_state):
        raise RenderError(f'{run_id}: its parent run {os.path.basename(parent_dir)} has not completed with the end '
                          f'state {init_state} (last attempt: {last.get("status", "none")}); render the parent '
                          'together with this run, or after the parent has completed')
    return {'run_id': pm['run_id'], 'attempt': last['attempt'], 'state_sha256': file_hash(init_state)}


def check_start_year(run, mapping):
    """VIC checks only the start-year file of every forcing: the climate file's first time must not be later
    than the model start, and each plugin file's first time must equal the climate file's first time
    (drivers/image/src/vic_force.c, plugins/general/src/plugin_get_forcing_file.c at 39e21ff5). A linked file
    of another year passes for every later year but not for the first one, so the first year of a run must
    be an identity link in every family."""
    y0 = run['start_year']
    bad = {k: v[y0] for k, v in mapping.items() if v[y0]['rule'] != 'identity'}
    if bad:
        raise RenderError(f'run {run["run_id"]} starts in {y0}, but these forcing series have no file of that '
                          f'year and would be linked to another year, which VIC rejects for the start year: '
                          f'{bad}. The forcing unit must contain the start year (04_forcing).')


# ------------------------------------------------------------------------------------------------ checks
def decomposition_groups(path, domain):
    import numpy as np
    import netCDF4 as nc
    with nc.Dataset(domain) as d:
        mask = np.asarray(d['mask'][:]).astype(bool)
    with nc.Dataset(path) as d:
        basin = np.asarray(d['basin'][:].filled(-1))
    vals, counts = np.unique(basin[mask], return_counts=True)
    if (vals < 0).any():
        raise RenderError('the decomposition file has no group on some active cells')
    return {'groups': int(len(vals)), 'largest_group_cells': int(counts.max()),
            'smallest_group_cells': int(counts.min()), 'active_cells': int(mask.sum())}


def check_tasks(ntasks, dec):
    """The FILE decomposition gives whole groups to ranks, largest first, to the rank with the fewest cells
    (plugins/routing/src/rout_decomposition.c); ranks beyond the number of groups stay empty."""
    if ntasks > dec['groups']:
        raise RenderError(f'{ntasks} MPI tasks but only {dec["groups"]} decomposition groups')
    # a lower bound of the largest rank load: the largest group, or an even share
    dec['largest_rank_cells_lower_bound'] = max(dec['largest_group_cells'], math.ceil(dec['active_cells'] / ntasks))
    return dec


def check_outputs_cover_protocol(campaign, protocol_dir):
    """Every protocol variable of the campaign's sector is either mapped or listed as not provided."""
    import glob
    sector = campaign['protocol']['sector']; want = set()
    for p in glob.glob(os.path.join(protocol_dir, 'definitions', 'variable', '*.yaml')):
        for v in read_yaml(p) or []:
            if sector in (v.get('sectors') or []):
                want.add(v['specifier'])
    o = campaign['output']
    have = set(o['isimip']) | set(o['not_provided'])
    both = set(o['isimip']) & set(o['not_provided'])
    if want - have or have - want or both:
        raise RenderError(f'output selection does not match the {sector} variables of the protocol: missing '
                          f'{sorted(want - have)}, unknown {sorted(have - want)}, both {sorted(both)}')
    return len(want)


# ------------------------------------------------------------------------------------------------ text blocks
OUTPUT_STREAMS = {'daily': 'NDAYS 1', 'monthly': 'NMONTHS 1'}
HISTORY_FREQUENCY = 'NYEARS 1'


def check_output_files(campaign):
    """The expected outputs (output/daily.<year>-01-01.nc, output/monthly.<year>-01.nc) and the run check
    (monitor/check_run.py) are written for these streams with one file per stream and calendar year; other output
    configurations stop the render instead of producing runs whose outputs would never be found."""
    o = campaign['output']
    if o['streams'] != OUTPUT_STREAMS or o['history_frequency'] != HISTORY_FREQUENCY:
        raise RenderError(f'output streams {o["streams"]} with history_frequency {o["history_frequency"]} are not '
                          f'supported: the expected outputs and monitor/check_run.py know only {OUTPUT_STREAMS} with '
                          f'{HISTORY_FREQUENCY}')


# Spin-up output (D19, spin-up rule 3; user 2026-10-17): a spin-up writes only the variables of its convergence test,
# as monthly means (December snow water equivalent needs monthly values; the test forms the annual values). The
# campaign lists them under output.spinup; a variable of a plugin that is off is refused, because VIC drops an OUTVAR
# it does not know with a warning only and the run would then miss a requested output.
SPINUP_STREAMS = {'monthly': 'NMONTHS 1'}
PLUGIN_OUTPUTS = (('dams', ('OUT_GDAM', 'OUT_LDAM')),
                  ('water_use', ('OUT_WI_', 'OUT_DE_', 'OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_CONSUMED', 'OUT_RETURNED',
                                 'OUT_NONREN')),
                  ('irrigation', ('OUT_REQUIREMENT', 'OUT_APPLIED', 'OUT_SHORTAGE', 'OUT_LEFTOVER', 'OUT_RECEIVED')),
                  ('routing', ('OUT_DISCHARGE', 'OUT_STREAM_MOIST')))


def spinup_output(campaign, run_id):
    """{stream: [OUTVAR]} of a spin-up run from the campaign's output.spinup (only the monthly stream); stops when the
    key is missing, a stream is not monthly, or a variable belongs to a plugin that is off."""
    o = campaign['output'].get('spinup')
    if not o:
        raise RenderError(f'{run_id}: a spin-up needs the campaign key output.spinup (monthly convergence variables)')
    if set(o) != set(SPINUP_STREAMS) or not all(o.values()):
        raise RenderError(f'{run_id}: output.spinup must list variables of the stream(s) {sorted(SPINUP_STREAMS)} '
                          f'only, not {sorted(o)}')
    off = []
    for plugin, prefixes in PLUGIN_OUTPUTS:
        if not campaign['plugins'][plugin]['enabled']:
            off += [n for names in o.values() for n in names if n.startswith(prefixes)]
    if off:
        raise RenderError(f'{run_id}: output.spinup asks for {sorted(off)} of plugins that are off')
    return {s: list(dict.fromkeys(o[s])) for s in SPINUP_STREAMS}


def output_streams(campaign, result_dir, spinup_run=None):
    """OUTFILE blocks of the VIC file and {stream: frequency}; for a spin-up run (spinup_run: its run ID) the monthly
    convergence variables of output.spinup only."""
    o = campaign['output']; agg = o.get('aggregation', {})
    if spinup_run:
        chosen = spinup_output(campaign, spinup_run); freqs = SPINUP_STREAMS
    else:
        chosen = {}; freqs = o['streams']
        for stream in o['streams']:
            names = []
            for var in o['isimip'].values():
                if stream in var['streams']:
                    names += [n for n in var['vic'] if n not in names]
            names += [n for n in o.get('diagnostics', {}).get(stream, []) if n not in names]
            chosen[stream] = names
    lines = []
    for stream, names in chosen.items():
        lines += ['', f'OUTFILE                 {stream}', f'AGGFREQ                 {freqs[stream]}',
                  f'HISTFREQ                {o["history_frequency"]}', f'OUT_FORMAT              {o["format"]}',
                  f'COMPRESS                {o["compress"]}']
        lines += [f'OUTVAR                  {n}' + (f'  * * * {agg[n]}' if n in agg else '') for n in names]
    return '\n'.join(lines).lstrip('\n'), {s: freqs[s] for s in chosen}


def tf(value):
    return 'TRUE' if value else 'FALSE'


def render_job(W, rdir, campaign_id, run_id, start_year, end_year, resources, model, chunk_dir=None, chunk=None):
    """The Slurm job of a run or of one chunk (templates/slurm/vic_run.sbatch: chunk_dir holds its config and logs)
    and its wall time in hours."""
    nyears = end_year - start_year + 1
    wt = resources['wall_time']
    hours = min(math.ceil(wt['setup_hours'] + wt['hours_per_model_year'] * nyears), wt['max_hours'])
    conda_base = subprocess.run(['conda', 'info', '--base'], capture_output=True, text=True).stdout.strip() or \
        os.path.dirname(os.path.dirname(os.environ['CONDA_EXE']))
    sched = ([f'#SBATCH --constraint={resources["constraint"]}'] if resources.get('constraint') else []) + \
        (['#SBATCH --exclusive'] if resources.get('exclusive') else [])
    sb = {'JOB_NAME': f'vic-{campaign_id}-{start_year}-{end_year}',
          'PARTITION': resources['partition'], 'NODES': resources['nodes'], 'NTASKS': resources['ntasks'],
          'CPUS_PER_TASK': resources['cpus_per_task'], 'MEM': resources['mem'], 'TIME': f'{hours}:00:00',
          'SCHEDULER_LINES': '\n'.join(sched), 'RUN_DIR': rdir, 'RUN_ID': run_id, 'CAMPAIGN_ID': campaign_id,
          'CONDA_BASE': conda_base, 'WORKDIR': W, 'REPO': REPO, 'CHECK_PROCESSES': resources['check_processes'],
          'MODULE_LOADS': '\n'.join(f'  module load {m}' for m in model['runtime_modules']),
          'LAUNCHER': resources['launcher'], 'EXECUTABLE': f'{W}/{model["executable"]}',
          'CHUNK_DIR': chunk_dir or rdir, 'CHUNK_OPTION': f' --chunk {chunk}' if chunk else ''}
    with open(os.path.join(REPO, SLURM_TEMPLATE)) as fh:
        return fill(fh.read(), sb), hours


# ------------------------------------------------------------------------------------------------ chunks
def chunk_plan(start_year, end_year, chunk_years):
    """[(first, last)] of the chunks of a run: a run longer than chunk_years is split into chunks of chunk_years
    years (the last one shorter); otherwise one piece, the run itself."""
    if not chunk_years or end_year - start_year + 1 <= chunk_years:
        return [(start_year, end_year)]
    return [(y, min(y + chunk_years - 1, end_year)) for y in range(start_year, end_year + 1, chunk_years)]


def chunk_id(first, last):
    return f'{first:04d}-{last:04d}'


def end_state_rel(start_year, end_year, chunk_years):
    """Run-relative path of the end state of a run (in its last chunk when chunked)."""
    plan = chunk_plan(start_year, end_year, chunk_years)
    name = f'states/state.{end_year + 1:04d}0101_00000.nc'
    return name if len(plan) == 1 else f'chunks/{chunk_id(*plan[-1])}/{name}'


def run_chunk_years(run, resources):
    """chunk_years of a run: a restriction run's own value (non-production tests), else the resources'."""
    return run.get('chunk_years', resources.get('chunk_years'))


def run_end_state(base, prun, resources):
    """Absolute end-state path of a run of the campaign: as recorded in its manifest when it has been rendered
    (manifests before chunks have none: states/), else from its chunk plan."""
    rd = f'{base}/{prun["run_id"]}'
    if os.path.exists(f'{rd}/run_manifest.json'):
        with open(f'{rd}/run_manifest.json') as fh:
            pm = json.load(fh)
        return f'{rd}/' + pm.get('end_state', f'states/state.{prun["end_year"] + 1:04d}0101_00000.nc')
    return f'{rd}/' + end_state_rel(prun['start_year'], prun['end_year'], run_chunk_years(prun, resources))


# ------------------------------------------------------------------------------------------------ spin-up blocks
SPINUP_CHECKED_BY = 'workflow/05_simulation/monitor/check_spinup.py'


def manifest_of(run_dir):
    with open(os.path.join(run_dir, 'run_manifest.json')) as fh:
        return json.load(fh)


def end_state_of(run_dir):
    """Absolute end-state path of a rendered run (its manifest's end_state; states/ in manifests before chunks)."""
    m = manifest_of(run_dir)
    return f'{run_dir}/' + m.get('end_state', f'states/state.{int(m["period"]["end"][:4]) + 1:04d}0101_00000.nc')


def spinup_check(W, run_dir):
    """Summary of the convergence test of a spin-up block (monitor/check_spinup.py), None when it has not run."""
    p = f'{W}/qc/{os.path.relpath(run_dir, W)}/summary.json'
    if not os.path.isfile(p):
        return None
    with open(p) as fh:
        s = json.load(fh)
    return s if s.get('checked_by') == SPINUP_CHECKED_BY else None


def spinup_blocks(base, segment_id):
    """[(block, run_dir)] of the blocks of a spin-up segment rendered so far, block 1 first."""
    out, n = [], 1
    while os.path.exists(f'{base}/{rc.block_run_id(segment_id, n)}'):
        out.append((n, f'{base}/{rc.block_run_id(segment_id, n)}')); n += 1
    return out


def spinup_next(W, base, campaign, segment_id):
    """What the spin-up segment needs (D19 spin-up rule 3, D20 decision 3): ('render', 1, None) when no block exists;
    ('render', k + 1, dir of block k) when block k has completed and failed its convergence test; ('converged', k, dir)
    when block k passed it. Stops when block k has not completed, its test has not run (or ran from code that was not
    committed, in a production campaign), or spinup.max_blocks blocks did not converge."""
    blocks = spinup_blocks(base, segment_id)
    if not blocks:
        return 'render', 1, None
    k, bdir = blocks[-1]
    sys.path.insert(0, os.path.join(HERE, '..', 'submit'))
    import run_manifest as rm
    m = manifest_of(bdir)
    if not rm.is_completed(m):
        raise RenderError(f'{segment_id}: block {k} ({os.path.basename(bdir)}) has not completed (status '
                          f'{m.get("status")}); wait for it or retry it (submit_run.py --retry)')
    s = spinup_check(W, bdir)
    if s is None:
        raise RenderError(f'{segment_id}: the convergence test of block {k} has not run '
                          f'(monitor/submit_check.py --spinup --run-dir {os.path.relpath(bdir, W)})')
    if campaign['production'] and s.get('code_dirty') is not False:
        raise RenderError(f'{segment_id}: the convergence test of block {k} ran from code that was not committed')
    if s.get('status') == 'passed':
        return 'converged', k, bdir
    if s.get('status') != 'failed':
        raise RenderError(f'{segment_id}: the convergence test of block {k} has status {s.get("status")}')
    if k + 1 > rc.max_blocks(campaign['spinup']):
        raise RenderError(f'{segment_id}: not converged after {k} blocks (spinup.max_blocks); the user decides how to '
                          'go on (D19)')
    return 'render', k + 1, bdir


# ------------------------------------------------------------------------------------------------ render
def render(campaign_path, label=None, run_id=None, scratch=False, W=None):
    W = W or rc.workdir()
    campaign = rc.load_campaign(campaign_path)
    resources = read_yaml(os.path.join(REPO, campaign['resources']))
    commit, dirty = git_state()
    if not scratch and dirty:
        raise RenderError('the repository is not clean; render campaign runs from a clean repository '
                          '(docs/directory-contracts.md, rule 14) or use --scratch')
    protocol_dir = f'{W}/{campaign["protocol"]["path"]}'
    segments, chains = rc.resolve(campaign, protocol_dir)
    all_runs = rc.runs(campaign, segments, label)
    runs = all_runs
    if run_id:
        runs = [r for r in runs if r['run_id'] == run_id] or sys.exit(f'no run {run_id} in the campaign')
    in_campaign = {r['segment_id'] for r in all_runs}; in_call = {r['segment_id'] for r in runs}
    by_segment = {r['segment_id']: r for r in all_runs}
    # the ISIMIP output selection and its streams are checked when a run writes them; a spin-up writes only
    # output.spinup (spinup_output), so a campaign of spin-ups alone needs no ISIMIP selection
    nvars = None
    if any(r['segment']['period'] != 'spinup' for r in runs):
        nvars = check_outputs_cover_protocol(campaign, protocol_dir)
        check_output_files(campaign)
    check_nonrenewable_output(campaign)
    model = check_build(W, campaign, resources)
    params = parameter_files(W, campaign)
    _, _, aliases = rc.load_protocol(protocol_dir, campaign['protocol']['simulation_round'])
    dec = check_tasks(resources['ntasks'], decomposition_groups(f'{W}/{params["decomposition"]["path"]}',
                                                                f'{W}/{params["domain"]["path"]}'))
    base = f'{W}/scratch/{campaign["campaign_id"]}' if scratch else f'{W}/runs/{campaign["campaign_id"]}'
    rendered = []
    blocks_on = not campaign.get('restriction')     # spin-up blocks: campaigns without a restriction (D19, D20)
    spin_rendered, left_out = set(), set()
    for run in runs:
        seg = run['segment']
        parent = seg['parent']
        prev_block = spin_parent = None
        if blocks_on and seg['period'] == 'spinup':
            action, n, bdir = spinup_next(W, base, campaign, run['segment_id'])
            if action == 'converged':
                print(f'{run["segment_id"]}: block {n} passed the convergence test; no further block')
                continue
            if n > 1:
                y0, y1 = rc.block_years(campaign['spinup'], run['start_year'], run['end_year'], n)
                run = dict(run, run_id=rc.block_run_id(run['segment_id'], n), start_year=y0, end_year=y1)
                prev_block = (n - 1, bdir)
            run = dict(run, spinup_block=n)
        if parent in left_out:
            print(f'{run["run_id"]}: not rendered, its parent {parent} is not rendered yet'); left_out.add(run['segment_id'])
            continue
        if blocks_on and parent in in_campaign and by_segment[parent]['segment']['period'] == 'spinup':
            # a child of a spin-up starts only from the block that passed the convergence test
            done = None if parent in spin_rendered else spinup_next(W, base, campaign, parent)
            if not done or done[0] != 'converged':
                print(f'{run["run_id"]}: not rendered, the spin-up {parent} has not converged yet')
                left_out.add(run['segment_id']); continue
            spin_parent = done[2]
        rdir = f'{base}/{run["run_id"]}'
        if os.path.exists(rdir):
            raise RenderError(f'{rdir} exists; a run directory is never rendered again (retry: submit_run.py --retry)')
        alias = rc.input_alias(aliases, seg['climate'], campaign['gcms'][seg['gcm']]['climate_input'])
        rparams = run_parameters(params, seg['soc'])
        links, units, mapping = forcing_plan(W, campaign, run, alias)
        check_start_year(run, mapping)
        check_unit_parameters(W, rparams, units)
        if campaign['plugins']['landuse']['enabled']:
            check_landuse_tiles(W, rparams, units, campaign['dhf_forcing']['units'][seg['soc']])
        dams_on = campaign['plugins']['dams']['enabled']
        init_state = None; parent_state = {}; init_how = 'cold_start'; warm = False
        init = campaign['initialisation']
        if prev_block:
            # a continuation block starts from the end state of the previous block of the same segment (D20)
            k, bdir = prev_block
            init_state = end_state_of(bdir)
            init_how = f'end state of spin-up block {k} ({os.path.basename(bdir)})'
            parent_state = {**parent_run_state(bdir, init_state, run['run_id']), 'previous_block': k}
            if dams_on:
                pm = manifest_of(bdir)
                check_dams_from(f'{W}/{pm["inputs"]["parameters"]["dams"]["path"]}', int(pm['period']['end'][:4]),
                                f'{W}/{rparams["dams"]["path"]}', run['start_year'], init_state, run['run_id'],
                                f'the previous block {os.path.basename(bdir)}')
        elif parent and parent in in_campaign and not campaign.get('restriction'):
            pdir = spin_parent or f'{base}/{parent}'
            init_state = end_state_of(spin_parent) if spin_parent else run_end_state(base, by_segment[parent], resources)
            init_how = 'state of the parent run' + (f' (spin-up block {os.path.basename(spin_parent)}, converged)'
                                                    if spin_parent else '')
            # a parent rendered in this call has no state yet: the job binds it (run_manifest.py verify-inputs)
            parent_state = {'run_id': parent, 'attempt': None, 'state_sha256': None} if parent in in_call and \
                not spin_parent else parent_run_state(pdir, init_state, run['run_id'])
            if dams_on:
                prun = by_segment[parent]
                pfile = f'{W}/{run_parameters(params, prun["segment"]["soc"])["dams"]["path"]}'
                check_dams_from(pfile, prun['end_year'], f'{W}/{rparams["dams"]["path"]}', run['start_year'],
                                None if parent in in_call and not spin_parent else init_state, run['run_id'],
                                f'the parent run {parent}')
        elif init['without_parent'] == 'state_of_run':
            src = init.get('state_of_run') or {}
            if not (src.get('run_dir', '').startswith('runs/') and src.get('state') and str(src.get('reason', '')).strip()):
                raise RenderError('initialisation.state_of_run needs run_dir (under runs/), state and reason')
            init_state = f'{W}/{src["run_dir"]}/{src["state"]}'
            init_how = f'end state of the earlier run {src["run_dir"]} (campaign initialisation.state_of_run)'
            parent_state = parent_run_state(f'{W}/{src["run_dir"]}', init_state, run['run_id'])
            pm = check_same_identity(f'{W}/{src["run_dir"]}', model, rparams, run['run_id'])
            check_same_plugins(f'{W}/{src["run_dir"]}', campaign, run['run_id'])
            if dams_on:
                pdams = ((pm.get('inputs') or {}).get('parameters') or {}).get('dams') or {}
                plast = int(str((pm.get('period') or {}).get('end', '0'))[:4])
                if not pdams.get('path') or not plast:
                    raise RenderError(f'{run["run_id"]}: the earlier run {src["run_dir"]} records no dam file or period')
                check_dams_from(f'{W}/{pdams["path"]}', plast, f'{W}/{rparams["dams"]["path"]}', run['start_year'],
                                init_state, run['run_id'], f'the earlier run {src["run_dir"]}')
            parent_state['reason'] = ' '.join(str(src['reason']).split())
            parent_state['run_dir'] = src['run_dir']; warm = True
        elif init['without_parent'] != 'cold_start':
            raise RenderError(f'{run["run_id"]}: parent {parent} is not simulated and initialisation.without_parent is '
                              f'{init["without_parent"]!r} (cold_start or state_of_run)')
        usoc = campaign['dhf_forcing']['units'][seg['soc']]
        pl = campaign['plugins']
        cyears = run_chunk_years(run, resources)
        plan = chunk_plan(run['start_year'], run['end_year'], cyears)
        chunked = len(plan) > 1
        spinup = seg['period'] == 'spinup'
        streams_text, streams = output_streams(campaign, None, run['run_id'] if spinup else None)
        parent_rec = {'segment_id': None if warm or prev_block else parent,
                      **({'protocol_parent_segment': parent} if warm else {}),
                      'init_state': init_state and os.path.relpath(init_state, W),
                      'initialisation': init_how, **parent_state}
        files, expected, chunks, hours_total = {}, [], [], 0
        for k, (c0, c1) in enumerate(plan):
            cid = chunk_id(c0, c1) if chunked else None
            pre = f'chunks/{cid}/' if chunked else ''
            cdir = f'{rdir}/chunks/{cid}' if chunked else rdir
            if k == 0:
                c_init, c_how = init_state, init_how
            else:
                c_init = f'{rdir}/chunks/{chunk_id(*plan[k - 1])}/states/state.{c0:04d}0101_00000.nc'
                c_how = f'end state of chunk {chunk_id(*plan[k - 1])} of this run'
            check_start_year({'run_id': f'{run["run_id"]}' + (f' (chunk {cid})' if chunked else ''),
                              'start_year': c0}, mapping)
            for sub in ('config', 'logs', 'states', 'output', 'forcing'):
                os.makedirs(f'{cdir}/{sub}')
            clinks = [(n, t) for n, t in links if c0 <= year_of(n) <= c1]
            fy.build_view(f'{cdir}/forcing', clinks)
            view = f'{cdir}/forcing'
            force_types = '\n'.join(
                f'FORCE_TYPE              {vt:9s} {var:7s} {view}/climate/{var}/{var}_{seg["gcm"]}_{alias}_'
                for vt, var in (('AIR_TEMP', 'tair'), ('PREC', 'prec'), ('PRESSURE', 'psurf'), ('SWDOWN', 'swdown'),
                                ('LWDOWN', 'lwdown'), ('VP', 'vp'), ('WIND', 'wind')))
            # VIC opens the start-year file of every PLUGIN_FORCE_TYPE line, whether its plugin is on or not
            # (plugins/general/src/plugin_forcing_utils.c, plugin_force_validate_global_param, at 39e21ff5); the forcing
            # view has links only for the plugins that are on, so the lines of a plugin that is off are left out
            wu_lines = [] if pl['water_use']['enabled'] else ['# water use off: no water-use forcing']
            for prefix, sector in WATER_USE_FILES:
                if pl['water_use']['enabled'] and sector in pl['water_use']['sectors']:
                    for kind, var in WATER_USE_VARIABLES:
                        wu_lines.append(f'PLUGIN_FORCE_TYPE  {prefix}_{kind:12s} {var:21s} YEAR  '
                                        f'{view}/water_use/{sector}_{var}_{usoc}_')
            end_state = c1 + 1
            state_lines = '\n'.join([f'STATENAME               {cdir}/states/state', f'STATEYEAR               {end_state}',
                                     'STATEMONTH              1', 'STATEDAY                1', 'STATESEC                0',
                                     'STATE_FORMAT            NETCDF4', 'STATE_COMPRESS          2'])
            values = {
                'RUN_ID': run['run_id'] + (f' chunk {cid}' if chunked else ''), 'CAMPAIGN_ID': campaign['campaign_id'],
                'CODE_COMMIT': commit, 'MODEL_COMMIT': model['commit'], 'START_YEAR': c0, 'END_YEAR': c1,
                'DOMAIN': f'{W}/{rparams["domain"]["path"]}', 'PARAMETERS': f'{W}/{rparams["parameters"]["path"]}',
                'CONSTANTS': f'{cdir}/config/vic_constants.txt', 'FORCE_TYPES': force_types,
                'INIT_STATE_LINES': f'# {c_how}\nINIT_STATE              {c_init}' if c_init else
                                    '# cold start: no INIT_STATE (campaign initialisation.without_parent)',
                'STATE_LINES': state_lines,
                'ROUTING': tf(pl['routing']['enabled']), 'ROUT_STEPS_PER_DAY': pl['routing']['steps_per_day'],
                'DECOMPOSITION': pl['routing']['decomposition'],
                'ROUTING_PARAMETERS': f'{W}/{rparams["routing"]["path"]}',
                'DECOMPOSITION_PARAMETERS': f'{W}/{rparams["decomposition"]["path"]}',
                'WATERUSE': tf(pl['water_use']['enabled']), 'WATERUSE_PARAMETERS': f'{W}/{rparams["water_use"]["path"]}',
                'LOCAL_WITHDRAWAL': tf(pl['water_use']['local_withdrawal']),
                'REMOTE_WITHDRAWAL': tf(pl['water_use']['remote_withdrawal']),
                'COMPENSATION_WITHDRAWAL': tf(pl['water_use']['compensation_withdrawal']),
                'NONRENEWABLE_WITHDRAWAL': tf(pl['water_use']['nonrenewable_withdrawal']),
                'NONRENEWABLE_RUNOFF': tf(pl['water_use']['nonrenewable_runoff']),
                'WATER_USE_FORCE_TYPES': '\n'.join(wu_lines),
                'IRRIGATION': tf(pl['irrigation']['enabled']), 'IRRIGATION_PARAMETERS': f'{W}/{rparams["irrigation"]["path"]}',
                'POTENTIAL_IRRIGATION': tf(pl['irrigation']['potential_irrigation']),
                'EFFICIENT_IRRIGATION': tf(pl['irrigation']['efficient_irrigation']),
                'OFFSET_IRRIGATION': tf(pl['irrigation']['offset_irrigation']),
                'PBARE': pl['irrigation']['paddy_bare_class'],
                'DAMS': tf(pl['dams']['enabled']), 'DAMS_PARAMETERS': f'{W}/{rparams["dams"]["path"]}',
                'LANDUSE': tf(pl['landuse']['enabled']),
                'LANDUSE_FORCE_TYPE': f'PLUGIN_FORCE_TYPE  CV  coverage  YEAR  {view}/landuse/coverage_{usoc}_'
                                      if pl['landuse']['enabled'] else '# land use off: no land-use forcing',
                'EFR': tf(pl['efr']['enabled']), 'WOFOST': tf(pl['wofost']['enabled']),
                'RESULT_DIR': f'{cdir}/output/', 'LOG_DIR': f'{cdir}/logs/', 'OUTPUT_STREAMS': streams_text}
            vic_text = fill(open(os.path.join(REPO, VIC_TEMPLATE)).read(), values)
            if c_init:
                check_start_january(vic_text, run['run_id'])
            constants = (f'# VIC constants of run {run["run_id"]} (campaign plugins.dams, plugins.water_use)\n'
                         f'DAM_ALPHA {pl["dams"]["alpha"]}\nDAM_BETA {pl["dams"]["beta"]}\nDAM_GAMMA {pl["dams"]["gamma"]}\n')
            if pl['water_use'].get('nonrenewable_limit_mm') is not None:   # absent or null: no limit (compiled default)
                constants += f'NONRENEWABLE_LIMIT {float(pl["water_use"]["nonrenewable_limit_mm"])}\n'
            job_text, hours = render_job(W, rdir, campaign['campaign_id'], run['run_id'], c0, c1, resources, model,
                                         chunk_dir=cdir, chunk=cid)
            hours_total += hours
            cfiles = {'config/vic_global.txt': vic_text, 'config/vic_constants.txt': constants,
                      'config/job.sbatch': job_text}
            resolved = {
                'campaign_id': campaign['campaign_id'], 'run_id': run['run_id'], 'segment_id': run['segment_id'],
                'label': run['label'], 'start_year': run['start_year'], 'end_year': run['end_year'],
                **({'chunk': {'id': cid, 'index': k, 'chunks': len(plan), 'start_year': c0, 'end_year': c1,
                              'init_state': c_init and os.path.relpath(c_init, W), 'initialisation': c_how},
                    'chunk_years': cyears} if chunked else {}),
                'segment': seg, 'climate_input_alias': alias, 'dhf_unit': usoc,
                **({'spinup_block': run['spinup_block']} if 'spinup_block' in run else {}),
                'experiments_using_segment': seg['experiments'],
                # a warm start comes from an earlier run (run_id, run_dir), not from the protocol parent segment
                'parent': parent_rec,
                'campaign_file': os.path.relpath(campaign_path, REPO) if os.path.isabs(campaign_path) else campaign_path,
                'campaign_sha256': file_hash(campaign_path), 'campaign': campaign,
                'resources_file': campaign['resources'], 'resources': resources,
                'model': model, 'parameters': rparams, 'decomposition': dec,
                'protocol_water_global_variables': nvars,
                'forcing_units': {k2: {kk: vv for kk, vv in v.items() if kk != 'files'} for k2, v in units.items()},
                'output_streams': streams, 'wall_time_hours': hours,
                'rendered_by': RENDERED_BY, 'code_commit': commit, 'code_dirty': dirty, 'rendered_at': utcnow()}
            cfiles['config/resolved.yaml'] = yaml.safe_dump(resolved, sort_keys=False)
            for rel, text in cfiles.items():
                with open(f'{cdir}/{rel}', 'w') as fh:
                    fh.write(text)
                files[pre + rel] = text
            cexp = []
            for y in range(c0, c1 + 1):
                cexp += ([] if spinup else [f'{pre}output/daily.{y}-01-01.nc']) + [f'{pre}output/monthly.{y}-01.nc']
            cexp.append(f'{pre}states/state.{end_state:04d}0101_00000.nc')
            expected += cexp
            if chunked:
                chunks.append({'id': cid, 'start_year': c0, 'end_year': c1, 'dir': f'chunks/{cid}',
                               'init_state': c_init and os.path.relpath(c_init, W),
                               'job_file': f'{pre}config/job.sbatch', 'expected_outputs': cexp,
                               'end_state': f'{pre}states/state.{end_state:04d}0101_00000.nc', 'wall_time_hours': hours})
        manifest = {
            'schema': 'isimip4b-run-manifest-1', 'campaign_id': campaign['campaign_id'], 'run_id': run['run_id'],
            'segment_id': run['segment_id'], 'label': run['label'], 'production': campaign['production'],
            **({'spinup_block': run['spinup_block']} if 'spinup_block' in run else {}),
            'status': 'rendered', 'run_dir': os.path.relpath(rdir, W),
            'period': {'start': f'{run["start_year"]}-01-01', 'end': f'{run["end_year"]}-12-31'},
            'parent': parent_rec,
            'workflow': {'code_commit': commit, 'code_dirty': dirty, 'rendered_by': RENDERED_BY,
                         'rendered_at': resolved['rendered_at']},
            'campaign_config': {'path': resolved['campaign_file'], 'sha256': resolved['campaign_sha256']},
            'model': {k: model[k] for k in ('commit', 'freeze_status', 'build', 'build_status', 'executable',
                                            'executable_sha256', 'runtime_modules')},
            'inputs': {'parameter_set': campaign['parameter_set']['id'], 'parameters': rparams,
                       'forcing_units': units},
            'forcing_view': {k: {str(y): v for y, v in m.items()} for k, m in mapping.items()},
            'forcing_links': link_record(W, links) if not chunked else
            {f'chunks/{chunk_id(c0, c1)}/forcing/{n}': os.path.relpath(t, W)
             for c0, c1 in plan for n, t in links if c0 <= year_of(n) <= c1},
            'rendered_files': {rel: text_sha256(text) for rel, text in files.items()},
            'expected_outputs': expected,
            'end_state': end_state_rel(run['start_year'], run['end_year'], cyears),
            **({'chunk_years': cyears, 'chunks': chunks} if chunked else {}),
            'attempts': []}
        sys.path.insert(0, os.path.join(HERE, '..', 'submit'))
        import run_manifest as rm
        manifest['inputs_fingerprint'] = rm.inputs_fingerprint(manifest)
        rm.save(rdir, manifest)
        rendered.append(rdir)
        if seg['period'] == 'spinup':
            spin_rendered.add(run['segment_id'])
        print(f'rendered {rdir} ({len(links)} forcing links, {len(plan)} chunk(s), {hours_total} h wall time, '
              f'{resources["ntasks"]} tasks)')
    return rendered


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--label', default=None)
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--scratch', action='store_true', help='render under scratch/<campaign-id>/ (test, never submitted as a campaign run)')
    a = ap.parse_args()
    try:
        render(a.campaign, a.label, a.run_id, a.scratch)
    except (RenderError, rc.CampaignError) as e:
        sys.exit(f'render stopped: {e}')


if __name__ == '__main__':
    main()
