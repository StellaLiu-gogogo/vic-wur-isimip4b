# Open Decisions

This is the single list of project decisions that are not yet taken. Each
decision has a **due stage**: the workflow stage that must not produce
accepted outputs until the decision is taken. Coding agents check this list
before working on a stage and remind the user of every open decision due at
or before that stage (see `AGENTS.md`, "Open decisions"). The layout check
reports a warning while a stage contains code and a decision due at or
before it is still open.

Last reviewed: 2026-10-01.

D05 is being handled outside this session by another agent (user, 2026-09-29).

D01 does not block the climate forcing units of the smoke campaign: the user
allowed producing the EC-Earth3-ESM-1-1 `esm-hist` 2011–2020 climate units
as accepted forcing while D01 is open (user, 2026-09-30). The same holds
for the land-use forcing units of all five soc scenarios (`histsoc`,
`1850soc`, `2021soc`, `ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`): they do not
depend on the VIC commit and may be accepted while D01 is open (user,
2026-10-01).

## How to use this list

- **Status** is `open` or `decided`. A decision becomes `decided` only on
  the user's explicit instruction; a coding agent then writes the decision
  record and updates the table on the user's behalf, never on its own
  judgement.
- When a decision is taken, write a decision record
  `docs/decisions/<id>-<short-title>.md` (context, options, decision,
  consequences, date) and set the status to `decided` with a link to it.
  Decided rows stay in the table.
- **Due stage** is a full workflow stage name. A decision triggered by an
  event rather than a stage names the trigger in the "Trigger" column and has
  `-` as due stage.
- Sources in the legacy audit area refer to
  `/lustre/nobackup/WUR/ESG/liu297/vic_global/isimip4b/02Audit/`, which has
  not yet been migrated into this project.

## Decision table

| ID | Decision | Due stage | Trigger | Owner | Status |
|---|---|---|---|---|---|
| D01 | Which VIC-WUR commit is frozen for production | 03_parameters | | user | open (provisional: branch `fix-restart-luapply-snow-state`, head `39e21ff5` on 2026-09-29, recorded in `model/vic.lock.yaml` with `freeze_status: provisional`) |
| D02 | Compute scope: which GCMs, experiments, and priorities fit the available compute, and whether to apply for more | 05_simulation | | user | open |
| D03 | Storage plan for 5′ model output: where it lives during a campaign and when it is deleted after postprocessing | 05_simulation | | user | open |
| D04 | Land use: single-child rule for fallback parents, `rice_rainfed`, ISIMIP paddy area, `*_bf` variables, Köppen period for parameter backfill | 03_parameters | | user | decided 2026-09-30 ([D04-landuse-harmonization.md](D04-landuse-harmonization.md)) |
| D05 | Non-irrigation water use: how to proceed while the ISIMIP4b dataset is not released | 04_forcing | | user, sector coordinators | open |
| D06 | Composition of the `extrasoc` sensitivity experiments (which additional direct human forcings) | 05_simulation | | user, sector coordinators | open |
| D07 | 5′ to 0.5° aggregation method, `dis` outlet mapping, and `contfrac` derivation | 06_postprocessing | | user | open |
| D08 | Simulated domain versus the ISIMIP `water_global` mask: keep the VIC domain and report uncovered mask cells as missing, or extend the domain (fully or partially) | 03_parameters | | user, sector coordinators | decided 2026-09-30 ([D08-mask-coverage.md](D08-mask-coverage.md)): option (a), keep the domain, report uncovered cells as missing |
| D09 | ISIMIP4b `water_global` output filename pattern (not yet published by ISIMIP) | 06_postprocessing | | ISIMIP | open |
| D10 | VIC-WUR model name and version suffix for ISIMIP4b filenames | 06_postprocessing | | user | open |
| D11 | Structure of the postprocessed product-set manifest | 06_postprocessing | | user | open |
| D12 | Whether `2021co2` experiments are reported (VIC-WUR has no CO₂ response) | 08_delivery | | sector coordinators | open |
| D13 | Location and implementation of the backup procedure | - | first production object accepted | user | open |
| D14 | Include the ensemble member in project identifiers | - | a second ensemble member is used | user | open |
| D15 | Migration of the legacy `vic_global/isimip4b/` area into this project | - | approved 2026-09-29 | user | decided ([D15-legacy-migration.md](D15-legacy-migration.md)) |
| D16 | Elevation correction of downward longwave radiation (`lwdown`) in the climate forcing, consistent with the lapse-rate correction of `tair` | 04_forcing | | user | decided 2026-10-01 ([D16-lwdown-elevation-correction.md](D16-lwdown-elevation-correction.md)): option A, ratio method of Cosgrove et al. (2003) as in WATCH/WFDE5 |

