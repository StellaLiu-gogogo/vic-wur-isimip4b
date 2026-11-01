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

**Status.** done (2026-11-01). The proposal for `wall_time.hours_per_model_year` is with the user.

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
- This run replaces the rerun of campaign smoke-nonrenewable with the D19 dam files that the user asked for on
  2026-10-09 (user, 2026-11-01).

**Inputs** (paths relative to the workdir):

- the run above and its run check `qc/runs/production-config-check/<run-id>/`;
- `runs/snow-density-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016`: the same VIC code
  (test commit `a6868324`, the same Git tree as `a826251b`), segment, years, cold start, dam files, decomposition and
  ranks, with non-renewable withdrawal off; its check `qc/runs/snow-density-test/<run-id>/reports/check.json`;
- `runs/dam-test/ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016`: speed and memory at
  16 × 8 on a whole node (10.08 s per model day, 804 s to start, MaxRSS 35.8 GB per rank);
- `qc/runs/smoke-nonrenewable/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2011-2020/reports/check.json`:
  the earlier run with non-renewable withdrawal (VIC `39e21ff5`, old dam file, warm start that D19 now rejects);
- `raw/ISIMIP4b/InputData/geo_conditions/countrymasks/countrymasks-fractional_5arcmin.nc`: the ISIMIP country
  masks, for the non-renewable withdrawal by country.

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
3. Script of this task, `production_config_check.py` with the steps `nonrenewable`, `balance`, `dams`, `cells` and
   `timing` (each step a Slurm job, `--submit`, job records in `workdir/analysis/production-config-check/logs/`):
   non-renewable withdrawal by sector and region, the deficit at the end of each month and how much of it is repaid
   (non-renewable withdrawal minus the increase of the deficit), the global budget with the non-renewable term; the
   dams (global reservoir storage, withdrawal from dams, inflow, storage and release of the key dams against the
   `ranks16` run of snow-density-test); the cells that differ from that run against the cells with water use, and for
   each differing cell outside them (discharge downstream of them excepted) its reason (it gives water to other
   cells, it had water use in 2015, it is a dam cell or downstream of one); the
   number of cell-months with a monthly mean |`OUT_WATER_ERROR`| above 1 mm (mask rule of
   `analysis/snow-sublimation-outliers/`).
4. Speed and memory from the run manifest (VIC timing table, `sacct` MaxRSS and AveRSS) against dam-test `ranks16`,
   and the hours per model year they imply.

**Outputs.** `workdir/analysis/production-config-check/`:

- `tables/`: `nonrenewable_monthly.csv`, `nonrenewable_countries_2016.csv`, `balance_annual.csv`,
  `dams_global_monthly.csv`, `key_dams_monthly.csv`, `cells_2016.csv`, `timing.csv`, `<step>_summary.json`;
- `figures/`: `nonrenewable_monthly.png`, `dams_global.png`, `key_dams.png`;
- `logs/<step>_<slurm-job-id>/`: job records.

The comparison report of step 2 is
`workdir/qc/runs/production-config-check/<run-id>/reports/compare_ec-earth3-esm-1-1_historical_histsoc_default_historical__ranks16-2015-2016.json`
(job `workdir/logs/05_simulation/compare-runs-production-config-check-check-2015-2016-ranks16-2015-2016_<job-id>/`;
the end state needs more than 64G, `--mem 200G` was used).

**Conclusion.** The production configuration runs as intended; nothing found stops the production campaign.
Values for 2016 unless stated; km3 per year.

1. Run check: `passed` (VIC job 43532718, 2 h 30 min; check job 43532719). Coverage complete, water-use budget
   without violation, largest monthly mean |`OUT_WATER_ERROR`| 0.47 mm (2015) and 0.30 mm (2016), no cell-month
   above 1 mm. GRDC (969 stations, reference 2005-2024): median ratio simulated / observed 1.18, median seasonal
   correlation 0.66.
2. Non-renewable withdrawal 1 977 (municipal 106, manufacturing 270, irrigation 1 602), irrigation withdrawal 2 841,
   total withdrawal 4 386: within the judgement lines. 2015 (first year after the cold start): 2 190 non-renewable,
   3 153 irrigation. 85 % of the non-renewable withdrawal of 2016 is repaid within the year from baseflow; the deficit
   grows from 536 (end of 2015) to 841 (end of 2016), i.e. by 305 per year, of the order of published estimates of
   global groundwater depletion (about 280 per year around 2000). India has 678 (34 %) of the non-renewable
   withdrawal and 367 of the deficit; China 164, USA 108, Pakistan 104, Mexico 92. The country masks add up to the
   global total (ratio 1.000).
3. Against snow-density-test `ranks16` (non-renewable off): precipitation, air temperature, LAI and surface storage
   are identical; evapotranspiration +423, qtot +204 (repaid baseflow), consumption +689. Discharge, qtot and
   evapotranspiration differ in the water-use cells and discharge downstream of them; nothing differs in the 30 128
   cells farther than two cells from them. The 10 cells that differ outside these groups all have a reason
   (`cells_summary.json`): two give water to neighbouring cells, three had water use in 2015 only, four are supply
   dams or downstream of one (their release follows the demand of their service cells), none without reason.
   `compare_runs.py`: status `failed` only because the runs write different variables (the D03 daily variables and
   `OUT_NONREN_DEFICIT` in run check); all common variables that depend on water use differ, as expected.
4. Dams: storage, inflow and release of the global dams are the same in 2015 (history year) in both runs. In 2016 a
   dam operates from its first operation month on (VIC-WUR writes inflow, demand and release as 0 before it):
   Akosombo from January, Kariba from April, Three Gorges and Ust-Ilim from November. Global release 14 802 (ref
   14 831), mean storage 7 479 (ref 7 467), withdrawal from dams 4.9 (ref 5.0). The surface-water demand that the
   global dams register falls from 858 (ref) to 184: without non-renewable water the unmet irrigation demand is
   asked again every day (the irrigation demand of the ref run sums to 76 693 over the year, not a volume), with it
   the demand is met. This is the model's definition of the dam demand (`dam_register_demand`), not an error. Side
   observation, not acted on: `dam_register_demand` converts the demand of each service cell with the area of the
   dam cell, not of the service cell; the service cells lie near the dam, so the effect is small (VIC-WUR, frozen
   in D01).
5. Speed and memory at 16 × 8 on a whole node: 761 s to start, 11.24 s per model day (dam-test `ranks16`: 10.08),
   of which writing output 4.20 s (2.85; the D03 daily variables), 1.25 h per model year including the start
   (1.14 h without it). MaxRSS 34.5 GB per rank, AveRSS × ranks 379 GB of 500G. Output per model year: daily
   19.0 GB, monthly 3.3 GB; one state 4.4 GB. The resources file plans 3.0 h per model year: 2.4 × the measured
   value.

**Finding before the run (2026-10-31).** The first render of the campaign stopped in `render_run.py`
(`check_unit_parameters`, and `check_landuse_tiles` after it): `promote_parameter_set.py` copies the provenance record
of the assembled bundle unchanged, so in the production set its `object` is still the candidate path, and the
renderer did not accept it as the record of the production copy. Every campaign on the production parameter set,
the production campaign included, stopped there. The renderer now also accepts a record whose `object` is the same
file of the candidate set that `promotion.yaml` lists as copied (`render_run.parameter_provenance`, test
`ParameterProvenanceTest`).
