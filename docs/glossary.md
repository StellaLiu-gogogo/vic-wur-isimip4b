# Glossary

This glossary is the authoritative source for project terminology. Terms marked
**ISIMIP** are defined by the ISIMIP4 protocol and must be used exactly as the
protocol defines them. Terms marked **project** are defined by this project to
organize work that the protocol does not name.

Protocol source: <https://github.com/ISI-MIP/isimip-protocol-4>, checked at
commit `f9be7b0cdf83409315d9fa7da8581cc6fd6ff3e1` (2026-09-24). The
experiment, scenario, and period definitions are unchanged since commit
`4a51211054a5a90444ca87664d1f29b2abb5bc38` (2026-09-18), which is the commit
used by the protocol audit.

## Identifier conventions

- Identifiers are lowercase.
- Hyphens (`-`) join words inside one identifier, e.g. `ec-earth3-esm-1-1`.
- Underscores (`_`) separate identifiers inside a composite identifier, e.g.
  `h_ssp3hsoc-noadapt_default`.
- ISIMIP specifiers are copied from the protocol, never abbreviated or
  translated.

These rules follow ISIMIP section 5 (reporting) so that project identifiers can
be converted to delivery filenames without renaming.

## ISIMIP dimensions

### Climate forcing (`climate-forcing`) — ISIMIP

The GCM providing the climate-related forcing. ISIMIP4b values:

| Specifier | GCM |
|---|---|
| `ec-earth3-esm-1-1` | EC-Earth3-ESM-1-1 |
| `ukesm1-3-ll` | UKESM1-3-LL |

The DKRZ directory name uses the original capitalisation
(`EC-Earth3-ESM-1-1/`); filenames and all project identifiers use the lowercase
specifier. Short synonym in this project: **GCM**.

### Ensemble member (`ensemble-member`) — ISIMIP

The CMIP realisation label of the GCM run, e.g. `r1i1p1f1`. It appears in
ISIMIP4b input filenames. Project identifiers omit it while each GCM has exactly
one ensemble member; this must be revisited if a second member is used.

### Bias adjustment (`bias-adjustment`) — ISIMIP

The reference dataset used for bias adjustment. ISIMIP4b atmospheric forcing
uses `era5`.

### Climate scenario (`climate-scenario`) — ISIMIP

The climate-related forcing of an experiment. ISIMIP4b values:

| Experiment specifier | Concentration-driven input alias | Emission-driven input alias |
|---|---|---|
| `picontrol` | `picontrol` | `esm-picontrol` |
| `historical` | `historical` | `esm-hist` |
| `vl` | `scen7-vl` | `esm-scen7-vl` |
| `h` | `scen7-h` | `esm-scen7-h` |

The **experiment specifier** (left column) identifies the experiment and is used
in experiment IDs, segment IDs, run IDs, and output filenames. The **input
alias** (right columns) is the CMIP7 label used in DKRZ input paths and
filenames; it records whether the GCM run was concentration- or
emission-driven.

Project rule: paths that hold data derived from one specific input file set
(`workdir/raw/`, `workdir/forcing/climate/`) keep the input alias, because it is
part of the data identity. Everything downstream of forcing uses the experiment
specifier.

### Direct human forcing scenario (`soc-scenario`) — ISIMIP

The assumption on direct human forcing (DHF) such as land use, irrigation, and
water use. ISIMIP4b values relevant to `water_global`:

| Specifier | Meaning |
|---|---|
| `histsoc` | Varying historical DHF. |
| `1850soc` | DHF fixed at year 1850. |
| `2021soc` | DHF fixed at year 2021 over the whole simulation. |
| `2021soc-from-histsoc` | DHF fixed at year 2021 in the future period, following a `histsoc` historical period. |
| `ssp1vlsoc-noadapt` | Future DHF from SSP1 with the very low emission scenario, not responding to climate change. |
| `ssp3hsoc-noadapt` | Future DHF from SSP3 with the high emission scenario, not responding to climate change. |

