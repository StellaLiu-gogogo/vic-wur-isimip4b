# Dam parameter test (task L5)

**Question.** Do the ISIMIP4b dam files of D19 (`dams_isimip4b`) and the FILE decomposition built for them
(`decomposition_isimip4b`) run as intended in VIC-WUR `39e21ff5`?

- Do 8 and 16 ranks give the same result?
- Do the dams receive, store and release water plausibly, in particular Ust-Ilim and Brokopondo, which received
  almost no inflow with the old dam file (`analysis/dam-nservice-test/`)?
- How does the discharge at the GRDC stations change against the smoke run with the old dam file?
- How fast are 8 × 16 and 16 × 8, and how much memory do they need? The answer decides the ranks and threads of
  `configs/resources/vic-global-5arcmin.yaml`.

**Classification.** Analysis (user, 2026-10-30): the product is a comparison used for a decision on the resource
file. No workflow stage reads it.

**Status.** open

**Inputs** (paths relative to the workdir):

- Test runs of campaign `dam-test` (`configs/campaigns/dam-test.yaml`), both covering 2015-2016 with a cold start
  in 2015 and the `histsoc` dam file:
  - `runs/dam-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks8-2015-2016`: 8 ranks ×
    16 threads, 450G, job 43522174;
  - `runs/dam-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016`: 16 ranks ×
    8 threads, 500G, job 43522179;
  - `runs/dam-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks8-threads8-shared-2015-2016`:
    8 ranks × 8 threads, 450G, on a shared node, job 43530364. Added on 2026-10-30 (user) because `ranks8` and
    `ranks16` differ from 2016 on; it shows whether the difference comes from the number of ranks or of threads.
    The first submission (`ranks8-threads8-2015-2016`, job 43529716, a whole node) waited in the queue and was
    cancelled before it started (user, 2026-10-31); this run only compares values, so it shares a node.
- Reference: `runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2011-2020`. This run has
  the old dam file `vic_global_5min_dam_parameters_t3-extended-merged.nc` and the old decomposition, with a cold
  start in 2011.
- Dam list and natural mean discharge of the dam file:
  `parameters/candidates/vic-global-5arcmin-version-a/dams/` (`dam_list_isimip4b.csv`,
  `mean_discharge_natural.nc`).
- GRDC stations of the run check (`qc/runs/dam-test/<run-id>/reports/grdc_stations.csv`) and the GRDC daily
  export (`raw/external/grdc/export-2024-11`).

**Method.**

- The runs are compared with each other by the workflow tool `workflow/05_simulation/monitor/compare_runs.py`
  (every variable of the daily and monthly output of 2015 and 2016 and of the end state; report
  `qc/runs/dam-test/<run A>/reports/compare_<run B>.json`, job records under `logs/05_simulation/`).
- `dam_parameter_test.py`, every step as a Slurm job:
  - `dams`: covers the global dams active in 2016 in run `ranks16`.
    - Inflow, demand and release in 2016 at the dam cell (monthly `OUT_GDAM_*`).
    - After a cold start a dam only records its inflow for one year and starts to operate in the first month of
      its operational year, so in 2016 the dams start in different months. The inflow per operating day is
      compared with the natural mean discharge 1992-2021 of the dam file, times the inflow fraction.
    - Storage at the end of 2016 (`STATE_DAM_STORAGE` of the end state) against capacity.
    - Local dams in total.
    - Ust-Ilim, Bratsk, Brokopondo, Three Gorges, Kariba and Akosombo month by month, with the storage of the
      largest old global dam within 5 cells in the smoke run.
  - `grdc`: compares 2016 at the GRDC stations of the run check. It takes the simulated monthly discharge of run
    `ranks16` and of the smoke run, and compares each against the GRDC climatology 2005-2024 (ratio of the means,
    correlation of the 12 months). It also lists the first two stations on the downstream path of each key dam.

- Diagnoses of the rank dependence and of its correction, each run once as a Slurm job (`python3 <script>` with
  `ISIMIP4B_WORKDIR` set, 2 CPUs; the job script is `job.sbatch` in the job record; output in the record's
  `slurm-<job>.out`):
  - `diag_day1_cells.py` (job 43531574): runoff difference on 2016-01-01 between `ranks8` and `ranks16`, by change of
    the land-use cover. The job stopped with an error after this part (it read a monthly file that does not exist);
    the snow part was redone by `diag_snow_link.py`.
  - `diag_snow_link.py` (job 43531575): the differing cells against snow in December 2015 and snowfall on its last
    day.
  - `diag_effect.py` (job 43532147): size of the effect in 2016, corrected against original `ranks8` and original
    `ranks8` against `ranks16`.

