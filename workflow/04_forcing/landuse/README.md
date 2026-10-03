# 04 Forcing — land use

Converts ISIMIP4b `landuse-15crops` and `landuse-urbanareas` 15′ annual
fractions into VIC-WUR 5′ annual 16-class coverage (`LANDUSE_FORCE` YEAR
contract), one forcing unit per soc scenario under
`workdir/forcing/landuse/<soc-scenario>/`.

| File | Role |
|---|---|
| `isimip_landuse_to_vic_annual.py` | producer: allocation (joint order-free water-filling, fallback chains, single-child rule, natural remainder by the VIC 2003–2022 mean composition), writes `coverage_<soc>_<year>.nc`, `provenance.yaml`, and per-year ledger and QA JSON under `qc/forcing/landuse/<soc>/reports/` |
| `verify_forcing.py` | independent verification with its own code path (file format VIC reads, closure, conservation); writes `verify_<year>.{json,png}` and `summary.json` under `qc/forcing/landuse/<soc>/` and sets `qc.status` in the unit's `provenance.yaml` (`passed` only when every file of the unit passes) |
| `landuse_forcing.sbatch` | Slurm template: producer, then verifier, in one job |
| `submit_landuse_forcing.py` | renders the template, submits it on hold, writes the job record `logs/04_forcing/<job-name>_<slurm-job-id>/` (`job.sbatch`, `job.yaml`, scheduler output), releases the job |

Method version `1.4` is recorded in every file; bump `METHOD_VERSION` when
results change for identical inputs. Version 1.2 applies D04: every fallback
parent (no VIC weight for the class) receives its whole target in a single
child (`--small inf`, the default); `--small 1e-3` reproduces the 2026-09-23
prototypes. Version 1.3 (2026-10-02) gives the rounding residual of the
closure step to the largest class a cell already has (natural first);
version 1.2 gave it to class 1 in cells without natural cover, which created
about 22 000 class-1 cells of about 1e-16 cover over 1850–2100 that VIC had to
allocate as tiles. The version 1.2 units were replaced (user, 2026-10-02).
Version 1.4 (2026-10-03) writes the time axis with calendar
`proleptic_gregorian`, the VIC clock calendar of the project; version 1.3
wrote `standard`, and VIC (`plugin_get_forcing_file.c`, commit `39e21ff5`)
aborts at start when the calendar of a plugin forcing file differs from its
clock. The coverage values are unchanged. The verifier now also checks the
format VIC reads (time axis and calendar, dimensions, classes, grid, year).

## Inputs

- `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-{15crops,urbanareas}_*_15arcmin_annual_*.nc`
- `raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_<2003..2022>.nc` (within-parent weights)
- `parameters/<candidates|production>/<parameter-set-id>/domain/vic_global_5min_domain_nogl.nc`

The weights cache `scratch/landuse-converter/vic-coverage-mean-2003-2022-weights.npz`
is rebuilt when absent; it moves to `intermediate/` once `workflow/common/cache.py`
exists.

## Running

A unit is produced and verified by one Slurm job per soc scenario; years are converted in parallel, one
process per year (about 2 min and 6 GB per year on one core; the result does not depend on the number of
processes):

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/04_forcing/landuse/submit_landuse_forcing.py --scenario histsoc --years 1850-2021
python3 workflow/04_forcing/landuse/submit_landuse_forcing.py --scenario histsoc --years 2015-2016 --scratch --scratch-label test
```

`--processes` (default 16) sets the parallel years and `--mem` defaults to 9 GB per process (the
verifier peaks at about 7.4 GB per process); a worker killed by the memory limit stops the job with an error; `--dry-run`
prints the rendered job. The producer and verifier can also be run directly with the same arguments
(`--processes N` on both).

A unit is generated as a whole: the producer refuses to write into an existing, non-empty
`forcing/landuse/<soc>/`; replacing an accepted unit needs the user's authorization. Coverage files are
written under a temporary name and renamed when complete; `provenance.yaml` is written last.

If the repository is not clean, or with `--scratch`, the producer writes to
`scratch/landuse-converter/<soc>/` (with `--scratch-label L`: `scratch/landuse-converter/runs/L/<soc>/`)
instead of the forcing unit (and records `code_dirty: true` when not clean); the submit script then points
the verifier at that directory with `--unit-dir`. Use `--scratch` for every test run so that no test ever
lands in `forcing/`.

## Decisions

D04 (decided 2026-09-30, `docs/decisions/D04-landuse-harmonization.md`) is
implemented here: single child for every fallback parent, `rice_rainfed` in
class 12, `*_bf` merged into the rainfed and irrigated sums, ISIMIP paddy
area accepted. D01 (model commit) is provisional; the land-use units do not
depend on it and may be accepted while it is open (user, 2026-10-01; see
`docs/decisions/open-decisions.md`).
