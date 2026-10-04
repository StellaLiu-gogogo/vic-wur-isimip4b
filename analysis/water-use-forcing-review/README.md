# water-use-forcing-review

**Question.** Task D2-review of D05: what do the five water-use forcing units
(`forcing/water_use/<soc>/`, method 1.0) contain, and does anything in them look wrong? Specifically: global and
continental totals of withdrawal and consumption against the sources, with the difference matched to the
lost-demand ledger; 5′ maps of demand, consumption and groundwater fractions; the 2021/2022 join at 5′;
per-capita demand and the cells with demand but no population; how the 0.5° totals are spread inside the
parents; year-to-year changes at 5′ around the 2005 anomaly and the SSP join.

**Classification.** Analysis; proposed by the user and confirmed on 2026-10-04. Reason: the products are
figures, tables and a report; no workflow stage reads them.

**Status.** `closed` (user, 2026-10-04): the report answers the question; no change to the units is needed.

**Inputs** (read-only, paths relative to `$ISIMIP4B_WORKDIR`).

- `forcing/water_use/{histsoc,1850soc,2021soc,ssp1vlsoc-noadapt,ssp3hsoc-noadapt}/` (all `qc.status: passed`).
- `qc/forcing/water_use/<soc>/reports/lost_demand_ledger.csv` and `lost_parents_<year>.csv`.
- `raw/external/isimip3-water-abstraction/dkrz-2026-10-02/` (sources).
- `parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc` (mask, area).
- `raw/ISIMIP4b/InputData/socioeconomic/population/<soc>/` (5′ total population),
  `raw/ISIMIP4b/InputData/geo_conditions/countrymasks/countrymasks-fractional_30arcmin.nc`,
  `raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_water-global.nc`.

**Code.**

- `review_forcing.py` — the whole review in one script, one process per unit. It always runs on a compute
  node: `--submit` renders the Slurm job and keeps its record under
  `workdir/analysis/<task-id>/logs/review_<slurm-job-id>/`.
- Reused, not rewritten:
  - from `analysis/isimip3-water-abstraction-review/review_water_abstraction.py` (imported):
    - `file_table` and `read_file` (source readers);
    - `region_weights`, `REGIONS`, `CONTINENTS` and `regional` (continental totals with the same weights as D1);
    - `water_global_mask`;
    - `_plt` (plot style).
  - from `analysis/landuse-visualization/`: the region boxes `lu_vis.REGIONS` and `REGION_LABEL` for the insets,
    and `plot_maps.natural_earth_lines` and `LAND` for coastlines and the land colour.

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python analysis/water-use-forcing-review/review_forcing.py --submit
```

About 4 minutes with five processes (about 4 GB each).

**Outputs.** `workdir/analysis/water-use-forcing-review/`:

- `report.md` — the review (written by hand from the tables and figures).
- `tables/`:
  - `totals_by_region.csv` (written, source and lost volumes per unit, sector, quantity, year and region, with
    the residual and the ledger value);
  - `balance_summary.csv`, `balance_by_region.csv`;
  - `per_capita_by_continent.csv`, `even_split_cells.csv`;
  - `within_parent_distribution.csv`, `year_step_cell_changes.csv`;
  - `country_join_2021_2022.csv`.
- `figures/` — 25 PNG figures:
  - totals per sector and quantity, 1850–2100;
  - maps per unit and sector (histsoc 2021, futures 2100);
  - join ratios at 5′;
  - per-capita maps with the even-split cells;
  - within-parent distributions;
  - the 2005 anomaly at 5′;
  - year-to-year cell changes.

**Conclusion.** The units balance exactly against the sources and the lost-demand ledger, and nothing in them
looks wrong. The features that stand out (country-shaped steps at the 2021/2022 join, the 2005 industrial
redistribution, 0.5° blocks in the fractions, per-capita demand and even-split parents) are properties of the
sources or of the method. 2021soc equals histsoc 2021 in every year. Details:
`workdir/analysis/water-use-forcing-review/report.md`; the maintained record of the method is
`workflow/04_forcing/water_use/README.md` and D05.
