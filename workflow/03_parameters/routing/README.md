# 03 Parameters — routing

The `routing` component of a parameter set is **adopted** (vic_parameter routing release v1.0.0_20260804 and
decomposition v2.0.0_20260825, recorded in `manifests/parameters/<set>.yaml`); it has **no producer here**. This
directory holds the verification of the routing file `routing/vic_global_5min_routing.nc` (read by VIC with
`ROUTING_PARAMETERS`). The decomposition file of the component (`DECOMPOSITION_PARAMETERS`) is not checked here.

Classification: production workflow code (user, 2026-10-24, task R). The job, the shared parts and the status
rules are described in `../domain/README.md`. Tests: `tests/unit/test_adopted_parameter_qc.py`.

## Checks (verify_routing.py)

The network is walked by the verifier itself, not by VIC's reader (`rout_start.c`, `rout_init.c` at VIC
`39e21ff5`): every active cell points to the active cell whose `downstream_id` equals its `downstream`; a cell
pointing to itself is an outlet. The file holds no flow-direction codes and no upstream-area variable.

- `integrity`, `latlon`: see `../domain/README.md`; lat and lon equal the domain.
- `vic_variables`: `time`, `downstream_id`, `downstream`, `uh_inflow`, `uh_runoff` with the dimensions VIC reads;
  `time[i] = i × 3600 s` (`ROUT_STEPS_PER_DAY 24`, else VIC stops).
- `entries`: no fill on active cells in any variable VIC reads; `active_mask` equals the domain mask;
  `downstream_id` unique among active cells.
- `unit_hydrographs`: both ≥ 0 and summing to 1 within 1e-5 on every active cell (VIC rescales and warns otherwise).
- `links`: every `downstream` value is the id of an active cell (VIC silently makes any other cell an outlet); every
  link goes to one of the 8 neighbours (longitude wraps; the dateline links are listed) or to the cell itself; at
  most 8 upstream neighbours per cell (`MAX_UPSTREAM`, else VIC stops).
- `cycles`: walking downstream from every active cell ends at an outlet.
- `accumulation`: two independent walks agree: the upstream area accumulated cell by cell downstream equals, at
  every outlet, the sum of the areas of the cells that end there (relative 1e-9). The routing variable `cell_area`
  is compared with the domain `area` and the spherical cell area for the report only: VIC routes with the domain
  area and does not read `cell_area`.
- `basins_grdc`: number of outlets (the source manifest gives 79 461), the 50 largest basins and their outlet cells
  (`reports/largest_basins.csv`), and the most downstream GRDC station of the Amazon (Óbidos 3629000), Congo
  (Kinshasa 1147010), Mississippi (Vicksburg 4127800) and Yangtze (Datong 2181900) from
  `raw/external/grdc/export-2024-11/20241030_grdc_stations.csv`: each station is placed on the active cell within 3
  cells whose upstream area fits the GRDC catchment area best; the outlet that cell drains to is the river's outlet
  (position, basin area and rank reported). Passed with an area error within 10 % and the outlet within 150 km of
  an approximate river mouth or on a reviewed outlet cell; warning with an area error within 30 % or an outlet
  farther from the mouth (for review); failed otherwise.
  Reviewed outlet (user, 2026-10-24): the Yangtze ends at 31.958°N 120.208°E near Jiangyin, about 160 km from the
  coast, because the routing (HydroSHEDS 30″ network) treats the estuary below Jiangyin as sea; the estuary cells,
  land in the VIC mask, are separate outlets. The same convention ends the Paraná at the head of the Río de la
  Plata. This matters for the `dis` outlet mapping of D07. Figure `figures/upstream_area.png` (stations and their outlets marked).
