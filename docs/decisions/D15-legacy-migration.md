# D15 — Migration of the legacy `vic_global/isimip4b/` area

Status: **final, 2026-09-29.** Data steps executed and verified; code steps
7–8 reduced in scope (section 5) and pending.

Source: `/lustre/nobackup/WUR/ESG/liu297/vic_global/isimip4b/` (legacy area).
Target: `/lustre/nobackup/WUR/ESG/liu297/isimip4b/repo/` (Git) and
`/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir/`.

## 1. Decisions

| # | Decision (2026-09-29) |
|---|---|
| Q1 | The 12 Chinese audit and plan reports are not migrated and no `legacy/` area is created in the repository. Audits needed later are redone in English. |
| Q2 | The ISIMIP protocol repository is cloned into `workdir/raw/external/isimip-protocol-4/<commit>/`, commit `f9be7b0` only. |
| Q3 | Legacy analysis code is not rewritten unless it is reused. |
| Q4 | After moving the 1.39 TB: count + size for every file, md5 for a 5 % sample; full md5 by Slurm before first production use. |
| Q5 | Superseded: the levante-side QA script is not migrated (see section 5). |
| Q6 | `03Data/qa_slices/` (5.5 GB) stays in the legacy area. |
| Q7 | The weights cache `weights_cache_v5_2003_2022.npz` is not migrated. |
| Q8 | The VIC domain file is adopted into `workdir/parameters/candidates/vic-global-5arcmin-version-a/` (contract clause for adopted parameter sets, commit `77dcb9e`); the VIC coverage dataset used as weights goes to `workdir/raw/external/`. |
| Q9 | `01Info/` stays in the legacy area with `04Slides/`. |
| Q10 | After a first migration, the user decided that only material still needed by production or by a future data transfer is kept in the project. Five analysis tasks and the QC job outputs were moved back (section 4.4). |

## 2. Principles

1. Large data is moved (`mv` on the same Lustre filesystem: a rename, instant
   and reversible); verification is count and size against the pre-move
   inventory, plus md5 where stated.
2. Code is copied and then rewritten; the legacy copy stays until cleanup.
3. Nothing in the legacy area is deleted by this decision. A cleanup list is
   presented separately for approval.
4. One verified step at a time; one commit per repository step.

## 3. What was migrated

| Legacy path | Target | Verification |
|---|---|---|
| `03Data/raw_dkrz/InputData/` (895 files, 1.387 TB) | `workdir/raw/ISIMIP4b/InputData/` | 899/899 files present with recorded size (with the four files below); 43-file random md5 sample identical |
| `02Audit/evidence/irrigated_area_comparison_5crops_15arcmin/inputs_staged/` (4 `landuse-5crops` files, 1.75 GB) | `workdir/raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/` | full md5 identical to the DKRZ records |
| — (new) ISIMIP protocol repository at `f9be7b0cdf83409315d9fa7da8581cc6fd6ff3e1` | `workdir/raw/external/isimip-protocol-4/<commit>/` (248 files, no `.git`) | commit SHA in `COMMIT` |
| — (new) `vic_parameter/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2003…2022.nc` (20 files, 591 MB) | `workdir/raw/external/vic-coverage-version-a/5/` | md5 of every copy equals the source |
| — (new) `vic_coupled/Data/VIC/domain/global/vic_global_5min_domain_nogl.nc` (87 MB) | `workdir/parameters/candidates/vic-global-5arcmin-version-a/domain/` | md5 equals the source |
| `03Data/raw_dkrz/MD5SUMS`, `03Data/inventory/transfer_manifest_batch_{1,1b,2,3,4}.txt`, `03Data/README.md` (transfer table) | `repo/manifests/inputs/isimip4b-dkrz-2026-09-21/` (copies, generated `inventory.tsv` with 899 rows, README) | md5 of copies |
| — (new) | `repo/manifests/inputs/isimip-protocol-4.yaml`, `vic-coverage-version-a-5.yaml`, `repo/manifests/parameters/vic-global-5arcmin-version-a.yaml` | — |
| `03Data/inventory/` remainder (DKRZ listings of 2026-09-21, batch lists 1–6, expected sizes, storage report) | `workdir/analysis/data-acquisition-2026-09/inventory/` with `repo/analysis/data-acquisition-2026-09/README.md` | count (21 files) |
| `03Data/figures/` (19 PNG, 6 JSON), `03Data/QA_report_2026-09-21.md` | `workdir/qc/raw/ISIMIP4b/InputData/{figures,reports}/` plus a generated `summary.json` (status `warning`: reservoirs_dams) | count |
| `03Data/transfer_logs/` rsync, md5, remote-stat and driver logs (27 files) | `workdir/logs/01_acquisition/` | count |
| — (new) pre-move inventory of the legacy area | `workdir/logs/01_acquisition/legacy-inventory-2026-09-29.{tsv,md5}` (3,997 paths; 1,691 md5) | — |

## 4. What stays in the legacy area

### 4.1 Never migrated

