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

`plugins.irrigation.paddy_bare_class` (`PBARE`) 16 is the number of vegetation classes, VIC's default: with it the
land-use plugin does not move water-balance terms of paddy fields to a separate bare class
(`plugins/landuse/src/lu_apply.c`; `irr_start.c` accepts only the bare classes, here only 16). `OUT_CV` is not
reliable with this parameter set: in cells without a tile of class 16 the land-use plugin overwrites the class-1
value of the output field with 0 (`lu_apply.c`, the unused tile slot has class 0); the Cv used by the model is
correct, and land cover is taken from the land-use forcing, not from `OUT_CV`.

## Render (`render/`)

| File | Role |
|---|---|
| `resolve_campaign.py` | campaign → segments (years, parents, experiments) → runs; prints the list |
| `forcing_years.py` | year mapping rules and the forcing view of symbolic links |
| `render_run.py` | checks build, parameters and forcing units; renders the run directory |
| `../templates/vic/global_param.txt` | VIC global-parameter template (physics and options checked against the source of the locked commit) |
| `../templates/slurm/vic_run.sbatch` | Slurm template: input checksums, VIC, manifest completion; the job fails when VIC or the completion fails |

**Segments.** `resolve_campaign.py` reads `definitions/experiments/ISIMIP4b.yaml` and `period.yaml` of the
protocol commit the campaign pins (the snapshot's `COMMIT` file must equal `protocol.commit`), keeps the experiments of the campaign's sector and selection, and
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
| cycle | spin-up climate | `a + (Y − a) mod L` in the campaign's window `[a, b]`; when the day count differs, the next year of the window with the same count (a year that maps to itself is recorded as identity) |

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

**Initial state.** A run whose parent segment is a run of the campaign starts from the parent's end state. A
run without such a parent starts as the campaign's `initialisation.without_parent` says: `cold_start` (no
`INIT_STATE`, the initial moisture of the parameter file) or `state_of_run`, the end state of an earlier,
completed run named in the campaign (`run_dir`, `state`, `reason`), e.g. a warm start of a smoke run. The
renderer requires that run's last attempt to be completed and its state file to exist, and records the run,
attempt and the state's sha256 under `parent` in the run manifest; the job checks the sha256 before VIC starts.
VIC does not check the date of a state file, and it restores a state by array position, checking only its
dimensions (the dams plugin by dam index): the earlier run must have the same model commit, executable sha256
and parameter files (md5 per role) as the new run, else the renderer stops. A state dated after the run start
keeps the dams that were active at that date active (D19).

**Run directory.** `runs/<campaign-id>/<run-id>/` (`--scratch`: `scratch/<campaign-id>/<run-id>/`, never
submitted): `config/` (`vic_global.txt`, `vic_constants.txt` with the dam constants, `job.sbatch`,
`resolved.yaml` with campaign, segment, resources, build, parameter files and forcing units), `forcing/`
(the view), `logs/`, `states/`, `output/`, `run_manifest.json`. An existing run directory is never
rendered again; renders of campaign runs need a clean repository.

**Initial state.** Parent relations come from the whole campaign, whatever `--run-id` selects. A run whose
parent segment is a run of the campaign (and the campaign has no `restriction`) starts from the parent's end
state (`INIT_STATE`): when the parent is rendered in the same call, the job checks before VIC starts that the
parent run completed and records the state's sha256 in the attempt; when the run is rendered alone, the parent
run must already have completed with its end state, whose run, attempt and sha256 are recorded in
`parent`, else the renderer stops. A run whose parent is not a run of the campaign follows
`initialisation.without_parent`.

