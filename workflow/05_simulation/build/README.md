# 05 Simulation — build

Builds the VIC-WUR image driver at the commit pinned in `model/vic.lock.yaml`
and records the result under `workdir/builds/vic/<model-commit>/`
(`docs/directory-contracts.md`, `builds/`).

**Classification:** workflow (user decision, 2026-09-30). The executable is
read by the run stage and must be rebuilt to reproduce any simulation.

| File | Role |
|---|---|
| `build_vic.sh` | producer: checkout at the locked commit (or, with `--test-commit`, a test commit derived from it), module setup, `make`, checks, `build_manifest.json` |
| `promote_build.py` | records an existing candidate build of the frozen commit as the production build, without recompiling (D01 amendment 2026-10-28) |

## What the script does

1. Reads `model/vic.lock.yaml` (repository, branch, commit, driver,
   `freeze_status`); the lock file is never modified. `freeze_status:
   provisional` gives a **candidate** build, `frozen` a **production** build
   (`build_kind` in the manifest).
2. Clones (SSH, `git@github.com:wur-wsg/VIC.git`) or reuses the disposable
   checkout `workdir/scratch/vic-build/<commit>/`, checks out exactly that
   commit and requires a clean work tree. The VIC source is never copied
   into this repository.
3. Loads the Anunna module bucket `2025` and `netCDF/4.9.3-gompi-2025a`
   (GCC 14.2.0, OpenMPI 5.0.7, HDF5 1.14.6, netCDF 4.9.3; user decision of
   2026-09-30, replacing the unsupported `legacy` modules
   `mpich/gcc/64/3.1.3` and `netcdf/gcc/64/4.6.1` used by earlier ISIMIP3b
   jobs). It fails if `mpicc` or `nc-config` resolve outside the bucket,
   for example to a conda environment on `PATH`.
4. `make clean`, then `make -j N vic_image.exe` in `vic/drivers/image` with
   `MPICC`, `NC_CFLAGS` and `NC_LIBS` passed explicitly (the exact command
   is in the manifest and `logs/build.log`).
5. Copies `vic_image.exe` to `bin/`, computes its sha256 and runs the checks
   into `tests/`: `vic_image.exe -v`, `vic_image.exe -o`, `ldd` (libnetcdf,
   libhdf5 and libmpi must resolve inside the bucket).
6. Writes `build_manifest.json` (model commit and branch, freeze status,
   build date UTC, host and CPU architecture, modules, compiler, MPI and
   NetCDF versions, build command, workflow commit and `code_dirty`,
   executable path and sha256, test results, status).

Everything is staged under `scratch/vic-build/output/<commit>/<build-date>/`
and moved to `builds/vic/<commit>/` only when the build and the checks
succeed, so a failed build never creates a build directory; its evidence
stays in scratch. An existing `builds/vic/<commit>/` is never overwritten.

## Status

- `built`: the executable runs `-v` and `-o` and links to the recorded
  toolchain.
- `tested`: reserved for a build whose VIC test suite ran and passed. The
  suite in the checkout's `tests/` cannot run here: the unit tests need the
  VIC Python driver (`from vic import lib`), which this fork does not have,
  and the system tests need the `tonic` package and the Stehekin sample data
  submodule (a download). The manifest records the suite as `skipped`.
- `failed`: build or checks failed; see `failure_reason` in the manifest.

## Running

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
workflow/05_simulation/build/build_vic.sh            # records builds/vic/<commit>/
workflow/05_simulation/build/build_vic.sh --scratch  # test run, stays in scratch
```

No conda environment is needed; only Anunna modules are used. The build
runs on a login node in about 1 minute of CPU time; writing the object
files on `/lustre` took 7 minutes on 2026-09-30. If the repository is not
clean the result stays in scratch with `code_dirty: true` (rule 14): commit
first, then build, so that the manifest records the workflow commit.

## Test builds (`--test-commit`)

A test build compiles a VIC-WUR commit that descends from the locked commit, to test a change of the model before
the user decides on a new model version (task L5, user 2026-10-31: the new snow density of the land-use step,
campaign `snow-density-test`). The lock file is not changed.

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
workflow/05_simulation/build/build_vic.sh --test-commit <sha> --test-source <VIC git repository>
```

