# 03 Parameters — irrigation

The `irrigation` component of a parameter set,
`parameters/<status>/<set>/irrigation/vic_global_5min_irrigation_parameters.nc` (read by VIC with
`IRRIGATION_PARAMETERS`), is **adopted** (vic_parameter candidate v2, efficiency corrected, recorded in
`manifests/parameters/<set>.yaml`); it has **no producer here**. This directory holds its verification.

Classification: production workflow code (user, 2026-10-24, task R). The job, the shared parts and the status
rules are described in `../domain/README.md`. Tests: `tests/unit/test_adopted_parameter_qc.py`.

## Checks (verify_irrigation.py)

Computed from the stored values, not with VIC's reader (`irr_start.c`, `irr_alloc_free.c`, `irr_init.c` at VIC
`39e21ff5`).

- `integrity`, `latlon`: see `../domain/README.md`; lat and lon equal the domain.
- `vic_variables`: `veg_class`, `paddy` (`irr_class`), `groundwater_fraction`, `irrigation_efficiency` (lat, lon);
  `irr_class` = 2. The file has no `irrigation_offset`, so runs must set `OFFSET_IRRIGATION FALSE`.
- `classes`: `veg_class` = [14, 15] (irrigated non-paddy, irrigated paddy) and `paddy` = [0, 1]. `irr_init.c` sets
  the groundwater fraction of a paddy class to 0 whatever the file holds, so `groundwater_fraction` acts on class 14
  only.
- `values`: on every active cell `irrigation_efficiency` in (0, 1] (VIC divides the demand by it and uses it as the
  consumed fraction) and `groundwater_fraction` in [0, 1], neither fill nor NaN; values outside the mask are
  counted (VIC never reads them). Summary statistics; maps `figures/irrigation_efficiency.png`,
  `figures/groundwater_fraction.png`.
