# 04 Forcing — climate

Converts ISIMIP4b daily 0.5° bias-adjusted atmosphere files into VIC-WUR 5′
daily forcing on the project domain, one forcing unit per VIC variable under
`workdir/forcing/climate/<gcm>/<input-alias>/<variable>/`.

Classification: production workflow code (user, 2026-09-30); its output is
read by `05_simulation`.

| File | Role |
|---|---|
| `downscale_climate.py` | producer: unit conversion, orientation, 0.5° → 5′ remapping, elevation correction, masking; writes `<variable>_<gcm>_<alias>_<year>.nc` and `provenance.yaml` per unit |
| `verify_forcing.py` | independent verification (own code path, cdo for the remapping of sample days); writes `qc/forcing/climate/<gcm>/<alias>/<variable>/{summary.json,reports/,figures/}` and sets `qc.status` in `provenance.yaml` |
| `climate_forcing.sbatch` | Slurm job template (producer, then verifier) |
| `submit_climate_forcing.py` | renders the template, submits on hold, writes the job record `logs/04_forcing/<job-name>_<slurm-job-id>/{job.sbatch,job.yaml}`, releases the job |
| `../../../tests/unit/test_climate_downscaling.py` | unit tests (grid relation, bilinear and conservative remapping against cdo, physics including the `lwdown` ratio against an independent implementation, time axis, variable selection) |

Shared helpers (workdir, checksums, Git state, `provenance.yaml`, QC summary and verifier exit status, job records) come from `workflow/common/` (see its README); the verifier exits with 0 only for `passed` (1 failed, 3 warning, 4 not_checked), and a per-year report counts only for the data files and verifier version recorded in it.

## Method (version 1.1)

The VIC 5′ grid is an exact 6 × 6 subdivision of the ISIMIP 0.5° grid; the
producer derives this from the coordinates and stops otherwise. ISIMIP
latitudes (north to south) are reversed; `lat` and `lon` of every output file
are copied from the domain file, so VIC can match forcing and domain by
position.

| VIC variable | Units | ISIMIP source | Method |
|---|---|---|---|
| `prec` | mm/day | `pr` | × 86400; block replication (= first-order conservative = nearest neighbour for this grid pair) |
| `tair` | degC | `tas` | replication, − 0.0065 K/m × dz, − 273.15 |
| `psurf` | kPa | `ps`, `tas`, `huss` | replication of `ps`; hypsometric equation over dz with the mean virtual temperature T(1 + 0.61 r) of both levels; ÷ 1000 |
| `vp` | kPa | `huss`, `ps`, `tas` | r / (0.622 + r) × psurf, r = q / (1 − q) from bilinear `huss` (mixing ratio constant with height), capped at svp(`tair`) with VIC's svp formula |
| `swdown` | W m-2 | `rsds` | bilinear |
| `lwdown` | W m-2 | `rlds`, `tas`, `ps`, `huss` | R × bilinear `rlds`, R = ε(T₁, e₁) T₁⁴ / (ε(T₀, e₀) T₀⁴), ε(T, e) = 1.08 (1 − exp(−e^(T/2016))) with T in K and e in hPa (Satterlund 1979; Cosgrove et al. 2003, eq. 15; WATCH/WFDE5); level 0: replicated `tas` and e₀ = min(e(r, replicated `ps`), svp(`tas`)), the `vp` method without elevation change; level 1: the written `tair` and `vp`; R = 1 where dz = 0 (D16) |
| `wind` | m s-1 | `sfcwind` | bilinear |

- dz = `elev` of the parameter bundle (5′ mean cell elevation, the one VIC
  uses) − ERA5 surface height (geopotential / 9.80665, first-order
  conservative to the 0.5° grid, replicated to 5′). The ERA5 height matches
  the elevation implied by the ISIMIP surface pressure with an RMSE of 28 m
  (WFDE5 CRU elevation: 66 m).
- Bilinear interpolation uses separable linear weights in latitude and
  periodic longitude; the domain (56°S–84°N) lies inside the ISIMIP grid, so
  there is no extrapolation. No missing values are filled: the producer stops
  if an input cell it needs is missing.
- All variables use the domain mask (D08); values outside it are `1e20`.
  VIC cells outside the ISIMIP `water_global` mask take their own 0.5° cell's
  values (D08, amended 2026-09-30).
- Files: float32, dimensions (time, lat, lon), chunking (1, 1680, 4320), zlib
  level 5 with shuffle; calendar `proleptic_gregorian` (as ISIMIP); time
  `days since <year>-01-01 00:00:00`, one step at 00:00 of each day holding
  that day's mean (ISIMIP stamps 12:00).
- `vp` cap: without it, 1.4 % of the active cell-days of 2015 exceed
  saturation, 99.9 % of them created by lifting to higher 5′ cells (39 % of
  the days where dz > 500 m). VIC-WUR applies the same cap when it reads
  forcing (`drivers/image/src/vic_force.c`, commit `39e21ff5`), so the cap in
  the files changes nothing in the simulation; it makes the files equal to
  what VIC uses (user, 2026-10-01).

