# D07 — Aggregation of the 5′ output to the 0.5° grid, `dis` outlet cells, static fields

Status: **decided 2026-11-09** by the user (task AD).
Due stage: `06_postprocessing`.

## Context

ISIMIP4b `water_global` variables are reported on the 0.5° grid (protocol
`f9be7b0`, `definitions/variable/*.yaml`, resolution "0.5° grid"); VIC-WUR
runs on the 5′ grid. The model capability audit named three gaps for
postprocessing: the 5′ to 0.5° aggregation, the cell whose discharge
represents a 0.5° cell, and the derivation of `contfrac`. The decision only
concerns `06_postprocessing`: the 5′ output of the runs does not depend on it.
The user added a fourth part, the time steps of the variables the protocol
asks for "daily if possible".

## Evidence

- The VIC 5′ grid is an exact 6 × 6 subdivision of the ISIMIP 0.5° grid
  (latitudes from −55.958° to 83.958°, longitudes from −179.958°): every
  0.5° cell holds 36 5′ cells. Domain file of the production parameter set
  `vic-global-5arcmin-version-b`
  (`domain/vic_global_5min_domain_nogl.nc`): 2 188 551 active cells
  (`mask` 1); `area` (m2, WGS84) is defined on every cell of the grid;
  `frac` is 1 on every active cell (checked 2026-11-09), so every active
  5′ cell is simulated as whole land, and 100 306 inactive cells carry a
  partial `frac` that no run uses.
- D08: products are masked with `landseamask_water-global.nc`; the 3 310
  mask cells without an active VIC cell are `1e+20` and never filled from
  neighbours; the 11 328 active VIC cells outside the mask do not enter the
  aggregation; `contfrac` and `landfrac` are derived consistently with the
  missing cells.
- The routing file of the parameter set (`routing/vic_global_5min_routing.nc`)
  holds `downstream`, `downstream_id`, `cell_area` and `active_mask` but no
  upstream area; the upstream area is accumulated along `downstream`, as
  `workflow/05_simulation/monitor/grdc.py` does for the GRDC stations.
- ISIMIP's 0.5° drainage network DDM30 is in the raw data:
  `raw/ISIMIP4b/InputData/geo_conditions/river_routing/ddm30_flowdir_cru_neva.nc`.
- Protocol definitions (`definitions/variable/static.yaml`,
  `hydrological.yaml`, chapter 4.1):
  - `cellarea` in km2, "the total area associated with each grid cell";
  - `contfrac`: fraction of the cell that is continent, including inland
    water bodies, excluding ocean;
  - `landfrac`: fraction of the cell that is land, excluding ocean and
    inland water bodies;
  - `soil`: "soil type as used by your model";
  - `soilmoist`: every soil layer, depth in m, dimensions
    `(time, depth, lat, lon)`, "daily if possible, else monthly";
  - `dis`: m3 s-1, daily and monthly;
  - per-area variables refer to the land area of the cell unless stated
    otherwise; the reference area may be given in the global attribute
    `reference_area`.
- Campaign output (D03): daily `qtot` and `dis` in every reported segment;
  daily `OUT_SOIL_MOIST`, `OUT_EVAP` and `OUT_WITHDRAWN` only in the
  historical and future segments (1850–2100); `tsl`, `snd` and `snm` (daily
  if possible) are written monthly only. VIC-WUR has continuous soil
  parameters per cell and no soil types; `LAKES FALSE`, so there is no
  inland water store.

## Options considered

1. Fluxes and stores:
   - (A) area-weighted mean over the active 5′ cells of a 0.5° mask cell,
     i.e. a value per unit of simulated land area;
   - (B) sum over the 5′ cells divided by the whole 0.5° cell area, which
     dilutes coastal cells and does not follow the protocol's land-area
     reference.
2. `dis`:
   - (A) the 5′ cell with the largest upstream area inside the 0.5° cell,
     one fixed cell for all time steps;
   - (B) the 5′ cell whose upstream area best matches the DDM30 upstream
     area of the 0.5° cell, which follows ISIMIP's network but picks odd
     cells where the two networks disagree;
   - (C) the largest discharge of the 36 cells at each time step, which
     switches cells over time and is no consistent river.
3. Static fields: `cellarea` from the 5′ domain areas or from a sphere;
   `landfrac` equal to `contfrac` or not provided; `soil` not provided or a
   class derived from the soil parameters.
