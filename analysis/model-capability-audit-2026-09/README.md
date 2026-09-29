# model-capability-audit-2026-09

**Question.** Can VIC-WUR at 5 arcmin deliver the ISIMIP4b `water_global`
experiments, and which capability gaps must be closed first (land-use
forcing, 5′→0.5° aggregation, non-irrigation water use, mask coverage,
cost)?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** closed. Evidence collected 2026-09-18 to 2026-09-20.

**Inputs.** VIC-WUR source and production configuration on Snellius (headers
and run scripts captured as text), the ISIMIP `water_global` land-sea mask
(`landseamask_water-global.nc`, a copy of the DKRZ file now under
`raw/ISIMIP4b/InputData/geo_conditions/landseamask/`), and the protocol
output-variable tables.

**Outputs.** `workdir/analysis/model-capability-audit-2026-09/`:
`mask_compare.npz` (VIC domain vs ISIMIP mask), `proto_*.yaml` (variable
tables), `snellius_*.txt` (configuration and output headers),
`PROTOCOL_HEAD_2026-09-20.txt`. No code.

**Conclusion.** Recorded so far only in the legacy report
`vic_global/isimip4b/02Audit/VICWUR_ISIMIP4b_WaterGlobal_model_capability_audit_v2_2026-09-20.md`
(Chinese, not adopted). Re-audit in English pending. Open decisions derived
from it: D02, D03, D07, D08 in `docs/decisions/open-decisions.md`.
