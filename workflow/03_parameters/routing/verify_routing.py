#!/usr/bin/env python3
"""Independent verification of the adopted routing file of a parameter set (component `routing`, file
routing/vic_global_5min_routing.nc read by VIC with ROUTING_PARAMETERS; plugins/routing/src/rout_start.c and
rout_init.c at VIC 39e21ff5). The decomposition file of the same component is not checked here.

The network is walked by code of this file, not by VIC's reader: every active cell points to the cell whose
downstream_id equals its downstream value; a cell pointing to itself is an outlet.

Checks (each with its own status; the file passes only when all pass, `basins_grdc` may give a warning):
  integrity      md5 and size equal the manifest; not modified after adoption (see adopted.py)
  vic_variables  time (time), downstream_id and downstream (lat, lon, int), uh_inflow and uh_runoff (time, lat, lon)
                 present; lat 1680, lon 4320; time[i] = i * 3600 s for ROUT_STEPS_PER_DAY = 24 (rout_start.c)
  latlon         lat and lon equal the domain file exactly
  entries        on every active cell: downstream_id, downstream, uh_inflow and uh_runoff are not fill;
                 active_mask equals the domain mask; downstream_id is unique among active cells
  unit_hydrographs  on every active cell both unit hydrographs are >= 0 and sum to 1 within 1e-5 (VIC rescales and
                 warns otherwise, AREA_SUM_ERROR_THRESH)
  links          every downstream value is the id of an active cell (VIC turns any other cell into an outlet, with
                 a warning only); every link goes to one of the 8 neighbouring cells (longitude wraps at the
                 dateline) or to the cell itself; no cell has more than MAX_UPSTREAM = 8 upstream neighbours
  cycles         walking downstream from every active cell ends at an outlet (no closed loop)
  accumulation   the upstream area at each outlet from accumulating cell areas downstream equals the sum of the
                 areas of all cells that end at that outlet (two independent walks; relative 1e-9); the routing
                 variable cell_area is compared with the domain area and with the spherical cell area for the
                 report only (VIC routes with the domain area and does not read cell_area)
  basins_grdc    number of outlets; the largest basins and their outlet cells; the GRDC stations near the mouths of
                 the Amazon, Congo, Mississippi and Yangtze (GRDC_STATIONS) are placed on the cell within 3 cells
                 whose upstream area fits the GRDC catchment area best; the outlet of that cell is the river's
                 outlet (position, basin area and rank reported); passed when every area error is within 10 % and
                 the outlet lies within MOUTH_RADIUS_KM of the approximate river mouth (MOUTHS) or is the cell of a
                 reviewed outlet (REVIEWED_OUTLETS), warning when the area error is within 30 % or the outlet lies
                 farther from the mouth, failed otherwise
Writes <qc>/summary.json, <qc>/reports/{verify.json,largest_basins.csv}, <qc>/figures/upstream_area.png, where <qc>
is qc/parameters/<status>/<set>/routing/.

Usage: verify_routing.py [--parameter-set ID] [--parameter-status candidates]
"""
import os, sys

import numpy as np
import netCDF4 as nc
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'domain'))
import adopted   # noqa: E402
import verify_domain as vd   # noqa: E402  (cell areas)

ROUTING = 'routing/vic_global_5min_routing.nc'
ROUT_DT = 3600            # s: ROUT_STEPS_PER_DAY 24 of the simulation template
MAX_UPSTREAM = 8          # plugins/routing/include/routing.h
UH_TOLERANCE = 1e-5       # AREA_SUM_ERROR_THRESH, drivers/shared_image/include/vic_driver_shared_image.h
VIC_READS = {'time': (('time',), None), 'downstream_id': (('lat', 'lon'), 'i'), 'downstream': (('lat', 'lon'), 'i'),
             'uh_inflow': (('time', 'lat', 'lon'), 'f'), 'uh_runoff': (('time', 'lat', 'lon'), 'f')}
