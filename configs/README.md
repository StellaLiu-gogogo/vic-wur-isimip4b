# Configurations

This directory contains structured definitions used to render and execute campaigns. Configuration expresses intended behavior; it is not a record of what actually happened.

## `campaigns/`

One definition per campaign (see `docs/glossary.md`). A campaign definition states:

- the model build (`model/vic.lock.yaml` commit) and parameter-set ID;
- the ISIMIP protocol commit whose experiment definitions are used;
- the GCMs;
- the selection of ISIMIP experiments to simulate, e.g. all `water_global` experiments of a given priority or an explicit list of experiment IDs;
- explicit exclusions with their justification, e.g. `2021co2` experiments are identical to `default` for VIC-WUR because the model has no CO₂ response;
- initialization, output, and other run choices that are not defined by the protocol.

A campaign definition does not list segments. The workflow derives segments, their periods, and their parent segments from the protocol experiment definitions (`workflow/05_simulation/render/`). The complete resolved configuration is saved with each run.

Each production campaign must be self-contained enough to review without relying on hidden scientific defaults.

Keys of a campaign file (checked by `workflow/05_simulation/render/resolve_campaign.py`; `configs/campaigns/smoke.yaml` is an example):

| Key | Content |
|---|---|
| `campaign_id` | equals the file name |
| `production` | `true` for production campaigns; only non-production campaigns may carry a `restriction` |
| `model` | `lock` file and `commit` (must equal `model/vic.lock.yaml`), driver, coupling |
| `parameter_set` | `id`, `status`, and `files`: role (`domain`, `parameters`, `routing`, `decomposition`, `irrigation`, `water_use`) → file inside the set; `dams`: soc scenario of a segment → dam file inside the set, one entry for every soc scenario the campaign simulates (D19; the files share one dam list) |
| `protocol` | `path` (under the workdir), `commit`, `simulation_round`, `sector` |
| `gcms` | per GCM `climate_input`: `concentration-driven` or `emission-driven` (selects the input alias) |
| `experiments` | `ids: [...]`, `priority: [...]` or `all: true` |
| `exclusions` | list of `{experiment, reason}` |
| `sensitivity_equivalence` | sens scenario → `{same_as, reason}` (e.g. `2021co2` → `default`) |
| `restriction` | non-production only: `periods` and `runs: {<label>: {years: [start, end]}}`; a run may set `chunk_years` (test of chunked runs, campaign `chunk-test`) |
| `initialisation` | `without_parent`: `cold_start` (no INIT_STATE) or `state_of_run` (the end state of an earlier, completed run: `state_of_run` with `run_dir` under `runs/`, `state` inside it, and `reason`); `state_at_end` |
| `spinup` | `length_years` (first block) and `climate_cycle` `[first, last]` (null when the campaign simulates no spin-up); for a campaign without a restriction also `block_years` (continuation blocks) and `max_blocks` (D19, D20; `workflow/05_simulation/README.md`, "Spin-up blocks") |
| `dhf_forcing` | `units` (segment soc scenario → land-use and water-use unit) and `constant` (scenarios constant in time) |
| `plugins` | switches and settings of routing, irrigation, dams (operation constants), water use (sectors, withdrawal options, `nonrenewable_limit_mm`: limit of the non-renewable deficit in mm, null for none), land use, EFR, WOFOST |
| `output` | format, compression, file frequency, streams, aggregation overrides, `isimip` (protocol variable → VIC outputs, frequency, streams, rule), `diagnostics`, `not_provided` (with reasons; together with `isimip` it must cover every protocol variable of the sector; not needed by a campaign of spin-ups alone), `spinup` (`monthly`: the VIC outputs a spin-up writes, D19; required when the campaign renders a spin-up) |
| `resources` | path of the resource file |
| `open_decisions` | the open decisions the campaign runs under |

## `resources/`

Resource configurations define Anunna execution requirements such as partition, task count, memory, wall time, and job dependencies. They must be organized by workload type or scale rather than by individual developer.

`vic-global-5arcmin.yaml` (one global 5′ VIC-WUR run): `partition`, `constraint`, `nodes`, `ntasks`, `cpus_per_task` (OpenMP threads), `exclusive`, `mem`, `wall_time` (`setup_hours`, `hours_per_model_year`, `max_hours`; per job, i.e. per chunk of a chunked run), `chunk_years` (a longer run is split into chunks of this many years, one job each), `launcher`, `modules` (must equal the build's `runtime_modules`), `check_processes`.

## Rules

- Store YAML or another explicitly documented structured format.
- Validate production configurations before rendering run files.
- Do not maintain segment lists by hand.
- Do not store credentials, logs, generated VIC configurations, or scientific datasets here.
- Do not duplicate campaigns by adding `v2`, `fix`, `new`, `final`, or date suffixes. A campaign with a different model build or parameter set gets a new descriptive campaign ID.
- Do not distribute personal absolute paths across configuration files.
- Save the fully resolved configuration in the corresponding run directory.
