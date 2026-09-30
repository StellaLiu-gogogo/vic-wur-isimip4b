# 05 Simulation

## Purpose

Render complete VIC and Slurm configurations, create isolated run directories, submit VIC-WUR simulations, and record run provenance.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Inputs

- Campaign definitions under `configs/campaigns/`.
- ISIMIP experiment definitions from the protocol commit pinned by the campaign.
- Resource definitions under `configs/resources/`.
- Accepted parameters under `workdir/parameters/`.
- Accepted forcing units under `workdir/forcing/` (`provenance.yaml` with `qc.status: passed`).
- A pinned VIC-WUR version from `model/vic.lock.yaml`.
- A verified executable under `workdir/builds/`.

## Outputs

A campaign is resolved into segments by code: the segments, their periods, and their parent segments are derived from the protocol experiment definitions, never listed by hand. Each segment becomes one run.

Each run must be isolated under `workdir/runs/<campaign-id>/<run-id>/`, where `<run-id>` is the segment ID defined in `docs/glossary.md`. A run split into chunks uses `chunks/<start-year>-<end-year>/`. Each run contains at least:

- the resolved campaign and segment configuration;
- the exact VIC configuration used;
- the exact Slurm job submitted;
- a run manifest;
- logs, state files, and raw output in dedicated subdirectories.

## Build

`build/build_vic.sh` builds the image driver at the commit of
`model/vic.lock.yaml` and records it under `workdir/builds/vic/<commit>/`
with `build_manifest.json`, logs and checks (see `build/README.md`):

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
workflow/05_simulation/build/build_vic.sh            # records the build
workflow/05_simulation/build/build_vic.sh --scratch  # test run under scratch/
```

It uses the Anunna module bucket `2025` with `netCDF/4.9.3-gompi-2025a`;
jobs that run the executable must load the same modules (manifest key
`runtime_modules`). With a provisional lock (D01 open) the result is a
candidate build; its status is `built` (the VIC test suite cannot run
here, see `build/README.md`).

## Allowed content

- Run-directory creation and submission code.
- VIC configuration templates.
- Slurm job templates.
- Restart, dependency, and status-management logic.

## Forbidden content

- Generated run configurations or job files in the repository.
- Compiled executables.
- Model output or state files.
- Production runs from a repository that is not clean (see `docs/glossary.md`).
- Manual edits to a resolved configuration after submission without a new campaign.

## Completion criteria

A run is complete only when the scheduler status, model exit status, expected outputs, resolved configurations, code versions, executable checksum, and input identities are recorded in its run manifest.