- `<sha>` must be a full commit in `<VIC git repository>` (a local clone, for example in the task's scratch) that
  descends from the locked commit; the checkout `scratch/vic-build/<sha>/` is cloned from that repository.
- The manifest records `build_kind: test`, `model.freeze_status: test`, the source repository and branch, and a
  `test` record: `base_commit` (the locked commit), the difference to it (`logs/test_diff.patch`, its sha256 and the
  changed files).
- The build goes to `builds/vic/<sha>/` like any build. Only a non-production campaign with `model.test_build: true`
  and `model.commit: <sha>` can run it (`render_run.py check_build`); a production campaign never can.
- A commit that exists only in a local clone must also be kept in the repository, as a patch with the analysis that
  uses it (campaign `snow-density-test`: `analysis/dam-parameter-test/vic-lu-snow-density.patch`), so that the
  workdir never holds the only copy of the change.

## Promotion of a candidate build (`promote_build.py`)

A candidate build made before the lock was frozen can become the production build of the same commit without
recompiling, when the user decides so (D01 amendment 2026-10-28 for `39e21ff5`). The script checks that
`model/vic.lock.yaml` is frozen at the build's commit, that the manifest is a candidate build with status `built` or
`tested`, not promoted before, whose checkout was at that commit, and that the executable still has the recorded
sha256 and size. It then

1. keeps the manifest as it was, byte for byte, in `logs/build_manifest.candidate.json` (never overwritten);
2. rewrites `build_manifest.json` with `build_kind: production`, `model.freeze_status: frozen`, the kept manifest added
   to `logs`, and a `promotion` record: time, decision, `authorised_by`, reason, `recompiled: false`, from/to kind and
   freeze status, the lock, the verified executable sha256 and size, the status kept (`built`: the VIC test suite was
   not run), the kept manifest's sha256, and the workflow commit of the script.

Everything else stays: status, environment, build command, tests and the build's own `workflow` record. The
executable is not touched, so runs that recorded its sha256 are unaffected. A promotion needs a clean repository
(rule 14) and the user's authorisation of the file change in `builds/`:

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 workflow/05_simulation/build/promote_build.py --authorised "user, 2026-10-28" --dry-run   # checks, prints the change
python3 workflow/05_simulation/build/promote_build.py --authorised "user, 2026-10-28"
```

`render_run.py` renders a production campaign only with `build_kind: production`. Tests:
`tests/unit/test_simulation_promote_build.py`.

## Running the executable

The 2025 bucket installs one library tree per CPU architecture
(`skylake_avx512`, `zen3`, `zen5`) and `module load 2025` selects the tree of
the current node. The executable was linked on a login node against the
`zen3` tree. Every Slurm job that runs it must load the modules listed
under `runtime_modules` in the manifest (`module load 2025` then
`module load netCDF/4.9.3-gompi-2025a`); the loaded `LD_LIBRARY_PATH` takes
precedence over the executable's run path, so each node uses its own tree
of the same library versions. This applies to the Slurm templates of
`templates/slurm/` when they are written.

## Decisions

D01 is decided (2026-10-28): the lock is frozen at `39e21ff5`, so the script
now gives a production build. The build of 2026-09-30 in
`builds/vic/39e21ff5…/` was made from the provisional lock and is a
candidate build; the user decided that it becomes the production build
without recompiling (amendment 2026-10-28 of
`docs/decisions/D01-frozen-model-version.md`), recorded by `promote_build.py`
after the user's authorisation of the file change: promoted on 2026-10-30
(from `a6761b7`; the earlier manifest is `logs/build_manifest.candidate.json`).
On 2026-10-31 the user froze `a826251b` instead (D01 amendment 2026-10-31:
`39e21ff5` with the corrected fresh-snow density of the land-use step, tested
as the test build `a6868324` of the same code, task L5). Its production build
in `builds/vic/a826251b…/` was compiled by this script; the builds of
`39e21ff5` and `a6868324` stay unchanged. D02, D03 and D06 do not affect the
build.
