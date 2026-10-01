# Workflow

The end-to-end path from ISIMIP4b input data on DKRZ to VIC-WUR products
delivered to ISIMIP, and where the project stands on it. Directory rules are
in `directory-contracts.md`, terms in `glossary.md`, pending choices in
`decisions/open-decisions.md`. The eight stage directories under
`workflow/` implement the steps below; each has a README with inputs,
outputs, and completion criteria.

## 1. Scientific chain

VIC-WUR runs at 5 arcmin; ISIMIP provides inputs at 0.5° (climate) and 15′
(land use) and expects outputs at 0.5°. Every ISIMIP experiment is a chain
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

| Stage | What it does | Reads | Writes | State on 2026-09-30 |
|---|---|---|---|---|
| `01_acquisition` | inventory the DKRZ tree, choose batches, rsync with size and md5 verification, record manifests | DKRZ levante | `raw/ISIMIP4b/`, `manifests/inputs/`, `logs/01_acquisition/` | **done for EC-Earth3-ESM-1-1** (899 files, 1.39 TB, manifest `isimip4b-dkrz-2026-09-21`); UKESM1-3-LL and tasmin/tasmax/prsn not transferred (batches 5–6 need approval) |
| `02_preprocessing` | reusable caches shared by later stages (regridding weights, mask alignment, subsets) | `raw/` | `intermediate/<stage>/<cache-id>/` | nothing yet; `workflow/common/cache.py` not written |
| `03_parameters` | VIC parameter set: domain, soil, vegetation (with the full union of land-use tiles over all scenarios and parameter backfill for new tiles, D04), routing, dams, irrigation, water use | `raw/`, `intermediate/`, adopted sets from `vic_parameter` | `parameters/candidates/<set>/`, `manifests/parameters/`, `qc/parameters/` | candidate `vic-global-5arcmin-version-a` holds the adopted domain and the natural static parameter bundle (VIC-14 vegetation; its `elev` is the climate-forcing target elevation); land-use vegetation with the full tile union deferred until D01 is frozen; no generation code yet |
| `04_forcing` | climate: unit conversion, N→S orientation, masking, 0.5° → 5′ downscaling with elevation correction for the 7 VIC variables; land use: ISIMIP 15′ fractions → 5′ 16-class annual coverage; water use: non-irrigation demand | `raw/`, `raw/external/`, `parameters/` | `forcing/<family>/…/provenance.yaml`, `qc/forcing/` | land-use converter implemented and tested (method 1.2, D04), no unit produced yet; climate producer and verifier implemented (method 1.0, ERA5 orography reference, `lwdown` scratch-only until D16), 2011–2020 `esm-hist` units pending; water use blocked by D05 |
| `05_simulation` | build VIC at the locked commit; resolve a campaign into segments from the protocol definitions; render VIC and Slurm files; submit with dependencies; record run manifests | `configs/`, `model/vic.lock.yaml`, `parameters/`, `forcing/`, `raw/external/isimip-protocol-4/` | `builds/`, `runs/<campaign>/<run-id>/` | nothing yet; VIC version provisional (D01); first campaign is `smoke` |
| `06_postprocessing` | aggregate 5′ output to the 0.5° ISIMIP grid (D07), derive protocol variables, split files per variable and period, name per protocol (D09, D10) | `runs/` | `postprocessed/<product-set>/`, `qc/postprocessed/` | nothing yet |
| `07_quality_control` | ISIMIP QC tool checks plus project checks on inputs, forcing, runs, products | any workdir object | `qc/<object path>/summary.json` | input QA of 2026-09-21 recorded under `qc/raw/ISIMIP4b/InputData/`; no code yet |
| `08_delivery` | assemble accepted products, inventory, checksums, delivery manifest, upload to DKRZ | `postprocessed/`, `qc/` | `delivery/<id>/`, `manifests/deliveries/` | nothing yet |

## 3. Order of work

1. **Smoke campaign** (`configs/campaigns/smoke.yaml`): one GCM, one short
   segment on a small domain or one year globally, to exercise build →
   forcing → run → postprocessing → QC end to end. Needs: a VIC build at the
   provisional commit, climate forcing for one decade
   (EC-Earth `esm-hist` 2011–2020 is already on disk), the land-use unit
   `histsoc`, and the adopted parameter set with its vegetation bundle.
2. **Freeze the model version** (D01) and the parameter set; promote them to
   `production/`.
3. **Fast Track campaign** (`fasttrack`): the first-priority `water_global`
   experiments for EC-Earth3-ESM-1-1 (compute scope D02, output storage D03).
4. **Second GCM** (UKESM1-3-LL): transfer batch 5, repeat forcing and runs.
5. **Postprocessing, QC, delivery** once the output filename pattern (D09)
   and model name (D10) are settled.

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
