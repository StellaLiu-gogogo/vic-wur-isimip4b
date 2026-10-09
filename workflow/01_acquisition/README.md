# 01 Acquisition

## Purpose

Discover, transfer, inventory, and verify external source data required by the project.

Open decisions due at or before this stage are listed in `docs/decisions/open-decisions.md`; check them before starting work here.

## Scripts

| File | Role |
|---|---|
| `build_inventory.py` | classify a `find` listing of the DKRZ ISIMIP4b tree into datasets and transfer priorities (A/B/C); writes `dkrz_isimip4b_inventory_<date>.{csv,md}` |
| `make_batch_lists.py` | split the inventory into the project's transfer batches 1–6; writes `batch_<n>_files.txt` and `batch_<n>_expected_sizes.tsv` |
| `transfer_batch.sh` | rsync one approved batch from levante into the staging directory `workdir/scratch/acquisition-staging/batch-<id>/` (an interrupted file stays there and is resumed by running the same batch again), accept a file only when its size equals the approved size and the remote size, the remote size and mtime did not change during the transfer, and its md5 equals the remote md5, move accepted files into `workdir/raw/ISIMIP4b/` (an existing raw file is never overwritten, only verified again), and write `transfer_manifest_batch_<id>.txt` (with the reason of every file not accepted) and `MD5SUMS` (accepted files, each listed once also when the batch is run again) into the manifest directory; the optional arguments `[src-root] [dst-root]` take files from another DKRZ tree (e.g. `/work/bb0820/ISIMIP` with list paths starting `ISIMIP3b/…`) into `workdir/raw/external/<dataset-id>/<dataset-version>/`; without them the ISIMIP4b behaviour is unchanged |

Exploratory inventories and batch lists go to `workdir/scratch/`; once a
batch is approved and transferred, its list, expected sizes, manifest and
`MD5SUMS` are committed under `manifests/inputs/<dataset-id>/`. The DKRZ
listing itself is made on levante with
`find /work/bb0820/ISIMIP/ISIMIP4b -printf "%y\t%s\t%TY-%Tm-%Td\t%p\t%l\n"`
(plus a `find -L` listing for directory symlinks); an ssh alias `levante`
with key-based login is required.

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

