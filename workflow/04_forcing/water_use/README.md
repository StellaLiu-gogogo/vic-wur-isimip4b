# 04 Forcing — water use

Converts the ISIMIP3a/3b non-irrigation water-abstraction data (0.5°, m³ per year per cell) into the
yearly forcing of the VIC-WUR `wateruse` plugin on the 5′ domain, one forcing unit per soc scenario under
`workdir/forcing/water_use/<soc-scenario>/`. Decision D05 as amended on 2026-10-03
(`docs/decisions/D05-non-irrigation-water-use.md`); data description in
`workdir/analysis/isimip3-water-abstraction-review/report.md` (task D1).

**Classification.** Production workflow code (task D2): the units are read by `05_simulation`.

| File | Role |
|---|---|
| `downscale_water_use.py` | producer: reads the sources, splits each 0.5° volume over the active 5′ cells by ISIMIP4b population, converts to mm/day, writes `<sector>_<variable>_<soc>_<year>.nc`, `provenance.yaml`, and `qa_<year>.json`, `lost_parents_<year>.csv`, `lost_demand_ledger.csv` under `qc/forcing/water_use/<soc>/reports/` |
| `verify_forcing.py` | independent verification (own source reader, own re-aggregation by index arrays, own fraction recomputation); writes `verify_<year>.{json,png}` and `summary.json` under `qc/forcing/water_use/<soc>/` and sets `qc.status` in `provenance.yaml` (`passed` only when every year of the unit is present and passes) |
| `water_use_forcing.sbatch` | Slurm template: producer, then verifier, in one job |
| `submit_water_use_forcing.py` | renders the template, submits it on hold, writes the job record `logs/04_forcing/<job-name>_<slurm-job-id>/` (`job.sbatch`, `job.yaml`, scheduler output), releases the job |
| `continents.csv` | ISO3 → continent for the consumption-fraction fallback (same grouping as the D1 analysis) |

