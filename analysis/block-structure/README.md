# Block structure in the VIC-WUR inputs and outputs (task Z follow-up)

**Question.** The outputs of the comparison runs of task Z still show block shapes after the 2-degree calibration
blocks of the soil were removed (version-b). Which parameter fields and which forcing fields are piecewise constant on
a coarser grid (2-degree calibration blocks, 1-degree, 0.5-degree ISIMIP cells, 0.25-degree), which run outputs inherit
that structure, and what would have to change to remove it?

**Classification.** Analysis (user, 2026-11-04): the product is a table, figures and a reading that attribute the
block shapes to their sources; no workflow stage reads it. The screening was first run from `scratch/soil-smoothing/
block-screen/` (jobs 43600516 and 43600523, 2026-11-04) and is kept here as the analysis task with the same method.

**Status.** `open`: the job from the committed code and the report are pending; the preliminary findings of the scratch
run are listed below.

**Inputs** (read only; paths relative to `$ISIMIP4B_WORKDIR`):

- `parameters/production/vic-global-5arcmin-version-a/`: domain file, image-driver file (the five calibration fields
  `depth`, `Ds`, `Dsmax`, `Ws`, `c` and `max_moist`, `init_moist`);
- `parameters/candidates/vic-global-5arcmin-version-b/`: image-driver file (every variable) and irrigation file
  (`groundwater_fraction`, `irrigation_efficiency`);
- the MPR soil candidate of vic_parameter (the soil of version-c), the file recorded as `soil_source` in
  `parameters/candidates/vic-global-5arcmin-version-c/soil/provenance.yaml` (outside the workdir; `--mpr-file` overrides);
- forcing of 2015: `forcing/climate/ec-earth3-esm-1-1/esm-hist/<var>/` (seven variables, annual mean),
  `forcing/landuse/histsoc/coverage_histsoc_2015.nc`, `forcing/water_use/histsoc/*_histsoc_2015.nc`;
- the monthly output of the comparison runs `runs/soil-comparison-version-<v>/ec-earth3-esm-1-1_historical_histsoc_default_historical__years-2011-2020/output/`
  (`--runs b` by default; `--runs b c` once the version-c run has finished).

**Outputs.** `workdir/analysis/block-structure/`: `tables/block_screen.csv` (one row per field slice: mean absolute
difference between neighbouring active cells per line class, the ratios to the interior, the share on lines of 0.5
degree or coarser, the verbal signal), `tables/mpr_vs_a.csv` (the MPR file against version-a field by field),
`tables/mpr_depth_percentiles.json`, `tables/summary.json`, `figures/<group>_<field>[_<slice>].png` (two zoom regions,
Europe 40-56 N 5 W-30 E and Central Asia 35-50 N 60-95 E), `logs/screen_<job>/`, and `report.html` (`make_report.py`).

**Method** (`block_screen.py`, one Slurm job, `--submit`; 1 core, 96 GB, about 15 minutes). For every 2-D field (and
every layer, class, snow band or month mean of a 3-D or 4-D field) the absolute difference between horizontally and
vertically adjacent active cells is averaged separately for cell pairs that straddle a 2-degree calibration-block
edge (latitude edges on even degrees, longitude edges on even degrees east of 0 and odd degrees west of 0), a 1-degree
line, a 0.5-degree line, a 0.25-degree line, and for every other pair. The ratio of a line class to the interior mean
is the block signal: about 1 for a field without that structure, large for a field that is piecewise constant on that
grid. The verbal signal is a fixed rule on the ratios (`2deg-blocks` when the 2-degree ratio exceeds 2 and 1.5 times
the 1-degree ratio; `0.5deg-blocks` when the 0.5-degree ratio exceeds 2 with a 0.25-degree ratio below 1.5;
`0.5deg-weak` for 1.3 and 1.2; `1deg-lines` when the 1-degree ratio exceeds 2 and 1.5 times the 0.5-degree ratio).

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/block-structure/block_screen.py --runs b --submit
python3 analysis/block-structure/make_report.py          # login node, seconds
```

**Jobs.** Scratch screening 43600516 (failed on a wrong file for `groundwater_fraction`) and 43600523 (complete,
15 minutes, 515 slices). The job from the committed code: pending.

**Preliminary findings** (scratch run of 2026-11-04; to be confirmed by the job from the committed code).

- Version-a: the five calibration fields have 2-degree ratios of 450-670. Version-b: every ratio near 1; of the 401
  slices of its image-driver file, 392 show no block structure; the exceptions are bookkeeping flags VIC does not read
  and slices that are almost everywhere zero.
- Forcing: `prec` is pure 0.5-degree blocks (the ISIMIP value replicated to the 36 cells; method 1.1 of
  `04_forcing/climate`); `tair` and `lwdown` replication plus the elevation correction (ratio 1.3-1.4, blocks on flat
  terrain); `psurf`, `vp`, `swdown`, `wind` none. Water-use consumption and groundwater fractions: pure 0.5-degree
  blocks (WaterGAP); the demands none. Land-use coverage: none.
- Irrigation file: `groundwater_fraction` pure 0.5-degree blocks (WaterGAP); `irrigation_efficiency` one value per
  country (edges along borders, not grid blocks).
- MPR candidate: no block structure in any soil field; `c` constant 2, `Ds` equal to `Dsmax`; layer-2 depth 5 m
  (the cap) over most of the land.
- Run outputs (version-b, 2011-2020 mean): the 2-, 1- and 0.5-degree lines carry the same ratio and the 0.25-degree
  lines none, so the structure is the 0.5-degree ISIMIP grid; strongest in runoff, baseflow and recharge (about 2.1),
  weaker in evaporation, soil moisture and snow (1.3-1.8), none in LAI and river storage.

**Conclusion.** Pending the job from the committed code. Reading so far: the 2-degree blocks are gone with version-b;
what remains is the 0.5-degree resolution of the protocol input (precipitation first of all), which disappears in the
0.5-degree ISIMIP products (D07) by construction; removing it from the 5-arcmin fields would be a change of the
forcing downscaling method (an interpolation of precipitation is not conservative), not of the parameters.
