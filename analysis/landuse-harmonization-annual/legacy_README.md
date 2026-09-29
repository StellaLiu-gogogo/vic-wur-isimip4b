# Annual land-use harmonization with ISIMIP4b `landuse-15crops` — prototypes (2026-09-23)

Supports `02Audit/VICWUR_ISIMIP4b_annual_landuse_harmonization_plan_15crops_2026-09-23.md`. Prototype only; no production forcing written; nothing outside this directory modified. Inputs are the local `03Data/raw_dkrz/.../landuse-15crops_*_15arcmin_*.nc` and `landuse-urbanareas_*` files (batch 1, md5-verified), VIC v5 annual coverage 2003–2022, bundle v3, activity masks v5, and the Köppen-Geiger 1991–2020 0.1° map (Beck et al. 2023).

| file | what |
|---|---|
| `check_15crops_consistency.py` → `check_15crops_consistency.json`, `union_15crops.npz` | metadata; 2021 three-way check (15crops vs 5crops vs landuse-totals); `rice_irrigated ≤ Σ irrigated` for every year/scenario; annual global totals per VIC class; per-class time-max union (12 / 14 / 15) with first-positive year and scenario bitmask |
| `compare_paddy_2021.py` → `compare_paddy_2021.json`, `figures/p01` | 2021 class 15 vs `rice_irrigated` (and class 14 vs Σirr − rice) with the same framework as the irrigated-area comparison |
| `union_backfill_paddy.py` → `union_backfill_paddy.json`, `_fields.npz`, `figures/p04–p05` | per-class fallback parents vs VIC union; LAI/fcanopy/albedo backfill ladder (same class ≤500 km → same Köppen class → 5° band → global) for new class 15 and class 14 tiles |
| `annual_harmonize_prototype_15crops.py` → `annual_harmonize_prototype_15crops.json`, `figures/p02–p03` | annual allocation with 15crops + urbanareas targets, VIC 2003–2022 mean weights, water-filling, fallback chains with cross-class record, single-child rule (share < 1e-3), natural remainder; 8 target years |
| `logs/` | run logs |

Environment: `/home/WUR/liu297/miniconda3/envs/py39/bin/python` (numpy, netCDF4, scipy, rasterio, matplotlib). Runtimes: consistency pass ≈ 9 min (streams 3.7 GB), paddy comparison 1 min, annual prototype 4 min (~2 GB), union/backfill ≈ 5 min (~5 GB).

## Corrections 2026-09-23 (evening)
- `annual_harmonize_prototype_15crops.py` now saves `annual_harmonize_prototype_15crops_union.npz` and reports the correct full union (existing bundle v3 tiles ∪ allocated) and the new-tile set U_new = allocated \ existing per class. Earlier "union" counts were the allocation union only.
- `union_backfill_paddy.py` now backfills every 5′ tile of U_new (paddy 47,098; class 14 347,939), not one representative child per fallback parent, and reports donor distances for L2 tiles only (≤500 km by construction) separately from the pre-cut nearest-donor distances.
- `order_sensitivity.py` → `order_sensitivity.json`, `figures/p06`: sequential orders A/B vs order-free joint water-filling; joint is the production method.
