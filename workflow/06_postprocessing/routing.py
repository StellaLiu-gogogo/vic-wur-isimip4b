"""River networks for the `dis` outlet map (D07 part 2): the 5' routing network of the parameter set, the ISIMIP
DDM30 0.5-degree network, and the upstream area accumulated along a network.

The stage keeps its own copy of the network functions of workflow/05_simulation/monitor/grdc.py instead of importing
them (user, 2026-11-10, task AD: the stage is self-contained). The rules are the same:

- 5' network: `downstream` of an active cell holds the `downstream_id` of the cell it drains to; a cell that points
  to itself, outside the ids, or to an inactive cell is an outlet;
- upstream area of a cell = its own area plus the upstream areas of every cell that drains into it.
"""
import numpy as np

# DDM30 flow directions (ddm30_cru_documentation_update_14112022.pdf): -1 inland sink, 0 outlet to the ocean,
# 1 east, 2 south-east, 3 south, 4 south-west, 5 west, 6 north-west, 7 north, 8 north-east.
# (north, east) steps in cells; north means a larger latitude.
DDM30_STEPS = {1: (0, 1), 2: (-1, 1), 3: (-1, 0), 4: (-1, -1), 5: (0, -1), 6: (1, -1), 7: (1, 0), 8: (1, 1)}


def network(downstream, downstream_id, active):
    """Flat index of the cell each active cell drains to (the cell itself for an outlet); -1 for inactive cells."""
    did = np.asarray(downstream_id).ravel().astype('i8')
    ds = np.asarray(downstream).ravel().astype('i8')
    act = np.asarray(active).ravel().astype(bool)
    lookup = np.full(did[act].max() + 1, -1, 'i8')
    lookup[did[act]] = np.flatnonzero(act)
    nxt = np.full(did.size, -1, 'i8')
    ok = act & (ds >= 0) & (ds < lookup.size)
    nxt[ok] = lookup[ds[ok]]
    ends = act & (nxt < 0)
    nxt[ends] = np.flatnonzero(ends)
    return nxt


def ddm30_network(flowdir, lat):
    """Flat index of the downstream cell of every DDM30 cell (itself for an outlet or sink, or when the step leaves
    the valid cells; -1 off the network). `lat` is the latitude axis of the file, which may run either way.
    Returns (nxt, number of steps that left the valid cells)."""
    fd = np.ma.filled(np.ma.asarray(flowdir).astype('f8'), np.nan)
    ny, nx = fd.shape
    valid = np.isfinite(fd)
    north = 1 if lat[-1] > lat[0] else -1           # row step that goes north
    nxt = np.full(fd.size, -1, 'i8')
    idx = np.arange(fd.size).reshape(ny, nx)
    nxt[valid.ravel()] = idx[valid]
    lost = 0
    for code, (dn, de) in DDM30_STEPS.items():
        rows, cols = np.nonzero(valid & (fd == code))
        r2 = rows + north * dn
        c2 = (cols + de) % nx                           # the grid is global in longitude
        inside = (r2 >= 0) & (r2 < ny)
        ok = inside.copy()
        ok[inside] = valid[r2[inside], c2[inside]]
        nxt[idx[rows[ok], cols[ok]]] = idx[r2[ok], c2[ok]]
        lost += int((~ok).sum())
    return nxt, lost


def upstream_area(nxt, area, active):
    """Upstream area of every cell (in the units of `area`, the cell included), accumulated from the sources down in
    the order of the network; 0 for inactive cells. Stops when the network has a loop."""
    act = np.asarray(active).ravel().astype(bool)
    acc = np.where(act, np.asarray(area, dtype='f8').ravel(), 0.0)
    flows = act & (nxt != np.arange(nxt.size))
    indeg = np.bincount(nxt[flows], minlength=nxt.size)
    front = np.flatnonzero(act & (indeg == 0))
    done = 0
    while front.size:
        done += front.size
        moving = front[nxt[front] != front]
        down = nxt[moving]
        np.add.at(acc, down, acc[moving])
        np.subtract.at(indeg, down, 1)
        cand = np.unique(down)
        front = cand[indeg[cand] == 0]
    if done != int(act.sum()):
        raise SystemExit(f'the network has a loop: {int(act.sum()) - done} cells never reached')
    return acc
