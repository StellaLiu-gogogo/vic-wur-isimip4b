# 05 Simulation

## Purpose

Render complete VIC and Slurm configurations, create isolated run directories, submit VIC-WUR simulations, and record run provenance.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Inputs

- Campaign definitions under `configs/campaigns/`.
- ISIMIP experiment definitions from the protocol commit pinned by the campaign.
- Resource definitions under `configs/resources/`.
- Accepted parameters under `workdir/parameters/`.
- Accepted forcing units under `workdir/forcing/` (`provenance.yaml` with `qc.status: passed`).
- A pinned VIC-WUR version from `model/vic.lock.yaml`.
- A verified executable under `workdir/builds/`.

## Outputs

A campaign is resolved into segments by code: the segments, their periods, and their parent segments are derived from the protocol experiment definitions, never listed by hand. Each segment becomes one run.

Each run must be isolated under `workdir/runs/<campaign-id>/<run-id>/`, where `<run-id>` is the segment ID defined in `docs/glossary.md`. A run split into chunks uses `chunks/<start-year>-<end-year>/`. Each run contains at least:

- the resolved campaign and segment configuration;
- the exact VIC configuration used;
- the exact Slurm job submitted;
- a run manifest;
- logs, state files, and raw output in dedicated subdirectories.

## Build

`build/build_vic.sh` builds the image driver at the commit of
`model/vic.lock.yaml` and records it under `workdir/builds/vic/<commit>/`
with `build_manifest.json`, logs and checks (see `build/README.md`):

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
workflow/05_simulation/build/build_vic.sh            # records the build
workflow/05_simulation/build/build_vic.sh --scratch  # test run under scratch/
```

It uses the Anunna module bucket `2025` with `netCDF/4.9.3-gompi-2025a`;
jobs that run the executable must load the same modules (manifest key
`runtime_modules`). With a provisional lock (D01 open) the result is a
candidate build; its status is `built` (the VIC test suite cannot run
here, see `build/README.md`).

## Configuration

The model is the standalone VIC-WUR image driver with `GWM FALSE`, not coupled to MODFLOW: the `wateruse`
plugin takes "groundwater" from the deepest soil layer and returns flows to the river
(`plugins/wateruse/src/wu_run_local.c`); ISIMIP `qr`, `qg` and `qsb` are all `OUT_BASEFLOW`, the outflow
of the bottom soil layer (`vic_run/src/runoff.c`), and `OUT_RECHARGE` (percolation into the bottom layer)
is not `qr`. A campaign (`configs/campaigns/<id>.yaml`, `configs/README.md`) selects experiments and
declares plugin switches, initialisation, DHF forcing units, spin-up and output; resources come from
`configs/resources/<workload>.yaml`.

## Render (`render/`)

| File | Role |
|---|---|
| `resolve_campaign.py` | campaign → segments (years, parents, experiments) → runs; prints the list |
| `forcing_years.py` | year mapping rules and the forcing view of symbolic links |
| `render_run.py` | checks build, parameters and forcing units; renders the run directory |
| `../templates/vic/global_param.txt` | VIC global-parameter template (physics and options checked against the source of the locked commit) |
| `../templates/slurm/vic_run.sbatch` | Slurm template: input checksums, VIC, manifest completion |

**Segments.** `resolve_campaign.py` reads `definitions/experiments/ISIMIP4b.yaml` and `period.yaml` of the
protocol commit the campaign pins, keeps the experiments of the campaign's sector and selection, and
derives per GCM the segments `<gcm>_<climate>_<soc>_<sens>_<period>`: an explicit period entry defines a
segment; "Identical to the similar **c/s[/sens]** run above" refers to the segment with that composition
in the same period (it must be defined explicitly by some experiment); "Does not have to be simulated,
spin-up should be based on the 2021 DHF" means no pre-industrial segment and a `2021soc` spin-up that links
to 1850. The spin-up uses `picontrol` climate with the pre-industrial DHF (`1850soc`) or the one named by
that note; its length is a campaign setting. Parents: pre-industrial ← spin-up, historical ← pre-industrial
(or spin-up), future ← historical; a segment shared by several experiments must get the same parent from
each. `sensitivity_equivalence` maps `2021co2` to `default` (no CO₂ response), so those experiments share
the default segments. For the 18 `water_global` experiments and one GCM this gives 24 segments: 2 spin-ups,
1 pre-industrial, 6 historical, 15 future (`tests/unit/test_simulation_resolve.py` lists them with their
parents). A non-production campaign may restrict runs to some periods and years with a label: run ID
`<segment-id>__<label>`.

**Climate input alias.** The campaign states per GCM whether its DKRZ input is `concentration-driven` or
`emission-driven`; the alias is taken from `specifier_alias` of `definitions/climate_scenario.yaml`
(emission-driven aliases start with `esm-`: `historical` → `esm-hist` for EC-Earth3-ESM-1-1).

**Forcing year mapping.** VIC and its plugins open forcing files by `<prefix><year>.nc` with the simulation
year, but the units cover only the years of their sources (climate: the years of the input alias; land use
and water use: `histsoc` and `1850soc` 1850–2021, `2021soc` and the SSP units 2022–2100). The renderer
builds, per run, a forcing view `runs/<campaign>/<run-id>/forcing/<family>/` of relative symbolic links
named by simulation year (`climate/<variable>/<variable>_<gcm>_<alias>_<year>.nc`,
`landuse/coverage_<soc>_<year>.nc`, `water_use/<sector>_<variable>_<soc>_<year>.nc`) that point into the
accepted units; units are never modified or copied. Rules (`forcing_years.py`):

| Rule | When | Source year |
|---|---|---|
| identity | the unit has the year | the same year |
| constant | the DHF scenario is listed in the campaign's `dhf_forcing.constant` (`1850soc`, `2021soc`) and the unit lacks the year | the first year of the unit with the same number of days (365/366): VIC reads daily records within the year and the water-use demand is mm/day of its calendar year |
| cycle | spin-up climate | `a + (Y − a) mod L` in the campaign's window `[a, b]`; when the day count differs, the next year of the window with the same count |

`2021soc-from-histsoc` uses the `2021soc` unit (`dhf_forcing.units`). The mapping of every simulation year
(source file, rule) is in the run manifest (`forcing_view`).

**Start-year restriction.** VIC checks only the start-year file of each forcing: the climate file's first
time sets the record offset (`drivers/image/src/vic_force.c`, `make_dmy.c`), and every plugin file's first
time must equal the climate file's first time (`plugins/general/src/plugin_get_forcing_file.c`). Files of
later years are opened by name and read from record 0 without any check. A linked file of another year is
therefore accepted for every year except a run's first year; the renderer stops when the first year of a
run is not an identity link in every family. Runs that start in a year a unit does not contain (the
pre-industrial segment starting 1601 with `1850soc`, `2021soc` historical runs starting 1850, `1850soc`
future runs starting 2022, spin-ups before 1601) need that year in the unit itself (04_forcing).

**Run directory.** `runs/<campaign-id>/<run-id>/` (`--scratch`: `scratch/<campaign-id>/<run-id>/`, never
submitted): `config/` (`vic_global.txt`, `vic_constants.txt` with the dam constants, `job.sbatch`,
`resolved.yaml` with campaign, segment, resources, build, parameter files and forcing units), `forcing/`
(the view), `logs/`, `states/`, `output/`, `run_manifest.json`. An existing run directory is never
rendered again; renders of campaign runs need a clean repository.

**Checks before rendering.** Model commit of the campaign = `model/vic.lock.yaml` = build manifest; build
status `built` or `tested`; resources modules = `runtime_modules` of the build; every parameter file in the
parameter manifest; every forcing unit accepted (`code_dirty: false`, `qc.status: passed`); the campaign's
output selection covers every protocol variable of the sector (mapped or listed as not provided); MPI tasks
≤ decomposition groups (VIC gives whole groups to ranks, largest first, `rout_decomposition.c`; extra ranks
stay empty, and with the 128-group file more than about 6 ranks shorten nothing, so the cores go to OpenMP
threads).

## Submit (`submit/`)

| File | Role |
|---|---|
| `submit_run.py` | renders the runs of a campaign (label) and submits each job on hold, records the attempt, releases it; a run whose parent is submitted in the same call waits for it (`afterok`); `--retry <run-dir>` resubmits an unchanged run as a new attempt |
| `run_manifest.py` | `verify-inputs` (job step before VIC: checksums of parameters, forcing files and executable) and `complete` (job step after VIC, also on failure) |

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/05_simulation/render/resolve_campaign.py --campaign configs/campaigns/smoke.yaml --label smoke2015
python3 workflow/05_simulation/render/render_run.py --campaign configs/campaigns/smoke.yaml --label smoke2015 --scratch
python3 workflow/05_simulation/submit/submit_run.py --campaign configs/campaigns/smoke.yaml --label smoke2015
python3 workflow/05_simulation/submit/submit_run.py --retry runs/smoke/<run-id>
```

