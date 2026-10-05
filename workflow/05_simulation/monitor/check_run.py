#!/usr/bin/env python3
"""Checks, derived water-use file and figures of a completed VIC-WUR run.

Reads the run's output (daily and monthly streams of the campaign output selection, one file per year), the
domain and routing files of the parameter set, the water-use forcing files the run read (through its forcing
view) and the GRDC daily export (raw/external/grdc/export-2024-11, see grdc.py). Writes to
qc/runs/<campaign-id>/<run-id>/: summary.json, reports/check.json, reports/grdc_stations.csv,
reports/water_use_by_sector_<year>.nc (run_figures.py) and figures/*.png.

Checks per calendar year
  coverage        active cells (domain mask) without a finite qtot or discharge value
  qtot            annual qtot = sum of daily OUT_RUNOFF + OUT_BASEFLOW (mm/yr), map and global volume (km3/yr)
  water_balance   OUT_WATER_ERROR (monthly sum per cell): largest absolute value; global P, ET, qtot
  outlets         mean discharge at the river outlets (routing downstream equal to the cell's own downstream_id)
  irrigation      irrigation withdrawal (sector 4), requirement, received water
  sectors         municipal (0) and manufacturing (2): forcing demand (mm/day x days), VIC demand, withdrawal
  budget          per cell and month: withdrawn <= demand, consumed <= withdrawn,
                  GW + SURF + DAM + TREM + NREN (all sectors) = OUT_WITHDRAWN (the GWM FALSE definition in
                  plugins/wateruse/src/wu_output.c), and the variant GW + SURF + REM + DAM (informative);
                  tolerance 1e-4 mm plus 1e-5 relative (float32 output)
  state           the end-state file exists
GRDC comparison (whole run)
  The run is driven by GCM climate, so its days and months do not correspond to observed weather: the main
  comparison is climatological, the simulated monthly-mean seasonal cycle of the run years (the first year
  excluded when the run has at least 3 years, because of the cold start) against the GRDC monthly
  climatology of the years first-10 .. last+10 (months with >= 20 valid days, >= 5 years per calendar month).
  Daily series of the same dates are drawn for visual reference only.

Usage: check_run.py --run-dir DIR [--min-area 10000] [--panels 24]
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
sys.path.insert(0, HERE)
import grdc          # noqa: E402
import run_figures   # noqa: E402

SECTORS = {'municipal': 0, 'energy': 1, 'manufacturing': 2, 'livestock': 3, 'irrigation': 4}
WI = ('OUT_WI_GW_SECT', 'OUT_WI_SURF_SECT', 'OUT_WI_DAM_SECT', 'OUT_WI_TREM_SECT', 'OUT_WI_NREN_SECT')
ABS_TOL, REL_TOL = 1e-4, 1e-5
read = run_figures.read
km3 = run_figures.km3
draw = run_figures.draw_map


def workdir():
    return os.environ.get('ISIMIP4B_WORKDIR') or sys.exit('set ISIMIP4B_WORKDIR')


# ------------------------------------------------------------------------------------------------ per year
def check_year(year, rd, mask, area, lat, lon, own, figs, forcing_view, station_cells, provenance, qc):
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

    # ---- water-use budget per cell and month
    sect = {n: np.zeros((5,) + mask.shape) for n in WI + ('OUT_DE_GW_SECT', 'OUT_DE_SURF_SECT')}
    tot = {k: np.zeros(mask.shape) for k in ('OUT_WITHDRAWN', 'OUT_DEMAND', 'OUT_CONSUMED', 'OUT_RETURNED')}
    irr = {k: np.zeros(nm) for k in ('received', 'requirement', 'applied')}
    viol = {'withdrawn_gt_demand': 0, 'consumed_gt_withdrawn': 0, 'sum_ne_withdrawn': 0, 'sum_with_rem_ne_withdrawn': 0}
    worst = {k: 0.0 for k in viol}; wb_err = 0.0
    for t in range(nm):
        m = {k: read(monthly, k, t) for k in list(sect) + list(tot) + ['OUT_WI_REM_SECT']}
        for k in sect:
            sect[k] += np.nan_to_num(m[k])
        for k in tot:
            tot[k] += np.nan_to_num(m[k])
        for k, v in (('received', 'OUT_RECEIVED'), ('requirement', 'OUT_REQUIREMENT'), ('applied', 'OUT_APPLIED')):
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
        wb_err = max(wb_err, float(np.nanmax(np.abs(read(monthly, 'OUT_WATER_ERROR', t))[mask], initial=0)))
    out['budget'] = {'cell_months_checked': int(mask.sum()) * nm, 'violations': viol, 'largest_excess_mm': worst,
                     'tolerance': f'{ABS_TOL} mm + {REL_TOL} x value',
                     'status': 'passed' if all(viol[k] == 0 for k in ('withdrawn_gt_demand', 'consumed_gt_withdrawn',
                                                                      'sum_ne_withdrawn')) else 'failed',
                     'note': 'sum_with_rem_ne_withdrawn is informative: under GWM FALSE OUT_WITHDRAWN counts water '
                             'taken from other cells for this cell (TREM), not water this cell gave away (REM)'}
    wi = sum(sect[k] for k in WI); de = sect['OUT_DE_GW_SECT'] + sect['OUT_DE_SURF_SECT']
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
    wb, f = run_figures.water_balance(year, monthly, mask, area, lat, figs)
    wb['max_abs_monthly_water_error_mm'] = wb_err
    out['water_balance'] = wb; figs_made.append(f)
    out['figures'] = figs_made
    daily.close(); monthly.close()
    return out, st_daily


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


def grdc_figures(W, rd, years, mapped, files, ref, st_daily, mask, figs, qc, panels):
    # simulated monthly means at the station cells
    sim = {}
    for y in years:
        with nc.Dataset(f'{rd}/output/monthly.{y}-01.nc') as m:
            m.set_auto_mask(False)
            for t in range(len(m.dimensions['time'])):
                q = read(m, 'OUT_DISCHARGE', t)
                sim[pd.Timestamp(y, t + 1, 1)] = q[mapped['row'].values, mapped['col'].values]
    sim = pd.DataFrame(sim).T; sim.columns = mapped.index
    use_years = years[1:] if len(years) >= 3 else years
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


# ------------------------------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--min-area', type=float, default=10000.0, help='smallest GRDC catchment (km2) compared')
    ap.add_argument('--panels', type=int, default=24, help='stations shown in the climatology and daily figures')
    a = ap.parse_args(); W = workdir(); rd = os.path.abspath(a.run_dir)
    with open(f'{rd}/run_manifest.json') as fh:
        man = json.load(fh)
    with open(f'{rd}/config/resolved.yaml') as fh:
        res = yaml.safe_load(fh)
    params = res['parameters']
    qc = f'{W}/qc/{man["run_dir"]}'
    figs = f'{qc}/figures'; os.makedirs(figs, exist_ok=True); os.makedirs(f'{qc}/reports', exist_ok=True)
    with nc.Dataset(f'{W}/{params["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool); area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
        lat = np.asarray(d['lat'][:]); lon = np.asarray(d['lon'][:])
    with nc.Dataset(f'{W}/{params["routing"]["path"]}') as r:
        r.set_auto_mask(False)
        own = np.asarray(r['downstream'][:]) == np.asarray(r['downstream_id'][:])
    view = {k: {y: f'{W}/{v["source"]}' for y, v in m.items()} for k, m in man['forcing_view'].items()}
    years = list(range(int(man['period']['start'][:4]), int(man['period']['end'][:4]) + 1))
    commit = os.popen(f'git -C {os.path.dirname(os.path.dirname(os.path.dirname(HERE)))} rev-parse HEAD').read().strip()
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prov = {'title': 'withdrawal per water-use sector, derived from VIC-WUR output', 'run': man['run_dir'],
            'created_by': 'workflow/05_simulation/monitor/run_figures.py (check_run.py)', 'code_commit': commit,
            'created_at': now}
    mapped, files, ref, _ = grdc_compare(W, rd, years, mask, area, lat, lon, f'{W}/{params["routing"]["path"]}',
                                         figs, qc, a.min_area, a.panels)
    cells = (mapped['row'].values.astype(int), mapped['col'].values.astype(int))
    results, st_daily = {}, []
    for y in years:
        results[y], d = check_year(y, rd, mask, area, lat, lon, own, figs, view, cells, prov, qc)
        st_daily.append(d)
    st_daily = np.concatenate(st_daily)
    grdc_summary, grdc_figs = grdc_figures(W, rd, years, mapped, files, ref, st_daily, mask, figs, qc, a.panels)
    state = sorted(glob.glob(f'{rd}/states/state.*.nc'))
    report = {'run': man['run_dir'], 'checked_at': now, 'checked_by': 'workflow/05_simulation/monitor/check_run.py',
              'code_commit': commit, 'years': results, 'grdc': grdc_summary | {'figures': grdc_figs},
              'state_files': [{'path': os.path.relpath(s, rd), 'size_bytes': os.path.getsize(s)} for s in state]}
    statuses = [v[k]['status'] for v in results.values() for k in ('coverage', 'budget')]
    report['status'] = 'passed' if all(s == 'passed' for s in statuses) and state else 'failed'
    with open(f'{qc}/reports/check.json', 'w') as fh:
        json.dump(report, fh, indent=1, default=float)
    with open(f'{qc}/summary.json', 'w') as fh:
        json.dump({'object': man['run_dir'], 'status': report['status'], 'checked_at': now,
                   'checked_by': report['checked_by'], 'note': 'sanity checks of a smoke run, not acceptance of a '
                   'production run'}, fh, indent=1)
    print(json.dumps({y: {k: v[k] for k in ('coverage', 'qtot', 'budget', 'withdrawal_by_sector_km3')}
                      for y, v in results.items()}, indent=1, default=float))
    print(json.dumps({k: v for k, v in grdc_summary.items() if k != 'largest'}, indent=1, default=float))
    print('status', report['status'])


if __name__ == '__main__':
    main()
