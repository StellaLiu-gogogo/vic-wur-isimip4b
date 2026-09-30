#!/usr/bin/env python
"""Figures for the analysis task ``isimip-mask-coverage`` (decision D08).

Reads the cell-wise comparison NetCDF files written by ``compare_masks.py``
and writes PNG figures to ``<out>/figures/``. Only matplotlib is used (no
cartopy on Anunna); coastlines are implied by the masks themselves.

Usage:
  python plot_maps.py [--scratch]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

TASK_ID = "isimip-mask-coverage"

# category colours (same codes as compare_masks.CAT)
CAT_COLOURS = {
    0: ("#d9e6f2", "ocean / not in ISIMIP mask"),
    1: ("#bfbfbf", "covered, all 36 VIC cells active"),
    2: ("#7f7f7f", "covered, 1-35 VIC cells active"),
    3: ("#7b3294", "uncovered: Greenland (VIC land template, inactive)"),
    4: ("#0571b0", "uncovered: Arctic islands and coasts (>= 60N)"),
    5: ("#008837", "uncovered: inland (8 land neighbours)"),
    6: ("#e66101", "uncovered: coastal (1-7 land neighbours)"),
    7: ("#d7191c", "uncovered: isolated island (0 land neighbours)"),
    8: ("#000000", "uncovered: outside VIC latitude range"),
}
OUTSIDE_COLOUR = "#ffff00"  # VIC active cells outside the mask


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scratch", action="store_true", help="read from and write to workdir/scratch/%s/" % TASK_ID)
    args = ap.parse_args()
    w = os.environ.get("ISIMIP4B_WORKDIR")
    if not w:
        sys.exit("ISIMIP4B_WORKDIR is not set")
    out = Path(w) / ("scratch" if args.scratch else "analysis") / TASK_ID
    fig_dir = out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    ds = xr.open_dataset(out / "cellwise_comparison_0p5deg.nc")
    lat = ds["lat"].values
    lon = ds["lon"].values
    cat = ds["category"].values.astype(int)
    n_out = ds["vic_active_cells_outside_mask"].values
    n_act = ds["vic_active_cells"].values
    m_wg = ds["isimip_mask_water_global"].values == 1
    extent = [lon[0] - 0.25, lon[-1] + 0.25, lat[-1] - 0.25, lat[0] + 0.25]

    codes = sorted(CAT_COLOURS)
    cmap = ListedColormap([CAT_COLOURS[c][0] for c in codes])
    norm = BoundaryNorm([c - 0.5 for c in codes] + [codes[-1] + 0.5], cmap.N)

    def draw(ax, box=None, show_outside=True, title=""):
        ax.imshow(cat, cmap=cmap, norm=norm, extent=extent, interpolation="nearest", aspect="auto", origin="upper")
        if show_outside:
            yy, xx = np.where(n_out > 0)
            ax.scatter(lon[xx], lat[yy], s=4 if box is None else 30, c=OUTSIDE_COLOUR, marker="s",
                       edgecolors="k", linewidths=0.2 if box is None else 0.4, zorder=3)
        if box is not None:
            ax.set_xlim(box[0], box[1])
            ax.set_ylim(box[2], box[3])
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_title(title)

    legend = [Patch(facecolor=CAT_COLOURS[c][0], edgecolor="k", label=CAT_COLOURS[c][1]) for c in codes if c != 8]
    legend.append(Patch(facecolor=OUTSIDE_COLOUR, edgecolor="k", label="0.5 degree cell outside the mask with active VIC cells"))

    # 1. global map
    fig, ax = plt.subplots(figsize=(16, 8.5))
    draw(ax, title="ISIMIP water_global mask versus VIC-WUR 5' domain: category of each 0.5 degree cell")
    ax.axhline(84, color="k", lw=0.6, ls="--")
    ax.axhline(-56, color="k", lw=0.6, ls="--")
    ax.text(-178, 85, "VIC domain extent: 56S-84N", fontsize=8)
    ax.legend(handles=legend, loc="lower left", fontsize=8, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(fig_dir / "map_global_categories.png", dpi=150)
    plt.close(fig)

    # 2. Arctic zoom (Greenland and Arctic islands)
    fig, ax = plt.subplots(figsize=(14, 7))
    draw(ax, box=(-140, 110, 55, 85), title="Arctic zoom: Greenland, Canadian Arctic Archipelago, Svalbard, Russian Arctic islands")
    ax.legend(handles=legend, loc="lower left", fontsize=7, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(fig_dir / "map_arctic_zoom.png", dpi=150)
    plt.close(fig)

    # 3. zooms on regions with uncovered cells south of 60N
    zooms = [
        ("caspian_aral", (40, 70, 30, 50), "Caspian and Aral Sea region"),
        ("southeast_asia_pacific", (90, 180, -25, 30), "South-East Asia and western Pacific islands"),
        ("caribbean_atlantic", (-100, -20, 0, 40), "Caribbean and tropical Atlantic"),
        ("indian_ocean", (30, 100, -30, 30), "Indian Ocean islands and coasts"),
        ("southern_ocean", (-180, 180, -56, -30), "Southern mid-latitudes and sub-Antarctic islands"),
    ]
    for name, box, title in zooms:
        fig, ax = plt.subplots(figsize=(14, 7))
        draw(ax, box=box, title=title)
        ax.legend(handles=legend, loc="lower left", fontsize=7, framealpha=0.95)
        fig.tight_layout()
        fig.savefig(fig_dir / f"map_zoom_{name}.png", dpi=150)
        plt.close(fig)

    # 4. active VIC cells per ISIMIP cell (0-36) and histogram
    fig, axes = plt.subplots(1, 2, figsize=(18, 6), gridspec_kw=dict(width_ratios=[3, 1.2]))
    shown = np.where(m_wg, n_act, np.nan).astype(float)
    im = axes[0].imshow(shown, cmap="viridis", vmin=0, vmax=36, extent=extent, interpolation="nearest", aspect="auto", origin="upper")
    axes[0].set_title("number of active VIC 5' cells per ISIMIP mask cell (0-36)")
    axes[0].set_xlabel("longitude")
    axes[0].set_ylabel("latitude")
    fig.colorbar(im, ax=axes[0], fraction=0.03, pad=0.02)
    hist = pd.read_csv(out / "tables" / "histogram_active_cells_per_isimip_cell.csv")
    axes[1].bar(hist["vic_active_cells"], hist["isimip_cells"], color="#4d4d4d")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("active VIC cells in the 0.5 degree cell")
    axes[1].set_ylabel("number of ISIMIP mask cells (log)")
    axes[1].set_title("distribution over the 67 420 mask cells")
    for x in (0, 36):
        v = int(hist.loc[hist["vic_active_cells"] == x, "isimip_cells"].iloc[0])
        axes[1].annotate(str(v), (x, v), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "map_active_cells_per_isimip_cell.png", dpi=150)
    plt.close(fig)

    # 5. candidate contfrac from the current VIC domain over the mask
    fig, ax = plt.subplots(figsize=(16, 8))
    cf = np.where(m_wg, ds["vic_active_area_fraction"].values, np.nan)
    im = ax.imshow(cf, cmap="YlGnBu", vmin=0, vmax=1, extent=extent, interpolation="nearest", aspect="auto", origin="upper")
    ax.set_title("active VIC area / 0.5 degree cell area on ISIMIP mask cells (candidate contfrac; 0 = uncovered)")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    fig.tight_layout()
    fig.savefig(fig_dir / "map_vic_area_fraction.png", dpi=150)
    plt.close(fig)

    # 6. latitude profile
    band = pd.read_csv(out / "tables" / "summary_by_latitude_band.csv")
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(band))
    ax.bar(x - 0.2, band["uncovered"], width=0.4, label="ISIMIP mask cells without active VIC cell", color="#d7191c")
    ax.bar(x + 0.2, band["vic_outside_cells_0p5"], width=0.4, label="0.5 degree cells outside the mask with active VIC cells", color="#e6c700", edgecolor="k")
    ax.set_xticks(x)
    ax.set_xticklabels(band["lat_band"], rotation=60, fontsize=8)
    ax.set_ylabel("number of 0.5 degree cells")
    ax.set_title("mismatch between the ISIMIP mask and the VIC domain by latitude band")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "bars_mismatch_by_latitude.png", dpi=150)
    plt.close(fig)

    print("figures written to", fig_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
