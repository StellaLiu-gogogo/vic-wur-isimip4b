# HYDE (History Database of the Global Environment) — review for use as 5′ irrigation weights under ISIMIP4b / LUH3

Prepared 2026-09-22 for VIC-WUR (Wageningen). Web/literature review executed by a research sub-agent (WebSearch/WebFetch), key quotes re-checked by hand in the saved page texts (`logs/hyde_sources/`). Every factual statement carries its source URL and access date. "Could not be verified" is stated explicitly where a primary page was unreachable. Section 12 (evaluation of the downscaling scheme) is the analyst's assessment and combines this review with the numeric results of the comparison (`../../ISIMIP4b_VIC_irrigated_area_comparison_and_HYDE_review_2026-09-22.md`).

## 1. Name, institutions, lead author, purpose

- Full name: **History Database of the Global Environment (HYDE)**. The HYDE 3.2 paper describes it as "an internally consistent combination of historical population estimates and allocation algorithms with time-dependent weighting maps for land use" (source: https://essd.copernicus.org/articles/9/927/2017/, accessed 2026-09-22).
- Lead author/maintainer: Kees (C.G.M.) Klein Goldewijk, Copernicus Institute of Sustainable Development, Utrecht University (contact in the HYDE 3.2.1 readme: c.g.m.kleingoldewijk@uu.nl, listing Utrecht University and PBL Netherlands Environmental Assessment Agency) (source: https://archaeology.datastations.nl/api/access/datafile/5396388, accessed 2026-09-22).
- Institutional history: developed from the 1990s at RIVM (NL), then MNP → PBL; "since 2014, developed collaboratively with Utrecht University; from 2020 it is fully and solely supported by UU" (source: https://landuse.sites.uu.nl/hyde-project/, accessed 2026-09-22).
- Purpose: "historical land-use reconstructions covering the whole Holocene which can be freely used by modelers and teachers"; the ESSD paper stresses use by climate/ESM communities and states "this most recent HYDE 3.2 version is again applied in the follow-up product LUH2" (sources: https://landuse.sites.uu.nl/hyde-project/ and https://essd.copernicus.org/articles/9/927/2017/essd-9-927-2017.pdf, accessed 2026-09-22).

## 2. Versions

The UU datasets page (https://landuse.sites.uu.nl/datasets/, accessed 2026-09-22) lists the lineage:

| Version | Year | Coverage | Notes (as stated on the UU page) | Documentation / DOI |
|---|---|---|---|---|
| HYDE 3.1 | 2011 | 10 000 BCE – 2005 CE, 5′ | "Population, cropland and pasture only" | Klein Goldewijk et al. 2011, Global Ecol. Biogeogr. 20:73–86, doi:10.1111/j.1466-8238.2010.00587.x (metadata confirmed via https://api.crossref.org/works/10.1111/j.1466-8238.2010.00587.x; the Wiley page returned HTTP 403) |
| HYDE 3.2 | 2017 | 10 000 BCE – 2015 CE (UU page says "– CE 2020"; the ESSD paper and DANS readme say 2015) | "Incl. irrigated areas, rice, intensive pasture, extensive rangelands. FAOdata from 1961-2015" | Klein Goldewijk et al. 2017, ESSD 9:927–953, https://doi.org/10.5194/essd-9-927-2017; data https://doi.org/10.17026/dans-25g-gez3. An earlier 2016 beta DOI 10.17026/dans-znk-cfy3 is marked "(replaced)" by ISIMIP (https://data.isimip.org/10.48364/ISIMIP.887218.1, accessed 2026-09-22) |
| HYDE 3.2.1 | Sept 2017 | as 3.2 | "replaces former 2017_beta_releases 3.2.000 and 3.2.001 … Major updates concern use of new FAO data until the year 2014 (instead of 2012), improved computations of (physical) Rice areas, and an adjustment of the cropland area for India before 1000 CE" | Same DANS DOI; DANS record "Version 2.0", files `HYDE3_2_1-baseline.zip` (5.34 GB) etc. (source: https://archaeology.datastations.nl/api/datasets/:persistentId/?persistentId=doi:10.17026/DANS-25G-GEZ3 and the readme, accessed 2026-09-22) |
| HYDE 3.3 | 2023 | 10 000 BCE – 2023 CE, 5′ | "radiocarbon archaeological data (onset of agriculture) for Eurasia & ArchaeoGlobe … FAOdata from 1961-2017 … MODIS … MapBiomas for Brazil 1985-2020 (MapBiomas_c8), Indonesia 2000–2020 … Baseline, Lower and Upper scenario. Extension of the database to year 2023" | No peer-reviewed paper: pastclim states "there is no current publication for 3.3" (https://evolecolgroup.github.io/pastclim/reference/HYDE_3.3_baseline.html, accessed 2026-09-22). Data DOI 10.24416/UU01-94FNH0 on UU YODA, reported by datahub.io (https://datahub.io/climate-and-environment/hyde-history-database-of-the-global-environment, accessed 2026-09-22); the YODA page https://public.yoda.uu.nl/geo/UU01/94FNH0.html is behind an Anubis bot-challenge and **could not be read directly** |
| HYDE 3.4 | 2024 | 10 000 BCE – 2024 CE, 5′ | "MapBiomas Brazil 1985-2022 (c8), Indonesia 2000–2022 (MB 2.0), China 1900-2019. FAOdata from 1961-2021" | No paper found. **This is the version used by LUH3** (§8). YODA links exist on the UU page but are not machine-readable (bot-challenge) |
| HYDE 3.5 | 2025 | 10 000 BCE – 2025 CE, 5′ | "MapBiomas_c9 … New FAOSTAT data for 1961 – 2022"; "paper currently in preparation" | source: https://landuse.sites.uu.nl/datasets/ and https://landuse.sites.uu.nl/hyde-project/ (accessed 2026-09-22) |

The UU page also lists GCB-specific YODA builds (`hyde33_MapBiomas_v12`, `hyde33_MapBiomas_c7`, `hyde34_MapBiomas_c8`, `hyde35_MapBiomas_c9`) used as input to the 2022–2025 Global Carbon Budgets. No "HYDE 4.0" exists on any of these pages.

**Bottom line on "current, public, documented":** HYDE 3.2.1 is the last version with a peer-reviewed methods paper and an open, machine-accessible archive (DANS). HYDE 3.3/3.4/3.5 are public on UU YODA but have no paper; 3.4 is the LUH3 input.

## 3. Resolution, extent, time coverage, time step

- Grid: 5 arcmin, global; ASCII header in every file: `ncols 4320, nrows 2160, xllcorner -180, yllcorner -90, cellsize 0.0833333, NODATA_value -9999` (source: HYDE 3.2.1 readme, https://archaeology.datastations.nl/api/access/datafile/5396388, accessed 2026-09-22). This grid is identical in origin and spacing to the VIC 5′ domain (VIC rows −55.958…83.958 are a latitude subset of it).
- Time steps (HYDE 3.2.1): "Time intervals are 1000 yr for the BCE period, then 100 yr till 1700, 10 yr till 2000, and from 2000 - 2015 1 year timesteps" (same readme). Hurtt et al. 2020 confirm what LUH2 received: "at 5′ spatial resolution every 100 years from 800 to 1700, every 10 years from 1700 to 2000, and then annually from 2000 to 2015" (source: https://gmd.copernicus.org/articles/13/5425/2020/, accessed 2026-09-22).
- HYDE 3.3 extends to 2023 CE; 3.4 to 2024; 3.5 to 2025 (source: https://landuse.sites.uu.nl/datasets/, accessed 2026-09-22).
- Post-1950 annual steps in HYDE 3.4: the input4MIPs discussion notes HYDE 3.4 "shifted to annual data post-1950 (previously decadal)", which caused spiky transitions in the first LUH3 release (source: https://github.com/PCMDI/input4MIPs_CVs/discussions/141, accessed 2026-09-22).

## 4. Variables and file names (HYDE 3.2.1 distribution; 3.3 follows the same category set)

From the HYDE 3.2.1 readme (https://archaeology.datastations.nl/api/access/datafile/5396388, accessed 2026-09-22), per year `<yr>` in `yearAD_lu.zip` / `yearBC_lu.zip`:

- `cropland<yr>.asc` – "total cropland area, in km2 per grid cell, after 1960 identical to FAO's category 'Arable land and permanent crops'"
- `grazing<yr>.asc` – total grazing land, "after 1960 identical to FAO's category 'Permanent Pasture'"; `pasture<yr>.asc`, `rangeland<yr>.asc` – split of grazing (aridity/population rules)
- `ir_norice<yr>.asc`, `rf_norice<yr>.asc`, `ir_rice<yr>.asc`, `rf_rice<yr>.asc` (irrigated/rain-fed non-rice and rice; the readme's one-line descriptions of `ir_norice` and `ir_rice` are transposed, an evident typo)
- `tot_irri<yr>.asc` – "total actual irrigated area, in km2 per grid cell"; `tot_rainfed<yr>.asc`, `tot_rice<yr>.asc`
- Population zip: `popc_`, `popd_`, `rurc_`, `urb_`, `uopp_<yr>.asc` ("total built-up area … in km2 per grid cell")
- Country/region tables (`/txt`): `conv_rangeland_c.txt`, `tot_irri_c.txt`, etc. (converted rangeland appears only as tables in 3.2.1)
- `/General files`: `garea_cr.asc` (grid-cell area km², spherical Earth), `landlake_cr.asc`, `maxln_cr.asc` ("maximum landarea available per gridcell in km2"), `iso_cr.asc`, `sub_iso_cr.asc`
- Three scenario directories: Baseline, Lower, Upper; plus Anthromes.

So HYDE **does** contain: total cropland (yes), rainfed cropland (yes, `tot_rainfed` = `rf_norice`+`rf_rice`), irrigated cropland (yes, `tot_irri` = `ir_norice`+`ir_rice`), irrigated/rainfed rice (yes), pasture/rangeland (yes), urban/built-up (yes, `uopp`), population (yes).

HYDE 3.3 categories: "cropland (irrigated and rain-fed, including rice distinction), grazing lands (pasture, converted rangeland, natural rangeland), population (total, urban, rural, density), built-up area" (source: https://evolecolgroup.github.io/pastclim/reference/HYDE_3.3_baseline.html, accessed 2026-09-22). The exact HYDE 3.3/3.4 file list could not be verified (YODA bot-challenge).

## 5. Units, format, `maxln_cr`

- Units: **km² per grid cell** for all land-use and built-up grids (not fractions); population in inhabitants per cell (`popc`) or inhabitants km⁻² (`popd`) (source: readme above).
- Format: "Arcmap asciigrid format" (`.asc`) inside zips; no NetCDF in the 3.2.1 distribution. MIRCA-OS/pastclim redistributions exist, but the official HYDE files are ASCII grids.
- `maxln_cr.asc` = "maximum landarea available per gridcell in km2". In the allocation it is the ceiling `Gareamax = Garea_cell − Uarea_t − Parea_t − NLarea_t`, where "Garea_cell is the land area of a 5′ grid cell (spherical Earth) except water bodies, snow and ice; Uarea_t is the urban built-up area; Parea_t is protected area … NLarea is the no-land-use area in central Australia" (source: https://essd.copernicus.org/articles/9/927/2017/essd-9-927-2017.pdf §3.2.2, accessed 2026-09-22). For our use: convert km² grids to fractions by dividing by `maxln_cr` (land fraction) or `garea_cr` (whole-cell fraction); the VIC-side capacity should remain the VIC active land area (whole cell), not `maxln_cr`.

## 6. Observation, reconstruction, or model-based allocation?

HYDE is a **model-based spatial allocation (hindcast) of tabular statistics**, not an observation product. National/subnational totals (FAO after 1961; historical censuses and per-capita assumptions before) are distributed over 5′ cells with weighting maps: "The land use statistics are allocated to grid cells according to a mix of two weighting maps: a reference map of 2010 CE for cropland (Wcrop_satellite2010), derived from satellite imagery of ESA (2016) for the present, and a historical map (Wcrop_historic_t)"; "We assume that the influence of Wcrop_reference_t is zero in the year 1500 CE and 100 % in 2010 CE"; "There are large and many uncertainties that come with the hindcast methods applied in this study" (source: ESSD 2017 PDF, accessed 2026-09-22). Post-1961 national totals are FAOSTAT by construction.

## 7. Allocation method (HYDE 3.2; the basis of 3.3/3.4)

All quotes from https://essd.copernicus.org/articles/9/927/2017/essd-9-927-2017.pdf (accessed 2026-09-22):

- Order: "first, we allocate cropland, then rice, then irrigation and finally grazing land."
- Present-day reference maps: ESA CCI Land Cover 300 m, 2010 epoch, aggregated to 5′ fractions; LandScan 2012 for population; MapSPAM 2005 for rice. HYDE 3.3+ add MODIS and MapBiomas (Brazil/Indonesia) and Yu et al. (China) (source: https://landuse.sites.uu.nl/datasets/, accessed 2026-09-22).
- Historical weighting: `Wcrop_historic_t = Wpop_t · Wsuit · Wriver · Wcoast · Wslope · Wtemp_crop` (population density, soil suitability, distance to rivers/coast, slope, temperature > 0 °C).
- **Irrigation statistics**: "The input data for the category 'areas equipped for irrigation' for the post-1960 CE period were taken from FAO (2015) and for the 1900–1960 CE period from Siebert et al. (2015) [HID]. For the 1700–1900 CE period estimates were taken from Siebert (2008). … The statistics for the actual irrigated area for the 1960–2010 CE period were derived by multiplying FAO's category 'area equipped for irrigation' with the fraction of 'equipped/actual irrigated area' from the GMIA_v5 database … we used the last known ratio and applied this to the complete series."
- **Irrigation spatial pattern**: "For the spatial representation of current global areas equipped for irrigation and actual irrigated areas, we used the Siebert et al. (2015) global data set of monthly irrigated and rain-fed crop areas around the year 2000 (MIRCA2000)." (The paper cites MIRCA2000 as "Siebert et al. 2015"; the MIRCA2000 paper is Portmann et al. 2010 — a citation slip in the source.) Then: "All irrigated area must fall within the computed cropland area. Next, we check whether there is enough water available to irrigate (Wwav), for which we use, as a proxy, a discharge map derived from Van Beek and Bierkens (2008) [PCR-GLOBWB]. Furthermore, we assume that when the aridity index (Waridity) is low, the need for irrigation is higher." `Wirri_t = Waridity · Wwav · Wirri_2010`.
- Rice: FAO rice statistics post-1960, harvested→physical correction ("In China … this ratio of physical area to harvested area is around 0.6 … the rest of the world is assumed to have a ratio of 1.0"), irrigated share from Ricepedia; "Rain-fed rice was allocated first, irrigated rice second."
- Backcasting: per-capita land use per country "modelled back in time … followed a curved trajectory", multiplied by historical population; Lower/Upper scenarios.
- 2015 irrigated total: "we estimate the global irrigated area in 2015 CE at 276 Mha" (= 2.76 Mkm², actual irrigated). For comparison: ISIMIP4b/LUH3 2015 = 2.82 Mkm², VIC 2015 = 3.02 Mkm² (this analysis, `timeseries_global.csv`).

## 8. HYDE ↔ LUH2 / LUH3, and where LUH irrigation comes from

- LUH2 (CMIP6): "Historical maps of land use were based on the History of the Global Environment database (HYDE)"; "The version of the HYDE 3.2 dataset used for the baseline LUH2 historical product was the 2016_beta_release version" (source: https://gmd.copernicus.org/articles/13/5425/2020/, accessed 2026-09-22). LUH2 v2h README: "Agriculture and urban land-use based on HYDE 3.2" (source: https://luh.umd.edu/LUH2/LUH2_v2h_README.pdf, accessed 2026-09-22).
- **LUH2 irrigation** (re-checked in the saved page text): "Data on irrigated area and area of flooded rice were obtained from HYDE. The irrigated fraction of each crop type was computed during the historical period by dividing the HYDE 3.2 irrigated fraction of each grid cell by the HYDE 3.2 cropland fraction of each grid cell. This fraction is then used as the irrigated fraction of each crop subtype." (Hurtt et al. 2020, same URL). No FAO/AQUASTAT/GMIA source enters LUH2 directly; it enters via HYDE. Variables: `irrig_c3ann, irrig_c3per, irrig_c4ann, irrig_c4per, irrig_c3nfx` "(units fraction of crop area)" and `flood`.
- LUH2-GCB (annual updates): HYDE 3.2 with FAO updates and "a 5-year trend" extrapolation (source: https://essd.copernicus.org/articles/13/4175/2021/, accessed 2026-09-22).
- **LUH3** (CMIP7, `UofMD-landState-3-1-2`): "LUH3 for CMIP7 fast track uses new land-use inputs from the HYDE 3.4 dataset … the new annual temporal resolution results in large inter-annual fluctuations in land-use transitions. To reduce the impacts of these fluctuations, we have resampled the HYDE data every 10 years from 1700 to present day, and then linearly interpolated between those sampled points to generate annual values." Also: "Since LUH3 is built upon the recent land-use dataset created for Global Carbon Budget (i.e. LUH2-GCB2024), it has considerable similarity with that product" (source: https://input4mips-cvs.readthedocs.io/en/latest/dataset-overviews/land-use/, accessed 2026-09-22). Chini's CMIP7 slides: "New HYDE 3.4 data for historical cropland, grazing land, and urban land … New FAO inputs within HYDE for years 1961-2021 … Extension to current year (using trend from previous 5 years)" (source: https://wcrp-cmip.org/wp-content/uploads/2024/10/S1_03_LChini.pdf, accessed 2026-09-22). Version history: v3.0 retracted for "spurious spikes post-1950"; 3.1 → 3.1.1 → 3.1.2 metadata-only; DOI 10.5281/zenodo.19261724, 850–2024, 0.25° (https://zenodo.org/records/19261724, accessed 2026-09-22).
- LUH3 irrigation source: the LUH3 management file carries the same `irrig_*` and `flood` variables. **No LUH3 document was found that states explicitly where LUH3's irrigated fraction comes from**; the CV page says LUH3 is "very similar to the LUH2 data" and points to Hurtt et al. 2020 for methodology, so the HYDE-derived approach is implied but not verified for LUH3.
- ISIMIP: ISIMIP3b used LUH2 v2h "which in turn is based on HYDE 3.2" (source: https://data.isimip.org/10.48364/ISIMIP.887218.1, accessed 2026-09-22). ISIMIP4a/4b landuse is "Derived from the CMIP7 input4MIPs UofMD Land-Use Harmonization (LUH3) dataset … Historical: UofMD-landState-3-1-2, SSP1-VL: UofMD-landState-vl-3-1-1, SSP3-H: UofMD-landState-h-3-1-1 … v20260408"; "Irrigation is a share of the crop area, not of the grid cell. In the LUH3 source the irrigated fraction is defined relative to the area of its crop functional type, and the published irrigated and rainfed variables are already the product of the two"; "The 0.5° product is conservatively remapped from the native 0.25° grid … Use the 15arcmin files when the global total matters" (source: https://www.isimip.org/gettingstarted/input-data-bias-adjustment/details/205/, accessed 2026-09-22).

## 9. Future scenarios

- HYDE has **no** future scenarios; all versions end at the current year (source: https://landuse.sites.uu.nl/datasets/, accessed 2026-09-22).
- LUH2 futures came from IAMs (IMAGE, GCAM, MESSAGE-GLOBIOM, AIM, REMIND-MAgPIE; https://luh.umd.edu/data.shtml). LUH2 harmonization: IAM changes "aggregated to 2°×2°" then "disaggregated into 0.25°×0.25° grids"; future irrigation: "Annual changes in national irrigated areas were computed and then applied to the previous year's gridded irrigation fractions … first increasing irrigated area on grid cells with existing irrigation, and then adding any additional needed irrigated area equally to all nonirrigated cropland grid cells within each country" (source: https://gmd.copernicus.org/articles/13/5425/2020/, accessed 2026-09-22).
- LUH3 futures (2022–2100): VL from "the REMIND-MAgPIE team at PIK" (https://zenodo.org/records/19353397); H from "the GCAM team at JGCRI/PNNL" (https://zenodo.org/records/19354835) (accessed 2026-09-22). ISIMIP4b uses only VL and H. The local DKRZ check found the two SSP 5crops/totals files identical to histsoc 2021 in 2022 and diverging from 2025.

## 10. Known limitations / critiques of HYDE irrigated area

- Equipped vs actually irrigated: a single last-known GMIA v5 actual/equipped ratio per country applied to the whole series; spatial pattern = MIRCA2000 (year 2000, GMIA-v4-based), so post-2000 expansion (NW India, NE China) enters only through national totals redistributed by aridity/discharge rules.
- Non-independence: "The HYDE 3.2 relies on the FAO-GMIA and the MIRCA 2000 to parametrise irrigated areas, with the MIRCA 2000 being also a gridded product grounded on the FAO-GMIA" (Puy et al. 2021, https://www.nature.com/articles/s41467-021-24508-8, accessed 2026-09-22).
- Rice: fixed 0.6 physical/harvested ratio for Asian rice countries; MapSPAM 2005 pattern.
- Hindcast sensitivity: "very sensitive to the shape of the curve into the past" (ESSD 2017).
- Temporal artefacts: annual HYDE 3.4 produced "spurious spikes post-1950" in LUH3 v3.0; LUH3 now resamples decadally and interpolates.
- No published validation of HYDE 3.3/3.4 irrigated grids was found.

## 11. License and download mechanics

- HYDE 3.2/3.2.1 (DANS): open access, no registration; DANS metadata shows "CC0-1.0" while the readme states "CC BY 3.0"; `HYDE3_2_1-baseline.zip` 5.34 GB, `-anthromes.zip` 141.8 MB, `-general_supplementary.zip` 23.6 MB (source: DANS API record, accessed 2026-09-22). Lower/Upper scenario zips are not in the listing.
- HYDE 3.3/3.4/3.5: Utrecht University YODA, linked from https://landuse.sites.uu.nl/datasets/. YODA pages use an Anubis proof-of-work challenge that blocks non-browser clients, so **registration, file sizes, license and NetCDF availability could not be verified**; a browser download should work. datahub.io reports "CC BY 4.0" and DOI 10.24416/UU01-94FNH0 for HYDE 3.3 (third-party).
- No Zenodo deposit of HYDE was found; official format is ESRI ASCII grid. PBL pages returned "Access denied" on 2026-09-22.

## Related irrigation datasets (independence check)

- **MIRCA2000** (Portmann, Siebert, Döll 2010, doi:10.1029/2008GB003435): 5′, ~2000, 26 irrigated + 26 rain-fed crop classes, monthly growing areas in ha (https://zenodo.org/records/7422506, accessed 2026-09-22). Based on GMIA + national statistics; not HYDE-based (HYDE uses it).
- **MIRCA-OS** (Kebede et al., Scientific Data 2025): 5′, 2000/2005/2010/2015, 23 crop classes, CC BY 4.0, HydroShare. **Not independent of HYDE** (re-checked): "Gridded (5-arcminute) cropland extent (CE) came from the History Database of the Global Environment (HYDE) dataset … we utilized HYDE's annual maps of cropland extent spanning from 2000 to 2015", with irrigated area constrained by Mehta et al.'s AEI (sources: https://www.nature.com/articles/s41597-024-04313-w and https://www.hydroshare.org/resource/60a890eb841c460192c03bb590687145/, accessed 2026-09-22). The VIC Version-A product uses MIRCA-OS **v2** (2026-03, HydroShare `e4582ca0…`, snapshots 2000–2020); its documentation was not re-checked here, but the v1 lineage applies.
- **GMIA v5** (Siebert et al. 2013): 5′, ~2005, area equipped for irrigation plus "percentage … actually used for irrigation" (https://data.apps.fao.org/catalog/iso/f79213a0-88fd-11da-a88f-000d939bc5d8, accessed 2026-09-22). HID (Siebert et al. 2015): AEI 1900–2005 at 5′ (https://hess.copernicus.org/articles/19/1521/2015/).
- **Meier, Zabel & Mauser 2018** (HESS 22:1119): 30″ irrigated-area map from GMIA v5 + ESA-CCI NDVI; independent of HYDE (https://hess.copernicus.org/articles/22/1119/2018/, accessed 2026-09-22).
- **Mehta et al. 2024** (Nature Water 2:254): 5′ AEI 2000/2005/2010/2015; "AEI increased … from 2000 (297 Mha) to 2015 (330 Mha)"; **uses HYDE 3.2 cropland as constraint** and GMIA 2005 pattern (https://www.nature.com/articles/s44221-024-00206-9, https://zenodo.org/records/6886564, accessed 2026-09-22).

Dependency graph (documented links only):
`FAO AEI + GMIA v5 (+HID) → HYDE 3.x irrigation (pattern = MIRCA2000 × aridity × discharge)` → `LUH2 (documented) / LUH3 (implied)` → `ISIMIP4b landuse-5crops`;
`HYDE cropland + Mehta AEI (GMIA-based) → MIRCA-OS → VIC Version-A classes 14/15`.
Hence **neither the VIC proxy nor HYDE is an independent validation of the ISIMIP field**; the comparison in this report is between two HYDE/GMIA-lineage products with different allocation rules (LUH3/HYDE's vs MIRCA-OS's).

## 12. Evaluation of the proposed 15′→5′ allocation scheme with HYDE weights

Scheme under evaluation (per parent j with children i): `w_i = max(HYDE_irr_i, 0) · active_land_i`; `A_i = A_ISIMIP_parent · w_i/Σw` if Σw > 0; documented fallback if Σw = 0; capacity `A_i ≤ active_land_i` with iterative water-filling. "Using HYDE" means using its 5′ spatial distribution as weights inside each 15′ parent, never replacing the ISIMIP parent total.

Numeric context from this analysis (HYDE itself is not on disk; the mechanics were tested with the VIC 2021 5′ pattern as stand-in weights, `downscale_waterfill_test.json`):
- 26,366 ISIMIP parents carry irrigated area in 2021 (2.967 Mkm²). With VIC weights 1,177 parents (23.5 k km², 0.79 %) have Σw = 0 and need a fallback; 13 of those have no VIC land at all (506 km²), 778 have a weighted pattern in a neighbouring parent (20.6 k km²). Water-filling converged in 5 iterations, 2,102 children saturated, 87 parents needed the spill rule, conservation error 9e-11 km². With uniform weights (no proxy) the within-parent placement differs by 0.68 Mkm² (23 % of the total), i.e. the choice of proxy moves about a quarter of the irrigated area between children.
- Because LUH3's irrigated fraction is (documented for LUH2, implied for LUH3) HYDE-derived at 5′ and then aggregated to 0.25°, HYDE weights would be expected to have Σw = 0 in far fewer parents than the VIC weights (the ISIMIP zero/non-zero pattern is itself a HYDE product), and to reproduce the "isolated zero" cells seen in the ISIMIP field. This expectation is **not verified** (no HYDE data locally).

| aspect | assessment |
|---|---|
| Advantages | (1) Source-consistent: HYDE is the documented 5′ basis of the LUH pipeline, so HYDE-weighted disaggregation approximately inverts LUH3's own aggregation; parent totals are conserved by construction. (2) Full historical coverage 1850–2021 at 5′ (decadal to 2000, annual after), matching the ISIMIP histsoc period, which the VIC product (2003–2022) cannot provide. (3) Same 5′ grid origin/spacing as the VIC domain (no regridding). (4) km² units with `maxln_cr`/`garea_cr`, so conversion to fractions is unambiguous. (5) Separate `ir_rice`/`ir_norice` gives a paddy/non-paddy weight that the 5crops product lacks. |
| Disadvantages | (1) Not observation: the modern-era irrigation pattern is MIRCA2000 (year 2000, GMIA-based) modulated by aridity and discharge; post-2000 expansion enters only via national totals. The VIC proxy (MIRCA-OS 2020) carries more recent sub-national information for 2015–2021. (2) HYDE 3.4 (the LUH3 input) has no paper, is only on UU YODA (bot-protected), and its file list/units/license could not be machine-verified; 3.2.1 is documented but ends 2015 and differs from what LUH3 used. (3) ASCII grids, ~5 GB per version; a conversion pipeline is required. (4) LUH3 resampled HYDE decadally then interpolated annually, so the annual HYDE 3.4 pattern ≠ what LUH3 used year by year. (5) HYDE-weighted allocation would place area only where HYDE has irrigation; VIC parameter tiles (LAI/albedo/root for classes 14/15) exist only where the VIC bundle already has irrigated tiles — new tiles need the parameter fallbacks described in the full-union audit. |
| Circularity | HYDE → LUH3 → ISIMIP (parent) and HYDE → MIRCA-OS/Mehta → VIC (child weights). Using HYDE as weights makes the 5′ product a re-expansion of ISIMIP's own upstream, which is *consistent* but must not be presented as validation. Equally, the VIC-vs-ISIMIP agreement (IoU 0.52) is not an independent check of either. |
| Historical years | 1850–2002: HYDE is the only 5′ irrigation reconstruction; usable as primary weight there (decadal steps interpolated), or a frozen VIC-2003 pattern can be used because the parent totals already carry the historical signal (LUH3 states are HYDE-based) and pre-1950 irrigated area is small (1.0 Mkm² in 1950, 0.35 in 1850). 2003–2021: VIC pattern available annually. |
| Future years 2022–2100 | HYDE has no future. LUH3's own rule grows irrigation first on already-irrigated cells; a frozen last-year weight (VIC 2022 pattern, or HYDE 2021 in a HYDE run) with a documented fallback for parents that become irrigated only in the SSPs is the consistent choice. HYDE offers nothing beyond that frozen pattern. |
| vs current VIC proxy | VIC proxy: more recent (MIRCA-OS 2020), already has parameter tiles, 0.8 % of parent area needs fallback in 2021; but spreads area over 3.2× more cells than ISIMIP and is absent in 1850–2002. HYDE: consistent with the parent's own lineage, historical coverage, but older pattern and unverified 3.4 files. |
| Recommendation | **Not as primary proxy for 2003–2021** (VIC pattern preferred: same grid, in production, more recent management data, parameter tiles present). **Secondary/fallback and historical option**: HYDE as the weight for 1850–2002 if a year-specific 5′ pattern is wanted, and as the fallback when the VIC pattern is zero in a parent (before the nearest-parent rule). **Sensitivity experiment**: re-run 2021 with HYDE 3.4 weights to quantify within-parent placement uncertainty (expected order: the 0.68 Mkm² VIC-vs-uniform difference is an upper bound). Do not use HYDE for 2022–2100. Before any of this: download HYDE 3.4 (and 3.2.1 for the documented baseline) in a browser from YODA/DANS, verify file list, `tot_irri` units and `maxln_cr`, and record md5 in the evidence directory. |

## Bibliography (all accessed 2026-09-22)

- https://essd.copernicus.org/articles/9/927/2017/ ; PDF https://essd.copernicus.org/articles/9/927/2017/essd-9-927-2017.pdf
- https://doi.org/10.17026/dans-25g-gez3 ; https://archaeology.datastations.nl/api/datasets/:persistentId/?persistentId=doi:10.17026/DANS-25G-GEZ3 ; readme https://archaeology.datastations.nl/api/access/datafile/5396388
- https://landuse.sites.uu.nl/datasets/ ; https://landuse.sites.uu.nl/hyde-project/
- https://public.yoda.uu.nl/geo/UU01/94FNH0.html (blocked by bot-challenge) ; https://doi.org/10.24416/UU01-94FNH0
- https://datahub.io/climate-and-environment/hyde-history-database-of-the-global-environment
- https://evolecolgroup.github.io/pastclim/reference/HYDE_3.3_baseline.html
- https://onlinelibrary.wiley.com/doi/10.1111/j.1466-8238.2010.00587.x (HTTP 403) ; https://api.crossref.org/works/10.1111/j.1466-8238.2010.00587.x
- https://www.pbl.nl/en/hyde-history-database-of-the-global-environment (Access denied)
- https://gmd.copernicus.org/articles/13/5425/2020/ (Hurtt et al. 2020)
- https://essd.copernicus.org/articles/13/4175/2021/ (Chini et al. 2021)
- https://luh.umd.edu/data.shtml ; https://luh.umd.edu/LUH2/LUH2_v2h_README.pdf
- https://input4mips-cvs.readthedocs.io/en/latest/dataset-overviews/land-use/
- https://zenodo.org/records/19261724 ; https://zenodo.org/records/19353397 ; https://zenodo.org/records/19354835 ; https://zenodo.org/records/22017128 (HTTP 404)
- https://github.com/PCMDI/input4MIPs_CVs/discussions/141
- https://wcrp-cmip.org/wp-content/uploads/2024/10/S1_03_LChini.pdf
- https://gmd.copernicus.org/articles/19/2627/2026/
- https://www.isimip.org/gettingstarted/input-data-bias-adjustment/details/205/ ; …/details/208/ ; …/details/82/
- https://data.isimip.org/10.48364/ISIMIP.887218.1 ; https://www.isimip.org/protocol/isimip4-protocol/
- https://www.geo.uni-frankfurt.de/45218031/Data_download_center_for_MIRCA2000 ; https://zenodo.org/records/7422506
- https://www.nature.com/articles/s41597-024-04313-w ; https://www.hydroshare.org/resource/60a890eb841c460192c03bb590687145/
- https://data.apps.fao.org/catalog/iso/f79213a0-88fd-11da-a88f-000d939bc5d8
- https://hess.copernicus.org/articles/19/1521/2015/ ; https://hess.copernicus.org/articles/22/1119/2018/
- https://www.nature.com/articles/s44221-024-00206-9 ; https://zenodo.org/records/6886564
- https://www.nature.com/articles/s41467-021-24508-8
- https://essd.copernicus.org/articles/17/3473/2025/

Saved page texts: `logs/hyde_sources/` (hyde32.txt, readme_hyde321.txt, hurtt2020.html, luh2_v2h_readme.txt, isimip205.html, mircaos.txt, mehta.txt, uu_datasets.txt, …).
