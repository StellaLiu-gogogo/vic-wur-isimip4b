"""Grid side of the dam component (decision D19): routing topology, upstream area, snapping, one dam per cell,
service maps, and the VIC dam parameter file.

Snapping (snap) follows the legacy 01CreateDamDatabase.py of the corrected GDW table, on the routing of the
parameter set:
  * the dam point goes to the nearest 5' cell; when that cell is outside the domain, to the nearest active cell of
    its 3x3 neighbourhood (user, 2026-10-11), else the dam is not placed;
  * catchment area < area of that cell: local dam (type 0) in that cell, inflow_fraction = catchment / cell area;
  * otherwise a global dam (type 1, inflow_fraction 1): the active cell of the 3x3 neighbourhood of the nearest
    cell whose upstream area is closest to the catchment area, unless max(ratio, 1/ratio) > MAX_RATIO, then the
    nearest (active) cell. SSP future dams are always global.
One dam per cell (place): dams are placed in the given order (largest first); a dam whose cell is taken moves to
a free active neighbour (3x3) on the same river - the cell directly downstream of the taken cell or a cell that
drains directly into it - whose upstream area still fits (max(ratio, 1/ratio) <= MAX_RATIO; best fit chosen); a
local dam to the free active neighbour nearest to its point. Otherwise a historical dam is merged into the
dam of the cell (capacities summed; year, type and inflow fraction of the dam already there, which is the larger;
the caller combines the purposes)
and a future dam is not placed (user, 2026-10-11). VIC 39e21ff5 sizes the dam output for one dam per cell
(plugins/general/src/plugin_output.c).
Service maps (trace_service) follow vic_parameter src/vic_parameter/dams/service.py.
The writer follows vic_parameter src/vic_parameter/dams/writer.py: only each dam's bounding box of service and
service_fraction is written; a dam with Nservice = 0 has a fully empty slice (dam_init.c stops when a slice has
more serviced cells than Nservice).
"""
import numpy as np
import netCDF4 as nc

EARTH_KM = 6371.0
MAX_RATIO = 1.5
MIN_FRAC = 0.1
MAX_SERVICE = 1000
CHUNK = 128
TYPE_LOCAL, TYPE_GLOBAL = 0, 1


class Grid:
    """Domain grid with the routing topology. Arrays are (lat, lon); flat index = row * nx + col.
    cell_id: routing downstream_id on active cells, -1 elsewhere (the id_map of the dam file);
    next_flat: flat index of the downstream cell, -1 at outlets and outside the domain;
    area_m2: routing cell_area; upstream_m2: area of the cell and everything draining into it."""

    def __init__(self, lat, lon, mask, cell_id, downstream_id, area_m2):
        self.lat, self.lon = np.asarray(lat, float), np.asarray(lon, float)
        self.mask = np.asarray(mask, bool)
        self.ny, self.nx = self.mask.shape
        self.cell_id = np.where(self.mask & (cell_id > 0), cell_id, -1).astype(np.int32)
        self.area_m2 = np.where(self.mask, area_m2, 0.0).astype(float)
        self.next_flat = downstream_index(self.cell_id, np.where(self.mask, downstream_id, -1))
        self.upstream_m2 = upstream_area(self.next_flat.ravel(), self.area_m2.ravel()).reshape(self.mask.shape)

    def nearest(self, lat, lon):
        return int(np.abs(self.lat - lat).argmin()), int(np.abs(self.lon - lon).argmin())

    def neighbours(self, r, c):
        """Cells of the 3x3 neighbourhood of (r, c) without (r, c); longitude wraps."""
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, (c + dc) % self.nx
                if (dr or dc) and 0 <= rr < self.ny:
                    out.append((rr, cc))
        return out


def load_grid(domain_nc, routing_nc):
    with nc.Dataset(domain_nc) as d:
        lat = np.asarray(d['lat'][:], float); lon = np.asarray(d['lon'][:], float)
        mask = np.asarray(d['mask'][:].filled(0)) == 1
    with nc.Dataset(routing_nc) as r:
        r.set_auto_mask(False)
        rlat, rlon = np.asarray(r['lat'][:], float), np.asarray(r['lon'][:], float)
        if rlat.shape != lat.shape or rlon.shape != lon.shape or \
                max(np.abs(rlat - lat).max(), np.abs(rlon - lon).max()) > 1e-6:
            raise ValueError('routing and domain grids differ')
        cell_id = np.asarray(r['downstream_id'][:]); down = np.asarray(r['downstream'][:])
        area = np.asarray(r['cell_area'][:], float)
    if (mask & ~(cell_id > 0)).any():
        raise ValueError('active cells without a routing cell id')
    return Grid(lat, lon, mask, cell_id, down, area)


