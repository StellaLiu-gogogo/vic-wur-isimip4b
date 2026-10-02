#!/usr/bin/env python3
"""Area time series 1850-2100 of the land-use visualisation, made only from cache/areas.csv.

Products under workdir/analysis/landuse-visualization/figures/timeseries/ (PNG, 1600 px wide, and PDF):
  areas_<region>.png/.pdf    urban, rainfed crop, irrigated crop (VIC 14+15) and paddy, one axis each; one line per
                             soc scenario (histsoc solid to 2021, 1850soc dashed, the three futures from 2022); VIC
                             solid, ISIMIP on the VIC domain thin dotted in the same colour
  stacked_<future>.png/.pdf  VIC only, global: natural, barren, rainfed, irrigated non-paddy, paddy, urban stacked,
                             histsoc 1850-2021 followed by the future scenario 2022-2100

Usage: plot_timeseries.py
"""
import os, sys

import pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lu_vis as lv   # noqa: E402

COLOR = {'histsoc': '#000000', '1850soc': '#777777', '2021soc': '#0072B2', 'ssp1vlsoc-noadapt': '#009E73',
         'ssp3hsoc-noadapt': '#D55E00'}                       # Okabe-Ito
STYLE = {'1850soc': '--'}
TS_GROUPS = ('urban', 'rainfed', 'irrigated', 'paddy')
plt.rcParams.update({'font.size': 13, 'axes.titlesize': 14, 'legend.fontsize': 11})


def series(df, src, soc, group, region):
    s = df[(df.source == src) & (df.soc == soc) & (df.group == group) & (df.region == region)]
    return s.year.values, s.area_Mkm2.values


def areas_figure(df, region, out):
    fig, axs = plt.subplots(2, 2, figsize=(16, 10), dpi=100, sharex=True); axs = axs.ravel()
    for ax, g in zip(axs, TS_GROUPS):
        for soc in lv.SOC:
            x, y = series(df, 'vic', soc, g, region)
            ax.plot(x, y, color=COLOR[soc], ls=STYLE.get(soc, '-'), lw=2.0, label=f'{soc} VIC')
            x, y = series(df, 'isimip_vic_domain', soc, g, region)
            ax.plot(x, y, color=COLOR[soc], ls=':', lw=1.0)
        ax.set_title(f'{lv.LABEL[g]}' + (' (VIC classes 14 + 15)' if g == 'irrigated' else ''), loc='left')
        ax.set_ylabel('area (Mkm²)'); ax.grid(alpha=0.3); ax.set_xlim(1850, 2100); ax.set_ylim(bottom=0)
        ax.axvline(2021.5, color='#bbbbbb', lw=0.8)
    h, l = axs[0].get_legend_handles_labels()
    h.append(plt.Line2D([], [], color='#444444', ls=':', lw=1.0)); l.append('ISIMIP on the VIC domain (each scenario)')
    fig.legend(h, l, loc='lower center', ncol=6, frameon=False)
    fig.suptitle(f'Land-use area, {lv.REGION_LABEL[region]}: VIC-WUR 5′ forcing (solid) and ISIMIP4b 15′ input (dotted; hidden under the solid line where both agree)',
                 x=0.01, ha='left', fontsize=16)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    for ext in ('png', 'pdf'):
        fig.savefig(f'{out}/areas_{region}.{ext}')
    plt.close(fig)


def stacked_figure(df, future, out):
    parts = [('natural', ['natural'], '#009E73'), ('barren', ['barren'], '#BBBBBB'), ('rainfed crop', ['rainfed'], '#E69F00'),
             ('irrigated non-paddy', ['irrigated', '-paddy'], '#56B4E9'), ('irrigated paddy', ['paddy'], '#0072B2'),
             ('urban', ['urban'], '#CC79A7')]
    fig, ax = plt.subplots(figsize=(16, 8), dpi=100)
    ys = []
    for label, gs, col in parts:
        vals = []
        for soc in ('histsoc', future):
            x, y = series(df, 'vic', soc, gs[0], 'global')
            if len(gs) > 1:
                _, p = series(df, 'vic', soc, 'paddy', 'global'); y = y - p
            vals.append((x, y))
        x = list(vals[0][0]) + list(vals[1][0]); y = list(vals[0][1]) + list(vals[1][1]); ys.append((label, y, col))
    ax.stackplot(x, [y for _, y, _ in ys], labels=[l for l, _, _ in ys], colors=[c for _, _, c in ys], alpha=0.9)
    ax.axvline(2021.5, color='#333333', lw=0.8); ax.text(2023, ax.get_ylim()[1] * 0.97, future, va='top', fontsize=12)
    ax.text(1852, ax.get_ylim()[1] * 0.97, 'histsoc', va='top', fontsize=12)
    ax.set_xlim(1850, 2100); ax.set_ylabel('area (Mkm²)'); ax.grid(alpha=0.3)
    ax.legend(loc='lower left', ncol=6, frameon=True)
    ax.set_title(f'VIC-WUR 5′ land-use forcing, global area by group: histsoc 1850–2021, {future} 2022–2100', loc='left')
    fig.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(f'{out}/stacked_{future}.{ext}')
    plt.close(fig)


def main():
    df = pd.read_csv(f'{lv.products()}/cache/areas.csv')
    out = f'{lv.products()}/figures/timeseries'; os.makedirs(out, exist_ok=True)
    for r in ['global'] + list(lv.REGIONS):
        areas_figure(df, r, out); print(f'areas_{r}', flush=True)
    for f in lv.FUTURES:
        stacked_figure(df, f, out); print(f'stacked_{f}', flush=True)


if __name__ == '__main__':
    main()