`ssp1vlsoc-adapt` and `ssp3hsoc-adapt` exist in the protocol but are hidden and
are not requested for `water_global`.

### Sensitivity scenario (`sens-scenario`) — ISIMIP

A deviation from the default settings of an experiment. `default` is used when
no deviation applies. Values requested for `water_global`:

| Specifier | Meaning |
|---|---|
| `default` | No deviation. |
| `extrasoc` | Additional DHF chosen by the modelling team on top of land use, irrigation, and non-irrigation water use (Group III). |
| `2021co2` | CO₂ concentration fixed at 2021 levels. |

VIC-WUR has no CO₂-dependent process. The protocol states that a model without
CO₂ response labels its runs `default`; a `2021co2` experiment is therefore
identical to its `default` counterpart for VIC-WUR and is not simulated
separately. Whether the `2021co2` experiments must still be reported under that
label is an open question for the sector coordinators.

### Period (`period`) — ISIMIP

| Specifier | Years |
|---|---|
| `pre-industrial` | 1601–1849 |
| `historical` | 1850–2021 |
| `future` | 2022–2100 |

The pre-industrial control period (1601–1849) is part of the reported
experiments; the spin-up must be completed before 1601.

### Experiment — ISIMIP

A combination of climate scenario, direct human forcing scenario, and
sensitivity scenario, defined for the whole 1601–2100 time span. Within one
experiment, the climate scenario and DHF scenario may differ by period. For
example, `h_ssp3hsoc-noadapt_default` uses `picontrol`/`1850soc` in the
pre-industrial period, `historical`/`histsoc` in the historical period, and
`h`/`ssp3hsoc-noadapt` in the future period.

An experiment does not include the GCM.

### Experiment ID — ISIMIP

`<climate-scenario>_<soc-scenario>_<sens-scenario>`, where each part is the
value that applies to the **future** period. This is the protocol's own
experiment specifier, e.g. `picontrol_2021soc-from-histsoc_default`,
`h_ssp3hsoc-noadapt_extrasoc`.

The `water_global` ISIMIP4b experiments are:

| Experiment ID | Priority | Group III |
|---|---|---|
| `picontrol_2021soc-from-histsoc_default` | 1st | |
| `picontrol_2021soc_default` | 1st | |
| `picontrol_1850soc_default` | 2nd | |
| `picontrol_ssp1vlsoc-noadapt_default` | 1st | yes |
| `picontrol_ssp3hsoc-noadapt_default` | 1st | yes |
| `vl_2021soc-from-histsoc_default` | 1st | |
| `vl_2021soc_default` | 1st | |
| `vl_1850soc_default` | 2nd | |
| `vl_ssp1vlsoc-noadapt_default` | 1st | yes |
| `vl_ssp1vlsoc-noadapt_extrasoc` | 2nd | yes |
| `h_2021soc-from-histsoc_default` | 1st | |
| `h_2021soc_default` | 1st | |
| `h_1850soc_default` | 2nd | |
| `h_ssp3hsoc-noadapt_default` | 1st | yes |
| `h_ssp3hsoc-noadapt_extrasoc` | 2nd | yes |
| `h_2021soc-from-histsoc_2021co2` | 1st | |
| `h_2021soc_2021co2` | 1st | |
| `h_1850soc_2021co2` | 2nd | |

The per-period composition of each experiment is recorded in the protocol file
`definitions/experiments/ISIMIP4b.yaml`.

### Group I, II, III — ISIMIP

Experiment groups. Group I and II experiments use fixed or historical DHF;
Group III experiments use future SSP-based DHF (`ssp*soc-*`) and the Group III
forcing requirements of the protocol.

## Project concepts

### Simulation — project

One experiment driven by one GCM: `<climate-forcing>` × `<experiment-id>`. A
simulation is the unit that is reported to ISIMIP as one set of output files.
It is assembled from one or more segments.

### Segment — project

A continuous VIC-WUR integration over one ISIMIP period (or the spin-up) with
one fixed combination of climate scenario, DHF scenario, and sensitivity
scenario. Segments are the unit that is actually simulated.