4. `soilmoist` time steps:
   - (A) monthly 1601–2100, plus daily 1850–2100;
   - (B) daily 1850–2100 and monthly 1601–1849 only;
   - (C) monthly only.

## Decision

The user took the recommended option of every part (2026-11-09).

1. **Fluxes and stores, option (A).** For every 0.5° cell of
   `landseamask_water-global.nc` with at least one active 5′ cell, the
   value is the weighted mean `Σ x_i w_i / Σ w_i` over the active 5′ cells
   `i` inside it, with `w_i` = domain `area` × `frac` (equal to `area`
   while `frac` is 1 on every active cell). The value refers to the
   simulated continental area of the cell; the files say so in
   `reference_area`.
   - Volumes (reservoir storage in hm3) are summed over the 5′ cells and
     divided by `Σ w_i`.
   - Per-layer variables (`soilmoist`, `tsl`) are aggregated layer by
     layer (three VIC layers). The depth of a layer in a 0.5° cell is the
     weighted mean of the 5′ layer depths of the parameter set, written as
     the depth coordinate of the ISIMIP varying-levels form.
   - A missing value on an active 5′ cell is not expected (the run check
     covers coverage); the product check fails when one occurs, and nothing
     is filled.
   - Mask cells without an active 5′ cell are `1e+20` (D08).
2. **`dis`, option (A).** The outlet cell of a 0.5° cell is the active 5′
   cell inside it with the largest upstream area along the routing network
   of the parameter set, with a fixed tie rule recorded in the outlet map.
   The 0.5° `dis` is the unchanged 5′ discharge of that cell, daily and
   monthly. The outlet map (the outlet cell of every 0.5° cell and its
   upstream area) is a static file of the product set. DDM30 is used only in a
   check: the upstream area of each outlet is compared with the DDM30
   upstream area of the 0.5° cell (report and figures, not a pass
   criterion).
3. **Static fields.**
   - `cellarea` = sum of the domain `area` (WGS84) of the 36 5′ cells,
     in km2.
   - `contfrac` = `Σ w_i` / `cellarea` (same units).
   - `landfrac` = `contfrac`: VIC-WUR separates no inland water bodies
     (`LAKES FALSE`); the variable comment says so.
   - `soil` is not provided: VIC-WUR has continuous soil parameters and no
     soil types. This is recorded in the product configuration of
     `06_postprocessing`. The campaign file, whose `not_provided` lists
     `soil` as a postprocessing product, is not changed while its runs are
     in production.
   - Every static field is `1e+20` at the 3 310 uncovered mask cells (D08).
4. **`soilmoist`, option (A).** Monthly 1601–2100 from the monthly stream,
   and daily 1850–2100 from the daily stream. `tsl`, `snd` and `snm` are
   reported monthly, the only time step VIC writes. The daily `OUT_EVAP` and
   `OUT_WITHDRAWN` stay in the run output; the protocol asks for `evap` and
   the withdrawals monthly only.

## Consequences

- `06_postprocessing` (task AD) implements the static fields and the outlet
  map, the products per run chunk, and their checks:
  - for every variable and time step, the area-weighted global total of
    the 0.5° product equals the total over the active 5′ cells inside the
    mask, within float precision;
  - the outlet `dis` equals the 5′ discharge of its outlet cell;
  - exactly the 3 310 uncovered cells are missing.
- `contfrac` comes in steps of the 5′ cell areas, because every active 5′
  cell is simulated as whole land. A user who multiplies a value by
  `contfrac` × `cellarea` gets the simulated total of the cell.
- The D08 check of `07_quality_control` (exactly the 3 310 cells missing)
  applies to every product, the static fields included.
- A change of any part of this decision changes the products and needs a
  new product-set identity (D11).

## Amendment 2026-11-11 (user, task AD7)

The user reviewed the products of the AD6 scratch unit (test run
`soil-comparison-version-b`, 2011–2020; review page under
`scratch/postprocessing-build/review/`, deleted at the end of task AD) and
decided its three findings. No production unit had been made, so no product
set needs a new identity (D11); the scratch unit is made again.

