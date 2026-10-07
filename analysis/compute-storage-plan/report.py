"""Write workdir/analysis/compute-storage-plan/report.md from the results of plan.py (called by plan.py)."""
import csv, datetime as dt, os

import csp

GB, TB = 1e9, 1e12


def md(rows, cols, heads=None):
    """Markdown table of dict rows; cols = [(key, format or None)]."""
    heads = heads or [c for c, _ in cols]
    out = ['| ' + ' | '.join(heads) + ' |', '|' + '|'.join('---' for _ in cols) + '|']
    for r in rows:
        cells = []
        for k, f in cols:
            v = r.get(k, '')
            if f and v not in ('', None):
                try:
                    v = format(float(v), f)
                except ValueError:
                    pass
            cells.append(str(v))
        out.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(out)


def rcsv(name):
    p = f'{csp.tables()}/{name}'
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []


def drift_section(w):
    """Evidence of the 10-year smoke run (cold start) from spinup_drift.py, when its tables exist."""
    da = rcsv('drift_annual.csv')
    if not da:
        return
    by = {}
    for r in da:
        by.setdefault(r['store'], []).append(r)
    yrs = [int(r['year']) for r in by['reservoirs']]
    res = [float(r['december_km3']) for r in by['reservoirs']]
    ch = [float(r['december_change_km3']) for r in by['reservoirs'][1:]]
    last = {s: v[-1] for s, v in by.items()}
    sn = rcsv('drift_snow_regions.csv')
    w(f'**Evidence from the 10-year smoke run** (`spinup_drift.py`; run `…__smoke2011-2020`, cold start from the '
      f'initial state of the parameter file, historical climate and `histsoc`, water use on; '
      f'`tables/drift_annual.csv`, figure `figures/spinup_drift.png`). The climate changes from year to year, so '
      f'this run cannot show convergence at the 0.1 % level that the H line measured with a repeated decade. It '
      f'does show the first years after a cold start:')
    w('')
    w(f'- *Reservoirs.* The December total fell from {res[0]:,.0f} km³ ({yrs[0]}) by '
      + ', '.join(f'{c:+.0f}' for c in ch[:4]) +
      f' km³ in the next four years, then varied by ±{max(abs(c) for c in ch[4:]):.0f} km³ a year. The '
      f'relaxation from the initial storage of the parameter file takes about 4–5 years, longer than in the H line '
      f'(about 2 years from a storage seeded at 0.85 × capacity), and well inside a 50-year spin-up.')
    w(f'- *River storage and soil layers 2 and 3.* They change most in the first year (river '
      f'{float(by["river"][1]["december_change_km3"]):+.0f} km³; layer 2 '
      f'{float(by["soil layer 2"][1]["december_change_km3"]):+.0f} km³; layer 3 '
      f'{float(by["soil layer 3"][1]["december_change_km3"]):+.0f} km³). After that, the year-to-year change per '
      f'cell stays at the level of weather: area-weighted mean |change| of the December value '
      f'{min(float(r["mean_abs_cell_change_pct_of_depth"]) for r in by["soil layer 2"][2:]):.1f}–'
      f'{max(float(r["mean_abs_cell_change_pct_of_depth"]) for r in by["soil layer 2"][2:]):.1f} % of the '
      f'layer-2 depth.')
    w(f'- *Steady drying of layer 2.* {100 * float(last["soil layer 2"]["same_direction_share"]):.1f} % of the '
      f'area lost layer-2 water in every year from 2012 to 2020, together '
      f'{float(last["soil layer 2"]["same_direction_km3_per_year"]):.1f} km³ per year. That is '
      f'{100 * abs(float(last["soil layer 2"]["same_direction_km3_per_year"])) / float(last["soil layer 2"]["december_km3"]):.3f} % '
      f'of the global layer-2 store per year, the same order as the drift of the H-line production run '
      f'(−1.9 % in 41 years, ≈ 0.05 % per year) after its 40-year spin-up. Whether it is slow relaxation, '
      f'the DHF trend (more irrigation) or the warming of 2011–2020 cannot be separated here; the picontrol '
      f'spin-up with fixed DHF will separate it.')
    if sn:
        tot = sum(float(r['km3_per_year']) for r in sn)
        area = sum(float(r['area_km2']) for r in sn)
        top = ', '.join(f'{r["lat_south"]}°…{int(r["lat_south"]) + 10}° / {r["lon_west"]}°…{int(r["lon_west"]) + 10}° '
                        f'({float(r["km3_per_year"]):.0f} km³/yr)' for r in sn[:5])
        w(f'- *Snow that never melts.* Snow rose in every year on {100 * float(last["snow"]["rising_share"]):.2f} % '
          f'of the area ({area:,.0f} km²), by {tot:.0f} km³ per year in total, mostly in glacier regions '
          f'(10° boxes: {top}). The largest December 2020 SWE there is '
          f'{max(float(r["max_december_2020_swe_mm"]) for r in sn) / 1000:.0f} m. VIC has no glacier model and '
          f'no cap on snow, so this store grows without limit. At the present rate it would reach '
          f'≈ {tot * 550 / 1000:.0f}k km³ over the {50 + 500}-year chain (all soil layer 2 holds ≈ '
          f'{float(last["soil layer 2"]["december_km3"]) / 1000:.0f}k km³), and the water is missing from runoff '
          f'in those cells. This does not change the compute or storage numbers, but it affects the reported `swe` '
          f'and `tws` and every snow-based convergence test. How to treat it (cap the SWE and pass the excess to '
          f'runoff, mask the cells, or accept it) is a model decision for the user and is not settled here.')
    w('')
    w('![Spin-up drift](figures/spinup_drift.png)')
    w('')
    w('*Figure 3. Left: global December totals of each store, minus December 2020. Right: area-weighted mean '
      '|December change| per cell from the previous year, in % of the mean depth of the store.*')
    w('')


