#!/usr/bin/env python3
"""Independent verification of the adopted water-use file of a parameter set (component `water_use`, receiving
network, read by VIC with WATERUSE_PARAMETERS when REMOTE_WITHDRAWAL is TRUE; plugins/wateruse/src/wu_start.c,
wu_alloc_free.c and wu_init.c at VIC 39e21ff5).

Meaning of the variables (wu_init.c): receiving[k, cell] holds the receiving_id of a cell that `cell` withdraws
water FROM (the supplier; 0 marks an unused slot); Nreceiving[cell] is the number of cells that withdraw from `cell`.
A link is (demander, supplier). The file holds no distances and no fractions: VIC splits a remote withdrawal by the
water available in the suppliers at run time, so a fraction check is not applicable; distances are computed here
from the cell centres.

Checks (each with its own status; the file passes only when all pass, `generation_rules` may give a warning):
  integrity      md5 and size equal the manifest; not modified after adoption (see adopted.py)
  vic_variables  Nreceiving, receiving_id (lat, lon, int) and receiving (wu_receiving, lat, lon, int) present;
                 lat 1680, lon 4320
  latlon         lat and lon equal the domain file exactly
  ids            receiving_id is not fill and unique on active cells and equals the routing downstream_id there
  links          every supplier id of an active demander is the id of an active cell (VIC drops others); no
                 self-links; no supplier twice in one cell; Nreceiving is not fill on active cells and equals the
                 number of demanders of each cell (VIC stops when more are found, and drops links when fewer)
  order          the dependency graph of the routing order with water use (a cell waits for its upstream cells and
                 for the cells that withdraw from it, wu_set_routing_order) has no closed loop, and every demander
                 comes before the downstream cell of its supplier (wu_check_routing_order)
  distances      a delta link has as supplier the outlet the demander drains to (any distance); every other link
                 (search link) lies within the stated search: SEARCH_RADIUS cells and MAX_DISTANCE_KM between centres
  fractions      not_applicable (no fraction variable in the file)
  generation_rules  rules of the source README for the search links: at most MAX_SOURCES per demander and one
                 delta link; supplier upstream area >= MIN_AREA_RATIO times the demander's (upstream areas from the
                 routing variable cell_area, the spherical cell area the generator used; with the domain area a few
                 ratios fall 0.02 % below the limit); neither cell lies within PATH_EXCLUSION_STEPS cells downstream
                 of the other (warning if broken)
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{link_distance,sources_per_cell}.png, where <qc>
is qc/parameters/<status>/<set>/water_use/.

Usage: verify_water_use.py [--parameter-set ID] [--parameter-status candidates]
"""
import os, sys

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'domain'))
sys.path.insert(0, os.path.join(HERE, '..', 'routing'))
import adopted          # noqa: E402
import verify_routing as vr   # noqa: E402  (the walk of the routing network)

WATER_USE = 'water_use/vic_global_5min_wateruse_parameters_receiving-network.nc'
# generation parameters stated in the file (attribute generation_parameters) and the source README
SEARCH_RADIUS = 2
MAX_DISTANCE_KM = 50.0
MIN_AREA_RATIO = 20.0
MAX_SOURCES = 5
PATH_EXCLUSION_STEPS = 16
VIC_READS = {'Nreceiving': (('lat', 'lon'), 'i'), 'receiving_id': (('lat', 'lon'), 'i'),
             'receiving': (('wu_receiving', 'lat', 'lon'), 'i')}


def resolve(values, ids):
    """Index into `ids` (unique) of every value; -1 where a value is not an id."""
    order = np.argsort(ids, kind='stable'); s = ids[order]
    pos = np.clip(np.searchsorted(s, values), 0, s.size - 1)
    return np.where(s[pos] == values, order[pos], -1)


def dependency_levels(n, before, after):
    """Pass in which each node is placed when a node waits for all nodes `before[e]` with `after[e]` == node
    (1 for nodes that wait for nothing; 0 for nodes on or behind a closed loop)."""
    before = np.asarray(before, 'i8'); after = np.asarray(after, 'i8')
    indeg = np.bincount(after, minlength=n)
    o = np.argsort(before, kind='stable'); b_sorted = before[o]; a_sorted = after[o]
    start = np.searchsorted(b_sorted, np.arange(n)); end = np.searchsorted(b_sorted, np.arange(n), side='right')
    level = np.zeros(n, 'i8')
    front = np.flatnonzero(indeg == 0); p = 0
    while front.size:
        p += 1
        level[front] = p
        cnt = end[front] - start[front]
        if cnt.sum() == 0:
            break
        rep = np.repeat(front, cnt)
        off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        nxt_nodes = a_sorted[start[rep] + off]
        np.subtract.at(indeg, nxt_nodes, 1)
        cand = np.unique(nxt_nodes)
        front = cand[(indeg[cand] == 0) & (level[cand] == 0)]
    return level


