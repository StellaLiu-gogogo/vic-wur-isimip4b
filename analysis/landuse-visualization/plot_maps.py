#!/usr/bin/env python3
"""Animated 15' maps of the land-use visualisation, made only from the cache of build_cache.py.

Products under workdir/analysis/landuse-visualization/figures/maps/:
  <group>/<future>/frame_<year>.png and <group>_<future>.gif      ISIMIP | VIC | VIC - ISIMIP
  change/<group>/<future>/...  and change_<group>_<future>.gif     fraction minus 1850 (histsoc frames) or minus
                                                                   2021 (future frames), ISIMIP | VIC
  dominant/<future>/... and dominant_<future>.gif                  dominant group per 15' cell, ISIMIP | VIC
Every GIF runs histsoc 1850-2020 and then one future scenario 2030-2100 (26 frames), a global row on top and the
regions of lu_vis.REGIONS below; colour scales are fixed per group across frames, scenarios and sources.

Usage: plot_maps.py --draft GROUP YEAR FUTURE      one frame to figures/draft/
       plot_maps.py [--processes 8]               everything
"""
import argparse, os, sys
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib.collections import LineCollection
from PIL import Image
import cartopy.io.shapereader as shpreader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lu_vis as lv   # noqa: E402

MAP_GROUPS = ('urban', 'rainfed', 'irrigated', 'natural')
MAP_LABEL = {**lv.LABEL, 'natural': 'natural vegetation (VIC 1-11 + 16 barren; ISIMIP natural + pastures)'}
# fixed scales: fractions with a square-root stretch (small urban and irrigated shares stay visible); differences linear
FRAC_VMAX = {'urban': 0.5, 'rainfed': 1.0, 'irrigated': 1.0, 'paddy': 1.0, 'natural': 1.0}
FRAC_NORM = {g: mcolors.PowerNorm(gamma=0.5, vmin=0, vmax=v) for g, v in FRAC_VMAX.items()}
SHOW_MIN = 1e-3          # fractions below this are not coloured (SSP urban has ~1e-6 in almost every land cell)
DIFF_LIM = {'urban': 0.2, 'rainfed': 0.2, 'irrigated': 0.2, 'paddy': 0.2, 'natural': 0.5}


def light_to_dark(name):
    """ColorBrewer sequential map without its near-white end, transparent where there is no data."""
    cm = mcolors.LinearSegmentedColormap.from_list(f'{name}_cut', plt.get_cmap(name)(np.linspace(0.15, 1.0, 256)))
    cm.set_bad((0, 0, 0, 0))
    return cm


FRAC_CMAP = {'urban': light_to_dark('RdPu'), 'rainfed': light_to_dark('YlOrBr'), 'irrigated': light_to_dark('YlGnBu'),
             'paddy': light_to_dark('YlGnBu'), 'natural': light_to_dark('Greens')}
DIFF_CMAP = plt.get_cmap('RdBu_r').copy(); DIFF_CMAP.set_bad((0, 0, 0, 0))
DOM_CLASSES = ('natural', 'rainfed', 'irrigated', 'urban', 'barren')
DOM_COLORS = ('#009E73', '#E69F00', '#0072B2', '#CC79A7', '#BBBBBB')        # Okabe-Ito
LAND = '#ececec'


# ---------------------------------------------------------------------------------------------- data
class Cache:
    def __init__(self):
        c = f'{lv.products()}/cache'
        with nc.Dataset(f'{c}/static.nc') as d:
            self.lat = d['lat'][:]; self.lon = d['lon'][:]
            self.active = d['active_fraction'][:].filled(0); self.land = d['isimip_land_fraction'][:].filled(0)
        self.dom = self.active > 0
        self._f = {}

    def field(self, src, soc, group, year):
        key = (src, soc)
        if key not in self._f:
            d = nc.Dataset(f'{lv.products()}/cache/fields_{src}_{soc}.nc'); self._f[key] = (d, list(d['year'][:]))
        d, years = self._f[key]
        if group == 'barren' and group not in d.variables:
            return np.zeros(self.dom.shape, 'f4')
        return d[group][years.index(year)].filled(np.nan)

    def frame(self, src, group, future, year):
        return self.field(src, 'histsoc' if year <= 2021 else future, group, year)

    def compared(self, src, group, soc, year):
        """Field used in the ISIMIP-VIC comparison: VIC natural includes class 16 barren, because ISIMIP has no
        barren class and its forests_and_natural_vegetation share includes barren land (user, 2026-10-02)."""
        f = self.field(src, soc, group, year)
        return f + self.field('vic', soc, 'barren', year) if (src == 'vic' and group == 'natural') else f


