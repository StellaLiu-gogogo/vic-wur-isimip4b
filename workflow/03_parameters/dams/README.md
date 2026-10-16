# 03 Parameters — dams

Builds the dam files of a parameter set, `parameters/<status>/<parameter-set>/dams/`, as decided in D19
(`docs/decisions/D19-dams-and-initial-states.md`): one dam list (the ISIMIP4b `histsoc` dams located with GDW
v1.0, plus the ISIMIP4b SSP future hydropower dams) and one VIC dam file (`DAMS_PARAMETERS`) per DHF scenario,
identical except for the construction year.

Classification: production workflow code (user, task L, 2026-10-11). The crosswalk and readers were promoted
from `compare_gdw_isimip.py` of the analysis task `dam-distribution-review`.

| File | Role |
|---|---|
| `build_dams.py` | producer: dam list, cells, service maps, the three dam files, tables, `provenance.yaml`; `--review` writes only the hand-review tables |
| `dam_sources.py` | readers (GDW barriers shapefile, ISIMIP4b workbook, SSP csv), ISIMIP4b-GDW crosswalk, purpose rule, SSP sites |
| `dam_grid.py` | routing topology, upstream area, snapping, one dam per cell, service maps, dam-file writer |
| `dam_decisions.yaml` | hand decisions with reasons: manual locations, records combined into one dam, overrides of the review rules |
| `verify_dams.py` | independent verification; `summary.json` and `reports/verify.json` under `qc/parameters/<status>/<set>/dams/`, sets `qc.status` |
| `dams.sbatch` | Slurm template: producer, then verifier |
| `submit_dams.py` | renders and submits the job, job record under `logs/03_parameters/<job-name>_<slurm-job-id>/` |

Tests: `tests/unit/test_dam_parameters.py`.

## Inputs

- `raw/ISIMIP4b/InputData/socioeconomic/reservoirs_dams/histsoc/reservoirs-dams_1850_2021.xlsx` (7 331 dams,
  identical to `2021soc`) and the `ssp1vlsoc-noadapt` and `ssp3hsoc-noadapt` csv files (md5 against
  `manifests/inputs/isimip4b-dkrz-2026-09-21/MD5SUMS`).
- `raw/external/global-dam-watch/1.0/GDW_v1_0_shp/GDW_barriers_v1_0.*` (md5 against
  `manifests/inputs/global-dam-watch.yaml`). The barriers layer holds every GDW record (each reservoirs-layer
  record is a barriers record with the same `GDW_ID`); its point geometry is the dam location on the river
  (`LAT_RIV`/`LONG_RIV`); `LAT_DAM`/`LONG_DAM` of the `.dbf` are 0 in most records and are not used.
- Domain and routing file of the parameter set (md5 against the parameter manifest); the routing gives the cell
  ids, the downstream cells and the cell areas.
- The monthly `OUT_DISCHARGE` of a completed natural run (irrigation, dams and water use off) for the years of
  `--discharge-years` (default 1992–2021, user 2026-10-11).

## Method (version 1.0)

1. **Dam list.** Every ISIMIP4b `histsoc` dam (D19). Crosswalk to GDW, one to one: manual entries of the
   decisions file; GRanD ID for GRanD-sourced records (empty `SOURCE`); then the nearest GDW record within 2 km
   whose capacity is within a factor 2. GRanD pairs more than 10 km apart or with a capacity ratio outside
   [0.5, 2] are decided by review rules (user, 2026-10-16) and listed with their evidence in `review_pairs.csv`;
   an entry under `reviews` in `dam_decisions.yaml` overrides the rules for one pair. The producer refuses to write
   the component while an ISIMIP dam is unmatched and has no manual location.
   - Capacity: **C1** a regulated natural lake (GDW `LAKE_CTRL` Yes or Enlarged) takes the GDW capacity, the volume
     the dam regulates (ISIMIP gives the whole lake); **C2** when the mean depth (capacity / surface area, GDW
     `AREA_SKM` else ISIMIP `R_Area_km2`) lies within 5–100 % of the dam height (GDW `DAM_HGT_M` else ISIMIP
     `D_Hght_m`) for one source only, that source; **C3** otherwise ISIMIP. In most flagged pairs GDW keeps the
     ISIMIP value as its reported capacity (`CAP_REP`) and chose another value (often the HydroLAKES maximum,
     `CAP_MAX`) as its best estimate.
   - Location: the fit of a point is the best max(ratio, 1/ratio) between the upstream area of the 3×3 cells
     around it and the catchment area of the same source. **L1** the GDW point fits within 1.5: GDW (newer; its
     point lies on the HydroSHEDS river); **L2** only the ISIMIP point fits: ISIMIP; **L3** neither fits: GDW. Records the decisions file combines (Fengman/Fengman_2, the two Rogun records)
   are one dam. SSP future dams: river-power dams (`SystemID` 2) with a lake volume; a site in both SSP tables is
   one dam (same volume, years kept per scenario); diversion-canal plants (`SystemID` 1) have no lake volume and
   are left out (user, 2026-10-11), each listed in `dam_sources_isimip4b.csv`.
