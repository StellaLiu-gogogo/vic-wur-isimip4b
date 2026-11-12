#!/usr/bin/env python3
"""Product unit: the 0.5-degree ISIMIP products made from one chunk of a run, or from a whole unchunked run
(D07, D08, D11).

Writes postprocessed/<product-set-id>/<gcm>/<segment-key>/<start-year>-<end-year>/ (below scratch/<task>/ with
--scratch): one file <variable>_<daily|monthly>_<start>_<end>.nc per ISIMIP variable and time step, and the unit
record provenance.yaml. The product-set ID is the campaign ID; the static files of the product set (static/) must
exist.

Recipes: `variables` of products.yaml; their VIC outputs must be exactly those of output.isimip in the campaign.
Every variable gets a monthly product from the monthly stream; a variable whose protocol frequency names daily also
gets a daily product when every VIC output of its recipe is in the run's daily stream (D07 part 4: soilmoist daily
in the historical and future segments, qtot and dis daily everywhere).

Aggregation (D07): the area-weighted mean over the active 5' cells inside each covered mask cell (weights domain
area x frac), volumes summed and divided by the simulated area, `dis` the value of the outlet cell; every other cell
is the fill value. An active 5' cell without a value stops the producer. A recipe with `exclude` leaves out the 5'
cell-steps of its rule (evap: task T rule, |OUT_WATER_ERROR| > 1 mm) and takes the weighted mean of the remaining
active 5' cells, the fill value where none remains; the unit record lists them (D07 amendment 2026-11-11). A recipe
with `nonrenewable_groundwater` adds the groundwater part of the non-renewable withdrawal, split per 5' cell, water-use
class and time step by `nonrenewable_split` (*wwgw, D07 amendment 2026-11-12). Time axis:
days since 1601-01-01 in the calendar of the run, a value stamped at the first day of its period (ISIMIP).

Sources: outside --scratch the run must be a production run, the chunk's latest attempt completed, and its chunk
check (or the run check of an unchunked run) passed and bound to that attempt; the repository must be clean (rule
14). The unit is written into .writing-<start>-<end>/ beside it and renamed when complete; an existing unit is never
overwritten. Inputs are recorded by size and modification time, the run manifest by sha256 (D11 amendment
2026-11-10).

Usage: make_unit.py --campaign configs/campaigns/<id>.yaml --run <run-id> [--chunk <start>-<end>]
                    [--scratch <task-id>] [--expect-commit <sha>]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import netCDF4 as nc
import cftime
from scipy import sparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routing         # noqa: E402
import product_set     # noqa: E402
import static_fields   # noqa: E402
import support         # noqa: E402

REFERENCE_TIME = 'days since 1601-01-01 00:00:00'
STREAM_FILES = {'daily': 'daily.{year}-01-01.nc', 'monthly': 'monthly.{year}-01.nc'}
KG_PER_HM3 = 1e9
CONVERSIONS = {('mm', 'kg m-2 s-1'): ('rate', None), ('mm', 'kg m-2'): ('scale', 1.0), ('C', 'K'): ('offset', 273.15),
               ('cm', 'm'): ('scale', 0.01), ('m3 s-1', 'm3 s-1'): ('scale', 1.0), ('1', '1'): ('scale', 1.0)}
DAILY_BLOCK = 31                       # days read at once from a daily file


# ------------------------------------------------------------------------------------------------ recipes
def recipes(cfg, camp):
    """{variable: recipe} of products.yaml, checked against output.isimip of the campaign."""
    iso = camp['output']['isimip']
    rec = cfg['variables']
    problems = [f'{v}: no recipe in products.yaml' for v in iso if v not in rec]
    problems += [f'{v}: recipe without a campaign mapping' for v in rec if v not in iso]
    for v in set(iso) & set(rec):
        r = rec[v]
        used = list(r.get('terms', [])) + list(r.get('volumes', []))
        if sorted(set(used)) != sorted(set(iso[v]['vic'])):
            problems.append(f'{v}: recipe outputs {sorted(set(used))} differ from the campaign {sorted(iso[v]["vic"])}')
        if r.get('sector') not in (None, 'all', *cfg['sectors']):
            problems.append(f'{v}: unknown sector {r.get("sector")}')
        problems += [f'{v}: unknown note {n}' for n in r.get('notes', []) if n not in (cfg.get('notes') or {})]
        ex = r.get('exclude')
        if ex is not None and (sorted(ex) != ['abs_above', 'output'] or ex['output'] in used or
                               any(r.get(k) for k in ('outlet', 'volumes', 'layers', 'times_forcing'))):
            problems.append(f'{v}: exclude needs exactly output and abs_above, an output outside the terms, and a '
                            'plain mean (no outlet, volumes, layers or times_forcing)')
        if r.get('nonrenewable_groundwater') and (
                v not in (cfg.get('campaign_exceptions') or {}) or not cfg.get('nonrenewable_split') or
                r.get('sector') is None or
                any(r.get(k) for k in ('exclude', 'outlet', 'volumes', 'layers', 'times_forcing'))):
            problems.append(f'{v}: nonrenewable_groundwater needs an entry in campaign_exceptions, nonrenewable_split, '
                            'a sector and a plain mean')
    problems += [f'{v}: listed in campaign_exceptions but reads no output beyond the campaign mapping'
                 for v in (cfg.get('campaign_exceptions') or {}) if not (rec.get(v) or {}).get('nonrenewable_groundwater')]
    if problems:
        raise SystemExit('products.yaml does not match the campaign: ' + '; '.join(problems))
    return {v: rec[v] for v in iso}


def split_outputs(sp):
    """VIC outputs read by the groundwater split of the non-renewable withdrawal."""
    return {sp['nonrenewable'], sp['demand_groundwater'], sp['demand_surface'], *sp['withdrawn_groundwater'],
            *sp['withdrawn_surface']}


def time_steps(recipe, protocol_frequency, streams, split_config=None):
    """Time steps of a variable: monthly always, daily when the protocol names daily and the daily stream has every
    VIC output of the recipe. `streams`: {stream: set of VIC outputs}."""
    used = set(recipe.get('terms', [])) | set(recipe.get('volumes', []))
    if recipe.get('exclude'):
        used.add(recipe['exclude']['output'])         # the rule needs the output in the same stream
    if recipe.get('nonrenewable_groundwater'):
        used |= split_outputs(split_config)
    if not used <= streams.get('monthly', set()):
        raise SystemExit(f'the monthly stream lacks {sorted(used - streams.get("monthly", set()))}')
    steps = ['monthly']
    if 'daily' in str(protocol_frequency) and used <= streams.get('daily', set()):
        steps.insert(0, 'daily')
    return steps


def conversion(vic_unit, protocol_unit):
    key = (vic_unit, protocol_unit)
    if key not in CONVERSIONS:
        raise SystemExit(f'no unit conversion from {vic_unit!r} to {protocol_unit!r}')
    return CONVERSIONS[key]


# ------------------------------------------------------------------------------------------------ grid
class Grid:
    """The 5' -> 0.5-degree mapping of D07: weights of the counted 5' cells (active, inside the mask), the outlet
    of every covered cell, the layer depths; checked against the static files of the product set."""

    def __init__(self, W, cfg, files, static_dir):
        inmask05, self.coords = static_fields.read_mask(W, cfg)
        self.shape = inmask05.shape
        with nc.Dataset(os.path.join(W, files['domain'])) as d:
            lat5, lon5 = np.ma.filled(d['lat'][:]).astype('f8'), np.ma.filled(d['lon'][:]).astype('f8')
            active = np.ma.filled(d['mask'][:], 0).ravel() == 1
            area = np.ma.filled(d['area'][:], 0.0).astype('f8').ravel()
            frac = np.ma.filled(d['frac'][:], 0.0).astype('f8').ravel()
        self.shape5 = (lat5.size, lon5.size)
        self.lat5, self.lon5 = lat5, lon5
        with nc.Dataset(os.path.join(W, files['routing'])) as d:
            d.set_auto_mask(False)
            nxt = routing.network(d['downstream'][:], d['downstream_id'][:], active)
        rows, _ = static_fields.block_index(lat5, self.coords['lat'][0])
        cols, _ = static_fields.block_index(lon5, self.coords['lon'][0])
        cell = static_fields.cell_index(rows, cols, self.shape[1])
        n05 = self.shape[0] * self.shape[1]
        depth0 = np.zeros((1, cell.size))
        f, w, counted = static_fields.static_fields(cell, n05, inmask05.ravel(), active, area, frac, depth0)
        upa = routing.upstream_area(nxt, np.where(active, area * frac, 0.0) / 1e6, active)
        out5 = static_fields.outlets(cell, n05, counted, upa)
        self.cov = np.flatnonzero(f['covered'])
        self.counted = np.flatnonzero(counted)
        wsum = f['weight_m2'][self.cov]
        pos = np.full(n05, -1, 'i8'); pos[self.cov] = np.arange(self.cov.size)
        r = pos[cell[self.counted]]
        c = np.arange(self.counted.size)
        self.weights, self.cellpos, self.wsum = w[self.counted], r, wsum     # for the unit check (check_unit.py)
        self.mean = sparse.csr_matrix((w[self.counted] / wsum[r], (r, c)), shape=(self.cov.size, self.counted.size))
        self.volume = sparse.csr_matrix((KG_PER_HM3 / wsum[r], (r, c)), shape=(self.cov.size, self.counted.size))
        self.outlet = np.searchsorted(self.counted, out5[self.cov])
        # the static files of the product set must describe the same mapping
        with nc.Dataset(os.path.join(static_dir, 'dis-outlets.nc')) as d:
            s_row = np.ma.filled(d['outlet_row'][:], -1).ravel()[self.cov]
            s_col = np.ma.filled(d['outlet_col'][:], -1).ravel()[self.cov]
            s_n = np.ma.filled(d['n_cells'][:], -1).ravel()
        if not (np.array_equal(s_row * self.shape5[1] + s_col, out5[self.cov])
                and np.array_equal(np.flatnonzero(s_n >= 0), self.cov)):
            raise SystemExit(f'the static files in {static_dir} do not match the parameter set and the mask')
        with nc.Dataset(os.path.join(static_dir, 'soil-layers.nc')) as d:
            th = np.ma.filled(d['layer_thickness'][:].astype('f8'), np.nan)
            bottom = np.ma.filled(d['layer_bottom'][:].astype('f8'), np.nan)
        self.depth_bnds = np.stack([bottom - th, bottom])            # (bnds, lev, lat, lon)
        self.depth = bottom - th / 2

    def to_grid(self, vals, fill):
        """(..., n_covered) -> (..., lat, lon) with the fill value elsewhere and where vals is NaN (a covered cell
        whose 5' cells were all left out by an `exclude` rule), float32."""
        out = np.full(vals.shape[:-1] + (self.shape[0] * self.shape[1],), fill, 'f4')
        out[..., self.cov] = np.where(np.isnan(vals), fill, vals)
        return out.reshape(vals.shape[:-1] + self.shape)

    def cell_steps(self, t_first, excluded, err, x, missing, period):
        """Records of the 5' cell-steps left out by an `exclude` rule. `excluded`: (time index within the block,
        counted index) arrays; `err`, `x`: values of the rule's output and of the product's terms (VIC units);
        `missing`: (time, covered) true where the product is missing; `period(t)`: label of time step t."""
        nx5, nx = self.shape5[1], self.shape[1]
        rows = []
        for t, i in zip(*excluded):
            k = int(self.counted[i]); p = int(self.cellpos[i]); c = int(self.cov[p])
            rows.append({'time_index': int(t_first + t), 'period': period(t), 'row5': k // nx5, 'col5': k % nx5,
                         'lat5': float(self.lat5[k // nx5]), 'lon5': float(self.lon5[k % nx5]),
                         'rule_value': float(err[t, i]), 'term_value': float(x[t, i]),
                         'lat': float(self.coords['lat'][0][c // nx]), 'lon': float(self.coords['lon'][0][c % nx]),
                         'cell_missing': bool(missing[t, p])})
        return rows


def read5(var, t0, t1, grid, sector=None):
    """Values of a VIC output on the counted 5' cells for time steps t0..t1-1: (time, [layer], counted) float64;
    `sector` an index of the water-use class, 'all' for their sum, or None. Stops on a missing value."""
    a = var[t0:t1] if sector is None or sector == 'all' else var[t0:t1, sector]
    a = np.ma.filled(a, np.nan).astype('f8')
    if sector == 'all':
        a = a.sum(axis=1)
    a = a.reshape(a.shape[:-2] + (-1,))[..., grid.counted]
    if np.isnan(a).any():
        raise SystemExit(f'{var.name}: missing values on active 5 arcmin cells')
    return a


def aggregate(matrix, a):
    """Apply a (n_covered x n_counted) matrix to the last axis of a."""
    flat = a.reshape(-1, a.shape[-1])
    return np.asarray((matrix @ flat.T).T).reshape(a.shape[:-1] + (matrix.shape[0],))


# ------------------------------------------------------------------------------------------------ one block
class Block:
    """One block of time steps of one stream file: the products of every recipe, with the aggregated VIC outputs
    cached so that an output used by several variables is read once."""

    def __init__(self, ds, t0, t1, grid, cfg, forcing):
        self.ds, self.t0, self.t1, self.grid, self.cfg = ds, t0, t1, grid, cfg
        self.forcing = forcing                     # {series: (counted,) array} of the block's year
        self.cache = {}
        self.excluded = {}                         # {variable: (time and counted indices, rule values, term values)}
        self.split = {}                            # {water-use class: groundwater part of the non-renewable source}

    def sector(self, recipe):
        s = recipe.get('sector')
        return None if s is None else ('all' if s == 'all' else self.cfg['sectors'][s])

    def term(self, name, sector, mode, layers):
        key = (name, sector, mode, layers)
        if key not in self.cache:
            a = read5(self.ds[name], self.t0, self.t1, self.grid, sector)
            if a.ndim == 3 and not layers:
                a = a.sum(axis=1)
            if mode == 'outlet':
                self.cache[key] = a[..., self.grid.outlet]
            else:
                self.cache[key] = aggregate(self.grid.mean if mode == 'mean' else self.grid.volume, a)
        return self.cache[key]

    def excluding_mean(self, var, recipe, sector):
        """Area-weighted mean that leaves out the 5' cell-steps of the recipe's `exclude` rule: in a 0.5-degree cell
        with a left-out cell the weighted mean of its other active 5' cells, NaN when none remains; every other cell
        keeps the plain mean."""
        vals = sum(self.term(n, sector, 'mean', False) for n in recipe['terms']).copy()
        ex = recipe['exclude']
        err = read5(self.ds[ex['output']], self.t0, self.t1, self.grid)
        out = np.abs(err) > ex['abs_above']
        if not out.any():
            return vals
        x = sum(read5(self.ds[n], self.t0, self.t1, self.grid, sector) for n in recipe['terms'])
        for t in np.flatnonzero(out.any(axis=1)):
            keep = ~out[t]
            num = aggregate(self.grid.mean, np.where(keep, x[t], 0.0)[None])[0]
            den = aggregate(self.grid.mean, keep.astype('f8')[None])[0]
            hit = np.unique(self.grid.cellpos[out[t]])
            ok = den[hit] > 0
            vals[t, hit] = np.where(ok, num[hit] / np.where(ok, den[hit], 1.0), np.nan)
        self.excluded[var] = (np.nonzero(out), err, x)
        return vals

    def groundwater_part(self, sector):
        """Groundwater part of the non-renewable withdrawal on the counted 5' cells, (time, counted): per water-use
        class N x Ug / (Ug + Us) (products.yaml, nonrenewable_split), summed over the classes for 'all'."""
        sp = self.cfg['nonrenewable_split']
        classes = range(self.ds[sp['nonrenewable']].shape[1]) if sector == 'all' else [sector]
        total = 0.0
        for k in classes:
            if k not in self.split:
                def r(name):
                    return read5(self.ds[name], self.t0, self.t1, self.grid, k)
                ug = np.maximum(0.0, r(sp['demand_groundwater']) - sum(r(n) for n in sp['withdrawn_groundwater']))
                us = np.maximum(0.0, r(sp['demand_surface']) - sum(r(n) for n in sp['withdrawn_surface']))
                u = ug + us
                self.split[k] = np.where(u > 0, r(sp['nonrenewable']) * ug / np.where(u > 0, u, 1.0), 0.0)
            total = total + self.split[k]
        return total

    def product(self, var, recipe, conv, seconds):
        """Values of one variable on the covered cells, in the protocol unit."""
        sector, layers = self.sector(recipe), bool(recipe.get('layers'))
        if recipe.get('exclude'):
            vals = self.excluding_mean(var, recipe, sector)
        elif recipe.get('times_forcing'):
            a = sum(read5(self.ds[n], self.t0, self.t1, self.grid, sector) for n in recipe['terms'])
            vals = aggregate(self.grid.mean, a * self.forcing[recipe['times_forcing']])
        else:
            mode = 'outlet' if recipe.get('outlet') else 'mean'
            vals = sum(self.term(n, sector, mode, layers) for n in recipe.get('terms', []))
        if recipe.get('nonrenewable_groundwater'):
            vals = vals + aggregate(self.grid.mean, self.groundwater_part(sector))
        kind, k = conv
        if kind == 'rate':
            vals = vals / seconds.reshape((-1,) + (1,) * (vals.ndim - 1))
        elif kind == 'scale':
            vals = vals * k
        elif kind == 'offset':
            vals = vals + k
        for n in recipe.get('volumes', []):
            vals = vals + self.term(n, None, 'volume', False)
        return vals


# ------------------------------------------------------------------------------------------------ sources
def unit_years(man, chunk):
    if chunk:
        c = [x for x in man.get('chunks') or [] if x['id'] == chunk]
        if not c:
            raise SystemExit(f'the run has no chunk {chunk}')
        return c[0]['start_year'], c[0]['end_year'], c[0]['dir']
    if man.get('chunks'):
        raise SystemExit('the run is chunked: give --chunk')
    return int(man['period']['start'][:4]), int(man['period']['end'][:4]), '.'


def segment(camp, man):
    """(gcm, segment key, period, scenario parts) of the run's segment."""
    sid = man['segment_id']
    gcm = [g for g in camp['gcms'] if sid.startswith(g + '_')]
    if len(gcm) != 1:
        raise SystemExit(f'cannot find the GCM of segment {sid}')
    key = sid[len(gcm[0]) + 1:]
    climate, soc, sens, period = key.split('_')
    if period == 'spinup':
        raise SystemExit('spin-ups are not reported; no products')
    return gcm[0], key, period, {'climate_scenario': climate, 'soc_scenario': soc, 'sens_scenario': sens}


# ------------------------------------------------------------------------------------------------ files
def create_file(path, cfg, grid, var, attrs, units, steps_total, calendar, layered, global_attrs):
    rules = cfg['file_rules']; fill = np.float32(cfg['fill_value'])
    d = nc.Dataset(path, 'w', format=rules['data_model'])
    d.createDimension('time', steps_total)
    if layered:
        d.createDimension('lev', grid.depth.shape[0]); d.createDimension('bnds', 2)
    for name in ('lat', 'lon'):
        vals, a = grid.coords[name]
        d.createDimension(name, vals.size)
        v = d.createVariable(name, 'f8', (name,)); v.setncatts(a); v[:] = vals
    t = d.createVariable('time', 'f8', ('time',))
    t.setncatts({'standard_name': 'time', 'long_name': 'Time', 'units': REFERENCE_TIME, 'calendar': calendar,
                 'axis': 'T'})
    dims = ('time', 'lat', 'lon')
    chunks = (1,) + grid.shape
    if layered:
        lev = d.createVariable('lev', 'i4', ('lev',))
        lev.setncatts({'long_name': 'VIC soil layer, counted from the surface', 'units': '1', 'axis': 'Z'})
        lev[:] = np.arange(1, grid.depth.shape[0] + 1)
        dep = d.createVariable('depth', 'f4', ('lev', 'lat', 'lon'), zlib=True, complevel=rules['complevel'],
                               chunksizes=(1,) + grid.shape, fill_value=fill)
        dep.setncatts({'long_name': 'depth of the middle of the soil layer', 'units': 'm', 'positive': 'down',
                       'bounds': 'depth_bnds', 'missing_value': fill})
        dep[:] = np.where(np.isnan(grid.depth), fill, grid.depth).astype('f4')
        db = d.createVariable('depth_bnds', 'f4', ('bnds', 'lev', 'lat', 'lon'), zlib=True,
                              complevel=rules['complevel'], chunksizes=(1, 1) + grid.shape, fill_value=fill)
        db.setncatts({'long_name': 'depth of the top and the bottom of the soil layer', 'units': 'm',
                      'missing_value': fill})
        db[:] = np.where(np.isnan(grid.depth_bnds), fill, grid.depth_bnds).astype('f4')
        dims = ('time', 'lev', 'lat', 'lon'); chunks = (1, 1) + grid.shape
    v = d.createVariable(var, 'f4', dims, zlib=True, complevel=rules['complevel'], chunksizes=chunks, fill_value=fill)
    v.setncatts({**attrs, 'units': units, 'missing_value': fill})
    g = dict(global_attrs)
    if layered:
        g.update({'time_varying_layer_depth': 'false', 'location_varying_layer_depth': 'true'})
    d.setncatts(g)
    return d


def describe(var, recipe, camp_rule, cfg):
    """Comment of a product variable: how it was made from the VIC-WUR outputs."""
    sector = recipe.get('sector')
    sec = '' if sector is None else (' (sum over the water-use sectors)' if sector == 'all' else
                                     f' (water-use sector {sector}, VIC class {cfg["sectors"][sector]})')
    parts = []
    if recipe.get('terms'):
        parts.append(' + '.join(recipe['terms']) +
                     (' + the groundwater part of OUT_WI_NREN_SECT' if recipe.get('nonrenewable_groundwater') else '')
                     + sec)
    if recipe.get('times_forcing'):
        parts.append(f'multiplied by the {recipe["times_forcing"].split("/")[-1].replace("_", " ")} of the water-use '
                     'forcing')
    how = ('the 5 arcmin value of the outlet cell of the 0.5 degree cell (largest upstream area; static file '
           'dis-outlets.nc)' if recipe.get('outlet') else
           'mean over the active 5 arcmin cells of the 0.5 degree cell weighted by their area')
    text = f'VIC-WUR {", ".join(parts)}; {how}'
    if recipe.get('volumes'):
        text += f'; plus {" + ".join(recipe["volumes"])} (hm3) summed over the 0.5 degree cell and divided by its ' \
                'simulated area'
    if recipe.get('layers'):
        text += '; per VIC soil layer'
    ex = recipe.get('exclude')
    if ex:
        text += (f'; 5 arcmin cell-steps whose |{ex["output"]}| exceeds {ex["abs_above"]:g} mm (rare snow-sublimation '
                 'outliers of VIC) are left out of the mean, and a 0.5 degree cell whose active 5 arcmin cells are '
                 'all left out is missing; they are listed in provenance.yaml of the product unit')
    if camp_rule:
        text += f'. Campaign rule: {camp_rule}'
    text += ' (D07).'
    for n in recipe.get('notes', []):
        text += ' ' + ' '.join(cfg['notes'][n].split())
    return text


def missing_cells(rows):
    """0.5-degree cell-steps made missing by an `exclude` rule, from its cell-step records."""
    keys = sorted({(r['time_index'], r['period'], r['lat'], r['lon']) for r in rows if r['cell_missing']})
    return [{'time_index': t, 'period': p, 'lat': la, 'lon': lo} for t, p, la, lo in keys]


def exclusion_count_text(n_steps, n_missing):
    """Sentence appended to the comment of a product with an `exclude` rule once the file is written."""
    return (f' This file: {n_steps} 5 arcmin cell-steps left out, {n_missing} 0.5 degree cell-steps missing because '
            'of them.')


def output_files(rd, out_dir, years):
    paths = []
    for y in range(years[0], years[1] + 1):
        for s in ('daily', 'monthly'):
            p = os.path.join(rd, out_dir, 'output', STREAM_FILES[s].format(year=y))
            if not os.path.exists(p):
                raise SystemExit(f'{p} does not exist')
            paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--campaign', required=True)
    ap.add_argument('--run', required=True, help='run ID (directory below runs/<campaign-id>/)')
    ap.add_argument('--chunk', help='<start-year>-<end-year> of a chunked run')
    ap.add_argument('--scratch', metavar='TASK_ID')
    ap.add_argument('--expect-commit')
    a = ap.parse_args()
    started = support.utcnow()
    W = support.workdir(); cfg = support.config()
    state = support.check_expected_commit(a.expect_commit) if a.expect_commit else support.git_state()
    if state['dirty'] and not a.scratch:
        raise SystemExit('the repository is not clean: accepted product units need a clean repository (rule 14); '
                         'use --scratch <task-id>')
    camp, camp_sha, camp_rel = support.campaign(a.campaign)
    pset = camp['campaign_id']
    rd = os.path.join(W, 'runs', pset, a.run)
    man_path = os.path.join(rd, 'run_manifest.json')
    with open(man_path) as fh:
        man = json.load(fh)
    attempt, check, problems = product_set.source_state(W, man, a.chunk)
    if problems and not a.scratch:
        raise SystemExit('the source is not accepted: ' + '; '.join(problems))
    if attempt.get('status') != 'completed':
        raise SystemExit(f'the latest attempt of the source is {attempt.get("status")}')
    gcm, key, period, scen = segment(camp, man)
    y0, y1, cdir = unit_years(man, a.chunk)
    root = support.output_root(W, a.scratch)
    set_dir = os.path.join(root, 'postprocessed', pset)
    static_dir = os.path.join(set_dir, 'static')
    unit_rel = f'{gcm}/{key}/{y0}-{y1}'
    target = os.path.join(set_dir, gcm, key, f'{y0}-{y1}')
    staging = os.path.join(set_dir, gcm, key, f'.writing-{y0}-{y1}')
    if os.path.exists(target):
        raise SystemExit(f'{target} exists; product units are never overwritten')
    if os.path.exists(staging):
        raise SystemExit(f'{staging} exists (an interrupted job); the user decides on its deletion')
    if not os.path.isdir(static_dir):
        raise SystemExit(f'{static_dir} does not exist: make the static files first')
    files = support.parameter_files(camp, W)
    protocol = support.protocol_variables(camp, W)
    rec = recipes(cfg, camp)
    sources = output_files(rd, cdir, (y0, y1))
    grid = Grid(W, cfg, files, static_dir)

    # streams, units, time steps and calendar from the first year's files
    streams, units5, calendar = {}, {}, None
    for s in ('daily', 'monthly'):
        with nc.Dataset(os.path.join(rd, cdir, 'output', STREAM_FILES[s].format(year=y0))) as d:
            streams[s] = {k for k in d.variables if k.startswith('OUT_')}
            for k in streams[s]:
                units5[k] = d[k].units
            calendar = calendar or d['time'].calendar
    products = []                                              # (var, step, recipe, conversion, protocol unit)
    for var, r in rec.items():
        punit = support.for_sector(protocol[var]['units'])
        tunits = {units5[n] for n in r.get('terms', [])}
        if len(tunits) > 1 or any(units5[n] != 'hm3' for n in r.get('volumes', [])):
            raise SystemExit(f'{var}: VIC outputs in different units {sorted(tunits)}')
        conv = conversion(tunits.pop(), punit) if r.get('terms') else ('scale', 1.0)
        if r.get('exclude') and units5.get(r['exclude']['output']) != 'mm':
            raise SystemExit(f'{var}: the exclude rule is in mm, {r["exclude"]["output"]} is in '
                             f'{units5.get(r["exclude"]["output"])}')
        if r.get('volumes') and punit != 'kg m-2':
            raise SystemExit(f'{var}: volumes need the protocol unit kg m-2, not {punit}')
        for step in time_steps(r, support.for_sector(protocol[var].get('frequency')), streams,
                               cfg.get('nonrenewable_split')):
            products.append((var, step, r, conv, punit))

    # number of time steps of the unit
    def nsteps(step):
        if step == 'monthly':
            return 12 * (y1 - y0 + 1)
        d0 = cftime.datetime(y0, 1, 1, calendar=calendar); d1 = cftime.datetime(y1 + 1, 1, 1, calendar=calendar)
        return int(round((d1 - d0).total_seconds() / 86400))

    ident_base = {'model': None, 'climate_forcing': gcm, 'bias_adjustment': cfg['identity']['bias_adjustment'],
                  **scen, 'region': cfg['identity']['region']}
    global_attrs = {
        'title': f'VIC-WUR ISIMIP4b product of segment {man["segment_id"]}, {y0}-{y1}',
        'institution': cfg['attributes']['institution'], 'contact': cfg['attributes']['contact'],
        'product_set': pset, 'segment_id': man['segment_id'], 'run_id': man['run_id'],
        'chunk': a.chunk or 'whole run', 'model_commit': camp['model']['commit'],
        'parameter_set': camp['parameter_set']['id'], 'protocol_commit': camp['protocol']['commit'],
        'decisions': 'D07, D08, D11', 'created_by': 'workflow/06_postprocessing/make_unit.py',
        'code_commit': state['commit'], 'code_branch': state['branch'], 'code_dirty': str(state['dirty']).lower(),
        'created_at': started}
    for k in ('institution', 'contact'):
        if not cfg['attributes'].get(k):
            raise SystemExit(f'attributes.{k} of products.yaml is not set')
    os.makedirs(staging)
    out, offsets, comments = {}, {}, {}
    for var, step, r, conv, punit in products:
        p = support.for_sector(protocol[var].get('long_name'))
        attrs = {'long_name': p, 'comment': describe(var, r, camp['output']['isimip'][var].get('rule'), cfg)}
        comments[(var, step)] = attrs['comment']
        g = dict(global_attrs)
        if punit in ('kg m-2 s-1', 'kg m-2'):
            g['reference_area'] = 'simulated continental area of the grid cell (contfrac x cellarea, static files)'
        name = f'{var}_{step}_{y0}_{y1}.nc'
        out[(var, step)] = create_file(os.path.join(staging, name), cfg, grid, var, attrs, punit, nsteps(step),
                                       calendar, bool(r.get('layers')), g)
        offsets[(var, step)] = 0

    fill = cfg['fill_value']
    forcing_view = man.get('forcing_view') or {}
    excluded = {(var, step): [] for var, step, r, _, _ in products if r.get('exclude')}
    for y in range(y0, y1 + 1):
        forcing = {}
        for series in {r['times_forcing'] for r in rec.values() if r.get('times_forcing')}:
            src = forcing_view[series][str(y)]['source']
            with nc.Dataset(os.path.join(W, src)) as d:
                v = [k for k in d.variables if k not in ('time', 'lat', 'lon')][0]
                f = np.nan_to_num(np.ma.filled(d[v][0], np.nan).astype('f8')).ravel()[grid.counted]
            forcing[series] = f
        for step in ('daily', 'monthly'):
            todo = [p for p in products if p[1] == step]
            if not todo:
                continue
            with nc.Dataset(os.path.join(rd, cdir, 'output', STREAM_FILES[step].format(year=y))) as ds:
                tv = ds['time']
                dates = cftime.num2date(tv[:], tv.units, calendar)
                if dates[0].year != y or dates[0].month != 1 or dates[0].day != 1 or \
                        any(dd.year != y for dd in dates):
                    raise SystemExit(f'{STREAM_FILES[step].format(year=y)}: time axis not inside {y}')
                tnum = cftime.date2num(dates, REFERENCE_TIME, calendar)
                bnds = np.asarray(ds['time_bnds'][:], 'f8')
                seconds = (bnds[:, 1] - bnds[:, 0]) * 86400.0
                n = len(tnum)
                size = n if step == 'monthly' else DAILY_BLOCK
                for t0 in range(0, n, size):
                    t1 = min(n, t0 + size)
                    blk = Block(ds, t0, t1, grid, cfg, forcing)
                    for var, _, r, conv, _ in todo:
                        vals = blk.product(var, r, conv, seconds[t0:t1])
                        f = out[(var, step)]
                        o = offsets[(var, step)]
                        f['time'][o + t0:o + t1] = tnum[t0:t1]
                        f[var][o + t0:o + t1] = grid.to_grid(vals, fill)
                        if var in blk.excluded:
                            idx, err, x = blk.excluded[var]
                            fmt = '%Y-%m' if step == 'monthly' else '%Y-%m-%d'
                            excluded[(var, step)] += grid.cell_steps(
                                o + t0, idx, err, x, np.isnan(vals), lambda t, t0=t0: dates[t0 + t].strftime(fmt))
                for var, _, _, _, _ in todo:
                    offsets[(var, step)] += n
        print(f'{y} done {time.strftime("%H:%M:%S")}', flush=True)
    for (var, step), f in out.items():
        if offsets[(var, step)] != len(f.dimensions['time']):
            raise SystemExit(f'{var} {step}: {offsets[(var, step)]} time steps instead of {len(f.dimensions["time"])}')
        if (var, step) in excluded:
            rows = excluded[(var, step)]
            f[var].setncattr('comment', comments[(var, step)] +
                             exclusion_count_text(len(rows), len(missing_cells(rows))))
        f.close()

    # unit record (D11, amendment 2026-11-10)
    def stat(p):
        st = os.stat(p)
        return {'path': os.path.relpath(p, W), 'size_bytes': st.st_size,
                'mtime': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st.st_mtime))}

    forcing_used = sorted({forcing_view[r['times_forcing']][str(y)]['source'] for r in rec.values()
                           if r.get('times_forcing') for y in range(y0, y1 + 1)})
    prod_files = []
    for var, step, r, conv, punit in products:
        name = f'{var}_{step}_{y0}_{y1}.nc'
        p = os.path.join(staging, name)
        prod_files.append({'name': name, 'variable': var, 'time_step': step, 'years': [y0, y1], 'units': punit,
                           'size_bytes': os.path.getsize(p), 'sha256': support.sha256(p),
                           'identity': {**ident_base, 'variable': var, 'time_step': step, 'start_year': y0,
                                        'end_year': y1}})
    record = {
        'product_unit': f'postprocessed/{pset}/{unit_rel}', 'product_set': pset, 'segment_id': man['segment_id'],
        'segment_key': key, 'gcm': gcm, 'period': period, 'years': [y0, y1], 'chunk': a.chunk,
        'source': {'campaign': pset, 'campaign_file': camp_rel, 'campaign_sha256': camp_sha,
                   'run_id': man['run_id'], 'run_dir': man['run_dir'], 'production': bool(man.get('production')),
                   'run_manifest_sha256': support.sha256(man_path), 'attempt': attempt, 'check': check,
                   'accepted_source': not problems, 'problems': problems,
                   'output_files': [stat(p) for p in sources]},
        'inputs': {'static_files': {fn: support.sha256(os.path.join(static_dir, fn))
                                    for fn in static_fields.STATIC_FILES},
                   'mask': {'path': cfg['product_grid']['mask'],
                            'sha256': support.sha256(os.path.join(W, cfg['product_grid']['mask']))},
                   'parameter_files': {k: stat(os.path.join(W, files[k])) for k in ('domain', 'routing')},
                   'forcing_files': [{**stat(os.path.join(W, p)), 'sha256': support.sha256(os.path.join(W, p))}
                                     for p in forcing_used]},
        'code': {'script': 'workflow/06_postprocessing/make_unit.py', **state,
                 'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'started_at': started, 'ended_at': support.utcnow()},
        'method': {'decisions': ['D07', 'D08', 'D11'], 'protocol_commit': camp['protocol']['commit'],
                   'products_yaml_sha256': support.sha256(support.CONFIG), 'reference_time': REFERENCE_TIME,
                   'calendar': calendar, 'fill_value': fill,
                   'nonrenewable_split': cfg.get('nonrenewable_split'),
                   'campaign_exceptions': cfg.get('campaign_exceptions') or {}},
        'files': prod_files,
        'exclusions': {f'{var}_{step}_{y0}_{y1}.nc': {
            'rule': {**rec[var]['exclude'], 'units': units5[rec[var]['exclude']['output']],
                     'terms': rec[var]['terms'], 'source': 'task T rule (user 2026-10-30); D07 amendment 2026-11-11'},
            'cell_steps': rows, 'missing_cells': missing_cells(rows)}
            for (var, step), rows in excluded.items()},
        'check': {'qc_summary': f'qc/postprocessed/{pset}/{unit_rel}/summary.json'},
    }
    support.write_yaml(os.path.join(staging, 'provenance.yaml'), record)
    os.rename(staging, target)
    print(f'wrote {len(prod_files)} files to {target}')


if __name__ == '__main__':
    main()
