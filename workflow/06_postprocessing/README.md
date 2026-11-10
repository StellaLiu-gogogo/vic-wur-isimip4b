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
  1601–2100 and daily 1850–2100.
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
records under `logs/06_postprocessing/`), and `routing.py` its own copy of the river-network functions of
`workflow/05_simulation/monitor/grdc.py`, with the same behaviour. This is an exception to the canonical
implementation rule of `AGENTS.md`, approved by the user; it is also recorded in `docs/directory-contracts.md`,
`workflow/06_postprocessing/`. A change of a rule in `workflow/common/` must therefore be checked against
`support.py` by hand.

Until the user starts the production step (AD8), products are made only under `scratch/postprocessing-build/`.

**Order of work.** A product unit is made only from a run chunk that has completed and whose chunk check has passed
(its `summary.json` bound to the chunk's completed attempt). A segment's products are accepted when every unit has
passed and the whole-run check of the run has passed. The number of postprocessing jobs at the same time is limited,
so that they do not slow down the VIC jobs writing to the same file system.

| Step | Content | State |
|---|---|---|
| AD1 | decisions D07 and D11 recorded, D09 and D10 moved to `08_delivery`, contract (`postprocessed/` layout, `workflow/06_postprocessing/` section), layout check and its test, glossary terms, this README | done 2026-11-09, commit `9bb1c11` |
| AD2 | static files of a product set: 0.5° grid, `cellarea`, `contfrac`, `landfrac`, soil-layer depths, `dis` outlet map; tests; scratch run on Slurm; checks (area totals, exactly the 3 310 uncovered cells missing, outlet upstream area against DDM30) | code and unit tests 2026-11-10; scratch run pending |
| AD3 | product unit from one run chunk: aggregation, unit conversion, sector arithmetic, file rules of protocol chapter 5, unit record; tests on small synthetic grids | pending |
| AD4 | check of a unit: global totals 5′ against 0.5° per variable and time step, outlet `dis` equal to the 5′ discharge, mask, time coverage, value ranges, units, dimensions, calendar, attributes, file format; status `passed`, `warning`, `failed` or `not_checked` | pending |
| AD5 | Slurm template, submit script (only chunks completed with a passed chunk check; a limit on jobs at the same time), collecting step with `product-set.yaml` and `checksums.sha256` | pending |
| AD6 | scratch test on `runs/soil-comparison-version-b/ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020` (10 years, production settings with the D03 daily outputs): time, memory and size measured, figures for the user | pending |
| AD7 | review of the scratch products by the user | pending |
| AD8 | production product units as chunks of the campaign pass their chunk checks: first the pre-industrial segment and the two `2021soc` historical segments (expected complete around 2026-11-23), then the others | pending |
| AD9 | merge of the branch into main once no production job runs from main (user) | pending |

## Files

| File | Role |
|---|---|
| `products.yaml` | product configuration: product grid (ISIMIP mask), fill value, file rules of protocol chapter 5, the global attributes `institution` and `contact` (the producers stop while they are not set), static variables and their comments, static variables not provided (`soil`), DDM30 comparison |
| `support.py` | the stage's own infrastructure (see "Self-contained stage") |
| `routing.py` | 5′ routing network of the parameter set, DDM30 network (flow directions −1 sink, 0 outlet, 1–8 east clockwise to north-east), upstream area |
| `static_fields.py` | static files of a product set in `postprocessed/<set>/static/` (D07 parts 2 and 3, D08): `cellarea.nc`, `contfrac.nc`, `landfrac.nc` (ISIMIP variables, units and long names from the protocol), `soil-layers.nc` (thickness and bottom of the three layers, weighted block means), `dis-outlets.nc` (outlet 5′ cell of every 0.5° cell: largest upstream area, ties to the smallest 5′ flat index; its indices, coordinates, upstream area and the number of active 5′ cells). Written into `.writing-static/` and renamed; never overwritten; outside `--scratch` only from a clean repository |
| `check_static.py` | check of the static files, recomputed with 6 × 6 blocks instead of the producer's cell sums: file rules and attributes, coverage (exactly the uncovered mask cells of D08 missing), `cellarea` against the domain areas and the analytic WGS84 area (warning above `cellarea_tolerance`), `contfrac` and `landfrac`, layer depths, outlets (inside the block, active, in the mask, largest upstream area; the network conserves area); DDM30 comparison as a diagnostic only. Writes `qc/postprocessed/<set>/static/` |
| `postprocessing.sbatch`, `submit.py` | Slurm job of a producer and its check, with the job record `logs/06_postprocessing/<job-name>_<slurm-job-id>/`; `submit.py static --campaign <file> [--scratch <task-id>]` |

Tests: `tests/unit/test_postprocessing_static.py` (networks, blocks, outlets, WGS84 area, producer and check end to
end on a tiny synthetic workdir), `tests/unit/test_check_layout_postprocessed.py` (layout of a product set).

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 workflow/06_postprocessing/submit.py static --campaign configs/campaigns/water-global-ec-earth3-esm-1-1.yaml --scratch postprocessing-build
```

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