def natural_earth_lines():
    """Coastlines and land boundaries of Natural Earth 1:50m (cartopy data cache) as lists of (n, 2) lon/lat arrays."""
    out = {}
    for key, cat, name in (('coast', 'physical', 'coastline'), ('borders', 'cultural', 'admin_0_boundary_lines_land')):
        segs = []
        for geom in shpreader.Reader(shpreader.natural_earth(resolution='50m', category=cat, name=name)).geometries():
            for line in getattr(geom, 'geoms', [geom]):
                segs.append(np.asarray(line.coords)[:, :2])
        out[key] = segs
    return out


# ---------------------------------------------------------------------------------------------- drawing
def draw_panel(ax, data, cmap, norm, extent_box, C, coast, title=None):
    s, n, w, e = extent_box
    r = (C.lat >= s - 0.2) & (C.lat <= n + 0.2); c = (C.lon >= w - 0.2) & (C.lon <= e + 0.2)
    ext = [C.lon[c][0] - 0.125, C.lon[c][-1] + 0.125, C.lat[r][0] - 0.125, C.lat[r][-1] + 0.125]
    ax.imshow(np.where(C.dom[np.ix_(r, c)], 0.0, np.nan), origin='lower', extent=ext, cmap=mcolors.ListedColormap([LAND]),
              vmin=0, vmax=1, interpolation='nearest')
    ax.imshow(data[np.ix_(r, c)], origin='lower', extent=ext, cmap=cmap, norm=norm, interpolation='nearest')
    ax.add_collection(LineCollection(coast['borders'], colors='#a0a0a0', linewidths=0.25))      # reference only
    ax.add_collection(LineCollection(coast['coast'], colors='#505050', linewidths=0.35))
    ax.set_xlim(w, e); ax.set_ylim(s, n); ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_linewidth(0.5); sp.set_color('#999999')
    if title:
        ax.set_title(title, fontsize=10, loc='left', pad=3)


def frame_figure(columns, C, coast, stamp, colorbars):
    """columns: list of (header, data, cmap, norm); colorbars: list of (column indices, cmap, norm, label)."""
    ncol = len(columns); regions = list(lv.REGIONS)
    fig = plt.figure(figsize=(16, 10.4), dpi=100)
    gs = fig.add_gridspec(4, 2 * ncol, height_ratios=[1.45, 1, 1, 1], hspace=0.22, wspace=0.08,
                          left=0.012, right=0.988, top=0.925, bottom=0.115)
    glob = (-56, 84, -180, 180)
    for j, (head, data, cmap, norm) in enumerate(columns):
        ax = fig.add_subplot(gs[0, 2 * j:2 * j + 2])
        draw_panel(ax, data, cmap, norm, glob, C, coast, head)
        for r in regions:
            s, n, w, e = lv.REGIONS[r]
            ax.plot([w, e, e, w, w], [s, s, n, n, s], color='#d62728' if j < 2 else '#333333', lw=0.7)
    for i, r in enumerate(regions):
        row = 1 + i // 2; base = (i % 2) * ncol
        for j, (head, data, cmap, norm) in enumerate(columns):
            ax = fig.add_subplot(gs[row, base + j])
            draw_panel(ax, data, cmap, norm, lv.REGIONS[r], C, coast, lv.REGION_LABEL[r] if j == 0 else None)
    fig.suptitle(stamp, fontsize=15, x=0.012, ha='left', y=0.985)
    nb = len(colorbars)
    for k, (cols, cmap, norm, label) in enumerate(colorbars):
        cax = fig.add_axes([0.06 + k * (0.9 / nb), 0.06, 0.9 / nb - 0.08, 0.016])
        cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation='horizontal')
        cb.set_label(label, fontsize=11); cb.ax.tick_params(labelsize=10)
    return fig


def group_frame(C, coast, group, future, year, path):
    scen = 'histsoc' if year <= 2021 else future
    isi = C.compared('isimip', group, scen, year); vic = C.compared('vic', group, scen, year)
    lim = DIFF_LIM[group]; dnorm = mcolors.Normalize(-lim, lim)
    diff = np.where(C.dom, vic - isi, np.nan)
    cm = FRAC_CMAP[group]; fn = FRAC_NORM[group]
    cols = [('ISIMIP 15′ (whole-cell fraction)', np.where(isi >= SHOW_MIN, isi, np.nan), cm, fn),
            ('VIC 5′ aggregated to 15′ (fraction of active area)', np.where(vic >= SHOW_MIN, vic, np.nan), cm, fn),
            ('VIC − ISIMIP', np.where(np.abs(diff) > 1e-4, diff, np.nan), DIFF_CMAP, dnorm)]
    fig = frame_figure(cols, C, coast, f'{MAP_LABEL[group]} fraction   |   {year}   |   {scen}   |   ISIMIP4b input vs VIC-WUR forcing',
                       [(None, cm, fn, f'{lv.LABEL[group]} fraction (square-root scale; < {SHOW_MIN:g} not coloured)'),
                        (None, DIFF_CMAP, dnorm, f'VIC − ISIMIP (fraction; clipped at ±{lim})')])
    fig.savefig(path); plt.close(fig)