1. **Groundwater withdrawal products (F1), option (a).** *Replaced by the
   amendment of 2026-11-12 (below) before any production unit was made.*
   `airrwwgw`,
   `adomwwgw`, `aindwwgw` and `atotwwgw` keep the campaign mapping,
   `OUT_WI_GW_SECT` only: renewable groundwater, taken from the deepest VIC
   soil layer. The non-renewable source (`OUT_WI_NREN_SECT`) stays in the
   withdrawal totals (`airrww`, `adomww`, `aindww`, `atotww`) and in the
   consumption (`adomuse`, `ainduse`, `atotuse`). The `comment` of each of
   these products says whether the non-renewable source is included. The
   demand products `p*wwgw` (`OUT_DE_GW_SECT`) are unchanged.
   - Evidence. In the test run the non-renewable source supplies 1 925 of
     4 386 km3 per year (44 %), and `atotwwgw` is 279 km3 per year. Counting
     the source as groundwater would give about 2 200 km3 per year.
   - The share is not caused by the cold start of the test run. In the
     production `2021soc` chain it is 49 % in the first year after the cold
     start and 42–46 % from the second or third year on. This holds over the
     whole spin-up 1800–1849 and over `historical_2021soc` 1850–1874.
   - ISIMIP3b models report groundwater withdrawals of 640–1 000 km3 per
     year, of which about 170–180 km3 per year are non-renewable (H08,
     PCR-GLOBWB).
   - The non-renewable source of VIC-WUR mainly makes up a supply
     shortfall. H08 books a comparable shortfall as an unspecified surface
     supply.
2. **`qtot`, `qsb`, `qg`, `qr` and the repayment of the non-renewable
   deficit (F2), option (a).** These products keep `OUT_BASEFLOW`. Their
   `comment` says that, where a cell has a non-renewable deficit, part of
   the baseflow repays it in the routing and never reaches the river, so
   this water is in these products but not in `dis`.
   - VIC-WUR repays the deficit by two routes (model commit `a826251b`):
     - from the baseflow in the routing (`plugins/routing/src/rout_run.c`);
     - from the return flows of water use (`wu_run_local.c`, `wu_remote.c`,
       `wu_nonrenewable.c`).
   - VIC-WUR does not write the two parts separately. In the test run
     1 581 km3 per year were repaid. The baseflow part lies between 225 and
     734 km3 per year, 0.5–1.5 % of the global `qtot`.
   - Option (b), a separate model output for the baseflow part, would change
     the frozen model (D01).
3. **The task T rule in `evap` (F3).** The rule was decided by the user on
   2026-10-30 (`analysis/snow-sublimation-outliers/`), and stage 06 did not
   apply it until now.
   - **Which cell-months.** A 5′ cell-month is left out when its monthly
     mean |`OUT_WATER_ERROR`| exceeds 1 mm. These are rare snow-sublimation
     outliers of VIC: 7 cell-months in 172 years of the natural run, and
     none in the test run.
   - **How the 0.5° value is made (user, 2026-11-11).** A left-out cell is
     not counted in the area-weighted mean of `evap`. The 0.5° value is the
     weighted mean of the remaining active 5′ cells of that 0.5° cell. The
     whole 0.5° cell-month is not made missing: that keeps the coverage of
     D08.
   - **When no cell remains.** A 0.5° cell-month is missing (`1e+20`) only
     when every active 5′ cell in it is left out.
   - **Record.** The unit record (`provenance.yaml`, `exclusions`) lists:
     - every left-out 5′ cell-month, with its 5′ cell and its values of
       `OUT_WATER_ERROR` and `OUT_EVAP`;
     - the 0.5° cell-months made missing.

     The `comment` of the `evap` file states the rule and the counts for
     that file.
   - **Scope.** Daily `evap` is not produced (part 4), so the daily form of
     the rule is not needed. No other product is affected: of the variables
     the outliers touch, only `OUT_EVAP` enters a product.
   - **Configuration.** The rule is the `exclude` setting of the `evap`
     recipe in `products.yaml`. The VIC outputs of the recipe are still
     exactly those of the campaign.

**Changed consequences.**

- The total check of part 1 also covers `evap`. Its global total equals the
  5′ total in which every left-out cell-month takes the mean of the remaining
  cells of its 0.5° cell.
- **Missing cells.** Every product is missing on exactly the 3 310 uncovered
  cells of D08. `evap` is also missing on the cell-months that its unit
  record lists. The D08 check of `07_quality_control` takes those cell-months
  from the unit records.
- **The unit check** (`check_unit.py`) checks the rule in three ways:
  - it reads `OUT_WATER_ERROR` at every time step and compares the left-out
    cell-months and the missing cells with the record (`exclusions`);
  - it allows missing values only at the recorded cells (`coverage`);
  - it recomputes `evap` by its own route at every time step that has a
    left-out cell (`recompute`).