| Item | Reason |
|---|---|
| `01Info/` | Q9 |
| `02Audit/*.md` (12 reports) | Q1 |
| `02Audit/smoke_test/` | never executed; Snellius paths; superseded by `05_simulation` when implemented |
| `02Audit/evidence/landuse_monthly_harmonization_plan/` | withdrawn route |
| `03Data/qa_slices/` | Q6 |
| `04Slides/` | decided 2026-09-28 |
| `05Landuse/trial_2021/weights_cache_v5_2003_2022.npz` | Q7 |

### 4.2 Not migrated: code (section 5)

`03Data/scripts/qa_*.py`, `write_qa_report.py`, `qa_atmos_fullseries.sbatch`,
`levante_qa_slices.sh`: written for one visual QA pass with hard-coded paths.
Input QC is implemented anew under `workflow/07_quality_control/` when needed;
the legacy scripts serve as reference.

### 4.3 Kept in the legacy area although copied to the project

`03Data/raw_dkrz/MD5SUMS`, `03Data/inventory/transfer_manifest_batch_*.txt`
(copies in `repo/manifests/inputs/`); the original copies of every script
that will be rewritten in steps 7–8. Removed at cleanup (step 10).

### 4.4 Migrated first, then moved back (Q10, md5-verified against the pre-move inventory)

| Item | First target | Back to |
|---|---|---|
| `02Audit/evidence/` root files (protocol extracts, DKRZ listings) | analysis `protocol-audit-2026-09` | `02Audit/evidence/` |
| `02Audit/evidence/2026-09-20/` | analysis `model-capability-audit-2026-09` | `02Audit/evidence/2026-09-20/` |
| `02Audit/evidence/landuse_2021_analysis/` | analysis `landuse-scoping-2021` | `02Audit/evidence/landuse_2021_analysis/` |
| `02Audit/evidence/irrigated_area_comparison_5crops_15arcmin/` | analysis `irrigated-area-comparison` | same directory (without `inputs_staged/`, which is raw data) |
| `02Audit/evidence/landuse_annual_15crops_plan/`, `05Landuse/trial_2021/`, `05Landuse/logs/` | analysis `landuse-harmonization-annual` | same directories |
| `03Data/transfer_logs/atmqa_*.out`, `qa_*.out` (599 QC job outputs) | `qc/raw/ISIMIP4b/InputData/logs/` | `03Data/transfer_logs/` |

Reason: these support reports that are not adopted (Q1), are superseded by
the production converter, or are routine job output; the conclusions are
re-established when the audits are redone in English or when the converter
runs from a clean repository.

## 5. Remaining code steps (reduced scope)

| Step | Legacy path | Target | Rewrite |
|---|---|---|---|
| 7 | `03Data/scripts/build_inventory.py`, `make_batch_lists.py`, `transfer_batch.sh` | `workflow/01_acquisition/` | paths via `ISIMIP4B_WORKDIR`; manifests under `manifests/inputs/`; needed for the next DKRZ transfer (UKESM1-3-LL) |
| 8 | `05Landuse/scripts/isimip_landuse_to_vic_annual.py`, `verify_forcing.py` | `workflow/04_forcing/landuse/` | inputs from `raw/ISIMIP4b/`, `raw/external/vic-coverage-version-a/5/`, `parameters/candidates/<set>/domain/`; output as forcing units under `forcing/landuse/<soc>/` with `provenance.yaml`; weights cache via `common/cache.py` (until it exists, to `scratch/`); verification output to `qc/forcing/landuse/<soc>/`. Blocked by D01 and D04 for production use, not for the rewrite. |
| 9 | — | `check_layout.py --workdir`; `LEGACY_INDEX.md` in the legacy area | — |
| 10 | — | cleanup list for approval (section 4.3) | — |

## 6. Execution log

| Step | Date | Result |
|---|---|---|
| 0 | 2026-09-29 | legacy inventory saved: 3,997 files, 1,691 md5 |
| 1 | 2026-09-29 | D15 committed (`c2dcbde`) |
| 2 | 2026-09-29 | raw data moved: 899/899 files, sizes match, 43-file md5 sample OK, 5crops full md5 OK |
| 3 | 2026-09-29 | protocol repo and VIC coverage in `raw/external/`; input manifests committed (`e2ceb59`) |
| 4 | 2026-09-29 | domain file adopted; parameter manifest committed (`dbabb5d`) |
| 5 | 2026-09-29 | six analysis tasks committed; five moved back the same day (Q10), 49 + 697 files md5-verified; `data-acquisition-2026-09` kept |
| 6 | 2026-09-29 | QA figures, reports and `summary.json` in `qc/raw/ISIMIP4b/InputData/`; transfer logs in `logs/01_acquisition/`; 599 QC job outputs moved back (Q10) |
| 7 | 2026-09-29 | `build_inventory.py`, `make_batch_lists.py`, `transfer_batch.sh` in `workflow/01_acquisition/` (`d605b6f`); batch lists reproduce the 2026-09-21 lists exactly |
| 8 | 2026-09-29 | `isimip_landuse_to_vic_annual.py`, `verify_forcing.py` in `workflow/04_forcing/landuse/`; test run histsoc 2021 bit-identical to the legacy trial after fixing a precision dependence on the weights cache; verification passed |
| 9–10 | pending | |