def downstream_index(cell_id, downstream_id):
    """Flat index of each cell's downstream cell from the id-based routing; -1 at an outlet (downstream id
    missing, unknown, or the cell itself)."""
    ny, nx = cell_id.shape
    ids = cell_id.ravel()
    lookup = np.full(int(max(ids.max(), 0)) + 2, -1, np.int64)
    present = ids > 0
    if len(np.unique(ids[present])) != present.sum():
        raise ValueError('routing cell ids are not unique on active cells')
    lookup[ids[present]] = np.flatnonzero(present)
    tgt = downstream_id.ravel().astype(np.int64)
    ok = present & (tgt > 0) & (tgt < len(lookup))
    nxt = np.full(ids.size, -1, np.int64)
    nxt[ok] = lookup[tgt[ok]]
    nxt[nxt == np.arange(ids.size)] = -1
    return nxt.reshape(ny, nx)


def upstream_area(next_flat, area):
    """Accumulated area along the flow (each cell plus all cells draining into it); stops on a loop."""
    n = next_flat.size
    acc = area.astype(float).copy()
    has = next_flat >= 0
    indeg = np.bincount(next_flat[has], minlength=n)
    stack = list(np.flatnonzero(indeg == 0))
    done = 0
    while stack:
        i = stack.pop(); done += 1
        j = next_flat[i]
        if j >= 0:
            acc[j] += acc[i]
            indeg[j] -= 1
            if indeg[j] == 0:
                stack.append(j)
    if done != n:
        raise ValueError(f'routing has loops: {n - done} cells never reached')
    return acc


def gc_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def area_ratio(catch_km2, area_m2):
    a = area_m2 / 1e6
    if not (a > 0 and catch_km2 > 0):
        return np.inf
    return max(catch_km2 / a, a / catch_km2)


def location_fit(grid, lat, lon, catch_km2):
    """Best max(ratio, 1/ratio) between catch_km2 and the upstream area of the active cells of the 3x3
    neighbourhood of the nearest cell (inf when none is active or the catchment is unknown)."""
    r, c = grid.nearest(lat, lon)
    fits = [area_ratio(catch_km2, grid.upstream_m2[rr, cc]) for rr, cc in [(r, c)] + grid.neighbours(r, c)
            if grid.mask[rr, cc]]
    return min(fits) if fits else np.inf


def snap(grid, lat, lon, catch_km2, force_global=False):
    """Cell, type and inflow fraction of one dam: dict(row, col, type, inflow_fraction, method, ratio); row is
    None when no active cell is in reach."""
    r, c = grid.nearest(lat, lon)
    if grid.mask[r, c]:
        r0, c0, how = r, c, 'nearest'
    else:
        cands = [(rr, cc) for rr, cc in grid.neighbours(r, c) if grid.mask[rr, cc]]
        if not cands:
            return {'row': None, 'col': None, 'type': None, 'inflow_fraction': np.nan,
                    'method': 'no active cell in the 3x3 neighbourhood', 'ratio': np.nan}
        d = [gc_km(lat, lon, grid.lat[rr], grid.lon[cc]) for rr, cc in cands]
        (r0, c0), how = cands[int(np.argmin(d))], 'nearest_active'
    frac = catch_km2 * 1e6 / grid.area_m2[r0, c0]
    if frac < 1 and not force_global:
        return {'row': r0, 'col': c0, 'type': TYPE_LOCAL, 'inflow_fraction': float(frac), 'method': f'{how}_local',
                'ratio': np.nan}
    best, best_diff = (r0, c0), abs(catch_km2 * 1e6 - grid.upstream_m2[r0, c0])
    for rr, cc in [(r, c)] + grid.neighbours(r, c):
        if grid.mask[rr, cc]:
            diff = abs(catch_km2 * 1e6 - grid.upstream_m2[rr, cc])
            if diff < best_diff:
                best, best_diff = (rr, cc), diff
    ratio = area_ratio(catch_km2, grid.upstream_m2[best])
    if ratio > MAX_RATIO:
        best, method = (r0, c0), f'{how}_global_revert'
        ratio = area_ratio(catch_km2, grid.upstream_m2[best])
    else:
        method = f'{how}_global_neighbourhood' if best != (r0, c0) else f'{how}_global'
    return {'row': best[0], 'col': best[1], 'type': TYPE_GLOBAL, 'inflow_fraction': 1.0, 'method': method,
            'ratio': ratio}


