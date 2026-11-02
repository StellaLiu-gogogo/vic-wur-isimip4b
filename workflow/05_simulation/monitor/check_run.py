#!/usr/bin/env python3
"""Checks, derived water-use file and figures of a completed VIC-WUR run.

Reads the run's output (daily and monthly streams of the campaign output selection, one file per year), the
domain and routing files of the parameter set, the water-use forcing files the run read (through its forcing
view) and the GRDC daily export (raw/external/grdc/export-2024-11, see grdc.py). Writes to
qc/runs/<campaign-id>/<run-id>/: summary.json, reports/check.json, reports/grdc_stations.csv,
reports/water_use_by_sector_<year>.nc (run_figures.py) and figures/*.png.

Checks per calendar year (the plugins of the run are read from its config/resolved.yaml; a run without the water-use
plugin, e.g. a natural run, has no water-use output and gets no water-use checks)
  coverage        active cells (domain mask) without a finite qtot or discharge value
  qtot            annual qtot = sum of daily OUT_RUNOFF + OUT_BASEFLOW (mm/yr), map and global volume (km3/yr)
  water_balance   OUT_WATER_ERROR (monthly mean per cell, VIC's default aggregation): largest absolute value and the
                  number of cell-months above WATER_ERROR_LIMIT_MM; global P, ET, qtot, and the closure
                  P - ET - qtot - dS with dS the change of the December monthly-mean storage (soil, snow, canopy,
                  surface) from the previous year of the check (approximate: monthly means, no river or reservoir
                  storage; None for the first year)
  outlets         mean discharge at the river outlets (routing downstream equal to the cell's own downstream_id)
  irrigation      irrigation withdrawal (sector 4), requirement, received water (water-use and irrigation plugins on)
  sectors         municipal (0) and manufacturing (2): forcing demand (mm/day x days), VIC demand, withdrawal
                  (water-use plugin on, as the budget, the non-renewable deficit and the derived per-sector file)
  budget          per cell and month: withdrawn <= demand, consumed <= withdrawn,
                  GW + SURF + DAM + TREM + NREN (all sectors) = OUT_WITHDRAWN (the GWM FALSE definition in
                  plugins/wateruse/src/wu_output.c), and the variant GW + SURF + REM + DAM (informative);
                  tolerance 1e-4 mm plus 1e-5 relative (float32 output); every monthly water-use variable it
                  reads must have a value on every active cell and month (any sector): a missing value fails it
  nonrenewable    with OUT_NONREN_DEFICIT in the monthly output (NONRENEWABLE_WITHDRAWAL): the deficit at the end of
                  each month (km3), water taken as non-renewable and not yet repaid from the baseflow; OUT_BASEFLOW
                  (and so qtot) still contains the repaid water (plugins/routing/src/rout_run.c)
  state           the end-state file exists
Water balance of the check (chunk or unchunked run; review 2026-11-01 R8, user's rule of 2026-11-02): over every
  active cell and month of its years, the 99th percentile of |OUT_WATER_ERROR| must not exceed WATER_ERROR_LIMIT_MM
  (1 mm, the task T rule): status passed or failed, part of the check status; p99, p99.9, the largest value and the
  number of cell-months above the limit are recorded (percentiles from a histogram of WATER_ERROR_BIN_MM resolution).
Binding (review 2026-11-01 R5): summary.json and reports/check.json name the attempt (number, Slurm job id, status)
  and the sha256 of the end state they checked, the code commit and whether the repository was clean; from a
  repository that is not clean the results go to scratch/run-check/uncommitted/qc/runs/... and do not count. The
  whole-run check of a chunked run counts a chunk summary only when it is bound to the chunk's completed attempt.
  The check job also stores the final sacct rows of the run job in the attempt (`scheduler`, R16).
GRDC comparison (whole run)
  The run is driven by GCM climate, so its days and months do not correspond to observed weather: the main
  comparison is climatological, the simulated monthly-mean seasonal cycle of the run years (the first year
  excluded when a cold-started run has at least 3 years) against the GRDC monthly
  climatology of the years first-10 .. last+10 (months with >= 20 valid days, >= 5 years per calendar month).
  Daily series of the same dates are drawn for visual reference only.

Chunked runs (chunks/<start>-<end>/)
  --chunk ID      the checks per calendar year of one chunk (its output) and its end state, no GRDC comparison;
                  results in qc/runs/<campaign-id>/<run-id>/chunks/<id>/
  no --chunk      the whole run: the GRDC comparison over all years (output of every chunk), the run's end state,
                  and the status of every chunk check (each must have passed); per-year results stay in the chunk
                  reports

Usage: check_run.py --run-dir DIR [--chunk ID] [--min-area 10000] [--panels 24]
"""
import argparse, datetime, glob, json, os, sys

