# Workflow

This directory contains the complete version-controlled workflow. It is organized by data-flow stage rather than by individual experiment, date, or developer.

## Stages

1. `01_acquisition`: discover, transfer, inventory, and verify source data.
2. `02_preprocessing`: convert accepted source data into reusable intermediate products.
3. `03_parameters`: generate and validate VIC-WUR parameter datasets.
4. `04_forcing`: generate VIC-ready time-dependent forcing.
5. `05_simulation`: render run files, build run directories, and submit VIC-WUR simulations.
6. `06_postprocessing`: convert raw model output into protocol-oriented products.
7. `07_quality_control`: evaluate scientific, structural, and protocol compliance.
8. `08_delivery`: assemble only approved products and generate delivery inventories.

## Shared code

`common/` holds Python modules used by at least two stages, such as workdir path resolution, grid utilities, NetCDF metadata handling, checksum and manifest writing, and map plotting. It contains no stage-specific logic and no entry points. Stage code imports it as `from common import <module>` with `PYTHONPATH` including `repo/workflow`. Stage directory names start with a digit and cannot be imported as Python modules; shared code must therefore live in `common/`, not in another stage.

## General contract

Allowed content includes source code, small text templates, Slurm templates, workflow metadata, and stage documentation. Generated NetCDF files, logs, caches, model output, compiled executables, and personal notebooks are forbidden.

Each script must have one canonical responsibility. Before adding a script, search for an existing implementation and extend it when appropriate. Code variants must be represented by Git history or configuration, not by copied files with version-like suffixes.

All stages must fail clearly when required inputs are missing or invalid. Production workflows must not silently substitute scientific defaults.

## Data locations

Workflow code must read and write through `ISIMIP4B_WORKDIR`. Each stage README defines its expected input and output subdirectories. Centralized logs go to `workdir/logs/<stage>/`, using the full stage directory name such as `01_acquisition`. Temporary products belong under `workdir/scratch/<task-id>/`, never in this repository.

Workflow code must never read from `analysis/` or `workdir/analysis/`. A result needed by production must be produced by workflow code.

