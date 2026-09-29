# Irrigated-area comparison: VIC-WUR 5′ (classes 14+15) vs ISIMIP4b `landuse-5crops` 15′ — and HYDE review

Created 2026-09-22. Self-contained analysis directory; nothing under `03Data/raw_dkrz`, `vic_parameter` or `vic_coupled` was modified. Only `landuse-5crops` is used on the ISIMIP side (no `landuse-15crops`; `landuse-totals.cropland_irrigated` is read once as a cross-check and is numerically identical to the 5crops irrigated sum).

Final report (Chinese): `../../ISIMIP4b_VIC_irrigated_area_comparison_and_HYDE_review_2026-09-22.md`.

## Files

| file | content |
|---|---|
| `inventory.md` | input inventory with every metadata item actually checked (paths, sizes, grids, calendars, units, fill, semantics of fractions, VIC class 14/15 provenance) |
| `regions.py` | ISO3 → 12 country-group regions (all 248 codes of the ISIMIP fractional country mask) |
| `compare_irrigated_area.py` | main computation: alignment, 3×3 conservative aggregation, cell-wise metrics, global/regional statistics, threshold sensitivity, top-20 cells, multi-scale agreement, time series; writes the tables and `cellwise_comparison.nc` |
| `make_figures.py` | all figures (`figures/fig01…fig12`) from the outputs above |
| `downscale_waterfill_test.py` / `.json` | mechanics test of the proposed 15′→5′ weighted allocation with water-filling capacity limits, using the VIC 2021 5′ pattern as stand-in weights (HYDE is not on disk) |
| `statistics_global.csv` | conservation/totals, mask terms, alignment, global metrics on the common valid grid (2021) |
| `statistics_regional.csv` | per-region metrics: `*_areaweighted` columns use fractional country shares as weights; `*_dominantregion` columns count cells by their dominant region |
| `threshold_sensitivity.csv` | category counts/areas for presence threshold ∈ {0, 1, 10} km² × equality tolerance ∈ {5, 10, 20} % (floor 1 km²) |
| `top_disagreement_cells.csv` | 20 cells with largest \|A_vic − A_isimip\| with coordinates, both areas, ratios, dominant country and region |
| `multiscale_agreement.csv` | IoU / Dice / correlations after summing both fields to 30′, 1°, 2°, 5° |
| `timeseries_global.csv` | ISIMIP histsoc annual global irrigated area 1850–2021 (all cells and within VIC land parents); VIC 2003–2022 total / non-paddy / paddy |
| `peryear_cellwise_2003_2021.csv` | cell-wise agreement metrics for each common year 2003–2021 |
| `cellwise_comparison.nc` | 15′ grid (ISIMIP orientation, N→S) with `A_isimip`, `A_vic`, `A_vic_nonpaddy`, `A_vic_paddy`, `L_vic`, `A_full`, `D`, relative differences, `overlap`, `union`, `E_vic`, `E_isimip`, `overlap_ratio`, `category`, masks, `region_id`, `country_fraction_sum`, ISIMIP snapshots 1850/1900/1950/2000/2010/2021; all km² |
| `summary.json` | machine-readable copy of the key numbers |
| `hyde_review.md` | web/literature review of HYDE (versions, content, method, LUH dependency, suitability as 15′→5′ proxy), with URLs and access dates |
| `inputs_staged/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc` | verbatim copy of the DKRZ file (md5-verified), 591 MB; can be deleted and re-fetched with the rsync command in `logs/` |
| `logs/` | run logs, rsync log, md5 sums |

## Reproduce

```bash
cd /lustre/nobackup/WUR/ESG/liu297/vic_global/isimip4b/02Audit/evidence/irrigated_area_comparison_5crops_15arcmin
PY=/home/WUR/liu297/miniconda3/envs/py39/bin/python
$PY compare_irrigated_area.py      # ~75 s, ~3 GB RAM
$PY make_figures.py                # ~1 min
$PY downscale_waterfill_test.py    # ~20 s
```

## Definitions (short)
- `A_ISIMIP_15(j) = Σ_k f_k(j) · A_full(j)` with the 7 `*_irrigated*` CFT fractions (whole-cell fractions; no land-fraction factor).
- `A_VIC_15(j) = Σ_{i∈j} [coverage_14(i) + coverage_15(i)] · A_5(i) · mask(i)` (3×3 children, S→N flipped to N→S; conservation error 4e-9 km²).
- Spherical cell areas, R = 6371 km, both sides. Common valid grid = ISIMIP non-fill ∩ VIC parent with ≥ 1 active child (246,692 cells).
- Presence: A > 1 km² (sensitivity 0 / 10 km²); approx. equal: |D| ≤ max(1 km², 5 % · max(A_vic, A_isimip)) (sensitivity 10 %, 20 %).
- Regions: fractional country masks → 12 country groups; area-weighted by the fractional share so that border cells are split, not assigned.
