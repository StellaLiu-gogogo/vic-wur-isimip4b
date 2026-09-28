# 07 Quality Control

## Purpose

Determine whether inputs, parameters, forcing, runs, and postprocessed products satisfy project, scientific, and protocol requirements.

## Inputs

- Products from the relevant workdir stage.
- Their associated input, parameter, or run provenance.
- Explicit quality-control rules and protocol definitions.

## Outputs

- Machine-readable and human-readable reports under `workdir/qc/<object-type>/<object-id>/`, where `<object-type>` is the workdir top-level directory of the checked object.
- Clear status values such as `passed`, `failed`, `warning`, or `not_checked`.
- File-level evidence required for delivery decisions.

## Allowed content

- Structural, metadata, numerical, scientific, and protocol validation code.
- Small expected-value tables and schemas.
- Summary and visualization generators.

## Forbidden content

- Scientific products or raw datasets.
- Rules that convert failures into passes by moving or renaming files.
- Ambiguous statuses inferred only from directory names.
- Unrecorded manual approval of failed checks.

## Completion criteria

A product passes quality control only when all mandatory checks succeed and the tool versions, rule versions, inputs, results, warnings, and failures are recorded explicitly.

