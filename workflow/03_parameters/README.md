# 03 Parameters

## Purpose

Generate, assemble, and validate the static or slowly varying parameter datasets required by VIC-WUR.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Scope

This stage may include domain, soil, vegetation, land-use, routing, reservoir, irrigation, and water-use parameters. Subdirectories should be created by parameter family only when implementation work begins.

## Components

| Directory | Component | State |
|---|---|---|
| `soil/` | `parameters/<status>/<set>/soil/vic_global_5min_soil_calibration-smoothed.nc`: every non-vegetation variable of the base set's assembled bundle with the 2-degree calibration fields `depth[2]`, `Ds`, `Dsmax`, `Ws`, `c` smoothed and `max_moist[2]`, `init_moist[2]` recomputed (task Z); `vic_global_5min_soil_<label>.nc`: the same with the 18 soil fields taken from an external VIC parameter file instead (`adopt_soil_fields.py`, the MPR soil of version-c) | producer, verifier, Slurm template and unit tests implemented (method 1.0) for both |
| `vegetation/` | `parameters/<status>/<set>/vegetation/`: 16-class vegetation variables with the full land-use tile union (D04) and donor backfill of added tiles; `recompute_roots.py` writes the component of a set with another soil (root zones recomputed, task Z) | producer, verifier, Slurm template and unit tests implemented (method 1.0); root recomputation producer, verifier and tests (task Z) |
| `bundle/` | `parameters/<status>/<set>/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`: the image-driver file VIC reads with `PARAMETERS`, assembled from the natural bundle (soil, snow bands, `elev`), or from the soil component with `--soil-component` (task Z), and the vegetation component, every variable bitwise equal to its source | producer, verifier, Slurm template and unit tests implemented (method 1.0) |
| `dams/` | `parameters/<status>/<set>/dams/vic_global_5min_dam_parameters_isimip4b_{histsoc,1850soc,2021soc}.nc` (D19): the ISIMIP4b dams located with GDW v1.0 plus the SSP future river-power dams, snapped on the routing of the set, one dam list, `year` per DHF scenario; dam list and source tables | producer, verifier, Slurm template and unit tests implemented (method 1.0); built 2026-10-30 from the natural run (c327675), qc passed; manifest entry `dams_isimip4b` |
| `domain/` | adopted `domain` component (no producer): `verify_domain.py`, plus `adopted.py`, `adopted_qc.sbatch` and `submit_adopted_qc.py` shared by the verifiers of the four adopted components | verifier, Slurm template and unit tests implemented (task R) |
| `routing/` | adopted routing file (no producer): `verify_routing.py`; generated FILE decomposition `routing/vic_global_5min_file_decomposition_wateruse_isimip4b-dams.nc` keeping every water-use and D19 dam service link inside one group: `build_decomposition.py`, `verify_decomposition.py` | routing verifier (task R); decomposition producer, verifier, Slurm template and unit tests implemented (method 1.0, task L3); built 2026-10-30 (f6d850f), qc passed; manifest entry `decomposition_isimip4b` |
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

A manifest entry with `promotion: excluded` (and its `promotion_reason`) is not copied to `production/`: a file that
another entry supersedes, or a source file that VIC does not read and whose values reach VIC through a checked entry.
Such an entry keeps `qc_status: not_checked`; every other entry needs `qc_status: passed`.

## Promotion to production

| File | Role |
|---|---|
| `promote_parameter_set.py` | copies every file of the manifest entries not marked `promotion: excluded` (their `files` and `provenance` record) from `parameters/candidates/<set>/` to `parameters/production/<set>/` |
| `verify_parameter_promotion.py` | independent verification of the promoted copy; writes `qc/parameters/production/<set>/{summary.json,reports/verify.json}` |
| `parameter_promotion.sbatch` | Slurm template: promotion, then verification |
| `submit_parameter_promotion.py` | renders and submits the job, job record under `logs/03_parameters/parameter-promotion-<set>_<slurm-job-id>/` |

Tests: `tests/unit/test_parameter_promotion.py`. Classification: production workflow code (user, 2026-10-30, task R).

| File | Role |
|---|---|
| `copy_components.py` | copies the unchanged components of a candidate set into a new candidate set (every file of the manifest entries of the component, excluded entries included, checked against the manifest and after the copy; a `provenance.yaml` is renamed to the new set, its `qc` set to `not_checked`, `copied_from` added); writes the record of the copy |
| `copy_components.sbatch`, `submit_copy_components.py` | Slurm template and submit script; the record of the copy is in the job's output in its job record |

Tests: `tests/unit/test_copy_components.py`. Classification: production workflow code (user, 2026-11-02, task Z).