Segments are shared between experiments. For example, the historical segment
`historical`/`histsoc`/`default` is used by every experiment whose historical
period is "identical to the historical/histsoc run". Each shared segment is
simulated at most once per GCM and campaign, and not at all when the
campaign reuses it from an earlier campaign.

A segment starts from the end state of its parent segment. The parent of each
segment follows from the protocol's per-period experiment definitions.

### Segment ID — project

`<climate-forcing>_<climate-scenario>_<soc-scenario>_<sens-scenario>_<period>`

- `<climate-scenario>` is the experiment specifier, not the input alias.
- `<period>` is `spinup`, `pre-industrial`, `historical`, or `future`.

Examples:

- `ec-earth3-esm-1-1_picontrol_1850soc_default_spinup`
- `ec-earth3-esm-1-1_picontrol_1850soc_default_pre-industrial`
- `ec-earth3-esm-1-1_historical_histsoc_default_historical`
- `ukesm1-3-ll_h_ssp3hsoc-noadapt_default_future`

A spin-up segment uses the forcing the protocol prescribes for spin-up:
pre-industrial control climate with `1850soc` DHF, or with `2021soc` DHF for
experiments that use `2021soc` throughout.

### Chunk — project

A temporal sub-division of one segment, used only when a segment is too long
for one scheduler job. Identified by `<start-year>-<end-year>`. A chunk is a
computational split and has no scientific identity of its own.

### Campaign — project

A named set of runs that share one model build, one parameter set, and one
purpose, e.g. the production runs of one GCM or a smoke test. A campaign ID
is a short descriptive lowercase identifier such as `smoke`, `chunk-test`, or
`water-global-ec-earth3-esm-1-1`. It must not be a version label (`v2`,
`new`, `final`). A campaign is defined in `configs/campaigns/<campaign-id>.yaml`.

