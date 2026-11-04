# Soil comparison: version-a against version-b (task Z)

**Question.** Does smoothing the five 2-degree calibration fields of the soil (`depth[2]`, `Ds`, `Dsmax`, `Ws`, `c`;
parameter set `vic-global-5arcmin-version-b`, `workflow/03_parameters/soil/`) remove the 2-degree steps from the
simulated layer-2 soil moisture, baseflow and discharge without changing the global water balance or the discharge
at the GRDC stations for the worse, so that version-b can replace version-a in the production campaign?

**Classification.** Analysis (user, 2026-11-02): the figures and tables are the basis of the decision whether to
promote version-b and change `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`; no workflow stage reads them.

**Status.** done 2026-11-04 (analysis complete, conclusion below); the promotion of version-b is the user's decision.

**Runs.** Campaigns `soil-comparison-version-a` and `soil-comparison-version-b` (`configs/campaigns/`, non-production,
identical except for the parameter set): the historical `histsoc` segment of `h_ssp3hsoc-noadapt_default`, 2011-2020,
cold start, one chunk, with the settings of the production campaign (VIC-WUR `a826251b` production build, D19 dam
files, non-renewable withdrawal, D03 outputs, 16 ranks × 8 threads). Runs
`runs/soil-comparison-version-{a,b}/ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020`, with
their run checks under `qc/runs/soil-comparison-version-{a,b}/<run-id>/` (water balance, GRDC stations). The years
2011-2015 settle the cold start (the smoothed layer-2 storage starts from `init_moist` at the version-a ratio); the
maps and the station comparison use 2016-2020, the series the whole period.

**Inputs** (paths relative to the workdir):

- `parameters/production/vic-global-5arcmin-version-a/bundle/vic_global_5min_16class_landuse-union_root-b-zeng2001.nc`
  and `parameters/candidates/vic-global-5arcmin-version-b/bundle/...` (the two image-driver files), the domain file;
- the monthly output of the two runs (`OUT_SOIL_MOIST`, `OUT_BASEFLOW`, `OUT_RUNOFF`, `OUT_EVAP`, `OUT_DISCHARGE`,
  `OUT_WATER_ERROR`) and the run checks (`reports/check.json`, `reports/grdc_stations.csv`).

**Outputs.** `workdir/analysis/soil-comparison/{tables,figures,logs}/` and the report `workdir/analysis/soil-comparison/report.html`
(`make_report.py`: method, QC numbers, tables and figures in one page, figures embedded).

**Method** (`soil_comparison.py`, one Slurm job per step, `--submit`):

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
python3 analysis/soil-comparison/soil_comparison.py --step fields --submit
python3 analysis/soil-comparison/soil_comparison.py --step runs --submit     # after both run checks have finished
```

Jobs: `fields` 43553379 (2026-11-03); `runs` 43586550 (2026-11-04; the first attempt 43585332 wrote every table and figure but
failed on a numpy integer in `run_checks.json`, fixed). Run checks used: 43569306 (a) and 43569307 (b), both passed (the first
pair 43551799/43553342 passed with the same numbers but was recorded under `scratch/run-check/uncommitted/` because this
analysis directory was still uncommitted when they ran).

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

Recommendation: promote `vic-global-5arcmin-version-b` (`submit_parameter_promotion.py`, then `status: production` in the
manifest) and set `parameter_set.id: vic-global-5arcmin-version-b` in `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`.
