# D15 — Migration of the legacy `vic_global/isimip4b/` area

Decision record. The working copy with the execution log is
`vic_global/isimip4b/06Migration/migration_plan_2026-09-29.md` until the
migration is complete; then this record is updated with the final log.

Status: **revision 2, approved 2026-09-29.** Execution log: section 8.
Revision 2 applies the decisions of 2026-09-29 (Q1–Q9 below).
Source: `/lustre/nobackup/WUR/ESG/liu297/vic_global/isimip4b/` (legacy area).
Target: `/lustre/nobackup/WUR/ESG/liu297/isimip4b/repo/` (Git) and
`/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir/`.

The plan is executed step by step, each step verified before the next.

## 1. Decisions applied

| # | Decision |
|---|---|
| Q1 | The 12 Chinese audit and plan reports are **not migrated** and no `legacy/` area is created in the repository. Audits needed later are redone in English. |
| Q2 | The ISIMIP protocol repository is cloned into `workdir/raw/external/isimip-protocol-4/<commit>/`. |
| Q3 | Closed analysis code is migrated as-is with hard-coded legacy paths noted; only reused or promoted code is rewritten. |
| Q4 | After moving the 1.39 TB: count + size for every file, md5 for a 5 % sample; full md5 by Slurm before first production use. |
| Q5 | The levante-side QA script stays with the acquisition code, documented as running on the data source. |
| Q6 | `03Data/qa_slices/` (5.5 GB) **stays in the legacy area**; decided later with `07_quality_control`. |
| Q7 | `05Landuse/trial_2021/weights_cache_v5_2003_2022.npz` is not migrated (a regenerable cache). |
| Q8 | VIC domain and vegetation parameters are adopted into `workdir/parameters/candidates/`; the VIC coverage dataset used as weights goes to `workdir/raw/external/`. Contract clause for adopted parameter sets added in commit `77dcb9e`. |
| Q9 | `01Info/` stays in the legacy area with `04Slides/`. |

## 2. Inventory of the legacy area

| Directory | Files | Size | Migrated |
|---|---|---|---|
| `01Info/` | 3 | 0.5 MB | no |
| `02Audit/` | 193 | 1.8 GB | evidence directories and 1.7 GB of staged ISIMIP files only |
| `03Data/` | 2,997 | 1.3 TB | raw data, manifests, scripts, QA figures and report, logs; not `qa_slices/` |
| `04Slides/` | 791 | 58 MB | no |
| `05Landuse/` | 12 | 85 MB | scripts and trial product; not the weights cache |

## 3. Principles

1. **Move, do not copy, large data.** Source and target are on the same
   Lustre filesystem, so `mv` is a rename: instant and reversible by renaming
   back. Content is not rewritten; verification is count and size against
   the pre-move inventory, plus md5 where stated.
2. **Copy, then rewrite, code.** Scripts are copied into the repository and
   adapted (paths via `ISIMIP4B_WORKDIR`, shared helpers via
   `workflow/common/`, version suffixes removed). The legacy copy stays until
   the final cleanup.
3. **Nothing in the legacy area is deleted by this plan.** A separate cleanup
   list is presented for approval afterwards.
4. **One verified step at a time.** Repository content: one commit per step.
   Workdir content: one `mv` per step with the pre-move inventory saved under
   `workdir/logs/01_acquisition/`.
5. **No English maintained record exists yet for the legacy conclusions.**
   Analysis task READMEs point to the legacy report path and state
   "re-audit pending" until an English audit is written.

## 4. Mapping

### 4.1 Not migrated (stay in the legacy area)

| Item | Reason |
|---|---|
| `01Info/` | Q9 |
| `02Audit/*.md` (12 reports) | Q1 |
| `02Audit/smoke_test/` | never executed; Snellius paths; superseded by `05_simulation` when implemented |
| `02Audit/evidence/landuse_monthly_harmonization_plan/` (49 MB) | withdrawn route; nothing downstream uses it |
| `03Data/qa_slices/` (5.5 GB) | Q6 |
| `04Slides/` | decided 2026-09-28 |
| `05Landuse/trial_2021/weights_cache_v5_2003_2022.npz` | Q7 |

### 4.2 Raw data → `workdir/raw/`