def snap_future(grid, lat, lon):
    """Cell of an SSP future dam, whose tables give no catchment area (user, 2026-10-16): the active cell of the
    nearest cell and its 3x3 neighbourhood with the largest upstream area (a river-power dam sits on the main
    river); always global, inflow_fraction 1."""
    r, c = grid.nearest(lat, lon)
    cands = [(rr, cc) for rr, cc in [(r, c)] + grid.neighbours(r, c) if grid.mask[rr, cc]]
    if not cands:
        return {'row': None, 'col': None, 'type': TYPE_GLOBAL, 'inflow_fraction': 1.0,
                'method': 'no active cell in the 3x3 neighbourhood', 'ratio': np.nan}
    best = max(cands, key=lambda rc: grid.upstream_m2[rc])
    return {'row': best[0], 'col': best[1], 'type': TYPE_GLOBAL, 'inflow_fraction': 1.0,
            'method': 'future_largest_upstream' if best != (r, c) else 'future_nearest', 'ratio': np.nan}


def move_target(grid, row, col, dam, occupied):
    """Free active neighbour (3x3) of the taken cell (row, col) for `dam` (dict with type, lat, lon,
    catchment_km2), or None. Global: on the same river (directly downstream, or draining directly into the
    taken cell) with upstream area within MAX_RATIO, best fit; local: nearest to the dam point."""
    taken = row * grid.nx + col
    cands = [(rr, cc) for rr, cc in grid.neighbours(row, col)
             if grid.mask[rr, cc] and rr * grid.nx + cc not in occupied]
    if dam['type'] == TYPE_GLOBAL:
        ok = []
        for rr, cc in cands:
            f = rr * grid.nx + cc
            if grid.next_flat[row, col] == f or grid.next_flat[rr, cc] == taken:
                ratio = area_ratio(dam['catchment_km2'], grid.upstream_m2[rr, cc])
                if ratio <= MAX_RATIO:
                    ok.append((ratio, rr, cc))
        return (min(ok)[1], min(ok)[2]) if ok else None
    if not cands:
        return None
    d = [gc_km(dam['lat'], dam['lon'], grid.lat[rr], grid.lon[cc]) for rr, cc in cands]
    return cands[int(np.argmin(d))]


def place(grid, dams):
    """One dam per cell. `dams`: list of dicts in placement order (largest first, historical before future) with
    row, col, type, lat, lon, catchment_km2, capacity_mcm, future (bool). Adds to each dict `placement`
    ('as_snapped', 'moved', 'merged', 'not_placed') and, for merged dams, `merged_into` (index into `dams`);
    moved dams get the new row/col and `moved_from`. Returns the list of indices of dams that occupy a cell."""
    occupied = {}
    kept = []
    for k, d in enumerate(dams):
        if d['row'] is None:
            d['placement'] = 'not_placed'; d.setdefault('reason', 'no active cell'); continue
        f = d['row'] * grid.nx + d['col']
        if f not in occupied:
            occupied[f] = k; kept.append(k); d['placement'] = 'as_snapped'; continue
        tgt = move_target(grid, d['row'], d['col'], d, occupied)
        if tgt is not None:
            d['moved_from'] = (d['row'], d['col'])
            d['row'], d['col'] = tgt
            if d['type'] == TYPE_GLOBAL:
                d['ratio'] = area_ratio(d['catchment_km2'], grid.upstream_m2[tgt])
            occupied[tgt[0] * grid.nx + tgt[1]] = k; kept.append(k); d['placement'] = 'moved'
        elif d['future']:
            d['placement'] = 'not_placed'
            d['reason'] = f'cell taken by {dams[occupied[f]]["name"]}, no free neighbour on the same river'
        else:
            host = dams[occupied[f]]
            if host['future']:
                raise ValueError('a historical dam meets a future dam; historical dams must be placed first')
            d['placement'] = 'merged'; d['merged_into'] = occupied[f]
            host['capacity_mcm'] += d['capacity_mcm']
            host.setdefault('merged', []).append(k)
    return kept


