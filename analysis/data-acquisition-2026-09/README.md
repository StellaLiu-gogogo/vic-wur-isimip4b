# data-acquisition-2026-09

**Question.** Which ISIMIP4b input files exist on DKRZ for `water_global`,
how large are they, which does VIC-WUR need (priority A/B/C), and what was
planned and approved for transfer to Anunna in September 2026?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** closed (2026-09-21). The accepted transfers are recorded in
`manifests/inputs/isimip4b-dkrz-2026-09-21/`; this task keeps the planning
material that is not an acceptance record.

**Inputs.** `find` listing of `/work/bb0820/ISIMIP/ISIMIP4b/` taken on DKRZ
levante on 2026-09-21; Anunna storage figures of the same day.

**Outputs.** `workdir/analysis/data-acquisition-2026-09/inventory/`:
`dkrz_find_raw_2026-09-21.tsv`, `dkrz_deref_2026-09-21.tsv`,
`dkrz_isimip4b_inventory_2026-09-21.{csv,md}`, per-batch file lists and
expected sizes (`batch_1…6`), `atmos_raw_files.txt`,
`anunna_space_raw_2026-09-21.txt`, `anunna_storage_report_2026-09-21.md`.

**Code.** None here; the inventory and batch-list generators are production
acquisition code in `workflow/01_acquisition/` (D15 step 7).

**Conclusion.** Batches 1–4 and the four 5crops files were transferred and
accepted (see the manifest README). Not transferred: UKESM1-3-LL atmosphere,
tasmin/tasmax/prsn, and all priority-C datasets; a new approval is required
for each.
