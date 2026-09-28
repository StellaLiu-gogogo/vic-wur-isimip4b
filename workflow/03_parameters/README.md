# 03 Parameters

## Purpose

Generate, assemble, and validate the static or slowly varying parameter datasets required by VIC-WUR.

## Scope

This stage may include domain, soil, vegetation, land-use, routing, reservoir, irrigation, and water-use parameters. Subdirectories should be created by parameter family only when implementation work begins.

## Inputs

- Verified source data from `workdir/raw/`.
- Reusable intermediate products from `workdir/intermediate/`.
- Explicit parameter-generation settings.

## Outputs

- Candidate and accepted parameter datasets under `workdir/parameters/`.
- Parameter quality-control evidence under `workdir/qc/parameters/`.
- Accepted parameter definitions under `manifests/parameters/`.

## Allowed content

- Parameter-generation source code.
- Scientific validation code.
- Slurm templates and small configuration templates.
- Tests for scientific invariants and file structure.

## Forbidden content

- Generated parameter NetCDF files.
- Untraceable manual corrections to production parameters.
- A parameter marked as production-ready without quality-control evidence and a manifest.
- Alternative scripts named with `v2`, `fix`, `new`, or `final`.

## Completion criteria

A parameter set is production-ready only when its sources, workflow commit, configuration, checksum, and quality-control status are recorded in an accepted parameter manifest.

