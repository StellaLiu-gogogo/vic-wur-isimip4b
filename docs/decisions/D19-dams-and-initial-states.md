# D19 — Dams and initial states per experiment

Status: **decided 2026-10-11** by the user (decisions taken 2026-10-09 to 2026-10-11).
Due stage: `05_simulation`.

## Context

Raised on 2026-10-07 by the cross-module review. VIC-WUR `39e21ff5` switches a
dam on when the simulation year reaches the dam's construction year
(`plugins/dams/src/dam_register.c`) and never switches it off; the active flag,
the storage and the dam history are restored from an initial state by dam
position (`dam_state.c`). The renderer passed one dam file to every segment, so

- dams followed the simulation year, not the DHF scenario: a `1850soc` future
  segment would get every dam built 1850–2021, a `2021soc` historical segment or
  spin-up would lack the dams of 2021 until their construction years, and the
  1 806 dams with construction year 0 were active in every pre-industrial and
  spin-up year;
- a warm start from a state dated after the run start keeps later dams active:
  the `smoke-nonrenewable` run (2011–2020, started on 2026-10-07 from the
  2021-01-01 state of the smoke run 2011–2020) ran with the 269 dams built
  2012–2020 (284 292 hm³ capacity, 172 491 hm³ stored) active from January 2011.

The user (2026-10-08): dam parameters may need different files for different
experiments, and the spin-up of the model has to be reconsidered. On 2026-10-09
the selection rule of the dam file (degree of regulation DOR ≥ 10 %) was added
to the decision.

## Evidence

Analyses `dam-distribution-review` (`analysis/dam-distribution-review/`,
commits `d051004`, `2817aac`) and `dam-nservice-test`
(`analysis/dam-nservice-test/`, commit `60ca236`); products under
`workdir/analysis/<task-id>/`.

- **Current dam file.** `vic_global_5min_dam_parameters_t3-extended-merged.nc`
  (the `T3_extended_v2` file of `vic_parameter`, also used by the Snellius H
  line): 7 925 GDW v1.0 dams, 6 641 km³, selected by capacity ≥ 20 hm³,
  quality ≤ 4 and DOR ≥ 10 %. The DOR rule drops 1 373 reservoirs with 528 km³
  (Three Gorges, Itaipu, Yacyretá, Porto Primavera, Xiluodu, Saratov, Grand
  Coulee; Raza Dike because its DOR is missing). 1 806 dams have no GDW year
  (year 0). The file was snapped and its service maps traced on the old WBT
  routing (`01oc_natural/03vic_input/vic_global_5min_routing_param_wbt.nc`),
  whereas the parameter set uses the HydroSHEDS routing `v1.0.0_20260804`:
  60.89 % of the common cells have another downstream cell; in the test runs
  Ust-Ilim and Brokopondo receive less than 1 hm³/day.
- **ISIMIP4b reservoirs-dams.** `histsoc` (identical to `2021soc`, version of
  August 2026): 7 331 dams, 7 035 km³, construction years 1850–2021, unknown
  years set to 1850 (`FLAG_ART`, 291 dams). SSP future hydropower dams of
  WaterGAP2-2e: `ssp1vlsoc-noadapt` 1 758 dams (942 km³, built 2022–2060),
  `ssp3hsoc-noadapt` 2 855 dams (2 151 km³, built 2022–2100). The protocol
  makes the dataset optional; the `water_global` Group III default needs land
  use, irrigation and non-irrigation water use, and names hydropower dams as an
  example for `extrasoc`.
- **GDW against ISIMIP4b.** 7 324 of the 7 331 ISIMIP4b dams are found in GDW
  (GRanD ID, or location within 2 km and capacity within a factor 2); 39 of them
  (131 km³, e.g. Grand Ethiopian Renaissance Dam, Farakka) only in the GDW
  barriers layer; Rogun and Changheba lie 22 and 13 km from their GDW records,
  Huangdeng is a barrier without capacity, Burdana is combined with Rumela,
  Nam Kum Gate and Fengman_2 share the record of another ISIMIP dam, and only
  Wudongde (4 km³) is absent. Capacities differ strongly for some pairs (Daniel
  Johnson 141.9 against 35.2 km³, Indirasagar 1.2 against 9.75 km³).