| Legacy path | Target | Method | Verification |
|---|---|---|---|
| `03Data/raw_dkrz/InputData/` (895 files, 1.39 TB) | `raw/ISIMIP4b/InputData/` | `mv` | count + size against `transfer_manifest_batch_*`; md5 of a 5 % sample |
| `02Audit/evidence/irrigated_area_comparison_5crops_15arcmin/inputs_staged/<soc>/landuse-5crops_*.nc` (4 files, 1.7 GB, md5 = DKRZ) | `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/` | `mv` | md5 against the `md5_remote_5crops_*.txt` records |
| — (new) | `raw/external/isimip-protocol-4/f9be7b0cdf83409315d9fa7da8581cc6fd6ff3e1/` | `git clone` + checkout, `.git` removed, 2 MB | `COMMIT` file with the SHA |
| `vic_parameter/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2003…2022.nc` (20 files, 621 MB; outside the legacy area) | `raw/external/vic-coverage-version-a/5/` | copy | md5 of source and copy |

All four rows are recorded in `repo/manifests/inputs/` (see 4.3).

### 4.3 Manifests → `repo/manifests/inputs/`

| Legacy path | Target |
|---|---|
| `03Data/raw_dkrz/MD5SUMS`, `03Data/inventory/transfer_manifest_batch_{1,1b,2,3,4}.txt` | `manifests/inputs/isimip4b-dkrz-2026-09-21/` plus one generated `inventory.tsv` (path, size, md5, batch, transfer date) covering the 895 + 4 files |
| `03Data/README.md` transfer table (English) | `manifests/inputs/isimip4b-dkrz-2026-09-21/README.md` |
| — (new) | `manifests/inputs/isimip-protocol-4.yaml` and `manifests/inputs/vic-coverage-version-a-5.yaml` |

### 4.4 Adopted VIC parameters → `workdir/parameters/candidates/`

| Source (outside the legacy area) | Target | Note |
|---|---|---|
| `vic_coupled/Data/VIC/domain/global/vic_global_5min_domain_nogl.nc` (87 MB) | `parameters/candidates/<parameter-set-id>/domain/` | needed now by the land-use converter |
| vegetation bundle `vic_parameter/outputs/human_impact/version_a/v1/…16class_soil-v10_root-b_v3.nc` | `parameters/candidates/<parameter-set-id>/vegetation/` | **deferred** until D01 and D04 are decided; the bundle may change |

Both are copied, never linked, and recorded in
`manifests/parameters/<parameter-set-id>.yaml` with source path, source
version, and per-file checksums (contract, "adopted" parameter sets).
`<parameter-set-id>` = `vic-global-5arcmin-version-a` (confirmed).

### 4.5 Analysis tasks → `repo/analysis/` and `workdir/analysis/`

| Legacy path | Task ID | Code and small docs → `repo/analysis/<task>/` | Products → `workdir/analysis/<task>/` | Status | Paths rewritten |
|---|---|---|---|---|---|
| `02Audit/evidence/` root files (protocol YAML extracts, DKRZ listings, email extract, HTML index) | `protocol-audit-2026-09` | README only | 21 files, 1.7 MB | closed | — |
| `02Audit/evidence/2026-09-20/` | `model-capability-audit-2026-09` | README only | 10 files, 4.7 MB | closed | — |
| `02Audit/evidence/irrigated_area_comparison_5crops_15arcmin/` (without `inputs_staged/`) | `irrigated-area-comparison` | 4 `.py`, `README.md`, `hyde_review.md`, `inventory.md` | `cellwise_comparison.nc`, 8 CSV/JSON, `figures/`, `logs/` | closed | yes (its `cellwise_comparison.nc` is reused) |
| `02Audit/evidence/landuse_2021_analysis/` | `landuse-scoping-2021` | 6 `.py` | 7 JSON, 5 PNG, 1 TXT | closed | no |
| `02Audit/evidence/landuse_annual_15crops_plan/` | `landuse-harmonization-annual` | 6 `.py`, `README.md` | 6 JSON, 3 NPZ (17 MB), `figures/` | promoted | yes |
| `05Landuse/trial_2021/` (without the weights cache) and `05Landuse/logs/` | `landuse-harmonization-annual` (subdirectory `trial-2021/`) | — | `coverage_ISIMIP4b_histsoc_2021.nc` (38 MB), ledger, QA and verification files, 3 logs (`trial_histsoc_2021_v1.1.out` renamed `trial_histsoc_2021_attempt1.out`) | promoted | — |

Each task README records the question, the classification (analysis, user
decision 2026-09-29), the status, the legacy report that used the results
(Chinese, not adopted, re-audit pending), and for unrewritten code the note
that paths refer to the legacy layout.

### 4.6 Workflow code → `repo/workflow/`

