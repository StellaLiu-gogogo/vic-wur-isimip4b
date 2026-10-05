"""GRDC daily discharge for run checks: station files, upstream area of the routing network, station-to-cell
mapping, monthly means and climatologies.

Source: the GRDC daily export in raw/external/grdc/export-2024-11/ (manifests/inputs/grdc.yaml): one file
<grdc_no>_Q_Day.Cmd.txt per station in daily_2024/<subdir>/, GRDC Export format (latin-1 text, '#' header
with GRDC-No., River, Station, Latitude (DD), Longitude (DD), Catchment area, then 'YYYY-MM-DD;hh:mm; Value'
lines, -999 = missing), and the station catalogue 20241030_grdc_stations.csv (';' separated).

Station mapping: the upstream area of every active cell is accumulated along the routing network
(downstream / downstream_id of the routing file, cell area of the domain file); a station is placed on the
cell within `radius` cells (5 arcmin) of its coordinates whose upstream area is closest to the GRDC catchment
area (smallest |log(A_cell / A_grdc)|), and accepted when the relative area error is at most `max_area_error`.
"""
import glob, os, re

import numpy as np
import pandas as pd

GRDC_DIR = 'raw/external/grdc/export-2024-11'
CATALOGUE = '20241030_grdc_stations.csv'


# ------------------------------------------------------------------------------------------------ routing
def network(downstream, downstream_id, mask):
    """Flat index of the downstream cell of every active cell (itself for an outlet; -1 off the domain)."""
    did = np.asarray(downstream_id).ravel().astype('i8'); ds = np.asarray(downstream).ravel().astype('i8')
    act = np.asarray(mask).ravel().astype(bool)
    lut = np.full(did[act].max() + 1, -1, 'i8'); lut[did[act]] = np.flatnonzero(act)
    nxt = np.full(did.size, -1, 'i8')
    ok = act & (ds >= 0) & (ds < lut.size)
    nxt[ok] = lut[ds[ok]]
    bad = act & (nxt < 0)
    nxt[bad] = np.flatnonzero(bad)                     # a link to no active cell ends the path (outlet)
    return nxt


def upstream_area(nxt, area_km2, mask):
    """Upstream area (km2, including the cell) by accumulation in topological order."""
    act = np.asarray(mask).ravel().astype(bool)
    acc = np.where(act, np.asarray(area_km2).ravel(), 0.0).astype('f8')
    src = np.flatnonzero(act & (nxt != np.arange(nxt.size)))
    indeg = np.bincount(nxt[src], minlength=nxt.size)
    front = np.flatnonzero(act & (indeg == 0))
    while front.size:
        down = nxt[front]; flow = front[down != front]; down = nxt[flow]
        np.add.at(acc, down, acc[flow])
        np.subtract.at(indeg, down, 1)
        cand = np.unique(down)
        front = cand[indeg[cand] == 0]
    return acc


def outlets(nxt):
    """Flat index of the outlet each cell drains to (pointer jumping)."""
    out = nxt.copy()
    while True:
        new = out[out]
        if np.array_equal(new, out):
            return out
        out = new


# ------------------------------------------------------------------------------------------------ stations
def catalogue(W):
    df = pd.read_csv(os.path.join(W, GRDC_DIR, CATALOGUE), sep=';', encoding='utf-8-sig')
    return df.set_index('grdc_no')


def station_files(W):
    """{grdc_no: path}; a station exported twice keeps the first file in sorted path order."""
    out = {}
    for p in sorted(glob.glob(os.path.join(W, GRDC_DIR, 'daily_2024', '*', '*_Q_Day.Cmd.txt'))):
        no = int(os.path.basename(p).split('_')[0])
        out.setdefault(no, p)
    return out


HEADER = {'grdc_no': r'GRDC-No\.:\s*(\d+)', 'river': r'River:\s*(.*)', 'station': r'Station:\s*(.*)',
          'lat': r'Latitude \(DD\):\s*([-0-9.]+)', 'lon': r'Longitude \(DD\):\s*([-0-9.]+)',
          'area_km2': r'Catchment area \(km.{0,2}\):\s*([-0-9.]+)'}


