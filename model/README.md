# Model Version

This directory identifies the exact VIC-WUR source version approved for this project. It does not contain a copied model source tree or a compiled executable.

`vic.lock.yaml` must identify the authoritative source repository, full immutable commit SHA, release tag when available, driver, and freeze status. A moving branch name alone is not a frozen version.

VIC-WUR development belongs in its own Git repository. Production builds belong under `workdir/builds/vic/<commit>/` together with a build manifest, compiler and library information, build log, executable checksum, and test results.

Changes to the pinned commit must be reviewed as an explicit model-version change. Existing production results must continue to reference the commit and executable with which they were generated.

