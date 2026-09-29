# protocol-audit-2026-09

**Question.** What does the ISIMIP4b Fast Track protocol (sector
`water_global`) require from VIC-WUR, which input data exist on DKRZ, and
which questions remain open for the sector coordinators?

**Classification.** Analysis; user decision 2026-09-29 (migration D15).

**Status.** closed. The evidence was collected 2026-09-18 against protocol
commit `4a51211054a5a90444ca87664d1f29b2abb5bc38`.

**Inputs.** The ISIMIP protocol repository (now
`raw/external/isimip-protocol-4/f9be7b0…/`), the DKRZ tree
`/work/bb0820/ISIMIP/ISIMIP4b/InputData/`, and the ISIMIP4b start email.

**Outputs.** `workdir/analysis/protocol-audit-2026-09/`: extracted protocol
definitions (`*.yaml`, `02.experiments.md`, `03.input.md`), the DKRZ listing
(`DKRZ_ISIMIP4b_InputData_listing_2026-09-18.txt`), the land-use soc
consistency check, the protocol website index, and the extracted start
email. No code: the extracts were made by hand and with `ssh levante`
listings.

**Conclusion.** Recorded so far only in the legacy report
`vic_global/isimip4b/02Audit/ISIMIP4b_WaterGlobal_protocol_audit_2026-09-18.md`
(Chinese, not adopted). Re-audit in English pending. The durable outcomes are
in `docs/glossary.md` (experiments, specifiers, periods, open questions) and
`docs/decisions/open-decisions.md` (D05, D06, D09, D12).
