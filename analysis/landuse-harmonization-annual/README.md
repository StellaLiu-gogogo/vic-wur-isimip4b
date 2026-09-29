# landuse-harmonization-annual

**Question.** How should ISIMIP4b `landuse-15crops` and `landuse-urbanareas`
15′ annual fractions be converted into VIC-WUR 5′ annual 16-class coverage
(Option 1, annual Cv only): allocation weights, joint water-filling,
fallback chains, single-child rule, natural remainder, and parameter
backfill for new tiles?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** promoted. The production converter derived from these
prototypes is `workflow/04_forcing/landuse/isimip_landuse_to_vic_annual.py`
(migrated in D15 step 8). Prototype code here was rewritten to the project
layout where the inputs exist in this project; inputs that are still outside
the project are listed below.

**Inputs.**
- `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-15crops_*`,
  `landuse-urbanareas_*`, `landuse-5crops_*`, `landuse-totals_*` (15′);
- `raw/external/vic-coverage-version-a/5/` (VIC coverage 2003–2022);
- `parameters/candidates/vic-global-5arcmin-version-a/domain/`;
- **outside the project** (needed to re-run `union_backfill_paddy.py` and the
  vegetation-parameter checks): the VIC vegetation bundle and activity masks
  in `vic_global/vic_parameter/`, and the Köppen–Geiger 1991–2020 0.1° map
  (Beck et al. 2023) in `vic_global/01oc_natural/…`. They enter the project
  with decisions D01 and D04.

**Outputs.** `workdir/analysis/landuse-harmonization-annual/`:
`check_15crops_consistency.json`, `union_15crops.npz`,
`compare_paddy_2021.json`, `union_backfill_paddy.json` and `_fields.npz`,
`annual_harmonize_prototype_15crops.json` and `_union.npz`,
`order_sensitivity.json`, `figures/p01…p06`, `logs/`; and `trial-2021/`,
the first converter trial (histsoc 2021) produced 2026-09-23 from the legacy
layout: `coverage_ISIMIP4b_histsoc_2021.nc`, `ledger_histsoc_2021.csv`,
`qa_histsoc_2021.json`, `verify_histsoc_2021.{json,png}`, run logs. The trial
is evidence for D04, not a forcing unit.

**Code.** `check_15crops_consistency.py`, `compare_paddy_2021.py`,
`union_backfill_paddy.py`, `annual_harmonize_prototype_15crops.py`,
`order_sensitivity.py`. Runtimes 1–9 min each, up to 5 GB memory.

**Conclusion.** Recorded so far only in the legacy plan
`vic_global/isimip4b/02Audit/VICWUR_ISIMIP4b_annual_landuse_harmonization_plan_15crops_2026-09-23.md`
(Chinese, not adopted). Re-audit in English pending. Decisions still open
from it are listed as D04 in `docs/decisions/open-decisions.md`.
