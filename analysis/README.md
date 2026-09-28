# Analysis

This directory contains the source code of analyses: work that answers a
question or supports a decision but whose output is not used by a production
workflow stage. Generated data, figures, tables, and logs of an analysis are
stored under `workdir/analysis/<task-id>/`, using the same `<task-id>`.

Examples: comparing irrigated-area datasets, trialling a land-use
harmonization method before implementing it, reviewing an external dataset.

## Workflow or analysis

The user decides the classification. A coding agent proposes a classification
with a reason before writing code and asks the user whenever the case is not
unambiguous. `analysis/` is never the default for code that is hard to
classify.

Use these criteria:

| Question | Yes means |
|---|---|
| Is the output read by a later workflow stage or included in a delivery? | `workflow/` |
| Must the code be re-run to reproduce a production result? | `workflow/` |
| Is the product only a conclusion, comparison, figure, or report used to make a decision? | `analysis/` |

If any of the first two questions is answered yes, the code belongs in
`workflow/`, even when it was first written as a trial.

Workflow code must never read from `analysis/` or `workdir/analysis/`. When an
analysis leads to a production method, the method is implemented in
`workflow/` and the analysis status becomes `promoted`.

## Task layout

```text
analysis/<task-id>/
├── README.md
└── <source files>
```

`<task-id>` is a short, descriptive, lowercase identifier of the question,
e.g. `irrigated-area-comparison`. It must not contain a version label such as
`v2`, `new`, or `final`.

Each task README contains:

- **Question**: what the analysis must answer or decide.
- **Classification**: the user's decision that this is an analysis, with date.
- **Status**: `open`, `closed` (question answered), or `promoted` (method moved
  to `workflow/`, with the path).
- **Inputs**: data used, with paths relative to the workdir.
- **Outputs**: `workdir/analysis/<task-id>/`.
- **Conclusion**: a short summary and the path of the maintained record in
  `docs/audits/` or `docs/decisions/`.

## Rules

- Source code, small configuration, small tables, and the task README only.
- No generated data, figures, logs, or notebook checkpoints.
- Resolve the workdir through `ISIMIP4B_WORKDIR`; do not hard-code personal
  paths.
- Analysis code may import `workflow/common/`; workflow code may not import
  analysis code.