**Caveat.** Both runs use the same climate (EC-Earth3-ESM-1-1 historical), but the smoke run started cold in 2011
and the test runs in 2015. In 2016 the soil and snow stores of the test runs have had one year to develop instead
of five, and most of their dams operate only from some month of 2016 on (the dams of the smoke run operate from
2012 on). A difference at a station in 2016 therefore comes mostly from the start, not from the dam file.

**Outputs.** `workdir/analysis/dam-parameter-test/`:

- `tables/`: `dams_global_2016.csv`, `key_dams.csv`, `key_dams_monthly.csv`,
  `grdc_2016.csv`, `grdc_key_dams.csv`, `<step>_summary.json`;
- `figures/`: `key_dams.png`, `grdc_ratio_2016.png`, `grdc_key_dams.png`;
- `logs/<step>_<slurm-job-id>/`: job records; `logs/dams_43528699/` is the first `dams` job, which used the whole
  year for the inflow ratio and was replaced by `logs/dams_43529450/`.

**Speed and memory of the test runs.** Taken from the VIC timing table in `logs/vic_stdout_<job>.txt` and from
`sacct` (step `.1`). Wall time is per model day.

| Run | Run time (s/day) | Force (s/day) | Write (s/day) | Init (s) | MaxRSS per rank | AveRSS × ranks |
|---|---|---|---|---|---|---|
| smoke 2011-2020, 8 × 16, old decomposition (job 43023368) | 11.80 | 2.04 | 2.40 | 1178 | 72.5 GB | about 394 GB |
| `ranks8`, 8 × 16, new decomposition | 11.88 | 1.79 | 2.67 | 1050 | 60.2 GB | about 395 GB |
| `ranks16`, 16 × 8, new decomposition | 10.08 | 1.40 | 2.85 | 804 | 35.8 GB | about 396 GB |
| `ranks8-threads8-shared`, 8 × 8, shared node (timing not comparable) | 17.42 | 1.69 | 7.04 | 984 | 60.3 GB | about 395 GB |

The test runs write more than the smoke run (monthly `OUT_GDAM_*`/`OUT_LDAM_*` inflow, demand and release).

- No rank of either test run reported a dam service cell or a water-use receiving cell that was not found.
- The remote water-use summary reports zero events.

**Ranks and threads.** `compare_runs.py`, reports `qc/runs/dam-test/<ranks8 run>/reports/compare_<other run>.json`:

- `ranks8` (8 × 16) and `ranks16` (16 × 8): 2015 bitwise identical; from 2016-01-01 on they differ (day 1: runoff
  in 7 829 of 2 188 551 active cells, discharge in 10 076 cells; about 2-3 % of the cell-months by the end of 2016;
  monthly discharge up to 2.07 m3/s, daily up to 66 m3/s, snow depth up to 183 mm), and so does the end state.
- `ranks8` (8 × 16) and `ranks8-threads8-shared` (8 × 8): bitwise identical in all 160 compared variables (daily and
  monthly output of 2015 and 2016, end state).
- The result therefore depends on the number of ranks (which groups of cells share a rank), not on the number of
  threads. Memory per rank does not depend on the threads either.

**Cause of the rank dependence (2026-10-31).** VIC-WUR `39e21ff5`, `plugins/landuse/src/lu_support.c`,
`calculate_derived_water_states` (called by `lu_apply` at every year start, serial over the cells of a rank):

```c
snow[iVeg][iBand].density = new_snow_density(
    force->air_temp[NR] + soil_con->Tfactor[iBand]);
```

`force` and `soil_con` are the arrays of all cells of the rank, so `force->` and `soil_con->` are the air temperature
and band temperature offset of the first cell of the rank, not of cell `iCell` (`force[iCell]`, `soil_con[iCell]`).
The line runs for a tile with snow that fell on the last step of the year (`last_snow == 0`) or has no density. The
first cell of a rank depends on the number of ranks, not on the threads (`lu_apply` is serial), which matches all
comparisons; at the cold start of 2015 there is no snow, so 2015 is identical.

Evidence on 2016-01-01, `ranks8` against `ranks16` (`diag_day1_cells.py`, `diag_snow_link.py`, job records
`logs/diag-day1-cells_43531574/`, `logs/diag-snow-link_43531575/`; renamed on 2026-10-31 from `diag-day1_cells_…` and
`diag-snow_link_…` to follow the job-record naming rule):

- `OUT_RUNOFF` differs in 7 829 of 2 188 551 cells, `OUT_BASEFLOW` in none. The differences are small (median
  relative difference 8e-7, largest 0.15 mm).
