# Block structure in the VIC-WUR inputs and outputs (task Z follow-up)

**Question.** The outputs of the comparison runs of task Z still show block shapes after the 2-degree calibration
blocks of the soil were removed (version-b). Which parameter fields and which forcing fields are piecewise constant on
a coarser grid (2-degree calibration blocks, 1-degree, 0.5-degree ISIMIP cells, 0.25-degree), which run outputs inherit
that structure, and what would have to change to remove it?

**Classification.** Analysis (user, 2026-11-04): the product is a table, figures and a reading that attribute the
block shapes to their sources; no workflow stage reads it. The screening was first run from `scratch/soil-smoothing/
block-screen/` (jobs 43600516 and 43600523, 2026-11-04) and is kept here as the analysis task with the same method.

**Status.** `closed` (2026-11-04): job 43605761 from the committed code (commit 5871daf, clean tree) reproduced the
tables of the scratch run value for value; `report.html` built from its tables and figures.

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

**Method** (`block_screen.py`, one Slurm job, `--submit`; 1 core, 96 GB requested, 28 GB used, 23 minutes). For every 2-D field (and
every layer, class, snow band or month mean of a 3-D or 4-D field) the absolute difference between horizontally and
vertically adjacent active cells is averaged separately for cell pairs that straddle a 2-degree calibration-block
edge (latitude edges on even degrees, longitude edges on even degrees east of 0 and odd degrees west of 0), a 1-degree
line, a 0.5-degree line, a 0.25-degree line, and for every other pair. The ratio of a line class to the interior mean
is the block signal: about 1 for a field without that structure, large for a field that is piecewise constant on that
grid. The verbal signal is a fixed rule on the ratios (`2deg-blocks` when the 2-degree ratio exceeds 2 and 1.5 times
the 1-degree ratio; `0.5deg-blocks` when the 0.5-degree ratio exceeds 2 with a 0.25-degree ratio below 1.5;
`0.5deg-weak` for 1.3 and 1.2; `1deg-lines` when the 1-degree ratio exceeds 2 and 1.5 times the 0.5-degree ratio).
A field that is exactly piecewise constant on the 0.5-degree grid has no interior variation at all: its ratios are
undefined, its verbal signal is `none`, and `share_05 = 1` identifies it (`prec`, the consumption and groundwater
fractions of the water-use forcing).

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/block-structure/block_screen.py --runs b --submit
python3 analysis/block-structure/make_report.py          # login node, seconds
```

**Jobs.** Scratch screening 43600516 (failed on a wrong file for `groundwater_fraction`) and 43600523 (complete,
15 minutes, 515 slices). From the committed code: 43605761 (commit 5871daf, clean tree, node235, 2026-11-04
18:10-18:33 UTC, 515 slices, 23 minutes, 28 GB peak; `logs/screen_43605761/`): its `block_screen.csv` equals the
scratch table in every row and column, `mpr_vs_a.csv` and `mpr_depth_percentiles.json` equal the scratch files.

**Findings** (job 43605761; identical to the scratch run of 2026-11-04). Of the 515 slices: 204 constant; 279
labelled `none` (among them the fields that are pure 0.5-degree blocks, `share_05 = 1`: `prec` and the four
water-use fractions); 9 with 2-degree blocks (the five version-a calibration fields, `max_moist` and `init_moist`
of layer 2 derived from them, and the almost empty snow-band-4 slices of `AreaFract` and `Pfactor` in version-b);
10 with 0.5-degree blocks (runoff, baseflow, recharge and precipitation output of version-b; `groundwater_fraction`
and `irrigation_efficiency` of the irrigation file; four bookkeeping flags of version-b); 12 weak 0.5-degree
(`tair`, `lwdown`; evaporation, soil moisture, snow, canopy evaporation, transpiration and air temperature output);
1 with 1-degree lines (`backfill_level` of vegetation class 13, a bookkeeping field).

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

**Conclusion.** The 2-degree blocks of the version-a calibration fields are gone with version-b (every ratio near
1) and absent from the MPR soil; neither parameter set leaves a 2-degree signal in the run outputs. The block shapes
that remain in the outputs are the 0.5-degree ISIMIP grid, inherited from the forcing (precipitation replicated to
the 36 cells of each 0.5-degree cell, air temperature and longwave radiation to a lesser degree because of the
elevation correction) and, for the irrigated and water-use fields, from the 0.5-degree WaterGAP products
(`groundwater_fraction`, consumption and groundwater fractions of the water-use forcing). This structure disappears
in the 0.5-degree ISIMIP products (D07) by construction. Removing it from the 5-arcmin fields would be a change of
the forcing downscaling method (an interpolation of precipitation is not conservative and is not what the protocol
prescribes), not of the parameter set; no action on the parameters follows from this task. Rerun with `--runs b c`
if the version-c outputs are to be screened as well.