A **production campaign** (`production: true`) simulates runs intended for
delivery: its run IDs carry no label, its runs are rendered and submitted only
from a clean repository with the production build and a production parameter
set, and its completed runs become accepted production runs (see "Accepted
production run"). Every other campaign (smoke, debug, trial, test, comparison)
is a **non-production campaign**: its runs may be restricted to a region or a
few years, carry a label, and are never delivered or backed up.

A change of model build or parameter set that alters results requires a new
campaign. Runs from different campaigns are combined in one simulation only
when the newer campaign explicitly declares that it reuses whole periods of an
earlier accepted production campaign, with a justification (see
`directory-contracts.md`, `configs/`).

### Run — project

One execution record of one segment within one campaign. The run ID equals the
segment ID; the campaign provides the rest of the identity. Runs of
non-production campaigns that cover only part of a segment's domain or period
append a label, `<segment-id>__<label>` (see `directory-contracts.md`). A
spin-up segment has one run per block (see "Spin-up block"). A run may be
executed more than once (see "Attempt"); its directory
`workdir/runs/<campaign-id>/<run-id>/` and its run manifest stay the same.

### Spin-up block — project

One continuous integration of a spin-up segment. The spin-up is simulated in
blocks until the convergence test passes (D19, D20): the first block covers
`spinup.length_years` years before the chain start (50 years, 1551–1600 for
the `1850soc` chain and 1800–1849 for the `2021soc` chain); every continuation
block covers `spinup.block_years` years (25) labelled as the last years before
the chain start (1576–1600 or 1825–1849) and starts from the previous block's
end state, so that every block's end state is dated 1601-01-01 or 1850-01-01.
The first block's run ID is the segment ID; continuation block n has the run
ID `<segment-id>__block-<n>` (n = 2, 3, …), and `spinup.max_blocks` (8) limits
the chain. The suffix `block-<n>` is used for nothing else.

### Chain — project

The sequence of segments that follow each other through the parent relation,
from a spin-up to a future segment: spin-up → pre-industrial → historical →
future. The `1850soc` chain and the `2021soc` chain are the two spin-up chains
of a production campaign. The run order `longest-chain-then-priority` (D02)
submits the segments of the longest chain in model years first.

### Attempt — project

One execution of a run's job: the first submission and every scheduler retry
with identical inputs. Every attempt is recorded in the run manifest with its
Slurm job, its scheduler state, and its result; a new attempt never replaces
the record of an earlier one. The run check and the convergence test bind
their result to the attempt they checked.

### Convergence test — project

The test that decides whether a spin-up block has converged (D19, amended
2026-11-02; `workflow/05_simulation/monitor/check_spinup.py`). It uses the 25
annual values of the block. In every active cell, the least-squares slope of
the annual values divided by the standard deviation of the detrended values
must be at most 0.1 per year; a quantity passes when at least 80 % of the
active cells pass (soil moisture of layers 2 and 3, December snow water
equivalent without the perennial-snow cells, river storage). The global
totals of reservoir storage and, for `2021soc`, irrigation withdrawal must
pass under the same slope rule. The block has converged when every quantity
passes; the 20 largest basins appear in the figures only. A test that cannot
be evaluated is `not_checked`, not `failed`, and stops the chain for the user.

### Run check — project

The quality control of a completed run or chunk
(`workflow/05_simulation/monitor/check_run.py`), run as its own Slurm job
after the run job: coverage of the active cells, annual runoff, the water
balance and its closure, the 99th percentile of the absolute water-balance
error over all active cells and months (at most 1 mm), outlets, water use and
irrigation, the end state, and the comparison with GRDC discharge for the
whole run. Its result is written to `qc/runs/<campaign-id>/<run-id>/summary.json`
with a check status.

### Check status — project

The four values every quality-control record uses: `passed` (every check
passed), `warning` (passed with findings the user should see), `failed` (at
least one check failed), and `not_checked` (no check has run, or the check
could not be evaluated). A directory under `qc/` or a run directory is never
evidence by itself; only the recorded status is.

### Recovery ledger — project

`workdir/runs/<campaign-id>/recovery.json`, the campaign's record of attempts
that ended without completing: run, chunk, years, Slurm job, scheduler state,
reason, the jobs cancelled after it, the command that resumes it, and the
attempt that resumed it. It is written only by
`workflow/05_simulation/submit/submit_run.py` (`--reconcile`, `--resume`,
before `--retry`), summarises what the run manifests record, and never
replaces them.

### Cycle rule — project

The rule by which a spin-up run reads the pre-industrial control climate:
the years of the chain's cycle window (campaign key `spinup.climate_cycle`)
are repeated, and each simulation year is mapped to the window year with the
same position in the cycle and the same day count (D19 amendment 2026-10-22,
D20). The `1850soc` chain cycles `picontrol` 1601–1650, so its blocks
1551–1600 and 1576–1600 read copies of window years; the `2021soc` chain
cycles the real `picontrol` years 1800–1849, so its blocks read the climate
year of their own label. The run's forcing view links every simulation year
to the year it reads; the mapping is recorded in the run manifest.

### First-year files — project

The forcing files of a start year that lies outside the years a forcing unit
holds: the start years of the spin-up blocks (land use and water use 1551,
1576, 1800, 1825; climate 1551 and 1576 only, since the `2021soc` chain reads
real `picontrol` years), 1601 for the pre-industrial segment, 1850 for the
`2021soc` historical segments, and 2022 for the `1850soc` future segments.
They are produced as extension years
of the accepted units by the units' own producers, never by hand and never by
the renderer, and are recorded in the unit's `provenance.yaml` with the source
year and the transformation (D20).

## Output naming

### Output filename — ISIMIP

The protocol requires sector-specific output filename patterns. As of protocol
commit `f9be7b0`, no ISIMIP4b `OutputData` pattern for `water_global` has been
published. The ISIMIP3b `water_global` pattern is:

```text
<model>_<climate-forcing>_<bias-adjustment>_<climate-scenario>_<soc-scenario>_<sens-scenario>_<variable>_global_<time-step>_<start-year>_<end-year>.nc
```

Delivery code must read the pattern from the protocol once it is published and
must not hard-code the ISIMIP3b pattern. Whether the ISIMIP4b pattern adds
`<ensemble-member>` is open.

### Model name (`model`) — ISIMIP

The impact-model identifier in output filenames. The protocol requires a
version suffix when the model version differs from the one used in ISIMIP4a.
The VIC-WUR model name and suffix for ISIMIP4b are not yet decided.

## Data terms

### Direct human forcing (DHF) — ISIMIP

Human influences prescribed as input: land use, irrigation, non-irrigation
water use, reservoirs and dams, and other Group III forcings.

### Climate-related forcing (CRF) — ISIMIP

Atmospheric forcing and atmospheric composition supplied by the GCM.

### Raw data — project

Files exactly as downloaded from DKRZ, stored under `workdir/raw/` in the DKRZ
directory structure. Raw data is immutable: while present, a file is never
edited, renamed, or replaced. It may be deleted to save space and downloaded
again later under the conditions in `directory-contracts.md`; the restored
file must match the checksum in the input manifest.

### Forcing — project

VIC-ready time-dependent input derived from raw data, stored under
`workdir/forcing/`.

### Forcing unit — project

One leaf directory under `workdir/forcing/`, e.g.
`climate/ec-earth3-esm-1-1/esm-hist/prec/` or `landuse/histsoc/`, generated
and accepted as a whole (a unit of yearly files may be extended with new
years under the conditions in `directory-contracts.md`, `forcing/`). Its
`provenance.yaml` records how it was made and
its QC status; it is **accepted** when that record shows `code_dirty: false`
and `qc.status: passed` (see `directory-contracts.md`, `forcing/`).

### Clean repository — project

The state in which `git status --porcelain` in the repository prints nothing:
no modified, staged, deleted, or untracked non-ignored files anywhere in the
repository. Only a clean repository can produce reusable caches, accepted
forcing, production parameter sets, production runs, postprocessed product
sets, or deliveries, because only then does the recorded commit
identify the exact code, configuration, manifests, model lock, and environment
definitions that were used.

### Parameter set — project

A complete, internally consistent set of static or slowly varying VIC-WUR
parameter files, identified by a parameter-set ID and recorded in a parameter
manifest.

### Component — project

One directory of a parameter set, `parameters/<status>/<parameter-set-id>/<component>/`,
holding the files of one kind of parameter: `domain`, `bundle`, `routing`,
`irrigation`, `water_use`, `dams`, `vegetation`, and `soil`.
The valid components are the component directories listed under
`workflow/03_parameters/`. A component is either generated by its producer in
that stage or adopted.

### Adopted component — project

A component whose files are copied from a recorded external source, such as
the sibling `vic_parameter` project, instead of being generated by
`workflow/03_parameters/`. The parameter manifest records the source location,
source version or commit, and the checksum of every file; the files are
copied, never linked, renamed without version tokens with the source name
recorded, and verified by the component's verifier like a generated one.

### Bundle — project

The VIC image-driver parameter file that VIC reads with `PARAMETERS`: one
NetCDF file combining the soil, snow-band, elevation, and vegetation
variables. It is the `bundle` component of a parameter set, assembled by
`workflow/03_parameters/bundle/` from the other components, every variable
bitwise equal to its source.

### Candidate and production parameter set — project

A parameter set is a **candidate** (`parameters/candidates/<parameter-set-id>/`)
until it is promoted. A **production parameter set**
(`parameters/production/<parameter-set-id>/`) is the promoted copy that
production campaigns use; its manifest under `manifests/parameters/` has
`status: production`. The candidate copy stays, because earlier runs record
its paths. The production set is `vic-global-5arcmin-version-b` (promoted
2026-11-05, task Z), which the production campaign uses; it replaced
`vic-global-5arcmin-version-a` (promoted 2026-10-30), its base.

### Promotion — project

The explicit, recorded step that turns a candidate into a production object
after its quality control passed and the user authorised it. A parameter set
is promoted by `workflow/03_parameters/promote_parameter_set.py`: every file
of the manifest entries not excluded is copied (never moved) with its
checksums verified, `promotion.yaml` at the root of the production set
records the time, commit, authorisation, files, and QC evidence, and an
independent verifier checks the copy. A candidate build is promoted by
`workflow/05_simulation/build/promote_build.py` without rebuilding the
executable (see "Production build").

## Code and build terms

### Frozen model version — project

The VIC-WUR commit that `model/vic.lock.yaml` identifies by its immutable full
Git commit SHA (D01: `a826251b`). A branch name or a short, moving reference
is not a frozen version. Production builds, production parameter checks, and
production runs refer to the frozen version only.

### Production, candidate, and test build — project

A **build** is one compiled VIC-WUR executable with its evidence under
`workdir/builds/vic/<model-commit>/` and a build manifest (source commit,
build environment, build command, executable checksum, test status). A
**production build** (`build_kind: production`) is the build of the frozen
model version that production campaigns run. A **candidate build** is a build
made while the model lock was provisional; it becomes the production build of
the same commit only by promotion, which changes nothing but the manifest. A
**test build** (`build_kind: test`) is the build of a commit that descends
from the locked commit; only a non-production campaign with
`model.test_build: true` may run it.

### Code-equivalence record — project

`manifests/code-equivalence.yaml`: one entry per change of producing code that
leaves every result unchanged (moving code to `workflow/common/`,
documentation, a verifier change). Such a change alters the Git tree hashes
recorded in the provenance of forcing units and parameter sets; the entry
(`from` and `to` hashes, the change, the before-and-after test as evidence,
the user's approval) lets an accepted unit still be extended under the
changed code. Entries are added in the same commit as the change and are
never edited or removed.

### Job record — project

The directory `workdir/logs/<workflow-stage>/<job-name>_<slurm-job-id>/` that
every Slurm job of a stage other than `05_simulation` keeps: the exact
rendered job script `job.sbatch`, `job.yaml` (Slurm job ID, rendering script,
code commit and `code_dirty`, submission time in UTC, inputs, output paths),
and the scheduler output. A resubmission gets a new record; records are never
overwritten. Simulation jobs are recorded with their run, build jobs with
their build.

### Layout check — project

`tests/check_layout.py`: the automated check of the rules of
`directory-contracts.md` that can be verified from paths and file types, in
the repository and, with `--workdir`, in the workdir. It only reports, never
renames, moves, or deletes. Errors block a commit (the pre-commit hook runs
it on tracked and staged files); warnings do not. It also reports the open
decisions that are due for a stage.

## Backup terms

### Backup root — project

`/lustre/backup/WUR/ESG/liu297/isimip4b/` (`ISIMIP4B_BACKUP`), the directory
the administrators back up off site. It holds `archive/` with the snapshots,
the `current` pointer, and the bare repository `repo.git/` with every branch
and tag. Nothing writes into it except the backup procedure
(`workflow/09_backup/`, D13).

### Snapshot — project

One dated, complete copy `archive/<YYYY-MM-DD>/` of the workdir and of the
repository working tree under the same relative paths, selected by the D13
rules (no raw data, scratch, model output, data or log file types, or
`.git/`; kept whole: production parameter sets, the states of accepted
production runs, products, and deliveries). Unchanged files are hard links
to the previous snapshot, every copied file is verified by sha256, and the
snapshot carries `backup-manifest.json` and `backup-checksums.sha256`. A
snapshot is never changed or replaced after it is complete. A snapshot being
written, or left by a failed one, is a **staging snapshot**
`archive/<YYYY-MM-DD>.staging/`.

### Current pointer — project

The symbolic link `current` in the backup root, pointing to the newest
complete snapshot. It is moved only after a snapshot has been verified and
published, so it is always complete. It is never named `latest`.

### Accepted production run — project

A run of a production campaign whose `run_manifest.json` records `production`
and `completed`, and whose run check or convergence test has written
`qc/runs/<campaign-id>/<run-id>/summary.json`. Only the states of accepted
production runs are backed up; a run that is not yet accepted is taken by the
first snapshot after its acceptance.
