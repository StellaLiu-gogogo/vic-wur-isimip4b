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
  coverage    values on exactly the covered mask cells at every time step (static files), no NaN
  recompute   for recompute_steps_per_year sampled time steps per year, every product recomputed from the 5' output
              with sums per cell (not the producer's matrix) equals the product within recompute_rel_tol; dis equals
              the 5' discharge of the outlet cells
  identities  0.5-degree products that the recipes make equal (qtot = qs + qsb, qg = qr = qsb)
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


def check_file(path, var, step, cfg, protocol, grid, layered, y0, y1, wcell, keep=False, block=366):
    """Format, time axis, coverage and value range of one product file, read in blocks of time steps. Returns
    (problems of each check, statistics): range, the global area-weighted series, the time mean (map), the monthly
    means of a daily file, and all values when `keep`."""
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
            c = cov if not layered else cov[None]
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
            probs['coverage'].append(f'{off} values off the covered cells, {on_missing} missing on covered cells '
                                     '(all time steps and layers)')
        mean = total / max(n, 1)
        stats = {'range': {'min': vmin, 'max': vmax, 'valid_min': lo, 'valid_max': hi, 'values_outside': outside},
                 'series': (tv, series), 'map': np.where(cov if not layered else cov[None], mean, np.nan),
                 'monthly_means': None if month is None else
                 np.where(cov if not layered else cov[None], msum / mcnt.reshape((-1,) + (1,) * (msum.ndim - 1)),
                          np.nan),
                 'values': kept}
    return probs, stats


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
    if recipe.get('outlet'):
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
    for f in rec['files']:
        var, step = f['variable'], f['time_step']
        layered = bool(recipes[var].get('layers'))
        p, st = check_file(os.path.join(unit_dir, f['name']), var, step, cfg, protocol, grid, layered, y0, y1, wcell,
                           keep=(var, step) in keep)
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

    # recompute sampled steps from the 5' output
    rp, rd_ = [], {}
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
                for t in sampled_steps(step, y, len(bnds), uc['recompute_steps_per_year']):
                    for f in todo:
                        var = f['variable']; r = recipes[var]
                        tun = {ds[n].units for n in r.get('terms', [])}
                        conv = make_unit.conversion(tun.pop(), f['units']) if tun else ('scale', 1.0)
                        ref = recompute(ds, t, r, conv, seconds[t], grid, cfg, forcing, static_outlets)
                        with nc.Dataset(os.path.join(unit_dir, f['name'])) as d:
                            prod = np.ma.filled(d[var][offset + t].astype('f8'), np.nan)
                        prod = prod.reshape(prod.shape[:-2] + (-1,))[..., grid.cov]
                        ok, diff, scale = close(prod, ref, uc['recompute_rel_tol'])
                        rd_.setdefault(f['name'], {'steps': 0, 'max_rel_diff': 0.0})
                        rd_[f['name']]['steps'] += 1
                        rd_[f['name']]['max_rel_diff'] = max(rd_[f['name']]['max_rel_diff'], diff / max(scale, 1e-30))
                        if not ok:
                            rp.append(f'{f["name"]} step {offset + t}: differs from the 5 arcmin output by {diff:.3g} '
                                      f'(largest value {scale:.3g})')
    checks['recompute'] = ('failed' if rp else 'passed', {'problems': rp[:50], 'files': rd_})
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
