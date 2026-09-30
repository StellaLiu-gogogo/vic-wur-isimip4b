# D04 — Land-use harmonization choices

Status: **decided 2026-09-30** by the user.
Due stage: `03_parameters` / `04_forcing`.

## Context

VIC-WUR 5′ needs annual 16-class land cover for 1601–2100 built from the
ISIMIP4b `landuse-15crops` and `landuse-urbanareas` 15′ fractions
(`workflow/04_forcing/landuse/`). Each 15′ parent is split into nine 5′
children using the VIC 2003–2022 class pattern as weights. Five choices were
left open by the September 2026 prototypes (legacy area,
`02Audit/VICWUR_ISIMIP4b_annual_landuse_harmonization_plan_15crops_2026-09-23.md`,
Chinese, not adopted; the numbers below are its data facts).

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | How to place a class in a parent that has no VIC weight for it (fallback parent) | **Single child for every fallback parent**: the whole target goes to one child (largest fallback weight, else largest land area), regardless of the parent share. Prototype threshold 1e-3 gave ≈781k non-paddy and ≈768k urban children in SSP1-VL 2050 and +1.51 M crop and urban tiles overall (+17 % of the 9.06 M bundle tiles); the single-child rule bounds new tiles by one per fallback parent. |
| 2 | `rice_rainfed` | **Class 12 (rainfed crop)**, not the paddy class: VIC's paddy class 15 is irrigated by construction, and a separate rainfed-rice class would change the 16-class contract. Known simplification: flooded-field physics of rainfed rice is not represented. 2021: 0.786 Mkm². |
| 3 | ISIMIP paddy area (`rice_irrigated`) replaces the VIC paddy area | **Accepted.** Paddy 0.817 → 0.505 Mkm² (−38 %), non-paddy irrigated 2.26 → 2.46 (+9 %), irrigated total 3.08 → 2.97 (−3.6 %), 2021 values; spatial IoU of paddy 0.41. Areas are defined by ISIMIP for all sector models; the change in irrigation demand over rice regions is quantified in the smoke test and documented for the model description. |
| 4 | `*_bf` bioenergy variables | **Merged** into the rainfed and irrigated sums of their crop type (up to 1.1–1.3 Mkm² by 2100 in the SSP scenarios); VIC has no bioenergy class. |
| 5 | Köppen–Geiger map for vegetation-parameter backfill of new tiles | **1991–2020 only** (Beck et al. 2023, 0.1°), consistent with the 2003–2022 observation period of the VIC parameters; no scenario-dependent future maps, because the parameter climatology does not change by scenario. |

## Consequences

- `isimip_landuse_to_vic_annual.py` method version 1.2: `--small` defaults
  to `inf` (decision 1); decisions 2 and 4 were already implemented
  (all 17 `*_rainfed*` and 17 `*_irrigated*` variables summed;
  `rice_irrigated` alone forms class 15). `--small 1e-3` reproduces the
  prototypes.
- Decision 3 needs no code; the irrigation-demand check is part of the
  smoke campaign (`05_simulation`).
- Decision 5 concerns the vegetation-parameter backfill for new tiles,
  which is `03_parameters/vegetation` work tied to the adopted bundle and
  D01. No production code exists yet; the prototype
  `union_backfill_paddy.py` stays in the legacy area as reference.
- Units produced before this decision (none exist) would have to be
  regenerated.
