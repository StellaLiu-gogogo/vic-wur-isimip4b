# D03 — Storage of the 5′ model output

Status: **decided 2026-10-22** by the user.
Due stage: `05_simulation`.

## Context

A production campaign writes several TB of 5′ output per GCM. Raw model
output is not backed up (`docs/directory-contracts.md`, "Data protection"),
and `/lustre` is shared and nearly full. The decision fixes where the 5′
output lives during a campaign, whether it is deleted after postprocessing,
and which variables are written daily. If raw output could be deleted, the
run layout in `docs/directory-contracts.md` and the run-preservation rule in
`AGENTS.md` would have to change in the same commit. Evidence comes from the
analysis task `compute-storage-plan` (task F, report
`workdir/analysis/compute-storage-plan/report.md`).

## Evidence

- Output per model year (smoke 2015, VIC `COMPRESS 2`): daily stream with
  `OUT_RUNOFF`, `OUT_BASEFLOW`, `OUT_DISCHARGE` (for `qtot`, `dis`) 6.78 GB;
  monthly stream with every mapped variable 3.13 GB; end state 4.38 GB per
  job. A spin-up writes a monthly stream of its convergence variables only
  (about 0.65 GB per model year, task P).
- Daily size of further VIC outputs, estimated from their monthly size
  (task F, `tables/daily_cost_by_variable.csv`): `OUT_SOIL_MOIST` (3 layers)
  6.64 GB, `OUT_EVAP` 2.30 GB, `OUT_WITHDRAWN` 1.92 GB per model year.
- Lossless compression above VIC's level 2 saves at most a few percent and
  slows the write; rounding to significant digits would need a step after the
  run and is lossy.
- `/lustre` had 133 TB free on 2026-10-05 and 81 TB free (98 % used) on
  2026-10-22, for all users. The project workdir held about 3.9 TB
  (forcing 2.3 TB, raw 1.3 TB, runs 0.2 TB).
- `06_postprocessing` does not exist yet (D07, D09, D10, D11 open), so no 5′
  file could be deleted after QC before it is built.

## Options considered

- (a) Keep all 5′ output in the run directory (current contract).
- (b) Keep states, 5′ monthly output and run records; a workflow step deletes
  the 5′ daily output once the 0.5° products made from it have passed QC
  (task F recommendation; changes to `AGENTS.md`,
  `docs/directory-contracts.md` and the stage READMEs).
- (c) Keep only states, run records and 0.5° products.
- Daily variables: only the protocol-daily `qtot` and `dis`; or also the
  "daily if possible" variables; or a chosen set.
- Rolling climate forcing (remove picontrol years after their last use):
  needs a forcing-contract change.

## Decision

1. **Where and how long.** Option (a): every run keeps all its 5′ output in
   its run directory `runs/<campaign-id>/<run-id>/output/` (and
   `chunks/<start-year>-<end-year>/output/`) in the workdir on
   `/lustre/nobackup`, together with configuration, logs, states and run
   manifest. Nothing is deleted after postprocessing. `AGENTS.md` and
   `docs/directory-contracts.md` stay as they are; deleting run output stays
   a user authorisation under "Deletion permissions".
2. **Daily output.**
   - Every reported segment writes `OUT_RUNOFF`, `OUT_BASEFLOW` and
     `OUT_DISCHARGE` daily (`qtot`, `dis`).
   - The segments of the historical and future periods (1850–2100, every
     climate scenario, `picontrol` included) also write `OUT_SOIL_MOIST`,
     `OUT_EVAP` and `OUT_WITHDRAWN` daily.
   - The pre-industrial segment (1601–1849) and the spin-ups do not write
     these three daily.
   - The monthly stream is unchanged.
3. **Climate forcing.** No rolling forcing for now: climate units keep all
   their years. It is decided separately if space becomes short.

## Consequences

- Storage for EC-Earth3-ESM-1-1 with the D02 scope (2308 reported years, 2059
  of them in the historical and future periods):

  | Part | TB |
  |---|---|
  | 5′ daily output (15.6 for `qtot`/`dis`, 22.4 for the three extra variables) | 38.0 |
  | 5′ monthly output | 7.2 |
  | End states (about 125 jobs) | 0.55 |
  | Climate forcing (`picontrol` 1601–2100, historical 1850–2021, vl and h 2022–2100) | 11.1 |
  | Total | about 57 |

  This is about 70 % of the free space of `/lustre` on 2026-10-22, which is
  shared with other users. No free-space threshold is set; the user reviews
  this decision (options (b) or rolling forcing, or a storage request to the
  admins, D02) when space becomes short.
- Writing the three extra daily variables adds about 15 min per model year
  (VIC gathers and compresses every field on one rank), about 1.4 h per model
  year in the historical and future segments; included in the D02 estimate.
- `05_simulation`: the campaign output mapping lists streams per variable for
  the whole campaign. Writing the extra daily variables only in the
  historical and future periods needs a campaign key and renderer support for
  period-dependent daily outputs; implementation is a workflow task proposed
  to the user after this record. The three are written in addition to the
  protocol mapping; `soilmoist` could then be reported daily from 1850 and
  monthly before (a postprocessing question, D07 and D09); `OUT_EVAP` and
  `OUT_WITHDRAWN` daily are not protocol-daily variables.
- Backups are unchanged: a run backup excludes `output/`; the 0.5° products
  remain the protected form of the results (D13).
- The analysis task `compute-storage-plan` is closed for D03; its report stays
  the evidence.
