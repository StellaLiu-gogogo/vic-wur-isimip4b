# Environments

This directory defines the reproducible software environment used by the complete workflow on Anunna.

Expected content may include:

- Conda environment specifications and lock files;
- required Anunna modules and versions;
- Python and R dependency declarations;
- compiler, MPI, NetCDF, CDO, NCO, and quality-control tool requirements;
- environment creation and verification instructions.

Do not store an installed environment, package cache, credentials, user-specific activation script, or generated build tree here. Environment definitions must be version-controlled, reviewable, and testable.

Production run and build manifests must record the relevant environment or module versions rather than assuming that the current login environment is equivalent.


## Project environment

The workflow and analysis code runs in the conda environment **`isimip4b`**,
defined by `environments/isimip4b.yaml` and created once per user with:

```bash
conda env create -f environments/isimip4b.yaml
```

It uses Python 3.12 (pinned). Update it after a change to the file with
`conda env update -f environments/isimip4b.yaml --prune`. The layout check
`tests/check_layout.py` and the pre-commit hook run outside this
environment with the system `python3` (3.9 on Anunna) and must stay
compatible with it. No other environment (personal or
project) is used for production work; the environment name and package
versions are recorded in every provenance record, build manifest, and run
manifest. VIC-WUR itself is compiled with the Anunna modules recorded in the
build manifest, not with this environment.

Activate it and set the variables below in every shell and Slurm job:

```bash
conda activate isimip4b
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export PYTHONPATH=/lustre/nobackup/WUR/ESG/liu297/isimip4b/repo/workflow
```

## Required variables

Every environment used to run workflow or analysis code sets:

- `ISIMIP4B_WORKDIR`: absolute path of the sibling `workdir` directory;
- `PYTHONPATH` including `<repo>/workflow`, so that shared modules are imported as `from common import <module>`.

The backup procedure additionally uses:

- `ISIMIP4B_BACKUP`: absolute path of the backup copy of the workdir, `/lustre/backup/WUR/ESG/liu297/isimip4b/workdir`.
