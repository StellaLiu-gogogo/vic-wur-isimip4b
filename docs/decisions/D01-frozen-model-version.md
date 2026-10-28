# D01 — Frozen VIC-WUR model version

Status: **decided 2026-10-28** by the user.
Due stage: `03_parameters`.

## Context

Every production build, run and cache records a model commit, and parameter
files must match the input format of that commit. Since 2026-09-29 the
project worked with a provisional choice recorded in `model/vic.lock.yaml`:
branch `fix-restart-luapply-snow-state` of `https://github.com/wur-wsg/VIC`,
head `39e21ff5015d01d9bc20407a8f50006831417aff` (commit date 2026-09-15),
image driver, `freeze_status: provisional`. A provisional lock gives only
candidate builds, and `render_run.py` refuses a production campaign without
a frozen lock.

Under the provisional lock, the user allowed the following to be accepted
while D01 was open (`open-decisions.md`):

- the climate units of EC-Earth3-ESM-1-1;
- the land-use and water-use units of all five soc scenarios.

The following were built or run under the same commit:

- the candidate build `builds/vic/39e21ff5…/` (2026-09-30, status `built`);
- the smoke, smoke-nonrenewable, chunk-test, natural-spinup and natural-run
  campaigns;
- the parameter checks of task R (reader rules of this commit).

## Options considered

- Freeze `39e21ff5` now.
- Wait for a later VIC-WUR commit, which would require re-checking the
  plugin readers, the water-use demand unit and the parameter formats, and
  rebuilding.

On 2026-10-28 the branch head was still `39e21ff5`
(`git ls-remote`, `refs/heads/fix-restart-luapply-snow-state`).

## Decision

VIC-WUR commit `39e21ff5015d01d9bc20407a8f50006831417aff` (image driver) is
the frozen model version of the project (user, 2026-10-28). The frozen version
is the commit SHA, not the branch: later commits on the branch do not change
it. `model/vic.lock.yaml` records `freeze_status: frozen`.

## Consequences

- Production campaigns can pass the model check of `render_run.py`. They
  still need a production build, the production parameter set, and the other
  open items of `05_simulation` (D06; the implementation items of D03 and of
  the D19 amendment of 2026-10-22).
- **Build.** The existing build `builds/vic/39e21ff5…/` was made from the
  provisional lock. Its manifest says `build_kind: candidate` and
  `freeze_status: provisional`, and its status is `built`: the VIC test suite
  was not run. `build_vic.sh` now gives a production build of the same commit
  in the same directory. Replacing the candidate build directory needs the
  user's authorisation (`docs/directory-contracts.md`, "Deletion
  permissions"). How the production build is made and recorded is a task for
  `05_simulation`, to be agreed with the user before the first production
  run.
- **Forcing.** Every unit accepted under the allowance of `open-decisions.md`
  stays valid: the frozen commit is the provisional commit. The water-use
  demand unit (mm per model step, mm/day with one model step per day) was set
  for the `wateruse` plugin of `39e21ff5`, so the check required "when D01 is
  decided" is satisfied without a change.
- **Parameters.** The reader rules checked by the parameter verifiers are
  those of the frozen commit. Promoting the candidate parameter set
  `vic-global-5arcmin-version-a` to `parameters/production/` still needs:
  - the dam component (task L, after the natural run);
  - QC of the rebuilt FILE decomposition and of the two adopted bundles.

  This promotion is not part of D01.
- **Runs.** The smoke and natural runs used the frozen commit with a
  candidate build. They stay non-production runs.
- The note "D01 is provisional" in the stage READMEs is replaced by a
  reference to this record.
