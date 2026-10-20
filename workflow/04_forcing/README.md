# 04 Forcing

## Purpose

Convert accepted time-dependent inputs into the units, variables, grid, calendar, and file layout required by VIC-WUR.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Inputs

- Verified source datasets under `workdir/raw/`.
- Reusable caches from `workdir/intermediate/`, used only when their fingerprint matches and `_SUCCESS` exists.
- Accepted domain and parameter references where masking or spatial alignment is required.
- Campaign definitions under `configs/campaigns/`.

## Outputs

- VIC-ready forcing under `workdir/forcing/<family>/`, where `<family>` is `climate`, `landuse`, or `water_use`. Each forcing unit (leaf directory) carries a `provenance.yaml` as defined under "Forcing unit and provenance record" in `docs/directory-contracts.md`.
- Processing logs under `workdir/logs/04_forcing/`.
- Coverage, continuity, range, unit, and metadata checks under `workdir/qc/forcing/`.

## Forcing families

| Directory | Units | State |
|---|---|---|
| `climate/` | `forcing/climate/<gcm>/<input-alias>/<variable>/`, VIC variables `tair`, `prec`, `psurf`, `vp`, `swdown`, `lwdown`, `wind`; one file per year | producer, verifier, Slurm template and unit tests implemented (method 1.1, `lwdown` elevation correction of D16) |
| `landuse/` | `forcing/landuse/<soc-scenario>/`, 16-class annual coverage; one file per year | producer, verifier, Slurm template and unit tests implemented (method 1.4, D04); years converted in parallel |
| `water_use/` | `forcing/water_use/<soc-scenario>/` | producer, verifier and Slurm job implemented (method 1.0, D05 as amended 2026-10-03); units of all five soc scenarios (`histsoc`, `1850soc` 1850–2021; `2021soc`, `ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt` 2022–2100; 3 486 files, 7.7 GB) produced and accepted on 2026-10-04 (commit `6655b77`, `qc.status: passed`) |

Each family README lists its inputs, method, and commands.

## Start years outside a unit's years (D20, task O)

VIC-WUR `39e21ff5` checks the forcing files of a run's first year (the climate file's first time gives the record
offset; every plugin file's first time must equal it), so the renderer requires a file of the start year in every
forcing family. Runs on the constant DHF scenarios and the spin-ups start outside the units' own years
(`docs/decisions/D20-first-year-files.md`, decided 2026-10-11). The producers write those start years as
**extension years** of the accepted units: the constant land-use and water-use fields re-stamped to the year (the
water-use demand recomputed with the year's day count), the spin-up climate copied from the cycle year with the
time axis re-stamped. Classification: production workflow code (user, 2026-10-11); the task's steps and their state:

| Step | Content | State |
|---|---|---|
| O1 | the unit-extension rules of the contract moved from the climate producer into `workflow/common/unit_extension.py` | done 2026-10-12 (code-equivalence entries pending the user's approval) |
| O2 | land-use and water-use producers: extension path (`common/unit_extension.py`) and `--start-years` for `1850soc` and `2021soc` (the constant field of the scenario's first year re-stamped; water-use demand per day of the start year); verifiers check a start year against the raw data of its source year and against the unit's source-year files; the land-use units `1850soc` and `2021soc` (made before the fingerprint block existed) are regenerated as a whole in O4 (user, 2026-10-12) | done 2026-10-18 (entry `start-years-water-use`; land use has no code-equivalence entry because its units made before the fingerprint block cannot be extended: the scratch test of histsoc 2015 on commit base 4d52a73 (jobs 43351749 before, 43329875 after, comparison 43351751, `scratch/first-year-files/compare-o2.log`) found the coverage identical; the start-years test 1850soc 1850 + 1601, 1576 (job 43329877) and 2021soc 2022 + 1850, 1800 (job 43329878) passed the verifiers) |
| O3 | climate producer: spin-up start years copied from the cycle year; verifier source-year rule | moved to task P (user, 2026-10-17) |
| O4 | land-use units `1850soc` (1850–2021 plus the start years 1551, 1576, 1591, 1601, 2022; 177 files) and `2021soc` (2022–2100 plus 1800, 1825, 1850; 82 files) regenerated as whole units from commit 248b933 (jobs 43351770, 43351771; the coverage of every earlier year equals the replaced units' value for value, `scratch/first-year-files/compare-landuse-regeneration.log`); water-use units `1850soc` (+ 1551, 1576, 1601, 2022; 1 056 files) and `2021soc` (+ 1800, 1825, 1850; 492 files) extended from commit 1499398 (jobs 43368127, 43368128) and verified whole (43368130, 43368131); vegetation QC run again and passed (43353384) | done 2026-10-20, all four units `qc.status: passed` |
| O5 | climate `esm-picontrol` 1601–1650, then the start years 1551, 1576, 1800, 1825 | moved to task P (user, 2026-10-17) |
| O6 | `05_simulation`: spin-up continuation blocks, run-ID rule, campaign spin-up keys, README | moved to task P (user, 2026-10-17) |

Start years needed (D20): land use `1850soc` 1601, 2022, 1551, 1576 and 1591 (task L natural-run spin-up);
water use `1850soc` 1601, 2022, 1551, 1576; land use and water use `2021soc` 1850, 1800, 1825; climate
`esm-picontrol` 1551, 1576, 1800, 1825 (task P). The climate start years and task P's records use the same form as
O2: `start_years` `{year: source year}` in `provenance.yaml` and the file attribute `source_year`.

## Allowed content

- Forcing conversion and validation source code.
- Variable mappings and small templates.
- Slurm templates for scalable processing.

## Forbidden content

- Forcing data files in the repository.
- Silent gap filling or unit assumptions.
- Scenario-specific copies of common transformation code.
- Personal absolute paths in production scripts.

## Completion criteria

Forcing is simulation-ready only when temporal coverage, grid alignment, variables, units, calendar, missing values, and naming have been validated for the target experiment and the unit's `provenance.yaml` records `qc.status: passed`.