### Requirements for the VIC configuration (05_simulation)

- `CALENDAR PROLEPTIC_GREGORIAN`: VIC stops if the forcing calendar differs
  from its clock (`get_forcing_file_info`).
- The 00:00 time stamps are required: VIC takes the first time value as the
  file start and skips `round((model start − file start) × steps per day)`
  records into an unsigned integer (`make_dmy.c`); 12:00 stamps would give
  −1 for a model start at 00:00.
- One `FORCE_TYPE <VAR> <nc_varname> <path_prefix>` line per variable, with
  `<nc_varname>` equal to the unit name (`tair`, `prec`, …) and the prefix
  `<unit dir>/<variable>_<gcm>_<alias>_` (VIC appends `<year>.nc`); daily
  forcing requires a daily snow time step.

Bump `METHOD_VERSION` in the producer when results change for identical
inputs.

## Differences from the WFDE5 5′ reference method

The reference (`nauta008/vic_models/global/5arcmin/forcing/downscale.sh`,
`genweights.sh`) was read as a method description, not reused. Differences:
ISIMIP instead of WFDE5 input; ERA5 orography instead of the WFDE5 (CRU)
elevation as the 0.5° reference; the VIC `elev` parameter as the 5′ target
(identical to the reference DEM within 2.3e-4 m); one mask (the domain) for
every variable instead of the HydroSHEDS mask for four variables and the DEM
extent for three; no `REMAP_EXTRAPOLATE`, `setmisstonn`, or `setmisstodis`;
no weight files (the remapping weights follow from the exact subdivision and
are checked against cdo); Rd/g = 29.27 m/K instead of 29.3; `prec` in
`mm/day`; `vp` capped at saturation; `lwdown` elevation-corrected with the
WFDE5 ratio method (the 5′ reference interpolated it only); explicit
calendar, time axis, lat/lon, chunking, and provenance.

## Inputs

- `raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily/<alias>/<GCM>/<gcm>_*_era5_<alias>_<var>_global_30arcmin_daily_*_*.nc`
  (md5 checked against `manifests/inputs/isimip4b-dkrz-2026-09-21/MD5SUMS`)
- `raw/external/era5-surface-geopotential/cds-2026-09-30/` (`manifests/inputs/era5-surface-geopotential.yaml`)
- `parameters/<status>/<set>/domain/vic_global_5min_domain_nogl.nc` and
  `parameters/<status>/<set>/bundle/vic_global_5min_natural_static_root-b-zeng2001.nc`
  (md5 checked against `manifests/parameters/<set>.yaml`)

The grid relation and dz are kept in
`scratch/climate-forcing/weights/grid-relation-and-dz_<key>.npz`, rebuilt
when absent or when the grids, static inputs, or method version change
(about one minute). Jobs that build it at the same time write separate
temporary files and publish by rename; a file that cannot be read or does
not match is rebuilt. They move to `intermediate/` once
`workflow/common/cache.py` exists.

## Running

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python -m unittest discover -s tests/unit -v
python3 workflow/04_forcing/climate/submit_climate_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-hist --years 2015 --scratch
python3 workflow/04_forcing/climate/submit_climate_forcing.py --gcm ec-earth3-esm-1-1 --alias esm-hist --years 2011-2020
```

The producer runs one worker per variable; the verifier checks files in
parallel. With `--scratch` or from a repository that is not clean, output
goes to `scratch/climate-forcing/<gcm>/<alias>/<variable>/` with its QC in
`qc/` next to it; `--scratch-label <label>` puts a test run under
`scratch/climate-forcing/runs/<label>/` instead, so that it does not replace
an earlier one. Use `--scratch` for every test run.
The submit script decides this once, at submission, and passes it to the producer (`--scratch`, or `--expect-commit <commit>`); a producer submitted for a forcing unit stops when the repository is no longer clean at that commit when the job starts, so the producer and the verifier never look at different places. `--verify-only` submits a job that runs only the verifier on the existing files of the units, e.g. the whole unit after an extension (it updates `qc.status`; a repository that is not clean does not redirect it).

An existing unit is never overwritten. Running the producer for years a unit
does not contain extends it when the conditions in
`docs/directory-contracts.md` ("Forcing unit and provenance record") hold:
unchanged code fingerprint (Git tree of this directory and
`workflow/common/`, `METHOD_VERSION`) or a change of the trees recorded as
result-neutral in `manifests/code-equivalence.yaml`, unchanged SHA-256 of reused inputs,
new ISIMIP files matching their manifest, unchanged key software versions.
Existing data files are verified and never touched; only `provenance.yaml`
is rewritten, with `qc.status: not_checked` until the verifier has run.

## Decisions

- D08 (domain) and its amendment of 2026-09-30 (VIC cells outside the ISIMIP
  mask use their own 0.5° cell).
- D16 (decided 2026-10-01, `docs/decisions/D16-lwdown-elevation-correction.md`):
  `lwdown` ratio correction, method 1.1. No unit was produced with 1.0, so
  all seven units are produced with 1.1.
- D01 (open) does not block the smoke-campaign climate units (user,
  2026-09-30).