GRDC_CATALOGUE = 'raw/external/grdc/export-2024-11/20241030_grdc_stations.csv'
# the most downstream GRDC station of each river used for the basin check (GRDC catalogue numbers)
GRDC_STATIONS = {'Amazon': 3629000, 'Congo': 1147010, 'Mississippi': 4127800, 'Yangtze': 2181900}
# approximate river mouths (lat, lon); an outlet farther away is shown for review (warning)
MOUTHS = {'Amazon': (-0.2, -50.0), 'Congo': (-6.05, 12.3), 'Mississippi': (29.1, -89.3), 'Yangtze': (31.5, 121.8)}
MOUTH_RADIUS_KM = 150.0
# outlets farther from the river mouth that the user reviewed and accepted (cell centre lat, lon); a different outlet
# is a warning again
REVIEWED_OUTLETS = {
    'Yangtze': {'lat': 31.958333, 'lon': 120.208333, 'reviewed': 'user, 2026-10-24 (task R)',
                'reason': 'the routing (HydroSHEDS 30 arc-second network) treats the Yangtze estuary below Jiangyin as '
                          'sea, so the river ends about 160 km from the coast; the estuary cells, land in the VIC '
                          'mask, are separate outlets. Accepted as a property of the routing release v1.0.0_20260804.'},
}
STATION_RADIUS = 3        # cells


# ------------------------------------------------------------------------------------------------ network
def network(downstream_id, downstream):
    """Downstream cell of every active cell as an index into the active cells.

    downstream_id, downstream: 1-d int arrays over the active cells. Returns (nxt, not_found): nxt[i] is the active
    cell whose downstream_id equals downstream[i], i itself for an outlet (downstream[i] == downstream_id[i]) and
    for a value found on no active cell (listed in not_found, as VIC does)."""
    order = np.argsort(downstream_id, kind='stable')
    sid = downstream_id[order]
    pos = np.searchsorted(sid, downstream)
    pos = np.clip(pos, 0, sid.size - 1)
    found = sid[pos] == downstream
    nxt = np.where(found, order[pos], np.arange(downstream.size))
    return nxt, np.flatnonzero(~found)


def neighbour_links(nxt, rows, cols, nlon):
    """Indices of cells whose downstream cell is neither itself nor one of its 8 neighbours (longitude wraps)."""
    dr = np.abs(rows[nxt] - rows)
    dc = np.abs(cols[nxt] - cols); dc = np.minimum(dc, nlon - dc)
    return np.flatnonzero((dr > 1) | (dc > 1))


def walk(nxt):
    """Walk the network: (cyclic, outlet, levels).

    cyclic: indices of cells on a closed loop (they never reach an outlet); outlet[i]: the outlet that cell i ends at
    (-1 for cells on or draining into a loop); levels: number of passes of the upstream-first ordering (the longest
    path in cells)."""
    n = nxt.size
    idx = np.arange(n)
    flows = nxt != idx
    indeg = np.bincount(nxt[flows], minlength=n)
    done = np.zeros(n, bool)
    front = np.flatnonzero(indeg == 0)
    levels = 0
    while front.size:
        levels += 1
        done[front] = True
        f = front[flows[front]]
        down = nxt[f]
        np.subtract.at(indeg, down, 1)
        cand = np.unique(down)
        front = cand[(indeg[cand] == 0) & ~done[cand]]
    # outlets are processed when all their upstream cells are; cells left over lie on loops
    cyclic = np.flatnonzero(~done)
    # pointer jumping to the outlet; a loop cell points to itself and is marked -1 afterwards
    ptr = nxt.copy(); ptr[cyclic] = cyclic
    while True:
        new = ptr[ptr]
        if np.array_equal(new, ptr):
            break
        ptr = new
    outlet = ptr.copy()
    bad = np.zeros(n, bool); bad[cyclic] = True
    outlet[bad[ptr]] = -1
    return cyclic, outlet, levels


def accumulate(nxt, weight):
    """Upstream sum of `weight` (including the cell) by passing values downstream, upstream cells first. Cells on
    loops keep their own and their upstream contributions only up to the loop."""
    n = nxt.size
    idx = np.arange(n)
    flows = nxt != idx
    acc = np.asarray(weight, 'f8').copy()
    indeg = np.bincount(nxt[flows], minlength=n)
    front = np.flatnonzero(indeg == 0)
    while front.size:
        f = front[flows[front]]
        down = nxt[f]
        np.add.at(acc, down, acc[f])
        np.subtract.at(indeg, down, 1)
        cand = np.unique(down)
        front = cand[indeg[cand] == 0]
    return acc