import numpy as np
import pandas as pd
import netCDF4 as nc
import yaml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'submit'))
import grdc          # noqa: E402
import run_figures   # noqa: E402
import run_manifest as rm   # noqa: E402  (attempts, end-state checksum, final scheduler rows under the run lock)
from common import gitstate, qc as qc_status   # noqa: E402  (exit status of a check)

CHECKED_BY = 'workflow/05_simulation/monitor/check_run.py'
SECTORS = {'municipal': 0, 'energy': 1, 'manufacturing': 2, 'livestock': 3, 'irrigation': 4}
WI = ('OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_DAM_SECT', 'OUT_WI_TREM_SECT', 'OUT_WI_NREN_SECT')
ABS_TOL, REL_TOL = 1e-4, 1e-5
WATER_ERROR_LIMIT_MM = 1.0        # task T rule (2026-10-30): |monthly mean OUT_WATER_ERROR| above it is an outlier
WATER_ERROR_BIN_MM = 1e-4         # histogram resolution of the percentiles
WATER_ERROR_TOP_MM = 10.0         # values above it share the last bin (the maximum is exact)
UNCOMMITTED = 'scratch/run-check/uncommitted'
read = run_figures.read
km3 = run_figures.km3
draw = run_figures.draw_map


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


class WaterError:
    """|OUT_WATER_ERROR| over every active cell and month of the check: a histogram of WATER_ERROR_BIN_MM bins up to
    WATER_ERROR_TOP_MM (the last bin holds everything above), the exact maximum and the count above the limit."""

    def __init__(self, limit=WATER_ERROR_LIMIT_MM):
        self.nbin = int(round(WATER_ERROR_TOP_MM / WATER_ERROR_BIN_MM))
        self.counts = np.zeros(self.nbin + 1, 'i8')
        self.limit = limit; self.max = 0.0; self.above = 0; self.n = 0; self.missing = 0

    def add(self, values):
        """Add the |values| of one month (active cells); returns (largest value, count above the limit)."""
        v = np.abs(np.asarray(values, 'f8')); ok = np.isfinite(v); v = v[ok]
        self.missing += int((~ok).sum()); self.n += int(v.size)
        if not v.size:
            return 0.0, 0
        idx = np.minimum((v / WATER_ERROR_BIN_MM).astype('i8'), self.nbin)
        self.counts += np.bincount(idx, minlength=self.nbin + 1)
        vmax = float(v.max()); above = int((v > self.limit).sum())
        self.max = max(self.max, vmax); self.above += above
        return vmax, above

    def percentile(self, q):
        """Upper edge (mm) of the bin in which the cumulative share reaches q (0-100); None without values."""
        if not self.n:
            return None
        rank = int(np.ceil(round(q / 100.0 * self.n, 6)))           # the rank-th smallest value (1-based)
        k = int(np.searchsorted(np.cumsum(self.counts), rank, side='left'))
        return float('inf') if k >= self.nbin else (k + 1) * WATER_ERROR_BIN_MM

    def summary(self):
        p99 = self.percentile(99)
        return {'cell_months': self.n, 'cell_months_missing': self.missing, 'limit_mm': self.limit,
                'p99_abs_monthly_mean_water_error_mm': p99, 'p99.9_abs_monthly_mean_water_error_mm': self.percentile(99.9),
                'max_abs_monthly_mean_water_error_mm': self.max, 'cell_months_above_limit': self.above,
                'percentile_resolution_mm': WATER_ERROR_BIN_MM,
                'status': 'passed' if p99 is not None and p99 <= self.limit else 'failed',
                'rule': 'p99 of |OUT_WATER_ERROR| (monthly mean per cell) over all active cells and months of the check '
                        '<= limit (user, 2026-11-02; task T outlier rule)'}


