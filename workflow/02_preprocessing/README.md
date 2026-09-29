# 02 Preprocessing

## Purpose

Transform accepted raw datasets into reusable caches for later stages, without modifying the original source files. These caches are a performance optimization, not scientific products: later stages must produce their accepted outputs under `workdir/parameters/` or `workdir/forcing/`.

## Inputs

- Verified datasets under `workdir/raw/`.
- Accepted input manifests under `manifests/inputs/`.
- Explicit transformation settings supplied by the workflow or campaign configuration.

## Outputs

- Reusable caches under `workdir/intermediate/02_preprocessing/<cache-id>/`, each with `cache.yaml` and `_SUCCESS` as defined in `docs/directory-contracts.md`.
- Processing logs under `workdir/logs/02_preprocessing/`.
- Validation results, placed as defined under "Validation results" in `docs/directory-contracts.md`: structured results read by downstream code in the cache `data/` directory, human-readable QC evidence in `workdir/qc/intermediate/02_preprocessing/<cache-id>/`, and routine information in `workdir/logs/02_preprocessing/`.

## Allowed content

- Scripts for subsetting, remapping, unit conversion, harmonization, and format conversion.
- Stage-specific helper modules and Slurm templates. Code used by more than one stage belongs in `workflow/common/`.
- Small grid definitions and text templates when they are source-controlled project assets.

## Forbidden content

- Raw or processed scientific datasets.
- Manual edits to files under `workdir/raw/`.
- Undocumented one-off fixes embedded in production scripts.
- Duplicate implementations distinguished only by version suffixes.

## Completion criteria

Every cache must be reproducible from verified inputs, explicit settings, and a commit recorded from a clean repository, and deleting it must never lose information. Required structural and numerical checks must pass before downstream use.