def basin_sums(outlet, weight):
    """{outlet: sum of weight of the cells that end at it} as an array over cells (0 where not an outlet)."""
    ok = outlet >= 0
    return np.bincount(outlet[ok], weights=np.asarray(weight, 'f8')[ok], minlength=outlet.size)


def gc_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))


def place_station(lat, lon, area_km2, upa2, mask, glat, glon, radius=STATION_RADIUS):
    """(row, col, upstream area, relative area error) of the active cell within `radius` cells of (lat, lon) whose
    upstream area is closest to area_km2 (smallest |log ratio|); None when there is no active cell."""
    ny, nx = mask.shape
    i0 = int(np.argmin(np.abs(glat - lat))); j0 = int(np.argmin(np.abs(glon - lon)))
    best = None
    for i in range(max(i0 - radius, 0), min(i0 + radius + 1, ny)):
        for j in range(j0 - radius, j0 + radius + 1):
            jj = j % nx
            if mask[i, jj] and upa2[i, jj] > 0:
                err = abs(np.log(upa2[i, jj] / area_km2))
                if best is None or err < best[0]:
                    best = (err, i, jj)
    if best is None:
        return None
    _, i, j = best
    return i, j, float(upa2[i, j]), float(upa2[i, j] / area_km2 - 1)


