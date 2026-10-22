# D20 — First-year files of runs that start outside a forcing unit's years

Status: **decided 2026-10-11** by the user (option A); amended 2026-10-17 (start year 1591, renderer cycle rule; see "Amendment 2026-10-17") and 2026-10-22 (no climate start years for the `2021soc` chain; see "Amendment 2026-10-22").
Due stage: `05_simulation`.

## Context

Raised on 2026-10-07 by the cross-module review of `04_forcing`,
`05_simulation` and VIC-WUR `39e21ff5` (finding P2-1), registered on
2026-10-09 (commit `026e5da`). Three assumptions did not fit together:

- The renderer (`workflow/05_simulation/render/forcing_years.py`) builds a
  per-run forcing view of links named by simulation year. For scenarios
  declared constant in the campaign (`dhf_forcing.constant`: `1850soc`,
  `2021soc`) a year the unit lacks is linked to the unit's first year with the
  same number of days (`constant` rule); spin-up climate is linked into the
  cycle window (`cycle` rule). The rules assumed that VIC opens every year by
  file name only.
- VIC-WUR `39e21ff5` checks the **first year** of a run: the first time of the
  climate file gives the number of records to skip
  (`drivers/shared_all/src/make_dmy.c`, `forceskip = round(start − file
  start)`, an unsigned integer, so a file of another year breaks the run), and
  the first time of every plugin forcing file (land use, water use) must equal
  the first time of the climate file
  (`plugins/general/src/plugin_get_forcing_file.c`). From the second year on,
  files are opened by year name and read from record 0 without a date check
  (`drivers/image/src/vic_force.c`). `render_run.check_start_year` therefore
  requires an identity link for the start year in every forcing family.
- The land-use and water-use producers
  (`workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py`,
  `workflow/04_forcing/water_use/downscale_water_use.py`) write only the years
  of their scenario (`1850soc`, `histsoc`: 1850–2021; `2021soc`, SSP units:
  2022–2100) and stop otherwise.

The protocol experiments start runs on constant DHF scenarios outside these
years: the `1850soc` pre-industrial segment starts in 1601 and the `1850soc`
future segments in 2022; the `2021soc` historical segments start in 1850.
None of them can be rendered. The smoke campaigns (`histsoc` 2011–2020, an
identity year) did not meet the problem.

**Widened scope (2026-10-11).** The D19 spin-up rules label spin-up years
before 1601 (`1850soc` chain) and before 1850 (`2021soc` chain) with a
`picontrol` climate cycle 1601–1650. A read-only check of the VIC sources on
2026-10-11 confirmed that the climate file of the start year is subject to the
same check: a spin-up labelled 1551–1600 would link 1551 to the 1601 climate
file, which VIC rejects. D20 therefore covers every forcing family of the
first year of a run whose start year lies outside a unit's own years: the
constant DHF units **and** the spin-up climate.

## Evidence

Read-only checks of 2026-10-11 (VIC-WUR `39e21ff5`; accepted units under
`workdir/forcing/`, inspected on a compute node; no code written).

- The constant DHF units (`forcing/landuse/{1850soc,2021soc}`,
  `forcing/water_use/{1850soc,2021soc}`) hold one record per year file with
  time `days since <year>-01-01`. The fields are identical across years:
  land use `1850soc` 1850 = 1851, `2021soc` 2022 = 2023 = 2100 = `histsoc`
  2021; the water-use fractions are identical across years; the water-use
  demand (mm/day = annual volume / days of the calendar year) differs only
  between leap and non-leap years.
- The `picontrol` climate unit (`forcing/climate/<gcm>/esm-picontrol`,
  1601–2100) is not yet produced; the raw ISIMIP4b `esm-picontrol` input
  1601–2100 is under `raw/ISIMIP4b/InputData/climate/atmosphere/`.
