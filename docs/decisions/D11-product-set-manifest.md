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
   - per segment, whether it is accepted: every unit `passed` (amended
     2026-11-11: or `warning` from the range check only) and the
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

## Amendment 2026-11-10 (user, task AD3)

1. **Run output files by size and modification time.** The unit record lists
   the run output files it read with their size and modification time, not
   their sha256. Hashing would read the 5′ output a second time (about 525 GB
   per 25-year chunk, 15–30 minutes, about 45 TB for the campaign) on the
   file system the running VIC jobs write to. The output of a completed
   attempt is never rewritten, and the record names the attempt (number,
   Slurm job ID) and the sha256 of the run manifest. Small inputs (the
   static files of the set, the ISIMIP mask, the water-use forcing files of
   the consumption fractions) keep their sha256.
2. **Check status outside the unit.** A unit is never changed after it has
   been renamed into place, so its record names the path of its QC summary
   (`qc/postprocessed/<product-set-id>/<gcm>/<segment-key>/<start>-<end>/summary.json`)
   but not the check status; the status is in that summary and in
   `product-set.yaml`.

## Amendment 2026-11-11 (user, task AD6)

**Range warnings do not hold back acceptance.** A product unit counts as
`accepted` when every check of its unit check has passed except the range
check (`valid_range`: values outside the protocol's `valid_min` /
`valid_max`), which may be `warning`. The values are kept as VIC-WUR
computed them: nothing is clipped, so the water balance of the products is
unchanged. The number of values outside the range per product file is
recorded with the unit in `product-set.yaml`, for the report to ISIMIP at
delivery. Any other warning (the monthly means of a daily product against the
monthly product) still leaves the unit `present` until the user has seen it.

Reason: the scratch test of AD6 (soil-comparison-version-b, 2011–2020) passed
every other check, and its only warnings were model behaviour: negative
monthly `evap` (4 % of cell-months, condensation and deposition in high
latitudes and on the Tibetan Plateau in winter, at least −0.38 mm/day) and
daily `dis` above 700 000 m3 s-1 at the Amazon mouth (23 days in 2013, at
most 776 402 m3 s-1). Negative winter `evap` occurs in every chunk, so with
"every unit `passed`" no segment could be accepted.
