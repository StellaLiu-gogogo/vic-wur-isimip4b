# 03 Parameters — routing

The routing file of a parameter set is **adopted** (vic_parameter routing release v1.0.0_20260804, recorded in
`manifests/parameters/<set>.yaml`); it has **no producer here**. This directory holds

- the verification of the routing file `routing/vic_global_5min_routing.nc` (read by VIC with
  `ROUTING_PARAMETERS`): `verify_routing.py`, below;
- the producer and verifier of the FILE decomposition `routing/vic_global_5min_file_decomposition_wateruse_isimip4b-dams.nc`
  (read by VIC with `DECOMPOSITION_PARAMETERS`): `build_decomposition.py`, `verify_decomposition.py`, see
  "FILE decomposition". The adopted decomposition `vic_global_5min_file_decomposition_wateruse_dams.nc`
  (vic_parameter v2.0.0_20260825, built for the T3_extended dams) stays for the smoke campaigns and is not checked.

Classification: production workflow code (user, 2026-10-24, task R; the decomposition: task L, 2026-10-30). The job
of the routing verifier, the shared parts and the status rules are described in `../domain/README.md`. Tests:
`tests/unit/test_adopted_parameter_qc.py`, `tests/unit/test_decomposition.py`.

## FILE decomposition (build_decomposition.py, method 1.0)

VIC 39e21ff5 with `DECOMPOSITION FILE` reads the int variable `basin` (lat, lon) and gives whole groups to the MPI
ranks, largest first, each to the rank with the fewest cells so far (`rout_decomposition.c`). All computations of a
cell run on its rank; a dam service cell or a water-use source cell on another rank is dropped by VIC with only a
warning (`dam_init.c`, `wu_init.c`). Routing, dams and water use run cell after cell on each rank, so the rank with
the most cells sets the pace.

1. **Basins.** Every active cell belongs to the outlet it drains to (`downstream` matched against `downstream_id`;
   an outlet points to itself or to an id that is no active cell, as in VIC).
2. **Links.** Water use: every (demander, source) pair of `receiving` in
   `water_use/vic_global_5min_wateruse_parameters_receiving-network.nc`. Dams: every (dam cell, serviced cell) pair
   of `service` in `dams/vic_global_5min_dam_parameters_isimip4b_histsoc.nc` (the three D19 dam files hold the same
   service maps, `verify_dams.py` check `same_list`).
3. **Components.** Basins joined by a link are one component, without a size limit (user, 2026-10-30; the trade-off
   with a size limit is evaluated separately).
4. **Groups.** Components packed into 128 groups (`--groups`) by VIC's rule: largest first, each to the group with
   the fewest cells.

What sets the size of the largest group: a dam service map follows the river downstream from the dam, so it never
leaves the dam's basin; only water-use links join basins. The adopted water-use file was built by vic_parameter
(`tools/build_wateruse_receiving_network.py`, 2026-08-17) together with a decomposition capped at the largest
single basin (69 678 cells, the Amazon): candidate source links that would have joined basins beyond that size were
left out of the file then (15 897 of 2 514 348, its QA `wateruse_receiving_qa_global.json`). The groups built here
from that file therefore stay at most 69 678 cells without losing any link of the file. The adopted decomposition
(largest group 372 255 cells) was larger because the T3_extended service maps, traced on an older routing, cross
basins of the current routing (about 10 300 of their 80 204 links: 349 809 links across basins in its summary,
339 463 of them water use).

Inputs are checked against the md5 of the parameter manifest and, outside scratch, must have `qc_status: passed`.
Outputs: the decomposition and `routing/provenance.yaml` (covering only this file); build report and QC in
`qc/parameters/<status>/<set>/routing/decomposition/` (contract, `qc/`). The build report gives the largest
component and its largest basins, the cells of the largest rank for 1-128 ranks, and how many of these links the
adopted decomposition would put in different groups.

Checks of `verify_decomposition.py`: `vic_variables` (`basin` int on (lat, lon), lat and lon equal the domain);
`groups` (every active cell in 0 .. groups-1, no empty group, fill -1 outside the domain); `routing` (every cell in
the group of its downstream cell); `water_use` (every source in the group of its demander); `dams` (every serviced
cell in the group of its dam, in all three D19 dam files); `provenance` (file checksum, input md5 against the
manifest). It reports, without judging, the cells of the largest rank for 1-32 ranks.

```bash
python3 workflow/03_parameters/routing/submit_decomposition.py --scratch    # test, scratch/dam-parameters/decomposition/
python3 workflow/03_parameters/routing/submit_decomposition.py              # the parameter set (clean repository)
```

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