- First-year files missing under the D19 spin-up plan (with the block
  labelling decided below):

  | Unit | Missing start years | Run |
  |---|---|---|
  | `landuse/1850soc`, `water_use/1850soc` | 1601 | pre-industrial segment |
  | `landuse/1850soc`, `water_use/1850soc` | 2022 | `1850soc` future segments |
  | `landuse/1850soc`, `water_use/1850soc` | 1551, 1576 | `1850soc` spin-up (50-year block, 25-year blocks) |
  | `landuse/2021soc`, `water_use/2021soc` | 1850 | `2021soc` historical segments |
  | `landuse/2021soc`, `water_use/2021soc` | 1800, 1825 | `2021soc` spin-up (50-year block, 25-year blocks) |
  | `climate/<gcm>/esm-picontrol` | 1551, 1576, 1800, 1825 | both spin-up chains |

- Sizes per year file: land use 36 MB; water use 6 files, about 32 MB;
  climate 7 variables, about 13 GB. Option A adds about 70 MB per DHF start
  year and about 13 GB per climate start year (about 55 GB per GCM, almost
  all climate).
- Cycle years of the spin-up start years with the renderer's `cycle` rule
  (window 1601–1650, same day count): 1551 → 1601, 1576 (leap) → 1628,
  1800 → 1650, 1825 → 1625.

## Options considered

- **A (chosen).** The producers of the constant DHF units get an option to
  write, for `1850soc` and `2021soc`, start years outside the scenario's own
  years as *extension years*: the constant field with the time stamp of that
  year, the water-use demand scaled to the year's day count. The climate
  producer gets an option to write a spin-up start year as a copy of the cycle
  year chosen with the campaign's cycle window and the day-count rule, with
  the time axis re-stamped to the start year. The files are extension years of
  the accepted units (`docs/directory-contracts.md`, "Forcing unit and
  provenance record"), their provenance records the source year and the
  scaling. The renderer needs no change: later years keep the `constant` and
  `cycle` links.
- **B.** The producers write every year of the wider ranges (`1850soc`
  1601–2100, `2021soc` 1850–2100, plus the spin-up years): the same files as A
  many times over (about 35 GB of identical files), and the renderer's
  `constant` rule becomes pointless. Rejected.
- **C.** The renderer writes the first-year file into the run's forcing view.
  Rejected: the view holds links only; units are never copied or modified for
  a run (`docs/directory-contracts.md`).
- **D.** Change VIC-WUR so that the first-year date check is skipped. Rejected:
  a model change while D01 is provisional, and the check protects against real
  mistakes.

## Decision

1. **Option A.** Start years outside a unit's own years are produced as
   extension years of the accepted units by the units' own producers, never by
   hand and never by the renderer:
   - `landuse/1850soc`, `landuse/2021soc`: the constant coverage field, time
     `days since <year>-01-01`;
   - `water_use/1850soc`, `water_use/2021soc`: the constant fractions, and the
     demand recomputed as the annual volume divided by the days of the start
     year (365 or 366);
   - `climate/<gcm>/esm-picontrol`: a copy of the cycle year selected with the
     renderer's `cycle` rule for the campaign's window and the start year's day
     count, time axis re-stamped to the start year, data unchanged.
   Every extension year is recorded in the unit's `provenance.yaml` with the
   source year and the transformation (time stamp, demand scaling, cycle
   window).
2. **Acceptance.** The option changes the producers' code-tree hashes while
   every existing year stays bit-identical. Each producer change is tested
   before and after on the same commit base and recorded in
   `manifests/code-equivalence.yaml`; the extension of the accepted units is
   authorised by the user after that test, as the contract requires.
3. **Spin-up block labelling.** The first spin-up block of a chain covers the
   `spinup.length_years` years before the chain start (1551–1600 for the
   `1850soc` chain, 1800–1849 for the `2021soc` chain). Every 25-year
   continuation block is labelled as the last 25 years before the chain start
   (1576–1600 or 1825–1849) and starts from the previous block's end state.
   Every block's end state is thus dated 1601-01-01 or 1850-01-01, and each
   chain needs files for two start years only (1551 and 1576; 1800 and 1825).
   This amends the D19 spin-up rule 3 (length), which left the labels of the
   continuation blocks open.
4. **Scope.** D20 covers the first-year files of every forcing family (land
   use, water use, climate) for the pre-industrial segment (1601), the
   `1850soc` future segments (2022), the `2021soc` historical segments (1850)
   and the spin-up start years of both chains.

## Consequences

- `04_forcing/landuse`, `04_forcing/water_use`: an option to write extension
  years for the constant scenarios (`1850soc`, `2021soc` only; the producers
  keep refusing years outside the scenario for `histsoc` and the SSP units),
  with the day-count scaling of the water-use demand; provenance and verifier
  (`verify_forcing.py`) learn the extension-year record; code-equivalence test
  and entries; then extension of the four accepted units with the start years
  of the table above (user authorisation per unit).
- `04_forcing/climate`: the `esm-picontrol` unit 1601–1650 (at least the cycle
  window) is produced for the GCM; an option writes the spin-up start years
  from the cycle years; code-equivalence test and entry.
- `05_simulation`: no renderer change for the first-year links. The resolver's
  spin-up segment (`_spinup_years`) has to represent the continuation blocks
  (same segment, labels 1576–1600 / 1825–1849, parent = previous block); the
  run-ID rule (`<segment-id>__<label>` only for non-production runs covering
  part of a segment) does not yet cover several blocks of one production
  spin-up segment and needs the smallest contract change, proposed to the user
  in the implementation task. The campaign sets `spinup.length_years` 50 and
  `spinup.climate_cycle` `[1601, 1650]`. The "Start-year restriction"
  paragraph of `workflow/05_simulation/README.md` points to this record.
- If the spin-up block lengths change, the set of start years changes with
  them and further extension years are produced the same way.
- Implementation is a workflow task proposed to the user after this record.

## Amendment 2026-10-17

Recorded in task P (spin-up runs), which took over the climate steps of task O (O3, O5, O6; user, 2026-10-17):

- **Start year 1591.** The non-production spin-up of task L's natural run (10 years, `picontrol` cycle 1601–1610,
  `1850soc` land use, routing and land use only) is labelled 1591–1600 by the block rule of decision 3, so that its
  end state is dated 1601-01-01. It needs the start year 1591 in `landuse/1850soc` (task O, O4) and in
  `climate/<gcm>/esm-picontrol` (a copy of 1601, the cycle year of 1591 in the window 1601–1610). The cycle year of a
  start year depends on the window: in 1601–1650, 1591 would be a copy of 1641.
