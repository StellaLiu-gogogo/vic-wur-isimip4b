# Workflow

The end-to-end path from ISIMIP4b input data on DKRZ to VIC-WUR products
delivered to ISIMIP, and where the project stands on it. Directory rules are
in `directory-contracts.md`, terms in `glossary.md`, pending choices in
`decisions/open-decisions.md`. The eight stage directories under
`workflow/` implement the steps below; each has a README with inputs,
outputs, and completion criteria.

## 1. Scientific chain

VIC-WUR runs at 5 arcmin; ISIMIP provides inputs at 0.5° (climate) and 15′
(land use) and expects outputs at 0.5°. The model is the standalone VIC-WUR
image driver, GWM FALSE, not coupled to MODFLOW. Every ISIMIP experiment is a chain
of segments (`glossary.md`): a spin-up, a pre-industrial control period
(1601–1849), a historical period (1850–2021), and a future period
(2022–2100), each with its own climate and direct-human-forcing scenario.
Segments shared between experiments are simulated once per GCM and campaign;
each segment starts from the end state of its parent.

```
DKRZ ISIMIP4b inputs ──01──▶ raw/ISIMIP4b ──02──▶ intermediate caches
                                  │
                                  ├──03──▶ parameters (domain, soil, vegetation incl. full-union land-use tiles, routing, dams)
                                  │
                                  └──04──▶ forcing/climate (7 variables, 0.5° → 5′, per GCM and input scenario)
                                           forcing/landuse (16-class annual coverage per soc scenario)
                                           forcing/water_use (non-irrigation demand; dataset not yet released, D05)
                                                    │
        campaign (configs/campaigns) ──05──▶ builds/vic/<commit> ; runs/<campaign>/<segment-id>/ (spin-up → pre-industrial → historical → future)
                                                    │
                                           ──06──▶ postprocessed/<product-set> (5′ → 0.5°, ISIMIP variable names and filenames)
                                                    │
                                           ──07──▶ qc/ (structural, protocol, scientific checks; statuses passed/failed/warning/not_checked)
                                                    │
                                           ──08──▶ delivery/<delivery-id> → upload to DKRZ
```

## 2. Stages

