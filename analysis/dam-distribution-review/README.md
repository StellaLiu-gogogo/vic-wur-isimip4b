# dam-distribution-review

**Question.** Supporting open decision D19 (dams and initial states per experiment): where are the dams of the
model's dam parameter file, when were they built, which of them would operate in each DHF scenario
(`1850soc`, `2021soc`, `histsoc`), what are the dams with unknown construction year (year 0), how does the
file compare with the ISIMIP4b reservoirs-dams data (histsoc, 2026-08 version), and what do the ISIMIP4b
future hydropower dams (`ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`) look like.

**Classification.** Analysis; proposed by the agent and confirmed by the user on 2026-10-09. Reason: the
products are figures and tables used to discuss D19; no workflow stage reads them.

**Status.** `open`.

**Inputs** (read-only; paths relative to `$ISIMIP4B_WORKDIR` unless absolute).

- `parameters/candidates/vic-global-5arcmin-version-a/dams/vic_global_5min_dam_parameters_t3-extended-merged.nc`
  (role `dams` of the candidate parameter set; `id`, `id_map`, `type`, `year`, `capacity`).
- The GDW tier tables the dam file was built from, in the legacy `vic_parameter` area (not yet migrated, D15):
  `/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/candidates/dams/dam_parameter_candidate_v1/T3_extended/{global,local}Dams.csv`
  (unmerged records with GDW source `ORIG_SRC`, `GRAND_ID`, names, country). A model dam takes the attributes
  of the largest record of the same type in its 5′ cell.
- The corrected GDW database the tiers are selected from (legacy area):
  `/lustre/nobackup/WUR/ESG/liu297/vic_global/00pre_analysis/downscaling5min/08HumanImpact/01Dam/Data/GDW_reservoirs_corrected_5min.csv`
  (which records the T3_extended rules leave out: capacity < 20 hm3, quality worse than 4, DOR < 10 %).
- `raw/ISIMIP4b/InputData/socioeconomic/reservoirs_dams/histsoc/reservoirs-dams_1850_2021.xlsx` (identical to the
  `2021soc` file) and the two SSP csv files of the same directory.
- Natural Earth 1:50m `admin_0_countries` from the cartopy data cache (continent of each dam).

Matching of ISIMIP4b dams to model dams: by GRanD ID (`ID` = GDW `GRAND_ID`), then by the nearest GDW dam
location within 0.1° whose capacity is within a factor 2.

- GDW v1.0 shapefile attribute tables and point geometry (legacy area, not yet in `raw/`, D15):
  `/lustre/nobackup/WUR/ESG/liu297/vic_global/00pre_analysis/downscaling5min/08HumanImpact/01Dam/Data/GDW_v1_0_shp/`
  `GDW_reservoirs_v1_0` (35 295 records) and `GDW_barriers_v1_0` (41 145 records, all dams including those without a
  mapped reservoir; `LAT_DAM`/`LONG_DAM` are 0 in most barrier records, the location is taken from the point geometry;
  capacity -99 means missing). Used by `compare_gdw_isimip.py`.

Matching in `compare_gdw_isimip.py` (one to one, each GDW record used at most once): GRanD ID for ISIMIP dams whose
`SOURCE` is empty (pairs farther than 10 km apart or with a capacity ratio outside [0.5, 2] kept as
`grand_id_suspect`), then location within 2, 5 and 10 km in turn with a capacity ratio in [0.5, 2], first against the
corrected table, then against the GDW records outside it; name similarity within 50 km for the rest, listed as hints
and not counted. Candidate GDW rules: quality 5, DOR missing (-99), Offstream, capacity < 20 hm3, DOR < 10 % (DOR
known), the current T3_extended rule, proposed A (quality 5, DOR missing, Offstream) and proposed B (A + capacity
< 20 hm3). The cell count of proposed A places each record by `MODEL_LAT_DD`/`MODEL_LONG_DD` on the grid of the model
dam file; it only counts, the snapping itself is a later workflow task.

**Code.** `review_dams.py` (figures and tables of the model dam file, ISIMIP4b and the DOR rule) and
`compare_gdw_isimip.py` (dam-by-dam comparison of the full GDW database with ISIMIP4b histsoc, requested
2026-10-09 for the dam-list question of D19). It always runs on a compute node: `--submit` renders the Slurm job and
keeps its record under `workdir/analysis/dam-distribution-review/logs/review_<slurm-job-id>/`.

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python analysis/dam-distribution-review/review_dams.py --submit          # job record logs/review_<job-id>/
python analysis/dam-distribution-review/compare_gdw_isimip.py --submit   # job record logs/gdw_<job-id>/
```

**Outputs.** `workdir/analysis/dam-distribution-review/`:

- `figures/`:
  - `map_model_dams.png`: global and local dams, marker area by capacity, colour by construction period;
  - `cumulative_capacity.png`: number and capacity of dams by construction year, model file and ISIMIP4b;
  - `scenario_dams.png`: dams operating in `1850soc` and in `2021soc` (proposal for D19);
  - `unknown_year_dams.png`: dams with year 0 by GDW source, capacity distribution, the largest ones;
  - `model_vs_isimip_map.png`, `model_vs_isimip_scatter.png`: dams in both datasets or in one only; year and
    capacity of matched dams;
  - `ssp_future_dams.png`: ISIMIP4b future hydropower dams per SSP;
  - `capacity_by_continent.png`;
  - `gdw_excluded_by_dor.png`: GDW reservoirs left out of the model file by the rule DOR >= 10 %.
  - `gdw_isimip_match_map.png`: ISIMIP4b histsoc dams by match method in GDW, the unmatched ones named;
  - `gdw_isimip_distance.png`: distance and capacity ratio of the matched pairs;
  - `gdw_rule_effects.png`: records and capacity each candidate rule removes, matched to ISIMIP4b or not;
  - `gdw_offstream_dor_missing_map.png`: Offstream records and records with DOR missing;
  - `gdw_isimip_year_scatter.png`: construction year of matched dams in both datasets;
  - `gdw_cell_multiplicity_map.png`: 5' cells holding more than one dam under proposed A.
- `tables/`: `dams_by_period.csv`, `scenario_summary.csv`, `unknown_year_by_source.csv`,
  `unknown_year_largest.csv`, `model_isimip_match.csv`, `model_isimip_year_differences.csv`,
  `isimip_not_in_model_largest.csv`, `ssp_future_dams.csv`, `ssp_future_dams_largest.csv`, `capacity_by_continent.csv`,
  `gdw_tier_exclusions.csv`, `gdw_excluded_by_dor_largest.csv`; from `compare_gdw_isimip.py`: `gdw_layers.csv`,
  `gdw_reservoirs_not_in_corrected.csv`, `gdw_isimip_match.csv` (one row per ISIMIP4b dam),
  `gdw_isimip_match_summary.csv`, `gdw_isimip_suspect_reasons.csv`, `gdw_isimip_unmatched_largest.csv`,
  `gdw_isimip_name_hints.csv`, `gdw_rule_effects.csv`, `gdw_offstream_largest.csv`, `gdw_dor_missing_largest.csv`,
  `gdw_isimip_year_comparison.csv`, `gdw_cell_multiplicity.csv`, `gdw_cell_multiple_dams.csv`.
- `logs/review_<slurm-job-id>/`, `logs/gdw_<slurm-job-id>/`: job records.

**Conclusion.** Pending; to be recorded in the context of D19 in `docs/decisions/open-decisions.md`. Recorded
there on 2026-10-09: the GDW rule DOR >= 10 % leaves large run-of-river reservoirs out of the dam file
(1 373 dams, 528 km3), added to D19 by the user.
