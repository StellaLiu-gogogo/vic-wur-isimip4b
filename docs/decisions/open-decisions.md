# Open Decisions

This is the single list of project decisions that are not yet taken. Each
decision has a **due stage**: the workflow stage that must not produce
accepted outputs until the decision is taken. Coding agents check this list
before working on a stage and remind the user of every open decision due at
or before that stage (see `AGENTS.md`, "Open decisions"). The layout check
reports a warning while a stage contains code and a decision due at or
before it is still open.

Last reviewed: 2026-10-09.

D05 was decided on 2026-10-02 (option A) and amended on 2026-10-03; its first task (D1: acquisition, QA and description of the ISIMIP3a/3b water-abstraction data) was carried out on 2026-10-02 (`manifests/inputs/isimip3-water-abstraction.yaml`, report `workdir/analysis/isimip3-water-abstraction-review/report.md`) and was reviewed by the user on 2026-10-03 (amendments in the record).

D01 does not block the climate forcing units of the smoke campaign: the user
allowed producing the EC-Earth3-ESM-1-1 `esm-hist` 2011–2020 climate units
as accepted forcing while D01 is open (user, 2026-09-30). The same holds
for the land-use forcing units of all five soc scenarios (`histsoc`,
`1850soc`, `2021soc`, `ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`): they do not
depend on the VIC commit and may be accepted while D01 is open (user,
2026-10-01). The water-use forcing units of the same five soc scenarios may
also be accepted while D01 is open (user, 2026-10-04); their demand unit
(mm per model step, mm/day with one model step per day) follows the
`wateruse` plugin at the provisional commit and must be checked again when
D01 is decided.

