# 02 Preprocessing

## Purpose

Transform accepted raw datasets into reusable intermediate products without modifying the original source files.

## Inputs

- Verified datasets under `workdir/raw/`.
- Accepted input manifests under `manifests/inputs/`.
- Explicit transformation settings supplied by the workflow or campaign configuration.

## Outputs

- Reusable caches under `workdir/intermediate/02_preprocessing/<cache-id>/`, each with `cache.yaml` and `_SUCCESS` as defined in `docs/directory-contracts.md`.
- Processing logs under `workdir/logs/02_preprocessing/`.
- Validation summaries required by downstream stages.

## Allowed content

- Scripts for subsetting, remapping, unit conversion, harmonization, and format conversion.
- Reusable libraries and Slurm templates.
- Small grid definitions and text templates when they are source-controlled project assets.

## Forbidden content

- Raw or processed scientific datasets.
- Manual edits to files under `workdir/raw/`.
- Undocumented one-off fixes embedded in production scripts.
- Duplicate implementations distinguished only by version suffixes.

## Completion criteria

Every cache must be reproducible from verified inputs, explicit settings, and a commit recorded from a clean repository, and may be deleted at any time. Required structural and numerical checks must pass before downstream use.

