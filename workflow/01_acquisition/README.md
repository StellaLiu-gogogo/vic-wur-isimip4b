# 01 Acquisition

## Purpose

Discover, transfer, inventory, and verify external source data required by the project.

## Inputs

- Authoritative source locations and access instructions.
- Expected dataset definitions from project documentation or input manifests.
- Checksums or size inventories when provided by the data producer.

## Outputs

- Unmodified source files under `workdir/raw/`.
- Transfer and verification logs under `workdir/logs/01_acquisition/`.
- Candidate input inventories for `manifests/inputs/`.

## Allowed content

- Download and transfer scripts.
- Read-only inventory and checksum tools.
- Slurm job templates for large transfers or verification tasks.
- Small source lists and machine-readable transfer specifications.

## Forbidden content

- Downloaded datasets or generated scientific files.
- Credentials, tokens, or personal authentication material.
- Scripts that modify source files in place.
- Hard-coded personal paths distributed across multiple scripts.

## Completion criteria

Acquisition is complete only when expected files are present, file counts and sizes are checked, integrity verification is recorded, and the source data remain unmodified.

