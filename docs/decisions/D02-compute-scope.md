# D02 — Compute scope

Status: **decided 2026-10-22** by the user.
Due stage: `05_simulation`.

## Context

The campaign definitions need to know which GCMs and which ISIMIP4b
`water_global` experiments are simulated, in which order, and whether the
project asks Anunna for more resources. The model capability audit had
estimated the cost against a Snellius budget; the project runs on Anunna
only. The analysis task `compute-storage-plan` (task F,
`analysis/compute-storage-plan/`, report
`workdir/analysis/compute-storage-plan/report.md`, generated 2026-10-07)
measured the cost on Anunna from the smoke runs and proposed a scope that
was never recorded until now.

## Evidence

- Speed (smoke runs 2015 and 2011–2020, full plugin stack, 8 ranks × 16
  threads on one 128-core gen3 node): 1.14 h per model year (146 core-hours),
  plus about 21 min initialisation and 26 min end-state write per Slurm job.
  The natural-run spin-up of task P (routing and land use only) took 45 min
  per model year (2026-10-21).
- Segments (protocol commit `f9be7b0`, resolver of `05_simulation`, D19
  spin-ups of 50 years): one GCM, all experiments except the two `extrasoc`
  ones, is 22 segments and 2408 model years (100 of them spin-up). The three
  `2021co2` experiments share the segments of the `default` experiments
  (VIC-WUR has no CO₂ response; reporting is D12) and cost nothing extra.

  | Selection | Experiments | Model years per GCM | Core-hours per GCM |
  |---|---|---|---|
  | all 18 | 18 | 2566 | 376k |
  | all but `extrasoc` | 16 | 2408 | 353k |
  | 1st priority | 12 | 1827 | 268k |
  | Group I and II | 12 | 2092 | 307k |

- The longest chain (`1850soc` spin-up → pre-industrial 1601–1849 →
  historical → future) is 550 model years, about 26 days; more nodes do not
  shorten it.
- Anunna: 74 gen3 1 TB nodes; billing €2.69 per node-hour (128 cores, 700 GB)
  in 2026; from 2027-01-01 internal WUR use is no longer charged to projects.
  The fair share of the `esg` account is low. The draft fair-use page says
  "keep reservations to at most three nodes"; the admins have not been asked.
- The inputs of the second ISIMIP4b GCM, UKESM1-3-LL, have not been
  transferred (no approval yet; `manifests/inputs/isimip4b-dkrz-2026-09-21/`).

## Options considered

- GCMs: EC-Earth3-ESM-1-1 only now, or both GCMs with the same scope.
- Experiments: all 18; all except `extrasoc` (D06 open); 1st priority only;
  Group I and II only.
- Order: 1st-priority segments first, or no order beyond the parent–child
  order.
- Resources: ask the Anunna admins now for continuous nodes and 40–60 TB of
  storage, or plan with what the normal queue gives.

Task F recommended all experiments except `extrasoc`, both GCMs,
EC-Earth3-ESM-1-1 first, 1st-priority segments first, on 6 nodes.

## Decision

1. **GCM.** The scope covers EC-Earth3-ESM-1-1 only. UKESM1-3-LL is decided
   by an amendment of this record when its inputs are approved and
   transferred.
2. **Experiments.** All `water_global` experiments except the two `extrasoc`
   ones (`vl_ssp1vlsoc-noadapt_extrasoc`, `h_ssp3hsoc-noadapt_extrasoc`),
   which wait for D06: 16 experiments, 22 segments, 2408 model years
   including the two 50-year spin-ups.
3. **Order.** The longest chain always goes first; among the other segments
   that are ready to start, segments of 1st-priority experiments start before
   segments used only by 2nd-priority experiments (the `1850soc` historical
   and future segments), which run beside them when nodes are free.
4. **Resources.** No request to the Anunna admins for now; the campaign uses
   the nodes the normal queue gives.

## Consequences

- Estimated duration for EC-Earth3-ESM-1-1 with the output of D03 (extra
  daily variables in the historical and future segments, about 1.4 h per
  model year there), jobs of at most 20 model years (`chunk_years: 20`), no
  queue waits and no extra spin-up blocks: about 430k core-hours (about €9k at
  the 2026 tariff, none for the part run from 2027).

  | Nodes in use | All segments done | 1st-priority segments done |
  |---|---|---|
  | 2 | 71 days | 53 days |
  | 3 | 52 days | 37 days |
  | 4 | 42 days | 34 days |
  | 6 | 36 days | 31 days |

  Each 25-year continuation block of a spin-up that fails the convergence
  test (D19) adds about 1.2 days to its chain. Queue waits come on top.
- The production campaign under `configs/campaigns/` selects these 16
  experiments for `ec-earth3-esm-1-1`; the `extrasoc` experiments are added
  when D06 is decided and start from the kept end state of the historical
  `histsoc` segment.
- Submission order follows decision 3; the renderer and submit scripts need
  no scope logic beyond the experiment selection.
- `configs/resources/vic-global-5arcmin.yaml` still plans 3.0 h per model
  year; it should be updated from the measured speed before production (not
  part of this decision).
- If the queue does not give enough nodes, or storage becomes short (D03),
  the request to the admins is reconsidered; the open questions are listed in
  section 4 of the task F report.
- The analysis task `compute-storage-plan` is closed for D02; its report stays
  the evidence.