Tests: `tests/unit/test_water_use_forcing.py` (method on synthetic grids and driver rules) and
`tests/unit/test_water_use_port.py` (port test against `vic_parameter`, skipped unless
`ISIMIP4B_PORT_TEST=1`; on 2026-10-03 the split of the 2015 domestic demand with the sibling's population
proxy equalled the sibling's product exactly on all 2 188 551 active cells).

## Units

| Unit | Withdrawal | Consumption fraction | Years | Population (weights) |
|---|---|---|---|---|
| `histsoc` | ISIMIP3a histsoc, same year | ISIMIP3a wc/ww, same year | 1850–2021 | ISIMIP4b `histsoc` |
| `1850soc` | ISIMIP3b 1850soc (the 1901 field) | ISIMIP3b 1850soc wc/ww | 1850–2021 | ISIMIP4b `1850soc` |
| `2021soc` | ISIMIP3a histsoc 2021, constant | ISIMIP3a 2021 wc/ww | 2022–2100 | ISIMIP4b `2021soc` |
| `ssp1vlsoc-noadapt` | ISIMIP3b ssp126soc-noadapt modelavg, raw | ISIMIP3b 2015soc wc/ww | 2022–2100 | ISIMIP4b `ssp1vlsoc-noadapt` |
| `ssp3hsoc-noadapt` | ISIMIP3b ssp370soc-noadapt modelavg, raw | ISIMIP3b 2015soc wc/ww | 2022–2100 | ISIMIP4b `ssp3hsoc-noadapt` |

The year coverage equals that of the land-use units of the same soc scenario. The SSP series are not
rescaled or joined to 2021; the 2021/2022 step and the 2005 industrial anomaly are recorded in
`provenance.yaml` (`source_data_notes`).

## Files and plugin settings

Per year, two sectors × three variables, float32 on the domain grid (`_FillValue` 1e20 outside the domain
mask, 0 on active cells without demand), time `days since <year>-01-01 00:00:00`, value 0, calendar
`proleptic_gregorian`:

| Sector (plugin type) | ISIMIP source | Groundwater table |
|---|---|---|
| `municipal` (`MUN_*`) | domestic `domww`, `domwc` | `G_FRACTGW_DOM` |
| `manufacturing` (`MAN_*`) | industrial `indww`, `indwc` (manufacturing and energy together) | `G_FRACTGW_MAN` |

| Variable | Unit | Plugin type |
|---|---|---|
| `demand` | mm/day over the 5′ cell area | `*_DEMAND` |
| `consumption_fraction` | 1 | `*_CONSUMPTION` |
| `groundwater_fraction` | 1 (static, repeated every year) | `*_GROUNDWATER` |

VIC global parameter file (the plugin appends the year and `.nc` to the prefix,
`plugins/general/src/plugin_forcing_utils.c`):

```text
PLUGIN_FORCE_TYPE  MUN_DEMAND       demand                YEAR  <unit>/municipal_demand_<soc>_
PLUGIN_FORCE_TYPE  MUN_GROUNDWATER  groundwater_fraction  YEAR  <unit>/municipal_groundwater_fraction_<soc>_
PLUGIN_FORCE_TYPE  MUN_CONSUMPTION  consumption_fraction  YEAR  <unit>/municipal_consumption_fraction_<soc>_
PLUGIN_FORCE_TYPE  MAN_DEMAND       demand                YEAR  <unit>/manufacturing_demand_<soc>_
PLUGIN_FORCE_TYPE  MAN_GROUNDWATER  groundwater_fraction  YEAR  <unit>/manufacturing_groundwater_fraction_<soc>_
PLUGIN_FORCE_TYPE  MAN_CONSUMPTION  consumption_fraction  YEAR  <unit>/manufacturing_consumption_fraction_<soc>_
```

**Demand unit.** At the locked VIC commit the plugin stores the forcing value as the sector demand
(`plugins/wateruse/src/wu_force.c:110`), splits it into groundwater and surface demand without conversion
(`wu_run.c:101-108`), and meets it from available water in mm per model step over the cell area
(`wu_run_local.c:142-145`; `plugins/general/include/plugin_def.h:200` documents the demand as mm). With
`MODEL_STEPS_PER_DAY 1` the demand is mm per day:
`demand = V_child [m³/yr] / area_child [m²] × 1000 / days_in_year` (365 or 366). A configuration with more
than one model step per day would need the demand divided by the number of steps. The plugin also requires
the start-year file's first time to equal the climate forcing's first time and the calendar to equal VIC's
(`plugins/general/src/plugin_get_forcing_file.c`), hence 1 January 00:00 and `proleptic_gregorian`.

## Method (version 1.0)

1. **Sources** (report section 7): `years since 1901-1-1 03:00:00` decoded as `1901 + round(value)` with a
   contiguity check; SSP files `days since 1901-01-01` with 360 rows; the 280 parent rows (55.75°S–83.75°N)
   are selected by latitude and flipped to south-to-north; 0 (historical) and 1e20 (SSP) both mean no demand,
   SSP fill cells among parents with active VIC cells are counted; a negative value stops the producer.
2. **Volume split**: each 0.5° parent hands its volume to its 36 children in proportion to the ISIMIP4b 5′
   total population of the same soc scenario and year, restricted to active VIC cells; an even split over
   the active children where they have no population; parents without an active child are lost and listed per
   year (`lost_parents_<year>.csv`, `lost_demand_ledger.csv`). Conservation per parent holds to float64
   round-off (float32 in the files).
3. **Consumption fraction**: wc/ww of the source cell capped to [0, 1]; where ww = 0 the fraction of the
   cell's dominant continent for the same field (ISIMIP4b fractional country masks, `continents.csv`), the
   global fraction outside countries; replicated to the children.
4. **Groundwater fraction**: WaterGAP value of the 0.5° cell; parents with active VIC cells but no Arc_ID
   (2 531 parents, the VIC cells outside the ISIMIP/WaterGAP land mask) take the value of the nearest cell
   with one within 300 km (great-circle), else 0; on 2026-10-03 that was 2 477 filled (median 54 km) and 54
   remote-island parents set to 0, which carry no demand in the sources (the demand in such parents is
   recorded every year in `qa_<year>.json`). Replicated, static.

Bump `METHOD_VERSION` when results change for identical inputs.

Shared helpers (workdir, checksums, Git state, `provenance.yaml`, QC summary and verifier exit status, job records) come from `workflow/common/` (see its README); the verifier exits with 0 only for `passed` (1 failed, 3 warning, 4 not_checked), and a per-year report counts only for the data files and verifier version recorded in it.

## Running

One Slurm job per soc scenario; years run in parallel, one process per year (about 3 s and 1 GB per year;
the verifier about 6 s and 1.6 GB per year):

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=$PWD/workflow
python3 workflow/04_forcing/water_use/submit_water_use_forcing.py --scenario histsoc --years 1850-2021
python3 workflow/04_forcing/water_use/submit_water_use_forcing.py --scenario histsoc --years 2015 --scratch --scratch-label test
```

`--processes` (default 16) sets the parallel years; `--mem` defaults to 4 GB per process; `--dry-run`
prints the rendered job. A unit is generated as a whole: the producer refuses to write into an existing,
non-empty `forcing/water_use/<soc>/`; replacing an accepted unit needs the user's authorization. Files are
written under a temporary name and renamed when complete; `provenance.yaml` is written last. The input
files are checked against their manifests (md5) before anything is written. If the repository is not
clean, or with `--scratch`, everything goes to `scratch/water-use-forcing/<soc>/` (with `--scratch-label L`:
`scratch/water-use-forcing/runs/L/<soc>/`) and the verifier writes to `<that directory>/qc/`.

No cache is used: the parent-child relation is the 6 × 6 subdivision of the grid and the population sums
take seconds.

## Decisions

D05 (decided 2026-10-02, amended 2026-10-03) is implemented here. D01 (model commit) is provisional; the
demand unit follows the plugin at the locked commit `39e21ff5` with one model step per day.
