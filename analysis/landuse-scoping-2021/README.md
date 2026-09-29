# landuse-scoping-2021

**Question.** How far do the ISIMIP4b land-use maps (histsoc 2021, the
fixed-soc and SSP scenarios) and the VIC-WUR 5′ land-cover dataset agree at
15′, how many VIC tiles would a full union of all scenarios add, and which
parameter fields such tiles lack?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** closed (2026-09-21). Code migrated as-is: it contains paths of
the legacy layout (`vic_global/isimip4b/03Data/raw_dkrz/…`,
`vic_global/vic_parameter/…`) and is not runnable without editing.

**Inputs (legacy paths).** ISIMIP4b `landuse-*_15arcmin` files (now under
`raw/ISIMIP4b/InputData/socioeconomic/landuse/`), VIC coverage
`coverage_VersionA_v5_2021.nc` (now `raw/external/vic-coverage-version-a/5/`),
the VIC vegetation bundle and `veghist` in `vic_parameter` (not in this
project).

**Outputs.** `workdir/analysis/landuse-scoping-2021/`: `compare_2021.json`,
`extra_2021.json`, `extra_union.json`, `union_analysis.json`,
`union_completeness.json`, `vic_side_stats.json`, five PNG maps,
`veghist_bundle_fill_check_2026-09-21.txt`.

**Code.** `vic_side_stats.py`, `compare_2021.py`, `extra_2021.py`,
`union_analysis.py`, `extra_union.py`, `union_completeness.py`.

**Conclusion.** Recorded so far only in the legacy reports
`VICWUR_ISIMIP4b_landuse_scoping_GroupII_GroupIII_v2_2026-09-21.md` and
`VICWUR_ISIMIP4b_fullunion_vegparam_adaptation_audit_2026-09-21.md` under
`vic_global/isimip4b/02Audit/` (Chinese, not adopted). Re-audit in English
pending. Feeds decision D04.
