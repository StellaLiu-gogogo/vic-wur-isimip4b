#!/usr/bin/env python3
"""Build workdir/analysis/soil-comparison/report.html: method of the soil smoothing (task Z) and the comparison of
vic-global-5arcmin-version-a with version-b (parameter fields, 2011-2020 runs, GRDC stations, water use) and, when
the analysis tables hold it, with version-c (the MPR soil candidate of vic_parameter; part II of the report).
Every number comes from the QC records and the analysis tables; figures are embedded (base64)."""
import base64, csv, json, math, os, statistics, collections, datetime, html

W = os.environ['ISIMIP4B_WORKDIR']
A = f'{W}/analysis/soil-comparison'
QCB = f'{W}/qc/parameters/candidates/vic-global-5arcmin-version-b'
QCC = f'{W}/qc/parameters/candidates/vic-global-5arcmin-version-c'
RUN = 'ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020'
OUT = f'{A}/report.html'
REF = 'a'

def img(path, alt, cap=None, cls=''):
    with open(path, 'rb') as fh:
        b = base64.b64encode(fh.read()).decode()
    cap = f'<figcaption>{cap}</figcaption>' if cap else ''
    return f'<figure class="{cls}"><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}">{cap}</figure>'

def table(head, rows, cls='', note=None):
    h = ''.join(f'<th>{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    n = f'<p class="note">{note}</p>' if note else ''
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>{n}'

def f(x, d=2):
    return f'{x:,.{d}f}'

def pct(x, d=2):
    return f'{x * 100:+.{d}f} %'

def fl(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return float('nan')

# ------------------------------------------------------------------ the sets in the analysis tables
RC = json.load(open(f'{A}/tables/run_checks.json'))
VERS = list(RC['versions'])                       # e.g. ['a', 'b'] or ['a', 'b', 'c']; version-a is the reference
OTHERS = [v for v in VERS if v != REF]
HAS_C = 'c' in VERS
QCR = {v: f'{W}/qc/runs/soil-comparison-version-{v}/{RUN}' for v in VERS}
chk = {v: json.load(open(f'{QCR[v]}/reports/check.json')) for v in VERS}
ca, cb = chk['a'], chk['b']
VNAME = {v: f'version-{v}' for v in VERS}

# ------------------------------------------------------------------ parameter QC of version-b
build = json.load(open(f'{QCB}/soil/reports/build_report.json'))
ver = json.load(open(f'{QCB}/soil/reports/verify.json'))
vc = ver['checks']
roots = json.load(open(f'{QCB}/vegetation/reports/verify.json'))
ncell = build['active_cells']
FIELDS = ['depth', 'Ds', 'Dsmax', 'Ws', 'c']
LABEL = {'depth': 'depth[2] (m)', 'Ds': 'Ds (−)', 'Dsmax': 'Dsmax (mm/day)', 'Ws': 'Ws (%)', 'c': 'c (−)'}
rows = []
for k in FIELDS:
    b = build['fields'][k]; s = vc['staircase']['by_field'][k]; bm = vc['block_means']['by_field'][k]
    rows.append([LABEL[k], b['uniform'], b['mixed'], b['empty'],
                 f'{b["block_value_range"][0]:g} – {b["block_value_range"][1]:g}',
                 pct(b['cells_changed'] / ncell, 1), f'{b["max_abs_change"]:.3g}', pct(b['area_mean_relative_change'], 3),
                 f'{s["max_cell_jump_base"]:.3g} → {s["max_cell_jump_new"]:.3g} (bound {s["bound_block_difference_over_cells_between_centres"]:.3g})',
                 f'{bm["blocks_within"]["1%"]} / {bm["blocks_within"]["5%"]} / {bm["blocks_within"]["10%"]}'])
qc_fields = table(['field', 'uniform blocks', 'mixed blocks', 'empty blocks', 'value range', 'cells changed', 'largest change',
                   'area-mean change', 'largest jump between neighbouring cells, a → b', 'blocks whose mean stays within 1 / 5 / 10 %'],
                  rows, 'num', 'Blocks: 70 × 181 = 12 670 per field, 5 087 with active cells. The bound of the last-but-one column is the largest '
                  'difference between neighbouring block values divided by the 24 cells between block centres (18 next to the two '
                  '1-degree blocks). Block means are not conserved by bilinear interpolation (report only, user 2026-11-02).')
fq = build['fields']['depth']['fill_distance_km_quantiles']
mixed_q = build['fields']['Ds']['mixed_minority_share_quantiles']
checks_soil = ', '.join(f'{k} ({v if isinstance(v, str) else v.get("status")})' for k, v in json.load(open(f'{QCB}/soil/summary.json'))['checks'].items())
checks_roots = ', '.join(f'{k} ({v if isinstance(v, str) else v.get("status")})' for k, v in json.load(open(f'{QCB}/vegetation/summary.json'))['checks'].items())
rep = roots['checks']['reproduction']['by_class']
rep_tiles = sum(c['base_tiles'] for c in rep.values()); rep_eq = sum(c['root_fract_equal_after_float32'] for c in rep.values())

# ------------------------------------------------------------------ fields table (analysis step 1)
fr = list(csv.DictReader(open(f'{A}/tables/fields.csv')))      # one row per field, region and set (version-a the reference)
fmean = {(r['field'], r['region'], r['version']): r for r in fr}
def fields_table(v, skip=()):
    rows = []
    for r in fr:
        if r['version'] != v or r['field'] in skip:
            continue
        ra = fmean[(r['field'], r['region'], REF)]
        rows.append([r['field'], r['region'].replace('_', ' '), f'{int(r["cells"]):,}', f'{float(ra["mean"]):.4g}', f'{float(r["mean"]):.4g}',
                     pct(float(r['relative_change']), 2), pct(float(r['cells_changed_share']), 1), f'{float(r["max_abs_change"]):.3g}',
                     f'{float(r["p90_abs_change"]):.3g}'])
    return rows
fields_tab = table(['variable', 'region', 'active cells', 'mean a', 'mean b', 'change of the mean', 'cells changed', 'largest |b − a|', '90th percentile |b − a|'],
                   fields_table('b', skip=('Wcr_FRACT[2]',)), 'num',
                   'Area-weighted means over the active cells. root_fract[2] class 10 = layer-2 root fraction of grassland (IGBP class 10), '
                   'one of the 11 classes whose roots follow the Zeng (2001) rule; the change of a few per cent in West Siberia follows the depth change '
                   'there (the Alps keep depth[2] = 2.5 m everywhere, so the roots do not change).')

# ------------------------------------------------------------------ runs: global annual
ag = list(csv.DictReader(open(f'{A}/tables/annual_global.csv')))
VARS = [('sm2_mm', 'soil moisture layer 2 (mm)'), ('baseflow_mm', 'baseflow (mm/yr)'), ('runoff_mm', 'surface runoff (mm/yr)'),
        ('evap_mm', 'evapotranspiration (mm/yr)'), ('baseflow_share', 'baseflow / (baseflow + runoff) (−)')]
def mean(rows, k):
    return sum(float(r[k]) for r in rows) / len(rows)
def rel(x, a):
    return pct((x - a) / a) if a else '–'
rows = []
for k, lab in VARS:
    m10 = {v: mean(ag, f'{k}_{v}') for v in VERS}; m5 = {v: mean(ag[5:], f'{k}_{v}') for v in VERS}
    rows.append([lab, *[f'{m10[v]:.4g}' for v in VERS], *[f'{m10[v] - m10[REF]:+.3g} ({rel(m10[v], m10[REF])})' for v in OTHERS],
                 *[f'{m5[v]:.4g}' for v in VERS], *[rel(m5[v], m5[REF]) for v in OTHERS]])
annual_tab = table(['variable', *[f'{v} 2011–2020' for v in VERS], *[f'{v} − a' for v in OTHERS],
                    *[f'{v} 2016–2020' for v in VERS], *[f'{v} − a, relative' for v in OTHERS]], rows, 'num',
                   'Area-weighted means over the 2 188 551 active cells; soil moisture as the mean storage, fluxes as annual sums.')

ar = list(csv.DictReader(open(f'{A}/tables/annual_regions.csv')))
reg = collections.defaultdict(lambda: collections.defaultdict(list))
for r in ar:
    if int(r['year']) >= 2016:
        reg[r['region']][r['run']].append(r)
rows = []
for g in ('global', 'west_siberia', 'alps'):
    for k, lab in VARS:
        m = {v: mean(reg[g][v], k) for v in VERS}
        rows.append([g.replace('_', ' ') if k == 'sm2_mm' else '', lab, *[f'{m[v]:.4g}' for v in VERS],
                     *[f'{m[v] - m[REF]:+.3g} ({rel(m[v], m[REF])})' for v in OTHERS]])
region_tab = table(['region', 'variable', *VERS, *[f'{v} − a' for v in OTHERS]], rows, 'num',
                   'Means of 2016–2020 after the five settling years. West Siberia 58–66 N, 78–90 E (13 824 cells); the Alps 42–50 N, 2–14 E (11 868 cells).')

# ------------------------------------------------------------------ GRDC
st = list(csv.DictReader(open(f'{A}/tables/grdc_stations.csv')))
ok = [r for r in st if all(math.isfinite(fl(r[f'ratio_{v}'])) for v in VERS)]
G = {}
for v in VERS:
    la = [abs(math.log(fl(r[f'ratio_{REF}']))) for r in ok]; lv = [abs(math.log(fl(r[f'ratio_{v}']))) for r in ok]
    sa = [fl(r[f'seasonal_r_{REF}']) for r in ok]; sv = [fl(r[f'seasonal_r_{v}']) for r in ok]
    relc = sorted((fl(r[f'sim_mean_{v}']) - fl(r[f'sim_mean_{REF}'])) / fl(r[f'sim_mean_{REF}']) for r in ok)
    G[v] = {'med_abs_log': statistics.median(lv), 'imp': sum(y < x for x, y in zip(la, lv)), 'wor': sum(y > x for x, y in zip(la, lv)),
            'simp': sum(y > x for x, y in zip(sa, sv)), 'swor': sum(y < x for x, y in zip(sa, sv)), 'rel': relc}
n = len(ok)
g = {v: chk[v]['grdc'] for v in VERS}
grdc_sum = table(['', *[VNAME[v] for v in VERS]], [
    ['stations mapped / with a climatology', *[f'{g[v]["stations_mapped"]} / {g[v]["stations_with_climatology"]}' for v in VERS]],
    ['median of simulated / observed mean discharge', *[f'{g[v]["median_ratio_sim_obs"]:.3f}' for v in VERS]],
    ['share of stations within 0.8–1.25', *[pct(g[v]['share_within_0.8_1.25'], 1).lstrip('+') for v in VERS]],
    ['median seasonal correlation (monthly climatology)', *[f'{g[v]["median_seasonal_r"]:.3f}' for v in VERS]],
    ['median |ln(sim/obs)|', *[f'{G[v]["med_abs_log"]:.3f}' for v in VERS]],
    ['stations whose bias improved / worsened against a', '', *[f'{G[v]["imp"]} / {G[v]["wor"]} of {n}' for v in OTHERS]],
    ['stations whose seasonal correlation improved / worsened against a', '', *[f'{G[v]["simp"]} / {G[v]["swor"]} of {n}' for v in OTHERS]],
    ['change of the simulated mean discharge against a, 5th / 50th / 95th percentile over stations', '',
     *[f'{G[v]["rel"][int(.05 * n)] * 100:+.2f} % / {G[v]["rel"][n // 2] * 100:+.4f} % / {G[v]["rel"][int(.95 * n)] * 100:+.2f} %' for v in OTHERS]],
], 'num', 'Simulated years 2012–2020 (the cold-start year excluded by the run check) against the GRDC monthly climatology of 2001–2024; '
          'catchments ≥ 10 000 km².')
def grdc_big(v, note):
    big = sorted(ok, key=lambda r: abs(math.log(fl(r[f'ratio_{v}']) / fl(r[f'ratio_{REF}']))), reverse=True)[:12]
    rows = [[r['river'].title(), r['station'].title(), f'{fl(r["area_km2"]):,.0f}', f'{fl(r["obs_mean_m3_s"]):,.0f}', f'{fl(r[f"sim_mean_{REF}"]):,.0f}',
             f'{fl(r[f"sim_mean_{v}"]):,.0f}', f'{fl(r[f"ratio_{REF}"]):.2f} → {fl(r[f"ratio_{v}"]):.2f}',
             f'{fl(r[f"seasonal_r_{REF}"]):.2f} → {fl(r[f"seasonal_r_{v}"]):.2f}'] for r in big]
    return table(['river', 'station', 'area (km²)', 'observed (m³/s)', 'a (m³/s)', f'{v} (m³/s)', f'sim/obs a → {v}', f'seasonal r a → {v}'], rows, 'num', note)
grdc_big_b = grdc_big('b', 'The twelve stations with the largest relative change of the simulated mean discharge, b against a. Nine are in the Canadian '
                      'prairies and boreal plains (Saskatchewan, Manitoba, Alberta), where version-a has large depth[2] contrasts between neighbouring blocks.')
large = sorted(ok, key=lambda r: -fl(r['obs_mean_m3_s']))[:10]
rows = [[r['river'].title(), r['station'].title(), f'{fl(r["obs_mean_m3_s"]):,.0f}', *[f'{fl(r[f"sim_mean_{v}"]):,.0f}' for v in VERS],
         *[f'{(fl(r[f"sim_mean_{v}"]) / fl(r[f"sim_mean_{REF}"]) - 1) * 100:+.2f} %' for v in OTHERS],
         ' → '.join(f'{fl(r[f"ratio_{v}"]):.2f}' for v in VERS), ' → '.join(f'{fl(r[f"seasonal_r_{v}"]):.3f}' for v in VERS)] for r in large]
grdc_large = table(['river', 'station', 'observed (m³/s)', *[f'{v} (m³/s)' for v in VERS], *[f'{v} − a' for v in OTHERS],
                    'sim/obs ' + ' → '.join(VERS), 'seasonal r ' + ' → '.join(VERS)], rows, 'num', 'The ten stations with the largest observed discharge.')

# ------------------------------------------------------------------ water balance and water use
wbal = {v: chk[v]['water_balance'] for v in VERS}
wb_tab = table(['', *[VNAME[v] for v in VERS]], [
    ['run check status', *[chk[v]['status'] for v in VERS]],
    ['cell-months checked', *[f'{wbal[v]["cell_months"]:,}' for v in VERS]],
    ['99th percentile of |water error| (mm/month)', *[f'{wbal[v]["p99_abs_monthly_mean_water_error_mm"]}' for v in VERS]],
    ['largest |water error| (mm/month)', *[f'{wbal[v]["max_abs_monthly_mean_water_error_mm"]:.3f}' for v in VERS]],
    ['cell-months above the 1 mm limit', *[f'{wbal[v]["cell_months_above_limit"]}' for v in VERS]],
], 'num')
tot = {v: collections.defaultdict(float) for v in VERS}
q = {v: [] for v in VERS}
for v in VERS:
    c = chk[v]
    for y in sorted(c['years']):
        yy = c['years'][y]; q[v].append(yy['qtot']['global_km3_per_year'])
        for sec, src in yy['withdrawal_by_sector_km3'].items():
            for s, val in src.items():
                tot[v][(sec, s)] += val / len(c['years'])
SRC = [('withdrawal', 'total withdrawal'), ('surf', 'river and lakes'), ('gw', 'renewable groundwater'), ('nren', 'non-renewable groundwater'),
       ('trem', 'remote source (transfers)'), ('dam', 'dams')]
qm = {v: statistics.mean(q[v]) for v in VERS}
rows = [['total runoff, qtot (km³/yr)', *[f'{qm[v]:,.0f}' for v in VERS], *[rel(qm[v], qm[REF]) for v in OTHERS]]]
for sec in ('irrigation', 'manufacturing', 'municipal'):
    for s, lab in SRC:
        if tot[REF][(sec, s)] > 0.01:
            rows.append([f'{sec}: {lab} (km³/yr)', *[f'{tot[v][(sec, s)]:,.1f}' for v in VERS], *[rel(tot[v][(sec, s)], tot[REF][(sec, s)]) for v in OTHERS]])
dfc = {v: chk[v]['years']['2020']['nonrenewable']['deficit_end_of_year_km3'] for v in VERS}
rows.append(['non-renewable water not yet repaid at the end of 2020 (km³)', *[f'{dfc[v]:,.0f}' for v in VERS], *[rel(dfc[v], dfc[REF]) for v in OTHERS]])
wu_tab = table(['', *[VNAME[v] for v in VERS], *[f'{v} − a, relative' for v in OTHERS]], rows, 'num',
               'Means of 2011–2020 from the run checks (withdrawal per sector and source). Energy and livestock withdrawals are zero in this campaign (D02/D03 settings).')

# ------------------------------------------------------------------ part II: version-c (the MPR soil)
part2 = ''
toc2 = ''
if HAS_C:
    verc = json.load(open(f'{QCC}/soil/reports/verify.json')); vcc = verc['checks']
    rootc = json.load(open(f'{QCC}/vegetation/reports/verify.json'))
    checks_soil_c = ', '.join(f'{k} ({v if isinstance(v, str) else v.get("status")})' for k, v in json.load(open(f'{QCC}/soil/summary.json'))['checks'].items())
    checks_roots_c = ', '.join(f'{k} ({v if isinstance(v, str) else v.get("status")})' for k, v in json.load(open(f'{QCC}/vegetation/summary.json'))['checks'].items())
    gm = vcc['global_means']['by_field']
    UNITS = {'expt': '−', 'Ksat': 'mm/day', 'bubble': 'cm', 'quartz': '−', 'bulk_density': 'kg/m³', 'soil_density': 'kg/m³', 'depth': 'm',
             'init_moist': 'mm', 'max_moist': 'mm', 'Wcr_FRACT': '−', 'Wpwp_FRACT': '−', 'Wfc_FRACT': '−', 'resid_moist': '−', 'infilt': '−',
             'Ds': 'as stored (NIJSSEN2001 form)', 'Dsmax': 'as stored (NIJSSEN2001 form)', 'Ws': 'as stored (NIJSSEN2001 form)', 'c': '−'}
    rows = []
    for k, x in gm.items():
        layers = sorted(x) if 'base' not in x else [None]
        for l in layers:
            y = x[l] if l else x
            rows.append([f'{k}[{l[-1]}]' if l else k, UNITS.get(k, ''), f'{y["base"]:.4g}', f'{y["new"]:.4g}', rel(y['new'], y['base'])])
    mpr_means = table(['field', 'unit', 'version-a', 'version-c', 'change'], rows, 'num',
                      'Area-weighted means over the active cells from the verifier of the soil component (check global_means, report only). '
                      'Layer index in brackets (1 = top). Every value of version-c on the active cells is the stored value of the MPR file.')
    depth2 = gm['depth']['layer2']
    sm_c = {v: mean(ag, f'sm2_mm_{v}') for v in VERS}
    bf_c = {v: mean(ag, f'baseflow_mm_{v}') for v in VERS}; ro_c = {v: mean(ag, f'runoff_mm_{v}') for v in VERS}
    ev_c = {v: mean(ag, f'evap_mm_{v}') for v in VERS}; bs_c = {v: mean(ag, f'baseflow_share_{v}') for v in VERS}
    fields_tab_c = table(['variable', 'region', 'active cells', 'mean a', 'mean c', 'change of the mean', 'cells changed', 'largest |c − a|', '90th percentile |c − a|'],
                         fields_table('c'), 'num', 'Area-weighted means over the active cells; the same variables as in section 4, version-c against version-a.')
    grdc_big_c = grdc_big('c', 'The twelve stations with the largest relative change of the simulated mean discharge, c against a.')
    toc2 = ('<li><a href="#mpr">Part II. Version-c: the MPR soil</a></li><li><a href="#mprfields">The MPR fields against version-a</a></li>'
            '<li><a href="#mprruns">The version-c run</a></li><li><a href="#mprgrdc">GRDC stations and water use with version-c</a></li>'
            '<li><a href="#mprread">Reading of the three sets</a></li>')
    part2 = f"""
<h2 id="mpr">11. Part II. Version-c: the MPR soil candidate</h2>
<p>Version-b changes only the five calibration fields. Version-c asks a different question: what happens when the whole soil of the version-a file (18 fields: the hydraulic properties, the layer depths, the moisture thresholds and the four baseflow parameters) is replaced by the MPR soil candidate of <code>vic_parameter</code> (<code>nauta_mpr_reproduced_5m_candidate_v2</code>, 2026-09-06): SoilGrids 2017 through the Cosby transfer functions and the multiscale parameter regionalisation operators, with the Nijssen effective layer depths and the baseflow parameters from its stage 2 (D2 = D1, D4 = 2), a prior that was not calibrated against discharge. The soil component of version-c (<code>workflow/03_parameters/soil/adopt_soil_fields.py</code>) copies the version-a file and writes, on the active cells, the stored values of the MPR file for the 18 fields; elevation, the snow bands and every other variable stay as in version-a. The root zones were recomputed with the new layer depths as for version-b, and the other components are the verified copies of version-a. The source carries <code>not_authorized_for_global_production = true</code>: a promotion of version-c would need the user's acceptance of that restriction.</p>
<p>The verifier of the component ({checks_soil_c}) found the 18 fields bitwise equal to the source on all {vcc['grid']['active_cells']:,} active cells, everything else bitwise unchanged, the moisture closure of the source (porosity, max_moist, init_moist, resid_moist, Wpwp ≤ Wcr ≤ Wfc) and the VIC rules of <code>vic_init.c</code> satisfied on every active cell; the root-zone verifier ({checks_roots_c}) and the bundle verifier (7 checks) passed as well. The table below shows how far the MPR soil is from version-a in the global mean: the second layer is {depth2['new'] / depth2['base']:.1f} times deeper ({depth2['base']:.2f} → {depth2['new']:.2f} m, the MPR candidate caps it at 5 m, which most of the land reaches), the saturated conductivity is higher, the baseflow parameters are of another kind (<code>c</code> = 2 everywhere, <code>Ds</code> equal to <code>Dsmax</code>; see <code>analysis/block-structure</code>). Version-c is therefore not a repair of version-a but a different soil; the comparison below shows what that does to the water balance and the discharge.</p>
<div class="wrap">{mpr_means}</div>
{img(f'{QCC}/soil/figures/depth_west_siberia.png', 'depth[2] version-a and MPR, West Siberia', 'Figure 13. depth[2] (m) in West Siberia: version-a (left) and the MPR soil of version-c (right). From the QC of the soil component.')}
{img(f'{QCC}/soil/figures/depth2_global.png', 'global depth[2] MPR', 'Figure 14. depth[2] of version-c over the globe.')}

<h2 id="mprfields">12. The MPR fields against version-a</h2>
<p>Step <code>fields</code> of the analysis, run for the three sets, compares the same variables as section 4 (version-c against version-a). Unlike the smoothing, the MPR soil changes every field on almost every cell and the means by a lot.</p>
<div class="wrap">{fields_tab_c}</div>
{img(f'{A}/figures/fields_depth_west_siberia_c.png', 'depth[2] West Siberia a, c, difference', 'Figure 15. depth[2] (m) in West Siberia: version-a, version-c and the difference c − a.')}
{img(f'{A}/figures/fields_depth_alps_c.png', 'depth[2] Alps a, c', 'Figure 16. depth[2] (m) in the Alps: version-a (2.5 m throughout), version-c and the difference.')}
{img(f'{A}/figures/fields_Ds_alps_c.png', 'Ds Alps a, c', 'Figure 17. Ds in the Alps: version-a and version-c (another parameterisation: Ds = Dsmax in the MPR soil).')}

<h2 id="mprruns">13. The version-c run</h2>
<p>The campaign <code>soil-comparison-version-c</code> is the third copy of the comparison campaign (same segment, years, settings and build; only the parameter set differs). The run took 10 h 30 min and wrote 229 GB; its run check passed (tables of sections 5, 6 and 9 above now carry version-c as a third column). In the global mean over 2011–2020 version-c holds {sm_c['c'] / sm_c['a']:.2f} times the layer-2 storage of version-a ({sm_c['a']:.0f} → {sm_c['c']:.0f} mm), baseflow changes by {pct((bf_c['c'] - bf_c['a']) / bf_c['a'], 1)}, surface runoff by {pct((ro_c['c'] - ro_c['a']) / ro_c['a'], 1)}, evapotranspiration by {pct((ev_c['c'] - ev_c['a']) / ev_c['a'], 1)} and the baseflow share of total runoff goes from {bs_c['a']:.3f} to {bs_c['c']:.3f}. With a cold start the deep layer 2 of version-c starts from the <code>init_moist</code> of the MPR file and settles over the first years (figure 6, the dotted difference line).</p>
{img(f'{A}/figures/runs_sm2_global_c.png', 'sm2 global c', 'Figure 18. Layer-2 soil moisture (mm), mean 2016–2020, global: version-a, version-c, difference.')}
{img(f'{A}/figures/runs_baseflow_global_c.png', 'baseflow global c', 'Figure 19. Baseflow (mm/yr), mean 2016–2020, global: version-a, version-c, difference.')}
{img(f'{A}/figures/runs_baseflow_share_global_c.png', 'baseflow share global c', 'Figure 20. Baseflow share of total runoff, mean 2016–2020, global.')}
{img(f'{A}/figures/runs_sm2_west_siberia_c.png', 'sm2 West Siberia c', 'Figure 21. Layer-2 soil moisture (mm), mean 2016–2020, West Siberia: version-a, version-c, difference.')}
{img(f'{A}/figures/runs_baseflow_west_siberia_c.png', 'baseflow West Siberia c', 'Figure 22. Baseflow (mm/yr), mean 2016–2020, West Siberia.')}

<h2 id="mprgrdc">14. GRDC stations and water use with version-c</h2>
<p>The GRDC summary (section 8, now with version-c) and the water-use table (section 9) are read together with the table below: version-c against version-a, median sim/obs {g['a']['median_ratio_sim_obs']:.3f} → {g['c']['median_ratio_sim_obs']:.3f}, median |ln(sim/obs)| {G['a']['med_abs_log']:.3f} → {G['c']['med_abs_log']:.3f}, {G['c']['imp']} stations improved against {G['c']['wor']} worsened of {n}, median seasonal correlation {g['a']['median_seasonal_r']:.3f} → {g['c']['median_seasonal_r']:.3f}; at 90 % of the stations the simulated mean changes by between {G['c']['rel'][int(.05 * n)] * 100:+.1f} % and {G['c']['rel'][int(.95 * n)] * 100:+.1f} %.</p>
<div class="wrap">{grdc_big_c}</div>

<h2 id="mprread">15. Reading of the three sets</h2>
<p>Version-c is a different soil, and the run shows a different model.</p>
<ol>
<li><strong>Water balance.</strong> With a second layer 2.5 times deeper, a wilting point and a critical point half those of version-a and a 40 % higher saturated conductivity, the vegetation has far more water within reach: evapotranspiration rises by 9 % (+52 mm/yr) and total runoff falls by 23 % (baseflow −24 %, surface runoff −22 % over 2011–2020; −14 % and −19 % over 2016–2020, once the deep layer has filled). The layer-2 storage grows from 500 to 900 mm and is still rising slightly in 2020 (figure 6): ten years from a cold start do not settle a 5 m soil everywhere, so the 2016–2020 means of version-c carry a small drift that the other two runs do not have. Regionally the storage gain is largest where version-a had shallow blocks (West Siberia +970 mm, three times the version-a storage); the surface runoff falls everywhere; the baseflow map (figure 19) loses most in the Amazon basin, Southeast Asia and West Africa and gains along the Pacific coast of North America, the Andes and the Himalayan foothills.</li>
<li><strong>GRDC stations.</strong> Version-a overestimates the mean discharge by a third at the median station; version-c removes that bias at the median (sim/obs 0.981) and brings 595 stations closer to the observations against 381, but it does so by lowering the discharge at 970 of the 976 stations, by 36 % at the median. The spread around the observations does not shrink (median |ln(sim/obs)| 0.378 → 0.374): of the 326 stations that version-a had within 0.8–1.25, only 157 stay there; 158 of the 257 stations that version-a overestimated by 25–100 % move inside; the 100 stations that version-a underestimated get worse (median ratio 0.66 → 0.39). The large rivers, which version-a had about right, are now underestimated: the Amazon at Óbidos 0.97 → 0.82, the Mississippi at Vicksburg 0.89 → 0.58, the Yenisey at Igarka 1.18 → 0.85, the Madeira 1.17 → 0.80. The seasonal correlation worsens at the median (0.832 → 0.808; 431 stations better, 545 worse): the deep layer damps the snowmelt peak of the northern rivers (Yenisey 0.98 → 0.77, Mississippi 0.83 → 0.55) while it improves the Amazon (0.74 → 0.90).</li>
<li><strong>Water use.</strong> Municipal and manufacturing withdrawals follow the demand forcing and do not change. The irrigation withdrawal falls by a third (2 873 → 1 904 km³/yr): VIC-WUR irrigates when the root-zone moisture falls below the critical point, and the critical point of the MPR soil is half that of version-a (Wcr_FRACT 0.59 → 0.28), so the crops are irrigated later and less. With less baseflow the renewable groundwater shrinks (−73 % of a small amount) and the non-renewable withdrawal halves; the non-renewable water not repaid at the end of 2020 is 39 % smaller.</li>
<li><strong>Reading for the decision.</strong> Version-b is version-a without its steps: the same water balance, the same discharge, only the smoothing. Version-c is another soil whose uncalibrated prior parameters move the model to another state: a lower discharge bias at the median at the price of underestimating the large rivers and flattening the snowmelt seasonality, a third less irrigation, and a soil that takes more than ten years to settle from a cold start (a production spin-up would have to be checked for it). It cannot be judged from one 10-year run against version-a alone: its global water terms (ET +9 %, runoff −23 %) would have to be compared with independent estimates, and its layer-2 depth (5 m over most of the land) and baseflow parameters (c = 2, Ds = Dsmax) are the stage-2 settings of the MPR candidate, not calibrated values; the source also carries <code>not_authorized_for_global_production</code>. The recommendation of part I stands: promote version-b for the production campaign; keep version-c as a candidate for a calibration or evaluation task of its own, not for the production campaign now. The decision is the user's.</li>
</ol>
"""

# ------------------------------------------------------------------ provenance
prov_rows = [
    ['base parameter set', 'vic-global-5arcmin-version-a (production), bundle vic_global_5min_16class_landuse-union_root-b-zeng2001.nc'],
    ['candidate parameter set', 'vic-global-5arcmin-version-b (candidate), manifests/parameters/vic-global-5arcmin-version-b.yaml'],
    ['soil component', f'job 43542860, code commit {build["code_commit"][:7]}, QC {ver["status"]}: {checks_soil}'],
    ['root zones', f'job 43542862, QC {roots["status"]}: {checks_roots}; {rep_eq:,} of {rep_tiles:,} base tiles reproduce version-a root_fract exactly after float32 rounding'],
    ['assembled bundle', 'job 43542901, QC passed (7 checks); copied components (domain, routing, dams, irrigation, water use, decomposition) QC passed, jobs 43551227/43551228/43551229'],
    ['comparison runs', 'campaigns soil-comparison-version-a / -b (non-production), 2011–2020 historical histsoc, cold start, VIC-WUR build a826251b, 16 ranks × 8 threads; '
                        'jobs 43551798 (a, 10 h 16 min) and 43553341 (b, 10 h 22 min); 212 GB of output each'],
    ['run checks', f'jobs 43569306 (a) and 43569307 (b), code commit {ca["code_commit"][:7]}, both passed; records under qc/runs/soil-comparison-version-{{a,b}}/'],
]
if HAS_C:
    prov_rows += [
        ['version-c parameter set', 'vic-global-5arcmin-version-c (candidate), manifests/parameters/vic-global-5arcmin-version-c.yaml; soil source '
                                    f'{os.path.basename(vcc["replaced"]["soil_source"])} (sha256 as recorded; not_authorized_for_global_production = true)'],
        ['version-c components', f'copy 43600676; soil 43600681 built, 43600813 verified ({verc["status"]}: {checks_soil_c}); root zones 43600821, 43601037 verified '
                                 f'({rootc["status"]}: {checks_roots_c}); bundle 43601169 (7 checks); copied components QC 43602238/43602239/43602240'],
        ['version-c run', 'campaign soil-comparison-version-c, job 43602395 (10 h 30 min, node246; time limit reduced to 12 h by the user so that it ran before the '
                          'maintenance of 2026-11-05), 229 GB of output'],
        ['version-c run check', f'job 43610874 (the first check 43602435 passed with the same numbers but was recorded under scratch/run-check/uncommitted/, this '
                                f'analysis directory being uncommitted when it ran), code commit {chk["c"]["code_commit"][:7]}, {chk["c"]["status"]}'],
    ]
prov_rows += [
    ['analysis', 'analysis/soil-comparison/soil_comparison.py (branch task-z-soil-smoothing): step fields jobs 43553379 (a b)' + (', 43610880 (a b c)' if HAS_C else '') +
                 '; step runs jobs 43586550 (a b)' + (', 43617981 (a b c)' if HAS_C else '') + '; tables and figures under workdir/analysis/soil-comparison/'],
    ['this report', f'built {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%MZ} from the QC records and the analysis tables; figures embedded'],
]
prov_tab = table(['item', 'record'], prov_rows)

# ------------------------------------------------------------------ page
CSS = """
:root{--bg:#fbfaf7;--fg:#1f2328;--muted:#5d6670;--line:#d9d6cf;--accent:#1f5f8b;--soft:#eef3f7;--warn:#8a5a00;--warnbg:#fff6e0;}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15181c;--fg:#e6e6e3;--muted:#a3a9b1;--line:#363b42;--accent:#7fb3dc;--soft:#1e2a33;--warn:#f0c674;--warnbg:#2b2410;}}
:root[data-theme=dark]{--bg:#15181c;--fg:#e6e6e3;--muted:#a3a9b1;--line:#363b42;--accent:#7fb3dc;--soft:#1e2a33;--warn:#f0c674;--warnbg:#2b2410;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 Georgia,"Times New Roman",serif;}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px;}
h1{font-size:1.9rem;line-height:1.2;margin:0 0 .3rem}
h2{font-size:1.35rem;margin:2.4rem 0 .8rem;padding-top:.6rem;border-top:1px solid var(--line)}
h3{font-size:1.1rem;margin:1.6rem 0 .5rem}
p,li{max-width:78ch}
.sub{color:var(--muted);margin:0 0 1.2rem}
.key{background:var(--soft);border-left:4px solid var(--accent);padding:.8rem 1rem;margin:1rem 0}
.key p{margin:.3rem 0}
.caveat{background:var(--warnbg);border-left:4px solid var(--warn);padding:.6rem 1rem;margin:1rem 0}
table{border-collapse:collapse;width:100%;margin:.6rem 0 .3rem;font:14px/1.4 "Helvetica Neue",Arial,sans-serif}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}
table.num td:not(:first-child){text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.note{color:var(--muted);font-size:.85rem;margin:.2rem 0 1rem}
figure{margin:1rem 0}
figure img{width:100%;height:auto;border:1px solid var(--line);background:#fff}
figcaption{color:var(--muted);font-size:.85rem;margin-top:.3rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){.two{grid-template-columns:1fr}}
code{font:.9em/1.3 Menlo,Consolas,monospace;background:var(--soft);padding:1px 4px;border-radius:3px}
.toc{columns:2;column-gap:2rem;font-size:.95rem}
.toc a{color:var(--accent);text-decoration:none}
nav ol{margin:.2rem 0 0 1.2rem;padding:0}
.wrap{overflow-x:auto}
"""

sets_line = ' and '.join(f'<code>vic-global-5arcmin-{VNAME[v]}</code> ({"production" if v == REF else "candidate"})' for v in VERS)
H = []
H.append(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Soil smoothing comparison</title><style>{CSS}</style></head><body><main>
<h1>Smoothing the 2-degree soil calibration fields: version-a against version-b{' (and the MPR soil, version-c)' if HAS_C else ''}</h1>
<p class="sub">ISIMIP4b VIC-WUR parameter sets {sets_line}, task Z; analysis task <code>analysis/soil-comparison</code>. {datetime.date.today():%d %B %Y}.</p>

<div class="key">
<p><strong>Question.</strong> Version-a carries five soil parameters on 2-degree blocks inherited from the Nijssen et al. (2001) calibration: the depth of the second soil layer and the four baseflow parameters. Where neighbouring blocks differ, the simulated layer-2 storage and baseflow step along block edges. Does replacing the block values by a smooth field (version-b) remove the steps without changing the global water balance or the discharge at the GRDC stations for the worse?</p>
<p><strong>Answer.</strong> Yes. The smoothing changes the area-weighted global means of the five fields by less than 0.05 %, keeps every cell within the range of the blocks around it and removes the steps (largest jump between neighbouring cells 24 times smaller). In a 10-year run with the production settings the global water balance closes as before (both run checks passed, identical error statistics), total runoff changes by −0.08 %, evapotranspiration by +0.06 %, and the partition shifts slightly towards baseflow (+0.8 %) at the expense of surface runoff (−1.2 %). The GRDC comparison is marginally better for version-b (median sim/obs 1.355 → 1.345, median |ln(sim/obs)| 0.378 → 0.373, 514 stations improved against 462 worsened, seasonal correlation 0.832 → 0.833); the ten largest rivers change by at most 0.2 %. The visible effect is local: along former block edges the layer-2 storage changes by up to ±300 mm (where depth[2] stepped from 0.5 to 2.5 m) and baseflow by up to ±30 mm/yr, in both directions, so that the staircase in the moisture and baseflow maps disappears.</p>
<p><strong>Recommendation.</strong> Promote version-b to production and use it in the production campaign (<code>configs/campaigns/water-global-ec-earth3-esm-1-1.yaml</code>, <code>parameter_set.id</code>). The decision is the user's; the exact change is given at the end.{' Part II (sections 11–15) adds the third set, version-c with the MPR soil, to the same tables and figures; its reading is in section 15.' if HAS_C else ''}</p>
</div>

<nav><strong>Contents</strong><ol class="toc">
<li><a href="#why">The staircase in version-a</a></li><li><a href="#method">Method of the smoothing</a></li><li><a href="#qc">Quality control of the candidate</a></li>
<li><a href="#fields">The parameter fields compared</a></li><li><a href="#runs">The comparison runs</a></li><li><a href="#global">Global and regional water balance</a></li>
<li><a href="#maps">Maps: where the runs differ</a></li><li><a href="#grdc">Discharge at the GRDC stations</a></li><li><a href="#wateruse">Water use</a></li>
<li><a href="#conclusion">Conclusion and next steps</a></li>{toc2}<li><a href="#prov">Provenance</a></li></ol></nav>

<h2 id="why">1. The staircase in version-a</h2>
<p>The image-driver parameter file of version-a (1680 × 4320 cells of 5 arc minutes, 2 188 551 active cells) holds the depth of soil layer 2, <code>depth[2]</code>, and the NIJSSEN2001 baseflow parameters <code>Ds</code>, <code>Dsmax</code>, <code>Ws</code> and <code>c</code> as constants over 2-degree blocks: they were calibrated on a 2-degree grid and copied to every 5-arcmin cell of the block. <code>depth[2]</code> takes only six values between 0.5 and 4 m, <code>Dsmax</code> nine. The blocks are 70 rows × 181 columns: the latitude edges lie on even degrees everywhere; the longitude edges lie on even degrees east of 0° and on odd degrees west of 0° (the negative longitudes were rounded the other way when the calibration was mapped), which leaves two 1-degree blocks at [−180, −179] and [−1, 0]. Every other soil variable (the layer depths 1 and 3, the hydraulic properties, the snow bands, elevation) varies from cell to cell.</p>
<p>Where neighbouring blocks differ, the fields step at the edge; VIC's layer-2 storage capacity (<code>max_moist[2]</code> = depth × porosity) and the baseflow curve step with them, and so do the simulated soil moisture, baseflow and the baseflow share of runoff. In West Siberia <code>depth[2]</code> drops from 2.5 m to 0.5 m across a single block edge (left panel below); the 2016–2020 mean layer-2 storage of the version-a run follows the edge exactly (section 7).</p>
{img(f'{QCB}/soil/figures/depth_west_siberia.png', 'depth[2] base and smoothed, West Siberia', 'Figure 1. depth[2] (m) in West Siberia (58–66 N, 78–90 E): version-a (left) and the smoothed field of version-b (right). From the QC of the soil component.')}
{img(f'{QCB}/soil/figures/depth2_global.png', 'global depth[2] smoothed', 'Figure 2. The smoothed depth[2] of version-b over the globe. Six calibration values (0.5–4 m) remain the plateaus; the transitions are now 2 degrees wide.')}

<h2 id="method">2. Method of the smoothing</h2>
<p>The producer <code>workflow/03_parameters/soil/smooth_calibration_fields.py</code> (method version 1.0, design approved by the user on 2026-11-02) builds a soil component from the assembled bundle of version-a in four steps; only the five calibration fields and the two layer-2 variables that depend on them change, the other 48 non-vegetation variables are copied bit for bit.</p>
<ol>
<li><strong>Recover the blocks.</strong> Each field is cut into the 2-degree blocks described above (block edges region dependent as found on all five fields). A block takes the single value of its active cells (uniform block, {build['fields']['depth']['uniform']:,} of 5 087 land blocks for depth[2]) or, for the {min(b['mixed'] for b in build['fields'].values())}–{max(b['mixed'] for b in build['fields'].values())} mixed blocks that straddle a coast or a mask edge, the most frequent value (ties take the smaller value; the minority share is 9–13 % at the median, at most 62 %). The 7 583 blocks without active cells (ocean, Antarctica, Greenland) take the value of the nearest land block on the sphere (great-circle distance between block centres; median {fq['50']:.0f} km, at most {fq['100']:.0f} km), so that the interpolation has a value on every side of every coastal cell. Every block is recorded in <code>calibration_blocks.csv</code>.</li>
<li><strong>Interpolate.</strong> Every active cell receives the bilinear interpolation of the four block centres around it: linear in latitude between the two nearest centre rows (beyond the outermost rows the nearest row alone), linear in longitude between the two nearest centre columns, periodic across 180°. The result is clipped to the range of the four blocks, so that no cell lies outside its neighbourhood. A block centre keeps its calibration value, the plateaus of uniform regions are untouched, and the steps turn into linear ramps 24 cells (2 degrees) wide. Block means are not conserved: an isolated block is pulled towards its neighbours (reported, not judged).</li>
<li><strong>Dependent variables.</strong> <code>max_moist[2] = depth[2] × (1 − bulk_density / soil_density) × 1000</code> mm is recomputed in double precision; <code>init_moist[2]</code> keeps the ratio <code>init_moist[2] / max_moist[2]</code> of version-a cell by cell (0.18–0.81), so the cold-start state is equivalent. Layers 1 and 3 are untouched.</li>
<li><strong>Root zones.</strong> The root fractions of the vegetation classes depend on the layer depths. <code>workflow/03_parameters/vegetation/recompute_roots.py</code> recomputes <code>root_fract</code> and <code>root_depth</code> for the 11 classes whose roots in version-a follow the Zeng (2001) profile, Y(d) = 1 − ½(e<sup>−a d</sup> + e<sup>−b d</sup>), integrated between the layer interfaces and normalised within the soil column (coefficients in <code>root_zeng2001_igbp.yaml</code>; crop class 13 as in version-a). Classes 11, 12, 14, 15 and 16 keep their constants; tiles added by the land-use union copy their donor cell. The rule was verified first: with the version-a depths it reproduces the version-a root fractions exactly on {rep_eq:,} of {rep_tiles:,} tiles after rounding to float32.</li>
</ol>
<p>The bundle component then assembles the image-driver file from the new soil component and the recomputed vegetation (<code>assemble_bundle.py --soil-component</code>); domain, routing, dams, irrigation, water-use links and the decomposition are copied from version-a unchanged (<code>copy_components.py</code>), with their QC re-run. New values are written in double precision; cells outside the domain mask keep their fill values.</p>

<h2 id="qc">3. Quality control of the candidate</h2>
<p>The independent verifier <code>verify_soil.py</code> recomputes the block values with its own loop, checks the fill against the nearest land block, the four cells around every block centre against the block value, every cell against the range of its four blocks, the largest jump between neighbouring cells against the largest jump between neighbouring blocks divided by the cells between the centres, the area-weighted mean change (≤ 2 % per field), the dependent variables (1e-9 relative), the VIC rules the change touches, and that everything else is bitwise unchanged. All 11 checks passed (job 43542860); the root-zone verifier (6 checks, job 43542862) and the bundle verifier (7 checks, job 43542901) passed as well.</p>
<div class="wrap">{qc_fields}</div>

<h2 id="fields">4. The parameter fields compared</h2>
<p>Step <code>fields</code> of the analysis compares the two image-driver files directly. The global means barely move; the share of cells that change at all is 15 % for depth[2] (only the cells within 2 degrees of a depth edge) and 44–78 % for the baseflow parameters, whose blocks differ almost everywhere, by small amounts. West Siberia is the region of the largest depth contrast; the Alps have depth[2] = 2.5 m throughout, so only the baseflow parameters change there, and by less than 2 % of their means.</p>
<div class="wrap">{fields_tab}</div>
{img(f'{A}/figures/fields_depth_west_siberia_b.png', 'depth[2] West Siberia a, b, difference', 'Figure 3. depth[2] (m) in West Siberia: version-a, version-b and the difference b − a. The ramp across every former edge is 2 degrees wide and symmetric: cells on the deep side lose depth, cells on the shallow side gain it.')}
{img(f'{A}/figures/fields_Ds_west_siberia_b.png', 'Ds West Siberia', 'Figure 4. Ds (fraction of Dsmax where non-linear baseflow begins) in West Siberia. The mixed blocks on the coast show as slight asymmetries in the difference.')}
{img(f'{A}/figures/fields_Ds_alps_b.png', 'Ds Alps', 'Figure 5. Ds in the Alps: a patchwork of 2-degree values between 0.089 and 0.105 becomes a smooth field; the differences (right) are ±0.01 at most, with the block pattern still visible as the sign of the correction.')}

<h2 id="runs">5. The comparison runs</h2>
<p>Two non-production campaigns, <code>soil-comparison-version-a</code> and <code>soil-comparison-version-b</code> (<code>configs/campaigns/</code>), identical except for the parameter set, run the historical <code>histsoc</code> segment for 2011–2020 from a cold start with the settings of the production campaign: VIC-WUR production build <code>a826251b</code>, D19 dam files, non-renewable groundwater withdrawal, D03 output list, 16 ranks × 8 threads. Each run took about 10 h 20 min (about 1 h per model year) and wrote 212 GB. The run checks (water balance of every active cell and month, GRDC station comparison, water-use budgets) passed for both.{' The third campaign, <code>soil-comparison-version-c</code>, is described in part II; its run appears as the third column of the tables from here on.' if HAS_C else ''}</p>
<div class="caveat">The run checks were run twice. The first pair (jobs 43551799 and 43553342) passed with the same numbers but was recorded under <code>scratch/run-check/uncommitted/</code> because the analysis script was still uncommitted in the working tree when they started, which the check treats as "code not committed, result does not count" (rule 14). After committing the analysis task the checks were resubmitted (jobs 43569306 and 43569307); their records under <code>qc/runs/</code> are the ones used here.</div>
<div class="wrap">{wb_tab}</div>
<p>The water-balance statistics of version-a and version-b are identical to the printed precision: the largest residual (0.73 mm/month) is the same in both runs, in a cell the soil change did not touch, and no cell-month exceeds the 1 mm limit.</p>

<h2 id="global">6. Global and regional water balance</h2>
<p>The global monthly series of the two runs lie on top of each other (figure 6); the dashed line shows the difference b − a. Version-b holds slightly less water in layer 2 (−0.4 mm of 500 mm), produces slightly more baseflow (+1.6 mm/yr) and slightly less surface runoff (−2.0 mm/yr), so that total runoff falls by 0.4 mm/yr (−0.1 %) and evapotranspiration rises by 0.3 mm/yr (+0.06 %). The baseflow difference has a seasonal cycle (largest in the northern spring, +0.4 mm/month, near zero in autumn): the smoothed cells on the shallow side of a former edge now have a deeper layer 2 that stores the snowmelt and releases it as baseflow.</p>
<p>Why are the mean changes so small when the local changes are large? In the long-term mean, baseflow equals the drainage into the bottom layer minus the evaporation taken from it; the baseflow parameters only set how much storage is needed to transmit that drainage. Smoothing Ds, Dsmax, Ws and c therefore changes the storage and the timing of baseflow, not its mean, which is why the Alps (baseflow parameters changed, depth unchanged) show no change in the regional means to four digits. Only depth[2] changes the partition, through the storage capacity that governs evaporation and the drainage into layer 3, and that change cancels in the mean because every ramp is symmetric: the cells that lose depth and the cells that gain depth are about equally many.</p>
{img(f'{A}/figures/runs_global_series.png', 'global monthly series', 'Figure 6. Global area-weighted monthly means over the active cells, 2011–2020: layer-2 soil moisture, baseflow, surface runoff and the baseflow share of total runoff per set; the black lines are the differences to version-a on the right axis (dashed b − a' + (', dotted c − a' if HAS_C else '') + ').')}
<div class="wrap">{annual_tab}</div>
<div class="wrap">{region_tab}</div>

<h2 id="maps">7. Maps: where the runs differ</h2>
<p>The 2016–2020 means show the intended effect. In West Siberia the version-a layer-2 storage follows the depth edge as a staircase between 700 mm and 150 mm; in version-b the transition is a 2-degree ramp (figure 7). The difference map is a chain of paired bands: up to +300 mm on the former shallow side, up to −300 mm on the former deep side. Baseflow (figure 8) and the baseflow share (figure 9) change by up to ±30 mm/yr and ±0.07 along the same edges, and the block pattern that version-a imprinted on the baseflow share (figure 9, left: rectangles of 2 degrees) is gone. In the Alps (figure 10) the layer-2 storage changes by less than 0.01 mm and the baseflow by less than 0.1 mm/yr: with the depth unchanged, the smoothed baseflow parameters only redistribute the storage within the year.</p>
<p>Globally (figure 11) the differences of baseflow lie along the block edges of the northern plains (Canada, Siberia), the Andes, the Sahel, East Asia and Australia; between the edges the runs are identical to within rounding.</p>
{img(f'{A}/figures/runs_sm2_west_siberia_b.png', 'sm2 West Siberia', 'Figure 7. Layer-2 soil moisture (mm), mean 2016–2020, West Siberia: version-a, version-b, difference.')}
{img(f'{A}/figures/runs_baseflow_west_siberia_b.png', 'baseflow West Siberia', 'Figure 8. Baseflow (mm/yr), mean 2016–2020, West Siberia.')}
{img(f'{A}/figures/runs_baseflow_share_west_siberia_b.png', 'baseflow share West Siberia', 'Figure 9. Baseflow share of total runoff, mean 2016–2020, West Siberia. The 2-degree rectangles of version-a (left) come from the stepped baseflow parameters.')}
{img(f'{A}/figures/runs_sm2_alps_b.png', 'sm2 Alps', 'Figure 10. Layer-2 soil moisture (mm), mean 2016–2020, the Alps: with depth[2] unchanged the differences (right, note the scale of ±0.01 mm) are negligible.')}
{img(f'{A}/figures/runs_baseflow_global_b.png', 'baseflow global', 'Figure 11. Baseflow (mm/yr), mean 2016–2020, global: the differences follow the former block edges.')}
{img(f'{A}/figures/runs_baseflow_share_global_b.png', 'baseflow share global', 'Figure 12. Baseflow share of total runoff, mean 2016–2020, global.')}

<h2 id="grdc">8. Discharge at the GRDC stations</h2>
<p>The run checks compare the simulated monthly climatology of 2012–2020 (the cold-start year excluded) with the observed climatology of 2001–2024 at {g['a']['stations_with_climatology']} GRDC stations with catchments of at least 10 000 km² (the model is driven by GCM climate, so only the climatology is comparable). Both runs overestimate the mean discharge by a third at the median station; version-b is marginally closer at every summary measure, and the stations improve a little more often than they worsen. The change at any single station is small: at 90 % of the stations the simulated mean changes by between −2.1 % and +0.2 %. The largest changes (up to −20 %) are at prairie and boreal-plain stations in Canada, where version-a has the sharpest depth[2] contrasts, and most of them move towards the observations.</p>
<div class="wrap">{grdc_sum}</div>
<div class="wrap">{grdc_big_b}</div>
<div class="wrap">{grdc_large}</div>

<h2 id="wateruse">9. Water use</h2>
<p>Withdrawals follow the demand forcing and are nearly identical in version-a and version-b; the total irrigation withdrawal falls by 0.4 %, with a small shift between the sources: less from rivers (−2.3 %) and from renewable groundwater (−7 % of a small amount) and slightly more from the non-renewable groundwater, because VIC-WUR takes the renewable groundwater of a cell from its baseflow, which changed along the former block edges in irrigated plains (figure 11). The municipal and manufacturing withdrawals do not change.</p>
<div class="wrap">{wu_tab}</div>

<h2 id="conclusion">10. Conclusion and next steps</h2>
<p>The smoothing does what it was designed to do and nothing else: the five calibration fields keep their plateaus and global means, the 2-degree steps in the simulated layer-2 storage and baseflow disappear, the global water balance, evapotranspiration and total runoff are unchanged to within 0.1 %, the GRDC comparison is marginally better, and the water-use budgets are the same. No check or diagnostic favours version-a. Version-b is a candidate parameter set with every component QC passed and is ready for promotion.</p>
<ol>
<li>Promote the set from a clean repository: <code>submit_parameter_promotion.py --parameter-set vic-global-5arcmin-version-b --authorised "…" --accepted-restrictions "…"</code> (the restriction attributes of version-a are carried), then set <code>status: production</code> in the manifest.</li>
<li>Change the production campaign to the new set: in <code>configs/campaigns/water-global-ec-earth3-esm-1-1.yaml</code>, <code>parameter_set.id: vic-global-5arcmin-version-b</code> (status production). The spin-ups and the production runs are then made with version-b; runs made with version-a are not comparable cell by cell along the former block edges.</li>
<li>Record the decision in the task Z section of <code>workflow/03_parameters/README.md</code> (steps Z5–Z7) and close the analysis task (status closed, Conclusion in its README).</li>
<li>Housekeeping after the decision: fast-forward <code>task-z-soil-smoothing</code> into main; remove the task scratch (<code>scratch/soil-component</code> 486 MB, <code>scratch/vegetation-roots</code> 2.3 GB, <code>scratch/copy-components</code> 474 MB, <code>scratch/run-check/uncommitted</code>, the exploration jobs under <code>scratch/soil-smoothing/inspect</code>) and, once the comparison is no longer needed, the comparison runs (212 GB each).</li>
</ol>
{part2}
<h2 id="prov">{16 if HAS_C else 11}. Provenance</h2>
<div class="wrap">{prov_tab}</div>
</main></body></html>""")
with open(OUT, 'w') as fh:
    fh.write(''.join(H))
print(OUT, os.path.getsize(OUT) / 1e6, 'MB')