def trace_service(grid, row, col, discharge, min_frac=MIN_FRAC, max_service=MAX_SERVICE):
    """Serviced cells (rows, cols, fractions) downstream of (row, col): the walk stops at a cell without positive
    mean discharge, a fraction (discharge at the dam / discharge at the cell) below min_frac, an outlet, a cell
    already visited, or max_service cells; fractions are clipped to 1; never empty (the dam cell itself)."""
    rows, cols, fr = [], [], []
    q0 = discharge[row, col]
    if np.isfinite(q0) and q0 > 0:
        r, c, seen = row, col, set()
        while len(rows) < max_service and (r, c) not in seen:
            seen.add((r, c))
            q = discharge[r, c]
            if not (np.isfinite(q) and q > 0):
                break
            f = float(q0) / float(q)
            if f < min_frac:
                break
            if grid.mask[r, c]:
                rows.append(r); cols.append(c); fr.append(min(f, 1.0))
            n = grid.next_flat[r, c]
            if n < 0:
                break
            r, c = int(n // grid.nx), int(n % grid.nx)
    if not rows:
        rows, cols, fr = [row], [col], [1.0]
    return np.array(rows, np.int64), np.array(cols, np.int64), np.array(fr, float)


def write_dam_file(path, grid, dams, years, networks, attrs, complevel=4):
    """Write the dam parameter file VIC 39e21ff5 reads (dam_start.c, dam_alloc_free.c, dam_init.c). `dams`: list of
    dicts (row, col, type, capacity_mcm, inflow_fraction) in dam_class order; `years`: int array; `networks`:
    list of (rows, cols, fractions), an empty tuple of arrays for Nservice = 0."""
    n = len(dams)
    with nc.Dataset(path, 'w', format='NETCDF4') as o:
        o.createDimension('lon', grid.nx); o.createDimension('lat', grid.ny); o.createDimension('dam_class', n)
        v = o.createVariable('lon', 'f8', ('lon',)); v[:] = grid.lon; v.units = 'degrees_east'
        v = o.createVariable('lat', 'f8', ('lat',)); v[:] = grid.lat; v.units = 'degrees_north'
        kw = {'zlib': True, 'complevel': complevel}
        v = o.createVariable('id_map', 'i4', ('lat', 'lon'), fill_value=-1, **kw)
        v[:] = grid.cell_id; v.long_name = 'routing cell id (downstream_id of the routing file); -1 outside the domain'
        ids = np.array([grid.cell_id[d['row'], d['col']] for d in dams], np.int32)
        spec = [('id', 'i4', ids, 'routing cell id of the dam cell', None),
                ('type', 'i4', np.array([d['type'] for d in dams], np.int32),
                 '0 = local (runoff of its own cell), 1 = global (routed discharge)', None),
                ('year', 'i4', np.asarray(years, np.int32),
                 'construction year; the dam operates once the simulation year >= year (0: always, 9999: never)', None),
                ('capacity', 'f8', np.array([d['capacity_mcm'] for d in dams], float), 'storage capacity', 'hm3'),
                ('inflow_fraction', 'f8', np.array([d['inflow_fraction'] for d in dams], float),
                 'fraction of the cell discharge (global) or runoff (local) entering the dam', '1'),
                ('Nservice', 'i4', np.array([len(nw[0]) for nw in networks], np.int32), 'number of serviced cells', None)]
        for name, dt, val, ln, units in spec:
            v = o.createVariable(name, dt, ('dam_class',), **kw); v[:] = val; v.long_name = ln
            if units:
                v.units = units
        shape = (1, min(grid.ny, CHUNK), min(grid.nx, CHUNK))
        sv = o.createVariable('service', 'i4', ('dam_class', 'lat', 'lon'), fill_value=-1, chunksizes=shape, **kw)
        sv.long_name = 'routing cell id of the dam, at every cell serviced by the dam'
        fv = o.createVariable('service_fraction', 'f8', ('dam_class', 'lat', 'lon'), fill_value=np.nan,
                              chunksizes=shape, **kw)
        fv.long_name = 'demand weight of each serviced cell'
        for k, (rows, cols, fr) in enumerate(networks):
            if not len(rows):
                continue
            r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
            s = np.full((r1 - r0, c1 - c0), -1, np.int32); f = np.full(s.shape, np.nan)
            s[rows - r0, cols - c0] = ids[k]; f[rows - r0, cols - c0] = fr
            sv[k, r0:r1, c0:c1] = s; fv[k, r0:r1, c0:c1] = f
        o.setncatts(attrs)
