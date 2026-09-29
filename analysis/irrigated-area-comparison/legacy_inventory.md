# Input inventory — irrigated-area comparison (VIC-WUR 5′ vs ISIMIP4b landuse-5crops 15′)

Compiled 2026-09-22 with `ncdump -h`, `netCDF4`/`numpy` (env `py39`), `stat`, `md5sum`, `ssh levante`. Every item below was read from the file itself, not from file names or earlier reports. Log of the numeric checks: `logs/compare_irrigated_area.log`, `logs/run_compare.out`.

## 1. ISIMIP4b land-use, 15 arcmin, `landuse-5crops` (the only ISIMIP land-use product used here)

| item | value |
|---|---|
| DKRZ path (source of truth) | `levante:/work/bb0820/ISIMIP/ISIMIP4b/InputData/socioeconomic/landuse/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc` (regular file, not a symlink) |
| local copy used | `02Audit/evidence/irrigated_area_comparison_5crops_15arcmin/inputs_staged/histsoc/landuse-5crops_histsoc_15arcmin_annual_1850_2021.nc` — rsync 2026-09-22; **md5 `cf868f0e9f7bc447fb5f4f01c7b4ee09` identical on levante and Anunna** (`logs/md5_*_5crops_histsoc.txt`) |
| **not present in `03Data/raw_dkrz`** | the QA report (`03Data/QA_report_2026-09-21.md` §2) states that 5crops/forests/subgroups were deliberately not transferred (priority C). Only histsoc 15′ was staged for this analysis. Not staged: `landuse-5crops_{1850soc,2021soc}_15arcmin`, `_ssp1vl_`, `_ssp3h_` (sizes on DKRZ: 289.6 MB, 436.7 MB, 436.9 MB), and all 30arcmin variants. |
| size / mtime on DKRZ | 591,329,932 bytes, 2026-09-15 16:26:20 +0200 |
| dimensions | `time` = 172 (UNLIMITED), `lat` = 720, `lon` = 1440 |
| time | `days since 1850-1-1 00:00:00`, **calendar `365_day`**, values 0 … 62415 → 1850-01-01 … 2021-01-01, annual (`cell_methods = "time: mean"`) |
| latitude | `lat[0]` = 89.875 → `lat[-1]` = −89.875, **N→S**, step 0.25°, cell centres |
| longitude | −179.875 … 179.875, W→E, step 0.25° |
| grid | 0.25° × 0.25° regular lat/lon, global, `nominal_resolution = "25 km"` |
| variables (fraction of **whole grid cell**, `units = "1"`, `_FillValue = missing_value = 1e20f`, float32) | `c3ann_irrigated`, `c3ann_rainfed`, `c4ann_irrigated`, `c4ann_rainfed`, `c3nfx_irrigated`, `c3nfx_rainfed`, `c3per_irrigated_food`, `c3per_rainfed_food`, `c3per_irrigated_bf`, `c3per_rainfed_bf`, `c4per_irrigated_food`, `c4per_rainfed_food`, `c4per_irrigated_bf`, `c4per_rainfed_bf`, `pastures` |
| **irrigated total used** | `f_ISIMIP = c3ann_irrigated + c4ann_irrigated + c3nfx_irrigated + c3per_irrigated_food + c3per_irrigated_bf + c4per_irrigated_food + c4per_irrigated_bf` (7 variables). There is **no `cropland_irrigated` variable in the 5crops file**; that name exists only in `landuse-totals`. Cross-check 2021: `sum(7) − landuse-totals.cropland_irrigated`: max abs diff 6.5e-8, 0 cells > 1e-6 → identical. The two `_bf` (2nd-generation bioenergy) classes are exactly 0 everywhere in histsoc. |
| what the number is | **grid-cell fraction of the full cell** (global attribute `comment`: "Fractions are of the whole grid cell, not land area"). Empirically: sum(cropland_total + pastures + forests_and_natural_vegetation + urbanareas) over valid cells has p50 = 1.000 and min = 0 (coastal / ice / water cells), i.e. the water/ice part of a coastal cell is *not* re-normalised out. Therefore **no land-fraction multiplication is needed**: A = f × A_full. This is a *physical-area* fraction (LUH3 land state), **not harvested area**. |
| valid range 2021 | positives 1.2e-6 … 0.997; 26,366 cells > 0 |
| fill pattern | 778,261 fill cells (ocean + Antarctica: 100 % of rows < −60°), 258,539 valid land cells; fill mask identical for all 7 variables and for `landuse-totals` |
| provenance (global attrs) | `source = "LUH3 V1.2 (CMIP7 input4MIPs UofMD-landState-3-1-2), multiple-states and multiple-management, processed for ISIMIP4b"`, `source_version = "v20260408"`, `doi = 10.5281/zenodo.19261724`, `references = Hurtt et al. 2020; Chini et al. 2021`, `institution = PIK`, `creation_date_isimip = 2026-09-15T14:25:10Z`, `isimip_id = 2cbeffa3-418c-4f30-9766-4e6aa806ab25`, license CC BY 4.0 (LUH data, UMD) |
| scenario | `histsoc` (1850–2021). Per the DKRZ consistency check (`02Audit/evidence/DKRZ_landuse_soc_consistency_check_2026-09-18.txt`), `1850soc` ≡ histsoc 1850 and `2021soc` ≡ histsoc 2021 exactly. |
| irrigated area outside the VIC latitude window [−56°, 84°] | 0 km² (no irrigated cells) |

