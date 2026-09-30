#!/usr/bin/env python
"""Compare the ISIMIP water_global land-sea mask with the VIC-WUR 5 arcmin domain.

Analysis task ``isimip-mask-coverage`` (decision D08). The script answers,
with numbers, four questions:

1. Grid relation: is the VIC 5' grid an exact 6 x 6 subdivision of the
   ISIMIP 0.5 degree grid (coordinates, orientation, offsets)?
2. Coverage: for every ISIMIP mask cell, how many of its 36 VIC cells are
   active; which ISIMIP cells have no active VIC cell, and where are they?
3. The reverse: which VIC active cells lie outside the ISIMIP mask?
4. Cell counts for the D08 options (keep, full extension, partial extension).

Inputs (all read-only):
  raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_water-global.nc
  raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask.nc
  raw/ISIMIP4b/InputData/geo_conditions/landseamask/landseamask_no-ant.nc
  parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc
  optional: one VIC coverage file (raw/external/vic-coverage-version-a/5/)

Outputs (workdir/analysis/isimip-mask-coverage/, or scratch with --scratch):
  cellwise_comparison_0p5deg.nc   per ISIMIP 0.5 degree cell
  cellwise_comparison_5arcmin.nc  per VIC 5' cell
  tables/*.csv, tables/summary.json, tables/summary.md

The VIC domain file carries two land definitions: ``mask`` (active cells,
Greenland removed) and ``frac`` (1 on every land cell of the original
template, including Greenland). The difference is the Greenland land that
was made inactive; it is used here as the "VIC land template".

Usage:
  python compare_masks.py [--scratch] [--coverage FILE]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

TASK_ID = "isimip-mask-coverage"
EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius, only for cells outside the VIC extent
COARSE_RES = 0.5
FINE_RES = 1.0 / 12.0
NSUB = 6  # fine cells per coarse cell along one axis

# Category codes of ISIMIP mask cells (0.5 degree)
CAT = {
    0: "not_in_isimip_mask",
    1: "covered_full",             # all 36 VIC cells active
    2: "covered_partial",          # 1-35 VIC cells active
    3: "uncovered_greenland",      # VIC land template exists, made inactive (Greenland policy)
    4: "uncovered_arctic",         # >= 60N, no VIC land at all (Arctic islands and coasts)
    5: "uncovered_inland",         # < 60N, all 8 neighbours are ISIMIP land (inland water, interior)
    6: "uncovered_coastal",        # < 60N, 1-7 ISIMIP land neighbours (coasts, near-shore islands)
    7: "uncovered_isolated",       # < 60N, no ISIMIP land neighbour (isolated small islands)
    8: "uncovered_outside_extent", # outside the VIC latitude range (-56..84)
}

# Status codes of VIC 5' cells
VSTAT = {
    0: "inactive_outside_mask",
    1: "active_in_mask",
    2: "active_outside_mask",
    3: "inactive_template_in_mask",     # Greenland land template inside an ISIMIP cell
    4: "inactive_template_outside_mask",
    5: "inactive_no_template_in_mask",  # ISIMIP land, VIC has no land information at 5'
}

# Named regions used only for the "where" column of the tables (coarse boxes,
# checked in this order; Greenland is identified by the VIC land template).
REGIONS = [
    # Arctic
    ("greenland", 59.5, 84.0, -75.0, -10.0),          # coast cells without a VIC land template
    ("canadian_arctic_archipelago", 60.0, 84.0, -130.0, -60.0),
    ("svalbard", 76.0, 81.0, 9.0, 36.0),
    ("franz_josef_land", 79.5, 82.0, 44.0, 66.0),
    ("novaya_zemlya", 70.0, 77.5, 50.0, 70.0),
    ("severnaya_zemlya", 78.0, 81.5, 90.0, 108.0),
    ("kara_sea_islands", 73.0, 81.0, 70.0, 90.0),
    ("new_siberian_islands", 73.0, 77.0, 135.0, 160.0),
    ("iceland", 63.0, 67.0, -25.0, -13.0),
    ("jan_mayen", 70.5, 71.5, -9.5, -7.5),
    # inland waters
    ("caspian_sea", 36.0, 47.5, 46.0, 55.0),
    ("aral_sea", 43.5, 47.0, 58.0, 62.0),
    ("lake_ladoga_onega", 60.0, 62.5, 29.5, 36.5),
    ("great_lakes", 41.0, 49.5, -93.0, -76.0),
    ("lake_victoria", -3.5, 1.0, 31.5, 35.0),
    ("hudson_bay", 51.0, 64.0, -95.0, -76.0),
    ("baltic_sea", 53.5, 66.0, 10.0, 30.0),
    # oceanic islands
    ("hawaii", 18.5, 22.5, -161.0, -154.5),
    ("cape_verde", 14.5, 17.5, -25.5, -22.5),
    ("azores", 36.5, 40.0, -31.5, -24.5),
    ("madeira", 32.0, 33.5, -17.5, -16.0),
    ("canary_islands", 27.5, 29.5, -18.5, -13.0),
    ("bermuda", 32.0, 33.0, -65.0, -64.0),
    ("galapagos", -1.5, 0.7, -92.0, -89.0),
    ("mascarene_islands", -21.5, -19.5, 55.0, 58.0),
    ("seychelles", -10.0, -3.5, 46.0, 56.5),
    ("maldives_chagos", -8.0, 8.0, 71.0, 74.0),
    ("socotra", 12.0, 13.0, 53.0, 54.5),
    ("kerguelen_crozet_heard", -54.0, -45.5, 50.0, 74.0),
    ("south_georgia_sandwich", -60.0, -53.5, -38.5, -25.5),
    ("falkland_islands", -53.0, -51.0, -61.5, -57.5),
    ("st_helena_ascension", -16.5, -7.0, -15.0, -5.0),
    ("tristan_da_cunha_gough", -41.0, -37.0, -13.0, -9.0),
    ("fiji_tonga_samoa", -22.0, -12.0, 176.0, 180.0),
    ("fiji_tonga_samoa", -22.0, -12.0, -180.0, -168.0),
    ("french_polynesia_cook", -28.0, -7.0, -166.0, -134.0),
    ("kiribati_line_phoenix", -12.0, 5.0, -178.0, -150.0),
    ("micronesia_melanesia", -11.0, 15.0, 130.0, 176.0),
    ("bonin_volcano_islands", 24.0, 28.0, 140.0, 143.0),
    ("aleutian_islands", 51.0, 55.0, -180.0, -160.0),
    ("aleutian_islands", 51.0, 55.0, 165.0, 180.0),
    ("sub_antarctic_pacific", -56.0, -45.0, 150.0, 180.0),
]


def workdir() -> Path:
    w = os.environ.get("ISIMIP4B_WORKDIR")
    if not w:
        sys.exit("ISIMIP4B_WORKDIR is not set")
    return Path(w)


def region_name(lat: float, lon: float, greenland: bool) -> str:
    if greenland:
        return "greenland"
    for name, la0, la1, lo0, lo1 in REGIONS:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return "other"


def coarse_cell_area_km2(lat_c: np.ndarray, dlat: float = COARSE_RES, dlon: float = COARSE_RES) -> np.ndarray:
    """Spherical area of a lat/lon cell per latitude row (km2)."""
    phi1 = np.deg2rad(lat_c - dlat / 2)
    phi2 = np.deg2rad(lat_c + dlat / 2)
    return (EARTH_RADIUS_KM ** 2) * np.deg2rad(dlon) * (np.sin(phi2) - np.sin(phi1))


def neighbour_count(mask: np.ndarray) -> np.ndarray:
    """Number of the 8 neighbours that are True; longitude wraps, latitude is clipped."""
    m = mask.astype(np.int16)
    padded = np.pad(m, ((1, 1), (0, 0)), mode="constant")
    padded = np.pad(padded, ((0, 0), (1, 1)), mode="wrap")
    out = np.zeros_like(m)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            out += padded[1 + di:1 + di + m.shape[0], 1 + dj:1 + dj + m.shape[1]]
    return out


def check_grid_relation(isimip: xr.Dataset, vic: xr.Dataset) -> dict:
    """Question 1: coordinates, spacing, orientation and the 6 x 6 block mapping."""
    clat = isimip["lat"].values
    clon = isimip["lon"].values
    flat = vic["lat"].values
    flon = vic["lon"].values
    res: dict = {}
    res["isimip_shape"] = [int(clat.size), int(clon.size)]
    res["vic_shape"] = [int(flat.size), int(flon.size)]
    res["isimip_lat_first_last"] = [float(clat[0]), float(clat[-1])]
    res["isimip_lon_first_last"] = [float(clon[0]), float(clon[-1])]
    res["vic_lat_first_last"] = [float(flat[0]), float(flat[-1])]
    res["vic_lon_first_last"] = [float(flon[0]), float(flon[-1])]
    res["isimip_lat_orientation"] = "north_to_south" if clat[0] > clat[-1] else "south_to_north"
    res["vic_lat_orientation"] = "north_to_south" if flat[0] > flat[-1] else "south_to_north"
    # ideal coordinates
    ideal_clat = 90.0 - COARSE_RES * (np.arange(clat.size) + 0.5)
    ideal_clon = -180.0 + COARSE_RES * (np.arange(clon.size) + 0.5)
    res["isimip_lat_max_abs_dev_from_ideal_deg"] = float(np.abs(clat - ideal_clat).max())
    res["isimip_lon_max_abs_dev_from_ideal_deg"] = float(np.abs(clon - ideal_clon).max())
    lat0 = np.round((flat[0] - FINE_RES / 2) * 2) / 2  # southern edge rounded to 0.5 degree
    ideal_flat = lat0 + FINE_RES * (np.arange(flat.size) + 0.5)
    ideal_flon = -180.0 + FINE_RES * (np.arange(flon.size) + 0.5)
    res["vic_south_edge_deg"] = float(lat0)
    res["vic_north_edge_deg"] = float(lat0 + FINE_RES * flat.size)
    res["vic_lat_max_abs_dev_from_ideal_deg"] = float(np.abs(flat - ideal_flat).max())
    res["vic_lon_max_abs_dev_from_ideal_deg"] = float(np.abs(flon - ideal_flon).max())
    res["vic_lat_spacing_min_max_deg"] = [float(np.diff(flat).min()), float(np.diff(flat).max())]
    res["vic_lon_spacing_min_max_deg"] = [float(np.diff(flon).min()), float(np.diff(flon).max())]
    # mapping of fine rows/columns to coarse rows/columns
    j_row = np.floor((90.0 - flat) / COARSE_RES).astype(int)   # coarse row (N->S index)
    j_col = np.floor((flon + 180.0) / COARSE_RES).astype(int)
    rows, counts = np.unique(j_row, return_counts=True)
    cols, ccounts = np.unique(j_col, return_counts=True)
    res["fine_rows_per_coarse_row_min_max"] = [int(counts.min()), int(counts.max())]
    res["fine_cols_per_coarse_col_min_max"] = [int(ccounts.min()), int(ccounts.max())]
    res["coarse_row_range_covered_by_vic"] = [int(rows.min()), int(rows.max())]
    res["coarse_rows_covered_by_vic"] = int(rows.size)
    res["coarse_cols_covered_by_vic"] = int(cols.size)
    # edges of fine cells must lie inside the coarse cell
    edge_ok = np.all(np.floor((90.0 - (flat + FINE_RES / 2 - 1e-9)) / COARSE_RES) == j_row) and np.all(
        np.floor((90.0 - (flat - FINE_RES / 2 + 1e-9)) / COARSE_RES) == j_row)
    res["fine_cells_nested_in_coarse_cells"] = bool(edge_ok and counts.min() == NSUB and counts.max() == NSUB
                                                    and ccounts.min() == NSUB and ccounts.max() == NSUB)
    res["exact_6x6_subdivision"] = bool(res["fine_cells_nested_in_coarse_cells"]
                                        and res["vic_lat_max_abs_dev_from_ideal_deg"] < 1e-6
                                        and res["vic_lon_max_abs_dev_from_ideal_deg"] < 1e-6
                                        and res["isimip_lat_max_abs_dev_from_ideal_deg"] < 1e-6
                                        and res["isimip_lon_max_abs_dev_from_ideal_deg"] < 1e-6)
    return res


def df_to_md(df: pd.DataFrame) -> str:
    """Render a small DataFrame as a Markdown table without extra dependencies."""
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = [f"{v:.4g}" if isinstance(v, float) else str(v) for v in r.values]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def block_sum(fine_ns: np.ndarray) -> np.ndarray:
    """Sum a fine (N->S ordered) array over 6 x 6 blocks."""
    ny, nx = fine_ns.shape
    return fine_ns.reshape(ny // NSUB, NSUB, nx // NSUB, NSUB).sum(axis=(1, 3))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scratch", action="store_true",
                    help="write to workdir/scratch/%s/ instead of workdir/analysis/%s/" % (TASK_ID, TASK_ID))
    ap.add_argument("--coverage", type=Path, default=None,
                    help="optional VIC coverage file (16 classes at 5'); counts new cells with vegetation data")
    args = ap.parse_args()

    w = workdir()
    out = w / ("scratch" if args.scratch else "analysis") / TASK_ID
    tables = out / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    mask_dir = w / "raw/ISIMIP4b/InputData/geo_conditions/landseamask"
    domain_file = w / "parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc"

    # ---- load ------------------------------------------------------------------
    wg = xr.open_dataset(mask_dir / "landseamask_water-global.nc", decode_times=False)
    w5 = xr.open_dataset(mask_dir / "landseamask.nc", decode_times=False)
    na = xr.open_dataset(mask_dir / "landseamask_no-ant.nc", decode_times=False)
    vic = xr.open_dataset(domain_file, mask_and_scale=False)

    m_wg = (wg["mask"].squeeze(drop=True).fillna(0).values == 1)
    m_w5 = (w5["mask"].squeeze(drop=True).fillna(0).values == 1)
    m_na = (na["mask"].squeeze(drop=True).fillna(0).values == 1)
    for name, ds in (("landseamask.nc", w5), ("landseamask_no-ant.nc", na)):
        if not (np.allclose(ds["lat"].values, wg["lat"].values) and np.allclose(ds["lon"].values, wg["lon"].values)):
            sys.exit(f"{name} is not on the water-global grid")

    clat = wg["lat"].values
    clon = wg["lon"].values
    flat = vic["lat"].values
    flon = vic["lon"].values

    vmask = vic["mask"].values          # int32, _FillValue 0 -> inactive
    vfrac = vic["frac"].values          # float32, 1 on land template, fill elsewhere
    varea = vic["area"].values          # m2, defined on every cell
    active = vmask == 1
    template = (vfrac > 0) & (vfrac <= 1)
    if not np.all(template[active]):
        sys.exit("unexpected: active VIC cell outside the land template")

    # ---- question 1 -------------------------------------------------------------
    grid = check_grid_relation(wg, vic)
    if not grid["fine_cells_nested_in_coarse_cells"]:
        sys.exit("VIC cells are not nested in ISIMIP cells; the block logic below would be wrong")

    # flip VIC to N->S, then 6x6 blocks
    ns = slice(None, None, -1)
    r0, r1 = grid["coarse_row_range_covered_by_vic"]
    r1 += 1
    n_active_blk = block_sum(active[ns].astype(np.int32))
    n_template_blk = block_sum(template[ns].astype(np.int32))
    area_total_blk = block_sum(varea[ns].astype(np.float64)) / 1e6
    area_active_blk = block_sum(np.where(active, varea, 0.0)[ns].astype(np.float64)) / 1e6
    area_template_blk = block_sum(np.where(template, varea, 0.0)[ns].astype(np.float64)) / 1e6

    full = lambda blk, fill=0: np.pad(blk, ((r0, clat.size - r1), (0, 0)), constant_values=fill)  # noqa: E731
    n_active = full(n_active_blk)
    n_template = full(n_template_blk)
    n_tmpl_inactive = n_template - n_active   # land template made inactive (Greenland)
    area_active = full(area_active_blk, 0.0)
    area_template = full(area_template_blk, 0.0)
    in_extent = np.zeros(clat.size, dtype=bool)
    in_extent[r0:r1] = True
    in_extent2d = np.broadcast_to(in_extent[:, None], m_wg.shape)
    # cell area: VIC sum inside the extent, spherical formula outside
    area_cell = np.broadcast_to(coarse_cell_area_km2(clat)[:, None], m_wg.shape).copy()
    area_vic_sum = full(area_total_blk, np.nan)
    area_dev = np.nanmax(np.abs(area_vic_sum[in_extent2d] - area_cell[in_extent2d]) / area_cell[in_extent2d])
    area_cell[in_extent2d] = area_vic_sum[in_extent2d]

    # ---- question 2: categories of ISIMIP cells ------------------------------------
    nb = neighbour_count(m_wg)
    lat2d = np.broadcast_to(clat[:, None], m_wg.shape)
    lon2d = np.broadcast_to(clon[None, :], m_wg.shape)
    cat = np.zeros(m_wg.shape, dtype=np.int8)
    covered = m_wg & (n_active > 0)
    cat[covered & (n_active == NSUB * NSUB)] = 1
    cat[covered & (n_active < NSUB * NSUB)] = 2
    unc = m_wg & (n_active == 0)
    cat[unc & ~in_extent2d] = 8
    u = unc & in_extent2d
    cat[u & (n_template > 0)] = 3
    u2 = u & (n_template == 0)
    cat[u2 & (lat2d >= 60.0)] = 4
    u3 = u2 & (lat2d < 60.0)
    cat[u3 & (nb == 8)] = 5
    cat[u3 & (nb >= 1) & (nb <= 7)] = 6
    cat[u3 & (nb == 0)] = 7
    assert np.all((cat > 0) == m_wg)

    # ---- question 3: VIC active cells outside the mask -----------------------------
    parent_in_mask = np.repeat(np.repeat(m_wg[r0:r1], NSUB, axis=0), NSUB, axis=1)[ns]  # back to S->N
    vstat = np.zeros(active.shape, dtype=np.int8)
    vstat[active & parent_in_mask] = 1
    vstat[active & ~parent_in_mask] = 2
    vstat[~active & template & parent_in_mask] = 3
    vstat[~active & template & ~parent_in_mask] = 4
    vstat[~active & ~template & parent_in_mask] = 5
    n_outside_blk = block_sum((vstat == 2)[ns].astype(np.int32))
    area_outside_blk = block_sum(np.where(vstat == 2, varea, 0.0)[ns].astype(np.float64)) / 1e6
    n_outside = full(n_outside_blk)
    area_outside = full(area_outside_blk, 0.0)

    # optional: vegetation coverage available on 5' cells?
    cov_has_data = None
    if args.coverage is not None:
        cov = xr.open_dataset(args.coverage, mask_and_scale=True)
        cname = [v for v in cov.data_vars if set(cov[v].dims) >= {"lat", "lon"} and cov[v].ndim >= 3]
        if not cname:
            sys.exit("no coverage variable found in %s" % args.coverage)
        c = cov[cname[0]]
        c = c.sum(dim=[d for d in c.dims if d not in ("lat", "lon")], skipna=True)
        if not (np.allclose(c["lat"].values, flat) and np.allclose(c["lon"].values, flon)):
            sys.exit("coverage file is not on the VIC grid")
        cov_has_data = c.values > 0
        n_cov_blk = block_sum(cov_has_data[ns].astype(np.int32))
        n_cov = full(n_cov_blk)

    # ---- tables ---------------------------------------------------------------------
    is_greenland = n_template > 0
    rows = []
    for (i, j) in zip(*np.where(m_wg & (cat >= 3))):
        rows.append(dict(lat=float(clat[i]), lon=float(clon[j]), category=CAT[int(cat[i, j])],
                         region=region_name(clat[i], clon[j], bool(is_greenland[i, j])),
                         isimip_land_neighbours=int(nb[i, j]), vic_land_template_cells=int(n_template[i, j]),
                         cell_area_km2=float(area_cell[i, j]), in_w5e5_mask=bool(m_w5[i, j]),
                         in_no_ant_mask=bool(m_na[i, j]),
                         coverage_cells=(int(n_cov[i, j]) if cov_has_data is not None else np.nan)))
    unc_df = pd.DataFrame(rows).sort_values(["category", "lat", "lon"], ascending=[True, False, True])
    unc_df.to_csv(tables / "uncovered_isimip_cells.csv", index=False, float_format="%.6g")

    rows = []
    for (i, j) in zip(*np.where(n_outside > 0)):
        rows.append(dict(lat=float(clat[i]), lon=float(clon[j]), vic_active_cells=int(n_outside[i, j]),
                         vic_active_area_km2=float(area_outside[i, j]), cell_area_km2=float(area_cell[i, j]),
                         vic_active_share=float(area_outside[i, j] / area_cell[i, j]),
                         isimip_land_neighbours=int(nb[i, j]), region=region_name(clat[i], clon[j], False),
                         in_w5e5_mask=bool(m_w5[i, j]), in_no_ant_mask=bool(m_na[i, j])))
    out_df = pd.DataFrame(rows).sort_values(["lat", "lon"], ascending=[False, True])
    out_df.to_csv(tables / "vic_active_outside_mask_cells.csv", index=False, float_format="%.6g")

    # per-category summary
    cat_rows = []
    for code, name in CAT.items():
        if code == 0:
            continue
        sel = cat == code
        cat_rows.append(dict(code=code, category=name, isimip_cells=int(sel.sum()),
                             cell_area_km2=float(area_cell[sel].sum()),
                             vic_active_cells=int(n_active[sel].sum()),
                             vic_land_template_cells=int(n_template[sel].sum()),
                             coverage_cells=(int(n_cov[sel].sum()) if cov_has_data is not None else np.nan)))
    cat_df = pd.DataFrame(cat_rows)
    cat_df.to_csv(tables / "isimip_cell_categories.csv", index=False, float_format="%.6g")

    reg_df = (unc_df.groupby(["category", "region"]).agg(isimip_cells=("lat", "size"),
                                                          cell_area_km2=("cell_area_km2", "sum"),
                                                          vic_land_template_cells=("vic_land_template_cells", "sum"))
              .reset_index())
    reg_df.to_csv(tables / "uncovered_by_region.csv", index=False, float_format="%.6g")
    reg_out = (out_df.groupby("region").agg(isimip_cells=("lat", "size"), vic_active_cells=("vic_active_cells", "sum"),
                                            vic_active_area_km2=("vic_active_area_km2", "sum")).reset_index())
    reg_out.to_csv(tables / "vic_outside_by_region.csv", index=False, float_format="%.6g")

    # latitude-band summary (10 degree bands)
    bands = np.arange(-90, 91, 10)
    band_rows = []
    for b0, b1 in zip(bands[:-1], bands[1:]):
        sel = (lat2d >= b0) & (lat2d < b1)
        band_rows.append(dict(lat_band=f"{b0}..{b1}", isimip_cells=int((m_wg & sel).sum()),
                              covered=int((covered & sel).sum()), uncovered=int((unc & sel).sum()),
                              uncovered_area_km2=float(area_cell[unc & sel].sum()),
                              vic_outside_cells_0p5=int(((n_outside > 0) & sel).sum()),
                              vic_outside_cells_5arcmin=int(n_outside[sel].sum())))
    pd.DataFrame(band_rows).to_csv(tables / "summary_by_latitude_band.csv", index=False, float_format="%.6g")

    # histogram of active VIC cells per ISIMIP mask cell
    hist = np.bincount(n_active[m_wg], minlength=NSUB * NSUB + 1)
    pd.DataFrame(dict(vic_active_cells=np.arange(NSUB * NSUB + 1), isimip_cells=hist)).to_csv(
        tables / "histogram_active_cells_per_isimip_cell.csv", index=False)

    # comparison of the three ISIMIP masks
    mask_rows = []
    for name, m in (("landseamask_water-global", m_wg), ("landseamask", m_w5), ("landseamask_no-ant", m_na)):
        mask_rows.append(dict(mask=name, cells=int(m.sum()), area_km2=float(area_cell[m].sum()),
                              in_water_global=int((m & m_wg).sum()), not_in_water_global=int((m & ~m_wg).sum()),
                              water_global_not_in_this=int((m_wg & ~m).sum()),
                              cells_with_vic_active=int((m & (n_active > 0)).sum()),
                              cells_without_vic_active=int((m & (n_active == 0)).sum()),
                              lat_min=float(lat2d[m].min()), lat_max=float(lat2d[m].max())))
    pd.DataFrame(mask_rows).to_csv(tables / "isimip_masks_comparison.csv", index=False, float_format="%.6g")

    # ---- option counts ------------------------------------------------------------
    n_unc = int(unc.sum())
    n36 = NSUB * NSUB
    def opt(sel):
        sel = sel & unc
        with_t = sel & (n_template > 0)
        without = sel & (n_template == 0)
        d = dict(isimip_cells=int(sel.sum()), cell_area_km2=float(area_cell[sel].sum()),
                 isimip_cells_with_vic_template=int(with_t.sum()),
                 new_5arcmin_cells_from_vic_template=int(n_template[with_t].sum()),
                 isimip_cells_without_5arcmin_land_info=int(without.sum()),
                 new_5arcmin_cells_if_one_per_cell=int(without.sum()),
                 new_5arcmin_cells_if_all_36=int(without.sum()) * n36)
        d["new_5arcmin_cells_min"] = d["new_5arcmin_cells_from_vic_template"] + d["new_5arcmin_cells_if_one_per_cell"]
        d["new_5arcmin_cells_max"] = d["new_5arcmin_cells_from_vic_template"] + d["new_5arcmin_cells_if_all_36"]
        if cov_has_data is not None:
            d["new_5arcmin_cells_with_coverage_data"] = int(n_cov[sel].sum())
        return d
    options = {
        "a_keep_domain": dict(isimip_cells_reported_missing=n_unc, area_km2=float(area_cell[unc].sum()),
                              share_of_mask_cells=n_unc / int(m_wg.sum()),
                              share_of_mask_area=float(area_cell[unc].sum() / area_cell[m_wg].sum()),
                              vic_active_cells_dropped=int((vstat == 2).sum()),
                              vic_active_area_dropped_km2=float(varea[vstat == 2].sum() / 1e6)),
        "b_full_extension": opt(np.ones_like(unc)),
        "b_full_extension_restore_whole_greenland_template": dict(
            greenland_template_cells_total=int((template & ~active).sum()),
            of_which_in_uncovered_isimip_cells=int(n_tmpl_inactive[unc].sum()),
            of_which_in_covered_isimip_cells=int(n_tmpl_inactive[covered].sum()),
            of_which_outside_isimip_mask=int(n_tmpl_inactive[~m_wg].sum())),
        "c_partial_islands_and_coasts_excluding_greenland": opt(np.isin(cat, [4, 5, 6, 7, 8])),
        "c_partial_below_60N_only": opt(np.isin(cat, [5, 6, 7])),
    }

    summary = dict(
        task=TASK_ID, grid_relation=grid,
        area_check_max_rel_dev_vic_sum_vs_spherical=float(area_dev),
        isimip_mask_cells=int(m_wg.sum()), isimip_mask_area_km2=float(area_cell[m_wg].sum()),
        isimip_mask_lat_min_max=[float(lat2d[m_wg].min()), float(lat2d[m_wg].max())],
        isimip_cells_north_of_vic_extent=int((m_wg & ~in_extent2d & (lat2d > 0)).sum()),
        isimip_cells_south_of_vic_extent=int((m_wg & ~in_extent2d & (lat2d < 0)).sum()),
        vic_active_cells=int(active.sum()), vic_active_area_km2=float(varea[active].sum() / 1e6),
        vic_land_template_cells=int(template.sum()),
        vic_template_inactive_cells=int((template & ~active).sum()),
        isimip_cells_covered=int(covered.sum()), isimip_cells_covered_full=int((cat == 1).sum()),
        isimip_cells_covered_partial=int((cat == 2).sum()), isimip_cells_uncovered=n_unc,
        isimip_cells_uncovered_area_km2=float(area_cell[unc].sum()),
        coarse_cells_with_vic_active=int((n_active > 0).sum()),
        coarse_cells_with_vic_active_outside_mask=int((n_outside > 0).sum()),
        coarse_cells_entirely_outside_mask_with_vic_active=int(((n_outside > 0) & ~m_wg).sum()),
        vic_active_cells_outside_mask=int((vstat == 2).sum()),
        vic_active_area_outside_mask_km2=float(varea[vstat == 2].sum() / 1e6),
        vic_active_cells_in_mask=int((vstat == 1).sum()),
        vic_active_area_in_mask_km2=float(varea[vstat == 1].sum() / 1e6),
        categories={r["category"]: r for r in cat_rows},
        options=options,
        inputs=dict(water_global=str(mask_dir / "landseamask_water-global.nc"),
                    landseamask=str(mask_dir / "landseamask.nc"), no_ant=str(mask_dir / "landseamask_no-ant.nc"),
                    vic_domain=str(domain_file), coverage=(str(args.coverage) if args.coverage else None)),
    )
    (tables / "summary.json").write_text(json.dumps(summary, indent=2))

    # ---- NetCDF outputs -------------------------------------------------------------
    enc = {}
    ds05 = xr.Dataset(
        dict(
            isimip_mask_water_global=(("lat", "lon"), m_wg.astype(np.int8), dict(long_name="ISIMIP water_global land-sea mask", flag_values="0 1")),
            isimip_mask_w5e5=(("lat", "lon"), m_w5.astype(np.int8), dict(long_name="ISIMIP generic land-sea mask (W5E5)")),
            isimip_mask_no_ant=(("lat", "lon"), m_na.astype(np.int8), dict(long_name="ISIMIP land-sea mask without Antarctica")),
            vic_active_cells=(("lat", "lon"), n_active.astype(np.int8), dict(long_name="number of active VIC 5 arcmin cells in the 0.5 degree cell (0-36)")),
            vic_land_template_cells=(("lat", "lon"), n_template.astype(np.int8), dict(long_name="number of VIC land-template cells (frac>0, incl. inactive Greenland) in the 0.5 degree cell")),
            vic_active_area_km2=(("lat", "lon"), area_active.astype(np.float32), dict(units="km2", long_name="area of active VIC cells in the 0.5 degree cell")),
            vic_active_area_fraction=(("lat", "lon"), np.where(area_cell > 0, area_active / area_cell, 0).astype(np.float32), dict(long_name="active VIC area divided by 0.5 degree cell area (candidate contfrac)")),
            vic_active_cells_outside_mask=(("lat", "lon"), n_outside.astype(np.int8), dict(long_name="active VIC cells whose 0.5 degree parent is not in the water_global mask")),
            cell_area_km2=(("lat", "lon"), area_cell.astype(np.float32), dict(units="km2", long_name="0.5 degree cell area (sum of VIC areas inside the VIC extent, spherical formula outside)")),
            isimip_land_neighbours=(("lat", "lon"), nb.astype(np.int8), dict(long_name="number of the 8 neighbours that are water_global mask cells")),
            category=(("lat", "lon"), cat, dict(long_name="comparison category of the 0.5 degree cell",
                                                 flag_values=" ".join(str(k) for k in CAT), flag_meanings=" ".join(CAT.values()))),
            in_vic_extent=(("lat",), in_extent.astype(np.int8), dict(long_name="latitude row lies inside the VIC domain extent")),
        ),
        coords=dict(lat=("lat", clat, dict(units="degrees_north", long_name="latitude")),
                    lon=("lon", clon, dict(units="degrees_east", long_name="longitude"))),
        attrs=dict(title="ISIMIP water_global mask versus VIC-WUR 5 arcmin domain, per 0.5 degree cell",
                   analysis_task=TASK_ID, decision="D08", note="analysis product; not read by any workflow stage"),
    )
    if cov_has_data is not None:
        ds05["vic_coverage_cells"] = (("lat", "lon"), n_cov.astype(np.int8),
                                      dict(long_name="VIC 5 arcmin cells with vegetation coverage data in the 0.5 degree cell"))
    ds05.to_netcdf(out / "cellwise_comparison_0p5deg.nc", encoding={v: dict(zlib=True, complevel=4) for v in ds05.data_vars})

    ds5 = xr.Dataset(
        dict(
            vic_mask=(("lat", "lon"), active.astype(np.int8), dict(long_name="VIC active cell")),
            vic_land_template=(("lat", "lon"), template.astype(np.int8), dict(long_name="VIC land template (frac>0)")),
            isimip_parent_in_mask=(("lat", "lon"), parent_in_mask.astype(np.int8), dict(long_name="the 0.5 degree parent cell is in the water_global mask")),
            status=(("lat", "lon"), vstat, dict(long_name="comparison status of the 5 arcmin cell",
                                                 flag_values=" ".join(str(k) for k in VSTAT), flag_meanings=" ".join(VSTAT.values()))),
            area_km2=(("lat", "lon"), (varea / 1e6).astype(np.float32), dict(units="km2")),
        ),
        coords=dict(lat=("lat", flat, dict(units="degrees_north")), lon=("lon", flon, dict(units="degrees_east"))),
        attrs=dict(title="ISIMIP water_global mask versus VIC-WUR 5 arcmin domain, per 5 arcmin cell",
                   analysis_task=TASK_ID, decision="D08", note="analysis product; not read by any workflow stage"),
    )
    if cov_has_data is not None:
        ds5["vic_coverage_available"] = (("lat", "lon"), cov_has_data.astype(np.int8), dict(long_name="vegetation coverage data present"))
    ds5.to_netcdf(out / "cellwise_comparison_5arcmin.nc", encoding={v: dict(zlib=True, complevel=4) for v in ds5.data_vars})

    # ---- short markdown summary ------------------------------------------------------
    lines = [f"# {TASK_ID}: summary of numbers", "",
             "| Item | Value |", "|---|---|",
             f"| exact 6x6 subdivision | {grid['exact_6x6_subdivision']} |",
             f"| ISIMIP water_global mask cells | {summary['isimip_mask_cells']} |",
             f"| ISIMIP mask cells covered by >=1 active VIC cell | {summary['isimip_cells_covered']} ({summary['isimip_cells_covered']/summary['isimip_mask_cells']:.2%}) |",
             f"| of which all 36 VIC cells active | {summary['isimip_cells_covered_full']} |",
             f"| ISIMIP mask cells with no active VIC cell | {n_unc} ({n_unc/summary['isimip_mask_cells']:.2%}), {summary['isimip_cells_uncovered_area_km2']:.0f} km2 ({summary['options']['a_keep_domain']['share_of_mask_area']:.2%} of mask area) |",
             f"| VIC active cells | {summary['vic_active_cells']} |",
             f"| VIC active cells outside the mask | {summary['vic_active_cells_outside_mask']} ({summary['vic_active_cells_outside_mask']/summary['vic_active_cells']:.2%}), {summary['vic_active_area_outside_mask_km2']:.0f} km2, in {summary['coarse_cells_with_vic_active_outside_mask']} 0.5 degree cells |",
             "", "## ISIMIP cell categories", "", df_to_md(cat_df), "",
             "## Options", ""]
    for k, v in options.items():
        lines.append(f"### {k}")
        lines.append("")
        lines.append("| key | value |")
        lines.append("|---|---|")
        for kk, vv in v.items():
            lines.append(f"| {kk} | {vv:.4g} |" if isinstance(vv, float) else f"| {kk} | {vv} |")
        lines.append("")
    (tables / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines[:12]))
    print("outputs in", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
