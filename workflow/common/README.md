# workflow/common

Python modules shared by two or more workflow stages (docs/directory-contracts.md, `workflow/common/`).

Classification: production workflow code (user, 2026-10-05, task G). The modules were taken out of the
producers, submit scripts, and verifiers of `03_parameters/vegetation/` and `04_forcing/{climate,landuse,water_use}/`,
which each carried their own copy; the producers' results are unchanged (scratch tests before and after,
recorded in `manifests/code-equivalence.yaml`).

## Admission

A module belongs here when at least two stages use it, or when it is an infrastructure module listed in the
contract (`cache.py`, not written yet). Modules are flat files, contain no stage-specific logic and no entry
points (nothing here is run as a script), and define no path under `analysis/`. Stage-specific code (methods,
file formats, checks, which keys a record contains) stays in the stages.

## Modules

| Module | Provides | Used by |
|---|---|---|
| `workdir.py` | `root()`: the workdir from `ISIMIP4B_WORKDIR` (stops when unset); `logs(stage)`: `logs/<stage>/` | all producers, verifiers, submit scripts |
| `hashing.py` | `sha256`, `md5`, `file_hashes` (both in one pass), read in 16 MiB blocks | producers, `qc.py` |
| `gitstate.py` | `state(repo)`: full HEAD commit and whether the repository is not clean (`git status --porcelain`); `tree_hashes(repo, dirs)`: Git tree hashes at HEAD (the code fingerprint) | producers, `qc.py` |
| `provenance.py` | `utcnow`; `read`/`write` of `provenance.yaml` (written whole, then renamed); `set_qc`; `software_versions` and `fingerprint` (the fingerprint block); `code_equivalence`: the chain of entries of `manifests/code-equivalence.yaml` that connects a recorded code fingerprint with the current one | producers, verifiers, `jobrecord.py` |
| `qc.py` | status vocabulary and `combine` (failed > not_checked > warning > passed; a missing part counts as not_checked); `write_summary`, `write_json`; `exit_with` (verifier exit status); `verifier_state`, `binding`, `report_status` (per-file reports bound to their data files and verifier version) | verifiers |
| `jobrecord.py` | `render` a Slurm template, `conda_base`, `submit`: on hold, then `job.sbatch` and `job.yaml` in `logs/<stage>/<job-name>_<slurm-job-id>/`, then release | submit scripts |

### Verifier exit status

| `qc.status` | exit status | Slurm job state |
|---|---|---|
| `passed` | 0 | COMPLETED |
| `failed` | 1 | FAILED |
| `warning` | 3 | FAILED (a warning is not an acceptance; read the summary) |
| `not_checked` | 4 | FAILED (some part of the object has no valid report, e.g. a partial unit) |

2 is left out because Python uses it for command-line errors.

### Per-file reports

Each per-year report of a forcing verifier (`reports/verify_<year>.json`) contains a `binding` block: the
SHA-256 of the data files it checked and the verifier's commit, Git state, and code-tree hashes (its stage
directory and `workflow/common`). When the unit summary is made, a report of the current run counts if its data
files are unchanged; a report of an earlier run counts only if, in addition, both runs came from a clean
repository with the same verifier code-tree hashes. Any other report, including one written before 2026-10-05
without a `binding`, counts as `not_checked`, so that year must be verified again.

## Importing

Stage code imports the modules as

```python
from common import gitstate, hashing, provenance, qc, workdir
```

with `PYTHONPATH` including `repo/workflow` (environments/README.md); the Slurm templates set it. Tests:
`tests/unit/test_common_*.py`.