# ------------------------------------------------------------------------------------------------ per year
def check_year(year, rd, mask, area, lat, lon, own, figs, forcing_view, station_cells, provenance, qc, plugins,
               werr=None):
    """`plugins`: {plugin: on} of the run. The water-use checks need the water-use plugin and the irrigation
    results also the irrigation plugin; a natural run has neither, and VIC writes none of their outputs. `werr`
    accumulates |OUT_WATER_ERROR| over the years of the check (WaterError)."""
    out = {}; figs_made = []
    daily = nc.Dataset(f'{rd}/output/daily.{year}-01-01.nc'); monthly = nc.Dataset(f'{rd}/output/monthly.{year}-01.nc')
    nd = len(daily.dimensions['time']); nm = len(monthly.dimensions['time'])
    # ---- daily qtot and discharge, one day at a time; discharge at the GRDC station cells
    qtot = np.zeros(mask.shape); qnan = np.zeros(mask.shape, bool); dis_sum = np.zeros(mask.shape)
    rows, cols = station_cells
    st_daily = np.full((nd, len(rows)), np.nan)
    for t in range(nd):
        ro = read(daily, 'OUT_RUNOFF', t); bf = read(daily, 'OUT_BASEFLOW', t); q = read(daily, 'OUT_DISCHARGE', t)
        qtot += np.nan_to_num(ro) + np.nan_to_num(bf); qnan |= ~np.isfinite(ro) | ~np.isfinite(bf) | ~np.isfinite(q)
        dis_sum += np.nan_to_num(q); st_daily[t] = q[rows, cols]
    dis_mean = dis_sum / nd
    out['days'] = nd
    out['coverage'] = {'active_cells': int(mask.sum()), 'active_cells_with_missing_values': int((qnan & mask).sum()),
                       'status': 'passed' if not (qnan & mask).any() else 'failed'}
    out['qtot'] = {'global_km3_per_year': km3(qtot, area),
                   'mean_mm_per_year_over_active_cells': float(np.average(qtot[mask], weights=area[mask])),
                   'max_mm_per_year': float(qtot[mask].max()), 'min_mm_per_year': float(qtot[mask].min())}
    draw(f'{figs}/qtot_annual_{year}.png', np.maximum(qtot, 1e-1), mask, f'qtot {year} (OUT_RUNOFF + OUT_BASEFLOW)',
         'mm/yr', 1, 3000, log=True)
    figs_made.append(f'qtot_annual_{year}.png')
    cand = np.where(own & mask)
    order = np.argsort(dis_mean[cand])[::-1][:12]
    out['outlets'] = [{'lat': float(lat[cand[0][k]]), 'lon': float(lon[cand[1][k]]),
                       'mean_m3_s': float(dis_mean[cand[0][k], cand[1][k]])} for k in order]

    if plugins['water_use']:
        wu, wu_figs = check_water_use(year, monthly, nd, nm, mask, area, lat, lon, figs, forcing_view, provenance, qc,
                                      plugins['irrigation'])
        out.update(wu); figs_made += wu_figs
    werr = werr if werr is not None else WaterError()
    wb_err, above = 0.0, 0
    for t in range(nm):
        vmax, n = werr.add(read(monthly, 'OUT_WATER_ERROR', t)[mask])
        wb_err = max(wb_err, vmax); above += n
    wb, f = run_figures.water_balance(year, monthly, mask, area, lat, figs)
    wb['max_abs_monthly_mean_water_error_mm'] = wb_err
    wb['cell_months_above_limit'] = above
    out['water_balance'] = wb; figs_made.append(f)
    out['figures'] = figs_made
    daily.close(); monthly.close()
    return out, st_daily


