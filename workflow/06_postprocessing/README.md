# 06 Postprocessing

## Purpose

Convert raw VIC-WUR output into scientifically interpretable and protocol-oriented products.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Inputs

- Completed run output and run manifests under `workdir/runs/`, and the run-check summaries under `workdir/qc/runs/`.
- Accepted parameter information required for derived variables and static fields (the production parameter set of the campaign).
- The ISIMIP `water_global` land-sea mask and the DDM30 network under `workdir/raw/ISIMIP4b/InputData/geo_conditions/`.
- Current project and protocol specifications (the protocol commit pinned by the campaign).

## Outputs

- Postprocessed products under `workdir/postprocessed/<product-set-id>/` (layout in `docs/directory-contracts.md`, `postprocessed/`).
- Processing logs under `workdir/logs/06_postprocessing/`.
- Validation evidence under `workdir/qc/postprocessed/`.

## Decisions applied

- **D07** (decided 2026-11-09, `docs/decisions/D07-aggregation-to-half-degree.md`): area-weighted mean over the active
  5′ cells of each 0.5° mask cell (value per simulated land area); `dis` of the 5′ cell with the largest upstream area
  in the 0.5° cell, fixed for all time steps, with DDM30 for a check only; `cellarea` from the 5′ domain areas (km2),
  `contfrac` = simulated land area / `cellarea`, `landfrac` = `contfrac`, `soil` not provided; `soilmoist` monthly
  1601–2100 and daily 1850–2100. Amended 2026-11-11 and 2026-11-12 (AD7 review):
  - F1 (2026-11-12): `*wwgw` = `OUT_WI_GW_SECT` plus the groundwater part of the non-renewable withdrawal. The part
    is N × Ug / (Ug + Us) per 5′ cell, water-use class and month, with Ug and Us the unmet groundwater and
    surface-water demand. This is an exception to the campaign mapping, listed in `campaign_exceptions`.
  - F2: `qtot`, `qsb`, `qg`, `qr` keep `OUT_BASEFLOW`; a comment explains the repayment of the deficit.
  - F3: `evap` leaves out the 5′ cell-months of the task T rule (\|`OUT_WATER_ERROR`\| > 1 mm) and averages the
    remaining 5′ cells. A 0.5° cell-month is missing only when no 5′ cell remains. Both are listed in the unit
    record.
- **D08**: products masked with `landseamask_water-global.nc`; the 3 310 uncovered mask cells are `1e+20`; active VIC
  cells outside the mask do not enter the aggregation.
- **D11** (decided 2026-11-09, `docs/decisions/D11-product-set-manifest.md`): product-set ID = campaign ID; one product
  unit per run chunk with its `provenance.yaml`; `product-set.yaml` and `checksums.sha256` written only by the
  collecting step.
- **D09, D10** (open, due before `08_delivery` since 2026-11-09): the products follow the file rules of protocol
  chapter 5 with internal names; the ISIMIP identity of every file is recorded in the unit record, and `08_delivery`
  gives the ISIMIP names.
- **D03** (option (a)): every run keeps its 5′ output. This stage never deletes or changes run output. Deleting 5′
  output after the products have passed their checks would be D03 option (b): an amendment of D03 (with
  `AGENTS.md` and `docs/directory-contracts.md`) and a deletion authorisation per list, both decided by the user.

## Task AD: postprocessing of campaign `water-global-ec-earth3-esm-1-1`

Classification: production workflow code (user, 2026-11-09): this stage makes the accepted products of
`postprocessed/` that go to delivery; it is not decision support. Branch `task-ad-postprocessing`, worktree
`workdir/scratch/postprocessing-build/repo`.

**Code during the campaign (user, 2026-11-09).** The run jobs of the campaign read the code of the main checkout
while they run, so the main checkout is not edited, committed or switched while a production job is queued or
running from it. Every change of this task (code, documentation, decision records, contract, layout check) is made
and committed on the branch only, each commit after the user has seen its message; nothing is pushed. The branch is
merged into main by the user's decision once no production job runs from main.

**Accepted products from the branch (user, 2026-11-09, option (ii)).** Accepted product units may be made from a
commit of the branch before it is merged, under these conditions:

- the worktree is clean (rule 14) and the unit record names the commit and the branch;
- the branch is later merged into main with a merge commit (never rebased or squashed), so that every commit that
  made accepted products stays in the history of main;
