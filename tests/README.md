# Tests

This directory contains automated tests for workflow code, configuration validation, stage interfaces, and end-to-end smoke execution.

`check_layout.py` checks paths in the repository and, with `--workdir`, in `$ISIMIP4B_WORKDIR` against `docs/directory-contracts.md`. It runs automatically before every commit through `.githooks/pre-commit`.

Recommended structure:

- `unit/`: fast tests of individual functions and small transformations.
- `integration/`: tests of interfaces between workflow stages.
- `smoke/`: a minimal end-to-end workflow using a small spatial and temporal subset.
- `fixtures/`: small, version-controlled test inputs with documented origins.

Tests must not depend on full production datasets unless explicitly marked and documented. Large NetCDF files, model output, caches, and temporary test products do not belong in this repository.

A production workflow change should include tests proportional to its scientific and operational risk. Tests must verify failure behavior as well as successful behavior.