def check_water_use(year, monthly, nd, nm, mask, area, lat, lon, figs, forcing_view, provenance, qc, irrigation):
    """Water-use part of the yearly check (water-use plugin on): budget per cell and month, non-renewable deficit,
    irrigation (irrigation plugin on), withdrawal by sector and source, the derived per-sector file and the water-use
    figures. Returns (entries of the yearly result, figures made)."""
    out = {}; figs_made = []
    # ---- water-use budget per cell and month
    sect = {n: np.zeros((5,) + mask.shape) for n in WI + ('OUT_DE_GW_SECT', 'OUT_DE_SURF_SECT')}
    tot = {k: np.zeros(mask.shape) for k in ('OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_CONSUMED', 'OUT_RETURNED')}
    irr = {k: np.zeros(nm) for k in ('received', 'requirement', 'applied')}
    viol = {'withdrawn_gt_demand': 0, 'consumed_gt_withdrawn': 0, 'sum_ne_withdrawn': 0, 'sum_with_rem_ne_withdrawn': 0}
    worst = {k: 0.0 for k in viol}; missing = {}
    for t in range(nm):
        m = {k: read(monthly, k, t) for k in list(sect) + list(tot) + ['OUT_WI_REM_SECT']}
        for k, a in m.items():               # active cells without a value (in any sector): counted before use
            n = int(((~np.isfinite(a)).any(axis=0) & mask).sum() if a.ndim == 3 else (~np.isfinite(a) & mask).sum())
            if n:
                missing[k] = missing.get(k, 0) + n
        for k in sect:
            sect[k] += np.nan_to_num(m[k])
        for k in tot:
            tot[k] += np.nan_to_num(m[k])
        for k, v in (('received', 'OUT_RECEIVED'), ('requirement', 'OUT_REQUIREMENT'), ('applied', 'OUT_APPLIED')):
            if irrigation:
                irr[k][t] = km3(np.nan_to_num(read(monthly, v, t)), area)
        wd, de, co = m['OUT_WITHDRAWN'], m['OUT_DEMAND'], m['OUT_CONSUMED']
        s = sum(np.nansum(m[k], axis=0) for k in WI)
        s_rem = sum(np.nansum(m[k], axis=0) for k in ('OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_REM_SECT', 'OUT_WI_DAM_SECT'))
        for key, a, b in (('withdrawn_gt_demand', wd, de), ('consumed_gt_withdrawn', co, wd)):
            d = (a - b)[mask]; tol = ABS_TOL + REL_TOL * np.abs(b[mask])
            viol[key] += int(np.nansum(d > tol)); worst[key] = max(worst[key], float(np.nanmax(d, initial=0)))
        for key, a in (('sum_ne_withdrawn', s), ('sum_with_rem_ne_withdrawn', s_rem)):
            d = np.abs(a - wd)[mask]; tol = ABS_TOL + REL_TOL * np.abs(wd[mask])
            viol[key] += int(np.nansum(d > tol)); worst[key] = max(worst[key], float(np.nanmax(d, initial=0)))
    out['budget'] = {'cell_months_checked': int(mask.sum()) * nm, 'violations': viol, 'largest_excess_mm': worst,
                     'tolerance': f'{ABS_TOL} mm + {REL_TOL} x value',
                     'missing_values': missing,
                     'status': 'passed' if not missing and all(viol[k] == 0 for k in (
                         'withdrawn_gt_demand', 'consumed_gt_withdrawn', 'sum_ne_withdrawn')) else 'failed',
                     'note': 'sum_with_rem_ne_withdrawn is informative: under GWM FALSE OUT_WITHDRAWN counts water '
                             'taken from other cells for this cell (TREM), not water this cell gave away (REM)'}
    if 'OUT_NONREN_DEFICIT' in monthly.variables:
        deficit = [km3(np.nan_to_num(read(monthly, 'OUT_NONREN_DEFICIT', t)), area) for t in range(nm)]
        out['nonrenewable'] = {'deficit_end_of_month_km3': deficit, 'deficit_end_of_year_km3': deficit[-1],
                               'note': 'non-renewable water not yet repaid; OUT_BASEFLOW and qtot include the repaid '
                                       'part, which does not reach the river'}
    wi = sum(sect[k] for k in WI); de = sect['OUT_DE_GW_SECT'] + sect['OUT_DE_SURF_SECT']
    if irrigation:
        out['irrigation'] = {'withdrawal_km3': km3(wi[4], area), 'groundwater_km3': km3(sect['OUT_WI_GW_SECT'][4], area),
                             'received_km3': float(irr['received'].sum()), 'applied_km3': float(irr['applied'].sum()),
                             'requirement_monthly_mean_km3': float(irr['requirement'].sum()),
                             'demand_sum_km3_not_a_volume': km3(de[4], area),
                             'cells_with_withdrawal': int(((wi[4] > 0) & mask).sum())}
    out['totals'] = {k: km3(v, area) for k, v in tot.items()}
    by_source = {}
    for sec, i in SECTORS.items():
        by_source[sec] = {n.replace('OUT_WI_', '').replace('_SECT', '').lower(): km3(sect[n][i], area) for n in WI}
        by_source[sec]['withdrawal'] = km3(wi[i], area)
    out['withdrawal_by_sector_km3'] = by_source

    # ---- derived per-sector file and water-use figures
    cons = {}
    for sector in ('municipal', 'manufacturing'):
        with nc.Dataset(forcing_view[f'water_use/{sector}_consumption_fraction'][str(year)]) as f:
            cons[sector] = read(f, 'consumption_fraction', 0)
    out_nc = f'{qc}/reports/water_use_by_sector_{year}.nc'
    series, annual = run_figures.water_use(year, monthly, mask, area, lat, lon, cons, out_nc, figs, provenance)
    out['derived_file'] = os.path.relpath(out_nc, qc)
    figs_made += run_figures.water_use_figures(year, series, annual, irr, mask, figs)
    out['sectors'] = {}
    for sector in ('municipal', 'manufacturing'):
        i = SECTORS[sector]
        with nc.Dataset(forcing_view[f'water_use/{sector}_demand'][str(year)]) as f:
            fd = np.nan_to_num(read(f, 'demand', 0)) * nd                       # mm/day x days of the year
        out['sectors'][sector] = {'forcing_demand_km3': km3(fd, area), 'vic_demand_km3': km3(de[i], area),
                                  'withdrawal_km3': km3(wi[i], area),
                                  'consumption_estimate_km3': float(series[sector]['consumption_estimate'].sum()),
                                  'cells_with_demand': int(((de[i] > 0) & mask).sum())}
    return out, figs_made


# ------------------------------------------------------------------------------------------------ GRDC
def grdc_compare(W, rd, years, mask, area, lat, lon, routing_path, figs, qc, min_area, panels):
    with nc.Dataset(routing_path) as r:
        r.set_auto_mask(False)
        nxt = grdc.network(r['downstream'][:], r['downstream_id'][:], mask)
    upa = grdc.upstream_area(nxt, area / 1e6, mask)
    outl = grdc.outlets(nxt)
    y0, y1 = years[0], years[-1]
    ref = list(range(y0 - 10, min(y1 + 10, 2024) + 1))
    cat = grdc.catalogue(W)
    cat = cat[(cat['area'] >= min_area) & (cat['d_end'] >= ref[0]) & (cat['d_start'] <= ref[-1])]
    st = pd.DataFrame({'lat': cat['lat'], 'lon': cat['long'], 'area_km2': cat['area'], 'river': cat['river'],
                       'station': cat['station']})
    files = grdc.station_files(W)
    st = st[st.index.isin(list(files))]
    mapped = grdc.map_stations(st, upa, lat, lon, mask)
    mapped['outlet'] = outl[mapped['row'].values * mask.shape[1] + mapped['col'].values]
    return mapped, files, ref, upa


