# Documentation

This directory contains project-wide documentation intended for collaborators, reviewers, maintainers, and coding agents.

Required documents:

- `glossary.md`: the authoritative project terminology in plain language.
- `directory-contracts.md`: allowed and forbidden content for each major directory.

Documents created when their content exists:

- `architecture.md`: repository, workdir, software, and data-flow architecture.
- `workflow.md`: the end-to-end scientific and operational workflow.
- `experiment-matrix.md`: planned and completed experiment coverage.
- `runbook.md`: operational instructions for building, testing, running, recovering, and delivering.
- `decisions/`: durable records of important scientific or architectural decisions.
- `audits/`: read-only assessments and evidence summaries, including the maintained conclusions of analyses under `analysis/`.

Documentation must be written in English. It must use terminology defined in `glossary.md`, distinguish current policy from historical evidence, and avoid presenting plans as completed work.

Do not store large generated figures, raw evidence datasets, model output, or temporary review artifacts here. Small figures may be version-controlled only when they are necessary to understand a maintained document.

