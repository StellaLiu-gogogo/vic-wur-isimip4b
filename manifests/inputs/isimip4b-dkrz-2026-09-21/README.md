# ISIMIP4b input data accepted from DKRZ (2026-09-21)

Source: DKRZ levante `/work/bb0820/ISIMIP/ISIMIP4b/`. Location in the workdir:
`raw/ISIMIP4b/InputData/` (DKRZ relative paths preserved).

`inventory.tsv` lists every accepted file with size, md5 (verified on both
ends), transfer batch, and transfer date: 899 files, 1,388,989,749,037 bytes.
`MD5SUMS` and `transfer_manifest_batch_*.txt` are the original transfer
records; the four `landuse-5crops` files were transferred separately on
2026-09-22 (batch `5crops-2026-09-22`, md5 recorded from levante).

| Batch | Content | Files | Bytes |
|---|---|---|---|
| 1 | landuse 15arcmin+30arcmin (5 soc), population 5arcmin + national csv, gdp/fixed-assets csv, reservoirs_dams, co2/ch4, countrymasks | 276 | 16,844,135,047 |
| 1b | geo_conditions from DKRZ directory symlinks (lakes, landseamask, river_routing, soil) | 24 | 11,778,698 |
| 2 | EC-Earth3-ESM-1-1, 7 VIC variables, QA decades (esm-hist 2011–2020, esm-scen7-vl/h 2022–2030) | 21 | 46,197,145,637 |
| 3 | EC-Earth3-ESM-1-1, 7 VIC variables, esm-hist 1850–2021, esm-scen7-vl and esm-scen7-h 2022–2100 | 224 | 498,453,498,611 |
| 4 | EC-Earth3-ESM-1-1, 7 VIC variables, esm-picontrol 1601–2100 | 350 | 825,728,794,721 |
| 5crops-2026-09-22 | landuse-5crops 15arcmin (histsoc, 2021soc, ssp1vlsoc-noadapt, ssp3hsoc-noadapt) | 4 | 1,754,532,113 |

Not transferred (no approval yet): UKESM1-3-LL atmosphere (595 files,
1.42 TB); tasmin/tasmax/prsn full series (510 files, 0.84 TB); priority C
datasets (2,921 files, 1.91 TB). The DKRZ inventory used for these counts is
kept as an analysis product (`workdir/analysis/data-acquisition-2026-09/`).

Verification after the move into this project (2026-09-29): all 899 files
present with the recorded size; md5 of a 43-file random sample and of the
four 5crops files identical to the records. A full md5 pass is due before the
first production use (D15, Q4).