| Stage | What it does | Reads | Writes | State on 2026-10-28 |
|---|---|---|---|---|
| `01_acquisition` | inventory the DKRZ tree, choose batches, rsync with size and md5 verification, record manifests | DKRZ levante | `raw/ISIMIP4b/`, `manifests/inputs/`, `logs/01_acquisition/` | **done for EC-Earth3-ESM-1-1** (899 files, 1.39 TB, manifest `isimip4b-dkrz-2026-09-21`); UKESM1-3-LL and tasmin/tasmax/prsn not transferred (batches 5–6 need approval; D02 covers EC-Earth only for now). External datasets under `raw/external/`: `isimip3-water-abstraction` and `watergap-groundwater-fractions` (D05, 2026-10-02), `global-dam-watch` 1.0 (D19, task L1), `grdc` station export (run checks), `koppen-geiger`, `era5-surface-geopotential`, `vic-coverage-version-a`, `isimip-protocol-4`. `transfer_batch.sh` stages, verifies and then moves files (review fix of 2026-10-07) |
| `02_preprocessing` | reusable caches shared by later stages (regridding weights, mask alignment, subsets) | `raw/` | `intermediate/<stage>/<cache-id>/` | nothing yet; `workflow/common/cache.py` not written; `workflow/common/` holds the modules shared by the stages since 2026-10-05 (workdir, checksums, Git state, `provenance.yaml`, QC status and verifier exit status, Slurm job records, unit-extension rules; tasks G and O1), used by `03_parameters` and `04_forcing` |
| `03_parameters` | VIC parameter set: domain, soil, vegetation (with the full union of land-use tiles over all scenarios and parameter backfill for new tiles, D04), routing, dams (one dam list, one file per DHF scenario, D19), irrigation, water use | `raw/`, `raw/external/`, adopted sets from `vic_parameter`, the natural run of `05_simulation` (dam service maps) | `parameters/candidates/<set>/`, `manifests/parameters/`, `qc/parameters/` | candidate `vic-global-5arcmin-version-a`, seven components: adopted domain, natural static bundle and 16-class Version A bundle; `vegetation/` 16-class component with the full tile union (2026-10-02, `qc_status: passed`); `bundle/` assembled 16-class image-driver file (2026-10-04, passed); adopted routing (FILE decomposition, 128 groups), irrigation, water-use receiving network and domain, all `qc_status: passed` since 2026-10-24 (task R: verifiers in `domain/`, `routing/`, `irrigation/`, `water_use/`; the decomposition file is not covered); adopted dams T3_extended `not_checked` (to be replaced by the dam component). `dams/` (task L2, 2026-10-16): producer and verifier for the D19 dam list (ISIMIP4b `histsoc` dams located with GDW v1.0 plus the SSP future dams, snapped on the parameter-set routing, construction years per DHF scenario, rebuilt FILE decomposition) written but **not yet run**; it needs the natural run of task Q for the service maps. D01 decided 2026-10-28 (VIC `39e21ff5` frozen); the parameter set is promoted to `production/` after the dam component and the remaining QC |
| `04_forcing` | climate: unit conversion, N→S orientation, masking, 0.5° → 5′ downscaling with elevation correction for the 7 VIC variables, start years of spin-ups copied from their cycle year (D20); land use: ISIMIP 15′ fractions → 5′ 16-class annual coverage; water use: non-irrigation demand from the ISIMIP3a/3b series (D05); start years of runs outside a constant scenario's years (D20) | `raw/`, `raw/external/`, `parameters/` | `forcing/<family>/…/provenance.yaml`, `qc/forcing/` | all units `qc.status: passed`. Climate (method 1.1, D16): EC-Earth3-ESM-1-1 `esm-hist` 1850–2021, 7 variables, 172 files each (completed 2026-10-16); `esm-picontrol` 1601–1849 with the start years 1551, 1576 and 1591 (tasks P1, P2, P5); `esm-scen7-vl` and `esm-scen7-h` 2022–2100 (task P5, 2026-10-26). Running: `esm-picontrol` 1850–2100 (task P5, job 43440164, 2026-10-28); with it every climate year of the D02 scope of EC-Earth3-ESM-1-1 exists. The verifier accepts `lwdown` up to 650 W m-2 (`20a59d4`). Land use (method 1.4) and water use (method 1.0): five soc scenarios each; `1850soc` 1551–2022 and `2021soc` 1800–2100 include the D20 start years (task O4, 2026-10-20); `histsoc` 1850–2021, SSP units 2022–2100 |
| `05_simulation` | build VIC at the locked commit; resolve a campaign into segments (spin-up blocks, chunks); render VIC and Slurm files with the per-run forcing view (constant and cycle rules, start years) and the dam file of the segment's DHF scenario; submit with dependencies; record run manifests; run checks | `configs/`, `model/vic.lock.yaml`, `parameters/`, `forcing/`, `raw/external/isimip-protocol-4/`, `raw/external/grdc/` | `builds/`, `runs/<campaign>/<run-id>/`, `qc/runs/` | candidate build of `39e21ff5` (2026-09-30); D01 froze this commit on 2026-10-28, a production build is still to be made. Machinery: resolver (22 segments for the 16 experiments of D02 per GCM, spin-up continuation blocks until the D19 convergence test passes), renderer (year-named forcing links, dam file per scenario and D19 warm-start checks, chunked runs of `chunk_years`, spin-up monthly output), submit with run lock and manifest, `monitor/` run checks (coverage, water balance, GRDC discharge, water-use budget, non-renewable deficit) and run comparison. Campaigns (all non-production): `smoke` 2015 and 2011–2020 (completed 2026-10-05, 233 core-hours per year including setup, 146 in long runs), `smoke-nonrenewable` 2011–2020, `chunk-test` (continuous and chunked 2015–2016 identical), `natural-spinup` 1591–1600 (completed), `natural-run` 1850–2021 in 20-year chunks (routing and land use only; **running since 2026-10-23**, input of the dam service maps). Fixes of the code reviews of 2026-10-05 and 2026-10-07 applied (tasks H, I, K). D01 decided 2026-10-28, D02 and D03 2026-10-22; D06 open. Not yet implemented: one climate window per spin-up chain (D19 amendment of 2026-10-22) and the extra daily outputs of D03 in the historical and future periods |
| `06_postprocessing` | aggregate 5′ output to the 0.5° ISIMIP grid (D07), derive protocol variables, split files per variable and period, name per protocol (D09, D10) | `runs/` | `postprocessed/<product-set>/`, `qc/postprocessed/` | nothing yet; D07, D09, D10, D11 open |
| `07_quality_control` | ISIMIP QC tool checks plus project checks on inputs, forcing, runs, products | any workdir object | `qc/<object path>/summary.json` | input QA of 2026-09-21 under `qc/raw/`; per-object checks live with their producers (forcing verifiers, parameter verifiers, run checks); no central code yet |
| `08_delivery` | assemble accepted products, inventory, checksums, delivery manifest, upload to DKRZ | `postprocessed/`, `qc/` | `delivery/<id>/`, `manifests/deliveries/` | nothing yet |

