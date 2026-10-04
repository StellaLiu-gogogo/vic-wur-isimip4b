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

