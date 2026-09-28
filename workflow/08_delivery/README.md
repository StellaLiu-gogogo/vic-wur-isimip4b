# 08 Delivery

## Purpose

Assemble, inventory, checksum, and prepare approved products for formal delivery or long-term archival.

## Inputs

- Postprocessed products with an explicit passing quality-control status.
- Source run identities and provenance.
- Current naming and protocol requirements.

## Outputs

- Approved products under `workdir/delivery/`.
- Delivery inventories and checksums.
- Version-controlled delivery manifests under `manifests/deliveries/`.
- Delivery preparation logs under `workdir/logs/08_delivery/`.

## Allowed content

- Delivery assembly, inventory, checksum, and validation code.
- Packaging and transfer preparation logic.
- Small templates for machine-readable delivery records.

## Forbidden content

- Delivered scientific files in the repository.
- Files with `failed`, `warning`, or `not_checked` status unless a documented policy explicitly permits them.
- Treating file location as proof of quality-control success.
- Overwriting an existing delivery without a new delivery identity and manifest.

## Completion criteria

A delivery is complete only when its file inventory, checksums, source runs, workflow and model versions, protocol version, quality-control evidence, and destination are recorded in a delivery manifest.

