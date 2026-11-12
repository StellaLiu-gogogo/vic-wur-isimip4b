#!/usr/bin/env python3
"""Check of a product unit (make_unit.py; D07, D08, D11), against the protocol text (user, 2026-11-10: the ISIMIP4b
output schema is not published, so isimip-qc cannot check the products; the protocol commit pinned by the campaign
and protocol chapter 5 are the reference).

Writes qc/postprocessed/<product-set-id>/<gcm>/<segment-key>/<start>-<end>/ (below scratch/<task>/ with --scratch):
summary.json, reports/check.json, figures/maps.png, figures/global_series.png.

Checks (each passed, warning or failed; the summary takes the worst):
  record      provenance.yaml lists exactly the files present, with their sha256; the static files are those it
              records; the source attempt is still the latest of its chunk and completed, and the run output files
              have the recorded size and modification time
  files       data model, float32 variable with the protocol units and long name, dimensions (time, [lev,] lat,
              lon), the grid of the ISIMIP mask (latitudes north to south), time in days since 1601-01-01 with an
              accepted calendar, compression level, one chunk per field and layer, fill value and missing value,
              institution and contact, the varying-level variables and attributes of layered variables
  time        every day or month of the unit's years, stamped at the first day of its period, in order
  coverage    values on exactly the covered mask cells at every time step (static files), no NaN; missing only where
              the unit record lists a cell made missing by an `exclude` rule
  recompute   for recompute_steps_per_year sampled time steps per year, and for every time step with a left-out cell
              of an `exclude` rule, every product recomputed from the 5' output with sums per cell (not the producer's
              matrix) equals the product within recompute_rel_tol, missing at the same cells; dis equals the 5'
              discharge of the outlet cells; the groundwater part of the non-renewable withdrawal (*wwgw) is
              recomputed for all water-use classes at once (not class by class as the producer does)
  identities  0.5-degree products that the recipes make equal (qtot = qs + qsb, qg = qr = qsb)
  exclusions  the rule output of every `exclude` recipe read at every time step: the unit record lists exactly the
              5' cell-steps the rule leaves out and the 0.5-degree cell-steps it makes missing (D07 amendment
              2026-11-11)
Warnings: values outside the protocol's valid_min / valid_max (counted), monthly means of a daily product that
differ from the monthly product by more than daily_monthly_rel_tol.

Exit status: passed 0, failed 1, warning 3, not_checked 4.
Usage: check_unit.py --campaign configs/campaigns/<id>.yaml --run <run-id> [--chunk <start>-<end>]
                     [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import datetime
import json
import os
import sys
import time

import numpy as np
import netCDF4 as nc
import cftime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_unit       # noqa: E402
import product_set     # noqa: E402
import static_fields   # noqa: E402
import support         # noqa: E402

CALENDARS = ('standard', 'gregorian', 'proleptic_gregorian', '365_day', 'noleap', '366_day', 'all_leap')


# ------------------------------------------------------------------------------------------------ helpers
def expected_times(step, y0, y1, calendar):
    """Days since 1601-01-01 of the first day of every period of the unit."""
    if step == 'monthly':
        dates = [cftime.datetime(y, m, 1, calendar=calendar) for y in range(y0, y1 + 1) for m in range(1, 13)]
    else:
        d0 = cftime.datetime(y0, 1, 1, calendar=calendar)
        n = int(round((cftime.datetime(y1 + 1, 1, 1, calendar=calendar) - d0).total_seconds() / 86400))
        dates = [d0 + datetime.timedelta(days=i) for i in range(n)]
    return cftime.date2num(dates, make_unit.REFERENCE_TIME, calendar)


def sampled_steps(step, y, n_in_year, per_year):
    """Indices within the year of the time steps that are recomputed."""
    first = (y % 12) if step == 'monthly' else (y % 28)
    return sorted({(first + k * max(1, n_in_year // per_year)) % n_in_year for k in range(per_year)})


def close(product, reference, rtol):
    """(ok, max absolute difference, scale) with the tolerance relative to the largest |reference|."""
    scale = float(np.max(np.abs(reference))) if reference.size else 0.0
    diff = float(np.max(np.abs(product - reference))) if reference.size else 0.0
    return diff <= rtol * max(scale, 1e-30), diff, scale


# ------------------------------------------------------------------------------------------------ checks
def check_record(W, rec, unit_dir, static_dir, man):
    probs = []
    present = sorted(f for f in os.listdir(unit_dir) if f != 'provenance.yaml')
    listed = sorted(f['name'] for f in rec['files'])
    if present != listed:
        probs.append(f'files present {present} differ from the record {listed}')
    for f in rec['files']:
        p = os.path.join(unit_dir, f['name'])
        if os.path.exists(p) and support.sha256(p) != f['sha256']:
            probs.append(f'{f["name"]}: sha256 differs from the record')
    for fn, sha in rec['inputs']['static_files'].items():
        if support.sha256(os.path.join(static_dir, fn)) != sha:
            probs.append(f'static file {fn} differs from the one the unit was made with')
    att = product_set.latest_attempt(man, rec['chunk'])
    want = rec['source']['attempt']
    if att.get('attempt') != want.get('attempt') or att.get('slurm_job_id') != want.get('slurm_job_id') or \
            att.get('status') != 'completed':
        probs.append(f'the source attempt is no longer the latest completed one ({att.get("attempt")}, '
                     f'{att.get("status")})')
    for f in rec['source']['output_files']:
        p = os.path.join(W, f['path'])
        st = os.stat(p) if os.path.exists(p) else None
        mtime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st.st_mtime)) if st else None
        if st is None or st.st_size != f['size_bytes'] or mtime != f['mtime']:
            probs.append(f'{f["path"]}: changed or missing since the unit was made')
    return ('failed' if probs else 'passed'), {'problems': probs}


def check_file(path, var, step, cfg, protocol, grid, layered, y0, y1, wcell, keep=False, block=366, allowed=None):
    """Format, time axis, coverage and value range of one product file, read in blocks of time steps. `allowed`:
    {time index: (rows, cols)} of covered cells recorded as missing (an `exclude` rule). Returns (problems of each
    check, statistics): range, the global area-weighted series, the time mean (map), the monthly means of a daily
    file, and all values when `keep`."""
    probs = {'files': [], 'time': [], 'coverage': []}
    rules = cfg['file_rules']; fill = cfg['fill_value']
    stats = {}
    with nc.Dataset(path) as d:
        if d.data_model != rules['data_model']:
            probs['files'].append(f'data model {d.data_model}')
        for k in ('institution', 'contact'):
            if not getattr(d, k, ''):
                probs['files'].append(f'global attribute {k} missing')
        if var not in d.variables:
            probs['files'].append(f'variable {var} missing')
            return probs, None
        v = d[var]
        want_dims = ('time', 'lev', 'lat', 'lon') if layered else ('time', 'lat', 'lon')
        if v.dimensions != want_dims:
            probs['files'].append(f'dimensions {v.dimensions} instead of {want_dims}')
        if v.dtype != np.float32:
            probs['files'].append(f'data type {v.dtype}')
        p = protocol[var]
        for key in ('units', 'long_name'):
            if getattr(v, key, None) != support.for_sector(p[key]):
                probs['files'].append(f'{key} {getattr(v, key, None)!r} instead of {support.for_sector(p[key])!r}')
        flt = v.filters() or {}
        if not flt.get('zlib') or flt.get('complevel', 0) < rules['complevel']:
            probs['files'].append(f'compression {flt}')
        want_chunks = [1] + ([1] if layered else []) + list(grid.shape)
        if v.chunking() != want_chunks:
            probs['files'].append(f'chunks {v.chunking()} instead of {want_chunks}')
        for key in ('_FillValue', 'missing_value'):
            if not np.isclose(getattr(v, key, np.nan), fill):
                probs['files'].append(f'{key} {getattr(v, key, None)}')
        for name in ('lat', 'lon'):
            c = d[name]
            if c.dtype != np.float64 or not np.array_equal(c[:], grid.coords[name][0]):
                probs['files'].append(f'{name} differs from the ISIMIP mask grid')
        if d['lat'][0] < d['lat'][-1]:
            probs['files'].append('latitudes run south to north')
        t = d['time']
        calendar = getattr(t, 'calendar', None)
        if t.dtype != np.float64 or getattr(t, 'units', None) != make_unit.REFERENCE_TIME or calendar not in CALENDARS:
            probs['files'].append(f'time {t.dtype} {getattr(t, "units", None)!r} {calendar!r}')
            return probs, None
        if layered:
            for name in ('lev', 'depth', 'depth_bnds'):
                if name not in d.variables:
                    probs['files'].append(f'{name} missing')
            if getattr(d, 'location_varying_layer_depth', None) != 'true' or \
                    getattr(d, 'time_varying_layer_depth', None) != 'false':
                probs['files'].append('varying-level global attributes missing')
        tv = np.asarray(t[:])
        want_t = expected_times(step, y0, y1, calendar)
        if len(tv) != len(want_t) or not np.array_equal(tv, want_t):
            probs['time'].append(f'{len(tv)} time steps; not the first days of the periods of {y0}-{y1}')
        cov = np.zeros(grid.shape[0] * grid.shape[1], bool); cov[grid.cov] = True
        cov = cov.reshape(grid.shape)
        lo, hi = p.get('valid_min'), p.get('valid_max')
        n = len(tv)
        off = on_missing = outside = 0
        vmin, vmax = np.inf, -np.inf
        series = np.zeros(n); total = None
        month = None
        if step == 'daily':
            dates = cftime.num2date(tv, t.units, calendar)
            month = np.array([(dd.year - y0) * 12 + dd.month - 1 for dd in dates])
            msum = np.zeros((12 * (y1 - y0 + 1),) + v.shape[1:]); mcnt = np.zeros(12 * (y1 - y0 + 1))
        kept = np.empty(v.shape, 'f4') if keep else None
        for i in range(0, n, block):
            j = min(n, i + block)
            vals = np.ma.filled(v[i:j], np.nan).astype('f8')
            has = np.isfinite(vals)
            c = np.broadcast_to(cov if not layered else cov[None], vals.shape)
            if allowed:
                c = c.copy()
                for t_, (rr, cc) in allowed.items():
                    if i <= t_ < j:
                        c[t_ - i, ..., rr, cc] = False
            off += int((has & ~c).sum()); on_missing += int((~has & c).sum())
            if has.any():
                vmin = min(vmin, float(np.nanmin(vals))); vmax = max(vmax, float(np.nanmax(vals)))
            if lo is not None:
                outside += int(np.sum(vals < lo))
            if hi is not None:
                outside += int(np.sum(vals > hi))
            v2 = vals.sum(axis=1) if layered else vals
            series[i:j] = np.nansum(v2 * wcell, axis=(1, 2)) / wcell.sum()
            s = np.nansum(vals, axis=0)
            total = s if total is None else total + s
            if month is not None:
                np.add.at(msum, month[i:j], np.nan_to_num(vals))
                np.add.at(mcnt, month[i:j], 1)
            if keep:
                kept[i:j] = vals
        if off or on_missing:
            probs['coverage'].append(f'{off} values off the covered cells or at cells recorded as missing, '
                                     f'{on_missing} missing on covered cells (all time steps and layers)')
        mean = total / max(n, 1)
        stats = {'range': {'min': vmin, 'max': vmax, 'valid_min': lo, 'valid_max': hi, 'values_outside': outside},
                 'series': (tv, series), 'map': np.where(cov if not layered else cov[None], mean, np.nan),
                 'monthly_means': None if month is None else
                 np.where(cov if not layered else cov[None], msum / mcnt.reshape((-1,) + (1,) * (msum.ndim - 1)),
                          np.nan),
                 'values': kept}
    return probs, stats


def groundwater_part(ds, t, grid, sp, sector):
    """Groundwater part of the non-renewable withdrawal at time step t on the counted 5' cells, from all water-use
    classes at once: N x Ug / (Ug + Us) per class, then the class of the sector or the sum over the classes."""
    def read(name):
        a = np.ma.filled(ds[name][t], np.nan).astype('f8')
        a = a.reshape(a.shape[0], -1)[:, grid.counted]
        if np.isnan(a).any():
            raise SystemExit(f'{name}: missing values on active 5 arcmin cells')
        return a
    ug = np.clip(read(sp['demand_groundwater']) - sum(read(n) for n in sp['withdrawn_groundwater']), 0.0, None)
    us = np.clip(read(sp['demand_surface']) - sum(read(n) for n in sp['withdrawn_surface']), 0.0, None)
    u = ug + us
    part = read(sp['nonrenewable']) * np.divide(ug, u, out=np.zeros_like(u), where=u > 0)
    return part.sum(axis=0) if sector == 'all' else part[sector]


def recompute(ds, t, recipe, conv, seconds, grid, cfg, forcing, static_outlets):
    """Values of one variable on the covered cells at time step t from the 5' output, with sums per cell."""
    s = recipe.get('sector')
    sector = None if s is None else ('all' if s == 'all' else cfg['sectors'][s])
    layered = bool(recipe.get('layers'))
    x = 0.0
    for n in recipe.get('terms', []):
        a = make_unit.read5(ds[n], t, t + 1, grid, sector)[0]
        if a.ndim == 2 and not layered:
            a = a.sum(axis=0)
        x = x + a
    if recipe.get('times_forcing'):
        x = x * forcing[recipe['times_forcing']]
    if recipe.get('nonrenewable_groundwater'):
        x = x + groundwater_part(ds, t, grid, cfg['nonrenewable_split'], sector)
    if recipe.get('exclude'):
        ex = recipe['exclude']
        keep = np.abs(make_unit.read5(ds[ex['output']], t, t + 1, grid)[0]) <= ex['abs_above']
        num = np.bincount(grid.cellpos, weights=np.asarray(x) * grid.weights * keep, minlength=grid.cov.size)
        den = np.bincount(grid.cellpos, weights=grid.weights * keep, minlength=grid.cov.size)
        vals = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    elif recipe.get('outlet'):
        vals = np.asarray(x)[..., static_outlets]
    elif recipe.get('terms'):
        x = np.asarray(x)
        flat = x.reshape(-1, x.shape[-1])
        vals = np.stack([np.bincount(grid.cellpos, weights=row * grid.weights, minlength=grid.cov.size)
                         for row in flat]).reshape(x.shape[:-1] + (grid.cov.size,)) / grid.wsum
    else:
        vals = np.zeros(grid.cov.size)
    kind, k = conv
    vals = vals / seconds if kind == 'rate' else (vals * k if kind == 'scale' else vals + k)
    for n in recipe.get('volumes', []):
        vol = make_unit.read5(ds[n], t, t + 1, grid)[0]
        vals = vals + np.bincount(grid.cellpos, weights=vol, minlength=grid.cov.size) * make_unit.KG_PER_HM3 / \
            grid.wsum
    return vals