## Amendment 2026-11-12 (user, task AD7): groundwater part of the non-renewable withdrawal

The user replaced part 1 (F1) of the amendment of 2026-11-11, in the
session that compared VIC-WUR with ISIMIP3b groundwater withdrawals: "*wwgw
should be 279 + the groundwater part of NREN". In that sentence, 279 is
`atotwwgw` of the test run, in km3 per year.

**Decision.** `airrwwgw`, `adomwwgw`, `aindwwgw` and `atotwwgw` are the
renewable groundwater withdrawal (`OUT_WI_GW_SECT`) plus the groundwater part
of the non-renewable withdrawal (`OUT_WI_NREN_SECT`).

- **How the part is split.** For each 5′ cell, water-use class and month,
  the non-renewable withdrawal N is divided in proportion to the demand that
  the local sources left unmet:
  - unmet groundwater demand: Ug = max(0, `OUT_DE_GW_SECT` −
    `OUT_WI_GW_SECT`);
  - unmet surface-water demand: Us = max(0, `OUT_DE_SURF_SECT` −
    `OUT_WI_SURF_SECT` − `OUT_WI_DAM_SECT`);
  - groundwater part = N × Ug / (Ug + Us), and 0 where Ug + Us is 0.

  The user took this proportional rule, which was recommended. The split is
  made per class and then summed over the classes of the sector, or over
  all classes for `atotwwgw`.
- **The rest of N** is the unmet surface-water demand. It stays in the
  withdrawal totals (`a*ww`) and the consumption only, as before.
- **The comments** of `*wwgw` state the rule. The comments of the totals say
  that the groundwater part of the non-renewable withdrawal is also in
  `*wwgw`.
- **The demand products** `p*wwgw` (`OUT_DE_GW_SECT`) are unchanged.

**Why the split follows the model.** VIC-WUR `a826251b` with `GWM FALSE`
(`wu_run.c`, `wu_remote.c`, `wu_nonrenewable.c`) handles demand in four steps:

1. It splits the demand of a class into a groundwater demand (the
   groundwater fraction of the forcing, D05) and a surface-water demand.
2. The local step serves the groundwater demand from the deepest soil layer
   only, and the surface-water demand from the local river and the local
   dams only.
3. The remote step serves what is left of both.
4. The non-renewable source takes the rest.

What follows from this:

- The remote step can serve either kind of demand first. So the groundwater
  part of N lies between max(0, N − Us) and min(N, Ug), and the
  proportional rule always lies inside these bounds.
- In the test run, N = max(0, Ug + Us − `OUT_WI_TREM_SECT`) holds in every
  cell-month, within 1e-4 km3 per year globally. This confirms that the
  monthly outputs follow this order of steps.

**Evidence** (test run 2011–2020, cold start, km3 per year; scratch check of
the comparison session, job 43913296):

| | municipal | manufacturing | irrigation | all |
|---|---|---|---|---|
| groundwater part of N, bounds | 51–52 | 146–150 | 571–595 | 768–798 |
| groundwater part of N, proportional | 52 | 148 | 584 | 784 |
| `*wwgw`, proportional | 170 | 271 | 622 | 1 063 |

- `atotwwgw` = 1 063 km3 per year, 24 % of the withdrawal of 4 386 km3 per
  year. The literature range of global groundwater withdrawal is 737–1 500
  km3 per year.
- The shares of municipal, manufacturing and irrigation are close to those
  of WaterGAP 2.2e.
- The surface-water shortfall in N is about 1 140 km3 per year.

**Exception to the campaign mapping.** The campaign maps these four
variables to `OUT_WI_GW_SECT` only (task S). The campaign file is not changed
while its runs are in production. Stage 06 normally requires that a recipe
names exactly the campaign's VIC outputs; these four recipes are an exception
to that rule. Each of them is listed with this decision under
`campaign_exceptions` in `products.yaml`, and the producer stops when an
exception is missing or unused.

- The split reads six VIC outputs. All of them are in the monthly stream of
  the campaign already (the `a*ww` and `p*ww` recipes use them), so no model
  or campaign change is needed.
- The unit record keeps the split rule and the exceptions under `method`.

**Checks.** The unit check recomputes the products by a route of its own.
For the split, that route reads all water-use classes of a time step at
once, while the producer works class by class. No production unit had been
made, so no product set needs a new identity (D11).
