# 03 Parameters — domain

The `domain` component of a parameter set, `parameters/<status>/<set>/domain/vic_global_5min_domain_nogl.nc`
(read by VIC with `DOMAIN`), is **adopted** (copied from `vic_coupled`, recorded in
`manifests/parameters/<set>.yaml`); it has **no producer here**. This directory holds its verification, and the
shared parts and the Slurm job of the verifiers of all adopted components (`domain`, `routing`, `irrigation`,
`water_use`).

Classification: production workflow code (user, 2026-10-24, task R): the QC evidence every component needs before
a parameter set is promoted to `production/` (D01).

| File | Role |
|---|---|
| `verify_domain.py` | independent verification of the domain file; writes `qc/parameters/<status>/<set>/domain/` |
| `adopted.py` | shared by the four verifiers: manifest entry and file integrity (md5, size, modification and status-change times against the manifest), domain grid, variable and lat/lon checks, QC directory, report, summary and exit status, maps |
| `adopted_qc.sbatch` | Slurm template: runs the four verifiers one after the other (each runs whatever the others found); the job ends with the worst status |
| `submit_adopted_qc.py` | renders and submits the job, job record under `logs/03_parameters/adopted-parameter-qc-<set>_<slurm-job-id>/` |

The verifiers of the other components are `../routing/verify_routing.py`, `../irrigation/verify_irrigation.py`
and `../water_use/verify_water_use.py`. Tests: `tests/unit/test_adopted_parameter_qc.py`.

## Checks (verify_domain.py)

The checks are computed here from the stored values, not with VIC's reader (`get_global_domain.c` at VIC
`39e21ff5` reads `mask` as int, `area` and `frac` as double, and lat/lon).

- `integrity` (every verifier): md5 and size of every file of the component equal the manifest; the modification
  day is not after the adoption day and, for the main file, equals `source_mtime` (the copies kept the source
  time); a status-change time (ctime) after the adoption day is a warning (changing permissions also sets it).
- `vic_variables`, `grid`: the variables with their dimensions; lat and lon strictly monotonic with a step of
  1/12° and cell centres at k/12 + 1/24°.
- `forcing_grid`: lat and lon equal exactly those of the first file of every forcing unit under `forcing/`.
- `mask`: only 0 and 1, and 2 188 551 active cells (D08: the domain is fixed).
- `area`: > 0 and not fill on every active cell, and within 0.1 % (relative) of an own cell area, the spherical
  cell area with the authalic radius 6 371 007.2 m or the WGS84 ellipsoidal cell area; the report says which one
  the file follows. Figure `figures/area_deviation.png`.
- `frac`: in [0, 1] and not fill on every active cell. Figure `figures/frac.png`.

## Status, exit status and the manifest

Each check has a status of `common/qc.py` (`passed`, `warning`, `failed`, `not_checked`), or `not_applicable` for
a check the file cannot support (listed, not counted); the verifier exits with 0 passed, 1 failed, 3 warning,
4 not_checked. The verifiers write only their QC directory `qc/parameters/<status>/<set>/<component>/`
(`summary.json`, `reports/verify.json`, `figures/`); they never change a parameter file or the manifest. After a
committed run has been reviewed, `qc_status` and `qc_evidence` of the component are set in the manifest by hand.

## Running

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/domain/submit_adopted_qc.py                 # all four components
python3 workflow/03_parameters/domain/submit_adopted_qc.py --components routing
```

One core, about 2 GB per verifier (routing reads the 49 unit-hydrograph steps one at a time) and less than an hour.
From a repository that is not clean the results go to
`scratch/adopted-parameter-qc/verify-uncommitted/qc/parameters/<status>/<set>/<component>/` and count for nothing
(rule 14); from a clean repository the verifiers stop if the repository is no longer clean at the submitted commit
when the job starts.

## Decisions

D01 (decided 2026-10-28, VIC `39e21ff5` frozen): the reader rules checked here are those of that commit. D08 fixes the
domain and its 2 188 551 active cells.
