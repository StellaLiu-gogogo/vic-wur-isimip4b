# Manifests

Manifests provide machine-readable evidence about accepted data and products. They describe what was actually used, accepted, or delivered; configuration describes what was intended.

## `inputs/`

Records authoritative source identity, dataset version, expected coverage, file inventory, sizes, checksums, and verification status for accepted external inputs.

## `parameters/`

Records the identity, sources, workflow commit, generation configuration, checksums, and quality-control status of accepted parameter sets.

## `runs/`

May contain concise summaries of formally accepted production runs. The complete run manifest remains with the run under `workdir/runs/<campaign-id>/<run-id>/`. Debug, trial, failed, and routine run manifests do not need to be copied into Git.

## `deliveries/`

Records final delivery identity, source runs, protocol and quality-control versions, file inventories, checksums, status, and destination.

## Rules

- Prefer stable logical identifiers and paths relative to the project roots.
- Generate large file inventories programmatically as TSV or CSV.
- Never edit checksums or file counts merely to match expectations.
- Do not store the referenced scientific data in this directory.
- A manifest must distinguish expected, observed, passed, failed, warning, and not-checked states.

