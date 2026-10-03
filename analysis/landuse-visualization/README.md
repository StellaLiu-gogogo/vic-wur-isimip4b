# landuse-visualization

## Question

How do the VIC-WUR 5′ land-use forcing units and the ISIMIP4b 15′ land-use
inputs they are made from look, side by side, over 1850–2100 for all soc
scenarios, and where and why do they differ? Products are animated maps,
area time series and a short results note for internal reports to
colleagues.

## Classification

Analysis (user, 2026-10-02): the products are figures for the user's own
reports; no workflow stage reads them.

## Status

closed (user, 2026-10-02): the figures and `report.md` answer the question.

## Inputs (read-only, relative to the workdir)

- `forcing/landuse/<soc>/coverage_<soc>_<year>.nc`, soc `histsoc` and
  `1850soc` (1850–2021), `2021soc`, `ssp1vlsoc-noadapt`,
  `ssp3hsoc-noadapt` (2022–2100): the accepted method 1.3 units (commit
  `d6b42ad`), 581 files.
- `raw/ISIMIP4b/InputData/socioeconomic/landuse/<soc>/landuse-{15crops,urbanareas,totals}_<tag>_15arcmin_annual_<span>.nc`
  (whole-cell fractions; time index = year − first year).
- `parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc`
  (mask; `area` is the WGS84 area of each 5′ cell).
- Natural Earth 1:50m coastline and land boundaries
  (`ne_50m_coastline`, md5 of the `.shp` `ae4cc057c4b7a30256153a427c69c999`;
  `ne_50m_admin_0_boundary_lines_land`, `18b8b116118c860180a50d009f99db97`),
  read from the cartopy data cache of the user's home directory, for the
  map outlines only.

## Common grid and class groups

Everything is drawn on the ISIMIP 15′ grid over the VIC extent (56°S–84°N).
The VIC 5′ grid is an exact 3 × 3 subdivision of it (checked by
`build_cache.py`; VIC latitudes ascend, ISIMIP latitudes descend). VIC
coverage is aggregated to 15′ as the area-weighted mean over the active 5′
cells (a fraction of the active area); the active-area fraction of each 15′
cell is kept in `cache/static.nc`. ISIMIP values are whole-cell fractions.
All areas use WGS84 cell areas on both sides.

| Group | VIC classes | ISIMIP variables |
|---|---|---|
| urban | 13 | `urbanareas` (landuse-urbanareas) |
| rainfed crop | 12 | the 17 `*_rainfed*` variables of landuse-15crops: temperate_cereals, rice, temperate_roots, tropical_roots, oil_crops_sunflower, oil_crops_rapeseed, others_c3ann, maize, tropical_cereals, pulses, oil_crops_soybean, oil_crops_groundnut, others_c3nfx (`*_rainfed`), c3per_rainfed_food, c3per_rainfed_bf, c4per_rainfed_food, c4per_rainfed_bf |
| irrigated crop | 14 + 15 | the 17 `*_irrigated*` variables of landuse-15crops (same crops, incl. rice_irrigated and the `*_irrigated_bf` bioenergy variables) |
| of which paddy | 15 | `rice_irrigated` |
| natural vegetation | 1–11 + 16 in the map comparison (1–11 in the area tables, 16 separately) | `forests_and_natural_vegetation` + `pastures` (landuse-totals; VIC puts pastures into the natural remainder) |
| barren | 16 | no counterpart |

Natural vegetation is compared as VIC 1–11 + 16 against ISIMIP natural +
pastures (user, 2026-10-02), because ISIMIP has no barren class and its
natural share includes barren land. In landuse-totals, cropland_total +
pastures + forests_and_natural_vegetation + urbanareas equals the land
fraction of the cell (129.93 Mkm² globally, every year), and cropland_total
equals the 15crops rainfed + irrigated sums to 2e-7.

## Code

| File | Role |
|---|---|
| `lu_vis.py` | shared definitions: scenarios, groups, regions, frame years, WGS84 cell area |
| `build_cache.py` | reads every input once; writes `cache/areas.csv`, `areas.nc` (area per source, soc, year, group, region), `fields_<source>_<soc>.nc` (15′ fractions of the frame years), `static.nc` |
| `plot_maps.py` | animated maps from the cache (`--draft GROUP YEAR FUTURE` for one frame) |
| `plot_timeseries.py` | area time series and stacked areas from `areas.csv` |
| `write_report.py` | `report.md` and `cache/differences.csv`, `cache/regional_changes.csv` |
| `submit.py` | submits `--step cache` or `--step figures` as a Slurm job; job script and output in `logs/<step>_<job-id>/` |

Area sources in the cache: `vic` (Σ coverage × 5′ area over active cells),
`isimip` (Σ fraction × 15′ area, all cells), `isimip_vic_domain` (the same
over the 15′ cells that contain an active VIC cell: the area the converter
distributes, comparable with `vic`).

Regions (a 15′ cell belongs to a region when its centre is inside):
Europe 35–71°N 10°W–40°E; South Asia 6–36°N 66–92°E; East China 20–42°N
105–123°E; US Midwest / High Plains 33–49°N 105–85°W; Brazil cerrado–Amazon
arc 25–2°S 65–40°W; Sahel / West-Central Africa 5–18°N 18°W–40°E.

Maps: one GIF per class group and future scenario (user choice A,
2026-10-02): histsoc 1850–2020 then the future 2030–2100, every 10 years
(26 frames), 0.5 s per frame and 2 s on the first and last; columns ISIMIP |
VIC | VIC − ISIMIP, a global row and the six regions below. Fixed scales per
group: light-to-dark ColorBrewer maps (urban RdPu up to 0.5, rainfed YlOrBr,
irrigated YlGnBu, natural Greens up to 1) with a square-root stretch,
fractions below 0.001 not coloured; differences RdBu, ±0.2 (±0.5 natural).
Change maps (since 1850 for histsoc frames, since 2021 for future frames)
and dominant-group maps per source.

## Running

```bash
export ISIMIP4B_WORKDIR=/lustre/nobackup/WUR/ESG/liu297/isimip4b/workdir
python3 analysis/landuse-visualization/submit.py --step cache                 # about 12 min, 2.8 GB
python3 analysis/landuse-visualization/submit.py --step figures --mem 64G     # maps, time series, report
```

The cache was built by Slurm job 43009060 (11.7 min wall time, 581 years
with 16 processes, peak 2.8 GB; log in `logs/build-cache_43009060/`).

## Outputs

`workdir/analysis/landuse-visualization/`: `cache/`, `figures/maps/`,
`figures/timeseries/`, `figures/draft/`, `logs/`, `report.md`.

## Conclusion

See `workdir/analysis/landuse-visualization/report.md`. In short: for urban,
rainfed, irrigated and paddy the VIC forcing reproduces the ISIMIP areas on
the VIC domain to within a few km² in every year, scenario and region; map
differences are confined to coastal 15′ cells, where VIC values are
fractions of the active land area. VIC natural + barren exceeds ISIMIP
natural by 6.6 Mkm², the area VIC counts as land where ISIMIP's land
fraction is below 1. No maintained record in `docs/` is needed; the
analysis supports reporting only.
