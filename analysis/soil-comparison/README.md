# Soil comparison: version-a against version-b (task Z)

**Question.** Does smoothing the five 2-degree calibration fields of the soil (`depth[2]`, `Ds`, `Dsmax`, `Ws`, `c`;
parameter set `vic-global-5arcmin-version-b`, `workflow/03_parameters/soil/`) remove the 2-degree steps from the
simulated layer-2 soil moisture, baseflow and discharge without changing the global water balance or the discharge
at the GRDC stations for the worse, so that version-b can replace version-a in the production campaign?

**Classification.** Analysis (user, 2026-11-02): the figures and tables are the basis of the decision whether to
promote version-b and change `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`; no workflow stage reads them.

**Status.** open.

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

**Outputs.** `workdir/analysis/soil-comparison/{tables,figures,logs}/`.

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

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/soil-comparison/soil_comparison.py --step fields --submit
python3 analysis/soil-comparison/soil_comparison.py --step runs --submit     # after both run checks have finished
```

**Conclusion.** (open)
