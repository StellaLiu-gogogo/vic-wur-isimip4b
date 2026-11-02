#!/usr/bin/env python3
"""Convergence test of a spin-up block (D19 spin-up rule 3, amended by the user on 2026-11-02; task P3b, task X).

Reads the monthly spin-up output of the block (output.spinup of the campaign, one file per year; a chunked block
through its chunks), the domain and routing files of the parameter set, and writes to
qc/runs/<campaign-id>/<run-id>/: summary.json (status passed, failed or not_checked), reports/convergence.json,
reports/convergence_annual.csv and figures/convergence_global.png, figures/convergence_basins.png,
figures/convergence_map_soil_moisture_layer3.png; from a repository that is not clean the same files go to
scratch/spinup-check/uncommitted/qc/runs/... and the block has no test.

Window: the last WINDOW_YEARS (25) annual values of the block (the whole of a 25-year continuation block, the last
25 years of the first, 50-year block).

Quantities tested per active grid cell (annual values; month means weighted by their number of days)
  soil_moisture_layer2/3     soil moisture of VIC layers 2 and 3 (mm)
  december_swe               snow water equivalent of December (OUT_SWE + OUT_SNOW_CANOPY, mm) without the
                             perennial-snow cells: cells whose monthly snow water equivalent is never below
                             PERENNIAL_SWE_MM in the window years (snow that never melts and grows without a glacier
                             model; stands in for the glacier cells of D18, which an analysis identified)
  river_storage              OUT_STREAM_MOIST, annual mean (mm)
Quantities tested as global totals
  reservoir_storage          OUT_GDAM_STORAGE + OUT_LDAM_STORAGE (hm3 per cell), annual mean volume (km3); only
                             with the dams plugin on
  irrigation_withdrawal      sector 4 of OUT_WI_{GW,SURF,DAM,TREM,NREN}_SECT (mm per month), annual volume (km3);
                             only for a 2021soc spin-up with the irrigation plugin on (D19)
Test of a series of WINDOW_YEARS annual values: the least-squares trend b (per year) and the standard deviation s
(ddof 2, two fitted parameters) of the values after removing that trend; the series passes when |b| <= TREND_LIMIT * s
(the change over a decade is at most one interannual standard deviation); a constant series passes when its slope is
zero. A per-cell quantity passes when at least CELL_FRACTION (80 %) of its active cells pass (the perennial-snow cells
are left out of the December snow count); a global quantity passes when its series passes. The block has converged
(status passed, exit status 0) when every per-cell and global quantity passes, and has not converged (status failed,
exit status 3, the next block follows) otherwise. The global area-weighted series of the per-cell quantities and
their values over the BASINS largest river basins are diagnostics (CSV and figures), they do not decide. A block
shorter than WINDOW_YEARS years, a missing file, a missing variable or a missing value on an active cell means the
test could not be evaluated: status not_checked (exit status 4), and the renderer does not continue the chain until
the block has been looked at (review 2026-11-01, R6). Exit status 1 is left to errors of the test itself (R17).

Memory: the per-cell annual values of the window years are kept as float32 over the active cells (25 years x
active cells x 4 quantities, about 1 GB on the 5 arcmin domain); one year file is read at a time.

Usage: check_spinup.py --run-dir runs/<campaign-id>/<run-id>
"""
import argparse, csv, datetime, json, os, sys

import numpy as np
import netCDF4 as nc
import yaml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import grdc          # noqa: E402  (routing network, upstream area, outlets)
from common import gitstate, qc as qc_status   # noqa: E402

CHECKED_BY = 'workflow/05_simulation/monitor/check_spinup.py'
RULE = 'D19 amendment 2026-11-02'
WINDOW_YEARS = 25
TREND_LIMIT = 0.1
CELL_FRACTION = 0.8
PERENNIAL_SWE_MM = 1.0
BASINS = 20
IRRIGATION_SECTOR = 4
CELL_QUANTITIES = ('soil_moisture_layer2', 'soil_moisture_layer3', 'december_swe', 'river_storage')
WI = ('OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_DAM_SECT', 'OUT_WI_TREM_SECT', 'OUT_WI_NREN_SECT')
FILL_LIMIT = 1e19
UNCOMMITTED = 'scratch/spinup-check/uncommitted'


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