`landuse-15crops_*` files exist locally but were **not opened, not used** in this analysis (constraint 2).

## 2. ISIMIP geo_conditions used

| file | content | checks |
|---|---|---|
| `03Data/raw_dkrz/InputData/geo_conditions/countrymasks/countrymasks-fractional_15arcmin.nc` (version 2026.07i) | 248 ISO3 float variables `(lat, lon)` + `world`; 720×1440, lat N→S 89.875…−89.875, lon −179.875…179.875 | sum of country fractions per cell: min 0, max 1.0000000; **21,628 cells with 0 < sum < 0.999** (coastal partial cells, so area-weighting is required); `world` == sum of countries (max diff 8e-6), 299,417 cells > 0. No fill value. Used for regional statistics with fractional area weights (`regions.py` maps all 248 codes to 12 country groups; leftover 1−Σ is "Unassigned"). |
| `geo_conditions/landseamask/landseamask.nc`, `landseamask_water-global.nc` | 0.5° only (360×720) | **not used** (wrong resolution for a 15′ comparison; the 5crops fill mask and the country-mask `world` field are the 15′ land references) |

No cell-area variable exists in any of the ISIMIP files; areas are computed on the sphere (R = 6371 km):
`A_full(lat) = R² · Δλ · [sin(lat+Δφ/2) − sin(lat−Δφ/2)]`, Δλ = Δφ = 0.25° (15′) or 1/12° (5′).

## 3. VIC-WUR side (vic_parameter project; all paths verified to exist and were opened)

### 3.1 Domain
`/lustre/nobackup/WUR/ESG/liu297/vic_coupled/Data/VIC/domain/global/vic_global_5min_domain_nogl.nc`

| item | value |
|---|---|
| dims | `lat` = 1680, `lon` = 4320 |
| lat | −55.95833 … 83.95833, **S→N**, step 1/12°; lon −179.95833 … 179.95833 W→E |
| `mask` (int, fill 0) | values {0, 1}; **2,188,551 active cells** of 7,257,600 |
| `area` (float, m², fill −9999) | finite everywhere (also over ocean); ratio to spherical area 0.9955 … 1.0088 (ellipsoidal-type area). Active-cell total: 136.2091 Mkm² (`area`) vs 136.2188 Mkm² (spherical) → 0.007 % difference. |
| `frac` ("fraction of grid cell area") | **exactly 1.0 on every active cell** (min = max = 1.0), so VIC has no partial-land coastal cells; a cell is entirely active or inactive. Hence `coverage` fractions are whole-cell fractions, and VIC "land area" per 5′ cell = A_5 × mask. |
| history | subset of `vic_global_5min_domain_fullextent.nc` to lat −55.958…83.958 (2024-11-22), `mask=int(mask)` (2025-04-17) |

### 3.2 Annual land-use forcing (the product compared)
`/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_{2003..2022}.nc` — **20 files, 2003–2022 only** (≈32 MB each, 2026-08-13). No VIC land-use product exists for 1850–2002, so historical snapshot years (1850/1900/1950/2000) can only be shown for ISIMIP.