def climatology_years(years, cold_start):
    """Run years of the simulated climatology: without the first year of a cold-started run of 3 or more years."""
    return years[1:] if cold_start and len(years) >= 3 else years


def grdc_figures(W, ydir, years, mapped, files, ref, st_daily, mask, figs, qc, panels, cold_start=True):
    """`ydir(year)`: the directory whose output/ holds the files of that year (the run, or its chunk)."""
    # simulated monthly means at the station cells
    sim = {}
    for y in years:
        with nc.Dataset(f'{ydir(y)}/output/monthly.{y}-01.nc') as m:
            m.set_auto_mask(False)
            for t in range(len(m.dimensions['time'])):
                q = read(m, 'OUT_DISCHARGE', t)
                sim[pd.Timestamp(y, t + 1, 1)] = q[mapped['row'].values, mapped['col'].values]
    sim = pd.DataFrame(sim).T; sim.columns = mapped.index
    use_years = climatology_years(years, cold_start)
    sim_clim = np.array([[sim.loc[[pd.Timestamp(y, k + 1, 1) for y in use_years], no].mean() for k in range(12)]
                         for no in mapped.index])
    rows = []; obs = {}
    for idx, no in enumerate(mapped.index):
        _, daily = grdc.read_station(files[no])
        mon = grdc.monthly_means(daily)
        clim, lo, hi, n = grdc.climatology(mon, ref)
        obs[no] = (daily, clim, lo, hi)
        ok = np.isfinite(clim).all()
        rows.append({'grdc_no': no, 'river': mapped.at[no, 'river'], 'station': mapped.at[no, 'station'],
                     'lat': mapped.at[no, 'lat'], 'lon': mapped.at[no, 'lon'], 'area_km2': mapped.at[no, 'area_km2'],
                     'model_upstream_km2': mapped.at[no, 'upa_km2'], 'area_error': mapped.at[no, 'area_error'],
                     'row': int(mapped.at[no, 'row']), 'col': int(mapped.at[no, 'col']), 'outlet': int(mapped.at[no, 'outlet']),
                     'obs_mean_m3_s': float(np.mean(clim)) if ok else np.nan,
                     'sim_mean_m3_s': float(np.nanmean(sim_clim[idx])),
                     'ratio_sim_obs': float(np.nanmean(sim_clim[idx]) / np.mean(clim)) if ok and np.mean(clim) > 0 else np.nan,
                     'seasonal_r': float(np.corrcoef(sim_clim[idx], clim)[0, 1]) if ok and np.std(clim) > 0 else np.nan,
                     'obs_years_min': int(n.min())})
    tab = pd.DataFrame(rows).set_index('grdc_no')
    tab.to_csv(f'{qc}/reports/grdc_stations.csv')
    good = tab[np.isfinite(tab['ratio_sim_obs'])]
    made = []
    # scatter of annual means
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.5))
    ax = axs[0]
    sc = ax.scatter(good['obs_mean_m3_s'], good['sim_mean_m3_s'], c=np.log10(good['area_km2']), s=8, cmap='viridis')
    lim = [max(1, good[['obs_mean_m3_s', 'sim_mean_m3_s']].min().min() * 0.5), good[['obs_mean_m3_s', 'sim_mean_m3_s']].max().max() * 2]
    ax.plot(lim, lim, 'k-', lw=0.8); ax.plot(lim, [v * 1.25 for v in lim], 'k:', lw=0.6); ax.plot(lim, [v / 1.25 for v in lim], 'k:', lw=0.6)
    ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel(f'GRDC mean discharge {ref[0]}-{ref[-1]} (m3/s)'); ax.set_ylabel(f'simulated mean {use_years[0]}-{use_years[-1]} (m3/s)')
    fig.colorbar(sc, ax=ax, label='log10 catchment area (km2)')
    within = float(np.mean((good['ratio_sim_obs'] > 0.8) & (good['ratio_sim_obs'] < 1.25)))
    ax.set_title(f'{len(good)} stations: median sim/obs {good["ratio_sim_obs"].median():.2f}, within 0.8-1.25: {within:.0%}')
    ax = axs[1]
    sc = ax.scatter(good['lon'], good['lat'], c=good['ratio_sim_obs'], s=10, cmap='RdBu',
                    norm=colors.LogNorm(vmin=0.25, vmax=4))
    ax.set_xlim(-180, 180); ax.set_ylim(-56, 84); fig.colorbar(sc, ax=ax, label='sim / obs mean discharge')
    ax.set_title('ratio of mean discharge at the GRDC stations')
    fig.savefig(f'{figs}/grdc_mean_discharge.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    made.append('grdc_mean_discharge.png')
    # largest catchments, one station per outlet
    top = good.sort_values('area_km2', ascending=False).drop_duplicates('outlet').head(panels)
    ncol = 6; nrow = int(np.ceil(len(top) / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(22, 3.2 * nrow))
    for ax, (no, r) in zip(np.ravel(axs), top.iterrows()):
        idx = list(mapped.index).index(no); _, clim, lo, hi = obs[no]
        ax.fill_between(range(12), lo, hi, color='0.8', label='GRDC range')
        ax.plot(range(12), clim, 'k-', marker='o', ms=3, label=f'GRDC {ref[0]}-{ref[-1]}')
        ax.plot(range(12), sim_clim[idx], 'r-', marker='o', ms=3, label='VIC-WUR')
        ax.set_xticks(range(12)); ax.set_xticklabels(list(run_figures.MONTHS), fontsize=7)
        ax.set_title(f'{r.river.title()[:18]} / {r.station.title()[:16]}\nratio {r.ratio_sim_obs:.2f}, r {r.seasonal_r:.2f}', fontsize=8)
    for ax in np.ravel(axs)[len(top):]:
        ax.axis('off')
    np.ravel(axs)[0].legend(fontsize=6)
    fig.suptitle(f'monthly discharge climatology (m3/s): VIC-WUR {use_years[0]}-{use_years[-1]} (GCM climate) vs GRDC')
    fig.savefig(f'{figs}/grdc_climatology_largest.png', dpi=100, bbox_inches='tight'); plt.close(fig)
    made.append('grdc_climatology_largest.png')
    # daily series of the same dates, visual reference only
    days = pd.date_range(f'{years[0]}-01-01', f'{years[-1]}-12-31', freq='D')
    fig, axs = plt.subplots(nrow, ncol, figsize=(22, 3.2 * nrow))
    for ax, (no, r) in zip(np.ravel(axs), top.iterrows()):
        idx = list(mapped.index).index(no); daily = obs[no][0]
        ax.plot(days, st_daily[:, idx], 'r-', lw=0.6, label='VIC-WUR')
        ov = daily.reindex(days)
        ax.plot(days, ov.values, 'k-', lw=0.6, label='GRDC')
        ax.set_title(f'{r.river.title()[:18]} / {r.station.title()[:16]}', fontsize=8); ax.tick_params(labelsize=6)
    for ax in np.ravel(axs)[len(top):]:
        ax.axis('off')
    np.ravel(axs)[0].legend(fontsize=6)
    fig.suptitle('daily discharge (m3/s) on the same dates; GCM climate, so dates are not expected to match')
    fig.savefig(f'{figs}/grdc_daily_same_dates.png', dpi=100, bbox_inches='tight'); plt.close(fig)
    made.append('grdc_daily_same_dates.png')
    summary = {'stations_mapped': int(len(tab)), 'stations_with_climatology': int(len(good)),
               'reference_years': [ref[0], ref[-1]], 'simulated_years': [use_years[0], use_years[-1]],
               'median_ratio_sim_obs': float(good['ratio_sim_obs'].median()),
               'share_within_0.8_1.25': within, 'median_seasonal_r': float(good['seasonal_r'].median()),
               'largest': [{'grdc_no': int(no), 'river': r.river, 'station': r.station, 'obs_m3_s': r.obs_mean_m3_s,
                            'sim_m3_s': r.sim_mean_m3_s, 'ratio': r.ratio_sim_obs, 'seasonal_r': r.seasonal_r}
                           for no, r in top.iterrows()]}
    return summary, made


def station_daily(odir, year, cells):
    """Daily OUT_DISCHARGE of one year at the station cells (days x stations)."""
    rows, cols = cells
    with nc.Dataset(f'{odir}/output/daily.{year}-01-01.nc') as d:
        d.set_auto_mask(False)
        return np.array([read(d, 'OUT_DISCHARGE', t)[rows, cols] for t in range(len(d.dimensions['time']))])


def year_dirs(rd, man):
    """{year: directory whose output/ holds that year}: the run directory, or the chunk of each year."""
    chunks = man.get('chunks') or []
    if not chunks:
        y0, y1 = int(man['period']['start'][:4]), int(man['period']['end'][:4])
        return {y: rd for y in range(y0, y1 + 1)}
    return {y: f'{rd}/{c["dir"]}' for c in chunks for y in range(c['start_year'], c['end_year'] + 1)}


# ------------------------------------------------------------------------------------------------ binding
def plain(obj):
    """The record with every numpy number turned into a plain Python number (for qc.write_json)."""
    return json.loads(json.dumps(obj, default=float))


def latest_attempt(man, chunk=None):
    at = [x for x in man.get('attempts') or [] if x.get('chunk') == chunk]
    return at[-1] if at else {}


def bind(rd, man, chunk, state):
    """What the check looked at (review 2026-11-01 R5): the attempt that made the output (of the chunk, of the
    unchunked run, or of the last chunk of a whole chunked run, with the attempt of every chunk), its Slurm job id
    and status, and the sha256 of the end-state file."""
    chunks = man.get('chunks') or []
    last = latest_attempt(man, chunk or (chunks[-1]['id'] if chunks else None))
    out = {'attempt': last.get('attempt'), 'slurm_job_id': last.get('slurm_job_id'),
           'attempt_status': last.get('status'), 'end_state': os.path.relpath(state[0], rd) if state else None,
           'end_state_sha256': rm.file_hash(state[0], 'sha256') if state else None}
    if chunks and not chunk:
        out['chunk_attempts'] = {c['id']: latest_attempt(man, c['id']).get('attempt') for c in chunks}
    return out


def chunk_statuses(W, man):
    """Status of every chunk check of a chunked run, read from its summary; a summary not bound to the chunk's
    completed attempt (an earlier attempt, a summary written before the binding existed) counts as not_checked."""
    out = {}
    for c in man.get('chunks') or []:
        p = f'{W}/qc/{man["run_dir"]}/chunks/{c["id"]}/summary.json'
        if not os.path.exists(p):
            out[c['id']] = 'not_checked'; continue
        with open(p) as fh:
            summ = json.load(fh)
        b = summ.get('binding') or {}
        want = latest_attempt(man, c['id'])
        bound = want.get('status') == 'completed' and b.get('attempt') == want.get('attempt') and \
            b.get('slurm_job_id') == want.get('slurm_job_id') and summ.get('code_dirty') is False
        out[c['id']] = summ.get('status', 'not_checked') if bound else 'not_checked'
    return out


def record_scheduler(rd, man, chunk):
    """Store the final sacct rows of the run job(s) the check looks at in their attempts (review 2026-11-01 R16: the
    job itself can only record itself as RUNNING, kept as scheduler_at_completion). Nothing is changed when sacct is
    not available or the attempt has final rows already."""
    chunks = man.get('chunks') or []
    ids = [c['id'] for c in chunks] if (chunks and not chunk) else [chunk]
    jobs = [latest_attempt(man, c).get('slurm_job_id') for c in ids]
    try:
        rm.record_scheduler(rd, [j for j in jobs if j])
    except Exception as e:                                   # noqa: BLE001  (the check does not depend on it)
        print(f'final scheduler rows not recorded: {e!r}')


def closure(results, years):
    """Global closure P - ET - qtot - dS per year of the check (km3), dS from the December monthly-mean storage of
    the year and of the previous year of the check (approximate; None for the first year)."""
    prev = None
    for y in years:
        wb = results[y].get('water_balance') or {}
        stor = wb.get('storage_monthly_mean_km3') or []
        dec = stor[-1] if stor else None
        ds = (dec - prev) if (dec is not None and prev is not None) else None
        wb['storage_change_km3'] = ds
        wb['closure_p_minus_et_minus_qtot_minus_ds_km3'] = (wb['p_minus_et_minus_qtot_km3'] - ds) \
            if (ds is not None and 'p_minus_et_minus_qtot_km3' in wb) else None
        prev = dec


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--min-area', type=float, default=10000.0, help='smallest GRDC catchment (km2) compared')
    ap.add_argument('--panels', type=int, default=24, help='stations shown in the climatology and daily figures')
    ap.add_argument('--chunk', default=None, help='check one chunk of a chunked run')
    a = ap.parse_args(); W = workdir(); rd = os.path.abspath(a.run_dir)
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    chunks = {c['id']: c for c in man.get('chunks') or []}
    if a.chunk and a.chunk not in chunks:
        sys.exit(f'{man["run_id"]} has no chunk {a.chunk}')
    first = (man.get('chunks') or [{'dir': '.'}])[0]['dir']
    with open(f'{rd}/{first}/config/resolved.yaml') as fh:
        res = yaml.safe_load(fh)
    params = res['parameters']
    plugins = {k: v['enabled'] for k, v in res['campaign']['plugins'].items()}
    commit, dirty = gitstate.state(REPO)
    # results of code that is not committed never stand as the check of a run: they go to scratch (rule 14)
    qc = (f'{W}/{UNCOMMITTED}/qc/{man["run_dir"]}' if dirty else f'{W}/qc/{man["run_dir"]}') + \
        (f'/chunks/{a.chunk}' if a.chunk else '')
    figs = f'{qc}/figures'; os.makedirs(figs, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)
    with nc.Dataset(f'{W}/{params["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool); area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
        lat = np.asarray(d['lat'][:]); lon = np.asarray(d['lon'][:])
    with nc.Dataset(f'{W}/{params["routing"]["path"]}') as r:
        r.set_auto_mask(False)
        own = np.asarray(r['downstream'][:]) == np.asarray(r['downstream_id'][:])
    view = {k: {y: f'{W}/{v["source"]}' for y, v in m.items()} for k, m in man['forcing_view'].items()}
    ydirs = year_dirs(rd, man)
    years = sorted(ydirs) if not a.chunk else list(range(chunks[a.chunk]['start_year'], chunks[a.chunk]['end_year'] + 1))
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    whole_chunked = bool(chunks) and not a.chunk
    end_state = chunks[a.chunk]['end_state'] if a.chunk else man.get('end_state')
    state = [f'{rd}/{end_state}'] if end_state else sorted(glob.glob(f'{rd}/states/state.*.nc'))
    state = [x for x in state if os.path.isfile(x)]
    binding = bind(rd, man, a.chunk, state)
    record_scheduler(rd, man, a.chunk)
    prov = {'title': 'withdrawal per water-use sector, derived from VIC-WUR output', 'run': man['run_dir'],
            'created_by': 'workflow/05_simulation/monitor/run_figures.py (check_run.py)', 'code_commit': commit,
            'code_dirty': 'true' if dirty else 'false', 'created_at': now}      # a NetCDF attribute: no bool
    mapped, files, ref, _ = grdc_compare(W, rd, years, mask, area, lat, lon, f'{W}/{params["routing"]["path"]}',
                                         figs, qc, a.min_area, a.panels)
    cells = (mapped['row'].values.astype(int), mapped['col'].values.astype(int))
    results, st_daily, chunk_status, werr = {}, [], {}, WaterError()
    if whole_chunked:          # per-year results are in the chunk checks; their status is required here
        chunk_status = chunk_statuses(W, man)
        for y in years:
            st_daily.append(station_daily(ydirs[y], y, cells))
    else:
        for y in years:
            results[y], d = check_year(y, ydirs[y], mask, area, lat, lon, own, figs, view, cells, prov, qc, plugins,
                                       werr)
            st_daily.append(d)
        closure(results, years)
    st_daily = np.concatenate(st_daily)
    grdc_summary, grdc_figs = {}, []
    if not a.chunk:
        cold_start = not (man.get('parent') or {}).get('init_state')
        grdc_summary, grdc_figs = grdc_figures(W, lambda y: ydirs[y], years, mapped, files, ref, st_daily, mask, figs,
                                               qc, a.panels, cold_start)
    report = {'run': man['run_dir'], **({'chunk': a.chunk} if a.chunk else {}), 'checked_at': now,
              'checked_by': CHECKED_BY, 'code_commit': commit, 'code_dirty': dirty, 'binding': binding,
              'years': results, **({'water_balance': werr.summary()} if not whole_chunked else {}),
              'grdc': grdc_summary | {'figures': grdc_figs},
              **({'chunk_checks': chunk_status} if whole_chunked else {}),
              'state_files': [{'path': os.path.relpath(s, rd), 'size_bytes': os.path.getsize(s)} for s in state]}
    statuses = [v[k]['status'] for v in results.values() for k in ('coverage', 'budget') if k in v] + \
        ([report['water_balance']['status']] if not whole_chunked else []) + list(chunk_status.values())
    report['status'] = 'passed' if all(s == 'passed' for s in statuses) and state else 'failed'
    qc_status.write_json(f'{qc}/reports/check.json', plain(report))
    qc_status.write_json(f'{qc}/summary.json', plain({
        'object': man['run_dir'] + (f'/chunks/{a.chunk}' if a.chunk else ''), 'status': report['status'],
        'checked_at': now, 'checked_by': CHECKED_BY, 'code_commit': commit, 'code_dirty': dirty, 'binding': binding,
        **({'water_balance': report['water_balance']['status']} if not whole_chunked else {}),
        **({'chunk_checks': chunk_status} if whole_chunked else {}),
        'note': ('sanity checks of a production run; its acceptance is the user\'s decision'
                 if man.get('production') else 'sanity checks of a non-production run, not acceptance')}))
    print(json.dumps({y: {k: v[k] for k in ('coverage', 'qtot', 'budget', 'withdrawal_by_sector_km3') if k in v}
                      for y, v in results.items()}, indent=1, default=float))
    if not whole_chunked:
        print('water balance', json.dumps(report['water_balance'], indent=1, default=float))
    print(json.dumps({k: v for k, v in grdc_summary.items() if k != 'largest'}, indent=1, default=float))
    if chunk_status:
        print('chunk checks', json.dumps(chunk_status))
    print('status', report['status'], '->', qc)
    qc_status.exit_with(report['status'])        # the check job ends FAILED unless passed


if __name__ == '__main__':
    main()
