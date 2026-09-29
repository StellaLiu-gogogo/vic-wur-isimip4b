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
    workdir directories should be created by workflow code.
11. A new production directory pattern requires an approved update to this
    document before use.
12. Prefer two to five meaningful levels below a major directory. Add depth for
    stable semantics, not merely to hide a large unstructured collection.
13. Files and directories created by the project use ASCII names. Upstream
    names under `workdir/raw/` are kept exactly as delivered.

Rules that can be checked automatically are enforced by
`tests/check_layout.py` (see [Automated layout check](#automated-layout-check)).

## Project roots

```text
isimip4b/
├── repo/
└── workdir/
```

- `repo/` is the version-controlled project repository.
- `workdir/` is the large-data and runtime area outside Git.

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
│   └── audits/
├── environments/
├── manifests/
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
- `docs/README.md`, `docs/glossary.md`, `docs/directory-contracts.md`
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
- `docs/decisions/`
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
├── inputs/
├── parameters/
├── runs/
└── deliveries/
```

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
- modules are flat files in `common/`; do not add a language or package layer;
- workflow code imports it as `from common import <module>` with
  `PYTHONPATH` including `repo/workflow`, as defined in `environments/`.

#### `workflow/03_parameters/`

Create component directories only when implementation exists:

```text
03_parameters/
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
layer such as `python/` or `shell/`.

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
- the user has authorized the deletion, as required for large data
  collections in `AGENTS.md`.

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
  `climate-regridding_ec-earth3-esm-1-1_esm-hist_pr`. It must not contain a
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
- Before reuse, a producer may delete and immediately rebuild the one cache
  it is about to use when the fingerprint does not match or `_SUCCESS` is
  missing. It deletes no other cache.
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
cache_id: climate-regridding_ec-earth3-esm-1-1_esm-hist_pr
cache_fingerprint: <sha256>

producer_stage: 04_forcing
created_by: workflow/04_forcing/climate/regrid_climate.py
code_commit: 0123456789abcdef0123456789abcdef01234567
code_dirty: false
created_at: 2026-09-28T14:30:00Z

input_manifest: manifests/inputs/example.yaml

inputs:
  - raw/ISIMIP4b/InputData/...

rebuild_command: >-
  python3 workflow/04_forcing/climate/regrid_climate.py
  --manifest manifests/inputs/example.yaml

campaign_config: configs/campaigns/example.yaml

final_destination:
  - forcing/climate/ec-earth3-esm-1-1/esm-hist/pr
```

| Key | Requirement |
|---|---|
| `cache_id` | Required; equals the directory name. |
| `cache_fingerprint` | Required; SHA-256 defined below. |
| `producer_stage` | Required; equals the parent directory name. |
| `created_by` | Required; a path under `workflow/` that exists in the repository. |
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
recorded fingerprint **and** `_SUCCESS` exists. Otherwise it deletes and
rebuilds the cache. Cache validity never depends on file names or manual
judgement.

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

Valid components include those implemented under
`workflow/03_parameters/`. Promotion from `candidates/` to `production/` must
be explicit, reproducible, and supported by quality-control evidence and an
accepted parameter manifest.

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
forcing/climate/ec-earth3-esm-1-1/esm-picontrol/pr/
forcing/climate/ec-earth3-esm-1-1/esm-hist/tas/
forcing/climate/ukesm1-3-ll/esm-hist/pr/
forcing/landuse/histsoc/
forcing/landuse/ssp3hsoc-noadapt/
```

Rules:

- the first level identifies the forcing family (`climate`, `landuse`,
  `water_use`);
- climate forcing is organized by GCM, then climate-scenario input alias as
  used in the DKRZ path (e.g. `esm-hist`, see `glossary.md`), then variable;
- DHF forcing is organized by soc scenario;
- use official lowercase identifiers;
- apply the same dimension order to every GCM and scenario;
- do not add a redundant project, model, or grid level while only one model and
  production grid exist;
- record grid, method, workflow commit, and acceptance status in provenance,
  not in ad hoc version directories.

The climate variable level may be omitted only if each scenario contains a
small number of files and the decision is applied consistently to every GCM and
scenario. Changing this choice requires updating this contract first.

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
        └── run_manifest.json
```

- `<campaign-id>` identifies the campaign defined in `configs/campaigns/`.
- `<run-id>` is the segment ID defined in `glossary.md`:
  `<climate-forcing>_<climate-scenario>_<soc-scenario>_<sens-scenario>_<period>`.

`config/` must preserve the resolved campaign and segment configuration, the
exact VIC configuration, and the exact Slurm job used for the run.

If one run is split into chunks, use:

```text
runs/<campaign-id>/<run-id>/
├── run_manifest.json
└── chunks/
    └── <start-year>-<end-year>/
        ├── config/
        ├── logs/
        ├── states/
        └── output/
```

Do not create `run_fix`, `run_final`, or similar replacement directories.
Changed scientific or computational identity requires a new campaign.
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
└── <object-type>/
    └── <object-id>/
        ├── summary.json
        ├── reports/
        ├── figures/
        └── logs/
```

`<object-type>` is the name of the workdir top-level directory that holds the
checked object: `raw`, `intermediate`, `parameters`, `forcing`, `builds`,
`runs`, `postprocessed`, or `delivery`.

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
`<task-id>` under `repo/analysis/`. Source code is never stored here.

No workflow stage may read from this directory. A result that a production
stage needs must be produced by workflow code.

### `logs/`

Canonical layout:

```text
logs/
└── <workflow-stage>/
```

`<workflow-stage>` is the full stage directory name, e.g. `01_acquisition`.

Use this directory for centralized logs not already owned by a build, run,
quality-control target, analysis, or delivery. Run-specific logs belong with
the run; build-specific logs belong with the build.

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
permission for the whole workdir; `AGENTS.md` applies it to coding agents.

| Who | What | User authorization |
|---|---|---|
| The user | anything | not needed |
| A workflow producer | the one cache it is about to rebuild, when the fingerprint does not match or `_SUCCESS` is missing | not needed |
| A coding agent | `scratch/<task-id>/` of its own current task, at the end of that task | not needed |
| A coding agent | anything else, including caches, other scratch tasks, analysis products, and raw files | required |

When authorization is required, the agent first presents the paths, file
counts, and sizes to be deleted and deletes only after the user approves that
list. Raw files additionally require the conditions in [`raw/`](#raw).

Never delete a cache or run directory that a running job may be reading.

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

- The pre-commit hook runs the repository check before every commit.
- Coding agents run the full check before completing any task that creates or
  moves files, as required by `AGENTS.md`.

A reported violation is resolved by fixing the path or, if the rule is wrong,
by the change procedure below. Errors block a commit; warnings do not.

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
