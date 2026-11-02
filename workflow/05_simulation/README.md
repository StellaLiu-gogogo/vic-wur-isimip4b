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
`runtime_modules`). The build of 2026-09-30 was made from the provisional
lock and is a candidate build; its status is `built` (the VIC test suite
cannot run here, see `build/README.md`). Since D01 (2026-10-28) the lock is
frozen and the script gives a production build of the same commit. The user
decided that the existing build, unchanged, becomes the production build
(D01 amendment 2026-10-28): `build/promote_build.py` checked it and recorded
the change in its manifest without recompiling (`build/README.md`); promoted
on 2026-10-30 with the user's authorisation, from `a6761b7`. On 2026-10-31
the user froze `a826251b` instead (D01 amendment 2026-10-31: `39e21ff5` with
the corrected fresh-snow density of the land-use step, task L5); its
production build was compiled by `build_vic.sh` on 2026-10-31, and the build
of `39e21ff5` stays as the record of the earlier runs. A production campaign
renders only with a production build.

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

**Run order.** Without `run_order` the runs come as spin-ups, pre-industrial, historical, future, then by segment ID.
With `run_order: longest-chain-then-priority` (D02 decision 3) the resolver puts first the segments of the longest
chain in model years (for D02: 1850soc spin-up → pre-industrial → `histsoc` historical → future, 550 years; the
`histsoc` historical segment wins the tie of the four historical children of the pre-industrial segment by priority),
then the other segments by the best protocol priority of the experiments that use them (1st before 2nd), then by the
model years left from a segment's start to the end of its longest chain (`order_segments`). A parent always comes
before its children (checked). The renderer and `submit_run.py` render and submit in this order.

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
| cycle | spin-up climate | `a + (Y − a) mod L` in the window `[a, b]` of the run's spin-up chain (`spinup.climate_cycle`: one window, or one per spin-up DHF scenario, D19 amendment 2026-10-22); when the day count differs, the next year of the window with the same count (a year that maps to itself is recorded as identity, and so is a start year of the unit recorded as a copy of its cycle year for the same window, D20 amendment 2026-10-17; a start year made for another window is linked to its cycle year of this window, e.g. 1591 → 1641 in 1601–1650, and stops the render only when the run or one of its chunks starts in it, D20 amendment 2026-11-01) |

`2021soc-from-histsoc` uses the `2021soc` unit (`dhf_forcing.units`). The view and the `PLUGIN_FORCE_TYPE` lines of
the VIC file cover only the plugins that are on: VIC opens the start-year file of every `PLUGIN_FORCE_TYPE` line,
whatever the plugin switch says (`plugins/general/src/plugin_forcing_utils.c`; found by the first attempt of the
natural-run spin-up, job 43368322, 2026-10-21). The mapping of every simulation year
(source file, rule) is in the run manifest (`forcing_view`).

**Start-year restriction.** VIC checks only the start-year file of each forcing: the climate file's first
time sets the record offset (`drivers/image/src/vic_force.c`, `make_dmy.c`), and every plugin file's first
time must equal the climate file's first time (`plugins/general/src/plugin_get_forcing_file.c`). Files of
later years are opened by name and read from record 0 without any check. A linked file of another year is
therefore accepted for every year except a run's first year; the renderer stops when the first year of a
run is not an identity link in every family. Runs that start in a year a unit does not contain (the
pre-industrial segment starting 1601 with `1850soc`, `2021soc` historical runs starting 1850, `1850soc`
future runs starting 2022, spin-ups before 1601) need that year in the unit itself, written by the unit's producer as
an extension year (`docs/decisions/D20-first-year-files.md`).

**Initial state.** A run whose parent segment is a run of the campaign starts from the parent's end state. A
run without such a parent starts as the campaign's `initialisation.without_parent` says: `cold_start` (no
`INIT_STATE`, the initial moisture of the parameter file) or `state_of_run`, the end state of an earlier,
completed run named in the campaign (`run_dir`, `state`, `reason`), e.g. a warm start of a smoke run. The
renderer requires that run's last attempt to be completed and its state file to exist, and records the run,
attempt and the state's sha256 under `parent` in the run manifest; the job checks the sha256 before VIC starts.
VIC does not check the date of a state file, and it restores a state by array position, checking only its
dimensions (the dams plugin by dam index): the earlier run must have the same model commit, executable sha256
and parameter files (md5 per role) as the new run except the dam file, whose dam list is compared (below), else
the renderer stops. A state dated after the run start keeps the dams that were active at that date active (D19).

**Dam files per DHF scenario (D19).** `parameter_set.files.dams` maps every soc scenario of the campaign's
segments to a dam file (the renderer stops when one is missing); a run gets the file of its segment's soc
scenario, recorded as role `dams` in `resolved.yaml` and the run manifest. The files of one parameter set share one
dam list; only `year` differs.

