# 04 Forcing

## Purpose

Convert accepted time-dependent inputs into the units, variables, grid, calendar, and file layout required by VIC-WUR.

## Inputs

- Verified source datasets under `workdir/raw/`.
- Reusable caches from `workdir/intermediate/`, used only when their fingerprint matches and `_SUCCESS` exists.
- Accepted domain and parameter references where masking or spatial alignment is required.
- Campaign definitions under `configs/campaigns/`.

## Outputs

- VIC-ready forcing under `workdir/forcing/<family>/`, where `<family>` is `climate`, `landuse`, or `water_use` (see `docs/directory-contracts.md`).
- Processing logs under `workdir/logs/04_forcing/`.
- Coverage, continuity, range, unit, and metadata checks under `workdir/qc/forcing/`.

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

Forcing is simulation-ready only when temporal coverage, grid alignment, variables, units, calendar, missing values, and naming have been validated for the target experiment.

