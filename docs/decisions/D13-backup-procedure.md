# D13 — Backup procedure

Status: **decided 2026-11-02** by the user.
Trigger: the first production object accepted (reached 2026-10-30, parameter set
`vic-global-5arcmin-version-a` promoted; 2026-10-31, production build `a826251b`).

## Context

`/lustre/nobackup/` is not backed up by the administrators; `/lustre/backup/` is
backed up off site. Both are directories of the same Lustre file system and
share its space and the user's usage (97 % full on 2026-11-02; the user's
26 TB on the file system are almost all under `nobackup`). The directory
`/lustre/backup/WUR/ESG/liu297/` exists and holds one unrelated script. The
contract of 2026-09 ("Data protection") specified five write-once backup
objects (production parameter set, accepted production run without its
output, production build, postprocessed product set, delivery), a
staging-verify-publish sequence, and left the location and the implementation
of the procedure to this decision. Nothing had been backed up when the trigger
was reached; the user deferred the decision on 2026-10-30 and took it on
2026-11-02, before the production spin-ups start.

## Options

- **A. Five write-once backup objects** (the contract of 2026-09): each object
  copied once when accepted, under the same relative path. Rejected: the
  backup would hold only the listed objects; manifests, provenance records,
  QC reports, job records and the repository's uncommitted work would depend
  on the GitHub remote or on nothing; every new kind of object needs a
  contract change.
- **B. Dated snapshots of everything that cannot be recomputed** (chosen):
  a snapshot mirrors the workdir and the repository working tree, excluding
  what is recomputable from the raw data and the code (raw files, scratch,
  model output, data files of forcing units, candidate parameter sets,
  caches, executables, logs), and keeping whatever its type the production
  parameter sets, the states of accepted production runs, and the products
  and deliveries; a bare repository holds every branch and tag. Snapshots are
  complete directories with hard links to the unchanged files of the
  previous one; a pointer names the newest complete snapshot.
- **C. A manual rsync procedure without workflow code.** Rejected: no
  verification record, no job record, and the selection rules would live in
  a shell history.

## Decision (user, 2026-11-02)

1. **Principle.** Back up everything that cannot be recomputed from raw data
   and code, or only at a cost of weeks or hundreds of node hours; nothing
   that can.
2. **Selection.** The workdir is mirrored with the same relative paths,
   excluding the directories `raw/` and `scratch/` and every `output/`
   directory, and the file types of the `.gitignore` sections "Scientific
   data", "Logs and scheduler output", "Build products" and "Python and
   notebook caches" (the exclusion is by type, so the job records and every
   text file of `logs/`, `analysis/`, `qc/` and `forcing/` stay). Kept whatever
   the type: `parameters/production/`, the `states/` of accepted production
   runs (manifest `production` and `completed`, run check or convergence test
   summary present; every spin-up block counts), `postprocessed/` and
   `delivery/`. `builds/` loses only its executables (rebuilt from the model
   commit in minutes), its manifests stay.
3. **Repository.** A bare repository `repo.git/` under the backup root
   receives `git push --all` and `git push --tags` at every snapshot (never
   `--mirror`: a deleted branch stays); the working tree without `.git/` is
   copied under the same rules, which keeps uncommitted edits. The push
   touches no working tree, so the rule "no change of the main repository
   while a production job runs from it" is respected.
4. **Rotation.** One complete snapshot directory per date under
   `archive/<YYYY-MM-DD>/`, written with `rsync --link-dest` against the
   current snapshot (unchanged files are hard links), verified file by file
   (sha256, link targets) before `archive/<date>.staging/` is renamed and the
   pointer `current` is switched; the current snapshot is complete at any
   time. The pointer is not named `latest` (naming rule of the layout check).
   The bare repository carries its own history and is not rotated. No
   snapshot is deleted by the procedure; deletion follows the contract's
   "Deletion permissions".
5. **Trigger.** Every two weeks from the user's `scrontab` (Slurm 25.11,
   `ScronParameters=enable` on Anunna; the entry is recorded in
   `workflow/09_backup/README.md` and enabled after the user has seen it), and
   by hand after an acceptance, a promotion, a delivery or an important
   commit. The copy runs as a Slurm job on a compute node, never on the login
   node. The user's approval of the listed content before the first copy is
   the contract's rule; the scheduled snapshots run under the standing
   approval of these rules.
6. **Location.** The procedure is the workflow stage `workflow/09_backup/`
   (selection rules, snapshot script, Slurm template, submit script, README).
   Not `workflow/common/`: the contract forbids entry points there, and a
   change of `common/` re-binds every verifier report. `ISIMIP4B_BACKUP`
   names the backup root `/lustre/backup/WUR/ESG/liu297/isimip4b/`.

Details confirmed by the user on 2026-11-02 while the rules were written:
executables excluded by type rather than the whole `builds/` directory; the
repository's `.git/` left out of the working-tree copy; "accepted" judged
from the run manifest and the QC summary; `postprocessed/` and `delivery/`
kept whole; the "Python and notebook caches" section added to the excluded
types (caches are recomputed on import).

## Consequences

- `docs/directory-contracts.md`, "Data protection", "Project roots" and the
  repository hierarchy are changed in the same commit (change procedure);
  `tests/check_layout.py` knows the stage `09_backup`; `environments/README.md`
  redefines `ISIMIP4B_BACKUP` as the backup root.
- Task Y implements the stage (classification: production workflow code,
  user 2026-11-02) with unit tests of the rules and of a snapshot on
  temporary directories (hard links, verification failure, pointer, bare
  repository).
- The first snapshot is written after the user has approved the listed
  content and sizes of `submit_backup.py --list`; the contract's "Status"
  paragraph and `workdir/README.md` are updated with its date.
- The former five-object model and its staging layout are withdrawn; no
  object had been backed up under it.
