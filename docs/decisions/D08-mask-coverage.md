# D08 — Simulated domain versus the ISIMIP `water_global` mask

Status: **decided 2026-09-30** by the user (option (a)). Analysis by the
task `isimip-mask-coverage`.
Due stage: `03_parameters`.

## Context

VIC-WUR runs on the 5′ domain `vic-global-5arcmin-version-a`
(`vic_global_5min_domain_nogl.nc`, 2 188 551 active cells, Greenland made
inactive). ISIMIP expects `water_global` output on the 0.5° grid, on the
67 420 cells of `landseamask_water-global.nc` (the ISIMIP2b generic mask,
1 623 cells larger than the W5E5 mask without Antarctica). Extending the
domain would change every parameter component and every forcing unit, so
the decision is due before `03_parameters`.

The analysis (`analysis/isimip-mask-coverage/`, report and tables in
`workdir/analysis/isimip-mask-coverage/`) established:

- The VIC 5′ grid is an exact 6 × 6 subdivision of the ISIMIP 0.5° grid
  (opposite latitude order; VIC extent 56°S–84°N contains every mask cell).
- VIC has active cells in 64 110 of the 67 420 mask cells (95.1 %; 92.6 %
  of the mask area). 3 310 cells (2.2 % of the mask area, 3.25 Mkm²) have
  none:
  - 2 970 cells, 2.41 Mkm²: Greenland (land in VIC's template, 100 057 5′
    cells, deliberately inactive);
  - 340 cells, 0.83 Mkm²: Arctic islands and coasts (49), oceanic islands
    and coastal cells (242), isolated single-cell islands (48), one bay
    (1). VIC has no 5′ land information for any of them; only 45 are land
    in the W5E5 mask.
- 11 328 active VIC cells (0.5 %) lie in 2 532 coarse cells outside the
  mask (coastline fragments, Lake Ladoga/Onega, Kara-Bogaz-Gol); none of
  those coarse cells is land in any ISIMIP mask.
- The protocol requires the 0.5° grid and `1e+20` for "grid points you do
  not simulate"; neither the protocol text nor the `isimip-qc` tool
  requires a value in every mask cell. How the 5′ models of ISIMIP3b
  (PCR-GLOBWB, CWatM) handled this was not verifiable on Anunna.

## Options

| Option | Mask cells gained | New active 5′ cells | Main cost |
|---|---|---|---|
| (a) keep the domain; report the 3 310 uncovered cells as missing; drop the 11 328 VIC cells outside the mask at aggregation | 0 | 0 | documentation; `contfrac`/`landfrac` consistent with missing cells (D07) |
| (b) extend to all mask cells | 3 310 | 100 397 – 112 297 (+4.6 to +5.1 %) | Greenland: soil, vegetation, snow/elevation bands, routing and an ice-sheet representation that VIC-WUR does not have; islands: a new 5′ land mask and full parameter pipeline; all forcing units regenerated |
| (b′) as (b), restoring the whole Greenland template | 3 310 | 100 646 – 112 546 | as (b) |
| (c) islands and coasts only, Greenland excluded | 340 (0.5 % of cells, 0.6 % of area) | 340 – 12 240 | new 5′ land mask and parameter pipeline for cells whose climate forcing the protocol itself flags as possibly sea-like (295 of 340) |
| (c′) as (c), south of 60°N only | 291 | 291 – 10 476 | as (c) |

Ranges depend on a 5′ land mask that does not exist yet (one to 36 cells
per 0.5° cell).

## Recommendation (agent, 2026-09-30)

Option **(a)**. The protocol permits missing cells; 74 % of the uncovered
area is an ice sheet that VIC-WUR cannot represent; the remaining 0.5 % of
cells would need a new parameter pipeline for negligible gain; the reverse
mismatch costs nothing. Conditions: document the missing cells in the
model description and product provenance, keep the VIC cells outside the
mask in the simulation but not in the products, verify the ISIMIP3b
precedent on DKRZ before the first delivery, and inform the sector
coordinators. Option (c) is not recommended under any outcome; if
Greenland is required, the decision becomes (b′) and needs a
`03_parameters` component for ice-covered cells first.

## Decision

**Option (a)** (user, 2026-09-30): the simulated domain stays
`vic-global-5arcmin-version-a` (2 188 551 active 5′ cells, Greenland
inactive). The 3 310 `water_global` mask cells without an active VIC cell
are reported as missing (`1e+20`). The 11 328 active VIC cells outside
the mask stay in the simulation and are excluded from the reported 0.5°
fields.

## Consequences

- `03_parameters`: no change to the domain component; the vegetation and
  other components are generated for the current domain only.
- `04_forcing`: forcing units are downscaled for the current domain; the
  VIC cells outside the mask take the climate forcing of their own 0.5°
  cell, which the ISIMIP4b climate files populate over the ocean as well
  (amended 2026-09-30, see below).
- `06_postprocessing` (D07): products are masked with
  `landseamask_water-global.nc`; the 3 310 uncovered cells are `1e+20`
  and are never filled from neighbours; `contfrac` and `landfrac` are
  derived consistently with the missing cells; VIC cells outside the mask
  do not enter the aggregation.
- `07_quality_control`: a check confirms that exactly the 3 310 cells
  listed in `workdir/analysis/isimip-mask-coverage/tables/uncovered_isimip_cells.csv`
  are missing in every product.
- `08_delivery`: the missing cells and their reason (Greenland ice sheet
  not represented; small oceanic islands without 5′ parameters) are stated
  in the ISIMIP model documentation. Before the first delivery, the
  ISIMIP3b precedent (non-missing cell counts of CWatM and PCR-GLOBWB) is
  checked on DKRZ and the sector coordinators are informed.
- The analysis task `isimip-mask-coverage` is closed; its cell-wise NetCDF
  files remain the reference list of uncovered cells, but no workflow
  stage reads them (a QC check must derive the list from the mask and the
  domain itself).

## Amendment 2026-09-30: forcing of VIC cells outside the mask

The first version of this record stated that the 11 328 active VIC cells
outside the mask take their 0.5° forcing from the nearest mask cell. During
the climate-forcing design (`workflow/04_forcing/climate/`) the user
decided instead (2026-09-30) that they use the climate forcing of their own
0.5° cell, i.e. the ISIMIP4b value over the ocean, without substitution.
Evidence for EC-Earth3-ESM-1-1 `esm-hist` 2015 (own cell minus nearest mask
cell, weighted by the number of VIC cells): annual-mean `tas` +0.26 °C
(mean absolute 0.36 °C, extremes −3.9 to +4.8 °C), `pr` −0.14 mm/day,
`sfcwind` +0.64 m/s, `rsds` +2.0 W m⁻²; distance to the nearest mask cell
median 54 km, maximum 1 069 km. The same values also enter the bilinear
interpolation of coastal VIC cells inside the mask. The decision itself
(option (a)) is unchanged.
