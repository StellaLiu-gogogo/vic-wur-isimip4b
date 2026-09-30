# 04 Forcing — land use

Converts ISIMIP4b `landuse-15crops` and `landuse-urbanareas` 15′ annual
fractions into VIC-WUR 5′ annual 16-class coverage (`LANDUSE_FORCE` YEAR
contract), one forcing unit per soc scenario under
`workdir/forcing/landuse/<soc-scenario>/`.

| File | Role |
|---|---|
| `isimip_landuse_to_vic_annual.py` | producer: allocation (joint order-free water-filling, fallback chains, single-child rule, natural remainder by the VIC 2003–2022 mean composition), writes `coverage_<soc>_<year>.nc`, `provenance.yaml`, and per-year ledger and QA JSON under `qc/forcing/landuse/<soc>/reports/` |
| `verify_forcing.py` | independent verification with its own code path; writes `verify_<year>.{json,png}` and `summary.json` under `qc/forcing/landuse/<soc>/` and sets `qc.status` in the unit's `provenance.yaml` (`passed` only when every file of the unit passes) |

Method version `1.2` is recorded in every file; bump `METHOD_VERSION` when
results change for identical inputs. Version 1.2 applies D04: every fallback
parent (no VIC weight for the class) receives its whole target in a single
child (`--small inf`, the default); `--small 1e-3` reproduces the 2026-09-23
prototypes.

## Inputs

- `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-{15crops,urbanareas}_*_15arcmin_annual_*.nc`
- `raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_<2003..2022>.nc` (within-parent weights)
- `parameters/<candidates|production>/<parameter-set-id>/domain/vic_global_5min_domain_nogl.nc`

The weights cache `scratch/landuse-converter/vic-coverage-mean-2003-2022-weights.npz`
is rebuilt when absent; it moves to `intermediate/` once `workflow/common/cache.py`
exists.

## Running

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py --scenario histsoc --years 1850-2021
python3 workflow/04_forcing/landuse/verify_forcing.py --scenario histsoc
```

About 2 min per year on a login node (one core, ≈6 GB); full histsoc
(172 years) belongs in a Slurm job with a job record under
`logs/04_forcing/` (template to be added with the first production run).

If the repository is not clean, the producer writes to
`scratch/landuse-converter/<soc>/` instead of the forcing unit and records
`code_dirty: true`; verify such output with `--unit-dir`.

## Decisions

D04 (decided 2026-09-30, `docs/decisions/D04-landuse-harmonization.md`) is
implemented here: single child for every fallback parent, `rice_rainfed` in
class 12, `*_bf` merged into the rainfed and irrigated sums, ISIMIP paddy
area accepted. D01 (model commit) is provisional; a unit is promoted for
production only after D01 is frozen.
