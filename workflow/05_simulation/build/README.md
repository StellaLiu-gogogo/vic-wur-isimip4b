# 05 Simulation — build

Builds the VIC-WUR image driver at the commit pinned in `model/vic.lock.yaml`
and records the result under `workdir/builds/vic/<model-commit>/`
(`docs/directory-contracts.md`, `builds/`).

**Classification:** workflow (user decision, 2026-09-30). The executable is
read by the run stage and must be rebuilt to reproduce any simulation.

| File | Role |
|---|---|
| `build_vic.sh` | producer: checkout at the locked commit, module setup, `make`, checks, `build_manifest.json` |

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

D01 is open: the lock is provisional, so every build made from it is a
candidate build identified by its commit; production runs need a frozen
lock. D02, D03 and D06 are due at this stage and do not affect the build.
