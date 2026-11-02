# 09 Backup

## Purpose

Write dated snapshots of everything in the workdir and the repository that cannot be recomputed from raw data and
code into the backup root `/lustre/backup/WUR/ESG/liu297/isimip4b/` (`ISIMIP4B_BACKUP`), where the administrators'
off-site backup covers it. Decision D13 (2026-11-02, `docs/decisions/D13-backup-procedure.md`); the rules are the
contract's "Data protection" section in `docs/directory-contracts.md`, which is the source of truth.

Classification: production workflow code (user, 2026-11-02; task Y).

## Inputs

- `ISIMIP4B_WORKDIR`: the workdir, read only.
- The repository (the location of this stage's code), read only; `git push` into the bare repository.
- `.gitignore` of the repository: the excluded file types are its sections "Scientific data", "Logs and scheduler
  output", "Build products" and "Python and notebook caches".

## Outputs

Under the backup root: `archive/<YYYY-MM-DD>/{workdir,repo}/…`, `backup-manifest.json` and
`backup-checksums.sha256` in every snapshot, the pointer `current`, the bare repository `repo.git/`. Job records
in `logs/09_backup/<job-name>_<slurm-job-id>/`. Nothing is written into the workdir or the repository.

## Scripts

| Script | What it does |
|---|---|
| `backup_rules.py` | the selection: excluded directories (`raw/`, `scratch/`, every `output/`, the repository's `.git/`), excluded file types (read from `.gitignore`), the three kinds kept whatever the type (`parameters/production/`, `postprocessed/` and `delivery/`, the `states/` of accepted production runs: manifest `production` and `completed`, `qc/runs/<campaign-id>/<run-id>/summary.json` present); every selected file gets a category: workdir, states, parameter-sets, products, repo |
| `backup_snapshot.py` | `--dry-run` lists the categories with file counts and sizes, the accepted runs, the production runs not yet accepted and the free space; `--run` writes the snapshot (rsync with hard links against the current snapshot, `git push --all` and `--tags` into `repo.git/`, sha256 comparison of every copied file with its source, checksums file and manifest, rename of the staging directory, pointer switch); `--verify` re-hashes a published snapshot against its checksums file |
| `submit_backup.py`, `backup_snapshot.sbatch` | the Slurm job (compute node, job record `logs/09_backup/`): `--list` for the dry run, `--approved "user, <date>"` for a snapshot |
| `scheduled_backup.sh` | the command of the `scrontab` entry: sets the environment of a scheduled job and calls `submit_backup.py` with the standing approval |

## How to run

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
export ISIMIP4B_BACKUP=/lustre/backup/WUR/ESG/liu297/isimip4b
export PYTHONPATH=$PWD/workflow
python3 workflow/09_backup/submit_backup.py --list                      # what a snapshot would contain
python3 workflow/09_backup/submit_backup.py --approved "user, 2026-11-03"   # after the user's approval
python3 workflow/09_backup/backup_snapshot.py --verify                  # re-hash the current snapshot (compute node)
```

A snapshot copies into the backup root, so it needs the user's approval of the listed content; the scheduled
snapshots run under the user's standing approval of the rules (D13). The repository may be dirty: the manifest
records the commit and the dirty flag, and the working tree is copied as it is. A failed snapshot leaves
`archive/<date>.staging/` with a manifest of status `failed`; it is removed only under the contract's "Deletion
permissions". A snapshot is never replaced: a second one on the same day needs `--snapshot-id`.

## Schedule

Every two weeks, on the 1st and the 15th of each month at 02:00, the user's `scrontab` runs
`scheduled_backup.sh` as a small Slurm job (10 min, 1 core), which submits the snapshot job with its job record
through `submit_backup.py` under the user's standing approval of the D13 rules (2026-11-02). The entry (`scrontab -l`):

```text
#SCRON --partition=main --time=00:10:00 --cpus-per-task=1 --mem=1G --job-name=backup-schedule
#SCRON --output=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir/logs/09_backup/scrontab-%j.out
0 2 1,15 * * ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir ISIMIP4B_BACKUP=/lustre/backup/WUR/ESG/liu297/isimip4b /lustre/nobackup/WUR/ESG/liu297/isimip4b/repo/workflow/09_backup/scheduled_backup.sh
```

The small job's own output goes to `logs/09_backup/scrontab-<job-id>.out`; the snapshot job records itself in
`logs/09_backup/backup-snapshot_<job-id>/` as a manual one does. A snapshot that fails leaves
`archive/<date>.staging/`; the next scheduled one on a later date is not blocked by it.

## Restore

Copy from `$ISIMIP4B_BACKUP/archive/<date>/workdir/<path>` (or `current/workdir/<path>`) back into the workdir with
`rsync -a`, after the user's authorization (a write into an accepted location); for the repository, fetch from
`$ISIMIP4B_BACKUP/repo.git`. Check a snapshot first with `backup_snapshot.py --verify --snapshot-id <date>`.

## Task Y (2026-11-02)

| Step | What | State |
|---|---|---|
| Y1 | rules, snapshot script, Slurm template, submit script; unit tests on temporary directories (real rsync and git: hard links, verification failure keeps the staging directory, pointer, bare repository, rendering) | written 2026-11-02 |
| Y2 | contract change ("Data protection", hierarchy, stage list, layout check), D13 record, open-decisions | written 2026-11-02 |
| Y3 | listing job (`--list`) and the user's approval of the content and sizes | done 2026-11-02: job 43539715, 19 867 files, 17.0 GiB (workdir text 12.4 GiB, of which qc/forcing/landuse csv 8.9 GiB and QC figures 2.8 GiB; parameter set 4.5 GiB; repo 3.7 MiB; no accepted production run yet), approved by the user |
| Y4 | first snapshot; contract "Status" and `workdir/README.md` updated with its date | done 2026-11-02: job 43539753 from main `d1a6c54`, 12 min 49 s on one core-set of node213, `archive/2026-11-02` with 19 871 files verified, `current` set, `repo.git` holds every branch and tag |
| Y5 | `scrontab` entry shown to the user and enabled | pending |

## Allowed content

Source code, the Slurm template, this README.

## Forbidden content

Copies of workdir content, logs, checksums of real snapshots, credentials.

## Completion criteria

The first snapshot is complete and verified, `current` points at it, the bare repository holds every branch and tag,
the schedule is enabled and recorded here, and the contract's "Status" paragraph names the date.
