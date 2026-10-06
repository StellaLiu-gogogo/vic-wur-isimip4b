# 03 Parameters — vegetation

Builds the 16-class vegetation component of a parameter set,
`parameters/<status>/<parameter-set>/vegetation/`: the VIC image-driver
vegetation variables (`Cv`, `Nveg`, `LAI`, `fcanopy`, `albedo`,
`displacement`, `veg_rough` (12 months), `root_depth`, `root_fract`
(3 zones), `overstory`, `rarc`, `rmin`, `RGL`, `rad_atten`, `wind_atten`,
`trunk_ratio`, `wind_h`, `veg_class`) with every tile that the land-use
forcing of any soc scenario needs (D04, full tile union).

Classification: production workflow code (user, 2026-10-01).

| File | Role |
|---|---|
| `build_vegetation.py` | producer: land-use tile union, added tiles, donor backfill, `fcanopy` floor; writes the component file, `backfill_tiles.csv`, `provenance.yaml`, and `qc/.../reports/build_report.json` |
| `verify_vegetation.py` | independent verification; writes `summary.json`, `reports/verify.json`, `figures/added_tiles.png` under `qc/parameters/<status>/<set>/vegetation/` and sets `qc.status` in `provenance.yaml` |
| `vegetation_component.sbatch` | Slurm template: producer, then verifier, in one job |
| `submit_vegetation_component.py` | renders and submits the job, job record under `logs/03_parameters/<job-name>_<slurm-job-id>/` |

Shared helpers (workdir, checksums, Git state, `provenance.yaml`, QC summary and verifier exit status, job records) come from `workflow/common/` (see its README); the verifier exits with 0 only for `passed` (1 failed, 3 warning, 4 not_checked).

## Inputs

- Base bundle `parameters/<status>/<set>/bundle/vic_global_5min_humanimpact_16class_root-b-zeng2001.nc`
  (vic_parameter Version A 16-class, adopted 2026-10-01; soil, snow bands
  and `elev` bitwise identical to the natural bundle of the set): its
  2003–2022 tiles and their parameters.
- Domain `parameters/<status>/<set>/domain/vic_global_5min_domain_nogl.nc`.
- The accepted land-use forcing units `forcing/landuse/{histsoc,1850soc,2021soc,ssp1vlsoc-noadapt,ssp3hsoc-noadapt}/`
  (all 581 yearly files).
- Köppen–Geiger 1991–2020, Beck et al. (2023), 1 km:
  `raw/external/koppen-geiger/beck2023/1991_2020/koppen_geiger_0p00833333.tif`
  (manifest `manifests/inputs/koppen-geiger-beck2023.yaml`), reduced to the
  5′ grid by majority of the 10 × 10 pixels of each cell.

## Method (version 1.0)

The class contract is the 16-class contract of the land-use converter
(1–11 natural, 12 rainfed crop, 13 urban, 14 irrigated non-paddy,
15 irrigated paddy, 16 barren; class 16 is VIC's bare-soil class,
`Nbare = 1`).

1. **Tiles.** VIC allocates a tile only where the parameter `Cv > 0`
   (`vic_init.c`) and stops when the land-use forcing has `Cv > 0` on a
   class without a tile (`lu_force.c`). Final tiles = base tiles ∪ every
   (cell, class) with coverage > 0 in any year of the five units. Added
   tiles get `Cv = 1e-12` and each cell is renormalized to sum 1; the
   forcing replaces `Cv` at the first time step of a run, so the
   placeholder only allocates the tile. Base tiles that no forcing uses
   are kept (a tile with `Cv = 0` is skipped by `vic_run`).
2. **Nveg** = number of tiles among classes 1–15; VIC requires
   `Nveg ≤ tiles ≤ Nveg + 1`.
3. **Backfill.** Every added tile copies all vegetation parameters,
   unchanged, from one base tile of the same class (user, 2026-10-01):
   L1 values already present in the same cell; L2 nearest within 500 km;
   L3 nearest with the same Köppen–Geiger class; L4 nearest within ±2.5°
   latitude; L5 nearest anywhere. Level, donor cell, distance, Köppen
   classes and the soc scenarios that need the tile (`soc_bits`: 1 histsoc,
   2 1850soc, 4 2021soc, 8 ssp1vlsoc-noadapt, 16 ssp3hsoc-noadapt) are in
   `backfill_tiles.csv`; the level is also the variable `backfill_level`.
4. **fcanopy** is floored at 1.001e-4 on every tile (VIC's `MIN_FCANOPY` is
   1e-4, compared strictly; 1.001e-4 survives a float32 round trip). The
   base bundle had `fcanopy = 0` on 7 735 524 class-16 tile-months.
5. `LAI`, `fcanopy`, `albedo` are the base bundle's 12-month 2003–2022
   climatology, read with `LAI_SRC`, `FCAN_SRC`, `ALB_SRC = FROM_VEGPARAM`
   (user, 2026-10-01). Natural classes: calendar-month climatology weighted
   by valid observation days; classes 12, 14, 15 share one crop climatology
   (equal-weight 2003–2022 mean of the MIRCA-based crop canopy), a known
   simplification accepted by the user (2026-10-01).

The component holds the vegetation variables only; the assembled
image-driver file (soil and snow bands of the base bundle plus this
component) is produced before the smoke campaign.

Reusable intermediate: the land-use tile union is cached in
`scratch/vegetation-component/landuse-tile-union.nc`, keyed by the sha256
of every coverage file; it moves to `intermediate/` once
`workflow/common/cache.py` exists. The component never depends on it.

## Running

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/vegetation/submit_vegetation_component.py --scratch   # test, scratch/vegetation-component/vegetation/
python3 workflow/03_parameters/vegetation/submit_vegetation_component.py             # candidate component
```

From a repository that is not clean, or with `--scratch`, the producer
writes to `scratch/vegetation-component/vegetation/` (QC under its `qc/`).
The producer refuses to write into an existing, non-empty component
directory, and outside scratch it requires every land-use unit to be
accepted (`code_dirty: false`, `qc.status: passed`).

## Decisions

D04 items 1–5 apply (item 5: Köppen–Geiger 1991–2020 for the backfill).
D08: the domain is unchanged. D01 is provisional: the component is a
candidate and is promoted to `production/` only after D01 is frozen.
