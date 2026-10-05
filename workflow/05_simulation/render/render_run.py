#!/usr/bin/env python3
"""Render one or more runs of a campaign into their run directories.

For each run (resolve_campaign.py) the renderer
  1. checks the model build (builds/vic/<commit>/build_manifest.json: commit of the campaign and of
     model/vic.lock.yaml, executable sha256, runtime modules equal to the resources), the parameter files
     (present, md5 recorded in manifests/parameters/<set>.yaml) and every forcing unit it reads (accepted:
     code_dirty false and qc.status passed);
  2. builds the forcing view <run>/forcing/<family>/ of links named by simulation year (forcing_years.py);
  3. renders the VIC global-parameter file from templates/vic/global_param.txt and the Slurm job from
     templates/slurm/vic_run.sbatch;
  4. writes config/resolved.yaml (campaign, segment, run, resources and resolved inputs) and the run manifest
     run_manifest.json with status `rendered`.

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
    """{role: {path, md5, component, qc_status}} from the campaign and the parameter manifest."""
    ps = campaign['parameter_set']
    manifest = read_yaml(os.path.join(REPO, 'manifests', 'parameters', f'{ps["id"]}.yaml'))
    by_path = {}
    for key, comp in manifest['components'].items():
        for f in comp.get('files', []):
            by_path[f['path']] = {'md5': f.get('md5'), 'manifest_entry': key, 'qc_status': comp.get('qc_status')}
    out = {}
    for role, rel in ps['files'].items():
        if rel not in by_path:
            raise RenderError(f'parameter file {rel} ({role}) is not recorded in manifests/parameters/{ps["id"]}.yaml')
        if not by_path[rel]['md5']:
            raise RenderError(f'parameter file {rel} ({role}) has no md5 in the parameter manifest')
        full = f'{W}/parameters/{ps["status"]}/{ps["id"]}/{rel}'
        if not os.path.isfile(full):
            raise RenderError(f'parameter file missing: {full}')
        out[role] = {'path': os.path.relpath(full, W), **by_path[rel]}
    return out


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
        ymap = year_map(uyears)
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
            win = campaign['spinup']['climate_cycle']
            add_unit(rel, f'climate/{var}', f'climate/{var}', pat, lambda uy, w=win: fy.map_cycle(years, w, uy))
        else:
            add_unit(rel, f'climate/{var}', f'climate/{var}', pat,
                     lambda uy: fy.map_identity_or_constant(years, uy, constant=False))
    usoc = dhf['units'][seg['soc']]
    constant = usoc in dhf['constant']
    if spinup and not constant:
        raise RenderError(f'spin-up DHF {usoc} is not declared constant')
    if campaign['plugins']['landuse']['enabled']:
        add_unit(f'landuse/{usoc}', 'landuse', 'landuse', f'coverage_{usoc}_' + '{year}.nc',
                 lambda uy: fy.map_identity_or_constant(years, uy, constant=constant))
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
                         lambda uy: fy.map_identity_or_constant(years, uy, constant=constant))
                units[prov_rel]['files'] = {**before, **units[prov_rel]['files']}
    return links, units, mapping


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
def output_streams(campaign, result_dir):
    o = campaign['output']; agg = o.get('aggregation', {})
    lines = []
    for stream, freq in o['streams'].items():
        names = []
        for var in o['isimip'].values():
            if stream in var['streams']:
                names += [n for n in var['vic'] if n not in names]
        names += [n for n in o.get('diagnostics', {}).get(stream, []) if n not in names]
        lines += ['', f'OUTFILE                 {stream}', f'AGGFREQ                 {freq}',
                  f'HISTFREQ                {o["history_frequency"]}', f'OUT_FORMAT              {o["format"]}',
                  f'COMPRESS                {o["compress"]}']
        lines += [f'OUTVAR                  {n}' + (f'  * * * {agg[n]}' if n in agg else '') for n in names]
    return '\n'.join(lines).lstrip('\n'), {s: f for s, f in o['streams'].items()}


def tf(value):
    return 'TRUE' if value else 'FALSE'


def render_job(W, rdir, campaign_id, run_id, start_year, end_year, resources, model):
    """The Slurm job of a run (templates/slurm/vic_run.sbatch) and its wall time in hours."""
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
          'LAUNCHER': resources['launcher'], 'EXECUTABLE': f'{W}/{model["executable"]}'}
    with open(os.path.join(REPO, SLURM_TEMPLATE)) as fh:
        return fill(fh.read(), sb), hours


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
    runs = rc.runs(campaign, segments, label)
    if run_id:
        runs = [r for r in runs if r['run_id'] == run_id] or sys.exit(f'no run {run_id} in the campaign')
    nvars = check_outputs_cover_protocol(campaign, protocol_dir)
    model = check_build(W, campaign, resources)
    params = parameter_files(W, campaign)
    _, _, aliases = rc.load_protocol(protocol_dir, campaign['protocol']['simulation_round'])
    dec = check_tasks(resources['ntasks'], decomposition_groups(f'{W}/{params["decomposition"]["path"]}',
                                                                f'{W}/{params["domain"]["path"]}'))
    base = f'{W}/scratch/{campaign["campaign_id"]}' if scratch else f'{W}/runs/{campaign["campaign_id"]}'
    rendered = []
    for run in runs:
        seg = run['segment']
        rdir = f'{base}/{run["run_id"]}'
        if os.path.exists(rdir):
            raise RenderError(f'{rdir} exists; a run directory is never rendered again (retry: submit_run.py --retry)')
        alias = rc.input_alias(aliases, seg['climate'], campaign['gcms'][seg['gcm']]['climate_input'])
        links, units, mapping = forcing_plan(W, campaign, run, alias)
        check_start_year(run, mapping)
        parent = seg['parent']
        init_state = None
        if parent and parent in {r['segment_id'] for r in runs} and not campaign.get('restriction'):
            init_state = f'{base}/{parent}/states/state.{run["start_year"]:04d}0101_00000.nc'
        elif campaign['initialisation']['without_parent'] != 'cold_start':
            raise RenderError(f'{run["run_id"]}: parent {parent} is not simulated and the campaign gives no state')
        for sub in ('config', 'logs', 'states', 'output', 'forcing'):
            os.makedirs(f'{rdir}/{sub}')
        fy.build_view(f'{rdir}/forcing', links)
        view = f'{rdir}/forcing'
        force_types = '\n'.join(
            f'FORCE_TYPE              {vt:9s} {var:7s} {view}/climate/{var}/{var}_{seg["gcm"]}_{alias}_'
            for vt, var in (('AIR_TEMP', 'tair'), ('PREC', 'prec'), ('PRESSURE', 'psurf'), ('SWDOWN', 'swdown'),
                            ('LWDOWN', 'lwdown'), ('VP', 'vp'), ('WIND', 'wind')))
        usoc = campaign['dhf_forcing']['units'][seg['soc']]
        pl = campaign['plugins']
        wu_lines = []
        for prefix, sector in WATER_USE_FILES:
            if sector in pl['water_use']['sectors']:
                for kind, var in WATER_USE_VARIABLES:
                    wu_lines.append(f'PLUGIN_FORCE_TYPE  {prefix}_{kind:12s} {var:21s} YEAR  '
                                    f'{view}/water_use/{sector}_{var}_{usoc}_')
        streams_text, streams = output_streams(campaign, f'{rdir}/output')
        end_state = run['end_year'] + 1
        state_lines = '\n'.join([f'STATENAME               {rdir}/states/state', f'STATEYEAR               {end_state}',
                                 'STATEMONTH              1', 'STATEDAY                1', 'STATESEC                0',
                                 'STATE_FORMAT            NETCDF4', 'STATE_COMPRESS          2'])
        values = {
            'RUN_ID': run['run_id'], 'CAMPAIGN_ID': campaign['campaign_id'], 'CODE_COMMIT': commit,
            'MODEL_COMMIT': model['commit'], 'START_YEAR': run['start_year'], 'END_YEAR': run['end_year'],
            'DOMAIN': f'{W}/{params["domain"]["path"]}', 'PARAMETERS': f'{W}/{params["parameters"]["path"]}',
            'CONSTANTS': f'{rdir}/config/vic_constants.txt', 'FORCE_TYPES': force_types,
            'INIT_STATE_LINES': f'INIT_STATE              {init_state}' if init_state else
                                '# cold start: no INIT_STATE (campaign initialisation.without_parent)',
            'STATE_LINES': state_lines,
            'ROUTING': tf(pl['routing']['enabled']), 'ROUT_STEPS_PER_DAY': pl['routing']['steps_per_day'],
            'DECOMPOSITION': pl['routing']['decomposition'],
            'ROUTING_PARAMETERS': f'{W}/{params["routing"]["path"]}',
            'DECOMPOSITION_PARAMETERS': f'{W}/{params["decomposition"]["path"]}',
            'WATERUSE': tf(pl['water_use']['enabled']), 'WATERUSE_PARAMETERS': f'{W}/{params["water_use"]["path"]}',
            'LOCAL_WITHDRAWAL': tf(pl['water_use']['local_withdrawal']),
            'REMOTE_WITHDRAWAL': tf(pl['water_use']['remote_withdrawal']),
            'COMPENSATION_WITHDRAWAL': tf(pl['water_use']['compensation_withdrawal']),
            'NONRENEWABLE_WITHDRAWAL': tf(pl['water_use']['nonrenewable_withdrawal']),
            'NONRENEWABLE_RUNOFF': tf(pl['water_use']['nonrenewable_runoff']),
            'WATER_USE_FORCE_TYPES': '\n'.join(wu_lines),
            'IRRIGATION': tf(pl['irrigation']['enabled']), 'IRRIGATION_PARAMETERS': f'{W}/{params["irrigation"]["path"]}',
            'POTENTIAL_IRRIGATION': tf(pl['irrigation']['potential_irrigation']),
            'EFFICIENT_IRRIGATION': tf(pl['irrigation']['efficient_irrigation']),
            'OFFSET_IRRIGATION': tf(pl['irrigation']['offset_irrigation']),
            'PBARE': pl['irrigation']['paddy_bare_class'],
            'DAMS': tf(pl['dams']['enabled']), 'DAMS_PARAMETERS': f'{W}/{params["dams"]["path"]}',
            'LANDUSE': tf(pl['landuse']['enabled']),
            'LANDUSE_FORCE_TYPE': f'PLUGIN_FORCE_TYPE  CV  coverage  YEAR  {view}/landuse/coverage_{usoc}_',
            'EFR': tf(pl['efr']['enabled']), 'WOFOST': tf(pl['wofost']['enabled']),
            'RESULT_DIR': f'{rdir}/output/', 'LOG_DIR': f'{rdir}/logs/', 'OUTPUT_STREAMS': streams_text}
        vic_text = fill(open(os.path.join(REPO, VIC_TEMPLATE)).read(), values)
        constants = (f'# VIC constants of run {run["run_id"]} (campaign plugins.dams)\n'
                     f'DAM_ALPHA {pl["dams"]["alpha"]}\nDAM_BETA {pl["dams"]["beta"]}\nDAM_GAMMA {pl["dams"]["gamma"]}\n')
        job_text, hours = render_job(W, rdir, campaign['campaign_id'], run['run_id'], run['start_year'],
                                     run['end_year'], resources, model)
        files = {'config/vic_global.txt': vic_text, 'config/vic_constants.txt': constants, 'config/job.sbatch': job_text}
        resolved = {
            'campaign_id': campaign['campaign_id'], 'run_id': run['run_id'], 'segment_id': run['segment_id'],
            'label': run['label'], 'start_year': run['start_year'], 'end_year': run['end_year'],
            'segment': seg, 'climate_input_alias': alias, 'dhf_unit': usoc,
            'experiments_using_segment': seg['experiments'],
            'parent': {'segment_id': parent, 'init_state': init_state and os.path.relpath(init_state, W),
                       'initialisation': 'state of the parent run' if init_state else 'cold_start'},
            'campaign_file': os.path.relpath(campaign_path, REPO) if os.path.isabs(campaign_path) else campaign_path,
            'campaign_sha256': file_hash(campaign_path), 'campaign': campaign,
            'resources_file': campaign['resources'], 'resources': resources,
            'model': model, 'parameters': params, 'decomposition': dec,
            'protocol_water_global_variables': nvars,
            'forcing_units': {k: {kk: vv for kk, vv in v.items() if kk != 'files'} for k, v in units.items()},
            'output_streams': streams, 'wall_time_hours': hours,
            'rendered_by': RENDERED_BY, 'code_commit': commit, 'code_dirty': dirty, 'rendered_at': utcnow()}
        files['config/resolved.yaml'] = yaml.safe_dump(resolved, sort_keys=False)
        for rel, text in files.items():
            with open(f'{rdir}/{rel}', 'w') as fh:
                fh.write(text)
        expected = []
        for y in range(run['start_year'], run['end_year'] + 1):
            expected += [f'output/daily.{y}-01-01.nc', f'output/monthly.{y}-01.nc']
        expected.append(f'states/state.{end_state:04d}0101_00000.nc')
        manifest = {
            'schema': 'isimip4b-run-manifest-1', 'campaign_id': campaign['campaign_id'], 'run_id': run['run_id'],
            'segment_id': run['segment_id'], 'label': run['label'], 'production': campaign['production'],
            'status': 'rendered', 'run_dir': os.path.relpath(rdir, W),
            'period': {'start': f'{run["start_year"]}-01-01', 'end': f'{run["end_year"]}-12-31'},
            'parent': resolved['parent'],
            'workflow': {'code_commit': commit, 'code_dirty': dirty, 'rendered_by': RENDERED_BY,
                         'rendered_at': resolved['rendered_at']},
            'campaign_config': {'path': resolved['campaign_file'], 'sha256': resolved['campaign_sha256']},
            'model': {k: model[k] for k in ('commit', 'freeze_status', 'build', 'build_status', 'executable',
                                            'executable_sha256', 'runtime_modules')},
            'inputs': {'parameter_set': campaign['parameter_set']['id'], 'parameters': params,
                       'forcing_units': units},
            'forcing_view': {k: {str(y): v for y, v in m.items()} for k, m in mapping.items()},
            'rendered_files': {rel: text_sha256(text) for rel, text in files.items()},
            'expected_outputs': expected,
            'attempts': []}
        sys.path.insert(0, os.path.join(HERE, '..', 'submit'))
        import run_manifest as rm
        manifest['inputs_fingerprint'] = rm.inputs_fingerprint(manifest)
        rm.save(rdir, manifest)
        rendered.append(rdir)
        print(f'rendered {rdir} ({len(links)} forcing links, {hours} h wall time, {resources["ntasks"]} tasks)')
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