def write(T, sp, var_est, cf, results, sub, seg_tables, a, eur_node_h):
    L = []
    w = L.append
    py = T['runs']
    h = sp['hours_per_year']; init = sp['init_hours']; swh = sp['state_write_hours']
    dem = {(r['subset'], r['gcms']): r for r in T['demand']}
    sc = {r['scenario']: r for r in T['scenarios']}
    cl = T['cluster']
    opt = {r['option']: r for r in T['options']}
    samples = rcsv('compression_samples.csv')
    full = rcsv('compression_fullfile.csv')
    spin = {(r['spinup_years'], r['subset']): r for r in T['spin']}
    nodes = {(r['scenario'], int(r['nodes'])): r for r in T['nodes']}
    rec = 'S4'

    w('# Compute and storage plan for the ISIMIP4b water_global campaigns on Anunna')
    w('')
    w(f'Analysis task `compute-storage-plan` (evidence for decisions D02 and D03). Generated by '
      f'`analysis/compute-storage-plan/plan.py` on {dt.date.today()} from the run records of the smoke campaign, '
      f'the measurement tables of `measure_files.py`, the forcing on disk and the pinned protocol '
      f'(`f9be7b0`). Re-run `submit.py --step plan` when the smoke run 2011–2020 has finished: every number below '
      f'is recomputed. Planning parameters of this version: spin-up {a.spinup_years} years per spin-up segment, '
      f'{a.nodes} gen3 nodes used continuously, assumed production start {a.start}, queue wait '
      f'{a.queue_wait_hours:g} h per job, second GCM released {a.second_gcm_offset_days:g} days after the first.')
    w('')

    # ------------------------------------------------------------------ summary
    r1, r2 = dem[('all-18', 1)], dem[('all-18', 2)]
    w('## Summary')
    w('')
    w(f'- **Speed.** One model year takes **{h:.2f} h** on one 128-core gen3 node (8 ranks × 16 threads), '
      f'**{h * 128:.0f} core-hours**, measured on {sp["basis"].split("smoke runs ")[-1]}. Every job adds '
      f'{init * 60:.0f} min of initialisation and {swh * 60:.0f} min for writing the end state. The '
      f'"233 core-hours per model year" of the one-year smoke run is these three parts together; a long '
      f'segment costs {h * 128:.0f} core-hours per year.')
    w(f'- **Output per model year.** daily {sp["daily_bytes"] / GB:.2f} GB (only `qtot` and `dis`, 3 VIC fields), '
      f'monthly {sp["monthly_bytes"] / GB:.2f} GB, end state {sp["state_bytes"] / GB:.2f} GB per job.')
    w(f'- **Demand.** All 18 experiments of one GCM are {r1["segments"]} segments and {r1["model_years"]} model '
      f'years ({r1["spinup_years"]} of them spin-up). That is {r1["core_hours"] / 1e3:.0f}k core-hours '
      f'(≈ €{r1["eur"] / 1e3:.1f}k at the Anunna tariff) and {r1["output_5min_tb"]:.1f} TB of 5′ output, plus '
      f'{r1["climate_forcing_tb"]:.1f} TB of climate forcing. Two GCMs need twice this: '
      f'{r2["core_hours"] / 1e3:.0f}k core-hours, {r2["output_5min_tb"]:.1f} TB of output and '
      f'{r2["climate_forcing_tb"]:.1f} TB of forcing.')
    w(f'- **Time.** The longest chain is spin-up → pre-industrial → historical → future. It is {a.spinup_years + 500} model '
      f'years, about **{r1["critical_path_days"]:.0f} days** of wall-clock time. With {a.nodes} nodes, the '
      f'two-GCM scenarios finish in '
      f'{min(sc[k]["wall_days"] for k in ("S1", "S2", "S4")):.0f}–{max(sc[k]["wall_days"] for k in ("S1", "S2", "S4")):.0f} days, '
      f'including the {a.second_gcm_offset_days:g}-day later start of the second GCM. '
      f'Compute time is not the constraint before the AR7 date (May 2027).')
    w(f'- **Storage is the constraint.** /lustre had {a.free_tb:.0f} TB free on {a.free_date}, for all users. '
      f'Keeping all 5′ output of all 18 experiments for two GCMs, with daily `soilmoist`, `tsl`, `snd`, `snm` '
      f'and `lai` (scenario S1), peaks at {sc["S1"]["peak_tb"]:.0f} TB, which does not fit. Deleting the '
      f'5′ daily files once their 0.5° products have passed QC keeps the peak at about '
      f'{sc[rec]["peak_tb"]:.0f} TB ({rec}).')
    w(f'- **Lossless compression saves little.** zlib levels 4–9 make the files only a few percent smaller '
      f'than VIC\'s level 2, and writing takes longer. Lossy rounding to 3–4 significant digits saves much more '
      f'(section 2b), but VIC cannot apply it when it writes the files; it would be a separate step after the run.')
    w(f'- **Recommendation.** For D02, scenario {rec}: all experiments except the two `extrasoc` ones (D06 open), '
      f'for both GCMs, with EC-Earth3-ESM-1-1 first and the 1st-priority segments first, on {a.nodes} nodes, '
      f'{a.spinup_years}-year spin-ups. For D03: each run keeps its states, its 5′ monthly output and its run '
      f'records; its 5′ daily output is deleted once the 0.5° products made from it have passed QC; daily '
      f'output stays limited to the variables the protocol requires daily.')
    w('')

    # ------------------------------------------------------------------ part 1
    w('## 1. Demand')
    w('')
    w('### 1.1 Segments of the 18 water_global experiments (one GCM)')
    w('')
    w('Resolved by `workflow/05_simulation/render/resolve_campaign.py` from `definitions/experiments/ISIMIP4b.yaml` '
      'and `period.yaml` of protocol commit `f9be7b0`. The resolver starts from `configs/campaigns/smoke.yaml` with '
      'the experiment selection replaced; `2021co2` is mapped to `default` (VIC-WUR has no CO₂ response, D12). '
      'Segments shared by several experiments are counted once.')
    w('')
    w(md(seg_tables['all-18'], [('segment_id', None), ('start_year', None), ('end_year', None), ('years', None),
                                ('parent', None), ('n_experiments', None)],
         ['segment', 'first', 'last', 'years', 'parent', 'experiments']))
    w('')
    w('Totals per selection (one GCM; the segment lists are `tables/segments_<selection>.csv`):')
    w('')
    w(md([dem[(k, 1)] for k in sub], [('subset', None), ('experiments', None), ('segments', None),
                                      ('model_years', None), ('spinup_years', None), ('reported_years', None)],
         ['selection', 'experiments', 'segments', 'model years', 'spin-up years', 'reported years']))
    w('')
    w('"Group I and II only" leaves out the six experiments whose future DHF is an SSP scenario '
      '(`ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`, including the two `extrasoc` ones). The protocol has no group field; '
      'the group follows from the future DHF, as in `docs/glossary.md`.')
    w('')

    w('### 1.2 Spin-up')
    w('')
    w('**What the protocol requires** (`protocol/02.experiments.md`, ISIMIP4b):')
    w('')
    w('- The spin-up uses pre-industrial control climate, CO₂ fixed at 1850 and DHF fixed at 1850 levels, '
      '"for the spin up as long as needed". The protocol sets no number of years.')
    w('- "The pre-industrial control run from 1601–1849 is part of the regular experiments that should be '
      'reported and hence the spin-up has to be finished before that."')
    w('- `2021soc` experiments are spun up with 2021 DHF and link directly to 1850: they have no pre-industrial '
      'period. This is the second spin-up segment.')
    w('- picontrol climate starts in 1601 (DKRZ files `…_esm-picontrol_…_1601_1610.nc` onward). The spin-up '
      f'therefore cycles picontrol years; this plan assumes the window {1601}–{1650}, which is inside the '
      'pre-industrial forcing and needs no extra forcing years.')
    w('')
    w('**What VIC-WUR needs to reach equilibrium.** The stores with memory longer than a year are:')
    w('')
    w('- soil moisture, mainly the middle and bottom layers. Under `GWM FALSE` the bottom layer is also the '
      '"groundwater" from which the water-use plugin abstracts;')
    w('- snow in cells where it does not melt every year (high mountains; Greenland is outside the `nogl` domain);')
    w('- reservoir storage of the dams;')
    w('- soil temperature at the deep nodes.')
    w('')
    w('There is no separate groundwater store, no lake and no glacier store under the current configuration '
      '(`LAKES FALSE`, `GWM FALSE`).')
    w('')
    w('**Evidence from the sibling project (H line, Snellius, same 5′ domain and plugins, VIC `e083c9f3`).** '
      'Documents: `vic_global/vic_parameter/docs/HumanImpact_Hline_spinup执行与收敛_20260902.md`, '
      '`HumanImpact_生产41年验收_20260906.md`, `Natural_双轨spinup结果_v2_20260901.md`.')
    w('')
    w('- *Schedule.* Cold start; three 10-year cycles of 1979–1988 meteorology with the plugins off; then a '
      '10-year transition with real meteorology and dams on. That is 40 years in total.')
    w('- *Soil moisture.* Area-weighted |Δ| between the end states of consecutive cycles:')
    w('  - Layer 2 is the slowest: 1.40 mm (0.30 % of the column) after cycle 2 and 0.61 mm (0.14 %) after '
      'cycle 3. That is a decay ratio of 0.44 per 10-year cycle, an e-folding time of about 12 years.')
    w('  - Layers 1 and 3 were at 0.004–0.014 % after the first cycle.')
    w('  - The slowest basins were the Ob–Kara Sea basin and the Mississippi mouth (≈ 0.1 %, drying steadily).')
    w('- *Dams.* The storage-to-capacity ratio relaxed from 0.75 to 0.69 in about two years and then stayed flat. '
      'Over the last five years the trend divided by the year-to-year standard deviation was 0.14, which the '
      'project read as zero.')
    w('- *Production check.* In the 41-year production run that followed, every store had a trend smaller '
      'than 0.10 year-to-year standard deviations (layer 2 −0.09, layer 3 −0.02, December SWE 0.01, dam storage '
      '−0.03).')
    w('')
    w('**Recommended spin-up length.** The spin-up length is a parameter (`--spinup-years`). The recommended '
      f'value is **{a.spinup_years} years** per spin-up segment, followed by a convergence test before the '
      'pre-industrial segment starts. The reasons:')
    w('')
    w('- *Soil layer 2.* The H-line change per decade was 0.30 % of the column after the second decade and '
      '0.14 % after the third, a decay ratio of 0.44. Continuing that decay, the change in the fifth decade is '
      'about 0.03 % of the column, or 0.003 % per year. That is well inside the "trend below 0.1 year-to-year '
      'standard deviation" that the 41-year production run met. Reaching 0.01 % per decade would take about '
      '60 years.')
    w('- *Dams.* They need about 2 years from a seeded state, and 10 years of DAMS operation was judged '
      'sufficient.')
    w('- *Water use.* Unlike the H line, the ISIMIP spin-up runs with water use on, which takes water from the '
      'bottom layer. 50 years gives this abstraction-driven drawdown a margin that the H line did not test.')
    w('- *Test.* The convergence test is the H-line test on the last two decades: decay ratio and relative '
      'change per layer, SWE p99, dam storage trend divided by standard deviation. Cells where snow builds up '
      'every year are left out of the test (see the 10-year run below): no spin-up length brings them to '
      'equilibrium.')
    w('- *If it fails.* Extend the spin-up in 10-year steps from its end state.')
    w('')
    w('The cost of other lengths is in option d. Warm-starting the `2021soc` spin-up from the end state of the '
      '`1850soc` spin-up would shorten it further, at the price of making it wait for the first spin-up. '
      'This is not used in the numbers.')
    w('')
    drift_section(w)

    w('### 1.3 Cost of one model year')
    w('')
    w(md(T['years'], [('run', None), ('year', None), ('start_utc', None), ('hours', '.3f'), ('core_hours', '.0f'),
                      ('overlap_with_measurement', '.2f'), ('daily_gb', '.2f'), ('monthly_gb', '.2f')],
         ['run', 'model year', 'started (UTC)', 'wall h', 'core-h', 'share during measurement jobs', 'daily GB',
          'monthly GB']))
    w('')
    hs = [y['hours'] for y in T['years']]
    if max(hs) > 1.15 * min(hs):
        q = sp['hours_per_year_quiet']
        yrs = T['years']
        idx = [k for k, y in enumerate(yrs) if float(y['overlap_with_measurement']) > 0.05]
        before = [y['hours'] for y in yrs[:idx[0]] if y['run'] == 'smoke2011-2020'] if idx else []
        after = [y['hours'] for y in yrs[idx[-1] + 1:]] if idx else []
        w(f'**The speed varies.** Model years took {min(hs):.2f}–{max(hs):.2f} h. The slowest years ran while this '
          f'task\'s compression tests (`measure_files.py`, column "share during measurement jobs") read and wrote '
          f'tens of GB on the same /lustre. The years without the tests took {q:.2f} h on average '
          f'({sp["quiet_years"]} years).')
        if before and after:
            w(f'In the 10-year run the years before the tests took {sum(before) / len(before):.2f} h and the years '
              f'after them {sum(after) / len(after):.2f} h: the run did not keep slowing down, so there is no sign '
              f'of a slowdown that grows with the length of a run. The slightly slower years after the tests point '
              f'to other load on the filesystem, which production runs will also meet.')
        vt = {r['run']: r for r in T['runs']}
        lines = []
        for k, r in vt.items():
            try:
                run, force, wr = float(r['vic_run_s']), float(r['vic_force_s']), float(r['vic_write_s'])
            except (TypeError, ValueError):
                continue
            n = int(r['complete_years'])
            lines.append(f'{k}: reading forcing {force / run * 100:.0f} %, writing output {wr / run * 100:.0f} % of '
                         f'the VIC run time ({force / n / 60:.0f} and {wr / n / 60:.0f} min per model year)')
        if lines:
            w('VIC timing tables: ' + '; '.join(lines) + '. The extra time of the slow years is mostly reading and '
              'writing files, so the speed depends on how busy /lustre is. '
              'The plan uses the mean of all years (the slow years included), and the ×1.3 slow case covers the '
              'slowest year measured.')
        w('')
    w(md(py, [('run', None), ('status', None), ('node', None), ('init_h', '.2f'), ('state_write_h', '.2f'),
              ('complete_years', None), ('maxrss_gb_per_rank', '.1f'), ('vic_run_s', None), ('vic_force_s', None),
              ('vic_write_s', None)],
         ['run', 'status', 'node', 'init h', 'state write h', 'years done', 'MaxRSS GB/rank', 'VIC Run s',
          'Force s', 'Write s']))
    w('')
    w('How the times are measured:')
    w('')
    w('- *Year.* A model year is the time between the last writes of consecutive monthly files. The first '
      'year starts at the creation of its daily file, which marks the end of initialisation.')
    w('- *State write.* The time from the creation to the last write of the end-state file.')
    w('- *smoke2015.* Its VIC "Run Time" (5 233 s) is 1.0 h of model year plus the state write.')
    w('- *Planning value.* {:.3f} h per model year ({:.0f} core-hours). A slow case of {:.2f} h (×1.3) is '
      'carried for several runs sharing the filesystem; this factor is not measured.'.format(
          h, h * 128, sp['hours_per_year_slow']))
    w('')
    w(f'Billing on Anunna is by requested resources: 128 cores × €0.0150 plus {a.mem_gb:.0f} GB × €0.0011 '
      f'= **€{eur_node_h:.2f} per node-hour** (std QoS). MaxRSS was {sp["maxrss_gb_per_rank"]:.0f} GB per rank '
      f'in ' + ' and '.join(f'{x["run"]} ({x["complete_years"]} model year{"s" if int(x["complete_years"]) > 1 else ""}, '
                                  f'{x["maxrss_gb_per_rank"]} GB)' for x in py
                            if x['maxrss_gb_per_rank'] != '') + ': memory does not grow with the length of a run. '
      f'That is ≈ {sp["maxrss_gb_per_rank"] * 8:.0f} GB per node, so a request of about 700 GB instead of {a.mem_gb:.0f} GB '
      f'would cut the cost per node-hour by about {(a.mem_gb - 700) * 0.0011 / eur_node_h * 100:.0f} %.')
    w('')
    ov = rcsv('output_by_variable.csv')
    if ov:
        w('**Output per variable and time step** (allocated bytes in the smoke 2015 files, '
          '`tables/output_by_variable.csv`):')
        w('')
        w(md(ov, [('stream', None), ('variable', None), ('shape', None), ('bytes_per_year', ',.0f'),
                  ('share_of_stream', '.3f')], ['stream', 'VIC variable', 'shape', 'bytes per model year', 'share']))
        w('')
        dc = rcsv('daily_cost_by_variable.csv')
        w('**Cost of each variable if written daily.** These are bytes per model year. Variables that are not '
          'in the daily file are estimated from their monthly size; the method is in the "basis" column, '
          '`tables/daily_cost_by_variable.csv`:')
        w('')
        w(md(dc, [('variable', None), ('monthly_bytes_per_year', ',.0f'), ('daily_bytes_per_year', ',.0f'),
                  ('daily_basis', None)], ['VIC variable', 'monthly bytes/yr', 'daily bytes/yr', 'basis']))
        w('')

    w('### 1.4 Totals per GCM and for two GCMs')
    w('')
    w(f'Output, states and core-hours at the planning speed with the current output configuration (daily `qtot` '
      f'and `dis`, all monthly variables, zlib level 2). Climate forcing is {T["forcing"]["climate_gb_per_year"]:.2f} '
      f'GB per forcing year (7 variables, measured on `forcing/climate/ec-earth3-esm-1-1/esm-hist`, 2011–2020); '
      f'one GCM needs picontrol 1601–2100, historical 1850–2021, vl and h 2022–2100. Land-use and water-use '
      f'forcing (measured on disk) serve both GCMs.')
    w('')
    w(md(T['demand'], [('subset', None), ('gcms', None), ('model_years', None), ('jobs', None),
                       ('core_hours', ',.0f'), ('eur', ',.0f'), ('output_5min_tb', '.1f'), ('daily_tb', '.1f'),
                       ('monthly_tb', '.1f'), ('state_tb', '.2f'), ('climate_forcing_tb', '.1f'),
                       ('dhf_forcing_tb', '.3f'), ('critical_path_days', '.1f')],
         ['selection', 'GCMs', 'model years', 'jobs', 'core-h', '€', "5′ output TB", 'daily TB', 'monthly TB',
          'states TB', 'climate forcing TB', 'land-use + water-use TB', 'critical path days']))
    w('')
    raw = T['forcing']['raw']
    w('Raw ISIMIP climate input on disk (0.5°, per alias): ' +
      ', '.join(f'{k} {v:.0f} GB' for k, v in raw.items()) + '. Forcing units on disk: ' +
      ', '.join(f'{f} {sum(d.values()):.1f} GB' for f, d in T['forcing']['dhf'].items()) + '.')
    w('')

    w('### 1.5 Critical path, parallel chains and the cluster')
    w('')
    w(f'- **Critical path.** spin-up `picontrol/1850soc` ({a.spinup_years} y) → pre-industrial (249 y) → a '
      f'historical segment (172 y) → a future segment (79 y): {a.spinup_years + 500} model years ≈ '
      f'{(a.spinup_years + 500) * h / 24 + 4 * (init + swh) / 24:.1f} days at the measured speed. The '
      f'`2021soc` chain (spin-up → historical → future) is {a.spinup_years + 251} years and runs beside it.')
    w('- **Width.** After the pre-industrial segment, up to 4 historical segments can run at once, plus 2 on the '
      '`2021soc` spin-up, then up to 15 future segments per GCM. More than about 6 nodes per GCM shortens '
      'nothing: the pre-industrial segment is a single chain.')
    w('- **Splitting.** One job holds at most {:d} model years ({:d} h planned against the 21-day limit), so no '
      'segment needs chunks at the measured speed. `configs/resources/vic-global-5arcmin.yaml` still plans '
      '3.0 h per model year and `max_hours: 240`; with those values every historical and pre-industrial '
      'segment would be split. The values should be updated from this measurement before production (a '
      'configuration change, not made here).'.format(int((480 - init - swh) // h), 480))
    w('')
    gs = cl.get('gen3_states', {})
    w(f'**Anunna main partition** (sinfo/scontrol at {cl.get("time")}):')
    w('')
    w(f'- {cl.get("gen3_1tb_nodes")} gen3 nodes with 1 TB (state: ' +
      ', '.join(f'{k} {v}' for k, v in sorted(gs.items())) +
      f'), {cl.get("total_nodes")} nodes in the partition, wall-time limit {cl.get("max_time")}.')
    w('- QoS `std` (priority 10; `high` costs 30 % more; `low` is limited to 8 h per job).')
    w('- No per-user limit on cores or jobs is configured (sacctmgr). The QoS group limit is 40 000 cores.')
    fsh = cl.get('fairshare', {})
    w(f'- Fair share of user {fsh.get("user")} in account `{fsh.get("account")}`: FairShare '
      f'{fsh.get("fairshare")}, normalised share {fsh.get("norm_shares")}, effective usage '
      f'{fsh.get("effective_usage")}. Jobs start late when the cluster is busy. The wait cannot be measured in '
      f'advance; the plan adds `--queue-wait-hours` per job as a sensitivity.')
    w('- The wiki\'s fair-use page is a draft. Its only rule of thumb is "Keep reservations to at most three '
      'nodes"; whether that applies to normal jobs is an open question for the admins (section 4).')
    w('- From 1 January 2027, internal WUR use is funded from the Generic Research budget and is no longer '
      'charged to projects (wiki, Policies and Terms of Use).')
    w('')
    w('Finishing day by node count (days after the start, and date if production starts on '
      f'{a.start}):')
    w('')
    w(md(T['nodes'], [('scenario', None), ('nodes', None), ('wall_days', '.1f'), ('finish', None),
                      ('peak_tb', '.1f')], ['scenario', 'nodes', 'days', 'finish', 'peak storage TB']))
    w('')
    w('**ISIMIP timeline.** The ISIMIP4b start e-mail (2026-08-28, legacy audit evidence) says the data were '
      'released early "in the face of the AR7 submission deadline expected in May 2027". The protocol and the '
      'website give no delivery date for model output. Analyses for AR7 papers need the data well before May 2027, '
      'so the useful delivery date is earlier and has to be asked from the coordinators. The earliest '
      'finishing dates above assume the production start date; that date depends on D01 (frozen model), the '
      'production parameter set, the picontrol forcing, and the 1601 DHF years.')
    w('')

    # ------------------------------------------------------------------ part 2
    w('## 2. Options to reduce demand')
    w('')
    w('All options are applied one at a time to the reference: all 18 experiments, two GCMs, protocol-daily '
      f'output, zlib 2, everything kept, full climate forcing, {a.nodes} nodes (`tables/options.csv`).')
    w('')
    w(md(T['options'], [('option', None), ('description', None), ('core_hours', ',.0f'),
                        ('postrun_core_hours', ',.0f'),
                        ('hours_per_model_year', '.3f'), ('output_5min_tb', '.1f'), ('daily_tb', '.1f'),
                        ('monthly_tb', '.1f'), ('state_tb', '.2f'), ('climate_forcing_tb', '.1f'),
                        ('peak_tb', '.1f'), ('final_tb', '.1f'), ('wall_days', '.1f')],
         ['option', 'what', 'core-h', 'of which post-run core-h', 'h per model year', "5′ output TB", 'daily TB', 'monthly TB', 'states TB',
          'climate forcing TB', 'peak TB', 'end TB', 'days']))
    w('')
    w('### a. Daily output')
    w('')
    w('The protocol variables of `water_global` by time step (`definitions/variable/*.yaml`):')
    w('')
    w('- **daily & monthly (required):** `qtot`, `dis`. Written now as `OUT_RUNOFF`, `OUT_BASEFLOW` and '
      '`OUT_DISCHARGE`; there is no total-runoff output in VIC, so `qtot` needs two fields.')
    w('- **"daily if possible, else monthly":** `soilmoist`, `tsl`, `snd`, `snm`.')
    w('- **"daily else monthly":** `lai`. With `LAI_SRC FROM_VEGPARAM`, LAI is a monthly climatology.')
    w('- **all other variables:** monthly, annual or fixed.')
    w('')
    if var_est:
        e = var_est['est']
        extra = sum(e[v]['daily_bytes_per_year'] for v in ('OUT_SOIL_MOIST', 'OUT_SOIL_TEMP', 'OUT_SNOW_DEPTH',
                                                            'OUT_SNOW_MELT', 'OUT_LAI') if v in e)
        w(f'The "if possible" set would add about {extra / GB:.1f} GB per model year to the '
          f'{sp["daily_bytes"] / GB:.1f} GB of the required set. This is an estimate: a monthly time step of each '
          f'variable is scaled by the daily/monthly ratio of the variables in both files ({var_est["k"]:.2f}). '
          f'Most of it is the three soil-moisture and three soil-temperature layers. '
          f'**Recommendation:** daily output limited to `qtot` and `dis`. The protocol allows monthly for the '
          f'"if possible" variables, and `lai` has no daily information in this configuration.')
        w('')
    w('### b. Compression, precision, chunking')
    w('')
    if samples:
        w('Tests on copies in `scratch/compute-storage-plan/`. Each setting writes the same sample: 62 days '
          '(January and July) of the daily file, and January and July of the monthly file, all variables. Sizes '
          'and times are scaled to one model year. Writing and reading are single-threaded netCDF4-python on one '
          'compute node, on /lustre; read times may include the client cache. `tables/compression_samples.csv` '
          'has the full table.')
        w('')
        base = {s['file']: s for s in samples if s['variant'] == 'zlib2-shuffle (VIC)'}
        for s in samples:
            s['vs_vic'] = int(s['bytes_per_year']) / int(base[s['file']]['bytes_per_year'])
        w(md(samples, [('file', None), ('variant', None), ('bytes_per_year', ',.0f'), ('vs_vic', '.3f'),
                       ('write_s_per_year', '.0f'), ('read_s_per_year', '.0f')],
             ['file', 'setting', 'bytes per model year', 'size vs VIC now', 'write s / model year',
              'read s / model year']))
        w('')
        g = {(s['file'], s['variant']): s for s in samples}

        def f(k, v, key='vs_vic'):
            return float(g[(k, v)][key]) if (k, v) in g else float('nan')
        w(f'- *Lossless zlib levels.* Level 1 = level 2 within 0.5 %. Level 4 saves '
          f'{(1 - f("daily", "zlib4-shuffle")) * 100:.0f} % (daily) and '
          f'{(1 - f("monthly", "zlib4-shuffle")) * 100:.0f} % (monthly) but writes '
          f'{f("daily", "zlib4-shuffle", "write_s_per_year") / f("daily", "zlib2-shuffle (VIC)", "write_s_per_year"):.1f}× '
          f'slower. Level 9 saves {(1 - f("daily", "zlib9-shuffle")) * 100:.0f} % at '
          f'{f("daily", "zlib9-shuffle", "write_s_per_year") / f("daily", "zlib2-shuffle (VIC)", "write_s_per_year"):.0f}× '
          f'the write time. The values are float32 numbers whose last bits look random, and zlib cannot compress '
          f'those. The ocean and fill cells already compress to almost nothing.')
        w(f'- *Shuffle* (on in VIC) saves {(f("daily", "zlib2-noshuffle") - 1) * 100:.0f} % against no shuffle. '
          f'*float64* would cost {(f("daily", "zlib2-shuffle-f64") - 1) * 100:.0f} % more (daily). '
          f'*Chunk shape* changes the size by less than 1 %.')
        w(f'- *Rounding to significant digits* (GranularBitRound, then zlib 4): 4 digits → '
          f'{f("daily", "zlib4-shuffle-gbr4"):.2f} (daily) and {f("monthly", "zlib4-shuffle-gbr4"):.2f} '
          f'(monthly) of the present size; 3 digits → {f("daily", "zlib4-shuffle-gbr3"):.2f} and '
          f'{f("monthly", "zlib4-shuffle-gbr3"):.2f}. The errors are in the next table.')
        w(f'- *zstd level 3* writes {f("daily", "zlib2-shuffle (VIC)", "write_s_per_year") / f("daily", "zstd3-shuffle", "write_s_per_year"):.0f}× '
          f'faster than zlib 2 and reads {f("daily", "zlib2-shuffle (VIC)", "read_s_per_year") / f("daily", "zstd3-shuffle", "read_s_per_year"):.0f}× '
          f'faster, but the files are {(f("daily", "zstd3-shuffle") - 1) * 100:.0f} % larger.')
        w('')
    lossy = rcsv('compression_lossy.csv')
    if lossy:
        w('Errors of the rounding settings, per variable on the same samples (`tables/compression_lossy.csv`). '
          'Relative errors are given for values ≥ 1e-3 (mm, or m³ s⁻¹ for discharge). Smaller values can be '
          'rounded to zero; the last column gives the share of non-zero values for which that happens:')
        w('')
        w(md(lossy, [('file', None), ('variant', None), ('variable', None), ('max_rel_error_above_1e3', '.1e'),
                     ('p999_rel_error', '.1e'), ('max_abs_error', '.3g'), ('nonzero_to_zero_share', '.1e')],
             ['file', 'setting', 'variable', 'max rel. error (|x| ≥ 1e-3)', '99.9th pct rel. error',
              'max abs. error', 'non-zero → 0']))
        w('')
    if full:
        w('Whole files rewritten with `nccopy` (post-run step; `tables/compression_fullfile.csv`):')
        w('')
        w(md(full, [('file', None), ('variant', None), ('bytes', ',.0f'), ('seconds', None), ('read_s', None)],
             ['file', 'setting', 'bytes', 'nccopy s', 'read s']))
        w('')
        w(f'The end state is float64 and must stay lossless: a restart has to continue the run exactly. VIC '
          f'wrote it in {swh * 60:.0f} min at `STATE_COMPRESS 2`. The fill and ocean cells compress to almost '
          f'nothing, so most of that time is VIC collecting the fields on one rank, not compression. The state '
          f'rows of the table show what other levels would give; a state is written once per job, so this '
          f'is a fixed {swh:.2f} h per job and not a cost per model year.')
        w('')
    w('**What VIC can be told at write time (`39e21ff5`):**')
    w('')
    w('- `COMPRESS <0-9>` per output stream; zlib with shuffle always on (`vic_init_output.c`, '
      '`nc_def_var_deflate(..., true, true, level)`).')
    w('- `STATE_COMPRESS <0-9>` for the state file.')
    w('- The data type per variable in the `OUTVAR` line: `OUT_TYPE_FLOAT` (the default here), `OUT_TYPE_DOUBLE`, '
      'or `OUT_TYPE_SINT`/`OUT_TYPE_INT` with a multiplier. A scaled 16-bit integer is lossy and needs a '
      'fixed range, which does not suit `dis`.')
    w('- VIC sets no chunking (netCDF default: one time step, a quarter of the grid), no rounding of '
      'significant digits and no other compressor.')
    w('')
    w('Rounding to N significant digits (netCDF "granular bit round"), other chunk shapes and zstd therefore '
      'need a step after the run that rewrites the files. That step reads and writes every byte once, and zstd '
      'files need the HDF5 zstd plugin in every reader. VIC already writes float32. float64 would cost '
      'the "f64" row.')
    w('')
    w('Compression level also costs run time: VIC gathers each output field on one rank and compresses it '
      'there, so the extra write seconds per model year in the table add directly to the wall time of every run.')
    w('')
    w('### c. Lifecycle of the 5′ output')
    w('')
    w('What a run must keep so that it stays reproducible and auditable:')
    w('')
    w('- `config/`, `logs/` and `run_manifest.json` (inputs, checksums, attempts);')
    w('- every end state in `states/`. Each is the parent of later segments and is the backed-up part of a '
      'production run in the current contract ("Data protection");')
    w('- the 5′ monthly output. It is small and serves checks and re-aggregation (D07 may change).')
    w('')
    w('The 5′ daily output (`qtot`, `dis`) is about 2/3 of all output. Once the 0.5° daily products made from it '
      'have passed QC, it can be regenerated from the parent state, the configuration and the build at '
      f'{h:.1f} h per model year. Under this rule, storage over time is in figure 1. Option c in the table '
      'shows the peak and the end state for "delete daily" and for "delete daily and monthly".')
    w('')
    w('### d. Spin-up length')
    w('')
    w(md(T['spin'], [('spinup_years', None), ('subset', None), ('spinup_model_years_per_gcm', None),
                     ('core_hours_per_gcm', ',.0f'), ('spinup_share', '.3f'), ('critical_path_days', '.1f')],
         ['spin-up years', 'selection', 'spin-up model years per GCM', 'core-h per GCM', 'share of core-h',
          'critical path days']))
    w('')
    w('The protocol requires "as long as needed": a criterion, not a number. Each extra 50 years cost '
      f'{2 * 50 * h * 128 / 1e3:.0f}k core-hours per GCM (two spin-up segments) and add '
      f'{50 * h / 24:.1f} days to the critical path. Spin-up output beyond the end state is not reported. A '
      'spin-up stream of a few annual fields for the convergence test would cost a few GB.')
    w('')
    w('### e. Climate forcing')
    w('')
    prod = T['forcing']['producer']
    if prod:
        p = prod[0]
        w(f'Producer speed (`logs/04_forcing/{p["job"]}`): {p["years"]} forcing years × 7 variables took '
          f'{p["producer_h"]:.2f} h plus {p["verifier_h"]:.2f} h of verification on {p["cpus"]} cores. That is '
          f'{p["wall_h_per_year"]:.2f} wall-hours and {p["core_h_per_year"]:.1f} core-hours per forcing year. '
          f'picontrol 1601–2100 (500 years, {500 * T["forcing"]["climate_gb_per_year"] / 1e3:.1f} TB) costs '
          f'{500 * p["core_h_per_year"]:.0f} core-hours, about {500 * p["core_h_per_year"] / (h * 128):.0f} '
          f'model years\' worth. In decade jobs of {p["cpus"]} cores it takes {p["wall_h_per_year"] * 10:.1f} h per '
          f'decade, so 10 jobs at once produce it in about {50 / 10 * p["wall_h_per_year"] * 10:.0f} h.')
        w('')
    w('picontrol is used by the spin-up window, the pre-industrial segment (1601–1849), the three picontrol '
      'historical segments (1850–2021) and five picontrol futures (2022–2100). The years 1601–1849 are no longer '
      'needed after the pre-industrial segment, and 1850–2021 after the picontrol historical segments. '
      f'"Rolling" forcing produces each block before its first use and removes it after its last; option e '
      f'gives the peak ({opt.get("e: rolling climate forcing", {}).get("peak_tb", "")} TB against '
      f'{opt.get("reference", {}).get("peak_tb", "")} TB). Regenerating a block costs little compute (above). '
      'The run manifests keep the sha256 of every forcing file a run read, so a regenerated block can be checked '
      'bit by bit against the original.')
    w('')
    w('The forcing-unit contract does not allow this today. A unit (`climate/<gcm>/<alias>/<variable>/`) is '
      'accepted as a whole and may only be *extended* with years. Removing years, or a period level, would need a '
      'contract change (section 3), and deleting an accepted unit needs the user\'s authorisation each time.')
    w('')
    w('### f. Compute')
    w('')
    w('- *Ranks.* The FILE decomposition has 128 groups, and the largest (372 255 cells) sets the pace from '
      'about 6 ranks upward. More ranks per run gain nothing, so parallelism is across runs, one node each.')
    w(f'- *Memory and nodes.* A run needs about {sp["maxrss_gb_per_rank"] * 8:.0f} GB (8 × '
      f'{sp["maxrss_gb_per_rank"]:.0f} GB MaxRSS), so only the {cl.get("gen3_1tb_nodes")} gen3 1 TB nodes '
      'qualify. The gen4 nodes (192 cores, 2.3 TB) would need a build for their library tree.')
    w(f'- *Filesystem.* A run reads {T["forcing"]["climate_gb_per_year"]:.0f} GB of forcing and writes '
      f'{(sp["daily_bytes"] + sp["monthly_bytes"]) / GB:.0f} GB per model year, ≈ '
      f'{(T["forcing"]["climate_gb_per_year"] + (sp["daily_bytes"] + sp["monthly_bytes"]) / GB) / h / 3.6:.0f} MB/s. '
      f'16 runs are ≈ 0.1 GB/s against 15 GB/s nominal for /lustre. Bandwidth does not limit the number of runs. '
      f'Shared load can still slow every run (the ×1.3 slow case), and the free space limits the output.')
    w('- *Scheduling.* Fair share and node availability limit how many runs start at once. The admins\' answer on '
      'how many nodes may be used continuously is the missing number (section 4).')
    w('')

    # ------------------------------------------------------------------ part 3
    w('## 3. Scenarios and recommendation')
    w('')
    w(md(T['scenarios'], [('scenario', None), ('title', None), ('experiments', None), ('gcms', None),
                          ('model_years', None), ('core_hours', ',.0f'), ('eur', ',.0f'), ('wall_days', '.1f'),
                          ('finish', None), ('wall_days_slow', '.1f'), ('finish_slow', None), ('peak_tb', '.1f'),
                          ('final_tb', '.1f'), ('final_5min_tb', '.1f'), ('final_states_tb', '.2f'),
                          ('final_forcing_tb', '.1f'), ('weeks_before_ar7', '.0f')],
         ['', 'scenario', 'exp.', 'GCMs', 'model years', 'core-h', '€', 'days', 'finish', 'days (slow)',
          'finish (slow)', 'peak TB', 'end TB', "end 5′ TB", 'end states TB', 'end forcing TB',
          'weeks before May 2027']))
    w('')
    w('![Storage over time](figures/storage_over_time.png)')
    w('')
    w('*Figure 1. Project storage over time per scenario: climate forcing, states, 5′ monthly and daily output, '
      '0.5° products. The dashed line is the free space of /lustre on 2026-10-05, shared by all users.*')
    w('')
    w('![Critical path](figures/critical_path_gantt.png)')
    w('')
    w(f'*Figure 2. Jobs per scenario on {a.nodes} nodes. Colour = period; outlined = the chain that ends last.*')
    w('')
    w('**Risk to the deadline.**')
    w('')
    w('- None of the scenarios is limited by compute time: even the largest finishes months before May 2027 on '
      f'{a.nodes} nodes.')
    w(f'- S1 does not fit in the free space ({sc["S1"]["peak_tb"]:.0f} TB against {a.free_tb:.0f} TB shared).')
    w('- The real risks to the timeline lie elsewhere:')
    w('  - D01, the production parameter set and the picontrol forcing must be ready before the start;')
    w('  - 06_postprocessing (D07, D09, D10) must exist before any 5′ daily file can be deleted. Without it, '
      'every scenario behaves like "keep" for storage;')
    w('  - queue waits under a low fair share;')
    w('  - for UKESM1-3-LL: the transfer of its inputs (batch 5) and its forcing production.')
    w('')
    w(f'**Recommendation for D02: scenario {rec}.**')
    w('')
    w('- *Scope.* All experiments except the two `extrasoc` ones (their DHF is open, D06), for both GCMs. '
      f'{sc[rec]["core_hours"] / 1e3:.0f}k core-hours (≈ €{sc[rec]["eur"] / 1e3:.1f}k), '
      f'{sc[rec]["wall_days"]:.0f} days on {a.nodes} nodes (slow case {sc[rec]["wall_days_slow"]:.0f} days).')
    w('- *Order.* EC-Earth3-ESM-1-1 first, and within it the segments of 1st-priority experiments first.')
    w('- *Why include the 2nd-priority segments.* They are `1850soc` historical and future segments that branch '
      'from the shared pre-industrial state. They add model years but not wall-clock time, because they run '
      'beside the 1st-priority segments.')
    w('- *extrasoc.* When D06 is decided, the two segments start from the kept end state of the historical '
      '`histsoc` segment (2 × 79 years per GCM).')
    w('- *If the admins limit the project to 3 nodes,* the same scope finishes in '
      f'{nodes.get((rec, 3), {}).get("wall_days", "?")} days.')
    w('')
    w('**Recommendation for D03 (storage rule).**')
    w('')
    w('- *Daily output.* Limited to the protocol-daily variables (`qtot`, `dis`).')
    w('- *What a run keeps.* Configuration, logs, run manifest, every end state, and the 5′ monthly output.')
    w('- *Deleting the 5′ daily output.* This is a workflow step, not a manual one. It happens after the 0.5° '
      'products derived from the file have `qc.status: passed`, and the run manifest records the deleted files '
      'with size and sha256.')
    w('- *Peak storage.* With this rule the peak is about '
      f'{sc[rec]["peak_tb"]:.0f} TB, of which {dem[("all-but-extrasoc", 2)]["climate_forcing_tb"]:.0f} TB is climate forcing '
      f'(two GCMs), and {sc[rec]["final_tb"]:.0f} TB remain at the end.')
    w(f'- *Rolling climate forcing.* Not part of {rec}. It would lower the peak by about '
      f'{opt["reference"]["peak_tb"] - opt["e: rolling climate forcing"]["peak_tb"]:.0f} TB (option e) but needs '
      f'the forcing-contract change below. Decide it separately, if space becomes short.')
    w('- *Lossy rounding.* Not recommended for archived 5′ files. A run directory should hold what VIC wrote.')
    w('')
    w('**Sentences D03 would change** (current wording, and the proposed change in plain words):')
    w('')
    w('1. `AGENTS.md`, "Runs, quality control, and delivery":')
    w('   - Current: "The run must preserve the resolved configuration, exact VIC configuration, exact Slurm job, '
      'logs, states, raw output, and run manifest."')
    w('   - Proposed: "raw output" becomes "the 5′ monthly output", and a sentence is added that the 5′ daily output '
      'is kept until the 0.5° products made from it have passed QC and is then deleted by the workflow.')
    w('2. `docs/directory-contracts.md`, `runs/`: the layout lists `output/` without a lifecycle. Add a rule '
      'for which files of `output/` (and of `chunks/*/output/`) may be deleted, when, by which workflow step, and '
      'what the run manifest records.')
    w('3. `docs/directory-contracts.md`, "Deletion permissions":')
    w('   - Current: the table allows a workflow producer to delete only "the one cache it is about to rebuild".')
    w('   - Proposed: add a row that lets the postprocessing workflow delete 5′ daily output files of a production '
      'run once their products have passed QC, without a separate authorisation each time; the D03 record is '
      'the authorisation.')
    w('4. `docs/directory-contracts.md`, "Data protection":')
    w('   - Current: "Raw model output is reproducible from the backed-up configuration, states, build, and '
      'parameters".')
    w('   - Proposed: no change needed; it already treats output as reproducible. Add that the 5′ monthly '
      'output stays in the workdir only.')
    w('5. `workflow/05_simulation/README.md`:')
    w('   - Current, under Outputs: "logs, state files, and raw output in dedicated subdirectories".')
    w('   - Proposed: adapt it and the completion criteria in the same way.')
    w('6. `workflow/06_postprocessing/README.md`: "In-place modification of raw model output" stays forbidden. '
      'Deletion after QC becomes an allowed step.')
    w('7. If rolling climate forcing is adopted (option e): `docs/directory-contracts.md`, `forcing/`.')
    w('   - Current: "A forcing unit is regenerated only as a whole … Data files in a unit are never edited in '
      'place", and units may only be extended.')
    w('   - Proposed: a rule to remove years from a unit (recorded in `provenance.yaml`), and the matching line in '
      '`docs/glossary.md` ("Forcing unit").')
    w('8. `docs/decisions/open-decisions.md`: D03 row and context, plus a decision record `D03-…md`.')
    w('')

    # ------------------------------------------------------------------ part 4
    w('## 4. Open questions')
    w('')
    w('Not settled by the cluster documentation (wiki pages Using_Slurm, Scheduling, Tariffs, Policies_and_Terms_of_Use, '
      'Fair_Use_Policy read on 2026-10-05; `scontrol`, `sacctmgr`, `sshare`):')
    w('')
    w('1. **Nodes.** How many gen3 nodes may the project use continuously for 4–8 weeks? The fair-use page is a '
      'draft that says "Keep reservations to at most three nodes". Is that a limit on normal jobs, or only on '
      'reservations? Would a reservation of N nodes be granted for the campaign?')
    w('2. **Queue waits.** What waits should be expected with the current fair share (esg account usage above '
      'its share)? Can the project get a share or a commitment for the campaign period?')
    w('3. **Cost.** Is the 950 GB memory request billed in full? Billing is "on requested resources and claimed '
      'duration". Who pays the 2026 part? From 2027 use is not charged to projects.')
    w('4. **Storage.** Is there a quota or an allocation for 30–60 TB on `/lustre/nobackup` for several '
      'months? The filesystem is 97 % full and shared. What is the price? The tariff page says €100 per TB per '
      'year; is it billed on usage?')
    w('5. **Long jobs.** Are 15–20 day jobs on `main` acceptable, or are maintenance windows expected that would '
      'kill them? (This matters for splitting the 249-year pre-industrial segment.)')
    w('6. **ISIMIP.** What is the delivery deadline for Fast Track output, before the AR7 date? Is the second GCM '
      'needed in the first delivery? Are `2021co2` experiments reported (D12)? What is the `extrasoc` content '
      '(D06)? Are the potential-irrigation runs needed (D17)? If D17 adds `POTENTIAL_IRRIGATION TRUE` runs for '
      'the historical and future segments, demand rises by up to the number of affected segments × their '
      'years.')
    w('')
    w('## 5. Assumptions not settled by records')
    w('')
    w(f'- Start of production on {a.start}, and the second GCM {a.second_gcm_offset_days:g} days later.')
    w(f'- 0.5° products are {100 * 0.05:.0f} % of the 5′ output they come from (1/36 of the cells, more files).')
    w('- Products pass QC 3 days after the end of their run.')
    w('- Slow case ×1.3 per model year.')
    w('- No queue waits in the main numbers.')
    w('- Spin-up climate window 1601–1650.')
    w('- One job at most 480 h.')
    w('- UKESM1-3-LL has the same cost per year as EC-Earth3-ESM-1-1.')
    w('')
    path = f'{csp.products()}/report.md'
    with open(path, 'w') as fh:
        fh.write('\n'.join(L) + '\n')
    print(f'wrote {path}')