- a later change of the branch that would change products already made is either applied by making those units again
  (with the user's authorisation, an existing unit is never overwritten) or shown to leave them unchanged by a
  code-equivalence entry (`manifests/code-equivalence.yaml`);
- the stage's own code does not change `05_simulation` or `workflow/common/`; a change there needs the user's consent
  first.

**Self-contained stage (user, 2026-11-10).** The stage may later be published on its own, so it imports no module of
`workflow/common/` or of another stage. `support.py` holds its own copy of the infrastructure rules it needs (workdir
through `ISIMIP4B_WORKDIR`, Git state and the clean-repository rule, sha256, QC statuses and exit statuses, job
records under `logs/06_postprocessing/`), `routing.py` its own copy of the river-network functions of
`workflow/05_simulation/monitor/grdc.py`, and `product_set.py` its own copy of the rules by which
`workflow/05_simulation/render/` derives the reported segments and their chunks from the campaign and the protocol,
with the same behaviour (`tests/unit/test_postprocessing_set.py` compares the two on every campaign file). This is an exception to the canonical
implementation rule of `AGENTS.md`, approved by the user; it is also recorded in `docs/directory-contracts.md`,
`workflow/06_postprocessing/`. A change of a rule in `workflow/common/` must therefore be checked against
`support.py` by hand, and a change of the segment or chunk rules of `05_simulation` against `product_set.py`.

Until the user starts the production step (AD8), products are made only under `scratch/postprocessing-build/`.

**Order of work.** A product unit is made only from a run chunk that has completed and whose chunk check has passed
(its `summary.json` bound to the chunk's completed attempt). A segment's products are accepted when every unit has
passed and the whole-run check of the run has passed; a unit check whose only warning is the range check counts as
passed (D11 amendment 2026-11-11: values outside the protocol's valid range are kept as VIC-WUR computed them and
counted per product file in `product-set.yaml`). The number of postprocessing jobs at the same time is limited,
so that they do not slow down the VIC jobs writing to the same file system.

| Step | Content | State |
|---|---|---|
| AD1 | decisions D07 and D11 recorded, D09 and D10 moved to `08_delivery`, contract (`postprocessed/` layout, `workflow/06_postprocessing/` section), layout check and its test, glossary terms, this README | done 2026-11-09, commit `9bb1c11` |
| AD2 | static files of a product set: 0.5° grid, `cellarea`, `contfrac`, `landfrac`, soil-layer depths, `dis` outlet map; tests; scratch run on Slurm; checks (area totals, exactly the 3 310 uncovered cells missing, outlet upstream area against DDM30) | done 2026-11-10, commit `992cc60`; scratch job 43792579 (21 s, 0.8 GB) `passed`: 64 110 covered and 3 310 uncovered mask cells, 11 328 active 5′ cells outside the mask, `cellarea` within 4e-7 of the WGS84 area, continental area 135.53 million km2, 8 323 cells with `contfrac` below 1, 79 461 outlets of the 5′ network carry all active area; DDM30 diagnostic over 18 240 cells with at least 10 000 km2: median ratio 0.97, 50 % within 10 %, 74 % within 30 % (large rivers on the 1:1 line; smaller rivers sometimes in the neighbouring 0.5° cell); layer thickness 0.3 m, 0.5–4.0 m (median 1.7 m) and 0.18–0.27 m |
| AD3 | product unit from one run chunk: aggregation, unit conversion, sector arithmetic, file rules of protocol chapter 5, unit record; tests on small synthetic grids | done 2026-11-10, commit `56d5ac9`; D11 amended (run output by size and modification time; check status outside the unit) |
| AD4 | check of a unit against the protocol text (user, 2026-11-10: the ISIMIP4b output schema is not published; protocol commit of the campaign and protocol chapter 5 are the reference): record, file format, time axis, coverage, values recomputed from the 5′ output for sampled time steps, identities between variables; warnings for values outside the protocol range and for daily products whose monthly means differ from the monthly product | done 2026-11-10, commit `2546eec` |
| AD5 | Slurm template, submit script (only chunks completed with a passed chunk check; a limit on jobs at the same time), collecting step with `product-set.yaml` and `checksums.sha256` | done 2026-11-11, commit `e275f4a`: the expected units of the production campaign are 104 (20 reported runs; 25-year chunks), the same runs and chunks as stage 05 for all 13 campaign files |
| AD6 | scratch test on `runs/soil-comparison-version-b/ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020` (10 years, production settings with the D03 daily outputs): time, memory and size measured, figures for the user | done 2026-11-11 from commit `e275f4a`, outputs under `scratch/postprocessing-build/`: static files 43834904 `passed` (2.5 min, 0.8 GB); unit 43835929: producer 1 h 27 min (8.7 min per model year while the production runs wrote to the same file system) and 16.5 GB, 40 files (37 monthly, daily `qtot`, `dis`, `soilmoist`), 4.8 GB (5′ output 208 GB; about 1.1 TB for the campaign); check 7 min and 9.5 GB, `warning`: every check passed (values recomputed from the 5′ output within 6e-8 relative) except the range check, negative monthly `evap` (4 % of cell-months, winter in high latitudes and on the Tibetan Plateau, at least −0.38 mm/day) and daily `dis` above 700 000 m3 s-1 at the Amazon mouth (23 days in 2013, at most 776 402 m3 s-1), both model behaviour, so the user amended D11 (range warnings do not hold back acceptance); collecting step and set check 43856941 `passed` (unit `present`: not a production source). The run was a cold start, so discharge starts from 0 in January 2011. Unit job resources set to 8 h and 40 GB |
| AD7 | review of the scratch products by the user | 2026-11-11/12: findings F1–F3 decided (D07 amendments 2026-11-11 and 2026-11-12). F1 (2026-11-12): `*wwgw` = `OUT_WI_GW_SECT` + the groundwater part of the non-renewable withdrawal, by the proportional rule. F2 (a): `qtot`/`qsb`/`qg`/`qr` keep `OUT_BASEFLOW`, with a note on the deficit repayment. F3: the task T rule in `evap`, the remaining 5′ cells averaged, listed in the unit record, checked by the new unit check `exclusions`. Scratch rerun 43940969 from `399de68` (F2, F3), then 43947664 from `ea45e20` (F1 as well): every check passed except the range check (warning, as in AD6); the new `exclusions` check passed with 0 left-out cell-months; values recomputed from the 5′ output within 6e-8 relative. Means 2011–2020 inside the 0.5° mask: `atotwwgw` 1 063 km3/yr (`airrwwgw` 622, `adomwwgw` 170, `aindwwgw` 271; 279 before F1), the same as the independent split from the 5′ output; no cell-month where a `*wwgw` is above the total withdrawal of its sector, or `adomwwgw`/`aindwwgw` above `pdomwwgw`/`pindwwgw`. Producer 1 h 7 min and 16.6 GB, check 13 min and 9.5 GB. Collecting step and set check 43952110 `passed`. Open: the user's review of content and format |
| AD8 | production product units as chunks of the campaign pass their chunk checks: first the pre-industrial segment and the two `2021soc` historical segments (expected complete around 2026-11-23), then the others | pending |
| AD9 | merge of the branch into main once no production job runs from main (user) | pending |

## Files

| File | Role |
|---|---|
| `products.yaml` | product configuration: product grid (ISIMIP mask), fill value, file rules of protocol chapter 5, the global attributes `institution` and `contact` (the producers stop while they are not set), static variables and their comments, static variables not provided (`soil`), DDM30 comparison, the recipes of the ISIMIP variables (with the `exclude` rule of `evap`, the `nonrenewable_groundwater` part of `*wwgw` by `nonrenewable_split`, the `campaign_exceptions`, and the `notes` appended to comments; D07 amendments 2026-11-11 and 2026-11-12), the settings of the unit check |
| `support.py` | the stage's own infrastructure (see "Self-contained stage") |
| `routing.py` | 5′ routing network of the parameter set, DDM30 network (flow directions −1 sink, 0 outlet, 1–8 east clockwise to north-east), upstream area |
| `static_fields.py` | static files of a product set in `postprocessed/<set>/static/` (D07 parts 2 and 3, D08): `cellarea.nc`, `contfrac.nc`, `landfrac.nc` (ISIMIP variables, units and long names from the protocol), `soil-layers.nc` (thickness and bottom of the three layers, weighted block means), `dis-outlets.nc` (outlet 5′ cell of every 0.5° cell: largest upstream area, ties to the smallest 5′ flat index; its indices, coordinates, upstream area and the number of active 5′ cells). Written into `.writing-static/` and renamed; never overwritten; outside `--scratch` only from a clean repository |
| `check_static.py` | check of the static files, recomputed with 6 × 6 blocks instead of the producer's cell sums: file rules and attributes, coverage (exactly the uncovered mask cells of D08 missing), `cellarea` against the domain areas and the analytic WGS84 area (warning above `cellarea_tolerance`), `contfrac` and `landfrac`, layer depths, outlets (inside the block, active, in the mask, largest upstream area; the network conserves area); DDM30 comparison as a diagnostic only. Writes `qc/postprocessed/<set>/static/` |
| `make_unit.py` | one product unit (D07, D11): every ISIMIP variable of `output.isimip` by the recipes of `products.yaml` (which must name exactly the campaign's VIC outputs), monthly from the monthly stream and daily where the protocol names daily and the daily stream has every output of the recipe; area-weighted means, volumes per simulated area, outlet discharge, unit conversion by VIC unit and protocol unit; soil layers as ISIMIP varying levels (`lev`, `depth`, `depth_bnds`, global attributes `location_varying_layer_depth` true, `time_varying_layer_depth` false); time in days since 1601-01-01, first day of the period; `institution`, `contact`, `reference_area` and a `comment` with the recipe and its notes; the `exclude` rule of a recipe (`evap`: task T rule): left-out 5′ cell-steps, the mean of the remaining 5′ cells, missing where none remains, listed under `exclusions` of the unit record and counted in the comment; `nonrenewable_groundwater` (`*wwgw`): the groundwater part of the non-renewable withdrawal per 5′ cell, water-use class and time step, summed over the classes of the sector; unit record `provenance.yaml`. Outside `--scratch` only from an accepted source (production run, completed attempt, passed chunk check bound to it) and a clean repository; written via `.writing-<start>-<end>/`, never overwritten |
| `check_unit.py` | check of a product unit, writes `qc/postprocessed/<set>/<gcm>/<segment-key>/<start>-<end>/` (`summary.json`, `reports/check.json`, `figures/maps.png`, `figures/global_series.png`): record (files and sha256 as recorded, static files unchanged, source attempt still the latest completed one, run output files with the recorded size and modification time), file format (data model, float32, protocol units and long name, dimensions, mask grid north to south, time in days since 1601-01-01 and an accepted calendar, compression, one chunk per field and layer, fill and missing value, `institution`, `contact`, varying levels), time axis (every day or month, first day of the period), coverage (exactly the covered cells), recompute (for `recompute_steps_per_year` time steps per year every product recomputed from the 5′ output with sums per cell, not the producer's matrix, and `dis` against the outlet cells), identities (`qtot` = `qs` + `qsb`, `qg` = `qr` = `qsb`), exclusions (the rule output of an `exclude` recipe read at every time step: the left-out 5′ cell-steps and the missing 0.5° cells are exactly those of the unit record; coverage allows missing values only there, and every time step with a left-out cell is recomputed; the groundwater part of `*wwgw` recomputed for all classes at once); warnings: values outside the protocol's valid range, monthly means of daily products against the monthly products. Settings under `unit_check` in `products.yaml`. Product files are read in blocks of time steps |
| `product_set.py` | the product set of a campaign (D11): the expected product units, derived from the campaign and its protocol commit by the stage's own copy of the segment and chunk rules of `05_simulation` (experiments, exclusions, explicit, identical and not-simulated period entries, sensitivity equivalence, restriction labels, `chunk_years` of the resources file); the run manifest of every existing run must name the same years and chunks. The state of a unit's source (production run, latest attempt completed, chunk check passed and bound to it), of the whole-run check (bound to the latest attempt of every chunk), and of every unit: `missing`, `present` (made, not accepted: not checked yet, check warning, a source or a repository that was not accepted), `accepted`, `failed` (check failed, unit record changed after its check, a product file of another size than recorded, a newer attempt of the source chunk) |
| `collect_set.py` | collecting step, the only writer of `postprocessed/<set>/product-set.yaml` and `checksums.sha256` (both rewritten at every collection via a temporary name): identity of the set, state of D07–D11 from `docs/decisions/open-decisions.md`, static files with sha256 and check status, every expected unit with status and reasons, per segment accepted or not (every unit accepted and the whole-run check passed and bound), counts, the writing commit and job; checksums of the static files hashed, those of the unit files from the unit records (the unit check hashes the files), only the sizes compared |
| `check_set.py` | check of the set records against the disk (walking the set directory, not by the collecting step's derivation): records (campaign and `checksums.sha256` unchanged since the collection, line format), inventory (every product file listed once, every listed file present, static files hashed again, unit files with the size and sha256 of their unit record), units (every unit directory expected and recorded as made, counts, accepted segments consistent); warnings for failed units and staging directories. Writes `qc/postprocessed/<set>/` (`summary.json`, `reports/check.json`) |
| `postprocessing.sbatch`, `submit.py` | Slurm job of a producer and its check, with the job record `logs/06_postprocessing/<job-name>_<slurm-job-id>/`. `submit.py static` (static files), `submit.py unit` (one job per ready unit: not made, no staging directory, no active job, source chunk completed with a passed chunk check bound to its latest attempt, outside `--scratch` static files passed; at most `--max-jobs` product-unit jobs, default 4, queued or running at the same time; `--run`, `--chunk` to select), `submit.py collect` (collecting step and set check); `--dry-run` lists the units and prints the first job |

Tests: `tests/unit/test_postprocessing_static.py` (networks, blocks, outlets, WGS84 area, producer and check end to
end on a tiny synthetic workdir), `tests/unit/test_postprocessing_unit.py` (a product unit from a synthetic one-year
run: values, units, time axes, layers, unit record, the task T rule of `evap`, the groundwater split per water-use class, the campaign exception it needs, and the notes in the comments; the unit check passes and finds a changed value or source, an unlisted left-out cell-month and a value at a cell recorded as missing), `tests/unit/test_postprocessing_set.py` (expected units against stage 05 on every campaign file, segment rules on a
tiny protocol, unit selection for submission, collecting step and set check on the synthetic run: present, accepted,
a newer source attempt, an unlisted file, a run manifest that differs), `tests/unit/test_check_layout_postprocessed.py`
(layout of a product set).

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 workflow/06_postprocessing/submit.py static --campaign configs/campaigns/water-global-ec-earth3-esm-1-1.yaml --scratch postprocessing-build
python3 workflow/06_postprocessing/submit.py unit --campaign configs/campaigns/water-global-ec-earth3-esm-1-1.yaml --dry-run --scratch postprocessing-build
python3 workflow/06_postprocessing/submit.py collect --campaign configs/campaigns/water-global-ec-earth3-esm-1-1.yaml --scratch postprocessing-build
```

The unit step submits only what is ready at the time of the call and at most `--max-jobs` jobs; it is called again as
chunks complete (each call lists every unit with the reason it is not submitted), and the collecting step after the
unit jobs have ended.

## When the ISIMIP4b output schema is published

Checked on 2026-11-10: protocol4.isimip.org has no `pattern/ISIMIP4b/OutputData/water_global.json` and no
`schema/ISIMIP4b/OutputData/water_global.json` (HTTP 404, while the ISIMIP4b InputData pattern answers), and the
protocol repository (main `b79b94f`, 2026-11-04) has only `InputData` and `SecondaryInputData` under
`pattern/ISIMIP4b/` and `schema/ISIMIP4b/`. The ISIMIP3b schema of water_global describes only the file and path names
and the allowed value of each name part (model, climate forcing, bias adjustment, scenarios, variable, region, time
step); units, dimensions, ranges and attributes come from the protocol's variable definitions, which this stage
already reads. When the ISIMIP4b output pattern and schema are published:

1. acquire the protocol commit that publishes them into `raw/external/isimip-protocol-4/<commit>/` with its input
   manifest; the campaign keeps its pinned commit while its runs are in production;
2. compare the water_global variable definitions of the two commits (units, frequency, dimensions, valid range,
   variables added or removed): changed long names or comments are applied to the delivery copies; a changed unit
   or layer requirement means the affected products are made again, as a new product set (D11), by the user's
   decision;
3. decide D09 (filename pattern) and D10 (model name); `08_delivery` builds the ISIMIP names and the file splitting
   (e.g. ten-year files of daily data) from the identity fields of the unit records into copies under `delivery/`,
   never changing `postprocessed/`;
4. check the identity fields against the allowed values of the schema (`ec-earth3-esm-1-1`, `era5`, the scenario
   specifiers, `default`, `global`, `daily`, `monthly`); a different spelling is a mapping in `08_delivery`;
5. run isimip-qc on the delivery copies only: its `--fix` rewrites files in place, and it queries PyPI at start-up
   (to be checked on the compute nodes).

## Allowed content

- Variable mapping, derivation, unit conversion, temporal aggregation, file splitting, merging, and metadata code.
- Small protocol mapping tables and templates.
- Tests of units, dimensions, calendars, and conservation relationships.

The stage directory stays flat (`docs/directory-contracts.md`, `workflow/06_postprocessing/`).

## Forbidden content

- Postprocessed scientific files in the repository.
- In-place modification of raw model output.
- Hard-coded version strings or delivery dates as substitutes for provenance.
- Moving products to delivery before quality control passes.

## Completion criteria

Postprocessing is complete when every product can be traced to source runs and the expected variables, units, dimensions, time coverage, metadata, and file inventory have been verified.
