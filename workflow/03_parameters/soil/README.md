# 03 Parameters — soil

Builds the soil component of a parameter set, `parameters/<status>/<parameter-set>/soil/`: the file
`vic_global_5min_soil_calibration-smoothed.nc` with every non-vegetation variable of the image-driver
parameter file (soil, snow bands, `elev`, `run_cell`, the diagnostic variables of the soil product), taken from
the assembled bundle of a base parameter set with the five 2-degree calibration fields smoothed and the two
layer-2 variables that depend on them recomputed (task Z). The bundle component assembles the image-driver file
of the set from this file and the vegetation component (`bundle/assemble_bundle.py --soil-component`).

Classification: production workflow code of `03_parameters` (user, 2026-11-02).

| File | Role |
|---|---|
| `smooth_calibration_fields.py` | producer: block values, fill of empty blocks, bilinear interpolation, `max_moist[2]` and `init_moist[2]`; writes the component file, `calibration_blocks.csv`, `provenance.yaml` and `qc/.../reports/build_report.json` |
| `verify_soil.py` | independent verification; writes `summary.json`, `reports/verify.json` and `figures/` under `qc/parameters/<status>/<set>/soil/` and sets `qc.status` in `provenance.yaml` |
| `soil.sbatch` | Slurm template: producer, then verifier, in one job |
| `submit_soil.py` | renders and submits the job, job record under `logs/03_parameters/<job-name>_<slurm-job-id>/` |

Tests: `tests/unit/test_soil_smoothing.py`. Shared helpers (workdir, checksums, Git state, `provenance.yaml`, QC summary
and verifier exit status, job records) come from `workflow/common/`; the bitwise variable copy is the one of
`bundle/assemble_bundle.py`.

## Inputs

- The assembled bundle of the base set, `parameters/<status>/<base-set>/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`,
  accepted (`code_dirty: false`, `qc.status: passed`), and its `provenance.yaml`, whose `method.natural_variables`
  names the 53 non-vegetation variables.
- The domain of the base set, `parameters/<status>/<base-set>/domain/vic_global_5min_domain_nogl.nc` (mask, cell area).

## Method (version 1.0, user 2026-11-02)

In `vic-global-5arcmin-version-a` the depth of soil layer 2 (`depth[2]`) and the four NIJSSEN2001 baseflow
parameters `Ds`, `Dsmax`, `Ws` and `c` are constant over 2-degree blocks: they were calibrated on a 2-degree grid
and mapped to the 5-arcmin cells (`depth[2]` has 6 values, `Dsmax` 9). Where neighbouring blocks differ, the
fields step at the block edges; VIC's baseflow and layer-2 storage then step with them.

1. **Blocks.** Latitude edges on even degrees everywhere (−56, −54, …, 84); longitude edges on even degrees east of
   0 and on odd degrees west of 0 (the negative longitudes were rounded the other way when the blocks were mapped;
   found on all five fields, task Z 2026-11-02), so the blocks [−180, −179] and [−1, 0] are one degree wide: 70 × 181
   blocks. A block takes the one value of its active cells (uniform block) or the most frequent value of its active
   cells (mixed block, almost all coastal, ties take the smallest value); a block without active cells (empty) takes
   the value of the nearest land block on the sphere (great-circle distance between block centres).
2. **Smoothing.** Bilinear interpolation between the block centres on every active cell: linear in latitude between
   the two nearest centre rows (beyond the outermost rows the nearest row alone), linear in longitude between the two
   nearest centre columns, periodic across 180°. A block centre keeps its value, every cell lies between the values
   of the four blocks around it, and the 2-degree steps disappear. Block means are not conserved: an isolated block
   is pulled towards its neighbours (reported, not judged; user 2026-11-02).
3. **Dependent variables.** `max_moist[2] = depth[2] × (1 − bulk_density/soil_density) × 1000` mm in double
   precision; `init_moist[2]` keeps the ratio `init_moist[2]/max_moist[2]` of the base; layers 1 and 3 and every
   other variable are copied bitwise. The root zones of the vegetation follow in
   `vegetation/recompute_roots.py`.
4. The new values are written in double precision (the base holds float32-representable values). Cells outside the
   domain mask keep the stored fill values.

`calibration_blocks.csv` records every block of every field (edges, kind, value, number of active cells, share of
the block value among them, donor block and distance of an empty block, the value after the fill).

The verifier recomputes the block values with its own loop and checks them against the record, the fill against
the nearest land block, the four cells around every land block centre against the block value (within 5 % of the
largest difference to the 8 neighbouring blocks), every cell against the range of its four blocks and of the field,
the largest difference between neighbouring cells against the largest difference between neighbouring blocks
divided by the cells between their centres (24; 18 next to the two 1-degree blocks), the area-weighted mean change
(≤ 2 % per field), `max_moist[2]` and the `init_moist` ratio (1e-9 relative), the VIC rules the change touches
(`depth[2]` ≥ 0.001 m, `depth[1]` ≤ `depth[2]`, the NIJSSEN2001 conversion of `vic_init.c`), and that everything
else, the grid and the mask are bitwise unchanged. Reported only: the block means of the smoothed fields against
the block values and the share of the variance within 0.5-degree blocks. Figures: `depth[2]` and `Ds` of the
base and smoothed for West Siberia (58–66 N, 78–90 E) and the Alps (42–50 N, 2–14 E), and the global `depth[2]`.

## Running

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/soil/submit_soil.py --scratch   # test, scratch/soil-component/soil/
python3 workflow/03_parameters/soil/submit_soil.py             # candidate component of vic-global-5arcmin-version-b
```

One core, about 20 GB and half an hour (the copy writes about 2 GB). From a repository that is not clean, or with
`--scratch`, everything goes to `scratch/soil-component/soil/` (QC under its `qc/`). The producer refuses to write
into an existing, non-empty component directory and, outside scratch, takes only an accepted base bundle. The
submit script decides this once, at submission, and passes it to the producer (`--scratch`, or
`--expect-commit <commit>`); `--verify-only` submits a job that runs only the verifier on the existing component
(it updates `qc.status`; from a repository that is not clean the results go to
`scratch/soil-component/verify-uncommitted/qc/...` and the status is not changed). The restriction attributes of
the base (`not_authorized_for_global_production`, `product_stage`) are carried into the file and its
`provenance.yaml`.

## Decisions

The method is the user's decision of 2026-11-02 (task Z, `workflow/03_parameters/README.md`). D08: the domain is
unchanged. D01 is decided: the component is a candidate until the parameter set is promoted.