def read_station(path):
    """(metadata dict, pandas Series of daily discharge in m3/s with NaN for missing)."""
    with open(path, encoding='latin-1') as fh:
        lines = fh.read().splitlines()
    meta = {}; start = None
    for i, line in enumerate(lines):
        if not line.startswith('#'):
            if line.startswith('YYYY-MM-DD'):
                start = i + 1
                break
            continue
        for k, rx in HEADER.items():
            m = re.search(rx, line)
            if m and k not in meta:
                meta[k] = m.group(1).strip()
    for k in ('lat', 'lon', 'area_km2'):
        meta[k] = float(meta[k]) if k in meta else np.nan
    meta['grdc_no'] = int(meta['grdc_no'])
    rows = [l.split(';') for l in lines[start:] if l.strip()] if start is not None else []
    if not rows:
        return meta, pd.Series(dtype='f8')
    dates = pd.to_datetime([r[0] for r in rows], format='%Y-%m-%d')
    vals = np.array([float(r[2]) for r in rows])
    vals[vals < 0] = np.nan                             # -999 and negative values are missing
    return meta, pd.Series(vals, index=dates)


def map_stations(stations, upa, lat, lon, mask, radius=3, max_area_error=0.3):
    """stations: DataFrame with grdc_no index and lat, lon, area_km2. Adds row, col, upa_km2, area_error;
    stations without an acceptable cell are dropped."""
    ny, nx = mask.shape; upa2 = upa.reshape(mask.shape)
    dlat = lat[1] - lat[0]; dlon = lon[1] - lon[0]
    rows = []
    for no, s in stations.iterrows():
        if not np.isfinite(s.area_km2) or s.area_km2 <= 0:
            continue
        i0 = int(round((s.lat - lat[0]) / dlat)); j0 = int(round((s.lon - lon[0]) / dlon))
        best = None
        for i in range(max(i0 - radius, 0), min(i0 + radius + 1, ny)):
            for j in range(j0 - radius, j0 + radius + 1):
                jj = j % nx
                if not mask[i, jj]:
                    continue
                err = abs(np.log(upa2[i, jj] / s.area_km2))
                if best is None or err < best[0]:
                    best = (err, i, jj)
        if best is None:
            continue
        rel = upa2[best[1], best[2]] / s.area_km2 - 1
        if abs(rel) <= max_area_error:
            rows.append({'grdc_no': no, 'row': best[1], 'col': best[2], 'upa_km2': float(upa2[best[1], best[2]]),
                         'area_error': float(rel)})
    m = pd.DataFrame(rows).set_index('grdc_no') if rows else pd.DataFrame(columns=['row', 'col', 'upa_km2', 'area_error'])
    return stations.join(m, how='inner')


# ------------------------------------------------------------------------------------------------ time
def monthly_means(daily, min_days=20):
    """Monthly mean discharge; months with fewer than min_days valid days are NaN."""
    if daily.empty:
        return pd.Series(dtype='f8')
    g = daily.resample('MS')
    m = g.mean(); n = g.count()
    return m.where(n >= min_days)


def climatology(monthly, years, min_years=5):
    """12 monthly means over `years` (iterable of int), each needing min_years valid values; NaN otherwise.
    Also returns per calendar month the minimum and maximum of the yearly values."""
    sel = monthly[monthly.index.year.isin(list(years))]
    out = np.full(12, np.nan); lo = np.full(12, np.nan); hi = np.full(12, np.nan); n = np.zeros(12, int)
    for k in range(12):
        v = sel[sel.index.month == k + 1].dropna()
        n[k] = v.size
        if v.size >= min_years:
            out[k] = v.mean(); lo[k] = v.min(); hi[k] = v.max()
    return out, lo, hi, n
