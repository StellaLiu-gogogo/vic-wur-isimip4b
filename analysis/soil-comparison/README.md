# Soil comparison: version-a against version-b and version-c (task Z)

**Question.** Does smoothing the five 2-degree calibration fields of the soil (`depth[2]`, `Ds`, `Dsmax`, `Ws`, `c`;
parameter set `vic-global-5arcmin-version-b`, `workflow/03_parameters/soil/`) remove the 2-degree steps from the
simulated layer-2 soil moisture, baseflow and discharge without changing the global water balance or the discharge
at the GRDC stations for the worse, so that version-b can replace version-a in the production campaign? Added
2026-11-04 (user): what does the MPR soil candidate of vic_parameter (`vic-global-5arcmin-version-c`, every soil field
replaced, `workflow/03_parameters/soil/adopt_soil_fields.py`) do to the same run?

**Classification.** Analysis (user, 2026-11-02): the figures and tables are the basis of the decision whether to
promote version-b and change `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`; no workflow stage reads them.

**Status.** closed 2026-11-05: three sets compared, conclusion below; the user decided to promote version-b (job
43625069, `manifests/parameters/vic-global-5arcmin-version-b.yaml`, `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`).

**Runs.** Campaigns `soil-comparison-version-a`, `soil-comparison-version-b` and `soil-comparison-version-c`
(`configs/campaigns/`, non-production, identical except for the parameter set): the historical `histsoc` segment of `h_ssp3hsoc-noadapt_default`, 2011-2020,
cold start, one chunk, with the settings of the production campaign (VIC-WUR `a826251b` production build, D19 dam
files, non-renewable withdrawal, D03 outputs, 16 ranks × 8 threads). Runs
`runs/soil-comparison-version-{a,b,c}/ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020`, with
their run checks under `qc/runs/soil-comparison-version-{a,b,c}/<run-id>/` (water balance, GRDC stations). The years
2011-2015 settle the cold start (the smoothed layer-2 storage starts from `init_moist` at the version-a ratio); the
maps and the station comparison use 2016-2020, the series the whole period.

**Inputs** (paths relative to the workdir):

- `parameters/production/vic-global-5arcmin-version-a/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`
  and `parameters/candidates/vic-global-5arcmin-version-{b,c}/bundle/...` (the image-driver files), the domain file;
- the monthly output of the runs (`OUT_SOIL_MOIST`, `OUT_BASEFLOW`, `OUT_RUNOFF`, `OUT_EVAP`, `OUT_DISCHARGE`,
  `OUT_WATER_ERROR`) and the run checks (`reports/check.json`, `reports/grdc_stations.csv`).

**Outputs.** `workdir/analysis/soil-comparison/{tables,figures,logs}/` and the report `workdir/analysis/soil-comparison/report.html`
(`make_report.py`: method, QC numbers, tables and figures in one page, figures embedded).

**Method** (`soil_comparison.py`, one Slurm job per step, `--submit`; `--versions a b c` selects the sets, version-a
is the reference; the tables hold one row or column per set, the figures one file per set):

1. `fields`: area-weighted global and regional means of the seven changed variables and of the layer-2 root fraction
   of the grassland class in both files, the share of cells that changed and the size of the change; difference maps
   of `depth[2]` and `Ds` for West Siberia (58-66 N, 78-90 E) and the Alps (42-50 N, 2-14 E).
2. `runs`: global area-weighted monthly series of the layer-2 soil moisture, baseflow, surface runoff, evaporation and
   the baseflow share of total runoff for both runs and their difference; annual means per region and run
   (`annual_regions.csv`, `annual_global.csv`); maps of the 2016-2020 mean of the layer-2 soil moisture, baseflow and
   baseflow share (version-a, version-b, difference) for the globe and the two regions; the GRDC station tables of the
   two run checks joined (bias and seasonal correlation per station, stations improved and worsened); the water-balance
   error counts of the two runs.