## Context

**D01 — Frozen model version.** Every production build, run, and cache
records a model commit. Parameter files must match the input format of that
commit, so the decision is needed before production parameters are
generated.

**D02 — Compute scope.** The model capability audit (legacy audit area,
`VICWUR_ISIMIP4b_WaterGlobal_model_capability_audit_v2_2026-09-20.md`)
estimated the cost of the core experiment set per GCM. That estimate was made
against a Snellius budget, whereas this project runs on Anunna only; the
Anunna allocation available to the project has not been established. The
campaign definitions depend on this decision.

**D03 — Output storage.** The same audit and the land-use scoping estimated
several TB of 5′ output per GCM. Raw model output is not backed up (see
`directory-contracts.md`, "Data protection"), and `/lustre` was 98 % full on
2026-09-29. If the decision allows deleting raw output after postprocessing,
the run layout in `directory-contracts.md` and the run-preservation rule in
`AGENTS.md` must be updated in the same change, because both currently
require a run to keep its raw output.

**D04 — Land-use harmonization.** Open points listed in
`VICWUR_ISIMIP4b_annual_landuse_harmonization_plan_15crops_2026-09-23.md`
(legacy audit area): the tile-count threshold for fallback children in SSP
scenarios, the treatment of `rice_rainfed`, and accepting the change of
paddy area relative to the current VIC coverage.

**D05 — Non-irrigation water use.** The protocol audit found no ISIMIP4b
non-irrigation water-use dataset on DKRZ; Group III default experiments
require it.

**D06 — `extrasoc`.** The protocol leaves the choice of additional direct
human forcings to the modelling team and encourages coordination with the
sector coordinators.

**D07 — Aggregation.** ISIMIP `water_global` output is reported at 0.5°.
The capability audit identified the missing 5′ to 0.5° aggregation, the
outlet mapping for discharge, and the derivation of `contfrac` as gaps.

**D08 — Mask coverage.** The capability audit found ISIMIP mask cells,
mainly in Greenland and the Arctic, that the VIC domain does not cover, and
VIC cells outside the mask. Because extending the domain changes the
parameter set and every forcing unit, the decision is due before
`03_parameters`, not at postprocessing. The analysis task
`isimip-mask-coverage` established the numbers on 2026-09-30: 3 310 of the
67 420 mask cells (2.2 % of the mask area) have no active VIC cell, 2 970 of
them in Greenland. Decided the same day: the domain is kept and the
uncovered cells are reported as missing.

**D09, D10 — Filenames.** See `glossary.md`, "Output naming".

**D11 — Product-set manifest.** Required by "Data protection" in
`directory-contracts.md` to record backups of postprocessed product sets.

**D12 — `2021co2`.** See `glossary.md`, "Sensitivity scenario".

**D13 — Backup procedure.** See `directory-contracts.md`, "Data protection";
its location requires a contract change.

**D14 — Ensemble member.** See `glossary.md`, "Ensemble member".

**D16 — `lwdown` elevation correction.** The climate forcing corrects `tair`,
`psurf`, and `vp` from the ERA5 0.5° orography to the 5′ VIC cell
elevation; method 1.0 only interpolated `lwdown` bilinearly. Decided
2026-10-01: `lwdown` is scaled with the ratio of Satterlund clear-sky
emission at the corrected and the 0.5° level (Cosgrove et al. 2003, as in
WATCH/WFDE5); climate forcing method 1.1. Until then `lwdown` was produced
only in `scratch/`.
