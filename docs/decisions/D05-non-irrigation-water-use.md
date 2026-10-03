# D05 — Non-irrigation water use while the ISIMIP4b dataset is not released

Status: **decided 2026-10-02** by the user (option A, staged).
Due stage: `04_forcing`.

## Context

VIC-WUR represents municipal, manufacturing and livestock water withdrawal
through the `wateruse` plugin. At the locked VIC commit (`model/vic.lock.yaml`,
`39e21ff5`) the plugin cannot be switched off for experiments with direct
human forcing: irrigation water is withdrawn only through it
(`plugins/irrigation/src/irr_use.c`, `irr_wateruse` is the only path unless
`POTENTIAL_IRRIGATION` is set) and dams register demand only when it is on
(`plugins/dams/src/dam_register.c`). Each non-irrigation sector is optional:
it is read only when its demand, groundwater-fraction and consumption-fraction
forcing prefixes are all given (`plugins/wateruse/src/wu_get_global_param.c`).

The ISIMIP4b protocol lists non-irrigation water use as a harmonized direct
human forcing "for the models that need it" (`protocol/02.experiments.md`,
`definitions/group3_requirements.yaml`) but defines no dataset. On DKRZ the
tree `ISIMIP4b/InputData/socioeconomic/` held no water-use data on 2026-09-18
and still none on 2026-10-02 (nine directories: fixed-assets, gdp,
land-transformation, landuse, n-deposition, n-fertilizer, population,
reservoirs_dams, wood_harvesting).

Data that exist on DKRZ (`/work/bb0820/ISIMIP/`), 0.5°, annual, m³/yr per
cell, domestic (`dom`) and industrial (`ind`) withdrawal (`ww`) and
consumption (`wc`):

| Set | Scenario | Years | Note |
|---|---|---|---|
| ISIMIP3a `water_abstraction` | histsoc | 1850–1900, 1901–2021 | "prepared from ISIMIP2b data (H08, PCR-GLOBWB, WaterGAP)"; grid 720 × 280 (−55.75° to 83.75°) |
| ISIMIP3b `water_abstraction` | histsoc | 1601–1849, 1850–1900, 1901–2014 | same origin |
| ISIMIP3b | 1850soc, 2015soc | 1601–2100 in three files | constant in time (1850soc domww 52.9 km³/yr) |
| ISIMIP3b | ssp126soc-noadapt, ssp370soc-noadapt, ssp585soc-noadapt | 2015–2100 | `domww`/`indww` only, `modelavg` and `modelstd` of H08, WaterGAP2, CWatM; grid 720 × 360 |

Global totals around the join (km³/yr): ISIMIP3a histsoc 2021 domww 641,
indww 1 097; ISIMIP3b ssp370 2022 domww 586; ssp126 2022 domww about 515;
ssp370 2017 indww 902. The future series therefore sit 10–20 % below the
historical series at the join.

The sibling project `vic_global/vic_parameter` already downscaled the
ISIMIP3a histsoc (1979–2021) and ISIMIP3b ssp126/ssp370 (2022–2100) series
to 5′ (`outputs/water_use/sectors/v1.1.0_20260818`, population-weighted
parent-to-child split with even-split fallback, conservation audited) and
built static groundwater fractions from WaterGAP tables
(`outputs/water_use/gwfrac/v1.1.0_20260818`) and a livestock demand from
FAOSTAT stocks (`outputs/water_use/livestock/v1.1.0_20260818`). A one-month
VIC gate run (2026-08-26, Anunna) with these files passed the water-budget
checks. They cannot be used as they are: the historical series starts in
1979, the files carry `calendar = standard` while the project runs on
`proleptic_gregorian` (VIC aborts on a calendar mismatch of plugin forcing),
the 2021/2022 step is uncorrected, the SSP consumption fractions come from
`2015soc`, the population proxy (Yan et al. 2022) stops in 2020, and the
directory contract has no adoption path for forcing units. The older chain
in `/lustre/backup/WUR/ESG/marin052/waterUseForcing/` (R and cdo) lost about
2.7 % of domestic demand through `setmisstoc,0` and is reference only.

