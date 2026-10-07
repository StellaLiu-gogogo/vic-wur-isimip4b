#!/usr/bin/env python3
"""Snow that builds up every year: the 10-year smoke run (ISIMIP EC-Earth3-ESM-1-1 forcing, VIC 39e21ff5) against the
41-year natural production run of the sibling project (WFDE5 forcing, VIC e083c9f3, GWM FALSE, same 5' grid), which
stands in for the H line, whose monthly output exists only on Snellius scratch.

Both runs are only read. Steps:
  grid      the latitudes and longitudes of both outputs and of the domain must be identical (same order)
  smoke     cells whose December OUT_SWE rose in every year 2012-2020 (the mask of spinup_drift.py, recomputed with
            OUT_SWE alone because the natural file has no OUT_SNOW_CANOPY)
  natural   on the smoke cells: December SWE total (km3), growth (km3/yr) and largest SWE per year 1979-2019; the
            natural run's own cells whose December SWE rose in every year (a) of 1979-2019 and (b) of 2011-2019 (the
            same 8 steps as the smoke mask)
  climate   on the smoke cells: annual mean air temperature and annual precipitation that VIC read (OUT_AIR_TEMP,
            OUT_PREC; smoke 2011-2020, natural 2010-2019 and 1979-2019), and the temperature difference against the
            difference between the 5' cell elevation and the mean elevation of its 0.5 degree parent cell (a lapse-rate
            correction in one forcing and not in the other shows as a slope near -6.5 K/km)
Writes tables/snow_compare_*.csv and figures/snow_compare.png under workdir/analysis/compute-storage-plan/.

Usage: snow_compare.py
"""
import csv, glob, os, sys

import netCDF4
import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csp   # noqa: E402

# sibling project's delivery (read only), two levels above the workdir of this project
NATURAL = ('../../deliverables/vic_natural_production_41yr_20260907/'
           'vic_natural_gwmFALSE_monthly_1979-2019_5arcmin_v1.nc')
EPS = 1e-6     # mm: smallest change counted as a rise


def field(v, t):
    a = np.ma.filled(np.ma.masked_invalid(v[t]).astype('f8'), np.nan)
    a[np.abs(a) > 1e30] = np.nan
    return a


def rising_every_year(dec, mask):
    d = np.diff(dec, axis=0)
    return mask & np.all(d > EPS, axis=0)


def box_of(lat, lon):
    la, lo = np.meshgrid(np.floor(lat / 10) * 10, np.floor(lon / 10) * 10, indexing='ij')
    return la.astype(int), lo.astype(int)


def write(name, rows):
    with open(f'{csp.tables()}/{name}', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f'wrote {name} ({len(rows)} rows)', flush=True)


