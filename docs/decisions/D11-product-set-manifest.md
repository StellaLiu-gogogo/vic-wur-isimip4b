# D11 — Structure of the postprocessed product-set manifest

Status: **decided 2026-11-09** by the user (task AD).
Due stage: `06_postprocessing`.

## Context

A product set under `workdir/postprocessed/` must remain traceable to its
source runs and to the postprocessing commit (`docs/directory-contracts.md`,
`postprocessed/`). The backup procedure keeps `postprocessed/` whole (D13),
and `08_delivery` needs a list of every file with its ISIMIP identity once
the filename pattern is published (D09). The products of the campaign
`water-global-ec-earth3-esm-1-1` are made while later runs are still
simulating (task AD): several Slurm jobs write products of different run
chunks at the same time.

## Options considered

- (A) Two levels.
  - Every product unit (the products made from one run chunk) gets a
    `provenance.yaml` written by the job that made the unit.
  - A set-level `product-set.yaml` and `checksums.sha256` are written by a
    separate step that collects and checks the units.
  - This follows the provenance record of a forcing unit.
- (B) One manifest per product set, appended to by every job under a lock.
  It is simpler to read, but needs a lock against simultaneous writes and
  grows with every unit.
- (C) One record file beside every product file; far too many files.

Product-set identity: the campaign ID of the source runs, or a separate
name.

## Decision

The user took the recommended option on 2026-11-09.

1. **Option (A).**
2. **Product-set ID** = the campaign ID of the source runs, here
   `water-global-ec-earth3-esm-1-1`. A changed postprocessing method that
   changes the products (for example a change of D07) gets a new meaningful
   product-set ID, never a version suffix (`AGENTS.md`, "Naming and
   versioning").
3. **Product unit.** One run chunk (or a whole unchunked run) of a reported
   segment, in
   `postprocessed/<product-set-id>/<gcm>/<segment-key>/<start-year>-<end-year>/`
   (layout in `docs/directory-contracts.md`, `postprocessed/`).
   - The job writes the unit into a staging directory beside it and gives
     it its final name only when every file and the `provenance.yaml` are
     complete.
   - An existing unit is never overwritten; making it again needs the
     user's authorisation, as for any accepted object.
4. **`provenance.yaml` of a unit** records at least:
   - the product set, segment ID, segment key, GCM, period, chunk and years;
   - the source run (campaign, run ID, run directory), the chunk and its
     completed attempt (number, Slurm job ID), the sha256 of the run
     manifest, and the chunk check it relied on (`summary.json` path,
     sha256, status, the attempt it is bound to);
   - the input files read (the run output files with sha256, the
     parameter-set files of the static fields, the ISIMIP mask) and the static
     files of the product set used (sha256);
   - the producing code: commit, branch, `code_dirty` (always `false` for an
     accepted unit), script, Slurm job ID, start and end time (UTC);
   - the method: the D07 parts applied, the protocol commit, the product
     configuration file and its sha256;
   - every product file with: variable, time step, years, units, size,
     sha256, and the identity fields of the later ISIMIP filename (model
     name (D10), climate forcing, bias adjustment, climate scenario, soc
     scenario, sens scenario, variable, region `global`, time step, start
     and end year);
   - the check of the unit: status (`passed`, `failed`, `warning`,
     `not_checked`) and the path of its QC summary under
     `qc/postprocessed/<product-set-id>/...`.
5. **`product-set.yaml`** at the root of the set records:
   - the identity: product-set ID, campaign and campaign-file sha256,
     parameter set, model commit, protocol commit;
   - the state of the decisions the products depend on: D07 (decided), D09
     and D10 (open, names given at delivery);
   - the static files (`static/`) with sha256;
   - the expected product units, derived by code from the campaign's
     reported segments and their chunks, each with its status (`missing`,
     `present`, `accepted`, `failed`);
   - per segment, whether it is accepted: every unit `passed` and the
     run's whole-run check `passed`;
   - when the file was last written, by which commit and job.

   `checksums.sha256` lists every product file of the set.
   `product-set.yaml` and `checksums.sha256` are written only by the
   collecting step, never by a unit job.

## Consequences

- `06_postprocessing` (task AD) writes the unit records in its unit job and
  the set-level files in a separate collecting and checking step; both are
  produced only from a clean repository (rule 14).
- `08_delivery` builds the ISIMIP filenames and the file splitting from the
  identity fields of the unit records once D09 is published and D10 is
  decided; it does not have to read file names.
- The backup snapshots take the whole set, records included (D13 rule 3).
- `docs/directory-contracts.md`, `postprocessed/`, describes the layout in
  the same change.
