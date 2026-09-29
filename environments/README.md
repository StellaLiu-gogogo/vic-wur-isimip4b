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


## Required variables

Every environment used to run workflow or analysis code sets:

- `ISIMIP4B_WORKDIR`: absolute path of the sibling `workdir` directory;
- `PYTHONPATH` including `<repo>/workflow`, so that shared modules are imported as `from common import <module>`.

The backup procedure additionally uses:

- `ISIMIP4B_BACKUP`: absolute path of the backup copy of the workdir, `/lustre/backup/WUR/ESG/liu297/isimip4b/workdir`.
