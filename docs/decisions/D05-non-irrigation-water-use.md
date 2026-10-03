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

**Option A** (user, 2026-10-02; recorded first as "executed as C", i.e. staged; the staging was withdrawn 2026-10-03 and all units are produced in one task, see Amendments):

1. The ISIMIP3a and ISIMIP3b water-abstraction files are acquired into
   `raw/external/`, checked and interpreted first (task D1: acquisition,
   QA, data description); the downscaling producer (task D2) follows.
2. Units `forcing/water_use/{histsoc,1850soc,2021soc}/` are produced first;
   `ssp1vlsoc-noadapt` (from ssp126) and `ssp3hsoc-noadapt` (from ssp370)
   are produced before the Group III runs, with the future withdrawal
   series scaled per cell so that it joins the historical 2021 value, and
   the consumption fraction held at its 2021 value (withdrawn 2026-10-03,
   see Amendments).
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

## Evidence from task D1 (2026-10-02)

Analysis `isimip3-water-abstraction-review`; report
`workdir/analysis/isimip3-water-abstraction-review/report.md`, QC summary
`qc/raw/external/isimip3-water-abstraction/dkrz-2026-10-02/summary.json`
(status `warning`), manifests `manifests/inputs/isimip3-water-abstraction.yaml`
(52 files, md5 against levante and sha512 against data.isimip.org) and
`manifests/inputs/watergap-groundwater-fractions.yaml`.

- Origin: the historical series is the multi-model mean (H08, PCR-GLOBWB,
  WaterGAP) of the ISIMIP2a `varsoc` simulations for 1901–2005, continued
  from 2006 with the WFaS SSP2 (RCP6.0) projection (Wada et al. 2016) and
  carried through ISIMIP2b into ISIMIP3a/3b; ISIMIP3a histsoc 2006–2021 is
  therefore a projection, not an observation-based reconstruction. Every
  year before 1901 equals 1901, so ISIMIP3b `1850soc` is the 1901 field.
  ISIMIP3b histsoc 1901–2014 is identical cell by cell to ISIMIP3a, and
  `2015soc` equals ISIMIP3a 2015. The SSP series (doi:10.48364/ISIMIP.423677,
  2026) is a separate product of H08, WaterGAP2 and CWatM and provides
  withdrawal only.
- The 2021/2022 step: global domestic withdrawal goes from 641 km³ (ISIMIP3a
  2021) to 518 (ssp126, −19 %) or 585 (ssp370, −9 %) km³ in 2022, industrial
  from 1 097 to 797 (−27 %) or 950 (−13 %) km³. Per cell, weighted by the
  2021 withdrawal, the median ratio is 0.79/0.89 (domestic) and 0.63/0.73
  (industrial), and 5–9 % of the domestic and 23–33 % of the industrial
  withdrawal is in cells that halve or double across the join (a normal
  year moves 1–4 %). The SSP 2015 values already differ from `2015soc`
  (0.95–0.97 domestic, 0.86–0.87 industrial globally), although the
  documentation states that they were rescaled to match the 2015
  historical data.
- The `modelstd` files carry no model spread: std equals the mean in more
  than 98 % of the cells.
- Published comparison: around 2010 domestic withdrawal is 445 km³ (FAO
  AQUASTAT 464) and industrial 853 km³ (AQUASTAT 768); domestic plus
  industrial 1 298 km³ (Floerke et al. 2013: 1 345).
- Further properties handled by D2: undecodable `years since` time axis,
  north-to-south rows, 280-row historical and 360-row SSP grids, zeros
  instead of fill values in the historical files, consumption above
  withdrawal in up to 2 259 domestic cells, and a one-year redistribution
  of industrial withdrawal in 2005.

## Amendments 2026-10-03

Decided by the user after reading the D1 report:

1. Option A stands. No questions are sent to the sector coordinators or to
   the owner of the WaterGAP tables; the data are used as ISIMIP3b
   delivered them.
2. The SSP withdrawal series are used raw, without rescaling and without a
   join to the 2021 historical value. The 2021/2022 step (global −9 to
   −27 %) is accepted and documented as a property of the source data;
   item 2 of the decision is withdrawn.
3. Consumption fraction in the SSP years follows the ISIMIP3b convention:
   wc/ww of the `2015soc` files, capped at 1 per cell; where it is
   undefined, the continental fraction of the same field is used.
4. The 2005 industrial anomaly is kept as delivered and noted in the unit
   provenance.
5. The WaterGAP tables are used as they are, with `G_FRACTGW_MAN` for the
   whole industrial sector; their provenance stays "unconfirmed" in the
   manifest.
6. Task D2 produces all five units (`histsoc`, `1850soc`, `2021soc`,
   `ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`) in one task; there is no
   separate task for the SSP units.

## Consequences

- `01_acquisition`: ISIMIP3a/3b water-abstraction files and the WaterGAP
  tables enter `raw/external/<dataset-id>/<version>/` with manifests in
  `manifests/inputs/`.
- `04_forcing`: new producer and verifier `workflow/04_forcing/water_use/`;
  units follow the forcing-unit contract (provenance, `qc.status`,
  `proleptic_gregorian`, one time step per yearly file). Task D2 produces
  all five units; the SSP units use the raw SSP withdrawal (amendments 2
  and 6).
- `05_simulation`: every campaign with direct human forcing runs with
  `WATERUSE TRUE`, `IRRIGATION TRUE`, `DAMS TRUE`; the smoke campaign uses
  the histsoc unit for 2011–2020 and no livestock sector.
- `08_delivery`: the model description states that non-irrigation water use
  is taken from the ISIMIP3a/3b harmonized datasets pending the ISIMIP4b
  release, that the SSP series are used as delivered, and that they step
  down from the 2021 historical value in 2022 (amendment 2).
- The parameter set gains no component from this decision; the irrigation
  groundwater fraction stays in the irrigation parameter component.