def scan_exclusions(ds, n, ex, grid, offset, block=31):
    """5' cell-steps (time index of the unit, 5' row, 5' column) whose |rule output| exceeds the limit, and the
    0.5-degree cell-steps (time index, covered position) whose counted 5' cells are all left out."""
    nx5 = grid.shape5[1]
    per_cell = np.bincount(grid.cellpos, minlength=grid.cov.size)
    steps, missing = set(), set()
    for t0 in range(0, n, block):
        out = np.abs(make_unit.read5(ds[ex['output']], t0, min(n, t0 + block), grid)) > ex['abs_above']
        for t in np.flatnonzero(out.any(axis=1)):
            idx = np.flatnonzero(out[t])
            steps |= {(int(offset + t0 + t), int(k // nx5), int(k % nx5)) for k in grid.counted[idx]}
            gone = np.flatnonzero(np.bincount(grid.cellpos[idx], minlength=grid.cov.size) == per_cell)
            missing |= {(int(offset + t0 + t), int(p)) for p in gone}
    return steps, missing


def figures(series, maps, figs):
    os.makedirs(figs, exist_ok=True)
    names = [n for n in maps][:4]
    if names:
        fig, axes = plt.subplots(2, 2, figsize=(14, 7))
        for ax, n in zip(axes.ravel(), names):
            m = maps[n]
            im = ax.imshow(np.where(np.isfinite(m), m, np.nan), extent=[-180, 180, -90, 90], cmap='viridis')
            fig.colorbar(im, ax=ax, shrink=0.8); ax.set_title(n)
        for ax in axes.ravel()[len(names):]:
            ax.axis('off')
        fig.savefig(f'{figs}/maps.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    if series:
        fig, ax = plt.subplots(len(series), 1, figsize=(10, 2.2 * len(series)), squeeze=False)
        for a_, (n, (t, s, u)) in zip(ax[:, 0], series.items()):
            a_.plot(t, s, lw=0.8); a_.set_ylabel(f'{n}\n({u})')
        ax[-1, 0].set_xlabel('days since 1601-01-01')
        fig.savefig(f'{figs}/global_series.png', dpi=110, bbox_inches='tight'); plt.close(fig)


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--run', required=True)
    ap.add_argument('--chunk')
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--expect-commit')
    a = ap.parse_args()
    W = support.workdir(); cfg = support.config(); uc = cfg['unit_check']
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean: checks of accepted units need a clean repository; '
                         'use --scratch <task-id>')
    camp, _, _ = support.campaign(a.campaign)
    pset = camp['campaign_id']
    rd = os.path.join(W, 'runs', pset, a.run)
    with open(os.path.join(rd, 'run_manifest.json')) as fh:
        man = json.load(fh)
    gcm, key, _, _ = make_unit.segment(camp, man)
    y0, y1, cdir = make_unit.unit_years(man, a.chunk)
    root = support.output_root(W, a.scratch)
    set_dir = os.path.join(root, 'postprocessed', pset)
    static_dir = os.path.join(set_dir, 'static')
    unit_rel = f'{gcm}/{key}/{y0}-{y1}'
    unit_dir = os.path.join(set_dir, unit_rel)
    qc_dir = os.path.join(root, 'qc', 'postprocessed', pset, unit_rel)
    if not os.path.isdir(unit_dir):
        raise SystemExit(f'{unit_dir} does not exist')
    rec = support.load_yaml(os.path.join(unit_dir, 'provenance.yaml'))
    files = support.parameter_files(camp, W)
    protocol = support.protocol_variables(camp, W)
    recipes = make_unit.recipes(cfg, camp)
    grid = make_unit.Grid(W, cfg, files, static_dir)
    with nc.Dataset(os.path.join(static_dir, 'dis-outlets.nc')) as d:
        orow = np.ma.filled(d['outlet_row'][:], -1).ravel()[grid.cov]
        ocol = np.ma.filled(d['outlet_col'][:], -1).ravel()[grid.cov]
    static_outlets = np.searchsorted(grid.counted, orow * grid.shape5[1] + ocol)

    checks = {'record': check_record(W, rec, unit_dir, static_dir, man)}
    probs = {'files': [], 'time': [], 'coverage': []}
    rng, series, maps, values, monthly_of_daily = {}, {}, {}, {}, {}
    wcell = np.zeros(grid.shape[0] * grid.shape[1]); wcell[grid.cov] = grid.wsum
    wcell = wcell.reshape(grid.shape)
    keep = {(q, 'monthly') for target, parts in uc['identities'] for q in [target, *parts]}
    excl = rec.get('exclusions') or {}
    lat_row = {float(v): i for i, v in enumerate(grid.coords['lat'][0])}
    lon_col = {float(v): i for i, v in enumerate(grid.coords['lon'][0])}
    for f in rec['files']:
        var, step = f['variable'], f['time_step']
        layered = bool(recipes[var].get('layers'))
        allowed = {}
        for m in (excl.get(f['name']) or {}).get('missing_cells', []):
            rr, cc = allowed.setdefault(m['time_index'], ([], []))
            rr.append(lat_row[float(m['lat'])]); cc.append(lon_col[float(m['lon'])])
        p, st = check_file(os.path.join(unit_dir, f['name']), var, step, cfg, protocol, grid, layered, y0, y1, wcell,
                           keep=(var, step) in keep, allowed=allowed)
        for k, v in p.items():
            probs[k] += [f'{f["name"]}: {x}' for x in v]
        if st is None:
            continue
        rng[f['name']] = st['range']
        if st['values'] is not None:
            values[(var, step)] = st['values'].astype('f8')
        if st['monthly_means'] is not None:
            monthly_of_daily[var] = st['monthly_means']
        if step == 'monthly' and var in ('qtot', 'evap', 'potevap', 'tws', 'atotww', 'airrww', 'soilmoist'):
            series[var] = (st['series'][0], st['series'][1], f['units'])
        if step == 'monthly' and var in ('qtot', 'evap', 'tws', 'dis'):
            m = st['map']
            maps[var] = np.log10(np.maximum(m, 1e-3)) if var == 'dis' else m
    for k, v in probs.items():
        checks[k] = ('failed' if v else 'passed', {'problems': v})

    # identities
    idp, idd = [], {}
    for target, parts in uc['identities']:
        if (target, 'monthly') in values and all((q, 'monthly') in values for q in parts):
            a_ = values[(target, 'monthly')]
            sel = np.isfinite(a_)
            ok, diff, scale = close(a_[sel], sum(values[(q, 'monthly')] for q in parts)[sel], 1e-5)
            idd[target] = {'parts': parts, 'max_abs_diff': diff, 'scale': scale}
            if not ok:
                idp.append(f'{target} differs from {" + ".join(parts)} by {diff:.3g}')
    checks['identities'] = ('failed' if idp else 'passed', {'problems': idp, 'compared': idd})
    values.clear()

    # monthly means of the daily products against the monthly products
    dm, dmp = {}, []
    for var, mm in monthly_of_daily.items():
        name = f'{var}_monthly_{y0}_{y1}.nc'
        if not os.path.exists(os.path.join(unit_dir, name)):
            continue
        with nc.Dataset(os.path.join(unit_dir, name)) as d:
            mon = np.ma.filled(d[var][:].astype('f8'), np.nan)
        sel = np.isfinite(mon) & np.isfinite(mm)
        ok, diff, scale = close(mm[sel], mon[sel], uc['daily_monthly_rel_tol'])
        dm[var] = {'max_abs_diff': diff, 'scale': scale}
        if not ok:
            dmp.append(f'{var}: monthly mean of the daily product differs from the monthly product by {diff:.3g}')
    monthly_of_daily.clear()

    # recompute sampled steps from the 5' output; scan the rule output of every `exclude` recipe
    rp, rd_ = [], {}
    found = {f['name']: (set(), set()) for f in rec['files'] if recipes[f['variable']].get('exclude')}
    forcing_view = man.get('forcing_view') or {}
    for y in range(y0, y1 + 1):
        forcing = {}
        for series_name in {r['times_forcing'] for r in recipes.values() if r.get('times_forcing')}:
            with nc.Dataset(os.path.join(W, forcing_view[series_name][str(y)]['source'])) as d:
                vname = [k for k in d.variables if k not in ('time', 'lat', 'lon')][0]
                forcing[series_name] = np.nan_to_num(np.ma.filled(d[vname][0], np.nan).astype('f8')).ravel()[
                    grid.counted]
        for step in ('daily', 'monthly'):
            todo = [f for f in rec['files'] if f['time_step'] == step]
            if not todo:
                continue
            with nc.Dataset(os.path.join(rd, cdir, 'output', make_unit.STREAM_FILES[step].format(year=y))) as ds:
                bnds = np.asarray(ds['time_bnds'][:], 'f8')
                seconds = (bnds[:, 1] - bnds[:, 0]) * 86400.0
                offset = (y - y0) * 12 if step == 'monthly' else int(round(
                    (cftime.datetime(y, 1, 1, calendar=ds['time'].calendar) -
                     cftime.datetime(y0, 1, 1, calendar=ds['time'].calendar)).total_seconds() / 86400))
                sampled = sampled_steps(step, y, len(bnds), uc['recompute_steps_per_year'])
                for f in todo:
                    var = f['variable']; r = recipes[var]
                    steps_here = set(sampled)
                    if f['name'] in found:
                        s_, m_ = scan_exclusions(ds, len(bnds), r['exclude'], grid, offset)
                        found[f['name']][0].update(s_); found[f['name']][1].update(m_)
                        steps_here |= {t_ - offset for t_, _, _ in s_}
                    tun = {ds[n].units for n in r.get('terms', [])}
                    conv = make_unit.conversion(tun.pop(), f['units']) if tun else ('scale', 1.0)
                    for t in sorted(steps_here):
                        ref = recompute(ds, t, r, conv, seconds[t], grid, cfg, forcing, static_outlets)
                        with nc.Dataset(os.path.join(unit_dir, f['name'])) as d:
                            prod = np.ma.filled(d[var][offset + t].astype('f8'), np.nan)
                        prod = prod.reshape(prod.shape[:-2] + (-1,))[..., grid.cov]
                        same_missing = np.array_equal(np.isnan(prod), np.isnan(ref))
                        sel = ~np.isnan(ref)
                        ok, diff, scale = close(prod[sel], ref[sel], uc['recompute_rel_tol'])
                        rd_.setdefault(f['name'], {'steps': 0, 'max_rel_diff': 0.0})
                        rd_[f['name']]['steps'] += 1
                        rd_[f['name']]['max_rel_diff'] = max(rd_[f['name']]['max_rel_diff'], diff / max(scale, 1e-30))
                        if not (ok and same_missing):
                            rp.append(f'{f["name"]} step {offset + t}: differs from the 5 arcmin output by {diff:.3g} '
                                      f'(largest value {scale:.3g})' + ('' if same_missing else
                                                                        ', missing at other cells'))
    checks['recompute'] = ('failed' if rp else 'passed', {'problems': rp[:50], 'files': rd_})
    ep, ed = [], {}
    nx = grid.shape[1]
    for name, (steps_found, missing_found) in found.items():
        e = excl.get(name) or {}
        listed = {(c['time_index'], c['row5'], c['col5']) for c in e.get('cell_steps', [])}
        listed_missing = {(m['time_index'], lat_row[float(m['lat'])] * nx + lon_col[float(m['lon'])])
                          for m in e.get('missing_cells', [])}
        missing_flat = {(t_, int(grid.cov[p_])) for t_, p_ in missing_found}
        ed[name] = {'cell_steps': len(steps_found), 'missing_cells': len(missing_found)}
        if not e:
            ep.append(f'{name}: the unit record has no exclusions entry')
        if listed != steps_found:
            ep.append(f'{name}: {len(listed - steps_found)} cell-steps listed but not left out by the rule, '
                      f'{len(steps_found - listed)} left out but not listed')
        if listed_missing != missing_flat:
            ep.append(f'{name}: the 0.5 degree cells recorded as missing differ from the rule '
                      f'({len(listed_missing)} recorded, {len(missing_flat)} from the rule)')
    checks['exclusions'] = ('failed' if ep else 'passed', {'problems': ep, 'files': ed})
    outside = {k: v for k, v in rng.items() if v['values_outside']}
    checks['valid_range'] = ('warning' if outside else 'passed', {'files': rng})
    checks['daily_monthly'] = ('warning' if dmp else 'passed', {'problems': dmp, 'compared': dm})

    os.makedirs(f'{qc_dir}/reports', exist_ok=True)
    figures(series, maps, f'{qc_dir}/figures')
    status = support.combine([s for s, _ in checks.values()])
    summary = {'object': os.path.relpath(unit_dir, W), 'status': status,
               'checks': {k: s for k, (s, _) in checks.items()},
               'record_sha256': support.sha256(os.path.join(unit_dir, 'provenance.yaml')),
               'source': {'run_id': man['run_id'], 'chunk': a.chunk, 'attempt': rec['source']['attempt'],
                          'accepted_source': rec['source']['accepted_source']},
               'checked_by': {'script': 'workflow/06_postprocessing/check_unit.py', **state},
               'checked_at': support.utcnow()}
    support.write_json(f'{qc_dir}/reports/check.json',
                       {**summary, 'details': {k: d for k, (_, d) in checks.items()}})
    support.write_json(f'{qc_dir}/summary.json', summary)
    print(json.dumps({'status': status, 'checks': summary['checks']}, indent=1))
    support.exit_with(status)


if __name__ == '__main__':
    main()
