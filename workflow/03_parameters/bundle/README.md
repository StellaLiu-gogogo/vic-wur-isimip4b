# 03 Parameters — bundle

Assembles the 16-class VIC image-driver parameter file (the file VIC reads with `PARAMETERS`) of a
parameter set into its `bundle` component:
`parameters/<status>/<set>/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`.

Classification: production workflow code (user, 2026-10-04, task E smoke campaign); the file is read by
`05_simulation`.

| File | Role |
|---|---|
| `assemble_bundle.py` | producer: copies every non-vegetation variable of the natural bundle and every variable of the 16-class vegetation component into one file; writes `bundle/provenance.yaml` |
| `verify_bundle.py` | independent verification; writes `qc/parameters/<status>/<set>/bundle/{summary.json,reports/verify.json}` and sets `qc.status` in `bundle/provenance.yaml` |
| `bundle.sbatch` | Slurm template: producer, then verifier, in one job |
| `submit_bundle.py` | renders and submits the job, job record under `logs/03_parameters/<job-name>_<slurm-job-id>/` |

Tests: `tests/unit/test_parameter_bundle.py`.

## Inputs

- `bundle/vic_global_5min_natural_static_root-b-zeng2001.nc` (adopted natural bundle v3): soil,
  snow bands (5), `elev`, `run_cell` and the other non-vegetation variables. Its 14-class vegetation
  variables, `Nveg` and the `veg_class` coordinate are not used.
- `vegetation/vic_global_5min_vegetation_16class_root-b-zeng2001.nc` (`workflow/03_parameters/vegetation/`):
  `Cv`, `Nveg`, `LAI`, `fcanopy`, `albedo`, `displacement`, `veg_rough`, `root_depth`, `root_fract`,
  `overstory`, `rarc`, `rmin`, `RGL`, `rad_atten`, `wind_atten`, `trunk_ratio`, `wind_h`, the `veg_class`,
  `month` and `root_zone` coordinates and the bookkeeping variables `landuse_union_bits`,
  `added_tile_bits`, `backfill_level` (VIC ignores them).
- `domain/vic_global_5min_domain_nogl.nc` (lat and lon must be equal).

## Method (version 1.0)

A variable of the natural bundle is a vegetation variable when the component has a variable of the same
name or when it has the dimension `veg_class`; one with `veg_class` that the component lacks stops the
assembly. Values are copied as stored (no unpacking or masking) with their dtype, fill value, chunking,
compression and attributes, so every variable is bitwise equal to its source.

The verifier checks that every variable the image driver at VIC `39e21ff5` reads with the project options
(`drivers/shared_image/src/vic_init.c`: soil, baseflow D1–D4, snow bands, 16 vegetation classes with
`LAI`/`fcanopy`/`albedo` from the parameter file, `Wfc_FRACT`) is present with the dimensions in the order
VIC reads them (VIC checks only order and length, not names); that `run_cell` is int and 1 exactly on the
domain mask; lat/lon equal the domain; vegetation variables bitwise equal to the component and all other
variables bitwise equal to the natural bundle; `Nveg <= tiles <= Nveg + 1` on every active cell; and that
`overstory`, stored as double but read by VIC as int, is 0 or 1 on every tile.

## Running

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/bundle/submit_bundle.py --scratch   # test, scratch/parameter-bundle/bundle/
python3 workflow/03_parameters/bundle/submit_bundle.py             # candidate file in the bundle component
```

One core and about 10 GB; the copy writes about 4 GB. From a repository that is not clean, or with
`--scratch`, everything goes to `scratch/parameter-bundle/bundle/` (QC under its `qc/`). The producer never
overwrites an existing assembled file.

## Decisions

D01 is provisional: the file is a candidate. D04 and D08 apply through the vegetation component and the
domain.