The promotion copies, never moves: the candidate set stays, because earlier runs record its paths. Before copying it
checks that every promoted entry has `qc_status: passed`, that every candidate file has the md5 (and sha256) of the
manifest, and it lists the restriction attributes (`not_authorized_for_global_production`, `product_stage`) of the
candidate NetCDF files, promoted or excluded; it stops when such attributes exist and the user's acceptance is not
given (`--accepted-restrictions`). Each copy keeps the modification time and is checked against the candidate
(md5, sha256) before it gets its final name. `promotion.yaml`, written last at the root of the production set,
records the time, the workflow commit, the user's authorisation, the accepted restrictions, every file with size,
md5 and sha256, the excluded entries with their reasons and the QC evidence of every promoted entry; a production
directory without it is an unfinished promotion. An existing production directory stops the promotion. The
verifier checks the record, every copy (size, md5, sha256, still equal to the candidate and to the manifest), that
the set holds exactly the promoted files, and that the QC evidence of every promoted entry exists and passed. After
it has passed, the manifest is set to `status: production` by hand.

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/submit_parameter_promotion.py --scratch --authorised "test" --accepted-restrictions "test"
python3 workflow/03_parameters/submit_parameter_promotion.py --authorised "user, <date>" --accepted-restrictions "<text>"
```

`--scratch` promotes into `scratch/parameter-promotion/production/` (QC under `scratch/parameter-promotion/qc/`).
One core, a few GB of memory; the copy of `vic-global-5arcmin-version-a` is 27 files, 4.9 GB.

## Soil calibration fields smoothed (task Z)

Classification: production workflow code of `03_parameters` (user, 2026-11-02). Parameter set
`vic-global-5arcmin-version-b` = `vic-global-5arcmin-version-a` with the five 2-degree calibration fields of the
soil (`depth[2]`, `Ds`, `Dsmax`, `Ws`, `c`) smoothed by bilinear interpolation between the block centres, the
dependent `max_moist[2]`, `init_moist[2]` and the root zones of the vegetation recomputed, everything else identical
value for value (`manifests/parameters/vic-global-5arcmin-version-b.yaml`, version-a named as base). Facts found on
version-a (2026-11-02): the block edges lie on even latitudes and on even longitudes east of 0 but odd longitudes
west of 0; with that rule `depth[2]` has 4895 uniform, 192 mixed (all coastal) and 7583 empty blocks of 12 670, `Ds`
4462/625/7583; `max_moist` equals `depth × porosity × 1000` only within 2.5e-7 (float32 history); the Zeng 2001 root
rule reproduces `root_fract` of every base tile of classes 1–10 and 13 exactly after float32 rounding. Decisions of
the user (2026-11-02): mode of the active cells for mixed blocks, nearest land block for empty blocks, bilinear
interpolation periodic in longitude; the block-mean criterion is a report, the area-weighted global mean may change
by at most 2 %, the largest cell-to-cell jump may not exceed the largest block difference over the cells between
block centres; new values in double precision; unchanged components copied from version-a and verified again;
the comparison runs are two non-production campaigns and their figures and tables an analysis task
(`analysis/soil-comparison/`).

| Step | Content | State |
|---|---|---|
| Z1 | soil component: `soil/smooth_calibration_fields.py`, `verify_soil.py`, Slurm template, submit script, tests | done: candidate built and verified 2026-11-02 (job 43542860, 11 checks passed; global area means −0.04 % … +0.004 %) |
| Z2 | vegetation component with recomputed roots: `vegetation/recompute_roots.py`, `verify_roots.py`, `root_zeng2001_igbp.yaml`, tests | done: candidate built and verified 2026-11-02 (job 43542862, 6 checks passed; version-a roots reproduced on 100 % of the base tiles of classes 1–10 and 13) |
| Z3 | bundle assembled from the soil component (`--soil-component`), verifier compares with the source named in the provenance | done: candidate assembled and verified 2026-11-02 (job 43542901, 7 checks passed) |
| Z4 | unchanged components copied and verified again: `copy_components.py`, adopted QC, dams and decomposition verifiers with `--parameter-set vic-global-5arcmin-version-b`; manifest | done: copied 2026-11-02 (job 43542859, 26 files); manifest 2cd10b2; verified again on version-b 2026-11-03 (adopted QC 43551227, dams 43551228, decomposition 43551229, all passed) |
| Z5 | QC of the set and promotion to `production/` | QC passed for every component (Z2–Z4); promotion open: user's decision after Z6 |
| Z6 | comparison campaigns `soil-comparison-version-a`, `soil-comparison-version-b` (historical histsoc 2011–2020), analysis `analysis/soil-comparison/` | done 2026-11-04: runs 43551798 (a) and 43553341 (b), checks 43569306/43569307 passed; analysis conclusion: smoothing removes the steps, global water balance and GRDC comparison unchanged or marginally better; report `workdir/analysis/soil-comparison/report.html` |
| Z7 | change of `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml` (user's decision after the comparison) | open |
| Z8 | third set `vic-global-5arcmin-version-c` with the MPR soil of vic_parameter (user, 2026-11-04): `soil/adopt_soil_fields.py`, `verify_adopted_soil.py`, `submit_soil.py --soil-source`, tests; roots, bundle and copied components as for version-b; manifest | done 2026-11-04: copy 43600676 (26 files); soil 43600681 built, verified 43600813 (8 checks; the stored max_moist of the MPR product is 1.07 % off VIC's own, tolerance 2 %); roots 43600821, verified 43601037 (6 checks); bundle 43601169 (7 checks); manifest written, copied components to be verified again on version-c |
| Z9 | comparison campaign `soil-comparison-version-c` (identical to -a and -b), run check, analysis extended to three sets | open |