## 3. Order of work

1. **Smoke campaign** — done (2026-10-05): build → forcing → run → run checks
   for `esm-hist` 2015 and 2011–2020; postprocessing and QC were not part of
   it (no code yet).
2. **Inputs of the production chain** — in progress:
   - natural run 1850–2021 (campaign `natural-run`, task Q, running) → dam
     component run (task L3: dam list, per-scenario dam files, rebuilt FILE
     decomposition; re-check routing and water-use components against the new
     decomposition);
   - climate of the D02 scope (task P5): `esm-picontrol` 1551–1849 and the
     `vl` and `h` futures 2022–2100 done; `esm-picontrol` 1850–2100 running
     (2026-10-28);
   - QC evidence for the adopted components: done 2026-10-24 (task R); the
     decomposition file is checked once the dam component rebuilds it.
3. **Model version** frozen (D01, 2026-10-28: `39e21ff5`); make the
   production build; promote the parameter set to `production/`; decide D06
   (`extrasoc`) or record it as outside the scope; implement one climate
   window per spin-up chain (D19 amendment) and the period-dependent daily
   outputs of D03.
4. **Production spin-ups** (two chains per D19: `1850soc` on `picontrol`
   1601–1650, `2021soc` on `picontrol` 1800–1849; 50-year block and 25-year
   continuation blocks until the convergence test passes).
5. **Production campaign** for EC-Earth3-ESM-1-1 (D02: 16 experiments,
   22 segments, 2 408 model years; D03: all 5′ output kept), longest chain
   first; a code review of `05_simulation` to `07_quality_control` before the
   first production job.
6. **Postprocessing, QC, delivery** (D07, D09, D10, D11): built beside step 5
   on the smoke and natural-run output; delivery once the ISIMIP filename
   pattern and the model name are settled.
7. **Second GCM** (UKESM1-3-LL): amendment of D02, transfer batch 5, forcing
   and runs; storage permitting (`/lustre` 96 % full, 159 TB free on 2026-10-28).

## 4. Cross-cutting rules that every stage follows

- Accepted outputs (caches, forcing units, parameter sets, runs, products,
  deliveries) are produced only from a clean repository and record the
  commit (`directory-contracts.md`, rule 14); the land-use converter shows
  the pattern (`provenance.yaml`, scratch fallback when not clean).
- Every Slurm job of stages other than `05_simulation` keeps its job record
  under `logs/<stage>/<job-name>_<slurm-job-id>/`; simulation jobs live with
  their run.
- Caches under `intermediate/` are written only by the common cache writer
  (to be implemented in `workflow/common/cache.py`).
- A stage does not start production work while a decision due at or before
  it is open (`decisions/open-decisions.md`); the layout check warns.
- Backups of accepted objects follow `directory-contracts.md`, "Data
  protection" (not yet operational).

## 5. History

The project was set up on 2026-09-24 to 2026-09-30 as a clean-room
implementation; the earlier audit and exploration area
`vic_global/isimip4b/` is frozen as an archive and its useful content was
migrated (`decisions/D15-legacy-migration.md`). The Chinese audit reports
there are not adopted and are re-audited in English when needed.
