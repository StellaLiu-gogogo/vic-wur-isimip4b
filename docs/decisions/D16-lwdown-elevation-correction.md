# D16 — Elevation correction of downward longwave radiation (`lwdown`)

Status: **decided 2026-10-01** by the user (option A).
Due stage: `04_forcing`.

## Context

The climate forcing (`workflow/04_forcing/climate/`) corrects `tair`
(6.5 K/km lapse rate), `psurf` (hypsometric equation), and `vp` (mixing
ratio constant with height, capped at saturation) from the ERA5 0.5°
orography to the 5′ mean cell elevation `elev` of the parameter bundle.
Method 1.0 only interpolated `lwdown` bilinearly, as the WFDE5 5′ reference
method did, so at cells far above (below) the 0.5° reference height the
downward longwave radiation was too large (small) for the corrected air
temperature and humidity. The elevation differences dz = `elev` − ERA5
height on the 2 188 551 active cells: 1st/99th percentiles −489/+605 m,
54 544 cells with |dz| > 500 m, 7 317 with |dz| > 1 000 m.

## Options

| Option | Method | Assessment |
|---|---|---|
| A | Ratio method of Cosgrove et al. (2003, eq. 15): scale the bias-adjusted `rlds` by the ratio of Satterlund (1979) clear-sky emission ε(T, e) T⁴ at the corrected and the 0.5° level; used by WATCH (Weedon et al. 2010, eqs. 30–32) and WFDE5 (from ERA5 0.25° to 0.5°), hence for the W5E5 reference of ISIMIP | keeps the bias-adjusted `rlds` (R = 1 where dz = 0), consistent with how the ISIMIP reference data were made, only needs T and e of both levels |
| B | TopoSCALE emissivity decomposition (Fiddes & Gruber 2014) with the clear-sky emissivity of Konzelmann et al. (1994): separate clear-sky and cloud contributions, keep the cloud part, recompute the clear-sky part at the new level | physically more detailed; needs the all-sky/clear-sky split from daily means only; differs from A by less than 0.2 W m-2 on four 2015 test days |
| C | Re-parameterisation (MicroMet, Liston & Elder 2006): compute `lwdown` from T, e, and cloud cover at the 5′ level | rejected: discards the bias-adjusted `rlds` |
| D | Empirical lapse rate of `lwdown` (Marty et al. 2002: −29 W m-2 km-1 in the Alps) | not used as a method; kept as validation of the slope of A |

## Evidence

Before the decision (four 2015 days, prototype computations): options A and
B differ by less than 0.2 W m-2; option A changes `lwdown` by about
+48 W m-2 where dz < −1 km and about −45 W m-2 where dz is 1–2 km; the
land-area-weighted global mean changes by −0.09 W m-2.

Measured with the implementation (method 1.1, EC-Earth3-ESM-1-1 `esm-hist`
2015, 365 days, Slurm job 42986039; 1.1 minus 1.0, annual mean):

| dz [m] | Active cells | Mean change [W m-2] | 5th / 95th percentile |
|---|---|---|---|
| −3 000 to −1 000 | 2 239 | +41.1 | +28.0 / +61.1 |
| −1 000 to −500 | 18 391 | +21.0 | +13.5 / +31.9 |
| −500 to −200 | 99 071 | +9.3 | +5.5 / +15.2 |
| −200 to 200 | 1 922 232 | +0.1 | −3.5 / +3.8 |
| 200 to 500 | 112 704 | −9.2 | −14.9 / −5.4 |
| 500 to 1 000 | 28 836 | −20.4 | −31.4 / −12.8 |
| 1 000 to 2 000 | 4 950 | −39.8 | −60.2 / −26.0 |
| > 2 000 | 128 | −71.8 | −91.8 / −51.7 |

- Regression slope of the annual-mean change on dz: −31.1 W m-2 km-1; the
  verifier's slope of (`lwdown` − bilinear `rlds`) on dz over three sample
  days: −30.1 W m-2 km-1 (Marty et al. 2002: −29 W m-2 km-1).
- Land-area-weighted global mean change: −0.078 W m-2 (daily −0.086 to
  −0.068 W m-2), against a global mean `lwdown` of 329.0 W m-2.