| Legacy path | Target | Rewrite |
|---|---|---|
| `03Data/scripts/build_inventory.py`, `make_batch_lists.py`, `transfer_batch.sh` | `workflow/01_acquisition/` | paths via `ISIMIP4B_WORKDIR`; manifests under `manifests/inputs/` |
| `03Data/scripts/levante_qa_slices.sh` | `workflow/01_acquisition/` | header states it runs on DKRZ levante against the source tree (Q5) |
| `03Data/scripts/qa_common.py` | `workflow/common/grid.py` and `workflow/common/plots.py` (cell area, mask, orientation; map plotting) | paths removed; mask path becomes an argument |
| `03Data/scripts/qa_landuse.py`, `qa_population_gdp.py`, `qa_dams_co2_geo.py`, `qa_atmos_plots.py`, `write_qa_report.py` | `workflow/07_quality_control/inputs/` | paths; outputs to `qc/raw/ISIMIP4b/InputData/`; `qa_atmos_plots.py` reads slices from a path argument (they stay in the legacy area) |
| `03Data/scripts/qa_atmos_fullseries.sbatch` | `workflow/07_quality_control/inputs/` | Slurm output path and conda path become template variables; environment recorded in `environments/` |
| `05Landuse/scripts/isimip_landuse_to_vic_annual.py` | `workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py` | inputs from `raw/ISIMIP4b/`, `raw/external/vic-coverage-version-a/5/`, `parameters/candidates/<set>/domain/`; output to `forcing/landuse/<soc>/` with `provenance.yaml`; weights cache written to `scratch/` until `common/cache.py` exists |
| `05Landuse/scripts/verify_forcing.py` | `workflow/04_forcing/landuse/verify_forcing.py` | same inputs; output to `qc/forcing/landuse/<soc>/` |

### 4.7 QC evidence and logs → `workdir/qc/` and `workdir/logs/`

| Legacy path | Target | Method |
|---|---|---|
| `03Data/figures/` (25 PNG, 5 JSON) | `qc/raw/ISIMIP4b/InputData/figures/`; `summary.json` generated from the JSON files with status `passed` per dataset as recorded in the QA report | `mv` + generate |
| `03Data/QA_report_2026-09-21.md` | `qc/raw/ISIMIP4b/InputData/reports/` | `mv` |
| `03Data/transfer_logs/atmqa_*.out` (595 files) | `qc/raw/ISIMIP4b/InputData/logs/` | `mv` |
| `03Data/transfer_logs/` rsync, md5, remote-stat, driver logs | `logs/01_acquisition/` (files, no job records) | `mv` |
| `03Data/inventory/` remainder (DKRZ listings, batch 5/6 plans, storage report, `atmos_raw_files.txt`) | `workdir/analysis/data-acquisition-2026-09/` with `repo/analysis/data-acquisition-2026-09/README.md` (closed) | `mv` |

## 5. Order of execution

| Step | Content | Size | Reversible by |
|---|---|---|---|
| 0 | Save the legacy inventory (paths, sizes, md5 of everything except `raw_dkrz` and `qa_slices`) to `workdir/logs/01_acquisition/legacy-inventory-2026-09-29.tsv` | — | — |
| 1 | `docs/decisions/D15-legacy-migration.md` (this plan, approved); commit | — | git |
| 2 | `mv` `raw_dkrz/InputData` and the four staged 5crops files (4.2); verify (Q4) | 1.39 TB | `mv` back |
| 3 | Clone the protocol repository; copy the VIC coverage dataset (4.2); input manifests (4.3); commit | 0.6 GB | git, delete copies |
| 4 | Confirm the parameter-set ID; copy the domain file; parameter manifest; commit | 87 MB | git, delete copy |
| 5 | Analysis tasks (4.5): one commit per task; products `mv` | ≈80 MB | git + `mv` back |
| 6 | QC evidence and logs (4.7); verify counts | 15 MB | `mv` back |
| 7 | Acquisition and QC code (4.6); rewrite; commit | — | git |
| 8 | Land-use converter and verifier (4.6); rewrite; commit | — | git |
| 9 | `check_layout.py --workdir`; write `LEGACY_INDEX.md` in the legacy area mapping every old path to its new location or "stays" | — | — |
| 10 | Present the cleanup list (emptied directories, copied scripts) for approval | — | — |

Steps 2–6 move data and need no code changes; steps 7–8 can follow later.

## 6. Legacy area afterwards

`01Info/`, `04Slides/`, `02Audit/*.md`, `02Audit/smoke_test/`,
`02Audit/evidence/landuse_monthly_harmonization_plan/`, `03Data/qa_slices/`,
the weights cache, the original copies of every migrated script (until
cleanup), and `LEGACY_INDEX.md`.

## 7. Confirmations (2026-09-29)

1. Parameter-set ID: `vic-global-5arcmin-version-a`.
2. Protocol repository: clone `f9be7b0` only.

Plan approved for execution on 2026-09-29.

## 8. Execution log

| Step | Date | Result |
|---|---|---|
