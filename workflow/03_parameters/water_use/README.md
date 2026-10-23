# 03 Parameters — water_use

The `water_use` component of a parameter set,
`parameters/<status>/<set>/water_use/vic_global_5min_wateruse_parameters_receiving-network.nc` (read by VIC with
`WATERUSE_PARAMETERS` when `REMOTE_WITHDRAWAL` is TRUE), is **adopted** (vic_parameter receiving network
v1.0.0_20260817, recorded in `manifests/parameters/<set>.yaml`); it has **no producer here**. This directory holds
its verification. (The water-use forcing is produced by `workflow/04_forcing/water_use/`.)

Classification: production workflow code (user, 2026-10-24, task R). The job, the shared parts and the status
rules are described in `../domain/README.md`. Tests: `tests/unit/test_adopted_parameter_qc.py`.

## Variables

As `wu_init.c` at VIC `39e21ff5` reads them: `receiving[k, cell]` holds the `receiving_id` of a cell that `cell`
withdraws water **from** (the supplier; 0 = unused slot); `Nreceiving[cell]` is the number of cells that withdraw
from `cell`. A link is (demander, supplier). The file holds no distances and no fractions; VIC divides a remote
withdrawal over the suppliers by the water available at run time, so a fraction check is `not_applicable`
(user, 2026-10-24).

## Checks (verify_water_use.py)

- `integrity`, `latlon`: see `../domain/README.md`; lat and lon equal the domain.
- `vic_variables`: `Nreceiving`, `receiving_id` (lat, lon), `receiving` (`wu_receiving`, lat, lon).
- `ids`: `receiving_id` not fill and unique on active cells, equal to the routing `downstream_id`.
- `links`: every supplier of an active demander is an active cell (VIC drops others); no self-links, no supplier
  twice in one cell; `Nreceiving` not fill on active cells and equal to the number of demanders of each cell (VIC
  stops when it finds more and drops links when it finds fewer).
- `order`: the routing order with water use (a cell waits for its upstream cells and for the cells that withdraw
  from it, `wu_set_routing_order`) has no closed loop, and every demander comes before the downstream cell of its
  supplier (`wu_check_routing_order`).
- `distances`: a delta link has as supplier the outlet the demander drains to (any distance; the source QA counts
  8 934); every other link (search link) lies within the stated search, 2 cells and 50 km between cell centres
  (the file's `generation_parameters`).
  Figure `figures/link_distance.png`.
- `generation_rules` (warning only): at most 5 search links and one delta link per demander; supplier upstream area
  ≥ 20 × the demander's (upstream areas from the routing `cell_area`, a spherical cell area, which the generator
  used: with the domain area, an ellipsoidal one, 4 ratios fall 0.02 % below 20); neither cell within 16 cells
  downstream of the other. Map `figures/sources_per_cell.png`.
