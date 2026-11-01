# D06 — Composition of the `extrasoc` sensitivity experiments

Status: **decided 2026-11-01** by the user (option B).
Due stage: `05_simulation`.

## Context

The ISIMIP4b `water_global` protocol (commit `f9be7b0`) has two Group III
sensitivity experiments, `vl_ssp1vlsoc-noadapt_extrasoc` and
`h_ssp3hsoc-noadapt_extrasoc`, both 2nd priority. Their pre-industrial and
historical segments are identical to the `default` experiments; only the
future segment (2022–2100) differs. The protocol asks the modelling teams to
run the `default` Group III experiments first, with land use, irrigation and
non-irrigation water use, and then to choose themselves which direct human
forcings the `extrasoc` experiment adds on top (hydropower dams, inter-basin
water transfer and desalination are the protocol's examples); it encourages
coordination with the sector coordinators.

For VIC-WUR the choice is narrower than the protocol suggests:

- The `default` production runs already include the ISIMIP4b historical dams
  and non-renewable withdrawal (D19, campaign
  `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`): in VIC-WUR dam
  supply is part of the water-use plugin, so the dams are not switched off in
  the `default` runs.
- The frozen model (D01, `a826251b`) has no inter-basin transfer and no
  desalination. The only additional forcing it can represent is the set of
  ISIMIP4b SSP future hydropower dams (WaterGAP2-2e: `ssp1vlsoc-noadapt`
  1 758 dams, 942 km³; `ssp3hsoc-noadapt` 2 855 dams, 2 151 km³), which D19
  already placed in the dam list with construction year 9999 (never) in every
  dam file of today.

D02 excluded the two `extrasoc` experiments from the production scope until
this decision (16 experiments, 22 segments, 2 408 model years).

## Options

| Option | Content | Cost | Assessment |
|---|---|---|---|
| A | `extrasoc` = `default` plus the SSP future hydropower dams operating from their construction year | two future segments (158 model years, about 100 h wall time each at the measured speed, about 4 TB of output); two dam files for the SSP scenarios, their QC and manifest entries, the campaign and a small renderer change (dam file chosen by soc scenario and sensitivity) | prepared by D19; the 29 flagged future dams (487 km³, e.g. 289 km³ in Tibet, 275 km³ on the Niger) would need a capacity rule |
| B | `extrasoc` is not simulated; VIC-WUR reports the `default` experiments only | none | the `default` runs already carry the historical dams, so the sensitivity experiment would add only the uncertain SSP future dams; 2nd priority |
| C | leave the composition open and make D06 a triggered decision (due when `extrasoc` segments are added to a campaign) | none | same effect as B for the campaign, without a decision on the content |

## Decision

**Option B** (user, 2026-11-01): the `extrasoc` experiments are not
simulated and not reported. The production scope stays as D02 decision 2:
16 experiments, 22 segments. The SSP future dams stay in the dam list with
construction year 9999 in every dam file (D19); no `extrasoc` dam files are
made.

The decision can be amended (for example after an exchange with the sector
coordinators): option A then adds two future segments that start from the
kept end state of the historical `histsoc` segment, as D02 foresaw.

## Consequences

- `configs/campaigns/water-global-ec-earth3-esm-1-1.yaml`: the two
  `exclusions` stay, with this decision as their reason.
- `workflow/03_parameters/dams/`: no `extrasoc` dam files; the README notes
  of that directory say so (its QC reports are not bound to the directory
  tree, so the edit changes no QC status).
- D19's year table row for the SSP units ("follow their construction year
  where they operate (`extrasoc`, D06)") is not used.
- `05_simulation` has no open decision due at or before it; the production
  campaign may be rendered once the remaining preparation (task W start years,
  code review, D13 backup) is done.
- Reporting: the `extrasoc` experiments are absent from the deliveries;
  D12 (`2021co2`) is unaffected.