def trend_ratio(Y):
    """Per column of Y (years x series): the least-squares slope per year, the standard deviation of the detrended
    values (ddof 2) and |slope| / sd. A column with a constant value (sd within 1e-12 of its scale) gets ratio 0 when
    its slope is zero at that precision, inf otherwise; a column with a missing value gets nan everywhere."""
    Y = np.asarray(Y, 'f8')
    n = Y.shape[0]
    t = np.arange(n, dtype='f8'); tc = t - t.mean()
    b = (tc[:, None] * (Y - Y.mean(axis=0))).sum(axis=0) / (tc ** 2).sum()
    a = Y.mean(axis=0) - b * t.mean()
    res = Y - (a + np.outer(t, b))
    sd = np.sqrt((res ** 2).sum(axis=0) / max(n - 2, 1))
    scale = np.maximum(np.abs(Y).max(axis=0), 1e-30)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.abs(b) / sd
    const = sd <= 1e-12 * scale
    ratio = np.where(const, np.where(np.abs(b) <= 1e-12 * scale, 0.0, np.inf), ratio)
    bad = ~np.isfinite(Y).all(axis=0)
    ratio[bad] = np.nan; b[bad] = np.nan; sd[bad] = np.nan
    return b, sd, ratio, const & ~bad


def trend_test(values, limit=TREND_LIMIT):
    """{slope_per_year, detrended_sd, ratio, limit, passed} of one series of annual values (see the module text)."""
    y = np.asarray(values, 'f8')
    if y.size < 3 or not np.isfinite(y).all():
        return {'slope_per_year': None, 'detrended_sd': None, 'ratio': None, 'limit': limit, 'passed': False,
                'note': 'fewer than 3 values or a missing value'}
    b, sd, ratio, _ = trend_ratio(y[:, None])
    return {'slope_per_year': float(b[0]), 'detrended_sd': float(sd[0]), 'ratio': float(ratio[0]), 'limit': limit,
            'passed': bool(ratio[0] <= limit)}


def cell_test(Y, limit=TREND_LIMIT, fraction=CELL_FRACTION):
    """Test of a per-cell quantity: Y is (window years x cells). Returns the record {cells, passed_cells,
    fraction_passed, threshold, constant_cells, limit, passed} and the per-cell ratio."""
    _, _, ratio, const = trend_ratio(Y)
    ok = np.isfinite(ratio) & (ratio <= limit)
    n = int(ratio.size); k = int(ok.sum())
    return {'cells': n, 'passed_cells': k, 'fraction_passed': (k / n) if n else None, 'threshold': fraction,
            'constant_cells': int(const.sum()), 'missing_cells': int((~np.isfinite(ratio)).sum()), 'limit': limit,
            'passed': bool(n and k / n >= fraction)}, ratio


def block_status(tests, problems):
    """Status of the block: not_checked when the test could not be evaluated (problems, or no quantity tested),
    failed (not converged) when a deciding quantity fails, passed otherwise."""
    if problems or not tests:
        return 'not_checked'
    return 'failed' if any(not r['passed'] for r in tests.values()) else 'passed'


def exit_status(status):
    """Exit status of the test job: passed 0, not converged 3 (a warning, not a failed job), not_checked 4; 1 is left
    to errors of the test itself."""
    return qc_status.EXIT_CODES['warning' if status == 'failed' else status]


