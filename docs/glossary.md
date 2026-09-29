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
purpose, e.g. the production runs for the Fast Track delivery or a smoke test.
A campaign ID is a short descriptive lowercase identifier such as `smoke` or
`fasttrack`. It must not be a version label (`v2`, `new`, `final`).

A change of model build or parameter set that alters results requires a new
campaign. Runs from different campaigns are combined in one simulation only
when the newer campaign explicitly declares that it reuses whole periods of an
earlier accepted production campaign, with a justification (see
`directory-contracts.md`, `configs/`).

### Run — project

One execution record of one segment within one campaign. The run ID equals the
segment ID; the campaign provides the rest of the identity. Runs of
non-production campaigns that cover only part of a segment's domain or period
append a label, `<segment-id>__<label>` (see `directory-contracts.md`). A scheduler retry
with identical inputs is an additional attempt of the same run, recorded in the
run manifest.

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
`climate/ec-earth3-esm-1-1/esm-hist/pr/` or `landuse/histsoc/`, generated
and accepted as a whole. Its `provenance.yaml` records how it was made and
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
