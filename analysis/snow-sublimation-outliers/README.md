# snow-sublimation-outliers

**Question.** The natural run 1850–2021 (task Q, campaign `natural-run`) has, in 6 of its 172 years, one cell in one
month with an absurd monthly `OUT_EVAP` (7 000 mm to 8.7e16 mm), an equally absurd `OUT_ENERGY_ERROR` and an
`OUT_WATER_ERROR` of about minus the daily value, while precipitation, runoff, baseflow, discharge, snow water
equivalent and soil moisture of the same cell-month are normal. Why does VIC-WUR `39e21ff5` write these values, which
variables do they affect, and which cell-months must be masked?

**Classification.** Analysis (task T); proposed by the agent and confirmed by the user on 2026-10-30. Reason: the
product is a conclusion and a mask rule for a decision. No workflow stage reads it. The masking of production output
will be implemented by workflow code (`06_postprocessing`) later.

**Decision taken before the analysis (user, 2026-10-30).** The outliers are masked (set to missing) in the affected
cell-months. The model is not changed.

**Status.** `closed` (2026-10-30): the question is answered; masking in workflow code is a later task.

**Contract exception (as in `dam-nservice-test`).** The VIC test run of this analysis is not a campaign run. It is
kept under `workdir/analysis/snow-sublimation-outliers/runs/jan1990/` (`config/`, `logs/`, `output/`,
`run_record.yaml`), not under `runs/<campaign-id>/`. Its VIC file is derived from the rendered file of chunk 1990–2009
of the natural run. Its Slurm job is kept as a job record in `logs/run-jan1990_<slurm-job-id>/`. No end state is
written.

**Inputs** (read only; paths relative to `$ISIMIP4B_WORKDIR`).

- Natural run: `runs/natural-run/ec-earth3-esm-1-1_historical_histsoc_default_historical__natural1850-2021/`
  - monthly output of every chunk;
  - the configuration and forcing view of chunk 1990–2009;
  - the end state of chunk 1970–1989, `chunks/1970-1989/states/state.19900101_00000.nc`, whose sha256 is recorded
    in the run manifest and checked by the test job.
- Build: `builds/vic/39e21ff5015d01d9bc20407a8f50006831417aff/`.
- VIC-WUR source at `39e21ff5`: `scratch/vic-build/39e21ff5015d01d9bc20407a8f50006831417aff/`.

**Steps** (`sublimation_outliers.py`; every computation on a compute node).

| Step | Content |
|---|---|
| `render-run`, `submit-run` | test run `jan1990`: January 1990 again from the same initial state, with daily snow and energy-balance diagnostics |
| `check --submit` | daily diagnostics of the test run at the outlier cell (50.042 N, 121.792 W) and every cell with a daily sublimation above 50 mm; reproduction of the monthly value of the natural run |
| `scan --submit` | every monthly file of the natural run: cell-months by monthly sublimation and by monthly mean \|`OUT_WATER_ERROR`\|, the mask list, and the largest unmasked values |

**Outputs.** `workdir/analysis/snow-sublimation-outliers/`:

- `runs/jan1990/`
- `tables/jan1990_cell_daily.csv`
- `tables/jan1990_cells_over_limit.csv`
- `tables/scan_by_year.csv`
- `tables/mask_cell_months.csv`
- `tables/largest_unmasked.csv`
- `logs/`

**Conclusion (2026-10-30).**

- **What goes wrong.** In a very small tile, a thin new snowpack makes the snow-surface temperature solution fail on
  a few model steps. The step's sublimation is then absurd, but it is neither consistent with the energy balance
  nor removed from the snowpack. Only the output is wrong: snow water equivalent, soil moisture, runoff, baseflow and
  discharge of the cell are normal, and the water-balance error equals the reported sublimation.
- **Evidence from the test run** (`jan1990`, job 43518404): it reproduces the natural run exactly (January
  sublimation at 50.042 N, 121.792 W: 6840.34 mm in both). The outlier is in two days only, 1990-01-19 (979 mm) and
  1990-01-20 (5863 mm). On those days the snow-temperature fallback flag `OUT_SNOWT_FBFLAG` changes from 0 to
  0.00502. That is the area fraction of the one tile without snow cover (cell snow cover 0.99498).
- **Sequence in that tile.** It was snow-free from 1 to 21 January, with the ground-temperature fallback
  (`OUT_SURFT_FBFLAG`) every day. On 19 January it got 0.34 mm of snowfall, the snow-temperature solution failed,
  and the sublimation exploded on 19 and 20 January. From 22 January the tile was snow-covered and the values were
  normal again.
- **Mechanism in the code** (`39e21ff5`). `TFALLBACK TRUE` makes VIC keep the previous temperature when
  `root_brent` fails to bracket the root. The VIC logs of the natural run list such failures with brackets of
  +650 to +760 degC and -490 to -380 degC, i.e. absurd tile temperatures. The exact line that lets the vapour flux
  escape the limits in `snow_melt.c` and `calc_surf_energy_bal.c` was not traced further, because the model is not
  changed (user decision above).
- **Frequency.** 7 cell-months in 172 years of the natural run (scan, job 43518405):
  - 1851-11 at 61.04 N, 144.13 W
  - 1881-01 at 27.71 N, 92.88 E
  - 1927-09 at 55.13 N, 132.54 E
  - 1974-03 at 41.63 N, 123.79 W
  - 1989-06 and 1989-07 at 34.71 S, 70.71 W
  - 1990-01 at 50.04 N, 121.79 W

  The natural-run spin-up also has 2 such cells, in its cold-started first year 1591. Smoke 2011-2020 has none.
- **Affected variables.** `OUT_SUB_SNOW`, `OUT_EVAP` (so ISIMIP `evap`), `OUT_WATER_ERROR` and `OUT_ENERGY_ERROR` of
  those cell-months, and every global or basin sum of these variables (global ET 1927: 4.3e12 km3). Not affected:
  precipitation, runoff, baseflow, discharge, snow water equivalent, soil moisture, the other evaporation components.
- **Mask rule.** Set `OUT_SUB_SNOW`, `OUT_EVAP`, `OUT_WATER_ERROR` and `OUT_ENERGY_ERROR` to missing in every
  cell-month whose monthly mean \|`OUT_WATER_ERROR`\| exceeds 1 mm. In daily output, do the same in every cell-day
  whose daily \|`OUT_WATER_ERROR`\| exceeds 1 mm.
  - The rule is clear-cut in the natural run. It selects exactly the 7 cell-months above (`tables/mask_cell_months.csv`).
  - The same 7 are the only cell-months with a monthly sublimation above 100 mm; the smallest of them has 604 mm.
  - The largest unmasked monthly sublimation is 67 mm (Puna, 22.5 S 67.0 W; `tables/largest_unmasked.csv`).
  - All other years have a largest \|`OUT_WATER_ERROR`\| below 0.95 mm.
  - In the daily test month, the normal days have \|`OUT_WATER_ERROR`\| up to 0.01 mm at the outlier cell, and only
    the two outlier days exceed 50 mm of daily sublimation anywhere on the globe.
- **Implementation.** The mask belongs to workflow code: `06_postprocessing` for ISIMIP `evap`, and a report of the
  masked cell-months by `05_simulation/monitor/check_run.py`. It is a later workflow task. For the natural run,
  `tables/mask_cell_months.csv` lists the cell-months to mask before `OUT_EVAP` or global ET is used.