## Options

| Option | Content | Assessment |
|---|---|---|
| A | Substitute the ISIMIP3a/3b series: histsoc 1850–2021 from ISIMIP3a; 1850soc and 2021soc constant; ssp1vlsoc-noadapt from ssp126, ssp3hsoc-noadapt from ssp370, joined to the 2021 historical value; downscaled to 5′ with the ISIMIP4b 5′ population of the same soc scenario; groundwater fractions from the WaterGAP tables; produced by `workflow/04_forcing/water_use/` as forcing units | full plugin stack; same data the ISIMIP3b models used; replaced by regenerating the units when ISIMIP4b releases its dataset; not official ISIMIP4b input, must be documented and reported to the sector coordinators |
| B | Irrigation only: `WATERUSE` on, no municipal, manufacturing or livestock sector | omits about 1 700 km³/yr of withdrawals (irrigation about 2 500–3 000); a capability VIC-WUR has would go unused; dams would see no non-irrigation demand |
| C | A, staged: historical and constant units first, SSP units before the Group III runs | same as A, decision on the SSP join rule taken now |
| D | Wait for the ISIMIP4b release | blocks the smoke campaign and every histsoc experiment |

## Decision

**Option A, executed as C** (user, 2026-10-02):

1. The ISIMIP3a and ISIMIP3b water-abstraction files are acquired into
   `raw/external/`, checked and interpreted first (task D1: acquisition,
   QA, data description); the downscaling producer (task D2) follows.
2. Units `forcing/water_use/{histsoc,1850soc,2021soc}/` are produced first;
   `ssp1vlsoc-noadapt` (from ssp126) and `ssp3hsoc-noadapt` (from ssp370)
   are produced before the Group III runs, with the future withdrawal
   series scaled per cell so that it joins the historical 2021 value, and
   the consumption fraction held at its 2021 value.
3. Sectors: municipal (domestic) and manufacturing (industrial =
   manufacturing + energy) now; livestock deferred (about 49 km³/yr, 3 % of
   non-irrigation withdrawal; needs FAOSTAT and GLW4 inputs).
4. Proxy for the 0.5° to 5′ split: ISIMIP4b 5′ `total-population` of the
   same soc scenario (`raw/ISIMIP4b/InputData/socioeconomic/population/`),
   not Yan et al. (2022).
5. Groundwater fractions: static, from the WaterGAP `G_FRACTGW` tables
   (copied into `raw/external/` with a manifest).
6. The method of `vic_parameter` (parent-to-child split restricted to active
   children, even-split fallback, lost-demand accounting) is ported into
   this repository with tests; nothing is adopted as a file.
7. The sector coordinators are asked (audit question Q-B) when the ISIMIP4b
   dataset will be released; when it is, the units are regenerated as a
   whole from it.

## Consequences

- `01_acquisition`: ISIMIP3a/3b water-abstraction files and the WaterGAP
  tables enter `raw/external/<dataset-id>/<version>/` with manifests in
  `manifests/inputs/`.
- `04_forcing`: new producer and verifier `workflow/04_forcing/water_use/`;
  units follow the forcing-unit contract (provenance, `qc.status`,
  `proleptic_gregorian`, one time step per yearly file).
- `05_simulation`: every campaign with direct human forcing runs with
  `WATERUSE TRUE`, `IRRIGATION TRUE`, `DAMS TRUE`; the smoke campaign uses
  the histsoc unit for 2011–2020 and no livestock sector.
- `08_delivery`: the model description states that non-irrigation water use
  is taken from the ISIMIP3a/3b harmonized datasets pending the ISIMIP4b
  release, with the join rule for the SSP scenarios.
- The parameter set gains no component from this decision; the irrigation
  groundwater fraction stays in the irrigation parameter component.