- **Dams and water supply in VIC-WUR `39e21ff5`.** A local dam supplies its own
  cell from its storage (`wu_run_local.c`); the storage of a global dam is never
  withdrawn directly, its service map only enters the release rule (Hanasaki et
  al. 2006, `dam_calc_opt_release`: demand-following release with demand, the
  mean inflow without). There is no reservoir evaporation (`dam_area` is not
  called).
- **`Nservice = 0` test.** Two global runs of 2016 from the 2016-01-01 state of
  the smoke run 2015, the candidate dam file against a copy in which 1 301
  global dams (3 103 km³) without a supply purpose have `Nservice = 0`: exit
  code 0, no `[ERROR]` line, no service warning; the 1 301 dams operated,
  registered zero demand and closed their daily storage balance within
  0.015 hm³. Their first-year planned release still follows the demand history
  of the state (up to five years are averaged, `DAM_HIST_YEARS`).
- **Initial states (source review, 2026-10-11).** VIC checks only dimensions of
  a state (grid, vegetation classes, snow bands, layers, nodes:
  `drivers/shared_image/src/vic_restore.c`; routing step: `rout_restore.c`;
  number of dams: `dam_state.c`), never its date, and restores every field by
  position. Beyond soil, snow and soil temperature a state carries the dams
  (active flag, storage, operation month, inflow and demand history, planned
  release), the land-use coverage of the state's year (`STATE_LU_CV`), the
  irrigation state (`STATE_IRR_PREV_CV`, leftover and received water, offset)
  and the water in transit in the rivers (the non-renewable deficit only with
  `NONRENEWABLE_WITHDRAWAL`). At the first step of a run with an initial state
  the land-use plugin applies the run's coverage and redistributes water between
  tiles **only when the run starts on 1 January** (`plugins/landuse/src/lu_force.c`);
  on any other start date the state's coverage stays until the next 1 January.
  The irrigation plugin starts a new season where the coverage changed
  (`irr_run.c`); dams register the new year and switch on as the run's dam file
  says, but a dam active in the state stays active.

## Options considered

- Dam list: keep the GDW T3_extended selection; GDW without the DOR rule
  (all GDW minus quality 5, missing DOR and offstream: 25 816 records,
  7 244 km³); or the ISIMIP4b dams located with GDW (chosen).
- Location: keep the 5′ cells of the corrected GDW table for the matched dams and
  snap only the 46 others; or snap every dam again on the routing of the
  parameter set (chosen, because the corrected table was made on the WBT routing).
- Dams per DHF scenario: one dam file for all segments (current, rejected) or
  one dam list with a construction-year rule per scenario (chosen).
- Initial states: forbid every warm start, or allow them under conditions
  checked by the renderer (chosen).

## Decision

**Dam list.**

1. The dams are the 7 331 ISIMIP4b `histsoc` dams, no more and no less, plus the
   ISIMIP4b SSP future hydropower dams of `ssp1vlsoc-noadapt` and
   `ssp3hsoc-noadapt`. GDW v1.0 (corrected 5′ table and barriers layer) only
   provides dam locations and identifiers; dams found only in GDW are dropped.
   The future dams enter the list now because an initial state is restored by
   dam position and an `extrasoc` future segment starts from the `histsoc`
   historical state.
2. Every dam is snapped again on the routing of the parameter set with the full
   rule of the corrected GDW table (nearest cell, then the cell of the 3×3
   neighbourhood whose upstream area best matches the catchment area); the
   service maps are traced again on that routing and the FILE decomposition file
   is rebuilt.
3. Where two dams fall into one 5′ cell (VIC `39e21ff5` sizes the dam output for
   one dam per cell), the smaller dam is moved to a free neighbouring cell on the
   same river when the upstream area still fits; otherwise the two are merged
   (capacities summed, construction year of the larger dam). Fengman and
   Fengman_2 (one reservoir, dam rebuilt in 2019) are one dam with the capacity
   of the new dam (11 460 hm³) and the construction year of the old dam (1941).
4. Capacity: ISIMIP4b `CAP_MCM`; pairs whose ISIMIP4b and GDW capacities differ
   strongly are reviewed by hand.