The smoke campaign (`configs/campaigns/smoke.yaml`, non-production, every output a
candidate) ran on 2026-10-04/05 under the provisional D01 (VIC `39e21ff5`) with
D02, D03 and D06 open: it needs no compute-scope decision (one segment, 2015
and 2011–2020), keeps its 5′ output in the run directory (D03), and uses no
`extrasoc` experiment (D06).

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
| D05 | Non-irrigation water use: how to proceed while the ISIMIP4b dataset is not released | 04_forcing | | user, sector coordinators | decided 2026-10-02, amended 2026-10-03 (SSP series used raw, one producer task D2) ([D05-non-irrigation-water-use.md](D05-non-irrigation-water-use.md)): option A, ISIMIP3a/3b water-abstraction series downscaled with ISIMIP4b population |
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
| D17 | Potential irrigation (`pirrww`, `pirrwwgw`, `pirruse`, `pirrusegw`): whether to report it and, if so, from additional runs with `POTENTIAL_IRRIGATION TRUE` | 08_delivery | | user | open |
| D18 | Snow accumulating every year on high-mountain and glacier cells in the smoke run (about 21 times faster than in the WFDE5-driven natural run on the same cells): whether the climate forcing's elevation correction, the precipitation, or the model's snow treatment on such cells needs a change | - | none: parked; reviewed when the user has time, does not block any stage | user | open |
| D19 | Dams and initial states per experiment: which dams the dam parameters contain (the GDW selection rule DOR ≥ 10 % leaves out large run-of-river reservoirs such as Three Gorges and Itaipu) and which of them (construction years) each DHF scenario uses (`1850soc`, `2021soc`, `histsoc`, SSP units; dams with construction year 0), and how runs are spun up and warm-started (spin-up DHF and dams, date of an initial state against the run start, reuse of another run's end state) | 05_simulation | | user | open |
| D20 | First year of runs on constant DHF units: how the land-use and water-use units of `1850soc` and `2021soc` provide a file of a run's first year that lies outside their own years (`2021soc` historical from 1850, `1850soc` pre-industrial from 1601 and future from 2022, spin-ups), which VIC requires for the start year | 05_simulation | | user | open |

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
non-irrigation water-use dataset on DKRZ (confirmed again 2026-10-02).
The `wateruse` plugin cannot be switched off for experiments with direct
human forcing (irrigation withdrawals and dam demand go through it), so a
substitute was decided: see the record. Amended 2026-10-03 after the D1 review: the SSP series are used raw without a join to 2021, and task D2 produces all five units.

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

**D17 — Potential irrigation.** ISIMIP `pirrww` is the irrigation withdrawal
assuming unlimited water. In the runs of VIC-WUR `39e21ff5` the irrigation
plugin hands the water-use plugin, every day, the whole current soil-moisture
deficit divided by the irrigation efficiency (`plugins/irrigation/src/irr_use.c`,
`irr_set_demand`), and asks again the next day while the deficit lasts; the
irrigation demand written per sector (`OUT_DE_*_SECT`, sector 4) is therefore a
sum of daily deficits, not a withdrawal volume (smoke 2015: 67 226 km3/yr
against 1 763 km3 withdrawn and 957 km3 received by the fields). The potential
variables can only come from separate runs with `POTENTIAL_IRRIGATION TRUE`.
Raised 2026-10-05 during the smoke campaign; left open by the user: the
potential variables are listed as not provided until it is decided, and extra
runs are added then.

**D18 — Snow build-up on glacier cells (parked).** The compute-storage
analysis (`analysis/compute-storage-plan/`, `snow_compare.py`, report
section on spin-up, 2026-10-06) found that in the 2011–2020 smoke run snow
rose every year on 1 928 cells (0.08 % of the area, 111 988 km², mostly
Patagonia, Karakoram, Alaska, Himalaya) by 94 km³/yr in total, against
4.4 km³/yr on the same cells in the sibling project's WFDE5-driven natural
run 1979–2019. The figures relate the temperature difference between the
two forcings to the height of the 5′ cell above its 0.5° parent, which
points at the lapse-rate correction of `tair` (and possibly `prec`) on
cells far above the ERA5 reference height, or at missing glacier
processes in VIC-WUR. No production stage waits for this: the affected
area is 0.08 %, the spin-up convergence test leaves these cells out, and
the ISIMIP products are reported as VIC computes them. The user parks the
question (2026-10-07) for a later look; a possible outcome is a capped or
elevation-dependent lapse rate in `04_forcing/climate` (a new method
version) or a note in the model description.

**D19 — Dams and initial states per experiment.** Raised 2026-10-07 by the
cross-module review. VIC-WUR (`39e21ff5`) switches a dam on when the
simulation year reaches the dam's construction year
(`plugins/dams/src/dam_register.c`) and never switches it off; the active
flag and the storage are restored from an initial state
(`dam_state.c`). The renderer passes one dam file to every segment, so
(a) dams follow the simulation year, not the DHF scenario: a `1850soc`
future segment gets every dam built 1850–2021, a `2021soc` historical
segment or spin-up lacks the dams of 2021 until their construction years,
and the 1 806 dams with construction year 0 are active in every
pre-industrial and spin-up year; (b) a warm start from a state dated after
the run start keeps later dams active: the `smoke-nonrenewable` run
(2011–2020, started 2026-10-07 from the 2021-01-01 state of the smoke run
2011–2020) ran with the 269 dams built 2012–2020 (284 292 hm³ capacity,
172 491 hm³ stored) active from January 2011, so its reservoir operation,
downstream discharge and dam water supply in 2011–2019 are affected. The
user (2026-10-08): dam parameters may need different files for different
experiments, and the spin-up of the model has to be reconsidered. Until
decided, no production segment is rendered, and a warm start whose state
date differs from the run start is not used for results.

Added to D19 on 2026-10-09 (user), from the analysis
`dam-distribution-review` (`workdir/analysis/dam-distribution-review/`):
the dam file (`vic_global_5min_dam_parameters_t3-extended-merged.nc`,
7 925 dams, 6 641 km³) is the GDW tier T3_extended of `vic_parameter`
(capacity ≥ 20 hm³, quality ≤ 4, degree of regulation DOR ≥ 10 %). The DOR
rule leaves out 1 373 GDW reservoirs with 528 km³ that pass the other two
rules, among them Three Gorges (39 km³, DOR 9 %), Itaipu (29 km³), Yacyretá
(21 km³), Porto Primavera (20 km³), Xiluodu and Saratov (13 km³ each) and
Grand Coulee (6 km³); Raza Dike (Razzaza, 26 km³) is left out because its
DOR is missing (−99). The ISIMIP4b reservoirs-dams data (`histsoc`, 7 331
dams, 7 035 km³ in 2021) contain these reservoirs. The question is whether
the dam parameters keep the T3_extended selection, drop or change the DOR
rule (and the treatment of a missing DOR), or are rebuilt from another
source such as the ISIMIP4b data; the dam list has to be fixed before the
per-scenario dam files of this decision are produced, because an initial
state is restored by dam position.

**D20 — First year of runs on constant DHF units.** Raised 2026-10-07 by the
cross-module review. VIC checks the first time of each plugin file of the
start year against the climate (`plugins/general/src/plugin_get_forcing_file.c`),
so `render_run.py` requires the start year to be a file of that year in
every family; later years may be linked to another year (the `constant`
rule of `forcing_years.py`). The land-use and water-use producers write only
the years of their scenario (`1850soc` and `histsoc` 1850–2021, `2021soc`
and SSP units 2022–2100) and stop otherwise, so the `2021soc` historical
segments (start 1850), the `1850soc` pre-industrial segment (start 1601),
the `1850soc` future segments (start 2022) and spin-ups before 1601 cannot
be rendered. Options include letting the producers of constant units write
the start year with the unit's constant field, or another way to satisfy
VIC's start-year check. Related to D19 (spin-up).

**D16 — `lwdown` elevation correction.** The climate forcing corrects `tair`,
`psurf`, and `vp` from the ERA5 0.5° orography to the 5′ VIC cell
elevation; method 1.0 only interpolated `lwdown` bilinearly. Decided
2026-10-01: `lwdown` is scaled with the ratio of Satterlund clear-sky
emission at the corrected and the 0.5° level (Cosgrove et al. 2003, as in
WATCH/WFDE5); climate forcing method 1.1. Until then `lwdown` was produced
only in `scratch/`.