def main():
    W = csp.workdir()
    rd = f'{W}/{csp.SMOKE_RUNS["smoke2011-2020"]}'
    res = yaml.safe_load(open(f'{rd}/config/resolved.yaml'))
    with netCDF4.Dataset(f'{W}/{res["parameters"]["domain"]["path"]}') as d:
        mask = np.asarray(d['mask'][:]).astype(bool)
        area = np.where(mask, np.asarray(d['area'][:], 'f8'), 0.0)
        lat = np.asarray(d['lat'][:], 'f8'); lon = np.asarray(d['lon'][:], 'f8')
    with netCDF4.Dataset(f'{W}/{res["parameters"]["parameters"]["path"]}') as p:
        elev = np.asarray(p['elev'][:], 'f8')
    files = sorted(glob.glob(f'{rd}/output/monthly.*-01.nc'))
    syears = [int(os.path.basename(f)[8:12]) for f in files]

    # ---- grid
    natural = os.path.normpath(os.path.join(W, NATURAL))
    nat = netCDF4.Dataset(natural)
    print(f'natural run: {natural}', flush=True)
    nlat, nlon = np.asarray(nat['lat'][:], 'f8'), np.asarray(nat['lon'][:], 'f8')
    with netCDF4.Dataset(files[0]) as s:
        slat, slon = np.asarray(s['lat'][:], 'f8'), np.asarray(s['lon'][:], 'f8')
    grid = dict(smoke_equals_domain=bool(np.array_equal(slat, lat) and np.array_equal(slon, lon)),
                natural_equals_domain=bool(np.array_equal(nlat, lat) and np.array_equal(nlon, lon)),
                lat_first=float(lat[0]), lat_last=float(lat[-1]), lon_first=float(lon[0]), lon_last=float(lon[-1]),
                natural_months=len(nat.dimensions['time']))
    print(grid, flush=True)
    if not (grid['smoke_equals_domain'] and grid['natural_equals_domain']):
        sys.exit('grids differ: stop')
    write('snow_compare_grid.csv', [grid])

    # ---- smoke: December SWE, annual temperature and precipitation
    sdec, st, sp = [], [], []
    for f in files:
        with netCDF4.Dataset(f) as s:
            sdec.append(field(s['OUT_SWE'], 11))
            st.append(np.mean([field(s['OUT_AIR_TEMP'], t) for t in range(12)], axis=0))
            sp.append(np.sum([field(s['OUT_PREC'], t) for t in range(12)], axis=0))
    sdec = np.stack(sdec)
    smask = rising_every_year(np.nan_to_num(sdec[1:]), mask)     # 2012-2020, as spinup_drift.py
    print(f'smoke mask: {smask.sum()} cells', flush=True)

    # ---- natural: December SWE every year; temperature and precipitation for 2010-2019 and 1979-2019
    nyears = list(range(1979, 2020))
    ndec = np.stack([field(nat['OUT_SWE'], 12 * k + 11) for k in range(len(nyears))])
    nt_all = np.zeros_like(area); np_all = np.zeros_like(area); nt_dec = np.zeros_like(area); np_dec = np.zeros_like(area)
    for k, y in enumerate(nyears):
        t = np.mean([field(nat['OUT_AIR_TEMP'], 12 * k + m) for m in range(12)], axis=0)
        p = np.sum([field(nat['OUT_PREC'], 12 * k + m) for m in range(12)], axis=0)
        nt_all += t / len(nyears); np_all += p / len(nyears)
        if y >= 2010:
            nt_dec += t / 10; np_dec += p / 10
        print(f'natural {y} read', flush=True)
    nat.close()
    nmask41 = rising_every_year(np.nan_to_num(ndec), mask)
    nmask10 = rising_every_year(np.nan_to_num(ndec[-9:]), mask)   # 2011-2019: 8 steps, as the smoke mask

    km3 = lambda a, m: float(np.nansum(np.where(m, a, 0.0) * area)) * 1e-12   # noqa: E731
    la, lo = box_of(lat, lon)

    def series(dec, years, m, run, label):
        out = []
        for i, y in enumerate(years):
            out.append(dict(run=run, cells=label, year=y, december_swe_km3=round(km3(dec[i], m), 3),
                            max_swe_mm=round(float(np.nanmax(np.where(m, dec[i], np.nan))), 1) if m.any() else ''))
        return out

    def summary(dec, years, m, run, label):
        tot = np.array([km3(dec[i], m) for i in range(len(years))])
        slope = float(np.polyfit(years, tot, 1)[0]) if len(years) > 1 else 0.0
        return dict(run=run, cells=label, n_cells=int(m.sum()), area_km2=round(float(area[m].sum()) / 1e6),
                    first_year=years[0], last_year=years[-1], december_swe_first_km3=round(tot[0], 2),
                    december_swe_last_km3=round(tot[-1], 2), slope_km3_per_year=round(slope, 3),
                    mean_step_km3_per_year=round(float(np.mean(np.diff(tot))), 3),
                    max_swe_last_mm=round(float(np.nanmax(np.where(m, dec[-1], np.nan))), 1) if m.any() else '')

    rows_s, rows_t = [], []
    sets = [('smoke', sdec, syears, smask, 'smoke cells'),
            ('natural', ndec, nyears, smask, 'smoke cells'),
            ('natural', ndec[-9:], nyears[-9:], smask, 'smoke cells'),
            ('natural', ndec, nyears, nmask41, 'natural cells, rising 1979-2019'),
            ('natural', ndec[-9:], nyears[-9:], nmask10, 'natural cells, rising 2011-2019'),
            ('smoke', sdec, syears, nmask10, 'natural cells, rising 2011-2019')]
    for run, dec, yrs, m, label in sets:
        rows_s.append(summary(dec, yrs, m, run, label))
    write('snow_compare_summary.csv', rows_s)
    for run, dec, yrs, m, label in (sets[0], sets[1], sets[3], sets[4]):
        rows_t += series(dec, yrs, m, run, label)
    write('snow_compare_series.csv', rows_t)

    # ---- by 10-degree box (smoke cells and the natural run's own 2010-2019 cells)
    stm, spm = np.mean(st, axis=0), np.mean(sp, axis=0)
    boxes = sorted({(int(a), int(b)) for a, b in zip(la[smask | nmask10], lo[smask | nmask10])})
    rows_b, series_b = [], []
    for b in boxes:
        inb = (la == b[0]) & (lo == b[1])
        ms, mn = smask & inb, nmask10 & inb
        r = dict(lat_south=b[0], lon_west=b[1], smoke_cells=int(ms.sum()), natural_cells_2010_2019=int(mn.sum()),
                 natural_cells_1979_2019=int((nmask41 & inb).sum()))
        for tag, dec, yrs, m in (('smoke', sdec, syears, ms), ('natural_on_smoke_cells', ndec, nyears, ms),
                                 ('natural_own', ndec[-9:], nyears[-9:], mn)):
            tot = np.array([km3(dec[i], m) for i in range(len(yrs))])
            r[f'{tag}_km3_per_year'] = round(float(np.polyfit(yrs, tot, 1)[0]), 3) if m.any() else 0.0
            r[f'{tag}_max_swe_mm'] = round(float(np.nanmax(np.where(m, dec[-1], np.nan))), 1) if m.any() else ''
        if ms.any():
            w = area[ms]
            r['smoke_tair_c'] = round(float(np.average(stm[ms], weights=w)), 2)
            r['natural_tair_c_2010_2019'] = round(float(np.average(nt_dec[ms], weights=w)), 2)
            r['smoke_prec_mm'] = round(float(np.average(spm[ms], weights=w)))
            r['natural_prec_mm_2010_2019'] = round(float(np.average(np_dec[ms], weights=w)))
            r['mean_elev_m'] = round(float(np.average(elev[ms], weights=w)))
        rows_b.append(r)
        for i, y in enumerate(nyears):
            series_b.append(dict(lat_south=b[0], lon_west=b[1], run='natural', year=y,
                                 december_swe_km3_smoke_cells=round(km3(ndec[i], ms), 3)))
        for i, y in enumerate(syears):
            series_b.append(dict(lat_south=b[0], lon_west=b[1], run='smoke', year=y,
                                 december_swe_km3_smoke_cells=round(km3(sdec[i], ms), 3)))
    rows_b.sort(key=lambda r: -r['smoke_km3_per_year'])
    write('snow_compare_regions.csv', rows_b)
    write('snow_compare_region_series.csv', series_b)

    # ---- climate on the smoke cells, and the elevation test
    # mean elevation of the 0.5 degree parent (6 x 6 block of 5' cells, area-weighted over active cells)
    ny, nx = elev.shape
    eb = np.where(mask, elev, 0.0) * area
    blk = lambda a: a.reshape(ny // 6, 6, nx // 6, 6).sum(axis=(1, 3))   # noqa: E731
    parent = blk(eb) / np.where(blk(area) > 0, blk(area), np.nan)
    dz = elev - np.repeat(np.repeat(parent, 6, axis=0), 6, axis=1)
    dt = stm - nt_dec
    clim = []
    for label, m in (('smoke cells', smask), ('natural cells, rising 2011-2019', nmask10),
                     ('all active cells', mask), ('active cells above 3000 m', mask & (elev > 3000))):
        w = area[m]
        ok = m & np.isfinite(dt) & np.isfinite(dz)
        slope = float(np.polyfit(dz[ok] / 1000, dt[ok], 1)[0]) if ok.sum() > 10 else ''
        clim.append(dict(cells=label, n_cells=int(m.sum()), mean_elev_m=round(float(np.average(elev[m], weights=w))),
                         smoke_tair_c_2011_2020=round(float(np.average(stm[m], weights=w)), 2),
                         natural_tair_c_2010_2019=round(float(np.average(nt_dec[m], weights=w)), 2),
                         natural_tair_c_1979_2019=round(float(np.average(nt_all[m], weights=w)), 2),
                         smoke_prec_mm_2011_2020=round(float(np.average(spm[m], weights=w))),
                         natural_prec_mm_2010_2019=round(float(np.average(np_dec[m], weights=w))),
                         natural_prec_mm_1979_2019=round(float(np.average(np_all[m], weights=w))),
                         mean_dz_to_parent_m=round(float(np.average(dz[ok], weights=area[ok]))),
                         slope_dtair_vs_dz_k_per_km=round(slope, 2) if slope != '' else ''))
    write('snow_compare_climate.csv', clim)

    # ---- figure
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    top = rows_b[:6]
    fig, axes = plt.subplots(2, 4, figsize=(16, 7))
    for ax, r in zip(axes.flat[:6], top):
        for run, c in (('natural', '#1f78b4'), ('smoke', '#e31a1c')):
            s = [x for x in series_b if x['lat_south'] == r['lat_south'] and x['lon_west'] == r['lon_west']
                 and x['run'] == run]
            ax.plot([x['year'] for x in s], [x['december_swe_km3_smoke_cells'] for x in s], color=c,
                    label='natural (WFDE5)' if run == 'natural' else 'smoke (ISIMIP EC-Earth)')
        ax.set_title(f'{r["lat_south"]}..{r["lat_south"] + 10}°, {r["lon_west"]}..{r["lon_west"] + 10}° '
                     f'({r["smoke_cells"]} cells)', fontsize=8, loc='left')
        ax.set_ylabel('December SWE (km3)', fontsize=8)
    axes.flat[0].legend(fontsize=7)
    ax = axes.flat[6]
    ok = smask & np.isfinite(dt)
    ax.scatter(dz[ok], dt[ok], s=2, alpha=0.4, color='#e31a1c', label='smoke cells')
    ax.axhline(0, color='k', lw=0.5); ax.axvline(0, color='k', lw=0.5)
    xx = np.linspace(np.nanmin(dz[ok]), np.nanmax(dz[ok]), 2)
    ax.plot(xx, -6.5e-3 * xx, 'k--', lw=1, label='-6.5 K/km')
    ax.set_xlabel('5\' elevation - 0.5° parent mean (m)', fontsize=8)
    ax.set_ylabel('T smoke - T natural (K)', fontsize=8); ax.legend(fontsize=7)
    ax = axes.flat[7]
    ok2 = smask & np.isfinite(spm) & np.isfinite(np_dec)
    ax.scatter(np_dec[ok2], spm[ok2], s=2, alpha=0.4, color='#6a3d9a')
    mx = float(np.nanmax(np.r_[np_dec[ok2], spm[ok2]]))
    ax.plot([0, mx], [0, mx], 'k--', lw=1)
    ax.set_xlabel('natural precipitation 2010-2019 (mm/yr)', fontsize=8)
    ax.set_ylabel('smoke precipitation 2011-2020 (mm/yr)', fontsize=8)
    fig.suptitle('Snow that builds up every year: smoke (ISIMIP EC-Earth3-ESM-1-1, VIC 39e21ff5) against the natural '
                 'production run (WFDE5, VIC e083c9f3), same 5\' cells', fontsize=10)
    fig.tight_layout()
    fig.savefig(f'{csp.figures()}/snow_compare.png', dpi=130)
    print('wrote figures/snow_compare.png')


if __name__ == '__main__':
    main()
