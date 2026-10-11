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
| O2 | land-use and water-use producers: extension path and the extension-year option for `1850soc` and `2021soc`; verifiers compare an extension year with the raw data of its source year; the land-use units `1850soc` and `2021soc` (made before the fingerprint block existed) are regenerated as a whole (user, 2026-10-12) | open |
| O3 | climate producer: spin-up start years copied from the cycle year; verifier source-year rule | open |
| O4 | code-equivalence entries; extension of the accepted units (user authorisation per unit); verification of every extended unit | open |
| O5 | climate `esm-picontrol` 1601–1650, then the start years 1551, 1576, 1800, 1825 | open |
| O6 | `05_simulation`: spin-up continuation blocks, run-ID rule, campaign spin-up keys, README | open, after task L |

Start years needed (D20): land use and water use `1850soc` 1601, 2022, 1551, 1576; `2021soc` 1850, 1800, 1825;
climate `esm-picontrol` 1551, 1576, 1800, 1825.

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

