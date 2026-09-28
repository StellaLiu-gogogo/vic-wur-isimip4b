# Configurations

This directory contains structured definitions used to render and execute campaigns. Configuration expresses intended behavior; it is not a record of what actually happened.

## `campaigns/`

One definition per campaign (see `docs/glossary.md`). A campaign definition states:

- the model build (`model/vic.lock.yaml` commit) and parameter-set ID;
- the ISIMIP protocol commit whose experiment definitions are used;
- the GCMs;
- the selection of ISIMIP experiments to simulate, e.g. all `water_global` experiments of a given priority or an explicit list of experiment IDs;
- explicit exclusions with their justification, e.g. `2021co2` experiments are identical to `default` for VIC-WUR because the model has no CO₂ response;
- initialization, output, and other run choices that are not defined by the protocol.

A campaign definition does not list segments. The workflow derives segments, their periods, and their parent segments from the protocol experiment definitions (`workflow/05_simulation/render/`). The complete resolved configuration is saved with each run.

Each production campaign must be self-contained enough to review without relying on hidden scientific defaults.

## `resources/`

Resource configurations define Anunna execution requirements such as partition, task count, memory, wall time, and job dependencies. They must be organized by workload type or scale rather than by individual developer.

## Rules

- Store YAML or another explicitly documented structured format.
- Validate production configurations before rendering run files.
- Do not maintain segment lists by hand.
- Do not store credentials, logs, generated VIC configurations, or scientific datasets here.
- Do not duplicate campaigns by adding `v2`, `fix`, `new`, `final`, or date suffixes. A campaign with a different model build or parameter set gets a new descriptive campaign ID.
- Do not distribute personal absolute paths across configuration files.
- Save the fully resolved configuration in the corresponding run directory.
