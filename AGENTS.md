# Project Instructions for Coding Agents

## Scope

These instructions apply to the entire VIC-WUR ISIMIP4b repository.
They are mandatory for all coding agents and all tasks performed in this
repository.

The complete workflow runs on Anunna. Do not introduce configuration,
documentation, paths, modules, scheduler profiles, or deployment instructions
for another computing platform.

## Required reading

Before creating, moving, renaming, copying, or generating any file or
directory, read:

1. `docs/directory-contracts.md`;
2. the README in the affected top-level directory;
3. the README for the affected workflow stage, when applicable;
4. `docs/glossary.md` when introducing or interpreting project terminology.

The layouts, naming rules, allowed contents, forbidden contents, and lifecycle
rules in `docs/directory-contracts.md` are mandatory.

## Directory placement

- Store version-controlled workflow source code under `workflow/`. Store
  Python modules shared by two or more stages under `workflow/common/`.
- Store analysis source code under `analysis/<task-id>/` and its generated
  products under `../workdir/analysis/<task-id>/`.
- Store campaign definitions and Anunna resource definitions under
  `configs/`.
- Store accepted inventories and provenance records under `manifests/`.
- Store automated tests and small test fixtures under `tests/`.
- Store maintained project documentation under `docs/`.
- Store only the pinned VIC-WUR version record and related documentation under
  `model/`.
- Store environment specifications under `environments/`.
- Store large inputs and generated products under the sibling `../workdir/`
  hierarchy defined in `docs/directory-contracts.md`.

Do not introduce a new top-level directory, directory level, naming pattern,
output location, or file category unless it is permitted by
`docs/directory-contracts.md`.

If requested work does not fit the current contract:

1. do not invent a location;
2. identify the conflict;
3. propose the smallest contract change;
4. obtain user approval when it changes the project structure;
5. update `docs/directory-contracts.md` before placing production content in
   the new location.

## Workflow or analysis classification

The user decides whether new code belongs to `workflow/` or `analysis/`.
Before writing code for a new task:

1. state the proposed classification and the reason, using the criteria in
   `analysis/README.md`;
2. if the classification is not unambiguous, ask the user and wait for the
   answer;
3. never use `analysis/` as the default for code that is hard to classify;
4. record the user's decision in the task README.

Workflow code must never read from `analysis/` or `../workdir/analysis/`.

## Repository and workdir boundary

The repository defines how results are produced. The workdir contains inputs,
builds, runs, logs, intermediate data, and generated products.

Never commit or place the following in the repository:

- production NetCDF, GeoTIFF, HDF, Zarr, or similar scientific data;
- downloaded forcing or parameter data;
- model output or state files;
- compiled executables and build trees;
- Slurm stdout or stderr logs;
- package caches, temporary files, or notebook checkpoints;
- credentials, tokens, secrets, or personal authentication files.

No workdir directory may contain the only copy of source code. Temporary code
created during exploration must be promoted to the appropriate repository
location or deleted before the task is considered complete.

Files under `../workdir/raw/` are immutable. Never modify them in place.

Files may be written to `../workdir/intermediate/` only by workflow code under
`workflow/`, and only as reproducible caches with a declared producing
workflow, recorded inputs, a fingerprint, rebuild instructions, and no
irreplaceable information. Never write there manually, from analysis code, or
from a repository that is not clean (see `docs/glossary.md`). Final workflow products go to their purpose-specific
workdir directory. Uncertainty about classification is not a reason to use
`intermediate/`: intermediate is a rebuildable performance cache, never a
scientific product or a storage destination.

## Naming and versioning

Use Git commits, branches, and tags for source-code versioning. Do not create
parallel code or directory versions using names such as:

- `v1`, `v2`, or similar numeric suffixes;
- `new`, `old`, `fix`, `fixed`, `final`, or `latest`;
- a date used only as a substitute for version control;
- a developer or agent name.

Dates are allowed when they represent a real scientific, protocol, audit,
meeting, delivery, or run attribute rather than a code version.

Use stable, meaningful identifiers for datasets, parameter sets, experiments,
runs, builds, products, and deliveries. Use official lowercase identifiers for
GCMs, scenarios, and variables where the upstream protocol defines them.

## Canonical implementation rule

Before adding a source file, search for an existing implementation with the
same responsibility. Extend or refactor the canonical implementation when
appropriate. Do not create a parallel implementation merely to avoid editing
existing code.

Represent scientific variants through explicit campaign configuration.
Represent reusable execution differences through templates or structured
resource configuration. Do not duplicate workflow code for individual GCMs,
scenarios, years, or experiments.

## Configuration and templates

- Campaign configuration describes intended scientific behavior. It selects
  ISIMIP experiments; segments are derived by workflow code from the pinned
  protocol and are never listed by hand.
- Resource configuration describes Anunna execution requirements.
- VIC and Slurm templates belong under `workflow/05_simulation/`.
- Resolved campaign and segment configuration, VIC configuration, and Slurm
  jobs belong with the corresponding run under
  `../workdir/runs/<campaign-id>/<run-id>/`.
- Production configuration must not rely on hidden scientific defaults.
- Do not distribute personal absolute paths across scripts or configuration.
  Resolve the workdir through `ISIMIP4B_WORKDIR`.

## Model version and builds

Treat a VIC-WUR version as frozen only when `model/vic.lock.yaml` identifies an
immutable full Git commit SHA. A moving branch name is not a frozen version.

Do not copy the VIC-WUR source tree into this repository. Store compiled
executables and build evidence under:

`../workdir/builds/vic/<model-commit>/`

Each production build must record its source commit, build environment, build
command, executable checksum, and test result.

## Runs, quality control, and delivery

Each run must have a stable run identifier and an isolated directory that
follows the canonical run layout. The run ID is the segment ID defined in
`docs/glossary.md`. The run must preserve the resolved configuration, exact VIC configuration, exact Slurm job, logs, states, raw
output, and run manifest.

A directory name is not evidence of successful quality control. Use explicit
statuses such as `passed`, `failed`, `warning`, and `not_checked`.

Do not place a product under `../workdir/delivery/` unless all mandatory checks
have passed and the product is represented in a delivery manifest.

## Language

All repository files and all generated documentation, configuration, scripts,
manifests, logs, reports, figures, tables, and result metadata must be written
in English. Chinese may be used only in direct conversation with the user.

## Tests and verification

Changes to production workflow code must include verification proportional to
their scientific and operational risk. Prefer small unit, integration, and
smoke tests over ad hoc manual evidence.

Before completing a task that creates or moves files:

1. run `python3 tests/check_layout.py --workdir` from the repository root and
   resolve every reported error; report any remaining warning to the user;
2. verify that every affected path follows `docs/directory-contracts.md`,
   including rules the layout check cannot verify;
3. verify that new documentation and metadata are in English;
4. run relevant tests or explain why they could not be run;
5. report any contract exception explicitly.

The layout check only reports. Do not rename, move, or delete data under
`../workdir/` to resolve a finding without user approval.

Do not bypass the pre-commit hook (`git commit --no-verify`) unless the user
explicitly asks for it.

## Safety

Do not delete, overwrite, or relocate large data collections without explicit
user authorization and pre-operation inventory checks. Prefer reversible,
incremental migrations with file-count, size, and checksum verification.