# ------------------------------------------------------------------------------------------------ main
def main():
    run = adopted.Run('routing', __doc__.splitlines()[0])
    dom = adopted.read_domain(f'{run.pset}/{adopted.DOMAIN}')
    mask = dom['mask']; ny, nx = mask.shape
    flat = np.flatnonzero(mask); rows, cols = np.divmod(flat, nx)
    checks = {'integrity': run.integrity('routing')}
    ds = nc.Dataset(f'{run.pset}/{ROUTING}')
    checks['vic_variables'] = adopted.variables_check(ds, VIC_READS, {'lat': 1680, 'lon': 4320})
    t = adopted.raw(ds, 'time')
    nt = t.size
    time_ok = bool(np.array_equal(t, np.arange(nt) * ROUT_DT))
    checks['vic_variables']['time'] = {'steps': int(nt), 'equals_i_times_rout_dt': time_ok, 'rout_dt_s': ROUT_DT}
    if not time_ok:
        checks['vic_variables']['status'] = 'failed'
    checks['latlon'] = adopted.latlon_check(ds, dom)

    # ---- entries on active cells
    did2 = adopted.raw(ds, 'downstream_id'); ds2 = adopted.raw(ds, 'downstream')
    am = adopted.raw(ds, 'active_mask') if 'active_mask' in ds.variables else None
    fill = {v: adopted.fill_value(ds[v]) for v in ('downstream_id', 'downstream', 'uh_inflow', 'uh_runoff')}
    did = did2[mask].astype('i8'); dsv = ds2[mask].astype('i8')
    ent = {'active_cells': int(mask.sum()),
           'downstream_id_fill': int(adopted.is_fill(did, fill['downstream_id']).sum()),
           'downstream_fill': int(adopted.is_fill(dsv, fill['downstream']).sum()),
           'downstream_id_duplicates': int(did.size - np.unique(did).size),
           'downstream_id_is_linear_index_plus_1': bool(np.array_equal(did, flat + 1)),
           'active_mask_equals_domain': None if am is None else bool(np.array_equal(am == 1, mask)),
           'cells_outside_mask_with_downstream_id': int((~mask & ~adopted.is_fill(did2, fill['downstream_id'])).sum())}

    # ---- unit hydrographs, one time step at a time
    uh = {}
    for v in ('uh_inflow', 'uh_runoff'):
        s = np.zeros(flat.size); neg = 0; nfill = np.zeros(flat.size, bool)
        for k in range(nt):
            x = adopted.raw(ds, v, k)[mask].astype('f8')
            nfill |= adopted.is_fill(x, fill[v])
            x = np.where(np.isfinite(x) & ~nfill, x, 0.0)
            neg += int((x < 0).sum()); s += x
        dev = np.abs(s - 1)
        uh[v] = {'cells_fill': int(nfill.sum()), 'negative_values': neg, 'sum': adopted.stats(s),
                 'cells_sum_beyond_tolerance': int((dev > UH_TOLERANCE).sum()), 'max_abs_sum_error': float(dev.max())}
    ent['uh_fill_cells'] = {v: uh[v]['cells_fill'] for v in uh}
    ok = (ent['downstream_id_fill'] == ent['downstream_fill'] == ent['downstream_id_duplicates'] == 0 and
          ent['active_mask_equals_domain'] is not False and all(x == 0 for x in ent['uh_fill_cells'].values()))
    checks['entries'] = {**ent, 'status': 'passed' if ok else 'failed'}
    checks['unit_hydrographs'] = {**uh, 'tolerance': UH_TOLERANCE,
                                  'status': 'passed' if all(u['negative_values'] == 0 and
                                                            u['cells_sum_beyond_tolerance'] == 0
                                                            for u in uh.values()) else 'failed'}

    # ---- links
    nxt, not_found = network(did, dsv)
    far = neighbour_links(nxt, rows, cols, nx)
    is_out = nxt == np.arange(nxt.size)
    nup = np.bincount(nxt[~is_out], minlength=nxt.size)
    wrap = np.flatnonzero(~is_out & (np.abs(cols[nxt] - cols) > 1))
    loc = lambda i: {'lat': float(dom['lat'][rows[i]]), 'lon': float(dom['lon'][cols[i]])}  # noqa: E731
    checks['links'] = {'downstream_not_an_active_cell': int(not_found.size),
                       'examples_not_found': [loc(i) | {'downstream': int(dsv[i])} for i in not_found[:20]],
                       'links_not_to_a_neighbour': int(far.size),
                       'examples_not_to_a_neighbour': [{'from': loc(i), 'to': loc(nxt[i])} for i in far[:20]],
                       'links_across_the_dateline': [{'from': loc(i), 'to': loc(nxt[i])} for i in wrap],
                       'max_upstream_neighbours': int(nup.max()), 'max_allowed': MAX_UPSTREAM,
                       'status': 'passed' if not_found.size == 0 and far.size == 0 and nup.max() <= MAX_UPSTREAM
                       else 'failed'}

    # ---- walk
    cyclic, outlet, levels = walk(nxt)
    checks['cycles'] = {'cells_on_loops': int(cyclic.size), 'examples': [loc(i) for i in cyclic[:20]],
                        'cells_not_reaching_an_outlet': int((outlet < 0).sum()), 'longest_path_cells': int(levels),
                        'status': 'passed' if cyclic.size == 0 and (outlet >= 0).all() else 'failed'}

    # ---- accumulation
    area_km2 = dom['area'][mask] / 1e6
    upa = accumulate(nxt, area_km2)
    ncell = accumulate(nxt, np.ones(flat.size))
    bsum = basin_sums(outlet, area_km2)
    outs = np.flatnonzero(is_out)
    rel = np.abs(upa[outs] / np.where(bsum[outs] > 0, bsum[outs], np.nan) - 1)
    total_ok = bool(np.isclose(upa[outs].sum(), area_km2.sum(), rtol=1e-9))
    ca = adopted.raw(ds, 'cell_area')[mask].astype('f8') if 'cell_area' in ds.variables else None
    ca_rel = None if ca is None else np.abs(ca / dom['area'][mask] - 1)
    sph = vd.sphere_area(dom['lat'], dom['lon'])[mask]
    ca_sph = None if ca is None else np.abs(ca / sph - 1)
    checks['accumulation'] = {'outlets_compared': int(outs.size), 'max_relative_difference': float(np.nanmax(rel)),
                              'outlets_beyond_1e-9': int((~(rel <= 1e-9)).sum()),
                              'sum_over_outlets_equals_total_area': total_ok,
                              'total_area_km2': float(area_km2.sum()),
                              'cell_area_vs_domain_area_max_relative': None if ca_rel is None else float(ca_rel.max()),
                              'cell_area_vs_sphere_area_max_relative': None if ca_sph is None else float(ca_sph.max()),
                              'cell_area_note': 'not read by VIC (routing uses the domain area); reported only',
                              'upstream_cells_max': int(ncell.max())}
    c = checks['accumulation']
    c['status'] = 'passed' if c['outlets_beyond_1e-9'] == 0 and total_ok else 'failed'

    # ---- basins and GRDC
    glat, glon = dom['lat'], dom['lon']
    order = outs[np.argsort(-upa[outs])]
    rank = {int(o): r + 1 for r, o in enumerate(order)}
    top = pd.DataFrame([{'rank': r + 1, 'outlet_lat': float(glat[rows[o]]), 'outlet_lon': float(glon[cols[o]]),
                         'area_km2': float(upa[o]), 'cells': int(ncell[o])} for r, o in enumerate(order[:50])])
    top.to_csv(f'{run.qc}/reports/largest_basins.csv', index=False)
    upa2 = np.zeros(mask.shape); upa2[mask] = upa
    out2 = np.full(mask.shape, -1, 'i8'); out2[mask] = outlet
    cat = pd.read_csv(f'{run.W}/{GRDC_CATALOGUE}', sep=';', encoding='utf-8-sig').set_index('grdc_no')
    rivers = {}; statuses = []; points = []
    for river, no in GRDC_STATIONS.items():
        s = cat.loc[no]
        rec = {'grdc_no': no, 'station': str(s.station), 'lat': float(s.lat), 'lon': float(s.long),
               'grdc_area_km2': float(s.area)}
        p = place_station(rec['lat'], rec['lon'], rec['grdc_area_km2'], upa2, mask, glat, glon)
        if p is None:
            rec['problem'] = 'no active cell within the search radius'; st = 'failed'
        else:
            i, j, a, e = p
            so = int(out2[i, j])
            mlat, mlon = MOUTHS[river]
            olat, olon = float(glat[rows[so]]), float(glon[cols[so]])
            dm = float(gc_km(mlat, mlon, olat, olon))
            rec |= {'cell_lat': float(glat[i]), 'cell_lon': float(glon[j]), 'cell_upstream_area_km2': a,
                    'area_error': e,
                    'outlet': {'lat': olat, 'lon': olon, 'basin_area_km2': float(upa[so]), 'basin_cells': int(ncell[so]),
                               'basin_rank': rank[so], 'station_to_outlet_km': float(gc_km(glat[i], glon[j], olat, olon)),
                               'mouth_reference': [mlat, mlon], 'outlet_to_mouth_reference_km': dm}}
            rv = REVIEWED_OUTLETS.get(river)
            reviewed = rv is not None and abs(olat - rv['lat']) < 1e-4 and abs(olon - rv['lon']) < 1e-4
            if rv is not None:
                rec['reviewed_outlet'] = {**rv, 'matches': reviewed}
            st = ('passed' if abs(e) <= 0.10 and (dm <= MOUTH_RADIUS_KM or reviewed) else
                  'warning' if abs(e) <= 0.30 else 'failed')
            points.append((float(glon[j]), float(glat[i]), f'{river} {no}'))
            points.append((olon, olat, f'{river} outlet'))
        rec['status'] = st; statuses.append(st); rivers[river] = rec
    checks['basins_grdc'] = {'outlets': int(outs.size), 'outlets_expected_from_source_manifest': 79461,
                             'largest_basins': top.head(10).to_dict('records'), 'rivers': rivers,
                             'status': adopted.qcm.combine(statuses)}
    adopted.save_map(f'{run.qc}/figures/upstream_area.png', np.where(mask, np.log10(np.maximum(upa2, 1)), np.nan),
                     glat, glon, 'log10 upstream area (km2) from the walk of the routing network, GRDC stations',
                     'log10 km2', cmap='Blues', vmin=1, vmax=7, points=points)
    ds.close()
    run.finish([ROUTING], checks, 'workflow/03_parameters/routing/verify_routing.py')


if __name__ == '__main__':
    main()