**Warm-start rule (D19, decided 2026-10-11, amended 2026-10-16; checked by `render_run.py`).** A reported
segment (pre-industrial, historical, future) starts only from the end state of its parent segment, dated its
start. A spin-up or a non-production run may start from another completed run's end state only when
(a) **the run starts on 1 January**: at the first step of a run with an initial state the land-use plugin applies
the run's coverage and redistributes water between tiles only on 1 January (`plugins/landuse/src/lu_force.c` of
`39e21ff5`), on any other date the state's coverage stays until the next 1 January (`check_start_january`, also
for runs that start from a parent); (b) model commit, executable and every parameter file are identical except the
dam file (`check_same_identity`), whose dam list must agree: `id`, `type` and order of every dam, and `capacity` of
every dam that can operate in the earlier run (`year` not after its last year; a dam that never operated is an
empty entry of the state, D19 amendment 2026-10-16); (c) the same plugins are on (`check_same_plugins`, from the
earlier run's `config/resolved.yaml`); (d) every dam active in the state (`STATE_DAM_ACTIVE`) and every dam that
can operate by the end of the earlier run operates in the run's dam file at the start year, because VIC never
switches a dam off. The dam checks (`check_dams_from`) apply also to a run that starts from its parent in the
campaign (parent and child may use the dam files of different DHF scenarios), with the state when the parent has
completed. With the dams plugin off the dam checks are skipped. The earlier run may be chunked: its plugins are read
from the `config/resolved.yaml` of its first chunk. A spin-up started this way repeats the convergence
test. The record is `docs/decisions/D19-dams-and-initial-states.md`. Example: the warm start of
`smoke-nonrenewable` (2011 from the 2021-01-01 state of the smoke run) is now refused: 269 dams active in the state
do not operate in 2011.

**Run directory.** `runs/<campaign-id>/<run-id>/` (`--scratch`: `scratch/<campaign-id>/<run-id>/`, never
submitted): `config/` (`vic_global.txt`, `vic_constants.txt` with the dam constants, `job.sbatch`,
`resolved.yaml` with campaign, segment, resources, build, parameter files and forcing units), `forcing/`
(the view), `logs/`, `states/`, `output/`, `run_manifest.json`. An existing run directory is never
rendered again; renders of campaign runs need a clean repository. A render that stops leaves no run directory (D20
amendment 2026-11-01): the first year of every chunk is checked before anything is written, and the run is written
into `.rendering-<run-id>/` beside it and renamed when complete. A run directory without `run_manifest.json`, or a
`.rendering-` directory left by a killed render, stops the render; the user decides whether it is deleted. A year that
no mapping rule can map stops the render with `render stopped: <run>: forcing unit <unit>: ...`.

**Chunked runs (task L4b, user 2026-10-16).** A run longer than `chunk_years` of the resources (25 since 2026-11-01,
D20 amendment 2026-11-01: the chunks of the 50-year spin-ups then start on the D20 start years; 20 before) is split into
chunks of `chunk_years` years, the last one shorter (`render_run.chunk_plan`; a restriction run of a non-production
campaign may set its own `chunk_years`, e.g. campaign `chunk-test`). The run directory then holds only
`run_manifest.json` and `chunks/<start>-<end>/` with `config/`, `forcing/` (the links of the chunk's years),
`logs/`, `states/` and `output/` (`docs/directory-contracts.md`, `runs/`). The first chunk starts as the run (cold,
parent or warm start); every later chunk from the previous chunk's end state, with its own VIC file, job and wall
time; the run's end state is the last chunk's (`end_state` in the manifest; a child run starts from it). Every
chunk starts on 1 January and its first year must be an identity link in every forcing family, as for a run:
a chunk of a run on a constant DHF unit (`1850soc`, `2021soc`) therefore needs the unit's file of the chunk's start
year (D20 extension years) or the render stops. With 25-year chunks the production campaign needs 18 such years in the
land-use and water-use units (`1850soc` 1626, 1651, …, 1826 and 2047, 2072, 2097; `2021soc` 1875, 1900, …, 2000;
D20 amendment 2026-11-01), produced in task W on 2026-11-01. `submit_run.py` submits one job per chunk, each waiting for the
previous one (`afterok`), with a check of each chunk and the check of the whole run after the last chunk and every chunk check (`afterany`: it reads their status);
`--retry` resubmits from the first chunk whose latest attempt did not complete. The manifest's `chunks` and the
`chunk` of every attempt record the bookkeeping; the run is `completed` when every chunk is. **Test (campaign
`chunk-test`, task L4b, 2026-10-22; runs 43407082 and 43407183/43407187, comparison job 43414516):** 2015-2016 in one
job and in two one-year chunks gave bitwise identical daily output, monthly output and end state (all 48 state
variables), except the diagnostic `OUT_WATER_ERROR` of 2016 (differences up to 5.8e-11 mm against values up to
0.3 mm: the storage at the start of a chunk is recomputed from the state); report
`qc/runs/chunk-test/<continuous run>/reports/compare_<chunked run>.json`. The first whole-run check (job 43407189)
started beside the last chunk check and read its status before it was written, which led to the `afterany` wait above.

**Resources of a test run (task L5, user 2026-10-30).** A restriction run of a non-production campaign may set
`resources: {ntasks, cpus_per_task, mem, exclusive, wall_time_hours}`; these replace the values of the campaign's
resource file for that run only (`resolve_campaign.run_resources_override`, `render_run.run_resources`;
`wall_time_hours` replaces the wall time computed from the resource file: the `timeout-test` run of campaign
`production-config-check`, task X, uses 1 h to provoke the TERM signal of the job template). The renderer checks the ranks
against the decomposition groups per run and records the values in `resolved.yaml` (`resources`, and
`resources_override`); `submit_run.py --retry` renders a new job with the same values. Campaign `dam-test` uses it
to run 2015-2016 with 8 ranks x 16 threads and 16 ranks x 8 threads, and with 8 ranks x 8 threads on a shared
node (`exclusive: false`, user 2026-10-31: that run only compares values, so its timing is not comparable).

**Initial state.** Parent relations come from the whole campaign, whatever `--run-id` selects. A run whose
parent segment is a run of the campaign (and the campaign has no `restriction`) starts from the parent's end
state (`INIT_STATE`): when the parent is rendered in the same call, the job checks before VIC starts that the
parent run completed and records the state's sha256 in the attempt; when the run is rendered alone, the parent
run must already have completed with its end state, whose run, attempt and sha256 are recorded in
`parent`, else the renderer stops. A run whose parent is not a run of the campaign follows
`initialisation.without_parent`.

**Checks before rendering.** Model commit of the campaign = `model/vic.lock.yaml` = build manifest; build
status `built` or `tested`; for a production campaign a frozen lock and `build_kind: production`; resources modules = `runtime_modules` of the build; every parameter file in the
parameter manifest; every forcing unit accepted (`code_dirty: false`, `qc.status: passed`) and made on the
campaign's domain file and, for climate, with its elevation (the sha256 recorded in the unit's `provenance.yaml`
equal to that of the domain file and of the natural bundle the parameter file was assembled from; in a promoted set
the bundle `provenance.yaml` keeps the candidate path as `object` and is accepted as the record of the production copy
that `promotion.yaml` lists, `render_run.parameter_provenance`, found by campaign `production-config-check`); the campaign's
output selection covers every protocol variable of the sector (mapped or listed as not provided); the output
streams are `daily` (`NDAYS 1`) and `monthly` (`NMONTHS 1`) with `history_frequency: NYEARS 1`, the only
files the expected outputs and `check_run.py` know (other stream configurations stop the render); the
`output.period_outputs` of a run's period (below); with
`plugins.water_use.nonrenewable_withdrawal` the monthly output contains `OUT_NONREN_DEFICIT` (the routing plugin
repays the deficit from the baseflow that enters the river, but `OUT_BASEFLOW` keeps it, `rout_run.c`); with the
land-use plugin, the QC of the vegetation component behind the parameter file (bundle `provenance.yaml`,
`inputs.vegetation_component`) is `passed` and has checked the land-use files of the run with their current
sha256 (`forcing_tiles.checked_files`), since VIC stops in the first year a class has coverage but no tile; MPI tasks
≤ decomposition groups (VIC gives whole groups to ranks, largest first, `rout_decomposition.c`; extra ranks
stay empty, and with the 128-group file more than about 6 ranks shorten nothing, so the cores go to OpenMP
threads).

## Spin-up runs (task P)

Classification: production workflow code (user, 2026-10-17); implements the spin-up rules of D19 and D20 (task P took
over the steps O3, O5 and O6 of task O). Steps and their state:

| Step | Content | State |
|---|---|---|
| P1 | climate `esm-picontrol` 1601–1610 for ec-earth3-esm-1-1 (existing producer) | done 2026-10-17 (job 43339587, 70 files passed, commit `bb8cd76`); the other years in P5 |
| P2 | climate producer: spin-up start years copied from the cycle year (`--start-years`, `--cycle-window`), verifier check `start_year` (`workflow/04_forcing/climate/README.md`); start year 1591 of the natural-run spin-up | code `a86aaf9`; code-equivalence entry `start-years-climate` (user, 2026-10-20); start year 1591 added to the units (user, 2026-10-20) |
| P3a | renderer: climate start years in the cycle rule, spin-up output (`output.spinup`), no run check for spin-ups | code `e3ec0f3` |
| P3b | production spin-ups: continuation blocks (run ID `<segment-id>__block-<n>`, user 2026-10-17), convergence test of D19 (rules: user, 2026-10-22; amended 2026-11-02, task X), warm start from a chunked run | code `30d4ff6`; tried on the natural-run spin-up (not converged after 10 years, as expected). One climate window per spin-up chain (D19 amendment of 2026-10-22: `2021soc` cycles 1800–1849): done in task S |
| P4 | natural-run spin-up of task L: campaign `natural-spinup` (1591–1600, cycle 1601–1610, `1850soc` land use, routing and land use only) | done 2026-10-22 (job 43374681, 8.2 h, 45 min per model year; renderer fix `9bdd46a`); its end state starts the natural run of task Q |
| P5 | climate for the production campaign of D02 (released by the user in batches, 2026-10-22 and 2026-10-25): `esm-picontrol` 1611–1650, start years 1551 and 1576, 1800–1849, 1651–1799, 1850–2100; `esm-scen7-vl` and `esm-scen7-h` 2022–2100 | done 2026-10-30: `esm-picontrol` 1551, 1576, 1591 and 1601–2100 (503 years per variable, 6.2 TB) and both futures 2022–2100 passed, all seven variables (jobs 43423709, 43424190, 43424270, 43427422, 43440164, 43426662, 43431185); lwdown range of the verifier raised to 650 W m-2 (`20a59d4`, code-equivalence entry `lwdown-range-climate`), lwdown verified again with it (vl 43432908, h 43433722, picontrol 43518194, 43518409, 43519881) |

**Spin-up output (D19 spin-up rule 3, user 2026-10-17).** A spin-up writes only the monthly variables listed under
`output.spinup.monthly` of the campaign (one file per year, `output/monthly.<year>-01.nc`): the variables of the
convergence test (soil moisture per layer, snow water equivalent for the December values, river and reservoir storage,
irrigation withdrawal of the `2021soc` chain) and others the campaign adds. Monthly values are needed for December snow
water equivalent; the annual values are formed by the convergence test. The renderer stops when a spin-up run has no
`output.spinup`, when it lists a stream other than `monthly`, or when it asks for a variable of a plugin that is off
(VIC would drop it with a warning only). A campaign of spin-ups alone needs no ISIMIP output selection; the protocol
coverage and stream checks apply to the other runs. `submit_run.py` submits no run check (`check_run.py` reads the daily
and monthly ISIMIP outputs) after a spin-up but the convergence test (below).

**Climate window per chain (D19 amendment 2026-10-22, task S).** `spinup.climate_cycle` is one window `[first, last]`
for every spin-up chain (campaign `natural-spinup`: `[1601, 1610]`) or a map spin-up DHF scenario → window (production:
`1850soc: [1601, 1650]`, `2021soc: [1800, 1849]`); a map must name exactly the DHF scenarios of the campaign's spin-ups
(`resolve_campaign.climate_window`, `check_climate_windows`), and the renderer links the climate of a spin-up run with
the window of its scenario. With the window 1800–1849 the `2021soc` blocks 1800–1849 and 1825–1849 link every year to
the `picontrol` year of the same number (identity), so no climate start years are needed (D20 amendment 2026-10-22).

**Spin-up blocks (D19 spin-up rule 3, D20 decision 3; campaigns without a restriction).** The campaign sets
`spinup.length_years` (first block, e.g. 50), `spinup.block_years` (continuation blocks, e.g. 25) and
`spinup.max_blocks` (e.g. 8). A spin-up segment is run block by block, each block its own run: block 1 has the
segment ID and covers the segment years (1551–1600 or 1800–1849); block n ≥ 2 has the run ID
`<segment-id>__block-<n>` (`docs/directory-contracts.md`, `runs/`), the years of the last `block_years` before the
chain start (1576–1600 or 1825–1849) and starts from the end state of block n − 1 (`parent.previous_block` in its
manifest; the D19 dam checks apply). Each call of the renderer (`submit_run.py --campaign`) looks at the blocks on
disk (`render_run.spinup_next`): no block → block 1 (cold start or `initialisation.state_of_run`); the last block
completed and its convergence test `failed` → the next block; `passed` → no block, and the children of the
spin-up (pre-industrial, or the `2021soc` historical segments) start from that block's end state; the last block not
completed, its test not run, or its test `not_checked` (it could not be evaluated: a short file, a missing value) → the
spin-up and its children are left out of the call with a note and the other runs of the call go on (review 2026-11-01
R3, R6: before, the render stopped after earlier runs of the call were already written, which the next call refused
as existing); a test run from code that was not committed (production campaign), an unknown test status or
`max_blocks` reached → the render stops with the reason. Children of a spin-up that has not converged, and their
children, are left out of the call with a note. Each next block is submitted by hand (user, 2026-10-22).

**Convergence test (`monitor/check_spinup.py`, D19 spin-up rule 3 as amended on 2026-11-02; the rules of 2026-10-22
could not pass on a converged spin-up, review 2026-11-01 R1).** Submitted by `submit_run.py` after the last job of every
spin-up block (`submit_check.py --spinup`, job `spinup-check-...`). Window: the 25 annual values of the block (the last
25 years of the first, 50-year block). Per active grid cell, for soil moisture of layers 2 and 3 (annual means),
December snow water equivalent without the perennial-snow cells (monthly snow water equivalent never below 1 mm in the
window years; they stand in for the glacier cells of D18) and river storage: the least-squares slope of the 25 values
divided by the standard deviation of the detrended values (ddof 2) must not exceed 0.1 per year (a constant cell passes
when its slope is zero); a quantity passes when at least 80 % of its active cells pass. Reservoir storage (dams on)
and, for `2021soc`, irrigation withdrawal are tested as global totals under the same rule and must pass. The block has
converged (`passed`, exit status 0) when every one of these quantities passes, has not converged (`failed`, exit status
3, a warning in Slurm: the next block follows) otherwise; a test that could not be evaluated (a short file, a missing
variable or value) is `not_checked` (exit status 4) and the chain is not continued until the block has been looked at.
The global area-weighted series of the per-cell quantities and the 20 largest river basins of the routing network are
diagnostics in the CSV and figures only. Results in `qc/runs/<campaign>/<run-id>/` (`summary.json` with the fraction
of cells passed per quantity, `reports/convergence.json`, `reports/convergence_annual.csv`,
`figures/convergence_{global,basins}.png`, `figures/convergence_map_soil_moisture_layer3.png` with the per-cell slope
ratio, where the slow drift of arid regions shows); from a repository that is not clean they go to
`scratch/spinup-check/uncommitted/` and the block has no test.

**Outputs by period (D03 decision 2, task S).** `output.period_outputs` (`{stream: {period: [OUTVAR]}}`) adds VIC
outputs to a stream of the runs of the named periods only (`pre-industrial`, `historical`, `future`; spin-ups write
`output.spinup` only). The production campaign adds `OUT_SOIL_MOIST`, `OUT_EVAP` and `OUT_WITHDRAWN` to the daily stream
of the historical and future segments (1850–2100, every climate scenario, `picontrol` included); the pre-industrial
segment writes daily only `qtot` and `dis` (`OUT_RUNOFF`, `OUT_BASEFLOW`, `OUT_DISCHARGE`), and the monthly stream is
the same in every period. The file names and the expected outputs do not change; `run_manifest.py complete` checks
every OUTVAR of the run's VIC file in its stream. The renderer stops when a stream is not one of `output.streams`, a
period is unknown, a list is empty or a variable belongs to a plugin that is off.

## Production campaign (task S)

Classification: workflow (user, 2026-10-28). Campaign `water-global-ec-earth3-esm-1-1`
(`configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`, `production: true`): D02 scope, every `water_global`
experiment except the two `extrasoc` ones (D06), 16 experiments, 22 segments, 2408 model years with the two 50-year
spin-ups; `run_order: longest-chain-then-priority`; both spin-ups cold starts (user, 2026-10-28), 25-year continuation
blocks up to 8 blocks, climate window per chain; routing, irrigation, dams, water use with non-renewable withdrawal
(user, 2026-10-28: without it the groundwater demand cannot be met; no limit on the deficit) and land use; output as
D03 with `OUT_NONREN_DEFICIT` monthly, also in the spin-ups (not part of the convergence test). Dry run of the resolver
(2026-10-28; nothing rendered, nothing submitted):

```bash
python3 workflow/05_simulation/render/resolve_campaign.py --campaign configs/campaigns/water-global-ec-earth3-esm-1-1.yaml
```

The render needs the production build and the production parameter set. The build of the frozen commit `a826251b`
was compiled on 2026-10-31 (D01 amendment 2026-10-31; the build of `39e21ff5` promoted on 2026-10-30 by
`build/promote_build.py` no longer matches the lock), and `parameters/production/vic-global-5arcmin-version-a/`
was promoted by `workflow/03_parameters/promote_parameter_set.py` (task R) with the D19 dam files
`dams/vic_global_5min_dam_parameters_isimip4b_{histsoc,1850soc,2021soc}.nc` (task L2) and the FILE decomposition
rebuilt for them, `routing/vic_global_5min_file_decomposition_wateruse_isimip4b-dams.nc`
(`workflow/03_parameters/routing/build_decomposition.py`, task L3), which the campaign names.
`configs/resources/vic-global-5arcmin.yaml` still plans 3.0 h per model year (D02 measured 1.14 h, about 1.4 h with the
D03 daily outputs); it is not changed by task S. Its `chunk_years` became 25 on 2026-11-01 (task V, D20 amendment
2026-11-01); since then both spin-ups render (scratch render of a copy of the campaign: two chunks each, 77 h per
chunk, cold start, 1850soc year 1591 linked to `esm-picontrol` 1641).

| Step | Content | State |
|---|---|---|
| S1 | one climate window per spin-up chain (resolver, renderer) | done |
| S2 | outputs by period (`output.period_outputs`, D03) | done |
| S3 | production campaign file, run order, resolver dry run | done (not rendered) |
| S4 | production build: `build/promote_build.py`, production campaigns need `build_kind: production` | done: `builds/vic/39e21ff5…/` promoted 2026-10-30 (user's authorisation, from `a6761b7`), not recompiled; since D01 amendment 2026-10-31 the production build is `builds/vic/a826251b…/` (compiled, task L5) |

## Natural run (task Q)

Classification: workflow (user, 2026-10-22). Campaign `natural-run` (non-production): the historical segment 1850–2021
with `esm-hist` climate and `histsoc` land use, routing and land use only, warm-started from the end state of the
natural-run spin-up (campaign `natural-spinup`, D19 warm-start rule), in chunks of 20 years. Its discharge gives task L
the dam service maps (D19; mean 1992–2021) and multi-year daily means of discharge, runoff and baseflow (daily
`OUT_DISCHARGE`, `OUT_RUNOFF`, `OUT_BASEFLOW`, user 2026-10-22). The output selection is that of campaign `smoke`
without the variables of the plugins that are off (listed under `not_provided`); `check_run.py` skips the water-use
checks of such a run. The `esm-hist` climate unit was extended with 2021 for this run (user, 2026-10-22).

## Pre-production review fixes (task X)

Classification: production workflow code (user, 2026-11-02). Implements the fixes of the read-only pre-production code
review of `workflow/05_simulation` and `workflow/common` of 2026-11-01 (findings R1–R20; the user decided on
2026-11-02 how each is handled). Branch `task-x-review-fixes`, worktree `scratch/review-fixes/repo`. Steps and their
state:

| Step | Finding | Content | State |
|---|---|---|---|
| X1 | R3 (P1) | `render_run.spinup_next`: a spin-up whose latest block has not completed, whose test has not run or could not be evaluated is left out of the call (with its children) instead of stopping the render after earlier runs were written; `max_blocks`, an uncommitted test and an unknown status still stop | done; test with two spin-ups in different states |
| X2 | R6, R17 (P2/P3) | `check_spinup.py`: a test that cannot be evaluated is `not_checked` (exit 4), not `failed`; not converged exits 3 (warning), 1 only for errors of the test | done |
| X3 | R7 (P2) | `run_manifest.py`: `verify-inputs`, `complete` and `rescan-logs` change the manifest under the run lock (blocking flock on the run directory), so a submission of a later chunk cannot write over them; `complete` gathers everything first and holds the lock only for the write | done; write-order tests |
| X4 | R15 (P3) | `submit_run.submit`: any error between `sbatch` and the release cancels the held job | done |
| X5 | R5 (P2) | `--retry` refuses a dirty repository for a production run; `verify-inputs` and `complete` record (commit, dirty); `check_run.py` records (commit, dirty), writes to `scratch/run-check/uncommitted/` when dirty, binds `summary.json` and `reports/check.json` to the attempt (number, job id, status) and the sha256 of the end state, takes its note from `production`, writes both files atomically (`common.qc.write_json`); the whole-run check counts a chunk summary only when bound to the chunk's completed attempt | done |
| X6 | R4 (P2) | `submit_check.py`: wall time of a check scaled with its years (chunk check and unchunked run 1 h + 15 min/year, whole-run check of a chunked run 1 h + 2 min/year, never below 4 h; measured: natural-run chunk checks 50–83 min for 20 years without water use, production-config-check 13.7 min for 2 years with water use, natural-run whole-run check 2:49 h for 172 years) | done |
| X7 | R2 (P1), R16, R18 | recovery after a failed job: `run_manifest.reconcile` (attempts still `submitted`/`running` compared with `sacct`; ended jobs get `timeout`/`cancelled`/`failed` with the final rows and a reason; pending jobs with `DependencyNeverSatisfied` are cancelled and recorded); `submit_run.py --reconcile`, `--resume`, `--retry --dependency`, reconciliation before every retry; the campaign ledger `runs/<campaign-id>/recovery.json` (contract change proposed to the user: the only file at the campaign level); every submission with a dependency uses `--kill-on-invalid-dep=yes` (run jobs through `sbatch`, check jobs as an `#SBATCH` line: R18 covered); `vic_run.sbatch` gets `--signal=B:TERM@900` and a trap that stops VIC and runs `complete --exit-code 143 --reason "signal TERM: time limit or cancel"` (the completion step reads `sacct`, the logs and the output file names: well within 900 s); R16: the job records its own `sacct` rows as `scheduler_at_completion`, the check job and the reconciliation store the final rows as `scheduler` under the run lock | code and unit tests done; the real time-out test on the smoke campaign (short wall time) waits for the user's go-ahead |
| X8 | R8 (P2) | `check_run.py`: over every active cell and month of a chunk or unchunked run the 99th percentile of \|`OUT_WATER_ERROR`\| (monthly mean, mm) must not exceed 1 mm (user, 2026-11-02; task T outlier rule); p99, p99.9, the maximum and the count of cell-months above 1 mm are recorded, per year the maximum, the count and the closure P − ET − qtot − dS (dS from the December monthly-mean storage of consecutive years, approximate); part of the check status | done; needed before the first reported segment, not for the spin-ups |
| X9 | R11 (P3, user) | `verify-inputs` checksums only the forcing files of the chunk's own years (the links of its forcing view) plus the parameters, the executable and the parent or previous-chunk state; the whole-run set stays in the render fingerprint | done |
| X10 | R19 (P3, common) | `common.provenance.unit_lock` (flock on the unit directory) around `set_qc`; `common.unit_extension.write` (the producer's final write of a unit record under the lock, merged with what another job wrote meanwhile) used by the climate, land-use and water-use producers; `common.jobrecord` writes `job.sbatch` and `job.yaml` atomically; `submit_check.py` submits through `jobrecord` | done; code-equivalence entries `unit-lock-{climate,landuse,water-use}` (approval and the before/after evidence are the user's call) |
| X11 | R20 (P3) | `tests/unit/workflow_paths.py` puts `workflow/` on the module path for every test module (`python -m unittest discover -s tests/unit` without `PYTHONPATH`); tests for R3, R5, R7; the pre-commit hook warns when `workflow/common` or a forcing producer changes without a new code-equivalence entry | done |
| X12 | R9 (docs) | operation rule: the forcing units of a campaign are frozen while its chains run (below) | done |
| X13 | R1 (P1) | `check_spinup.py` under the D19 amendment of 2026-11-02 (25-year window, per-cell slope ratio with ddof 2, 80 % of the cells, global totals for reservoir storage and irrigation withdrawal, basins diagnostic only, map of the layer-3 ratio) | done; unit tests with synthetic fields |
| — | R10, R12, R13, R14 | not changed (user, 2026-11-02): non-unique job names are not important; a changed executable or parameter set between renders means rerunning everything by hand anyway; `check_nonrenewable_output` ignoring `output.spinup` has no effect on this campaign; `conda deactivate` under `set -u` was tested on 2026-11-02 in a clean environment (`env -i`) and in the login environment and succeeds after a `set +u`-wrapped `conda activate` | not changed |

**Operation of a campaign (R9, user's rules).** The forcing units of a campaign are frozen while its chains run: any
extension or re-verification of a land-use, water-use or climate unit puts the unit at `not_checked` until its verifier
passes (`common/unit_extension.py`, `run_manifest.units_not_accepted`), and a chunk that starts in that window fails its
input check and strands its chain. Extensions and re-verifications (e.g. the UKESM start years later, which touch the
shared land-use and water-use units) happen only before a campaign starts or after it ends. The production campaign
starts only after task W is fully accepted.

**Recovery after a failed job (R2).** A chunk that fails, times out or is cancelled leaves the chain behind it
pending (Anunna's Slurm has `DependencyParameters=(null)`); since task X a dependent of a failed job is cancelled by
Slurm (`--kill-on-invalid-dep=yes`), and a time limit or cancel is recorded by the job itself (TERM trap, exit code 143).
Procedure:

1. `submit_run.py --reconcile <campaign-id>` (or one run directory): every attempt still `submitted` or `running` is
   compared with `sacct`; ended jobs are recorded with their state and reason, jobs waiting forever are cancelled; the
   ledger `runs/<campaign-id>/recovery.json` lists every attempt that ended without completing (run, chunk, years, job,
   state, reason, the jobs cancelled after it, the resume command) and which attempt resumed it.
2. Read the reason in the ledger or in the attempt (`failure_reason`, `scheduler`, `log_scan`, the job's `slurm-<id>.err`).
   A time-out of a chunk whose wall time was too short is retried with `--rerender-job` after the resources were
   changed; an input mismatch or a VIC error needs the user first.
3. `submit_run.py --resume <campaign-id>`: every stranded run (an attempt that ended without completing, nothing
   running) is resubmitted from its first incomplete chunk, parents first; a run whose parent has not completed waits
   for the parent's job (its running job, or the job resubmitted in the same call). Single runs:
   `submit_run.py --retry runs/<campaign-id>/<run-id> [--dependency <job-id>]`; a production run only from a clean
   repository.
4. The check of a resumed run follows as usual; the convergence test of a spin-up block is submitted by the retry of
   its last chunk.

## Submit (`submit/`)

| File | Role |
|---|---|
| `submit_run.py` | renders the runs of a campaign (label), or the next block of a spin-up, and submits each job on hold (a spin-up with the convergence test instead of the run check), records the attempt, releases it (the run directory is locked meanwhile, so a second submission of the same run stops, and a manifest write never drops a recorded attempt; any error between `sbatch` and the release cancels the held job); a run whose parent is submitted in the same call waits for it (`afterok`, with `--kill-on-invalid-dep=yes`, so a dependent of a failed job is cancelled by Slurm instead of waiting forever); `--retry <run-dir>` reconciles the run with the scheduler (below) and resubmits an unchanged run as a new attempt (a production run only from a clean repository), `--dependency <job-id>` lets its first job wait for that job; `--retry <run-dir> --rerender-job` first renders only the Slurm job file again from the current template and resources (how the run is executed, not what it simulates), keeping the previous one as `config/job.attempt-<n>.sbatch` and recording it under `job_files`; the new job file is checked like a render (resources modules = build `runtime_modules`, MPI tasks ≤ the decomposition groups recorded in `resolved.yaml`); `--reconcile <campaign-id or run-dir>` and `--resume <campaign-id>`: recovery after a failed job (below) |
| `run_manifest.py` | `verify-inputs` (job step before VIC: checksums of the parameters, the executable, the forcing files of the chunk's own years and the parent or previous-chunk state file; every forcing unit still accepted; every forcing-view link of the chunk points to its recorded source; records the commit and Git state of the code) and `complete` (job step after VIC, also on failure and after the TERM signal of a time limit or cancel; every OUTVAR of `vic_global.txt` must be in the output files of its stream, since VIC drops an unknown OUTVAR with only a warning; exit status 1 when the attempt failed); both change the manifest under the run lock, so a submission of a later chunk never writes over them; `reconcile` and `record_scheduler` (used by `submit_run.py` and the check job) store the final scheduler rows of ended jobs |

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
| `check_run.py` | for a chunked run `--chunk <id>` checks one chunk (its years and end state, no GRDC), and the check without `--chunk` covers the whole run (GRDC comparison of all years, end state, every chunk check passed, each counted only when its summary is bound to the chunk's completed attempt); the summary names the attempt, its job and the sha256 of the end state it checked, the commit and whether the repository was clean (from a repository that is not clean the results go to `scratch/run-check/uncommitted/` and do not count), and the check job stores the final scheduler rows of the run job in the attempt; checks of a finished run per year: coverage of active cells, annual `qtot`, water balance (global P, ET, qtot, monthly storage, the closure P − ET − qtot − dS from the December storage of consecutive years, zonal means, `OUT_WATER_ERROR` as a monthly mean: its largest value and the cell-months above 1 mm), and over the whole chunk or run the 99th percentile of |`OUT_WATER_ERROR`| over all active cells and months, which must not exceed 1 mm (the task T outlier rule; user 2026-11-02; p99, p99.9, the maximum and the count above 1 mm are recorded; part of the check status), largest outlets, irrigation (withdrawal, requirement, received), municipal and manufacturing demand (forcing and VIC) and withdrawal, water-use budget per cell and month (withdrawn ≤ demand, consumed ≤ withdrawn, GW + SURF + DAM + TREM + NREN = `OUT_WITHDRAWN`, the definition of `wu_output.c` under GWM FALSE; a missing monthly water-use value on an active cell fails it and stays missing, not zero, in the derived file), the non-renewable deficit at the end of each month when `OUT_NONREN_DEFICIT` is written, end state; GRDC comparison for the whole run. The water-use parts (budget, sectors, derived file, water-use figures) run only when the run's water-use plugin is on and the irrigation results only when its irrigation plugin is also on (`config/resolved.yaml`; a natural run has neither and writes none of their outputs) |
| `run_figures.py` | the derived file `reports/water_use_by_sector_<year>.nc` (monthly withdrawal per sector municipal, manufacturing, irrigation and its sources groundwater, surface, dam, remote, nonrenewable; VIC demand and estimated consumption for municipal and manufacturing; VIC-WUR writes the sources per sector but no sector total) and the figures of water use by sector and source, source shares, sector maps, distributions of withdrawal/demand and of remote and groundwater shares, and the water balance |
| `grdc.py` | GRDC daily export (`raw/external/grdc/export-2024-11`, `manifests/inputs/grdc.yaml`): station files, upstream area along the routing network, station-to-cell mapping (closest upstream area within 3 cells, area error ≤ 30 %), monthly means (≥ 20 valid days) and climatology (≥ 5 years per month) |
| `compare_runs.py`, `compare_runs.sbatch` | compares the output (every variable, time step and active cell) and the end states of two completed runs over their common years, chunked or not (`--submit`: Slurm job with job record under `logs/05_simulation/`); report `qc/<run>/reports/compare_<other run-id>.json`, status passed when bitwise identical, warning with the size of the differences otherwise; used for campaign `chunk-test` (a chunked run against the same run in one job) |
| `check_spinup.py`, `check_spinup.sbatch` | convergence test of a spin-up block (D19 as amended 2026-11-02; see "Spin-up runs (task P)"), submitted with `submit_check.py --spinup`; exit status 0 converged, 3 not converged, 4 not evaluable |
| `check_run.sbatch`, `submit_check.py` | Slurm job of the check (one core, about 7 min and 13 GB for one year), rendered and submitted through `common.jobrecord` with the job record under `logs/05_simulation/<job-name>_<slurm-job-id>/`; the dependency is an `#SBATCH` line of the job file with `--kill-on-invalid-dep=yes`; `submit_run.py` submits it after every run job, to start when the run has succeeded; job name `run-check-<campaign>-<label>`, or the run ID with hyphens for a production run; wall time scaled with the years of the check (chunk check and unchunked run 1 h + 15 min per year, whole-run check of a chunked run 1 h + 2 min per year, never below 4 h; `--time` overrides it; the convergence test keeps 4 h); the job ends FAILED when the check fails (exit status 1) |

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
| `status` | `rendered`, `submitted`, `running`, `completed` or `failed` (of the last attempt; a chunked run is `completed` when every chunk is, `failed` when the latest attempt of a chunk failed, timed out or was cancelled) |
| `end_state` | run-relative path of the end state (in the last chunk of a chunked run) |
| `chunk_years`, `chunks[]` | chunked runs: per chunk `id` (`<start>-<end>`), years, `dir`, `init_state`, `job_file`, `expected_outputs`, `end_state`, `wall_time_hours` |
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
| `attempts[]` | `chunk` (chunked runs), `attempt`, `slurm_job_id`, `submitted_at`, `submitted_by_commit`, `code_dirty`, `dependency`, `inputs_fingerprint`, `input_verification` (files, mismatches, `verified_by_commit`, `verified_by_code_dirty`, `parent_state`, for a later chunk `chunk_state`: the previous chunk's end state and its sha256), `output_variables` (per stream: requested OUTVARs and the missing ones), `started_at`, `ended_at`, `vic_exit_code`, `scheduler_at_completion` (sacct rows as seen by the job itself: state RUNNING, partial elapsed time), `scheduler` (the final sacct rows: state, exit code, elapsed, MaxRSS, nodes, written by the check job or by a reconciliation; manifests before 2026-11-02 hold the rows seen by the job under this name until a reconciliation moves them), `reconciled` (when a reconciliation set the status: time, state, end, elapsed, nodes), `vic_timing` (VIC timing table and model cost), `log_scan` (warning and error lines by category), `outputs_present`, `outputs_complete`, `output_bytes`, `completed_by_commit`, `completed_by_code_dirty`, `status` (`submitted`, `running`, `completed`, `failed`, `timeout`, `cancelled`), `failure_reason` |

Tests: `tests/unit/test_simulation_resolve.py`, `tests/unit/test_simulation_render.py`,
`tests/unit/test_simulation_submit.py`, `tests/unit/test_simulation_retry.py`, `tests/unit/test_simulation_chunks.py`,
`tests/unit/test_simulation_recovery.py`, `tests/unit/test_run_check.py`, `tests/unit/test_run_check_job.py`,
`tests/unit/test_run_check_water_use.py`, `tests/unit/test_simulation_promote_build.py` (run with
`python -m unittest discover -s tests/unit`; `tests/unit/workflow_paths.py` puts `workflow/` on the module path).

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

