# compute-storage-plan

## Question

How much compute, wall-clock time and storage do the ISIMIP4b `water_global`
campaigns need on Anunna (per GCM and for EC-Earth3-ESM-1-1 plus
UKESM1-3-LL), which options reduce the demand and by how much, and which
compute scope (D02) and storage rule for the 5′ output (D03) follow from
that?

## Classification

Analysis (user, 2026-10-05): the product is a report with tables and figures
that supports decisions D02 and D03; no workflow stage reads it. The code
imports the campaign resolver
`workflow/05_simulation/render/resolve_campaign.py` to count segments and
years (allowed direction: analysis reads workflow, never the reverse).

## Status

open (report written 2026-10-05, updated 2026-10-06 with the completed smoke
run 2011–2020 and its store drift; D02 and D03 are with the user).

## Inputs (read-only, relative to the workdir)

- `runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2015/`
  and `…__smoke2011-2020/`: `run_manifest.json`, `logs/slurm-<job>.out`,
  the output and state files. Times come from the VIC timing table and the
  creation and last-write times of the files. Sizes come from the files.
- `raw/external/isimip-protocol-4/f9be7b0…/definitions/` (experiments,
  periods, variables) through the resolver;
  `configs/campaigns/smoke.yaml` (output mapping, base campaign) and
  `configs/resources/vic-global-5arcmin.yaml` (memory request).
- `forcing/climate/ec-earth3-esm-1-1/esm-hist/`, `forcing/landuse/`,
  `forcing/water_use/`, and
  `raw/ISIMIP4b/InputData/climate/atmosphere/bias-adjusted/global/daily/`:
  file sizes only.
- `logs/04_forcing/climate-forcing-*/` (producer speed).
- `../../deliverables/vic_natural_production_41yr_20260907/vic_natural_gwmFALSE_monthly_1979-2019_5arcmin_v1.nc`
  (relative to the workdir; the sibling project's natural run, WFDE5, VIC `e083c9f3`; read only by
  `snow_compare.py`, as a stand-in for the H line, whose monthly output is only on Snellius scratch).
- Cluster state from `sinfo`, `scontrol`, `sshare` at run time; tariffs
  and policies from wiki.anunna.wur.nl (read 2026-10-05, constants in
  `plan.py`).
- Spin-up evidence of the sibling project:
  `/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/docs/`
  (`HumanImpact_Hline_spinup执行与收敛_20260902.md`,
  `HumanImpact_生产41年验收_20260906.md`,
  `Natural_双轨spinup结果_v2_20260901.md`). These are cited in the report
  and not read by the code.

## Code

| File | Role |
|---|---|
| `csp.py` | paths, the measured runs |
| `measure_files.py` | per-variable storage (`h5ls -v`) of the smoke 2015 files. Compression, precision and chunking tests run on copies in `scratch/compute-storage-plan/` (netCDF4 samples, `nccopy` on whole files) and never touch `runs/` |
| `spinup_drift.py` | drift of the water stores (soil layers, snow, river, reservoirs) in the 10-year smoke run after its cold start, for the spin-up length; where snow builds up every year |
| `snow_compare.py` | snow that builds up every year: the smoke run against the sibling project's natural 41-year run (WFDE5) on the same cells; December SWE, air temperature and precipitation that VIC read, elevation test |
| `plan.py` | segments and model years from the resolver, speed and sizes from the run records, demand per selection and GCM count, options, scenarios (job schedule on N nodes, storage over time), figures |
| `report.py` | writes `report.md` from the results of `plan.py` |
| `submit.py` | Slurm job of one step; job record in `logs/<step>_<job-id>/` |

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/compute-storage-plan/submit.py --step measure   # once; about 4.5 h (state zlib 9 alone 2.2 h)
python3 analysis/compute-storage-plan/submit.py --step drift --cpus 2 --mem 32G --time 01:00:00   # about 5 min
python3 analysis/compute-storage-plan/submit.py --step snowcmp --cpus 2 --mem 48G --time 03:00:00   # about 15 min
python3 analysis/compute-storage-plan/submit.py --step plan --cpus 2 --mem 16G --time 01:00:00
```

The planning parameters are options of `plan.py`: `--spinup-years`
(default 50), `--start`, `--nodes`, `--queue-wait-hours` and
`--second-gcm-offset-days`. Assumptions that no record settles are
constants at the top of `plan.py` and are listed in the report.

## Outputs

`workdir/analysis/compute-storage-plan/`:

- `report.md`;
- `figures/storage_over_time.png`, `figures/critical_path_gantt.png` and
  `figures/spinup_drift.png`, `figures/snow_compare.png`;
- `tables/*.csv`: demand, segments per selection, model-year timing,
  output by variable, compression tests, options, scenarios, schedules,
  storage timelines;
- `tables/inputs.json`;
- `logs/`.

## Conclusion

See `report.md`. Proposed for D02: all experiments except `extrasoc`
(D06) for both GCMs, with EC-Earth3-ESM-1-1 first and the 1st-priority
segments first, and 50-year spin-ups with a convergence test. Proposed for
D03: protocol-daily output only; keep states, 5′ monthly output and run
records; delete the 5′ daily output once its 0.5° products have passed QC.
The maintained record will be the D02 and D03 decision records under
`docs/decisions/` once the user decides.