- **Renderer.** The consequence "no renderer change" holds for the constant DHF units but not for the climate:
  the renderer's `cycle` rule linked every spin-up year to its cycle year even when the unit contains a start year,
  so the start year was never an identity link. The renderer now uses a start year of the climate unit as itself
  when the unit records it as a copy of the cycle year of the campaign's window (provenance `start_years`,
  `cycle_windows`), and stops when it was made for another window.
- **Start years inside the input's years (open).** The climate start years 1800 and 1825 of the `2021soc` chain lie
  inside the years of the `esm-picontrol` input (1601–2100). A copy of 1650 or 1625 under the name of a year the input
  contains would conflict with the real year if the unit is ever extended beyond 1650. The climate producer
  therefore writes a start year only for a year the input does not contain. How the `2021soc` chain gets its climate
  (for example the real `picontrol` years 1800–1849 as its cycle window) is left to the user; it does not affect the
  `1850soc` chain or the natural-run spin-up.

## Amendment 2026-10-22

The open item "Start years inside the input's years" of the amendment of 2026-10-17 is decided (user, 2026-10-22,
D19 amendment of 2026-10-22): the `2021soc` spin-up chain cycles the real `picontrol` years 1800–1849, so its blocks
(1800–1849, 1825–1849) read the climate year of their own label and need no climate start years. The climate row of
the table in "Evidence" becomes:

| Unit | Missing start years | Run |
|---|---|---|
| `climate/<gcm>/esm-picontrol` | 1551, 1576 | `1850soc` spin-up (50-year block, 25-year blocks) |

The land-use and water-use start years of the `2021soc` chain (1800, 1825) are unchanged. The climate start years
cost about 26 GB per GCM instead of about 55 GB. The climate producer keeps refusing a start year that the input
contains.
