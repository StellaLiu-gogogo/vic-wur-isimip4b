# 06 Postprocessing

## Purpose

Convert raw VIC-WUR output into scientifically interpretable and protocol-oriented products.

## Inputs

- Completed run output and run manifests under `workdir/runs/`.
- Accepted parameter information required for derived variables.
- Current project and protocol specifications.

## Outputs

- Postprocessed products under `workdir/postprocessed/`.
- Processing logs under `workdir/logs/06_postprocessing/`.
- Intermediate validation evidence under `workdir/qc/postprocessed/`.

## Allowed content

- Variable mapping, derivation, unit conversion, temporal aggregation, file splitting, merging, and metadata code.
- Small protocol mapping tables and templates.
- Tests of units, dimensions, calendars, and conservation relationships.

## Forbidden content

- Postprocessed scientific files in the repository.
- In-place modification of raw model output.
- Hard-coded version strings or delivery dates as substitutes for provenance.
- Moving products to delivery before quality control passes.

## Completion criteria

Postprocessing is complete when every product can be traced to source runs and the expected variables, units, dimensions, time coverage, metadata, and file inventory have been verified.

