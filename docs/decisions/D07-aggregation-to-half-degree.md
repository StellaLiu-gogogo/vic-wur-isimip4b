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