- All 7 829 cells had snow in December 2015 (`OUT_SWE`): 6 977 of 552 407 cells with snow and snowfall on 31 December
  2015 (precipitation > 0 and air temperature below 0.5 °C in the forcing), 852 of 547 933 cells with snow and no
  snowfall by this rough criterion, and 0 of 1 088 211 cells without snow.

The defect affects every run of this VIC version at every year start, whatever the layout, and makes the result
depend on the number of ranks.

**Test of the correction (user, 2026-10-31).** `vic-lu-snow-density.patch` (this directory) is the VIC-WUR test
commit `a686832448d4db64870fa96450992b7b5d9a9b92` on 39e21ff5, branch `lu-snow-density-cell` of a local clone (not
pushed): it uses `force[iCell]` and `soil_con[iCell]` in the line above and changes nothing else. Its test build
(`workflow/05_simulation/build/build_vic.sh --test-commit`, `builds/vic/a6868324…/`) runs in campaign
`snow-density-test` (`configs/campaigns/snow-density-test.yaml`): the runs `ranks8` and `ranks16` of `dam-test`
again, on shared nodes (jobs 43531702 and 43531704, run checks passed). Expected: the two runs are bitwise
identical; the comparison of the corrected `ranks8` run with the `ranks8` run of `dam-test` shows the effect of the
defect. Results (2026-10-31):

- Corrected `ranks8` against corrected `ranks16` (`compare_runs.py`, report
  `qc/runs/snow-density-test/<ranks8 run>/reports/compare_<ranks16 run>.json`): bitwise identical in all compared
  variables (daily and monthly output of 2015 and 2016, end state), status `passed`. The correction removes the rank
  dependence.
- Corrected `ranks8` against the `ranks8` run of `dam-test` (report
  `qc/runs/snow-density-test/<ranks8 run>/reports/compare_<ranks8 run>.json`; both runs have the same run ID):
  2015 identical, 2016 and the end state differ (status
  `warning`; the Slurm job 43532002 ends with exit code 3, the code of `warning`).
- Size of the effect in 2016 (`diag_effect.py`, job record `logs/diag-effect_43532147/`), with original `ranks8`
  against original `ranks16` (both with the defect) for scale:

| 2016 | Corrected − original (`ranks8`) | Original `ranks8` − `ranks16` |
|---|---|---|
| Cells with a different annual runoff + baseflow (of 2 188 551) | 551 489 | 413 719 |
| … by more than 1 mm / 5 mm / 20 mm | 140 / 15 / 2 (largest 25.5 mm) | 28 / 4 / 0 (largest 7.8 mm) |
| … by more than 1 % of the annual value | 129 | 12 |
| Cells with a different annual evapotranspiration by more than 1 mm | 187 (largest 17.9 mm) | 42 (largest 7.3 mm) |
| Global annual runoff + baseflow, global evapotranspiration | −0.0001 %, +0.0001 % | 0.0000 %, 0.0000 % |
| Cells with a monthly SWE difference above 10 mm | 7 | 2 |
| Cells with 2016 mean discharge > 10 m3/s (389 257): annual mean changed by more than 0.1 % / 1 % | 71 / 0 (largest 0.36 %) | 16 / 0 (largest 0.20 %) |
| … some month changed by more than 1 % / 5 % | 406 / 135 | 97 / 44 |

The defect changes the snow density at the year start in snow cells. The effect is small in global and annual
terms. It is a few millimetres to a few tens of millimetres in a few hundred cells, and it reaches some months of
discharge downstream of them. This run covers one year start (2016); a long run passes one year start per year.

**Speed of the corrected runs** (shared nodes, no other heavy job seen): `ranks8` 11.87 s/day run, init 1082 s,
MaxRSS 60.3 GB per rank; `ranks16` 10.07 s/day, init 740 s, MaxRSS 35.8 GB per rank, the same as the runs of
`dam-test` within 1 %. The correction does not change speed or memory.

**Conclusion (user, 2026-10-31).**

- The correction is the new frozen model version (D01 amendment 2026-10-31). The user, who develops the branch,
  pushed it to `fix-restart-luapply-snow-state` of `https://github.com/wur-wsg/VIC` as commit
  `a826251b6a9b831f432ebd7b655f2b456388c5e4`: the test commit `a6868324` with a new commit message, the same Git tree
  (`45eaa7d7be64e3b94b90541cbf81d7df2a6944aa`), so the results above hold for it.
- Earlier runs with `39e21ff5` are not rerun: the effect is small.
- `configs/resources/vic-global-5arcmin.yaml` uses 16 ranks × 8 threads with 500G (user, 2026-10-31; before: 8 × 16
  with 700G): 15 % faster than 8 × 16 per model day, and the measured memory fits.
