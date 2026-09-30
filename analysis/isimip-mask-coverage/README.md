# isimip-mask-coverage

**Question.** How does the ISIMIP `water_global` land-sea mask (0.5°,
67 420 cells) relate to the VIC-WUR 5 arcmin domain
(`vic-global-5arcmin-version-a`)? Which mask cells has VIC no active cell
for, which VIC cells lie outside the mask, what does the protocol require,
and what would each option of decision D08 (keep the domain, extend it
fully, extend it partially) cost in new 5′ cells?

**Classification.** Analysis; user decision 2026-09-30. Reason: the
product is a decision (D08); nothing here is read by a workflow stage. If
D08 leads to a domain extension, that extension is implemented in
`workflow/03_parameters/`, and the grid relation established here is
re-implemented as a `02_preprocessing` cache; this task then becomes
`promoted`.

**Status.** `closed` (2026-09-30). D08 was decided the same day: option
(a), keep the domain (`docs/decisions/D08-mask-coverage.md`).

**Inputs** (read-only, paths relative to `$ISIMIP4B_WORKDIR`).

- `raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_water-global.nc`
  (the mask for global water models), `landseamask.nc` (W5E5 generic mask,
  with Antarctica) and `landseamask_no-ant.nc`, for comparison.
- `parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc`
  (`mask` = active cells; `frac` = 1 on every cell of the original land
  template, which still includes Greenland; `area`).
- `raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_2010.nc`
  (optional, to test whether vegetation data exist for candidate new cells).
- `raw/external/isimip-protocol-4/f9be7b0…/` (protocol text and definitions),
  the ISIMIP web page "Preparing simulation files" and the `isimip-qc` source
  on GitHub (both read on 2026-09-30) for the reporting rules.
- Consulted only to establish provenance of the `nogl` domain (legacy area,
  `vic_global/01oc_natural/03vic_input/old/`): the pre-cut domain and the
  5′ Greenland polygon confirm that `mask` = `frac` minus Greenland.

**Code.**

- `compare_masks.py` — grid relation check, 6×6 block coverage, reverse
  check, cell categories, regional and latitude tables, option counts, and
  the two cell-wise NetCDF files. `--scratch` writes to
  `scratch/isimip-mask-coverage/` for test runs; `--coverage FILE` adds the
  vegetation-data test.
- `plot_maps.py` — figures from the NetCDF files (matplotlib only).

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python analysis/isimip-mask-coverage/compare_masks.py \
    --coverage $ISIMIP4B_WORKDIR/raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_2010.nc
python analysis/isimip-mask-coverage/plot_maps.py
```

Runtime about one minute; the environment needs `xarray` (added to
`environments/isimip4b.yaml` for this task).

**Outputs.** `workdir/analysis/isimip-mask-coverage/`:

- `report.md` — the English report answering the five questions.
- `cellwise_comparison_0p5deg.nc` — per 0.5° cell: the three ISIMIP masks,
  number of active VIC cells (0–36), VIC land-template cells, active area
  and area fraction (candidate `contfrac`), VIC cells outside the mask,
  neighbour count, category code.
- `cellwise_comparison_5arcmin.nc` — per 5′ cell: VIC mask, land template,
  parent-in-mask flag, status code.
- `tables/` — `summary.json`, `summary.md`, `isimip_cell_categories.csv`,
  `uncovered_isimip_cells.csv`, `uncovered_by_region.csv`,
  `vic_active_outside_mask_cells.csv`, `vic_outside_by_region.csv`,
  `summary_by_latitude_band.csv`, `histogram_active_cells_per_isimip_cell.csv`,
  `isimip_masks_comparison.csv`.
- `figures/` — global category map, Arctic zoom, five regional zooms,
  active-cells-per-cell map with histogram, VIC area-fraction map,
  mismatch-by-latitude bars.

**Conclusion.** The VIC 5′ grid is an exact 6×6 subdivision of the ISIMIP
0.5° grid (opposite latitude order, VIC limited to 56°S–84°N, which
contains every mask cell). VIC has active cells in 64 110 of the 67 420
mask cells (95.1 %); the 3 310 uncovered cells (2.2 % of the mask area)
are Greenland (2 970 cells, 74 % of the uncovered area, land in VIC's
template but deliberately inactive) and 340 small islands, coasts and
open-ocean cells for which VIC has no 5′ land information at all (only 45
of them are land in the W5E5 mask). Conversely 11 328 active VIC cells
(0.5 %) lie in 2 532 coarse cells outside the mask, all of them ocean in
every ISIMIP mask (coastline fragments, Lake Ladoga, Kara-Bogaz-Gol). The
protocol and the QC tool do not require a value in every mask cell;
unsimulated cells are filled with 1e+20. Recommendation: option (a), keep
the domain and report the uncovered cells as missing. The user took this
decision on 2026-09-30; the maintained record is
`docs/decisions/D08-mask-coverage.md`.
