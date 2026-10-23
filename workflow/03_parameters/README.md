# 03 Parameters

## Purpose

Generate, assemble, and validate the static or slowly varying parameter datasets required by VIC-WUR.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Scope

This stage may include domain, soil, vegetation, land-use, routing, reservoir, irrigation, and water-use parameters. Subdirectories should be created by parameter family only when implementation work begins.

## Components

| Directory | Component | State |
|---|---|---|
| `vegetation/` | `parameters/<status>/<set>/vegetation/`: 16-class vegetation variables with the full land-use tile union (D04) and donor backfill of added tiles | producer, verifier, Slurm template and unit tests implemented (method 1.0) |
| `bundle/` | `parameters/<status>/<set>/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`: the image-driver file VIC reads with `PARAMETERS`, assembled from the natural bundle (soil, snow bands, `elev`) and the vegetation component, every variable bitwise equal to its source | producer, verifier, Slurm template and unit tests implemented (method 1.0) |
| `dams/` | `parameters/<status>/<set>/dams/vic_global_5min_dam_parameters_isimip4b_{histsoc,1850soc,2021soc}.nc` (D19): the ISIMIP4b dams located with GDW v1.0 plus the SSP future river-power dams, snapped on the routing of the set, one dam list, `year` per DHF scenario; dam list and source tables | producer, verifier, Slurm template and unit tests implemented (method 1.0); hand review and natural discharge run pending (task L) |
| `domain/` | adopted `domain` component (no producer): `verify_domain.py`, plus `adopted.py`, `adopted_qc.sbatch` and `submit_adopted_qc.py` shared by the verifiers of the four adopted components | verifier, Slurm template and unit tests implemented (task R) |
| `routing/` | adopted `routing` component (no producer): `verify_routing.py` (routing file only; the decomposition file is not checked) | verifier and unit tests implemented (task R) |
| `irrigation/` | adopted `irrigation` component (no producer): `verify_irrigation.py` | verifier and unit tests implemented (task R) |
| `water_use/` | adopted `water_use` component (no producer): `verify_water_use.py` | verifier and unit tests implemented (task R) |

Adopted components of `vic-global-5arcmin-version-a` (copies of `vic_parameter` files recorded in
`manifests/parameters/vic-global-5arcmin-version-a.yaml` with source path, version, md5 and verification;
renamed without version tokens, the source name recorded), not generated here:

| Component | File | Read by VIC with |
|---|---|---|
| `domain` | `vic_global_5min_domain_nogl.nc` | `DOMAIN` |
| `bundle` | `vic_global_5min_natural_static_root-b-zeng2001.nc`, `vic_global_5min_humanimpact_16class_root-b-zeng2001.nc` (inputs of the assembled file and of the vegetation component) | – |
| `routing` | `vic_global_5min_routing.nc` (routing release v1.0.0_20260804) | `ROUTING_PARAMETERS` |
| `routing` | `vic_global_5min_file_decomposition_wateruse_dams.nc` (decomposition v2.0.0_20260825, 128 groups) | `DECOMPOSITION_PARAMETERS` with `DECOMPOSITION FILE` |
| `irrigation` | `vic_global_5min_irrigation_parameters.nc` (candidate v2, efficiency corrected) | `IRRIGATION_PARAMETERS` |
| `dams` | `vic_global_5min_dam_parameters_t3-extended-merged.nc` (candidate T3_extended with its 57 two-dam cells merged, vic_parameter T3_extended_v2; VIC 39e21ff5 writes past its dam output arrays in cells with two dams) | `DAMS_PARAMETERS` |
| `water_use` | `vic_global_5min_wateruse_parameters_receiving-network.nc` (receiving network v1.0.0_20260817) | `WATERUSE_PARAMETERS` |

Each plugin file was checked against the reader of VIC `39e21ff5` (variable names, dimensions and their
order, dtypes) and its lat/lon against the domain (equal); the source checksum lists, manifests, README and
QA files are copied next to the files as `source_*`.
The QC evidence of `domain`, the routing file, `irrigation` and `water_use` comes from the verifiers in the
directories of these components (one Slurm job, `domain/submit_adopted_qc.py`, see `domain/README.md`); the
manifest records `qc_status` and `qc_evidence` per component.

## Inputs

- Verified source data from `workdir/raw/`.
- Reusable caches from `workdir/intermediate/`, used only when their fingerprint matches and `_SUCCESS` exists.
- Explicit parameter-generation settings.

## Outputs

- Candidate and accepted parameter datasets under `workdir/parameters/`.
- Parameter quality-control evidence under `workdir/qc/parameters/`.
- Accepted parameter definitions under `manifests/parameters/`.

## Allowed content

- Parameter-generation source code.
- Scientific validation code.
- Slurm templates and small configuration templates.
- Tests for scientific invariants and file structure.

## Forbidden content

- Generated parameter NetCDF files.
- Untraceable manual corrections to production parameters.
- A parameter marked as production-ready without quality-control evidence and a manifest.
- Alternative scripts named with `v2`, `fix`, `new`, or `final`.

## Completion criteria

A parameter set is production-ready only when its sources, workflow commit, configuration, checksum, and quality-control status are recorded in an accepted parameter manifest.