| item | value |
|---|---|
| dims | `time` = 1, `veg_class` = 16, `lat` = 1680, `lon` = 4320; same grid as the domain (verified `allclose`) |
| `coverage(time, veg_class, lat, lon)` | float32, `units = "1"`, `long_name = "annual vegetation coverage fraction"`, `_FillValue = NaN`; NaN exactly on inactive cells, finite on all active cells; Σ over 16 classes on active cells ∈ [0.9999998, 1.0000002] |
| `veg_class:class_names` | `evergreen_needleleaf|evergreen_broadleaf|deciduous_needleleaf|deciduous_broadleaf|mixed_forest|closed_shrubland|open_shrubland|woody_savanna|savanna|grassland|permanent_wetland|rainfed_crop|urban|irrigated_non_paddy_crop|irrigated_paddy_crop|barren` |
| **classes 14 and 15 (1-based)** | index 13 = `irrigated_non_paddy_crop`, index 14 = `irrigated_paddy_crop`. Confirmed by (i) the class_names attribute, (ii) `docs/HumanImpact_VersionA_16class接口契约.md` ("Irrigation plugin 的 `irr_class` 只映射 vegetation classes 14 和 15", `paddy=[0,1]`, `irr_init.c:94`), (iii) the 16-class parameter bundle `outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc` (same `class_names`). Class 12 `rainfed_crop` is not irrigated. **VIC irrigated total = class 14 + class 15 (paddy included).** |
| time | `days since <year>-01-01`, calendar `standard`, one step per file |
| global attrs | `product_status = "Version-A annual dynamic land-use forcing"`, `forcing_contract = "PLUGIN_FORCE_TYPE CV coverage YEAR <prefix>"`, `source_cv16 = .../version_a_cv16_barren_baseline_v5/HumanImpact_VersionA_Cv16_barren_baseline_v5_<year>_5min_domain_nogl.nc` |
| manifest | `manifests/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2021.json`: status pass, 2,188,551 valid cells, max Cv closure error 2.4e-7, sha256 `3034884c…` |
| 2021 values | class 14: 506,988 cells > 0, positive values 1.9e-13 … 1.0 (median 7.7e-3); class 15: 215,941 cells > 0, 7.5e-8 … 0.982 (median 5.4e-3) → **very many tiny non-zero fractions** (5′ cells with 0 < A ≤ 1 km²: see report) |

### 3.3 What the VIC irrigated fractions mean (provenance chain, from the vic_parameter docs and manifests)
- Cropland total: "Candidate L" = max(MODIS MCD12Q1 LC_Type2 cropland, MIRCA-OS v2 *lower* bound) where `MIRCA_lower = max(max_month_irrigated, max_month_rainfed)` = **maximum monthly cropped area** (MMCAG), i.e. a *physical* area proxy, **not harvested area** (`docs/HumanImpact_crop_MODIS_MIRCA与crop_calendar设计.md` §5.1–5.2, §5.7).
- Management split inside the reconciled cropland: `irrigated total = MIRCA-OS v2 max_ir`; `paddy = min(raw monthly paddy, max_ir)`; `irrigated_non_paddy = max_ir − paddy` (§10; `manifests/human_impact/crop_split_v2_2003_2022_acceptance.json`, `paddy_policy = "min(raw monthly paddy, official MMCAG max_ir)"`).
- Temporal rule: MIRCA-OS v2 snapshots 2000/2005/2010/2015/2020; the 2021 split file carries `temporal_rule = "hold_2020"` (`work/human_impact/crop_split_v2/annual/MIRCA-OS_v2_candidate_L_crop_split_2021_5min_domain_nogl.nc`), i.e. **VIC 2021 irrigated pattern = MIRCA-OS 2020 management applied to 2021 MODIS-reconciled cropland**. 2003–2015 interpolate between snapshots.
- MIRCA-OS v2 source: HydroShare `e4582ca0042148338bb5e0148b749ed6` (2026-03 release), 5′, 2160×4320 global grid (§10).
- Upstream of MIRCA-OS (from the vic_parameter docs only; verified further in `hyde_review.md`): MIRCA-type products allocate FAO/AQUASTAT/national statistics with irrigation maps (GMIA/AEI) as spatial patterns — see the HYDE review for the dependency between HYDE, LUH3 and MIRCA/GMIA.

## 4. What was *not* found / not used
- HYDE: no `*hyde*` file under `vic_parameter`, `isimip4b` or `vic_coupled/Data` (searched 2026-09-22). The HYDE evaluation is therefore documentary (`hyde_review.md`) plus a mechanics test of the allocation scheme with the VIC 5′ pattern as stand-in weights (`downscale_waterfill_test.py`).
- `landuse-15crops_*`: present locally, not opened.
- `landuse-5crops` for 2021soc / SSP1-VL / SSP3-H: on DKRZ only (not staged); not needed for the 2021 comparison. The earlier consistency check shows SSP files equal histsoc 2021 in 2022 and diverge from 2025.
- 0.5° `landseamask*.nc`: not used (resolution).