def largest_basins(routing_path, mask, area_m2, lat, lon, n=BASINS):
    """(label per cell: basin rank 0..n-1 or -1, [basin records]) of the n outlets with the largest upstream area."""
    with nc.Dataset(routing_path) as r:
        r.set_auto_mask(False)
        nxt = grdc.network(r['downstream'][:], r['downstream_id'][:], mask)
    upa = grdc.upstream_area(nxt, area_m2 / 1e6, mask)
    out = grdc.outlets(nxt)
    act = mask.ravel()
    outlets = np.flatnonzero(act & (nxt == np.arange(nxt.size)))
    top = outlets[np.argsort(upa[outlets])[::-1][:n]]
    label = np.full(nxt.size, -1, 'i8')
    rank = {int(c): i for i, c in enumerate(top)}
    sel = act & np.isin(out, top)
    label[sel] = [rank[int(c)] for c in out[sel]]
    ncol = mask.shape[1]
    recs = [{'rank': i + 1, 'outlet_lat': float(lat[c // ncol]), 'outlet_lon': float(lon[c % ncol]),
             'upstream_area_km2': float(upa[c]), 'cells': int((label == i).sum())} for i, c in enumerate(top)]
    return label.reshape(mask.shape), recs


def field(ds, name, t, layer=None):
    v = ds[name]; v.set_auto_mask(False)
    a = np.asarray(v[t] if layer is None else v[t, layer], 'f8')
    a[np.abs(a) > FILL_LIMIT] = np.nan
    return a


def month_days(ds):
    tb = np.asarray(ds['time_bnds'][:], 'f8')
    return tb[:, 1] - tb[:, 0]


class Year:
    """Annual values of one year file: per active cell (`cell`, float32 over the active cells, kept for the window
    years) and as global and basin means or totals (`values`), with the lowest monthly snow of the year for the
    perennial-snow rule."""

    def __init__(self, path, mask, area, label, nbasin, quantities, keep_cells=True):
        self.values, self.problems, self.cell = {}, [], {}
        with nc.Dataset(path) as ds:
            need = {'OUT_SOIL_MOIST', 'OUT_SWE', 'OUT_STREAM_MOIST'} | \
                ({'OUT_GDAM_STORAGE', 'OUT_LDAM_STORAGE'} if 'reservoir_storage' in quantities else set()) | \
                (set(WI) if 'irrigation_withdrawal' in quantities else set())
            missing = sorted(need - set(ds.variables))
            if missing:
                self.problems.append(f'{os.path.basename(path)}: variables missing {missing}')
                return
            w = month_days(ds); w = w / w.sum(); nm = len(w)
            if nm != 12:
                self.problems.append(f'{os.path.basename(path)}: {nm} months')
                return
            cell_area = np.where(mask, area, 0.0)
            lab = label[mask]; a_act = area[mask]
            bas_area = np.bincount(lab[lab >= 0], weights=a_act[lab >= 0], minlength=nbasin)
            sm = {2: np.zeros(1 + nbasin), 3: np.zeros(1 + nbasin)}
            cell = {k: np.zeros(int(mask.sum()), 'f8') for k in ('soil_moisture_layer2', 'soil_moisture_layer3',
                                                                 'river_storage')}
            river = reservoir = irrigation = 0.0
            self.swe_min = np.full(int(mask.sum()), np.inf, 'f4')    # lowest monthly snow of the year (perennial test)
            for t in range(nm):
                for layer in (2, 3):
                    f = field(ds, 'OUT_SOIL_MOIST', t, layer - 1)[mask]
                    if not np.isfinite(f).all():
                        self.problems.append(f'{os.path.basename(path)} month {t + 1}: soil moisture missing on '
                                             f'{int((~np.isfinite(f)).sum())} active cells')
                    cell[f'soil_moisture_layer{layer}'] += w[t] * f
                    sm[layer][0] += w[t] * np.nansum(f * a_act) / a_act.sum()
                    bsum = np.bincount(lab[lab >= 0], weights=(f * a_act)[lab >= 0], minlength=nbasin)
                    sm[layer][1:] += w[t] * bsum / bas_area
                s = field(ds, 'OUT_SWE', t)
                if 'OUT_SNOW_CANOPY' in ds.variables:
                    s = s + np.nan_to_num(field(ds, 'OUT_SNOW_CANOPY', t))
                s = s[mask].astype('f4')
                self.swe_min = np.fmin(self.swe_min, s)
                if t == 11:
                    cell['december_swe'] = s.astype('f8')
                r = field(ds, 'OUT_STREAM_MOIST', t)
                cell['river_storage'] += w[t] * r[mask]
                river += w[t] * np.nansum(r * cell_area) * 1e-12
                if 'reservoir_storage' in quantities:
                    reservoir += w[t] * (np.nansum(field(ds, 'OUT_GDAM_STORAGE', t)[mask]) +
                                         np.nansum(field(ds, 'OUT_LDAM_STORAGE', t)[mask])) * 1e-3
                if 'irrigation_withdrawal' in quantities:
                    irrigation += sum(np.nansum(field(ds, n, t)[IRRIGATION_SECTOR] * cell_area) for n in WI) * 1e-12
        for layer in (2, 3):
            self.values[f'soil_moisture_layer{layer}'] = float(sm[layer][0])
            for i in range(nbasin):
                self.values[f'soil_moisture_layer{layer}_basin{i + 1:02d}'] = float(sm[layer][1 + i])
        self.values['river_storage'] = float(river)
        if 'reservoir_storage' in quantities:
            self.values['reservoir_storage'] = float(reservoir)
        if 'irrigation_withdrawal' in quantities:
            self.values['irrigation_withdrawal'] = float(irrigation)
        if keep_cells:
            self.cell = {k: v.astype('f4') for k, v in cell.items()}
        self.swe_dec = cell['december_swe'].astype('f4')      # every year: the global December series (diagnostic)


def perennial_cells(years, window):
    """Active cells (1-D, over the active cells) whose monthly snow water equivalent never falls below
    PERENNIAL_SWE_MM in the window years."""
    lows = np.fmin.reduce([years[y].swe_min for y in window])
    return lows >= PERENNIAL_SWE_MM


def evaluate(years, window, quantities, a_act):
    """The test of a block from the Year records (every year of the block; the window years with per-cell values):
    returns (series, cell_tests, global_tests, perennial, ratios). `series` holds the global and basin annual values
    of every year (december_swe without the perennial-snow cells, km3), `cell_tests` the per-cell quantities'
    records, `global_tests` the trend test of every global series (`decides` True for reservoir storage and
    irrigation withdrawal), `ratios` the per-cell ratio of every per-cell quantity."""
    perennial = perennial_cells(years, window)
    keep = ~perennial
    series = {}
    for k in years[window[0]].values:
        series[k] = {y: years[y].values[k] for y in years}
    series['december_swe'] = {y: float(np.nansum(years[y].swe_dec[keep] * a_act[keep]) * 1e-12) for y in years}
    cell_tests, ratios = {}, {}
    for q in CELL_QUANTITIES:
        Y = np.stack([years[y].cell[q] for y in window])
        if q == 'december_swe':
            Y = Y[:, keep]
        cell_tests[q], ratios[q] = cell_test(Y)
    deciding = {'reservoir_storage', 'irrigation_withdrawal'} & set(quantities)
    global_tests = {k: {**trend_test([series[k][y] for y in window]), 'decides': k in deciding} for k in series}
    return series, cell_tests, global_tests, perennial, ratios


def year_files(rd, man):
    """{year: monthly output file}: in the run directory, or in the chunk of each year."""
    chunks = man.get('chunks') or [{'dir': '.', 'start_year': int(man['period']['start'][:4]),
                                    'end_year': int(man['period']['end'][:4])}]
    return {y: os.path.normpath(f'{rd}/{c["dir"]}/output/monthly.{y}-01.nc')
            for c in chunks for y in range(c['start_year'], c['end_year'] + 1)}


def figures(figs, series, tests, window, basins):
    years = sorted(next(iter(series.values())))
    glob_keys = [k for k in tests if '_basin' not in k]
    for name, keys, ncol in (('global', glob_keys, 3),
                             ('basins', [k for k in tests if '_basin' in k], 5)):
        if not keys:
            continue
        nrow = int(np.ceil(len(keys) / ncol))
        fig, axs = plt.subplots(nrow, ncol, figsize=(4 * ncol, 2.6 * nrow), squeeze=False)
        for ax, k in zip(axs.flat, keys):
            y = [series[k][yy] for yy in years]
            ax.plot(years, y, '.-', color='0.5', lw=0.8)
            tv = [series[k][yy] for yy in window]
            ax.plot(window, tv, '.', color='k')
            r = tests[k]
            if r['slope_per_year'] is not None:
                t = np.arange(len(window))
                a0 = np.mean(tv) - r['slope_per_year'] * t.mean()
                ax.plot(window, a0 + r['slope_per_year'] * t, color='tab:green' if r['passed'] else 'tab:red')
            title = k.replace('soil_moisture_', 'SM ').replace('_basin', ' basin ') + \
                (' [mm]' if k.startswith('soil_moisture') else ' [km3]')
            if '_basin' in k:
                b = basins[int(k[-2:]) - 1]
                title += f' ({b["outlet_lat"]:.1f}, {b["outlet_lon"]:.1f})'
            if r['ratio'] is not None:
                title += f'\n|b|/s = {r["ratio"]:.3g}' + ('' if r.get('decides') else ' (diagnostic)')
            ax.set_title(title, fontsize=8)
            ax.tick_params(labelsize=7)
        for ax in list(axs.flat)[len(keys):]:
            ax.set_visible(False)
        fig.suptitle(f'spin-up convergence: window {window[0]}-{window[-1]}, series pass when |trend per year| <= '
                     f'{TREND_LIMIT} x detrended SD (green passed, red failed); global totals decide only for '
                     'reservoir storage and irrigation withdrawal', fontsize=9)
        fig.tight_layout()
        fig.savefig(f'{figs}/convergence_{name}.png', dpi=110); plt.close(fig)


def ratio_map(path, ratio, mask, lat, lon, quantity, rec):
    """Map of the per-cell slope ratio |b|/s of one quantity (cells above TREND_LIMIT in red shades)."""
    grid = np.full(mask.shape, np.nan, 'f4'); grid[mask] = ratio
    fig, ax = plt.subplots(figsize=(13, 6))
    cmap = colors.ListedColormap(['#1a9850', '#a6d96a', '#fee08b', '#f46d43', '#a50026'])
    norm = colors.BoundaryNorm([0, 0.05, TREND_LIMIT, 0.2, 0.5, 10], cmap.N)
    im = ax.imshow(np.minimum(grid, 9.9), origin='upper' if lat[0] > lat[-1] else 'lower', cmap=cmap, norm=norm,
                   extent=[lon.min(), lon.max(), min(lat), max(lat)], aspect='auto', interpolation='nearest')
    fig.colorbar(im, ax=ax, label=f'|slope| / detrended SD per year (limit {TREND_LIMIT})', shrink=0.8)
    ax.set_title(f'{quantity}: {rec["passed_cells"]} of {rec["cells"]} cells pass '
                 f'({(rec["fraction_passed"] or 0):.1%}, threshold {rec["threshold"]:.0%}); '
                 f'{rec["constant_cells"]} constant cells', fontsize=10)
    fig.savefig(path, dpi=110, bbox_inches='tight'); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    a = ap.parse_args(); W = workdir(); rd = os.path.abspath(a.run_dir)
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    first = (man.get('chunks') or [{'dir': '.'}])[0]['dir']
    with open(f'{rd}/{first}/config/resolved.yaml') as fh:
        res = yaml.safe_load(fh)
    params, plugins, seg = res['parameters'], res['campaign']['plugins'], res['segment']
    commit, dirty = gitstate.state(REPO)
    # results of code that is not committed never stand as the test of a block: they go to scratch (rule 14)
    qc = f'{W}/{UNCOMMITTED}/qc/{man["run_dir"]}' if dirty else f'{W}/qc/{man["run_dir"]}'
    figs = f'{qc}/figures'
    os.makedirs(figs, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)
    with nc.Dataset(f'{W}/{params["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool); area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
        lat = np.asarray(d['lat'][:]); lon = np.asarray(d['lon'][:])
    label, basins = largest_basins(f'{W}/{params["routing"]["path"]}', mask, area, lat, lon)
    quantities = set(CELL_QUANTITIES) | \
        ({'reservoir_storage'} if plugins['dams']['enabled'] else set()) | \
        ({'irrigation_withdrawal'} if seg['soc'].startswith('2021soc') and plugins['irrigation']['enabled'] else set())
    files = year_files(rd, man)
    window = sorted(files)[-WINDOW_YEARS:]
    years, problems = {}, []
    for y, p in sorted(files.items()):
        if not os.path.isfile(p):
            problems.append(f'{os.path.relpath(p, rd)} missing'); continue
        years[y] = Year(p, mask, area, label, len(basins), quantities, keep_cells=y in window)
        problems += years[y].problems
        print(f'{y}: ' + ', '.join(f'{k} {v:.4g}' for k, v in years[y].values.items() if '_basin' not in k), flush=True)
    if len(files) < WINDOW_YEARS:
        problems.append(f'the block has {len(files)} years, the test needs {WINDOW_YEARS}')
    series, cell_tests, global_tests, ratios = {}, {}, {}, {}
    perennial = np.zeros(int(mask.sum()), bool)
    if not problems:
        series, cell_tests, global_tests, perennial, ratios = evaluate(years, window, quantities, area[mask])
    deciding = {**cell_tests, **{k: r for k, r in global_tests.items() if r['decides']}}
    failed = sorted(k for k, r in deciding.items() if not r['passed'])
    status = block_status(deciding, problems)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    rule = {'decided': RULE, 'window_years': WINDOW_YEARS, 'window': [window[0], window[-1]] if window else None,
            'trend_limit': TREND_LIMIT, 'cell_fraction': CELL_FRACTION, 'detrended_sd_ddof': 2,
            'per_cell_quantities': list(CELL_QUANTITIES),
            'global_quantities': sorted(q for q in ('reservoir_storage', 'irrigation_withdrawal') if q in quantities),
            'perennial_swe_mm': PERENNIAL_SWE_MM, 'basins_diagnostic_only': BASINS}
    perennial_grid = np.zeros(mask.shape, bool); perennial_grid[mask] = perennial
    report = {'run': man['run_dir'], 'spinup_block': man.get('spinup_block'), 'checked_at': now,
              'checked_by': CHECKED_BY, 'code_commit': commit, 'code_dirty': dirty, 'rule': rule,
              'years': sorted(years), 'window': window, 'quantities': sorted(quantities),
              'perennial_snow_cells': int(perennial.sum()),
              'perennial_snow_area_km2': float((area * perennial_grid).sum() / 1e6), 'basins': basins,
              'problems': problems, 'cell_tests': cell_tests, 'global_tests': global_tests, 'failed': failed,
              'status': status, 'annual_values': {k: {str(y): v for y, v in s.items()} for k, s in series.items()}}
    qc_status.write_json(f'{qc}/reports/convergence.json', json.loads(json.dumps(report, default=float)))
    if series:
        keys = sorted(series)
        with open(f'{qc}/reports/convergence_annual.csv', 'w', newline='') as fh:
            wr = csv.writer(fh); wr.writerow(['year'] + keys)
            for y in sorted(years):
                wr.writerow([y] + [series[k][y] for k in keys])
        figures(figs, series, global_tests, window, basins)
        ratio_map(f'{figs}/convergence_map_soil_moisture_layer3.png', ratios['soil_moisture_layer3'], mask, lat, lon,
                  'soil_moisture_layer3', cell_tests['soil_moisture_layer3'])
    qc_status.write_summary(qc, {
        'object': man['run_dir'], 'status': status, 'checked_at': now, 'checked_by': CHECKED_BY,
        'code_commit': commit, 'code_dirty': dirty, 'spinup_block': man.get('spinup_block'), 'rule': rule,
        'window': [window[0], window[-1]] if window else None,
        'fraction_passed': {k: r['fraction_passed'] for k, r in cell_tests.items()},
        'global_ratio': {k: r['ratio'] for k, r in global_tests.items() if r['decides']},
        'failed': failed, 'problems': problems,
        'note': 'D19 convergence test of a spin-up block (amendment 2026-11-02); failed means: not converged, '
                'continue with the next block (render_run.py); not_checked means: the test could not be evaluated '
                '(see problems), the chain is not continued until the block has been looked at'})
    for k, r in cell_tests.items():
        print(f'{k}: {r["passed_cells"]} of {r["cells"]} cells pass ({(r["fraction_passed"] or 0):.1%}, threshold '
              f'{r["threshold"]:.0%}, {r["constant_cells"]} constant) -> {"passed" if r["passed"] else "failed"}')
    for k, r in global_tests.items():
        if '_basin' not in k and r['slope_per_year'] is not None:
            print(f'{k} (global{"" if r["decides"] else ", diagnostic"}): slope {r["slope_per_year"]:.4g}/yr, '
                  f'detrended sd {r["detrended_sd"]:.4g}, ratio {r["ratio"]:.3g} -> '
                  f'{"passed" if r["passed"] else "failed"}')
    if problems:
        print('problems:', *problems, sep='\n  ')
    print('status', status, '->', qc)
    sys.exit(exit_status(status))


if __name__ == '__main__':
    main()