2. **Point and catchment.** The GDW point, else ISIMIP `LAT_ORIG`/`LON_ORIG`. Catchment: GDW `CATCH_SKM`, else
   ISIMIP `CATCH_SKM_GranD`, else ISIMIP `CATCH_SKM_DDM30` (flagged in the dam list). SSP: `latitude`/`longitude`;
   the SSP tables give no catchment area (their column `DDM30/ISIMIP routing area [km2]` holds the WaterGAP
   `Arc_ID` of the 0.5° cell, all 2 855 ssp3 values match the WaterGAP Arc_ID table, checked 2026-10-16).
3. **Cell and type** (legacy `01CreateDamDatabase.py`, on the routing of the parameter set). Nearest cell (nearest
   active cell of its 3×3 neighbourhood when it is outside the domain). Catchment smaller than the cell: local dam,
   `inflow_fraction` = catchment / cell area. Otherwise global (`inflow_fraction` 1) in the cell of the 3×3
   neighbourhood whose upstream area is closest to the catchment, unless the ratio exceeds 1.5 (then the nearest
   cell). SSP future dams are global and go to the active cell of the nearest cell and its 3×3 neighbourhood with
   the largest upstream area (a river-power dam sits on the main river; user, 2026-10-16); that upstream area
   stands in for their catchment when they have to move. A historical dam with no active cell in reach is left out
   only when the decisions file lists it under `outside_domain` (Qorlortorsuaq, Greenland, D08; user 2026-10-16);
   otherwise the producer stops.
4. **One dam per cell** (VIC `39e21ff5` sizes the dam output for one dam per cell). Largest first, historical
   before future. A dam whose cell is taken moves to a free neighbouring cell on the same river (directly
   downstream or draining directly into the taken cell) whose upstream area still fits (ratio ≤ 1.5), a local dam to
   the nearest free neighbour; otherwise a historical dam is merged into the dam of the cell (capacities summed,
   year, type and inflow fraction of that larger dam) and a future dam is not placed (user, 2026-10-11).
5. **Capacity** ISIMIP `CAP_MCM` (hm³), GDW `CAP_MCM` where a review rule chooses it, or the decisions file;
   SSP: lake volume / 10⁶, kept as ISIMIP gives it (user, 2026-10-16). The dam list flags SSP future dams whose
   capacity exceeds 5 years of the mean discharge at their cell or whose mean depth (capacity / lake surface) lies
   outside 5–100 % of their dam height (`future_flag`, for D06); `years_of_mean_flow` is given for every dam.
6. **Purpose.** A global dam keeps its service map when ISIMIP `PURPOSE` or GDW (`USE_IRRI`, `USE_SUPP`,
   `MAIN_USE` Irrigation or Water supply) names irrigation or water supply, or when neither source names a purpose;
   a global dam with a known purpose without irrigation or water supply, and every SSP future dam, gets
   `Nservice = 0` and an empty service map (user, 2026-10-11; VIC accepts this, analysis `dam-nservice-test`).
   Local dams keep their service maps.
7. **Service maps** (vic_parameter `service.py`): from the dam cell downstream while mean discharge at the dam /
   mean discharge at the cell ≥ 0.1, stopping at an outlet, a revisited cell or 1 000 cells; fractions clipped to 1.
8. **Years per DHF scenario** (D19; 9999 = never, user 2026-10-11):

| File | `year` | Used by segments with soc scenario |
|---|---|---|
| `..._isimip4b_histsoc.nc` | ISIMIP `YEAR` (unknown years are 1850 in ISIMIP); SSP future dams 9999 | `histsoc` |
| `..._isimip4b_1850soc.nc` | 0 for `YEAR` ≤ 1850, 9999 otherwise | `1850soc` |
| `..._isimip4b_2021soc.nc` | 0 for every historical dam, 9999 for SSP future dams | `2021soc`, `2021soc-from-histsoc`, SSP units without `extrasoc` dams |

Files for `extrasoc` (SSP future dams following their construction year) wait for D06.

## Outputs

In `parameters/<status>/<set>/dams/` (the adopted T3_extended file stays for the smoke campaigns):
`vic_global_5min_dam_parameters_isimip4b_{histsoc,1850soc,2021soc}.nc`, `dam_list_isimip4b.csv` (one row per
`dam_class`), `dam_sources_isimip4b.csv` (every source record and what became of it), `review_pairs.csv`,
`mean_discharge_natural.nc`, `provenance.yaml` (these files only); QC under
`qc/parameters/<status>/<set>/dams/`.

## Running

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/03_parameters/dams/submit_dams.py --review                              # tables and review choices
python3 workflow/03_parameters/dams/submit_dams.py --discharge-run runs/<campaign>/<run-id> --scratch   # test
python3 workflow/03_parameters/dams/submit_dams.py --discharge-run runs/<campaign>/<run-id>             # component
```

`--review` and test runs write to `scratch/dam-parameters/`. Outside scratch the producer requires a clean
repository at the submitted commit, a natural discharge run, and a manual location for every unmatched dam; it
never overwrites its own files.

## Decisions

D19 (decided 2026-10-11) and the user's choices of 2026-10-11 recorded above. D01 is provisional: the dam files
follow the reader of VIC `39e21ff5`. D06 (`extrasoc`) is open.
