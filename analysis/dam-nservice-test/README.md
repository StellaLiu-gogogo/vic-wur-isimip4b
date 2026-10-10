# dam-nservice-test

**Question.** For open decision D19 (dam parameters): does VIC-WUR `39e21ff5` run with global dams whose
`Nservice` is 0 and whose service map is empty, and do these dams then operate without demand (planned release
from the mean inflow, Hanasaki et al. 2006)? The dam parameters planned for D19 give `Nservice = 0` to the ISIMIP4b
SSP future hydropower dams (forced global) and to global dams without an irrigation or water-supply purpose.

**Classification.** Analysis; proposed by the agent and confirmed by the user on 2026-10-10. Reason: a test of
model behaviour; no workflow stage reads its products.

**Status.** `closed` (2026-10-10): the question is answered; the result is recorded in D19.

**Contract exception (user, 2026-10-10).** The two VIC runs of this test are not campaign runs: the renderer of
`workflow/05_simulation` accepts only parameter files of a parameter set, and workflow code must not read from
`analysis/`. They are therefore kept under `workdir/analysis/dam-nservice-test/runs/<control|test>/`
(`config/`, `logs/`, `output/`, `run_record.yaml`), not under `runs/<campaign-id>/`. Their VIC files are derived
from the rendered configuration of the smoke run 2011–2020; their Slurm jobs are kept as job records in
`logs/run-<label>_<slurm-job-id>/`. No end state is written.

**Inputs** (read-only; paths relative to `$ISIMIP4B_WORKDIR` unless absolute).

- Dam file of the candidate parameter set:
  `parameters/candidates/vic-global-5arcmin-version-a/dams/vic_global_5min_dam_parameters_t3-extended-merged.nc`.
- GDW purposes of its dams: the unmerged T3_extended tables of `vic_parameter`
  (`/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter/candidates/dams/dam_parameter_candidate_v1/T3_extended/{global,local}Dams.csv`,
  fields `USE_*` and `MAIN_USE`).
- Configuration and forcing view of `runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2011-2020/`.
- Initial state: `runs/smoke/ec-earth3-esm-1-1_historical_histsoc_default_historical__smoke2015/states/state.20160101_00000.nc`
  (dated 2016-01-01, the start of the test runs; same model commit, executable and parameter files; same dam list and
  order, so the dam state is compatible).
- Build `builds/vic/39e21ff5015d01d9bc20407a8f50006831417aff/` and `configs/resources/vic-global-5arcmin.yaml`.

**Method.**

1. Test dam file: a copy of the candidate dam file in which every global dam whose GDW records (same 5′ cell and
   type) give a known purpose without irrigation or water supply (`USE_IRRI` and `USE_SUPP` empty, `MAIN_USE` not
   `Irrigation` or `Water supply`) gets `Nservice = 0` and an empty `service`/`service_fraction` slice. Local dams
   are not changed (they supply their own cell whatever `Nservice` is). All other variables are checked to be
   unchanged.
2. Two runs of 2016 from the same state: `control` (candidate dam file) and `test` (test dam file). Global dams start
   operating in 2016 at their operation month (they were not active at the end of the cold-started 2015 run).
3. Checks: VIC finishes without errors or service warnings; the `Nservice = 0` dams have zero demand and a planned
   release that hardly varies between months; daily storage balance of these dams; change of discharge (annual
   mean, lowest month) and of withdrawals against the control.

**Code.** `nservice_test.py`:

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python analysis/dam-nservice-test/nservice_test.py prepare --submit   # test dam file and run directories
python analysis/dam-nservice-test/nservice_test.py submit-runs        # the two VIC runs (one node each)
python analysis/dam-nservice-test/nservice_test.py check --submit     # tables and figures
```

**Outputs.** `workdir/analysis/dam-nservice-test/`:

- `inputs/`: `dam_parameters_nservice-zero.nc` (test file, not a parameter-set file), `dam_selection.csv` (every dam
  with its purpose category), `inputs.yaml` (checksums).
- `runs/control/`, `runs/test/`: VIC configuration, logs, output (daily discharge and global-dam variables, monthly
  discharge, local-dam and water-use variables), `run_record.yaml`.
- `tables/`: `checks.csv`, `selected_dams_operation.csv`, `discharge_change_largest.csv`.
- `figures/`: `release_examples.png`, `op_release_flatness.png`, `discharge_change_map.png`.
- `logs/<step>_<slurm-job-id>/`: job records of `prepare`, `check` and the runs.

**Conclusion.** VIC-WUR `39e21ff5` runs with `Nservice = 0` (runs 2016, jobs 43284902 control and 43284903 test,
about 50 min each; check job 43287012): both runs ended with exit code 0, no `[ERROR]` line and no service
warning; the 1 301 global dams (3 103 km³) with `Nservice = 0` all operated, registered zero demand (1 254 of them
have demand in the control) and closed their daily storage balance within 0.015 hm³. In this one-year test their
planned release still follows the demand history restored from the 2015 state (up to five years of history are
averaged), so the planned release barely differs from the control; the effect of `Nservice = 0` builds up as the
history is renewed and is complete in runs started from a spin-up with the same dam file. Discharge changed by
more than 1 % of the annual mean in 720 cells (> 1 m³/s) and the global withdrawal by 0.006 %. Side finding: some
large dams receive almost no inflow (Ust-Ilim, Brokopondo below 1 hm³/day) because the dam file was snapped on the
old WBT routing. Recorded in the context of D19 in `docs/decisions/open-decisions.md` (2026-10-10).
