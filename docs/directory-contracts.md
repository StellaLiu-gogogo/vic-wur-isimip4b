# Directory Contracts

## Purpose

This document is the authoritative specification for the VIC-WUR ISIMIP4b
directory hierarchy. It defines where files belong, which directory levels are
valid, which contents are allowed or forbidden, and how the hierarchy may
change.

All project contributors and coding agents must follow this contract before
creating, moving, renaming, copying, or generating files and directories.

Terms such as experiment, segment, chunk, campaign, and run are defined in
`glossary.md`.

## Quick reference

Read this table first, then only the sections you need. Read the whole
document when you change the project structure.

| I have… | It goes to | Section |
|---|---|---|
| production workflow code | `repo/workflow/<stage>/` | [`workflow/`](#workflow) |
| code used by two or more stages, or a listed infrastructure module | `repo/workflow/common/` | [`workflow/common/`](#workflowcommon) |
| analysis code (decision support; user decides) | `repo/analysis/<task-id>/` | [`analysis/`](#analysis) |
| a campaign definition | `repo/configs/campaigns/` | [`configs/`](#configs) |
| a downloaded source file | `workdir/raw/ISIMIP4b/…` or `workdir/raw/external/…` | [`raw/`](#raw) |
| a rebuildable cache written by workflow code | `workdir/intermediate/<stage>/<cache-id>/` | [`intermediate/`](#intermediate) |
| VIC-ready forcing (one unit per leaf directory, with `provenance.yaml`) | `workdir/forcing/<family>/…` | [`forcing/`](#forcing) |
| VIC parameters | `workdir/parameters/{candidates,production}/<set>/` | [`parameters/`](#parameters) |
| a model run | `workdir/runs/<campaign-id>/<run-id>/` | [`runs/`](#runs) |
| protocol-oriented model products | `workdir/postprocessed/<product-set-id>/…` | [`postprocessed/`](#postprocessed) |
| QC evidence | `workdir/qc/<object path>/` | [`qc/`](#qc) |
| analysis figures and tables | `workdir/analysis/<task-id>/` | [`analysis/`](#analysis-1) |
| a rendered Slurm job of a non-simulation stage and its output | `workdir/logs/<stage>/<job-name>_<slurm-job-id>/` | [`logs/`](#logs) |
| temporary files with no reuse value | `workdir/scratch/<task-id>/` | [`scratch/`](#scratch) |
| something that fits none of these | stop and propose a contract change | [Change procedure](#change-procedure) |

Deleting data: [Deletion permissions](#deletion-permissions). Backups:
[Data protection](#data-protection).

## Status vocabulary

Directory entries in this document use three lifecycle classes:

- **Required**: must exist in a usable project checkout.
- **Created when used**: created only when the corresponding maintained content
  exists. Do not pre-create speculative empty trees.
- **Dynamic**: created programmatically for a specific dataset, build, run,
  product, quality-control target, analysis, or delivery.

Angle-bracket names such as `<gcm>` and `<run-id>` are placeholders, not literal
directory names.

## Global hierarchy rules

1. Every directory level must represent a real and stable project dimension,
   ownership boundary, or lifecycle boundary.
2. Do not add a directory level with only one possible value unless that level
   provides an important lifecycle or access boundary.
3. Do not repeat information already established by the project root. For
   example, `workdir/forcing/` does not need an additional
   `isimip4b-vic-5arcmin/` level while this project has only one model and one
   production grid.
4. Use the same dimension order for all comparable datasets.
5. Do not organize scientific workflow code by programming language.
6. Do not organize production content by developer or agent name.
7. Do not use `v2`, `new`, `old`, `fix`, `fixed`, `final`, or `latest` as a
   versioning system.
8. Do not use dates as code versions. Dates are allowed when they are real
   audit, meeting, protocol, run, delivery, or scientific attributes.
9. Do not pre-create deep empty directory trees. Create **Created when used**
   and **Dynamic** paths only when real content requires them.
10. Static repository directories are created and reviewed manually. Dynamic
    workdir directories are created by the code that owns them: workflow
    code for production directories, analysis code for `analysis/`, and
    anyone for `scratch/`.
11. A new production directory pattern requires an approved update to this
    document before use.
12. Prefer two to five meaningful levels below a major directory. Add depth for
    stable semantics, not merely to hide a large unstructured collection.
13. Files and directories created by the project use ASCII names. Upstream
    names under `workdir/raw/` are kept exactly as delivered.
14. Reusable caches, accepted forcing, production parameter sets, production
    runs, postprocessed product sets, and deliveries are produced only from a
    clean repository (see `glossary.md`), and record the commit they were
    produced from. Outputs of a repository that is not clean go to
    `scratch/`.

Rules that can be checked automatically are enforced by
`tests/check_layout.py` (see [Automated layout check](#automated-layout-check)).

## Project roots

```text
isimip4b/
├── repo/
└── workdir/
```

- `repo/` is the version-controlled project repository.
- `workdir/` is the large-data and runtime area outside Git, on the
  non-backed-up filesystem `/lustre/nobackup/`.

The approved backup root for selected workdir content is outside the project
root, in `/lustre/backup/WUR/ESG/liu297/isimip4b/workdir/` (see
[Data protection](#data-protection)). No backup exists yet.

The complete project runs on Anunna.

## Repository hierarchy

```text
repo/
├── .githooks/
│   └── pre-commit
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── analysis/
│   ├── README.md
│   └── <task-id>/
├── configs/
│   ├── campaigns/
│   └── resources/
├── docs/
│   ├── README.md
│   ├── glossary.md
│   ├── directory-contracts.md
│   ├── architecture.md
│   ├── workflow.md
│   ├── experiment-matrix.md
│   ├── runbook.md
│   ├── decisions/
│   │   └── open-decisions.md
│   └── audits/
├── environments/
├── manifests/
│   ├── code-equivalence.yaml
│   ├── inputs/
│   ├── parameters/
│   ├── runs/
│   └── deliveries/
├── model/
│   └── vic.lock.yaml
├── tests/
│   ├── check_layout.py
│   ├── unit/
│   ├── integration/
│   ├── smoke/
│   └── fixtures/
└── workflow/
    ├── common/
    ├── 01_acquisition/
    ├── 02_preprocessing/
    ├── 03_parameters/
    ├── 04_forcing/
    ├── 05_simulation/
    ├── 06_postprocessing/
    ├── 07_quality_control/
    └── 08_delivery/
```

### Required repository paths

- `.githooks/pre-commit`
- `.gitignore`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `analysis/README.md`
- `configs/`
- `docs/README.md`, `docs/glossary.md`, `docs/directory-contracts.md`,
  `docs/decisions/open-decisions.md`
- `environments/`
- `manifests/`
- `model/`
- `tests/check_layout.py`
- `workflow/`
- the eight numbered workflow stage directories

`CLAUDE.md` imports `AGENTS.md` and must not duplicate its content.

### Created-when-used repository paths

- `analysis/<task-id>/`
- `docs/architecture.md`, `docs/workflow.md`, `docs/experiment-matrix.md`,
  `docs/runbook.md`
- `docs/decisions/<id>-<short-title>.md` (decision records)
- `docs/audits/`
- `tests/unit/`
- `tests/integration/`
- `tests/smoke/`
- `tests/fixtures/`
- `workflow/common/`
- component directories described below

## Repository contracts

### `.githooks/` and `.gitignore`

`.githooks/pre-commit` runs `tests/check_layout.py` on the repository before
every commit. Each clone activates it once with:

```bash
git config core.hooksPath .githooks
```

`.gitignore` keeps generated data, logs, caches, and build products out of Git.
It is a first line of defence, not a substitute for the layout check.

### `analysis/`

Canonical layout:

```text
analysis/
├── README.md
└── <task-id>/
    ├── README.md
    └── <source files>
```

An analysis answers a question or supports a decision. Its product is a
conclusion, comparison, figure, or report, not an input to a production stage.
Examples: comparison of irrigated-area datasets, a trial of a land-use
harmonization method, a review of an external dataset.

Classification between `analysis/` and `workflow/` is decided by the user, as
defined in `analysis/README.md`. Code whose output is read by a workflow stage,
or which must be re-run to reproduce a production result, belongs in
`workflow/`.

Each `<task-id>/README.md` records the question, the user's classification
decision, the status (`open`, `closed`, or `promoted`), the conclusion, and the
location of the maintained record of that conclusion in `docs/audits/` or
`docs/decisions/`.

Allowed: source code, small configuration, small tables, and the task README.

Forbidden: generated data, figures, and logs (these belong under
`workdir/analysis/<task-id>/`), and code imported by `workflow/`.

`<task-id>` is a short descriptive lowercase identifier of the question, e.g.
`irrigated-area-comparison`. The same `<task-id>` is used under
`workdir/analysis/`.

### `configs/`

Canonical layout:

```text
configs/
├── campaigns/
└── resources/
```

- `campaigns/` contains one structured definition per campaign.
- `resources/` contains Anunna resource requests organized by workload type or
  scale.

A campaign definition states the model build, parameter set, ISIMIP protocol
commit, GCMs, and the selection of experiments to simulate (for example all
`water_global` experiments of a given priority), together with any explicit
exclusions and their justification. It does not list segments. The segments,
their periods, and their parent segments are derived by workflow code from the
experiment definitions of the pinned protocol commit and are saved in the
resolved configuration of each run.

A campaign may declare that segments of whole periods are reused from one
earlier accepted production campaign instead of being simulated again, e.g.
spin-up, pre-industrial, and historical segments when only the future period
changes. The declaration names the source campaign, the reused periods, and a
justification of why the change does not affect them. Reused runs stay in the
source campaign's directory and are referenced, not copied; the resolved
configuration of each dependent run records the source run path. Reuse is
never implicit. The configuration keys are defined when campaign resolution
is implemented.

Allowed: YAML configuration, schemas when introduced, and directory
documentation.

Forbidden: hand-maintained segment lists, generated VIC files, generated Slurm
jobs, scientific data, logs, credentials, and personal path configuration
committed as production policy.

There is no `defaults/` directory unless a reviewed configuration-resolution
system is introduced and every run preserves a complete resolved configuration.

### `docs/`

Maintained project documentation belongs here. `glossary.md` is the canonical
terminology source. `directory-contracts.md` is the canonical path-placement
source.

Allowed: Markdown, small maintained diagrams, and small evidence required to
understand a maintained document.

Forbidden: raw data, model output, large generated figures, temporary review
artifacts, and undocumented copies of external documents.

### `environments/`

Contains reproducible environment definitions, lock files, Anunna module
requirements, and environment verification instructions.

Forbidden: installed environments, caches, personal activation scripts,
credentials, and generated build directories.

### `manifests/`

Canonical layout:

```text
manifests/
├── code-equivalence.yaml
├── inputs/
├── parameters/
├── runs/
└── deliveries/
```

- `code-equivalence.yaml` records result-neutral changes of producing code
  (see "Forcing unit and provenance record"); created when used.

- `inputs/` records accepted external dataset identity and integrity.
- `parameters/` records accepted parameter-set identity and provenance.
- `runs/` may contain concise summaries of formally accepted production runs.
- `deliveries/` records delivered products, source runs, checksums, quality
  status, protocol identity, and destination.

The complete run manifest remains under
`workdir/runs/<campaign-id>/<run-id>/`. Debug, trial, failed, and routine run
manifests do not need Git copies.

Allowed: YAML, JSON, CSV, TSV, checksum lists, schemas, and documentation.

Forbidden: the scientific data referenced by a manifest and manually altered
checksums or file counts.

### `model/`

Contains the VIC-WUR version lock and model-version documentation.

Forbidden: copied VIC-WUR source trees, compiled executables, build trees, and
model output.

The lock must use an immutable full Git commit SHA for a frozen production
version. A moving branch name is insufficient.

### `tests/`

Canonical layout:

```text
tests/
├── check_layout.py
├── unit/
├── integration/
├── smoke/
└── fixtures/
```

`check_layout.py` is the automated layout check. The subdirectories are
created when used.

Small fixtures may be committed when their source and purpose are documented.
Large production datasets and generated test products are forbidden.

### `workflow/`

Workflow code is organized by scientific and operational stage, not by
language, developer, GCM, scenario, or date.

Allowed: source code, small source-controlled mappings, schemas, templates,
Slurm templates, tests local to a stage when justified, and documentation.

Forbidden: generated scientific data, logs, caches, executables, model states,
personal notebooks, and any reference to `analysis/` or `workdir/analysis/`.

#### `workflow/common/`

Shared Python modules used by two or more workflow stages, for example workdir
path resolution, grid utilities, NetCDF metadata handling, checksum and
manifest writing, and map plotting, and the project infrastructure modules
listed below.

Admission: code belongs in `common/` when either condition holds:

1. at least two stages use it; or
2. it implements a project-wide rule of this contract and is listed as an
   infrastructure module below. Such a module is created in `common/` when
   its first user needs it, never first inside a stage.

Infrastructure modules:

| Module | Implements |
|---|---|
| `cache.py` | the `intermediate/` cache rules: cache creation, fingerprinting, Git-state checks, `cache.yaml`, and `_SUCCESS` |

Adding an infrastructure module requires a change to this table first.

Rules:

- `common/` contains no stage-specific logic and no executable entry points;
- `common/` defines no path under `analysis/`; analysis code resolves its own
  directories;
- modules are flat files in `common/`; do not add a language or package layer;
- workflow code imports it as `from common import <module>` with
  `PYTHONPATH` including `repo/workflow`, as defined in `environments/`.

#### `workflow/03_parameters/`

Create component directories only when implementation exists:

```text
03_parameters/
├── bundle/
├── domain/
├── soil/
├── vegetation/
├── landuse/
├── routing/
├── dams/
├── irrigation/
└── water_use/
```

Each component directory may contain its canonical generation and validation
code, small mappings, Slurm templates, tests, and README. Do not add a language
layer such as `python/` or `shell/`. `bundle/` assembles the image-driver
parameter file of the `bundle` component from other components.

#### `workflow/04_forcing/`

Create forcing-family directories only when implementation exists:

```text
04_forcing/
├── climate/
├── landuse/
└── water_use/
```

VIC-WUR has no CO₂-dependent process; there is no CO₂ forcing family.

Do not copy common transformation code for individual GCMs or scenarios.

#### `workflow/05_simulation/`

Create responsibility directories only when implementation exists:

```text
05_simulation/
├── build/
├── render/
├── submit/
├── monitor/
└── templates/
    ├── vic/
    └── slurm/
```

- `build/` builds or verifies the model executable.
- `render/` resolves a campaign into segments, resolves each run
  configuration, and renders exact run files.
- `submit/` creates dependencies and submits jobs.
- `monitor/` inspects scheduler and model status without changing scientific
  results.
- `templates/vic/` stores VIC configuration templates.
- `templates/slurm/` stores Slurm job templates.

Generated configurations and jobs belong with the dynamic run, not here.

## Workdir hierarchy

```text
workdir/
├── README.md
├── raw/
├── intermediate/
├── parameters/
├── forcing/
├── builds/
├── runs/
├── postprocessed/
├── qc/
├── delivery/
├── analysis/
├── logs/
└── scratch/
```

These top-level workdir paths are required. Their child paths are dynamic and
must be created only when used.

## Workdir contracts

### `raw/`

Canonical layout:

```text
raw/
├── ISIMIP4b/
│   └── <DKRZ path below ISIMIP4b/, unchanged>
└── external/
    └── <dataset-id>/
        └── <dataset-version>/
```

- `ISIMIP4b/` mirrors the DKRZ ISIMIP4b tree exactly, including directory
  names, capitalisation, and filenames, e.g.
  `raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily/esm-hist/EC-Earth3-ESM-1-1/`.
  Only the subset required by the project is present.
- `external/` holds data that do not come from the ISIMIP DKRZ tree, e.g. the
  ISIMIP protocol repository at a pinned commit or a third-party dataset used
  for comparison.

Raw files are immutable: while a file is present, its path and content never
change. Do not rename, rewrite, reformat, subset, or repair raw files in place.
Store transformations under `parameters/` or `forcing/`, and reusable caches of
transformation steps under `intermediate/`.

Immutability does not mean permanence. A raw file may be deleted to recover
space when all of the following hold:

- the accepted input manifest records its path, size, and checksum;
- the same file remains available from its source, so it can be downloaded
  again;
- the user has authorized the deletion, as defined in
  [Deletion permissions](#deletion-permissions).

A re-downloaded file must be restored to the same path and must match the
recorded checksum. A file with different content is a different dataset
version and must not be placed at the old path; it requires an updated input
manifest.

### `intermediate/`

Canonical layout:

```text
intermediate/
└── <producer-stage>/
    └── <cache-id>/
        ├── cache.yaml
        ├── data/
        └── _SUCCESS
```

The cache root contains only `cache.yaml`, `_SUCCESS`, and the `data/`
directory. All cached content, including small indexes or lookup tables, goes
into `data/`, whose internal structure is chosen by the producer. Any further
fixed metadata file in the cache root requires a change to this contract
first.

> Intermediate is a rebuildable performance cache, never a scientific product
> or a storage destination.

#### Purpose

This directory contains reproducible workflow caches only. A cache is an
optimization: deleting it costs compute time and nothing else.

Every cache must be reproducible from version-controlled workflow code,
recorded configuration and parameters, and upstream data that either remains
available or can be downloaded again using the referenced input manifest.

**Deleting a cache never loses information.** This directory is not backed
up and does not take part in delivery. Who may delete a cache is defined in
[Deletion permissions](#deletion-permissions).

| Situation | Directory |
|---|---|
| Disposable, no reuse value | `scratch/` |
| Disposable, expensive to compute, reusable | `intermediate/` |
| Accepted forcing | `forcing/` |
| Model parameters | `parameters/` |
| Model runs and restart states | `runs/` |
| Postprocessed products | `postprocessed/` |
| Trials, comparisons, and decision support | `analysis/` |

#### Identifiers

- `<producer-stage>` is the full name of the workflow stage whose code
  created the cache, e.g. `04_forcing`.
- `<cache-id>` uses lowercase letters, digits, hyphens, and underscores, and
  describes the transformation and target, e.g.
  `climate-regridding_ec-earth3-esm-1-1_esm-hist_prec`. It must not contain a
  version label or a manual date.

#### Producers

- Caches are written only by a workflow producer under `workflow/`, through
  the common cache writer. The producer may be started by anyone and in any
  way: from a terminal, through Slurm, or by a coding agent. The
  `rebuild_command` is exactly such an invocation.
- Forbidden ways of writing a cache: placing or changing files directly
  (`cp`, `mv`, `rsync`, `ln`, editors); ad hoc Python or shell commands,
  notebooks, or analysis code; and any code that bypasses the common cache
  writer.
- Before reuse, a producer may replace the one cache it is about to use when
  the fingerprint does not match or `_SUCCESS` is missing. It touches no
  other cache. A rebuild never deletes in place: the producer builds the new
  cache in a staging location, then renames the old cache directory away and
  the new one into place, so that a running job that still holds the old
  files open is not disturbed. The renamed-away directory is removed by the
  producer once it is no longer in use.
- A producer checks the Git state before it starts. Unless the repository is
  clean as defined in `glossary.md` (`git status --porcelain` prints nothing),
  it must write to `scratch/` or stop. Outputs of a repository that is not
  clean are never reusable caches.
- A producer writes `data/` and `cache.yaml` completely (flushed to disk)
  first and creates `_SUCCESS` last as an empty file with an exclusive create
  (`O_CREAT | O_EXCL`), which is atomic and leaves no temporary file in the
  cache root.
- Cache creation, fingerprinting, Git-state checks, and `_SUCCESS` handling
  (the common cache writer)
  are implemented once in the infrastructure module `workflow/common/cache.py`
  when the first producer needs them (see `workflow/common/`).

#### `cache.yaml`

```yaml
cache_id: climate-regridding_ec-earth3-esm-1-1_esm-hist_prec
cache_fingerprint: <sha256>

producer_stage: 04_forcing
created_by: workflow/04_forcing/climate/downscale_climate.py
code_commit: 0123456789abcdef0123456789abcdef01234567
code_dirty: false
created_at: 2026-09-28T14:30:00Z

input_manifest: manifests/inputs/example.yaml

inputs:
  - raw/ISIMIP4b/InputData/...

rebuild_command: >-
  python3 workflow/04_forcing/climate/downscale_climate.py
  --manifest manifests/inputs/example.yaml

campaign_config: configs/campaigns/example.yaml

final_destination:
  - forcing/climate/ec-earth3-esm-1-1/esm-hist/prec
```

| Key | Requirement |
|---|---|
| `cache_id` | Required; equals the directory name. |
| `cache_fingerprint` | Required; SHA-256 defined below. |
| `producer_stage` | Required; equals the parent directory name. |
| `created_by` | Required; a path under `workflow/`. If the file no longer exists in the repository, the cache is stale and is never reused (reported as a warning). |
| `code_commit` | Required; full 40-character Git commit, for provenance. |
| `code_dirty` | Required; must be `false`, i.e. the repository was clean. |
| `created_at` | Required; UTC ISO 8601. |
| `inputs` | Required; paths relative to the workdir. |
| `rebuild_command` | Required; run from the repository root. |
| `input_manifest` | Required when the inputs are covered by a manifest; an existing file under `manifests/inputs/`. |
| `campaign_config` | Optional; an existing file under `configs/campaigns/`. Omit the key when the cache does not depend on a campaign. |
| `final_destination` | Optional; workdir paths of the products built from this cache, never under `intermediate/`. Omit the key when the cache is only reused by its producer. |

There is no `status` key; completeness is expressed only by `_SUCCESS`.

#### Fingerprint and reuse

*Design status: the fingerprint composition below is specified before
`workflow/common/cache.py` exists. It is refined through the change procedure
when the module is implemented. The directory boundaries and producer rules
above are binding now.*

The producer computes `cache_fingerprint` as the SHA-256 of:

- `created_by`;
- the Git tree hashes of `workflow/<producer-stage>/`, `workflow/common/`,
  and `environments/` (so that commits which do not touch the producing code
  or its software environment keep caches valid);
- the content or checksum of the input manifest and of every input not
  covered by it;
- the effective parameters;
- the result-relevant part of the campaign configuration;
- the cache format version declared by the producer.

A workflow reuses a cache only when the requested fingerprint equals the
recorded fingerprint **and** `_SUCCESS` exists. Otherwise it rebuilds the
cache as described under Producers (never by deleting in place). Cache
validity never depends on file names or manual judgement.

#### Validation results

Results of validating a cache have exactly three possible locations:

| Kind | Location |
|---|---|
| Structured results that downstream code reads to decide whether the cache is usable | inside the cache under `data/`, written before `_SUCCESS` |
| Human-readable or standalone QC evidence | `qc/intermediate/<producer-stage>/<cache-id>/`, whose `summary.json` records the `cache_fingerprint` it refers to |
| Routine run information | `logs/<producer-stage>/` |

Validation results are cache content, not fingerprint inputs: the fingerprint
is computed before the cache is built and never depends on its own outputs.
QC evidence whose `cache_fingerprint` differs from the current cache refers to
an earlier cache and must not be used for the current one.

#### Forbidden

- manually created or manually edited data;
- the only copy of any file;
- accepted forcing, parameter, simulation, postprocessing, or delivery
  products and delivery candidates;
- audit or analysis evidence that cannot be regenerated;
- files without an identifiable producing workflow;
- files placed here because their proper destination is unclear;
- version suffixes such as `_v2` or `_final` and date-based manual copies;
- manifests that reference `intermediate/` as an input or delivered object.

Uncertainty about file classification is not a valid reason to place a file
in `intermediate/`.

### `parameters/`

Canonical layout:

```text
parameters/
├── candidates/
│   └── <parameter-set-id>/
│       └── <component>/
└── production/
    └── <parameter-set-id>/
        └── <component>/
```

Valid components are the component directories listed under
`workflow/03_parameters/` above, whether their files are generated there or
adopted. The `bundle` component holds VIC image-driver parameter files that
combine several components (soil, vegetation, snow bands) in one file: adopted,
already assembled files, and the file assembled by
`workflow/03_parameters/bundle/`. Files read by a plugin through another
plugin's option stay in that plugin's component (the FILE decomposition read
by the routing plugin is in `routing/`). Files copied into a parameter set follow the workdir
naming rules; when an upstream name contains a version-like token, the copy
is renamed and the manifest records the source path and name. Promotion from `candidates/` to `production/` must
be explicit, reproducible, and supported by quality-control evidence and an
accepted parameter manifest.

A parameter set may also be **adopted** from a recorded external source, such
as the sibling `vic_parameter` project, instead of being generated by
`workflow/03_parameters/`. For an adopted set, reproducible means that the
parameter manifest records the source location, source version or commit,
and the checksum of every file, so that the identical files can be obtained
again; the files are copied, never linked, and are treated like any other
candidate until promoted.

Do not represent parameter versions with `v2`, `fix`, `final`, or similar
names. Use a meaningful parameter-set identifier and manifest provenance.

### `forcing/`

Canonical layout:

```text
forcing/
├── climate/
│   └── <gcm>/
│       └── <climate-scenario-input-alias>/
│           └── <variable>/
├── landuse/
│   └── <soc-scenario>/
└── water_use/
    └── <soc-scenario>/
```

Examples:

```text
forcing/climate/ec-earth3-esm-1-1/esm-picontrol/prec/
forcing/climate/ec-earth3-esm-1-1/esm-hist/tair/
forcing/climate/ukesm1-3-ll/esm-hist/prec/
forcing/landuse/histsoc/
forcing/landuse/ssp3hsoc-noadapt/
```

Rules:

- the first level identifies the forcing family (`climate`, `landuse`,
  `water_use`);
- climate forcing is organized by GCM, then climate-scenario input alias as
  used in the DKRZ path (e.g. `esm-hist`, see `glossary.md`), then variable;
- the climate variable level uses the VIC-WUR forcing variable names `tair`,
  `prec`, `psurf`, `vp`, `swdown`, `lwdown`, and `wind`, because the products
  are VIC variables and `vp` has no ISIMIP counterpart; the ISIMIP source
  variables of each unit are recorded in its `provenance.yaml`
  (`method.source_variables`);
- DHF forcing is organized by soc scenario;
- use official lowercase identifiers;
- apply the same dimension order to every GCM and scenario;
- do not add a redundant project, model, or grid level while only one model and
  production grid exist;
- record grid, method, workflow commit, and acceptance status in the
  provenance record defined below, not in ad hoc version directories.

The climate variable level may be omitted only if each scenario contains a
small number of files and the decision is applied consistently to every GCM and
scenario. Changing this choice requires updating this contract first.

#### Forcing unit and provenance record

A **forcing unit** is one leaf directory of the layout above: one
`climate/<gcm>/<alias>/<variable>/` or one `landuse/<soc-scenario>/` or
`water_use/<soc-scenario>/` directory. It is the unit that is generated,
validated, accepted, and referenced by runs.

Every forcing unit contains a `provenance.yaml` written by the workflow code
that generated it, next to the data files:

```yaml
forcing_unit: climate/ec-earth3-esm-1-1/esm-hist/prec
created_by: workflow/04_forcing/climate/downscale_climate.py
code_commit: 0123456789abcdef0123456789abcdef01234567
code_dirty: false
created_at: 2026-10-05T09:12:00Z
input_manifest: manifests/inputs/example.yaml
inputs:
  - raw/ISIMIP4b/InputData/climate/atmosphere/...
method:
  target_grid: vic-5arcmin
  source_variables: [pr]
  interpolation: conservative
  mask: <mask identifier>
caches:
  - intermediate/04_forcing/<cache-id>
qc:
  status: not_checked
  evidence: qc/forcing/climate/ec-earth3-esm-1-1/esm-hist/prec
```

| Key | Requirement |
|---|---|
| `forcing_unit` | Required; equals the unit's path below `forcing/`. |
| `created_by`, `code_commit`, `code_dirty`, `created_at` | Required; same meaning and format as in `cache.yaml`. `code_dirty` must be `false`. |
| `input_manifest` | Required when the inputs are covered by a manifest; an existing file under `manifests/inputs/`. |
| `inputs` | Required; workdir-relative paths of the raw inputs, so that the unit stays traceable after raw files are deleted. |
| `method` | Required; the parameters that determine the result (grid, interpolation, masks, unit conversions, calendar handling). |
| `caches` | Optional; caches used, for information only. A forcing unit never depends on a cache remaining present. |
| `qc.status` | Required; `not_checked`, `passed`, `warning`, or `failed`, updated only by quality-control code. |
| `qc.evidence` | Required when `qc.status` is not `not_checked`; the unit's directory under `qc/`. |

A forcing unit is **accepted** when its `provenance.yaml` exists, records
`code_dirty: false`, and has `qc.status: passed`. Only accepted forcing units
are used by production runs; the resolved configuration of a run records the
`forcing_unit`, `code_commit`, and `created_at` of every unit it reads.

A forcing unit is regenerated only as a whole: the workflow writes the new
unit completely, including its `provenance.yaml`, before it replaces the old
one, and replacing an accepted unit requires user authorization as defined in
[Deletion permissions](#deletion-permissions). Data files in a unit are never
edited in place.

A unit made of one file per year may instead be **extended** with years it
does not yet contain, without regenerating it, when all of the following
hold (checked by the producer, which stops otherwise):

1. the fingerprint of the producing code is unchanged: the Git tree hashes of
   the producer's directory under `workflow/` and of `workflow/common/` equal
   the values recorded in `provenance.yaml`, or a chain of entries of the
   code-equivalence record (below) leads from the recorded to the current
   hashes; the method version declared by the producer equals the recorded
   one in either case; and the repository is clean;
2. every input used by the existing files that is used again (static inputs
   such as the domain, parameter files, and reference datasets, and source
   files shared with existing years) has the SHA-256 recorded in
   `provenance.yaml`, and every new source file matches its input manifest;
3. the versions of the key software recorded in `provenance.yaml` are
   unchanged.

Existing data files are not touched, not even rewritten with identical
content. The producer verifies their recorded SHA-256 before adding files,
writes the new files completely, and then rewrites `provenance.yaml`, the
only file of the unit that changes, with one entry per data file (year,
size, SHA-256, `created_at`, `code_commit`) and `qc.status: not_checked`,
until quality-control code has checked the extended unit. Extending an
accepted unit requires user authorization.

**Code-equivalence record.** A change of the producing code that leaves
every result unchanged (moving code to `workflow/common/`, documentation)
changes the tree hashes all the same. Such a change is recorded in
`manifests/code-equivalence.yaml`, outside the hashed directories, so that
existing units can still be extended. One entry per change and producer:

```yaml
equivalences:
  - id: common-modules-climate
    producer: workflow/04_forcing/climate/downscale_climate.py
    method_version: '1.1'
    from: {workflow/04_forcing/climate: <tree>, workflow/common: null}
    to: {workflow/04_forcing/climate: <tree>, workflow/common: <tree>}
    change: <one line>
    evidence: <the test: producer run before and after on the same commit base, inputs, years, result>
    approved: <user, date>
```

An entry is added in the same commit as the code change, only after a test
of the producer before and after the change on the same inputs gave data
files whose variables and attributes are identical except `created_at` (and
the commit and Git state attributes when those differ), and only with the
user's approval. Entries are never edited or removed; the `to` hashes are
those of the commit that adds the entry. A unit extended under the record
lists the entries used in its `extended` record (`code_equivalence`).

The same global attributes (`code_commit`, `created_by`, `created_at`,
`forcing_unit`) are also written into every NetCDF file of the unit, so that
a file copied elsewhere still identifies its origin.

### `builds/`

Canonical layout:

```text
builds/
└── vic/
    └── <model-commit>/
        ├── bin/
        ├── logs/
        ├── tests/
        └── build_manifest.json
```

`<model-commit>` must uniquely identify the source commit. Do not use
`current`, `latest`, `final`, or a branch name as a build identity.

The build manifest must record the full model commit, build environment, build
command, executable checksum, and test status.

### `runs/`

Canonical layout:

```text
runs/
└── <campaign-id>/
    └── <run-id>/
        ├── config/
        ├── logs/
        ├── states/
        ├── output/
        ├── forcing/
        └── run_manifest.json
```

- `<campaign-id>` identifies the campaign defined in `configs/campaigns/`.
- `<run-id>` is the segment ID defined in `glossary.md`:
  `<climate-forcing>_<climate-scenario>_<soc-scenario>_<sens-scenario>_<period>`.
  Runs of non-production campaigns (smoke, debug, trial) that cover only part
  of a segment's domain or period append a label: `<segment-id>__<label>`,
  e.g. `ec-earth3-esm-1-1_historical_histsoc_default_historical__rhine-3yr`.
  Production runs never carry a label.

`config/` must preserve the resolved campaign and segment configuration, the
exact VIC configuration, and the exact Slurm job used for the run.

`forcing/` is the run's forcing view: `forcing/<family>/` (`climate/<variable>/`,
`landuse/`, `water_use/`) contains only relative symbolic links named by
simulation year that point to files of accepted forcing units, because VIC
opens forcing files by `<prefix><year>.nc`. A link may point to a file of
another year (constant DHF scenarios, spin-up climate cycle); the mapping of
every year is recorded in `run_manifest.json`. Units are never copied or
modified for a run. The view is created by
`workflow/05_simulation/render/` and is not backed up.

If one run is split into chunks, use:

```text
runs/<campaign-id>/<run-id>/
├── run_manifest.json
└── chunks/
    └── <start-year>-<end-year>/
        ├── config/
        ├── logs/
        ├── states/
        ├── output/
        └── forcing/
```

Do not create `run_fix`, `run_final`, or similar replacement directories.
Changed scientific or computational identity requires a new campaign, which
may reuse unaffected parent segments as defined in [`configs/`](#configs).
A scheduler retry with identical identity remains associated with the same run
manifest and records the additional attempt.

### `postprocessed/`

Canonical layout:

```text
postprocessed/
└── <product-set-id>/
    └── <gcm>/
        └── <experiment-id>/
            └── <variable>/
```

This directory contains derived products that are not yet formal delivery
products. `<experiment-id>` is the ISIMIP experiment ID. Every product set must
remain traceable to its source runs and postprocessing workflow commit.

Use the same GCM, experiment, and variable ordering throughout a product set.

### `qc/`

Canonical layout:

```text
qc/
└── <object path relative to the workdir>/
    ├── summary.json
    ├── reports/
    ├── figures/
    └── logs/
```

The QC directory of an object is `qc/` followed by the object's own workdir
path, so it can never collide and always shows what was checked:

```text
qc/runs/fasttrack/ec-earth3-esm-1-1_historical_histsoc_default_historical/
qc/runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__rhine-3yr/
qc/forcing/climate/ec-earth3-esm-1-1/esm-hist/prec/
qc/parameters/production/<parameter-set-id>/
qc/intermediate/04_forcing/<cache-id>/
```

The first level is therefore one of the workdir top-level directories `raw`,
`intermediate`, `parameters`, `forcing`, `builds`, `runs`, `postprocessed`, or
`delivery`.

Use explicit statuses including `passed`, `failed`, `warning`, and
`not_checked`. A path under `qc/` is not proof that checks passed.

### `delivery/`

Canonical layout:

```text
delivery/
└── <delivery-id>/
    ├── files/
    ├── inventory.tsv
    ├── checksums.sha256
    ├── qc-summary.json
    └── delivery-manifest.yaml
```

Only products that satisfy all mandatory quality-control requirements may be
placed under `files/`. The delivery manifest must identify source runs,
workflow and model versions, protocol identity, quality-control evidence, file
inventory, checksums, status, and destination.

Do not overwrite an existing delivery identity. A materially changed delivery
requires a new reviewed delivery identity.

### `analysis/`

Canonical layout:

```text
analysis/
└── <task-id>/
```

Generated data, figures, tables, and logs of the analysis task with the same
`<task-id>` under `repo/analysis/`. Source code is never stored here, with
one exception: a Slurm job of the analysis keeps its job record in
`logs/<job-name>_<slurm-job-id>/` inside the task directory, with the exact
rendered `job.sbatch` and the scheduler output, as the job records of the
workflow stages do under `workdir/logs/` (the code that renders it stays in
`repo/analysis/<task-id>/`).

No workflow stage may read from this directory. A result that a production
stage needs must be produced by workflow code.

### `logs/`

Canonical layout:

```text
logs/
└── <workflow-stage>/
    ├── <log files of interactive executions>
    └── <job-name>_<slurm-job-id>/
        ├── job.sbatch
        ├── job.yaml
        ├── slurm-<slurm-job-id>.out
        └── slurm-<slurm-job-id>.err
```

`<workflow-stage>` is the full stage directory name, e.g. `01_acquisition`.

Use this directory for centralized logs not already owned by a build, run,
quality-control target, analysis, or delivery. Run-specific logs belong with
the run; build-specific logs belong with the build.

**Job records.** Every Slurm job of a stage other than `05_simulation` keeps
its exact rendered job script and its scheduler output in one job record
directory `<job-name>_<slurm-job-id>/`, never in `scratch/`. `<job-name>` is
lowercase words joined by hyphens and describes the task, e.g.
`climate-regrid-ec-earth3-esm-1-1-esm-hist-pr`. A resubmission gets a new
Slurm job ID and therefore a new job record; records are never overwritten.
`job.sbatch` is rendered from a template under `workflow/`, which remains the
source of truth. `job.yaml` records at least the Slurm job ID, the rendering
workflow script, the code commit and `code_dirty`, the submission time (UTC),
the inputs, and the output paths. Simulation jobs are recorded with their run
under `runs/`; model build jobs are recorded under
`builds/vic/<model-commit>/logs/`.

Logs do not replace manifests or structured status records.

### `scratch/`

Canonical layout:

```text
scratch/
└── <task-id>/
```

Scratch is a disposable temporary workspace with no reuse value. It may
contain temporary working files, exploratory trial outputs, and outputs of a
repository that is not clean. Nothing in scratch is reused: no workflow stage
reads from scratch, and reusable results belong in `intermediate/` as defined
above. Scratch content must never be required for production reproducibility.
Code in scratch is temporary; it is promoted to the repository or deleted
before the task is complete. Who may delete scratch content is defined in
[Deletion permissions](#deletion-permissions).

Do not organize shared production content by agent or developer name. If an
owner must be recorded for cleanup, record it in task metadata rather than as
the primary scientific hierarchy.

## Deletion permissions

Whether deleting something loses information is a property of the data.
Whether someone may delete it is a permission. This section defines the
permission for the whole workdir and the backup copy; `AGENTS.md` applies it
to coding agents.

| Who | What | User authorization |
|---|---|---|
| The user | anything | not needed |
| A workflow producer | the one cache it is about to rebuild, when the fingerprint does not match or `_SUCCESS` is missing (replaced by rename, never deleted in place) | not needed |
| A coding agent | `scratch/<task-id>/` of its own current task, at the end of that task | not needed |
| A coding agent | anything else, including caches, other scratch tasks, analysis products, raw files, and anything in the backup copy | required |

When authorization is required, the agent first presents the paths, file
counts, and sizes to be deleted and deletes only after the user approves that
list. Raw files additionally require the conditions in [`raw/`](#raw).

Never delete a cache or run directory that a running job may be reading.

## Data protection

`/lustre/nobackup/` is not backed up but is not purged automatically. The Git
repository is protected by its GitHub remote.

### Status

The approved backup root is
`/lustre/backup/WUR/ESG/liu297/isimip4b/workdir/`, inside the user's existing
directory `/lustre/backup/WUR/ESG/liu297/`. It is created when the first
production object is backed up. The backup procedure is not yet implemented,
so **no workdir content is currently backed up**. Update this status when the
procedure becomes operational.

### Backup copy

```text
/lustre/backup/WUR/ESG/liu297/isimip4b/
├── workdir/<same relative path as in the workdir>
└── staging/<staging-id>/
```

The backup copy uses the same relative paths as the workdir, and its
protected content equals the selected workdir content at the time of
copying. It is a backup, not a
mirror: a protected backup object may outlive or restore its workdir object,
and it is never deleted or changed because the workdir object was deleted or
changed. `staging/` holds objects that are being copied and have not been
published. The `workdir/` root is available to workflow code as
`ISIMIP4B_BACKUP`.

A **backup object** is one directory-level unit that is copied and published
atomically. There are exactly five kinds, listed in the table below.

### What is backed up

Only content of formally accepted production campaigns and parameter sets.
Smoke, trial, debug, and failed runs are never backed up.

| Backup object | Object root | Selected content |
|---|---|---|
| One production parameter set | `parameters/production/<parameter-set-id>/` | the whole directory |
| One accepted production run | `runs/<campaign-id>/<run-id>/` | `config/`, `states/`, `run_manifest.json`, and `config/` and `states/` of every `chunks/<start-year>-<end-year>/` |
| One production build | `builds/vic/<model-commit>/` | the whole directory |
| One postprocessed product set | `postprocessed/<product-set-id>/` | the whole directory |
| One delivery | `delivery/<delivery-id>/` | the whole directory. Once upload to DKRZ is confirmed, DKRZ holds the reference copy and the user may delete the backup object |

A run backup deliberately excludes `output/` and `logs/`, also inside
chunks. Raw model output is reproducible from the backed-up configuration,
states, build, and parameters; the postprocessed products are the protected
form of the model results.

Never backed up: `raw/`, `intermediate/`, `forcing/`, `parameters/candidates/`,
`qc/`, `analysis/`, `logs/`, `scratch/`, and non-production runs.

### How content is backed up

*Design status: this procedure is specified before any backup code exists. It
is refined through the change procedure when the backup procedure is
implemented. What is backed up and the permissions are binding now.*

- No scientific processing or primary project work occurs in the backup area.
  Only copied payload, copied manifests, checksums, and staging metadata are
  created there, and only by the backup procedure.
- An object is copied only after it is complete and accepted, and each backed
  up object is treated as write-once: existing files in the backup copy are
  never modified. A changed object gets a new identity in the workdir first.
- Each object is backed up in a staging, verify, publish sequence, so that a
  published object never changes afterwards:
  1. copy the payload (the selected content of the object except its
     manifest) to `staging/<staging-id>/`;
  2. verify every staged payload file against the workdir;
  3. record the backup path, date, and payload verification result in the
     object's manifest (see below for where each manifest lives);
  4. if the manifest lives inside the object, copy the final manifest into
     staging; a manifest that lives in the repository is committed instead;
  5. write `backup-checksums.sha256` in the staged object, covering the
     payload and, when present, the final manifest, but not itself, and
     verify it;
  6. publish by renaming the staged object to its final path under
     `workdir/`. Publishing never replaces an existing object.
- If any step fails, the final object must not appear, and the backup entry
  added in step 3 is removed from the workdir manifest. The staged object
  remains for recovery; removing it follows
  [Deletion permissions](#deletion-permissions).
- The manifest of an object is: `run_manifest.json` for a run,
  `build_manifest.json` for a build, and `delivery-manifest.yaml` for a
  delivery. A parameter set's manifest is in `manifests/parameters/` in the
  repository; it records the backup there, is protected by Git, and is not
  copied. A postprocessed product set records its backup in its product-set
  manifest, which is defined when postprocessing is implemented.
- The backup procedure is implemented as workflow code when the first
  production object is accepted; its location requires an update to this
  contract first.
- Copying into the backup copy uses paid storage. A coding agent proposes the
  list of objects, file counts, and sizes, and copies only after user approval.
  Deleting from the backup copy follows
  [Deletion permissions](#deletion-permissions).

## Directory density and depth

- Review a human-maintained directory when it grows beyond approximately 30 to
  50 files. Add a subdirectory only when a stable semantic grouping exists.
- Large machine-generated collections are organized by access pattern and
  scientific dimensions, not by an arbitrary file-count threshold.
- Do not create a directory for a single file unless it defines an ownership,
  lifecycle, or access boundary.
- Do not add a level solely to make the tree look symmetrical.
- Prefer canonical manifests and inventories over browsing enormous file lists
  manually.

## Automated layout check

`tests/check_layout.py` checks the rules of this document that can be verified
from paths and file types. It only reports; it never renames, moves, or deletes.

```bash
python3 tests/check_layout.py            # repository only
python3 tests/check_layout.py --workdir  # repository and $ISIMIP4B_WORKDIR
```

- The pre-commit hook runs the repository check on tracked and staged files
  before every commit (`--tracked-only`); untracked drafts do not block a
  commit.
- Coding agents run the full check before completing any task that creates or
  moves files, as required by `AGENTS.md`.

A reported violation is resolved by fixing the path or, if the rule is wrong,
by the change procedure below. Errors block a commit; warnings do not.

The check flags the name tokens `v<n>`, `old`, `fix`, `fixed`, `final`, and
`latest`. Whether `new` or a date is being used as a version label needs
judgement and is not machine-checked; rule 7 and rule 8 still apply.

## Change procedure

When a task does not fit this contract:

1. identify the missing or conflicting concept;
2. determine whether an existing directory can satisfy the requirement;
3. propose the smallest new stable hierarchy or rule;
4. obtain user approval if the project structure changes;
5. update this document and relevant README files in the same change;
6. update `tests/check_layout.py` when the new rule can be checked
   automatically;
7. only then create production content in the new location.

Temporary deviations are not allowed to become undocumented permanent
structure.