def change_frame(C, coast, group, future, year, path):
    scen = 'histsoc' if year <= 2021 else future; base_year = 1850 if year <= 2021 else 2021
    lim = DIFF_LIM[group]; dnorm = mcolors.Normalize(-lim, lim); cols = []
    for src, head in (('isimip', 'ISIMIP 15′'), ('vic', 'VIC 5′ → 15′')):
        d = C.compared(src, group, scen, year) - C.compared(src, group, 'histsoc', base_year)
        cols.append((f'{head}: {year} − {base_year}', np.where(np.abs(d) > 1e-4, d, np.nan), DIFF_CMAP, dnorm))
    fig = frame_figure(cols, C, coast, f'change of {MAP_LABEL[group]} fraction since {base_year}   |   {year}   |   {scen}',
                       [(None, DIFF_CMAP, dnorm, f'change (fraction; clipped at ±{lim})')])
    fig.savefig(path); plt.close(fig)


def dominant(C, src, future, year):
    stack = np.stack([np.nan_to_num(C.frame(src, g, future, year)) for g in DOM_CLASSES])
    if src == 'isimip':
        stack[DOM_CLASSES.index('barren')] = 0
    dom = stack.argmax(axis=0).astype('f4')
    return np.where(stack.max(axis=0) > 0, dom, np.nan)


def dominant_frame(C, coast, future, year, path):
    scen = 'histsoc' if year <= 2021 else future
    cmap = mcolors.ListedColormap(DOM_COLORS); norm = mcolors.BoundaryNorm(np.arange(-0.5, len(DOM_CLASSES)), len(DOM_CLASSES))
    cols = [('ISIMIP 15′ (no barren class)', dominant(C, 'isimip', future, year), cmap, norm),
            ('VIC 5′ → 15′', dominant(C, 'vic', future, year), cmap, norm)]
    fig = frame_figure(cols, C, coast, f'dominant land-use group   |   {year}   |   {scen}', [])
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in DOM_COLORS]
    fig.legend(handles, [lv.LABEL[g] for g in DOM_CLASSES], loc='lower center', ncol=len(DOM_CLASSES), fontsize=12, frameon=False)
    fig.savefig(path); plt.close(fig)


# ---------------------------------------------------------------------------------------------- products
_C = {}


def render(job):
    kind, group, future, year, path = job
    if 'C' not in _C:
        C = Cache(); _C['C'] = C; _C['coast'] = natural_earth_lines()
    C, coast = _C['C'], _C['coast']
    os.makedirs(os.path.dirname(path), exist_ok=True)
    {'group': lambda: group_frame(C, coast, group, future, year, path),
     'change': lambda: change_frame(C, coast, group, future, year, path),
     'dominant': lambda: dominant_frame(C, coast, future, year, path)}[kind]()
    return path


def make_gif(frames, path):
    imgs = [Image.open(f).convert('RGB') for f in frames]
    pal = [im.quantize(colors=255, method=Image.Quantize.MEDIANCUT) for im in imgs]
    dur = [2000] + [500] * (len(pal) - 2) + [2000]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=dur, loop=0, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--draft', nargs=3, metavar=('GROUP', 'YEAR', 'FUTURE'))
    ap.add_argument('--processes', type=int, default=8)
    a = ap.parse_args(); out = f'{lv.products()}/figures'
    if a.draft:
        g, y, f = a.draft
        print(render(('group', g, f, int(y), f'{out}/draft/{g}_{y}_{f}.png'))); return
    years = lv.HIST_FRAMES + lv.FUT_FRAMES
    sets = []
    for fut in lv.FUTURES:
        for g in MAP_GROUPS:
            sets.append((f'{out}/maps/{g}/{fut}', f'{out}/maps/{g}_{fut}.gif', 'group', g))
            sets.append((f'{out}/maps/change/{g}/{fut}', f'{out}/maps/change_{g}_{fut}.gif', 'change', g))
        sets.append((f'{out}/maps/dominant/{fut}', f'{out}/maps/dominant_{fut}.gif', 'dominant', None))
    jobs = [(kind, g, d.split('/')[-1], y, f'{d}/frame_{y}.png') for d, _, kind, g in sets for y in years]
    with ProcessPoolExecutor(a.processes, mp_context=get_context('fork')) as ex:
        for i, p in enumerate(ex.map(render, jobs, chunksize=2)):
            if i % 50 == 0:
                print(f'{i + 1}/{len(jobs)} {p}', flush=True)
    for d, gif, _, _ in sets:
        make_gif([f'{d}/frame_{y}.png' for y in years], gif); print(gif, flush=True)


if __name__ == '__main__':
    main()