- R = 1 within 8.4e-7 on the 357 active cells with |dz| < 0.005 m; the
  largest annual-mean change where |dz| < 1 m is 0.04 W m-2.
- Verifier: all checks passed (global mean difference to the 0.5° input at
  most 0.083 W m-2; independent recomputation within 1.5e-7 relative).

## Decision

**Option A** (user, 2026-10-01): `lwdown` = R × bilinear `rlds`, with

R = ε(T₁, e₁) T₁⁴ / (ε(T₀, e₀) T₀⁴),  ε(T, e) = 1.08 · [1 − exp(−e^(T/2016))],
T in K, e in hPa,

where T₀ is the block-replicated `tas` and e₀ the vapour pressure from the
same mixing ratio (bilinear `huss`) and the block-replicated `ps`, and T₁,
e₁ are the corrected `tair` and `vp` exactly as written to their units. No
cap on R or `lwdown`, no fill, no change to the other six variables.

Supplement (user, 2026-10-01): e₀ is capped at saturation like `vp`,
e₀ = min(r / (0.622 + r) · ps, svp(T₀)), i.e. the `vp` method applied at
the 0.5° level. Without it, R ≠ 1 at dz = 0 wherever the 0.5° level on
the 5′ grid is supersaturated (0.2–0.5 % of the active cells on the 2015
sample days, mostly coastal cells where bilinear `huss` mixes in moister
neighbours), because e₁ is capped and e₀ was not. Dropping the `vp` cap
altogether was considered: it would also give R = 1 at dz = 0, but `lwdown`
would then use supersaturated e₁ in 1.5 % of the cell-days (median
+0.7 W m-2, 99th percentile +6.8 W m-2 compared with the cap at both
levels; global land mean +0.018 W m-2) while VIC uses the capped `vp`.

## Consequences

- `workflow/04_forcing/climate/downscale_climate.py`: climate forcing method
  version 1.1; `lwdown` is a regular forcing unit (no longer scratch-only);
  `provenance.yaml` records the formula, units, and references under
  `method.corrections.lwdown`.
- No climate unit had been produced with method 1.0; all seven units
  (`tair`, `prec`, `psurf`, `vp`, `swdown`, `lwdown`, `wind`) are produced
  together with method 1.1, so the extension rule (unchanged code
  fingerprint and method version) applies to all of them from the start.
- `verify_forcing.py`: `lwdown` is recomputed on sample days with cdo
  bilinear `rlds` times an independently coded ratio (relative tolerance
  5e-3); R = 1 within 1e-6 where |dz| < 0.005 m; land-area-weighted global
  mean within 0.5 W m-2 of the 0.5° input; the slope of
  (`lwdown` − bilinear `rlds`) on dz is reported (expected −25 to
  −50 W m-2 km-1).
- The method-1.0 `lwdown` test output of 2015 stays in
  `scratch/climate-forcing/` until the user releases it.

## References

- Cosgrove, B. A., et al. (2003): Real-time and retrospective forcing in the
  North American Land Data Assimilation System (NLDAS) project, J. Geophys.
  Res., 108(D22), 8842, doi:10.1029/2002JD003118.
- Cucchi, M., et al. (2020): WFDE5: bias-adjusted ERA5 reanalysis data for
  impact studies, Earth Syst. Sci. Data, 12, 2097–2120.
- Fiddes, J., and Gruber, S. (2014): TopoSCALE v.1.0, Geosci. Model Dev., 7,
  387–405.
- Konzelmann, T., et al. (1994): Parameterization of global and longwave
  incoming radiation for the Greenland Ice Sheet, Global Planet. Change, 9,
  143–164.
- Liston, G. E., and Elder, K. (2006): A meteorological distribution system
  for high-resolution terrestrial modeling (MicroMet), J. Hydrometeorol., 7,
  217–234.
- Marty, C., et al. (2002): Altitude dependence of surface radiation fluxes
  and cloud forcing in the Alps, Theor. Appl. Climatol., 72, 137–155.
- Satterlund, D. R. (1979): An improved equation for estimating long-wave
  radiation from the atmosphere, Water Resour. Res., 15(6), 1649–1650.
- Weedon, G. P., et al. (2010): The WATCH forcing data 1958–2001, WATCH
  Technical Report 22.
