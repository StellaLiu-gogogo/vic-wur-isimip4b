# Production configuration check

**Question.** Does the production configuration of D02 run as intended when its new parts run together for the first
time? On 2026-10-31 these parts had never run together:

- VIC-WUR `a826251b` (D01 amendment 2026-10-31: the corrected fresh-snow density of the land-use step), production
  build `builds/vic/a826251b…/`;
- the production parameter set `parameters/production/vic-global-5arcmin-version-a/` (promoted 2026-10-30), with the
  D19 dam files (`dams_isimip4b`) and the FILE decomposition built for them;
- non-renewable withdrawal on, without a limit, with the monthly output `OUT_NONREN_DEFICIT`;
- the D03 daily outputs of the historical segments (`OUT_SOIL_MOIST`, `OUT_EVAP`, `OUT_WITHDRAWN`);
- the resources `configs/resources/vic-global-5arcmin.yaml`: 16 ranks × 8 threads, 500G, whole node.

Sub-questions: does the run check pass; are the non-renewable withdrawal and the deficit plausible; do the dams
operate; does the water balance close; how fast is the run and how much memory does it use at 16 × 8, and what does
that mean for `wall_time.hours_per_model_year` of the resources file (3.0 h)?

**Classification.** Analysis (user, 2026-10-31): the product is a comparison and a conclusion on whether the
production campaign can start. No workflow stage reads it.

**Status.** open.

**Run.** Campaign `production-config-check` (`configs/campaigns/production-config-check.yaml`, non-production): the
settings of the production campaign `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`, restricted to the
historical `histsoc` segment of `h_ssp3hsoc-noadapt_default`, 2015-2016, cold start, with the resources of the
resources file. Run `runs/production-config-check/ec-earth3-esm-1-1_historical_histsoc_default_historical__check-2015-2016`.
Differences to the production campaign: one experiment, the restriction, no spin-up and no run order, and the monthly
inflow, demand and release of the dams (`OUT_GDAM_*`, `OUT_LDAM_*`) added to the diagnostics for the dam check
(user, 2026-10-31).

- Cold start: no completed run of the production build exists whose end state the D19 warm-start rule accepts (same
  model commit and executable). The dams register 2015 as their first year of history and operate in 2016, so 2016
  is the year that is judged.
- D20: `histsoc` is not a constant unit; 2015 is an identity link in every forcing family.

**Inputs** (paths relative to the workdir):

- the run above and its run check `qc/runs/production-config-check/<run-id>/`;
- `runs/snow-density-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016`: the same VIC code
  (test commit `a6868324`, the same Git tree as `a826251b`), segment, years, cold start, dam files, decomposition and
  ranks, with non-renewable withdrawal off; its check `qc/runs/snow-density-test/<run-id>/reports/check.json`;
- `runs/dam-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016`: speed and memory at
  16 × 8 on a whole node (10.08 s per model day, 804 s to start, MaxRSS 35.8 GB per rank);
- `qc/runs/smoke-nonrenewable/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2011-2020/reports/check.json`:
  the earlier run with non-renewable withdrawal (VIC `39e21ff5`, old dam file, warm start that D19 now rejects).

**Reference values** (km3 per year, from the run checks):

| 2016 | Irrigation withdrawal | Non-renewable | Total withdrawal |
|---|---|---|---|
| snow-density-test `ranks16` (non-renewable off, D19 dam files) | 1 680 | 0 | 2 870 |
| smoke-nonrenewable (warm start, old dam file) | 2 842 | 1 822 | 4 387 |
| smoke-nonrenewable, range 2011-2020 | 2 638-3 075 | 1 612-2 101 | 4 033-4 695 |

Expected for 2016: irrigation about 2 600-2 900 and non-renewable about 1 600-1 900 km3/yr, possibly lower because the
D19 dam files reduced irrigation by about 8 % in campaign dam-test and the run starts cold. Values outside 1 300-2 400
(non-renewable) or 2 300-3 300 (irrigation) are investigated before the production campaign starts (user,
2026-10-31).

**Method.**

1. The run check of the workflow (`workflow/05_simulation/monitor/check_run.py`, submitted by `submit_run.py`) must
   pass: coverage, water balance, water-use budget, sectors, monthly non-renewable deficit, GRDC, end state.
2. Comparison with the `ranks16` run of snow-density-test (`workflow/05_simulation/monitor/compare_runs.py --submit`,
   absolute paths): values may differ only in cells with water use and downstream of them. The runs write different
   output variables, so the report status is `failed` by the rule of the tool; the per-variable differences are read.
3. Script of this task (each step a Slurm job, job records in `workdir/analysis/production-config-check/logs/`):
   non-renewable withdrawal by sector and region, the deficit at the end of each month and how much of it is repaid
   (non-renewable withdrawal minus the increase of the deficit), the global budget with the non-renewable term; the
   dams (global reservoir storage, withdrawal from dams, inflow, storage and release of the key dams against the
   `ranks16` run of snow-density-test); the cells that differ from that run against the cells with water use; the
   number of cell-months with a monthly mean |`OUT_WATER_ERROR`| above 1 mm (mask rule of
   `analysis/snow-sublimation-outliers/`).
4. Speed and memory from the run manifest (VIC timing table, `sacct` MaxRSS and AveRSS) against dam-test `ranks16`,
   and the hours per model year they imply.

**Outputs.** `workdir/analysis/production-config-check/` (tables, figures, job records).

**Conclusion.** Not yet available.

**Finding before the run (2026-10-31).** The first render of the campaign stopped in `render_run.py`
(`check_unit_parameters`, and `check_landuse_tiles` after it): `promote_parameter_set.py` copies the provenance record
of the assembled bundle unchanged, so in the production set its `object` is still the candidate path, and the
renderer did not accept it as the record of the production copy. Every campaign on the production parameter set,
the production campaign included, stopped there. The renderer now also accepts a record whose `object` is the same
file of the candidate set that `promotion.yaml` lists as copied (`render_run.parameter_provenance`, test
`ParameterProvenanceTest`).