**Checks before rendering.** Model commit of the campaign = `model/vic.lock.yaml` = build manifest; build
status `built` or `tested`; resources modules = `runtime_modules` of the build; every parameter file in the
parameter manifest; every forcing unit accepted (`code_dirty: false`, `qc.status: passed`) and made on the
campaign's domain file and, for climate, with its elevation (the sha256 recorded in the unit's `provenance.yaml`
equal to that of the domain file and of the natural bundle the parameter file was assembled from); the campaign's
output selection covers every protocol variable of the sector (mapped or listed as not provided); the output
streams are `daily` (`NDAYS 1`) and `monthly` (`NMONTHS 1`) with `history_frequency: NYEARS 1`, the only
files the expected outputs and `check_run.py` know (other stream configurations stop the render); with
`plugins.water_use.nonrenewable_withdrawal` the monthly output contains `OUT_NONREN_DEFICIT` (the routing plugin
repays the deficit from the baseflow that enters the river, but `OUT_BASEFLOW` keeps it, `rout_run.c`); with the
land-use plugin, the QC of the vegetation component behind the parameter file (bundle `provenance.yaml`,
`inputs.vegetation_component`) is `passed` and has checked the land-use files of the run with their current
sha256 (`forcing_tiles.checked_files`), since VIC stops in the first year a class has coverage but no tile; MPI tasks
≤ decomposition groups (VIC gives whole groups to ranks, largest first, `rout_decomposition.c`; extra ranks
stay empty, and with the 128-group file more than about 6 ranks shorten nothing, so the cores go to OpenMP
threads).

## Submit (`submit/`)

