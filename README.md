# VIC-WUR ISIMIP4b

This repository contains the version-controlled workflow used to prepare, run, validate, and deliver VIC-WUR simulations for ISIMIP4b on Anunna.

Large datasets and generated products are stored outside this Git repository in the sibling `workdir` directory. The repository defines how results are produced; the work directory contains the data and products produced by those definitions.

## Repository layout

- `workflow/`: executable workflow code, templates, and stage-specific documentation; `workflow/common/` holds modules shared by several stages.
- `analysis/`: source code of analyses that support decisions but do not feed production; their products live in `workdir/analysis/`.
- `configs/`: campaign definitions and Anunna resource requests.
- `manifests/`: version-controlled identities and inventories for accepted inputs, parameter sets, production runs, and deliveries.
- `model/`: the pinned VIC-WUR source version used for production.
- `environments/`: reproducible software and module specifications.
- `tests/`: unit, integration, and smoke tests with small fixtures, and the layout check `tests/check_layout.py`.
- `docs/`: project-wide documentation, terminology, architecture, and operating procedures.

## Work directory

The sibling `../workdir` directory contains raw data, generated forcing, parameter files, builds, model runs, postprocessed products, quality-control evidence, logs, and delivery products. It is not part of this Git repository.

Set a single environment variable before running the workflow:

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
```

Production scripts must derive data and output paths from this variable or from validated campaign configuration. Personal absolute paths must not be embedded throughout the workflow.

## Reproducibility contract

A production result is reproducible only when all of the following are known:

1. the clean Git commit of this repository;
2. the pinned VIC-WUR commit and executable checksum;
3. the resolved campaign and segment configuration;
4. the exact VIC configuration and Slurm job submitted;
5. the accepted input and parameter manifests;
6. the run manifest and quality-control result.

## Working rules

- Run AI coding sessions from this repository root.
- Keep production source code in `workflow/`, analysis source code in `analysis/`, and all tests in `tests/`.
- Do not commit model outputs, forcing files, logs, caches, compiled executables, or large scientific data.
- Do not create parallel code versions using names such as `v2`, `new`, `fix`, or `final`.
- Use Git commits and tags for code versions and meaningful campaign identifiers for scientific variants.
- Use terminology defined in `docs/glossary.md`.
- Read the relevant stage README before adding files or changing a workflow stage.

## Getting started

1. Activate the pre-commit layout check once per clone: `git config core.hooksPath .githooks`.
2. Read `docs/glossary.md`, `docs/directory-contracts.md`, and `workflow/README.md`.
3. Create or select a campaign definition under `configs/campaigns/`.
4. Verify the pinned model version in `model/vic.lock.yaml`.
5. Build the model and run the smoke tests.
6. Execute workflow stages in dependency order.
7. Treat products as delivery-ready only after quality control passes and a delivery manifest exists.