def within_steps(nxt, start, target, steps):
    """True where `target` is reached within `steps` cells downstream of `start`."""
    cur = start.copy(); hit = np.zeros(start.size, bool)
    for _ in range(steps):
        cur = nxt[cur]
        hit |= cur == target
    return hit


def main():
    run = adopted.Run('water_use', __doc__.splitlines()[0])
    dom = adopted.read_domain(f'{run.pset}/{adopted.DOMAIN}')
    mask = dom['mask']; ny, nx = mask.shape
    flat = np.flatnonzero(mask); rows, cols = np.divmod(flat, nx); n = flat.size
    checks = {'integrity': run.integrity('water_use')}
    ds = nc.Dataset(f'{run.pset}/{WATER_USE}')
    checks['vic_variables'] = adopted.variables_check(ds, VIC_READS, {'lat': 1680, 'lon': 4320})
    checks['vic_variables']['wu_receiving'] = len(ds.dimensions['wu_receiving'])
    checks['latlon'] = adopted.latlon_check(ds, dom)
    rid2 = adopted.raw(ds, 'receiving_id'); nrec2 = adopted.raw(ds, 'Nreceiving'); rec3 = adopted.raw(ds, 'receiving')
    f_rid = adopted.fill_value(ds['receiving_id']); f_nrec = adopted.fill_value(ds['Nreceiving'])
    f_rec = adopted.fill_value(ds['receiving'])
    ds.close()
    with nc.Dataset(f'{run.pset}/{vr.ROUTING}') as r:
        did = adopted.raw(r, 'downstream_id')[mask].astype('i8'); dsv = adopted.raw(r, 'downstream')[mask].astype('i8')
        rout_area_km2 = adopted.raw(r, 'cell_area')[mask].astype('f8') / 1e6
    rid = rid2[mask].astype('i8')
    checks['ids'] = {'active_cells_fill': int(adopted.is_fill(rid, f_rid).sum()),
                     'duplicates': int(rid.size - np.unique(rid).size),
                     'equals_routing_downstream_id': bool(np.array_equal(rid, did))}
    c = checks['ids']; c['status'] = 'passed' if (c['active_cells_fill'] == c['duplicates'] == 0 and
                                                  c['equals_routing_downstream_id']) else 'failed'

    # ---- links (demander, supplier) as indices into the active cells
    dem = []; sup = []; slot = []; unresolved = 0; fill_slots = 0
    for k in range(rec3.shape[0]):
        v = rec3[k][mask].astype('i8')
        fill_slots += int(adopted.is_fill(v, f_rec).sum())
        i = np.flatnonzero(v > 0)
        j = resolve(v[i], rid)
        unresolved += int((j < 0).sum())
        dem.append(i[j >= 0]); sup.append(j[j >= 0]); slot.append(np.full(int((j >= 0).sum()), k))
    dem = np.concatenate(dem); sup = np.concatenate(sup); slot = np.concatenate(slot)
    outside = int(((rec3 > 0) & ~mask[None]).sum())
    self_links = int((dem == sup).sum())
    pair = dem * n + sup
    duplicates = int(pair.size - np.unique(pair).size)
    nrec = nrec2[mask].astype('i8')
    nrec_fill = int(adopted.is_fill(nrec, f_nrec).sum())
    counted = np.bincount(sup, minlength=n)
    mismatch = np.flatnonzero(counted != nrec)
    srcs = np.bincount(dem, minlength=n)
    checks['links'] = {'links': int(dem.size), 'unresolved_supplier_ids': unresolved, 'self_links': self_links,
                       'duplicate_pairs': duplicates, 'slots_with_fill_on_active_cells': fill_slots,
                       'links_stored_on_cells_outside_mask': outside, 'Nreceiving_fill_on_active_cells': nrec_fill,
                       'Nreceiving_mismatch_cells': int(mismatch.size),
                       'Nreceiving_max': int(nrec.max()), 'Nreceiving_total': int(nrec[nrec > 0].sum()),
                       'demanders': int((srcs > 0).sum()), 'suppliers': int((counted > 0).sum()),
                       'sources_per_demander_max': int(srcs.max()),
                       'links_per_slot': np.bincount(slot, minlength=rec3.shape[0]).tolist()}
    c = checks['links']
    c['status'] = 'passed' if (unresolved == self_links == duplicates == nrec_fill == 0 and mismatch.size == 0) \
        else 'failed'

    # ---- routing order with water use
    nxt, _ = vr.network(did, dsv)
    flows = nxt != np.arange(n)
    up_b = np.flatnonzero(flows); up_a = nxt[up_b]           # a cell waits for its upstream cells
    level = dependency_levels(n, np.concatenate([up_b, dem]), np.concatenate([up_a, sup]))
    blocked = int((level == 0).sum())
    viol = int(((level[dem] >= level[nxt[sup]]) & (level[dem] > 0)).sum())
    checks['order'] = {'cells_ordered': int(n - blocked), 'cells_blocked_by_a_loop': blocked, 'passes': int(level.max()),
                       'demanders_not_before_supplier_downstream': viol,
                       'status': 'passed' if blocked == 0 and viol == 0 else 'failed'}

    # ---- distances
    lat = dom['lat'][rows]; lon = dom['lon'][cols]
    dist = vr.gc_km(lat[dem], lon[dem], lat[sup], lon[sup])
    dr = np.abs(rows[sup] - rows[dem]); dc = np.abs(cols[sup] - cols[dem]); dc = np.minimum(dc, nx - dc)
    within = (dist <= MAX_DISTANCE_KM) & (dr <= SEARCH_RADIUS) & (dc <= SEARCH_RADIUS)
    _, outlet, _ = vr.walk(nxt)
    delta = ~flows[sup] & (outlet[dem] == sup)
    in_search = ~delta
    neither = in_search & ~within
    checks['distances'] = {'search_radius_cells': SEARCH_RADIUS, 'max_distance_km': MAX_DISTANCE_KM,
                           'search_links': int(in_search.sum()), 'delta_links': int(delta.sum()),
                           'delta_links_expected_from_source_qa': 8934,
                           'search_links_outside_search': int(neither.sum()),
                           'examples_outside': [{'demander': {'lat': float(lat[a]), 'lon': float(lon[a])},
                                                 'supplier': {'lat': float(lat[b]), 'lon': float(lon[b])},
                                                 'distance_km': float(x)}
                                                for a, b, x in zip(dem[neither][:20], sup[neither][:20], dist[neither][:20])],
                           'distance_km_search_links': adopted.stats(dist[in_search]),
                           'distance_km_delta_links': adopted.stats(dist[delta]),
                           'status': 'passed' if neither.sum() == 0 else 'failed'}
    checks['fractions'] = {'status': adopted.NOT_APPLICABLE,
                           'reason': 'the file has no fraction variable; VIC divides a remote withdrawal over the '
                                     'suppliers by the water available at run time (wu_remote.c)'}

    # ---- generation rules (source README)
    upa = vr.accumulate(nxt, rout_area_km2)
    upa_dom = vr.accumulate(nxt, dom['area'][mask] / 1e6)
    s_dem = np.bincount(dem[in_search], minlength=n); d_dem = np.bincount(dem[delta], minlength=n)
    ratio = upa[sup[in_search]] / upa[dem[in_search]]
    con = (within_steps(nxt, dem[in_search], sup[in_search], PATH_EXCLUSION_STEPS) |
           within_steps(nxt, sup[in_search], dem[in_search], PATH_EXCLUSION_STEPS))
    gr = {'max_sources': MAX_SOURCES, 'min_area_ratio': MIN_AREA_RATIO, 'path_exclusion_steps': PATH_EXCLUSION_STEPS,
          'demanders_above_max_sources': int((s_dem > MAX_SOURCES).sum()),
          'demanders_with_more_than_one_delta_link': int((d_dem > 1).sum()),
          'search_links_below_area_ratio': int((ratio < MIN_AREA_RATIO).sum()),
          'area_ratio_search_links': adopted.stats(ratio),
          'search_links_below_area_ratio_with_domain_area':
              int((upa_dom[sup[in_search]] / upa_dom[dem[in_search]] < MIN_AREA_RATIO).sum()),
          'search_links_connected_by_river': int(con.sum())}
    broken = sum(v for k, v in gr.items() if k.startswith(('demanders_', 'search_links_')) and
                 not k.endswith('_with_domain_area'))
    gr['status'] = 'passed' if broken == 0 else 'warning'
    checks['generation_rules'] = gr

    # ---- figures
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    ax.hist(dist[in_search], bins=50, label='search links'); ax.hist(dist[delta], bins=50, alpha=0.6, label='delta links')
    ax.axvline(MAX_DISTANCE_KM, color='k', ls='--', lw=1); ax.set_yscale('log')
    ax.set_xlabel('distance between cell centres (km)'); ax.set_ylabel('links'); ax.legend()
    ax.set_title('water-use links: demander to supplier distance'); fig.tight_layout()
    fig.savefig(f'{run.qc}/figures/link_distance.png'); plt.close(fig)
    m2 = np.full(mask.shape, np.nan); m2[mask] = np.where(srcs > 0, srcs, np.nan)
    adopted.save_map(f'{run.qc}/figures/sources_per_cell.png', m2, dom['lat'], dom['lon'],
                     'number of supplier cells per demanding cell', 'suppliers', cmap='viridis', vmin=1,
                     vmax=rec3.shape[0])
    run.finish([WATER_USE], checks, 'workflow/03_parameters/water_use/verify_water_use.py')


if __name__ == '__main__':
    main()