| File | Role |
|---|---|
| `submit_run.py` | renders the runs of a campaign (label) and submits each job on hold, records the attempt, releases it (the run directory is locked meanwhile, so a second submission of the same run stops, and a manifest write never drops a recorded attempt); a run whose parent is submitted in the same call waits for it (`afterok`); `--retry <run-dir>` resubmits an unchanged run as a new attempt; `--retry <run-dir> --rerender-job` first renders only the Slurm job file again from the current template and resources (how the run is executed, not what it simulates), keeping the previous one as `config/job.attempt-<n>.sbatch` and recording it under `job_files`; the new job file is checked like a render (resources modules = build `runtime_modules`, MPI tasks ≤ the decomposition groups recorded in `resolved.yaml`) |
| `run_manifest.py` | `verify-inputs` (job step before VIC: checksums of parameters, forcing files, executable and parent state file; every forcing unit still accepted; every forcing-view link points to its recorded source) and `complete` (job step after VIC, also on failure; every OUTVAR of `vic_global.txt` must be in the output files of its stream, since VIC drops an unknown OUTVAR with only a warning; exit status 1 when the attempt failed) |

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/05_simulation/render/resolve_campaign.py --campaign configs/campaigns/smoke.yaml --label smoke2015
python3 workflow/05_simulation/render/render_run.py --campaign configs/campaigns/smoke.yaml --label smoke2015 --scratch
python3 workflow/05_simulation/submit/submit_run.py --campaign configs/campaigns/smoke.yaml --label smoke2015
python3 workflow/05_simulation/submit/submit_run.py --retry runs/smoke/<run-id>
python3 workflow/05_simulation/monitor/submit_check.py --run-dir runs/smoke/<run-id>
```

**Cores on Anunna.** Slurm on Anunna uses `task/cgroup` only: the job is confined to its cores, but no task
is bound to cores of its own and `--cpu-bind` has no effect. The job therefore sets no OpenMP binding
(`OMP_PLACES`/`OMP_PROC_BIND` put the main thread of every rank on the first core: the first smoke attempt
of 2026-10-04 ran its 8 ranks on one core and was cancelled) and prints the cores each rank may use before
VIC starts.

## Monitor (`monitor/`)

| File | Role |
|---|---|
| `check_run.py` | checks of a finished run per year: coverage of active cells, annual `qtot`, water balance (global P, ET, qtot, monthly storage, zonal means, `OUT_WATER_ERROR` as a monthly mean), largest outlets, irrigation (withdrawal, requirement, received), municipal and manufacturing demand (forcing and VIC) and withdrawal, water-use budget per cell and month (withdrawn ≤ demand, consumed ≤ withdrawn, GW + SURF + DAM + TREM + NREN = `OUT_WITHDRAWN`, the definition of `wu_output.c` under GWM FALSE; a missing monthly water-use value on an active cell fails it and stays missing, not zero, in the derived file), the non-renewable deficit at the end of each month when `OUT_NONREN_DEFICIT` is written, end state; GRDC comparison for the whole run |
| `run_figures.py` | the derived file `reports/water_use_by_sector_<year>.nc` (monthly withdrawal per sector municipal, manufacturing, irrigation and its sources groundwater, surface, dam, remote, nonrenewable; VIC demand and estimated consumption for municipal and manufacturing; VIC-WUR writes the sources per sector but no sector total) and the figures of water use by sector and source, source shares, sector maps, distributions of withdrawal/demand and of remote and groundwater shares, and the water balance |
| `grdc.py` | GRDC daily export (`raw/external/grdc/export-2024-11`, `manifests/inputs/grdc.yaml`): station files, upstream area along the routing network, station-to-cell mapping (closest upstream area within 3 cells, area error ≤ 30 %), monthly means (≥ 20 valid days) and climatology (≥ 5 years per month) |
| `check_run.sbatch`, `submit_check.py` | Slurm job of the check (one core, about 7 min and 13 GB for one year), job record under `logs/05_simulation/<job-name>_<slurm-job-id>/`; `submit_run.py` submits it after every run job, to start when the run has succeeded; job name `run-check-<campaign>-<label>`, or the run ID with hyphens for a production run; the job ends FAILED when the check fails (exit status 1) |

Output in `qc/runs/<campaign>/<run-id>/`: `summary.json`, `reports/check.json`, `reports/grdc_stations.csv`,
`reports/water_use_by_sector_<year>.nc`, `figures/`. GRDC comparison: the runs are driven by GCM climate, so
days and months do not correspond to observed weather. The main comparison is climatological: the simulated
monthly-mean seasonal cycle of the run years (without the first year when a cold-started run has 3 or more
years) against the GRDC climatology of the run years ± 10 years, at stations with a
catchment of at least 10 000 km2; daily series of the same dates are drawn for visual reference only.

## Run manifest (`run_manifest.json`, schema `isimip4b-run-manifest-1`)

| Key | Content |
|---|---|
| `campaign_id`, `run_id`, `segment_id`, `label`, `production`, `run_dir`, `period` | identity |
| `status` | `rendered`, `submitted`, `running`, `completed` or `failed` (of the last attempt) |
| `parent` | parent segment, `init_state` (workdir path) or `cold_start`; a warm start (`state_of_run`) has `segment_id` null, `protocol_parent_segment` and the earlier run's `run_dir`; with a state: parent `run_id`, its completed `attempt` and the state's `state_sha256` (null when the parent was rendered in the same call; the attempt's `input_verification.parent_state` then records them) |
| `workflow` | rendering commit, `code_dirty`, script, time |
| `campaign_config` | campaign file and its sha256 |
| `model` | commit, freeze status, build directory and status, executable and its sha256, runtime modules |
| `inputs` | parameter set; parameter files with md5 (parameter manifest); forcing units with `code_commit`, `created_at`, `qc_status` and every file read with its sha256 (unit provenance) |
| `forcing_view` | per series and simulation year: source file and rule |
| `forcing_links` | every link of the forcing view (run-relative) with its source file (workdir-relative), checked by `verify-inputs` (runs rendered from 2026-10-07) |
| `rendered_files` | sha256 of `vic_global.txt`, `vic_constants.txt`, `job.sbatch`, `resolved.yaml` |
| `inputs_fingerprint` | sha256 over executable, inputs, forcing view, rendered model files (not the Slurm job file) and, for a run with an initial state, `parent` |
| `job_files` | earlier Slurm job files of the run kept by `--rerender-job`, with sha256, time, commit and resources |
| `expected_outputs` | output files per year and the end state |
| `attempts[]` | `attempt`, `slurm_job_id`, `submitted_at`, `submitted_by_commit`, `dependency`, `inputs_fingerprint`, `input_verification` (files, mismatches, `parent_state`), `output_variables` (per stream: requested OUTVARs and the missing ones), `started_at`, `ended_at`, `vic_exit_code`, `scheduler` (sacct rows: state, exit code, elapsed, MaxRSS, nodes), `vic_timing` (VIC timing table and model cost), `log_scan` (warning and error lines by category), `outputs_present`, `outputs_complete`, `output_bytes`, `completed_by_commit`, `status`, `failure_reason` |

Tests: `tests/unit/test_simulation_resolve.py`, `tests/unit/test_simulation_render.py`,
`tests/unit/test_simulation_submit.py`, `tests/unit/test_run_check_water_use.py`.

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