5. Purpose: global dams without an irrigation or water-supply purpose, and every
   SSP future dam (forced to type global), get `Nservice = 0` and no service map.

**Construction years per DHF scenario.** Every scenario uses the same dam list
in the same order; only `year` differs:

| DHF scenario of the segment | `year` |
|---|---|
| `histsoc` | ISIMIP4b `YEAR` (unknown years 1850, as in ISIMIP4b); SSP future dams: a year after 2100 (never) |
| `1850soc` | 0 (always) for dams with `YEAR` ≤ 1850, a year after 2100 for all others |
| `2021soc`, `2021soc-from-histsoc` | 0 for every ISIMIP4b `histsoc` dam, a year after 2100 for the SSP future dams |
| SSP units | 0 for every ISIMIP4b `histsoc` dam; the SSP future dams of the unit's own scenario follow their construction year where they operate (`extrasoc`, D06), a year after 2100 otherwise |

**Spin-up.**

1. Two spin-ups per GCM. `1850soc`: `picontrol` climate with the `1850soc` land
   use, water use and dams, ending on 1601-01-01; it starts the pre-industrial
   segment (1601–1849), whose end state starts the four historical segments.
   `2021soc`: `picontrol` climate with the `2021soc` land use, water use and
   dams, ending on 1850-01-01; it starts the two `2021soc` historical segments.
   The year labels are the years before 1601 and 1850, so that each end state is
   dated the start of the next segment (the first year needs D20).
2. Climate cycle: `picontrol` 1601–1650 (`spinup.climate_cycle`).
3. Length: 50 years, then blocks of 25 years continued from the spin-up's own
   end state until the convergence test passes. Test: over the last 10 years the
   trend of the annual values is below 0.1 interannual standard deviations for
   soil moisture of layers 2 and 3 (global and the about 20 largest basins),
   December snow water equivalent (without the glacier cells of D18), total
   reservoir storage and river storage, and for `2021soc` also irrigation
   withdrawal. A spin-up writes only these annual diagnostics; its output is not
   reported.
4. Start: the first GCM's `1850soc` spin-up is a cold start; the `2021soc`
   spin-up may start from the end state of the `1850soc` spin-up, and the
   spin-ups of a further GCM from the end states of the first GCM's spin-ups with
   the same DHF scenario, under the warm-start rule below; the convergence test
   is repeated from the warm start.

**Initial states (warm-start rule).**

1. A reported segment (pre-industrial, historical, future) starts only from the
   end state of its parent segment, dated its start.
2. A spin-up or a non-production run may start from the end state of another
   completed run when all of the following hold, and the renderer checks them
   before it renders the run:
   - the run starts on 1 January (otherwise the land-use plugin keeps the
     state's coverage until the next 1 January);
   - model commit, executable and every parameter file are identical, except
     the dam file, whose dam list (`id`, `type`, `capacity`, order) is identical;
   - the same plugins are switched on;
   - every dam active in the state (`STATE_DAM_ACTIVE`) operates in the run's dam
     file at the start year.
3. A spin-up started this way repeats the convergence test. The
   `smoke-nonrenewable` warm start of 2026-10-07 breaks rule 2 and is not used
   for results.

## Consequences

- `03_parameters`: a dams component produces the dam list, the per-scenario dam
  files and the matching FILE decomposition from ISIMIP4b `histsoc`, the
  ISIMIP4b SSP files and GDW v1.0, which must first be acquired into
  `raw/external/` with an input manifest (now only in the legacy area, D15).
  The current dam and decomposition files stay candidates for the smoke
  campaigns only.
- `05_simulation`: the campaign names one dam file per DHF scenario; the
  renderer picks it by the segment's scenario, checks that parent and child have
  the same dam list instead of the same dam file, and checks the warm-start rule
  above (1 January, identical inputs except the dam file, same plugins, active
  dams). The resolver and the campaign keys `spinup.length_years` and
  `spinup.climate_cycle` follow the spin-up rules; the convergence test is new.
- D20 (first year of constant DHF units) is still needed for the spin-up year
  labels, the pre-industrial segment and the `2021soc` historical segments.
- The smoke runs used dams placed and served on the WBT routing; their dam
  results are not representative.
- Implementation is a workflow task proposed to the user after this record.
