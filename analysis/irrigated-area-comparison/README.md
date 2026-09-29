# irrigated-area-comparison

**Question.** How does the irrigated area in the VIC-WUR 5′ land-cover
dataset (classes 14 + 15) compare with ISIMIP4b `landuse-5crops` at 15′,
cell by cell and over time, and is HYDE a usable independent proxy for
15′→5′ downscaling?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** closed (2026-09-22). `cellwise_comparison.nc` is reused by later
land-use work, so the code was rewritten to the project layout.

**Inputs.**
- `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-5crops_*_15arcmin_annual_*.nc`
  and `landuse-totals_histsoc_15arcmin_annual_1850_2021.nc`;
- `raw/ISIMIP4b/InputData/geo_conditions/countrymasks/`;
- `raw/external/vic-coverage-version-a/5/coverage_VersionA_v5_<year>.nc`;
- `parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc`.

**Outputs.** `workdir/analysis/irrigated-area-comparison/`:
`cellwise_comparison.nc`, `statistics_global.csv`, `statistics_regional.csv`,
`threshold_sensitivity.csv`, `top_disagreement_cells.csv`,
`multiscale_agreement.csv`, `timeseries_global.csv`,
`peryear_cellwise_2003_2021.csv`, `summary.json`,
`downscale_waterfill_test.json`, `figures/fig01…fig12`, `logs/`.

**Code.** `regions.py` (ISO3 → 12 regions), `compare_irrigated_area.py`
(main computation, ~75 s, ~3 GB), `make_figures.py`,
`downscale_waterfill_test.py`. Paths are resolved from `ISIMIP4B_WORKDIR`;
outputs go to `$ISIMIP4B_WORKDIR/analysis/irrigated-area-comparison/`.
`inventory.md` documents every input metadata item checked;
`hyde_review.md` is the literature review of HYDE.

**Conclusion.** Recorded so far only in the legacy report
`vic_global/isimip4b/02Audit/ISIMIP4b_VIC_irrigated_area_comparison_and_HYDE_review_2026-09-22.md`
(Chinese, not adopted). Re-audit in English pending. Key numbers (2021): VIC
3.08 Mkm² vs ISIMIP 2.97 Mkm², IoU 0.52; HYDE is not independent of LUH and
is not used.
