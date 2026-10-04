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

| Stage | What it does | Reads | Writes | State on 2026-10-04 |
|---|---|---|---|---|
| `01_acquisition` | inventory the DKRZ tree, choose batches, rsync with size and md5 verification, record manifests | DKRZ levante | `raw/ISIMIP4b/`, `manifests/inputs/`, `logs/01_acquisition/` | **done for EC-Earth3-ESM-1-1** (899 files, 1.39 TB, manifest `isimip4b-dkrz-2026-09-21`); UKESM1-3-LL and tasmin/tasmax/prsn not transferred (batches 5–6 need approval); external datasets for D05 acquired 2026-10-02: `isimip3-water-abstraction` (`dkrz-2026-10-02`, 52 files, 5.36 GB, md5 against levante and sha512 against data.isimip.org verified) and `watergap-groundwater-fractions` (`snapshot-2026-10-02`, 4 tables, provenance to be confirmed) |
| `02_preprocessing` | reusable caches shared by later stages (regridding weights, mask alignment, subsets) | `raw/` | `intermediate/<stage>/<cache-id>/` | nothing yet; `workflow/common/cache.py` not written |
| `03_parameters` | VIC parameter set: domain, soil, vegetation (with the full union of land-use tiles over all scenarios and parameter backfill for new tiles, D04), routing, dams, irrigation, water use | `raw/`, `intermediate/`, adopted sets from `vic_parameter` | `parameters/candidates/<set>/`, `manifests/parameters/`, `qc/parameters/` | candidate `vic-global-5arcmin-version-a` holds the adopted domain, the natural static parameter bundle (VIC-14 vegetation; its `elev` is the climate-forcing target elevation) and the adopted 16-class Version A bundle (same soil, snow bands and `elev`); `vegetation/` builds the 16-class vegetation component with the full land-use tile union (D04) as a candidate under the provisional D01: produced 2026-10-02 (commit `6c7e5da`, 9 716 093 tiles of which 654 670 added and backfilled, 1.9 GB, `qc_status: passed`); `bundle/` assembles the 16-class image-driver file (soil, snow bands and `elev` of the natural bundle, vegetation of the component; producer and verifier implemented 2026-10-04); the plugin parameters (routing with the FILE decomposition of 128 groups, irrigation, dams T3_extended with two-dam cells merged, water-use receiving network) were adopted from `vic_parameter` on 2026-10-04 and checked against the plugin readers of VIC `39e21ff5` |
| `04_forcing` | climate: unit conversion, N→S orientation, masking, 0.5° → 5′ downscaling with elevation correction for the 7 VIC variables; land use: ISIMIP 15′ fractions → 5′ 16-class annual coverage; water use: non-irrigation demand | `raw/`, `raw/external/`, `parameters/` | `forcing/<family>/…/provenance.yaml`, `qc/forcing/` | land-use converter, verifier and Slurm job implemented (method 1.4, D04, time calendar `proleptic_gregorian`); units of all five soc scenarios (`histsoc`, `1850soc`, `2021soc`, `ssp1vlsoc-noadapt`, `ssp3hsoc-noadapt`, 581 yearly files, 21 GB) produced and accepted on 2026-10-03 (commit `8971bcf`, `qc.status: passed`; they replace the method 1.3 units of 2026-10-02, whose calendar `standard` would have stopped VIC, with bitwise identical coverage); climate producer and verifier implemented (method 1.1: ERA5 orography reference, `vp` capped at saturation, `lwdown` ratio correction of D16); EC-Earth3-ESM-1-1 `esm-hist` 2011–2020 units of all 7 variables produced and accepted on 2026-10-01 (commit `c88e6dc`, 133.9 GB, `qc.status: passed`); water use: D05 decided 2026-10-02, amended 2026-10-03; D1 done (data acquired and reviewed); D2 producer, verifier and Slurm job implemented (method 1.0, population-weighted split, demand in mm/day); units of all five soc scenarios (3 486 files, 7.7 GB) produced and accepted on 2026-10-04 (commit `6655b77`, `qc.status: passed`) |
| `05_simulation` | build VIC at the locked commit; resolve a campaign into segments from the protocol definitions; render VIC and Slurm files; submit with dependencies; record run manifests | `configs/`, `model/vic.lock.yaml`, `parameters/`, `forcing/`, `raw/external/isimip-protocol-4/` | `builds/`, `runs/<campaign>/<run-id>/` | candidate build of `39e21ff5` (2026-09-30); `render/` resolves a campaign into segments from the protocol (24 segments for the 18 `water_global` experiments per GCM), builds the per-run forcing view of year-named links, renders the VIC file and Slurm job; `submit/` submits on hold and keeps the run manifest; campaign `smoke` (`configs/campaigns/smoke.yaml`) defined; VIC version provisional (D01) |
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