3. `make_report.py` (login node, seconds): the report `report.html` from the QC records of the candidate, the run checks and
   the tables of steps 1 and 2, with the figures embedded.

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/soil-comparison/soil_comparison.py --step fields --versions a b c --submit
python3 analysis/soil-comparison/soil_comparison.py --step runs --versions a b c --submit   # after the run checks
python3 analysis/soil-comparison/make_report.py
```

Jobs: `fields` 43553379 (2026-11-03); `runs` 43586550 (2026-11-04; the first attempt 43585332 wrote every table and figure but
failed on a numpy integer in `run_checks.json`, fixed). Run checks used: 43569306 (a) and 43569307 (b), both passed (the first
pair 43551799/43553342 passed with the same numbers but was recorded under `scratch/run-check/uncommitted/` because this
analysis directory was still uncommitted when they ran). Three sets (2026-11-05): `fields` 43610880 (31 s), `runs`
43617981 (11 min, 22 GB); run check of version-c 43610874 passed (the first check 43602435 passed with the same numbers
but was recorded under `scratch/run-check/uncommitted/` for the same reason). `make_report.py` builds part II of the
report from the same tables when version-c is in them.

**Conclusion** (2026-11-04). The smoothing does what it was designed to do and nothing else; version-b can replace version-a.

- Parameter fields: the area-weighted global means of the five calibration fields change by less than 0.05 %; every cell stays
  within the range of its four blocks; the largest jump between neighbouring cells falls 24-fold (depth[2] 3.3 m → 0.14 m per
  cell); `depth[2]` changes on 15 % of the cells (those within 2 degrees of a depth edge), the baseflow parameters on 44–78 %.
- Runs (2011–2020, both run checks passed with identical water-balance statistics, p99 |error| 0.0022 mm/month, no cell-month
  above 1 mm): global total runoff −0.08 %, evapotranspiration +0.06 %, layer-2 storage −0.09 %; the partition shifts a little
  towards baseflow (+0.8 %) from surface runoff (−1.2 %), with a seasonal cycle of the difference (largest in the northern
  spring). The regional means of the Alps (depth unchanged, baseflow parameters smoothed) do not change to four digits: in the
  long-term mean the baseflow parameters set the storage, not the flux.
- Maps (2016–2020 means): the staircase of the layer-2 storage and of the baseflow share along the 2-degree block edges is gone;
  the differences are paired bands of up to ±300 mm (storage) and ±30 mm/yr (baseflow) on the two sides of each former edge
  (West Siberia), nothing between the edges.
- GRDC (976 stations, climatology 2012–2020 against 2001–2024): median sim/obs 1.355 → 1.345, median |ln(sim/obs)| 0.378 → 0.373,
  514 stations improved against 462 worsened, median seasonal correlation 0.832 → 0.833; the ten largest rivers change by at most
  0.2 %; the largest changes (up to −20 %, mostly towards the observations) are at prairie and boreal-plain stations in Canada.
- Water use: withdrawals follow the demand forcing; irrigation withdrawal −0.4 % with a small shift between sources (rivers
  −2.3 %, renewable groundwater −7 % of a small amount, non-renewable +0.5 %); municipal and manufacturing unchanged.

**Version-c** (2026-11-05, part II of the report). The MPR soil is another soil, not a repair of version-a: layer 2 is 2.5
times deeper in the global mean (1.85 → 4.54 m, the 5 m cap over most of the land), wilting and critical points are
halved, Ksat is 40 % higher, c = 2 and Ds = Dsmax everywhere; every compared field changes on every active cell.

- Runs (check passed, same water-balance statistics): evapotranspiration +9 % (+52 mm/yr), total runoff −23 % (baseflow
  −24 %, surface runoff −22 % over 2011–2020; −14 % and −19 % over 2016–2020); layer-2 storage 500 → 900 mm and still
  rising in 2020, so ten years from a cold start do not settle the 5 m soil everywhere. West Siberia: storage three times
  that of version-a; the Alps: storage +66 %, runoff −18 %.
- GRDC: the median overestimation of version-a disappears (sim/obs 1.355 → 0.981; 595 stations closer, 381 further) by
  lowering the discharge at 970 of 976 stations (−36 % at the median); the spread does not shrink (median |ln(sim/obs)|
  0.378 → 0.374), the 100 stations version-a underestimated get worse (0.66 → 0.39), the large rivers are now
  underestimated (Amazon at Óbidos 0.97 → 0.82, Mississippi 0.89 → 0.58, Yenisey 1.18 → 0.85). The seasonal
  correlation has two faces: at the median station it worsens (0.832 → 0.808; 358 stations worse by more than 0.05,
  249 better; 94 of the 121 stations above 0.95 in version-a lose) because the deep layer damps the snowmelt peaks
  of the northern rivers (Yenisey 0.98 → 0.77, Lena 0.93 → 0.79, Mississippi 0.83 → 0.55); weighted by the observed
  discharge it improves (0.790 → 0.838) because the large tropical rivers gain in shape and volume (Amazon at Óbidos
  r 0.74 → 0.90, Tocantins 0.67 → 0.90, Paraná ratio 1.62 → 1.10, São Francisco 1.82 → 0.98).
- Water use: irrigation withdrawal −34 % (the critical point halved, so the crops are irrigated later and less);
  renewable groundwater −73 %, non-renewable withdrawal −49 %; municipal and manufacturing unchanged.

Recommendation (unchanged): promote `vic-global-5arcmin-version-b` (`submit_parameter_promotion.py`, then `status:
production` in the manifest) and set `parameter_set.id: vic-global-5arcmin-version-b` in
`configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`. Version-c cannot be judged from one 10-year run against
version-a: its global water terms would have to be compared with independent estimates and its layer-2 depth and baseflow
parameters are uncalibrated stage-2 settings of the MPR candidate (source restricted, `not_authorized_for_global_production`);
it stays a candidate for a calibration or evaluation task of its own.

**Decision** (user, 2026-11-05): promote version-b; version-c is not promoted. The user records that the depth of soil
layer 2 is a sensitive control of the soil water storage and hence of the discharge (version-c: 1.85 → 4.54 m in the
global mean moved the total runoff by −23 % and the layer-2 storage by +72 %) and is a parameter for a later
fine-tuning task, not settled by this comparison.