## Run manifest (`run_manifest.json`, schema `isimip4b-run-manifest-1`)

| Key | Content |
|---|---|
| `campaign_id`, `run_id`, `segment_id`, `label`, `production`, `run_dir`, `period` | identity |
| `status` | `rendered`, `submitted`, `running`, `completed` or `failed` (of the last attempt) |
| `parent` | parent segment, `init_state` (workdir path) or `cold_start` |
| `workflow` | rendering commit, `code_dirty`, script, time |
| `campaign_config` | campaign file and its sha256 |
| `model` | commit, freeze status, build directory and status, executable and its sha256, runtime modules |
| `inputs` | parameter set; parameter files with md5 (parameter manifest); forcing units with `code_commit`, `created_at`, `qc_status` and every file read with its sha256 (unit provenance) |
| `forcing_view` | per series and simulation year: source file and rule |
| `rendered_files` | sha256 of `vic_global.txt`, `vic_constants.txt`, `job.sbatch`, `resolved.yaml` |
| `inputs_fingerprint` | sha256 over executable, inputs, forcing view and rendered files |
| `expected_outputs` | output files per year and the end state |
| `attempts[]` | `attempt`, `slurm_job_id`, `submitted_at`, `submitted_by_commit`, `dependency`, `inputs_fingerprint`, `input_verification` (files, mismatches), `started_at`, `ended_at`, `vic_exit_code`, `scheduler` (sacct rows: state, exit code, elapsed, MaxRSS, nodes), `vic_timing` (VIC timing table and model cost), `log_scan` (warning and error lines by category), `outputs_present`, `outputs_complete`, `output_bytes`, `completed_by_commit`, `status`, `failure_reason` |

Tests: `tests/unit/test_simulation_resolve.py`, `tests/unit/test_simulation_render.py`.

## Allowed content

- Run-directory creation and submission code.
- VIC configuration templates.
- Slurm job templates.
- Restart, dependency, and status-management logic.

## Forbidden content

- Generated run configurations or job files in the repository.
- Compiled executables.
- Model output or state files.
- Production runs from a repository that is not clean (see `docs/glossary.md`).
- Manual edits to a resolved configuration after submission without a new campaign.

## Completion criteria

A run is complete only when the scheduler status, model exit status, expected outputs, resolved configurations, code versions, executable checksum, and input identities are recorded in its run manifest.

