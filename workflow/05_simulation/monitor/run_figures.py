"""Derived water-use file and figures of a run check (check_run.py).

VIC-WUR at the locked commit writes the withdrawal of each water-use sector split by source
(OUT_WI_<source>_SECT, dimension wu_class = sector number of plugin_def.h) but no total per sector. The
derived file holds, per calendar month, sector and 5 arcmin cell, the withdrawal and its sources (mm over the
cell per month) and, for municipal and manufacturing, the VIC demand and the consumption estimated as
withdrawal x consumption fraction of the forcing (VIC does not write consumption per sector):

  withdrawal = GW + SURF + DAM + REMOTE + NONRENEWABLE  (the OUT_WITHDRAWN sum of wu_output.c under GWM FALSE)
  REMOTE = OUT_WI_TREM_SECT, water taken from other cells for this cell
"""
import os

import numpy as np
import netCDF4 as nc
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors

SECTORS = {'municipal': 0, 'manufacturing': 2, 'irrigation': 4}     # plugin_def.h: 0 mun, 1 ene, 2 man, 3 liv, 4 irr
SOURCES = {'groundwater': 'OUT_WI_GW_SECT', 'surface': 'OUT_WI_SURF_SECT', 'dam': 'OUT_WI_DAM_SECT',
           'remote': 'OUT_WI_TREM_SECT', 'nonrenewable': 'OUT_WI_NREN_SECT'}
SOURCE_COLORS = {'groundwater': '#8c564b', 'surface': '#1f77b4', 'dam': '#2ca02c', 'remote': '#ff7f0e',
                 'nonrenewable': '#7f7f7f'}
MONTHS = 'JFMAMJJASOND'


def read(ds, name, idx):
    v = ds[name]; v.set_auto_mask(False)
    a = np.asarray(v[idx], 'f8')
    a[np.abs(a) > 1e19] = np.nan
    return a


def km3(mm, area):
    return float(np.nansum(mm * area) * 1e-12)


def draw_map(path, field, mask, title, units, vmin, vmax, cmap='viridis', log=False):
    f = np.where(mask, field, np.nan)
    fig, ax = plt.subplots(figsize=(12, 5))
    norm = colors.LogNorm(vmin=vmin, vmax=vmax) if log else colors.Normalize(vmin=vmin, vmax=vmax)
    im = ax.imshow(f, origin='lower', extent=(-180, 180, -56, 84), cmap=cmap, norm=norm, interpolation='nearest')
    ax.set_title(title); fig.colorbar(im, ax=ax, label=units, shrink=0.8)
    fig.savefig(path, dpi=110, bbox_inches='tight'); plt.close(fig)


def water_use(year, monthly, mask, area, lat, lon, cons_frac, out_nc, figs, provenance):
    """Write the derived file; return global monthly series and annual maps for the figures."""
    nm = len(monthly.dimensions['time']); ny, nx = mask.shape
    with nc.Dataset(out_nc + '.part', 'w', format='NETCDF4') as o:
        o.createDimension('time', nm); o.createDimension('sector', len(SECTORS))
        o.createDimension('lat', ny); o.createDimension('lon', nx)
        o.createVariable('lat', 'f8', ('lat',))[:] = lat; o.createVariable('lon', 'f8', ('lon',))[:] = lon
        t = o.createVariable('time', 'i4', ('time',)); t[:] = np.arange(1, nm + 1); t.long_name = 'month of the year'
        s = o.createVariable('sector', str, ('sector',))
        for k, name in enumerate(SECTORS):
            s[k] = name
        o.sector_numbers = 'municipal = VIC water-use sector 0, manufacturing = 2 (ISIMIP industrial: manufacturing + energy), irrigation = 4'
        kw = dict(zlib=True, complevel=4, shuffle=True, chunksizes=(1, 1, ny, nx), fill_value=np.float32(1e20))
        var = {}
        for v, desc in [('withdrawal', 'GW + SURF + DAM + REMOTE + NONRENEWABLE'),
                        *[(f'withdrawal_{k}', SOURCES[k]) for k in SOURCES],
                        ('demand', 'OUT_DE_GW_SECT + OUT_DE_SURF_SECT (municipal and manufacturing only)'),
                        ('consumption_estimate', 'withdrawal x consumption fraction of the forcing (municipal and manufacturing only)')]:
            var[v] = o.createVariable(v, 'f4', ('time', 'sector', 'lat', 'lon'), **kw)
            var[v].units = 'mm per month over the cell area'; var[v].description = desc
        o.setncatts(provenance)
        series = {sec: {src: np.zeros(nm) for src in list(SOURCES) + ['withdrawal', 'demand', 'consumption_estimate']}
                  for sec in SECTORS}
        annual = {sec: {k: np.zeros(mask.shape) for k in ('withdrawal', 'demand', 'remote', 'groundwater')}
                  for sec in SECTORS}
        for m in range(nm):
            src = {k: read(monthly, v, m) for k, v in SOURCES.items()}
            de = read(monthly, 'OUT_DE_GW_SECT', m) + read(monthly, 'OUT_DE_SURF_SECT', m)
            for k, (sec, i) in enumerate(SECTORS.items()):
                parts = {s_: np.nan_to_num(src[s_][i]) for s_ in SOURCES}
                ww = sum(parts.values())
                for s_, a in parts.items():
                    var[f'withdrawal_{s_}'][m, k] = np.where(mask, a, 1e20).astype('f4')
                    series[sec][s_][m] = km3(a, area)
                var['withdrawal'][m, k] = np.where(mask, ww, 1e20).astype('f4')
                series[sec]['withdrawal'][m] = km3(ww, area)
                annual[sec]['withdrawal'] += ww
                annual[sec]['remote'] += parts['remote']; annual[sec]['groundwater'] += parts['groundwater']
                if sec in cons_frac:
                    d = np.nan_to_num(de[i]); c = ww * np.nan_to_num(cons_frac[sec])
                    var['demand'][m, k] = np.where(mask, d, 1e20).astype('f4')
                    var['consumption_estimate'][m, k] = np.where(mask, c, 1e20).astype('f4')
                    series[sec]['demand'][m] = km3(d, area); series[sec]['consumption_estimate'][m] = km3(c, area)
                    annual[sec]['demand'] += d
                else:
                    var['demand'][m, k] = np.where(mask, np.nan, 1e20).astype('f4')
                    var['consumption_estimate'][m, k] = np.where(mask, np.nan, 1e20).astype('f4')
    os.replace(out_nc + '.part', out_nc)
    return series, annual


def water_use_figures(year, series, annual, irrigation, mask, figs):
    made = []
    # stacked monthly withdrawal by source, one panel per sector
    fig, axs = plt.subplots(1, 3, figsize=(16, 4.5))
    for ax, sec in zip(axs, SECTORS):
        bottom = np.zeros(12)
        for s_ in SOURCES:
            v = series[sec][s_]
            if v.sum() > 0:
                ax.bar(np.arange(12), v, bottom=bottom, color=SOURCE_COLORS[s_], label=s_)
                bottom += v
        if sec != 'irrigation':
            ax.plot(np.arange(12), series[sec]['demand'], 'k-', marker='o', ms=3, label='demand')
            ax.plot(np.arange(12), series[sec]['consumption_estimate'], 'k--', label='consumption (estimate)')
        else:
            ax.plot(np.arange(12), irrigation['received'], 'k-', marker='o', ms=3, label='received by fields')
        tot = series[sec]['withdrawal'].sum()
        ax.set_title(f'{sec}: {tot:.0f} km3/yr'); ax.set_xticks(range(12)); ax.set_xticklabels(list(MONTHS))
        ax.set_ylabel('km3 per month'); ax.legend(fontsize=7)
    fig.suptitle(f'global withdrawal by sector and source, {year}')
    fig.savefig(f'{figs}/withdrawal_by_sector_and_source_{year}.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    made.append(f'withdrawal_by_sector_and_source_{year}.png')
    # annual share of each source per sector
    fig, ax = plt.subplots(figsize=(8, 4))
    left = np.zeros(3)
    for s_ in SOURCES:
        v = np.array([series[sec][s_].sum() for sec in SECTORS])
        frac = v / np.maximum(np.array([series[sec]['withdrawal'].sum() for sec in SECTORS]), 1e-12)
        ax.barh(list(SECTORS), frac, left=left, color=SOURCE_COLORS[s_], label=s_); left += frac
    ax.set_xlabel('share of the annual withdrawal'); ax.legend(fontsize=7, loc='lower right')
    ax.set_title(f'withdrawal sources, {year}')
    fig.savefig(f'{figs}/withdrawal_source_shares_{year}.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    made.append(f'withdrawal_source_shares_{year}.png')
    # maps per sector
    for sec in SECTORS:
        draw_map(f'{figs}/withdrawal_{sec}_{year}.png', np.maximum(annual[sec]['withdrawal'], 1e-2), mask,
                 f'{sec} withdrawal {year}', 'mm/yr', 0.1, 1000, cmap='YlGnBu', log=True)
        made.append(f'withdrawal_{sec}_{year}.png')
    # remote and groundwater shares: maps and histograms (all sectors)
    ww = sum(annual[s]['withdrawal'] for s in SECTORS)
    rem = sum(annual[s]['remote'] for s in SECTORS); gw = sum(annual[s]['groundwater'] for s in SECTORS)
    sel = mask & (ww > 0.1)
    for name, part in (('remote', rem), ('groundwater', gw)):
        share = np.where(sel, part / np.where(sel, ww, 1), np.nan)
        draw_map(f'{figs}/share_{name}_{year}.png', share, mask, f'share of {name} water in the withdrawal {year}',
                 '-', 0, 1, cmap='magma_r')
        made.append(f'share_{name}_{year}.png')
    fig, axs = plt.subplots(1, 4, figsize=(18, 3.8))
    for ax, sec in zip(axs[:2], ('municipal', 'manufacturing')):
        d = annual[sec]['demand']; ok = mask & (d > 0.1)
        r = annual[sec]['withdrawal'][ok] / d[ok]
        ax.hist(np.clip(r, 0, 1.05), bins=42, color='#1f77b4')
        ax.set_yscale('log'); ax.set_title(f'{sec}: withdrawal / demand\n({ok.sum()} cells with demand > 0.1 mm/yr)')
    for ax, (name, part) in zip(axs[2:], (('remote', rem), ('groundwater', gw))):
        ax.hist(part[sel] / ww[sel], bins=40, color=SOURCE_COLORS[name])
        ax.set_yscale('log'); ax.set_title(f'share of {name} water\n({sel.sum()} cells with withdrawal > 0.1 mm/yr)')
    fig.savefig(f'{figs}/water_use_distributions_{year}.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    made.append(f'water_use_distributions_{year}.png')
    return made


def water_balance(year, monthly, mask, area, lat, figs):
    """Global monthly precipitation, evapotranspiration, runoff (km3) and zonal means (mm/yr)."""
    nm = len(monthly.dimensions['time'])
    keys = ('OUT_PREC', 'OUT_EVAP', 'OUT_RUNOFF', 'OUT_BASEFLOW')
    glob_ = {k: np.zeros(nm) for k in keys}; ann = {k: np.zeros(mask.shape) for k in keys}
    store = {k: np.zeros(nm) for k in ('OUT_SOIL_MOIST', 'OUT_SWE', 'OUT_SNOW_CANOPY', 'OUT_WDEW', 'OUT_SURFSTOR')}
    for m in range(nm):
        for k in keys:
            a = np.nan_to_num(read(monthly, k, m)); glob_[k][m] = km3(a, area); ann[k] += a
        for k in store:
            a = read(monthly, k, m)
            a = np.nansum(a, axis=0) if a.ndim == 3 else np.nan_to_num(a)
            store[k][m] = km3(a, area)
    p, e, q = glob_['OUT_PREC'], glob_['OUT_EVAP'], glob_['OUT_RUNOFF'] + glob_['OUT_BASEFLOW']
    stor = sum(store.values())
    fig, axs = plt.subplots(1, 3, figsize=(18, 4.5))
    ax = axs[0]
    vals = [p.sum(), e.sum(), q.sum(), p.sum() - e.sum() - q.sum()]
    ax.bar(['precipitation', 'evapotranspiration', 'qtot', 'P - ET - qtot'], vals,
           color=['#1f77b4', '#2ca02c', '#ff7f0e', '#7f7f7f'])
    for i, v in enumerate(vals):
        ax.text(i, v, f'{v:.0f}', ha='center', va='bottom' if v >= 0 else 'top', fontsize=8)
    ax.set_ylabel('km3/yr'); ax.set_title(f'global land water balance {year}'); ax.tick_params(axis='x', labelsize=8, rotation=15)
    ax = axs[1]
    for v, lab in ((p, 'precipitation'), (e, 'evapotranspiration'), (q, 'qtot'), (glob_['OUT_BASEFLOW'], 'baseflow')):
        ax.plot(range(nm), v, marker='o', ms=3, label=lab)
    ax2 = ax.twinx(); ax2.plot(range(nm), stor, 'k--', label='storage (soil, snow, canopy, surface), mean')
    ax2.set_ylabel('km3 (storage)'); ax.set_xticks(range(nm)); ax.set_xticklabels(list(MONTHS)[:nm])
    ax.set_ylabel('km3 per month'); ax.legend(fontsize=7, loc='upper left'); ax2.legend(fontsize=7, loc='upper right')
    ax.set_title('global monthly fluxes and storage')
    ax = axs[2]
    band = np.floor(lat / 2.0) * 2.0
    for k, lab in (('OUT_PREC', 'precipitation'), ('OUT_EVAP', 'evapotranspiration')):
        z = [np.nanmean(ann[k][(band == b)[:, None] & mask]) if ((band == b)[:, None] & mask).any() else np.nan
             for b in np.unique(band)]
        ax.plot(z, np.unique(band) + 1, label=lab)
    qq = ann['OUT_RUNOFF'] + ann['OUT_BASEFLOW']
    z = [np.nanmean(qq[(band == b)[:, None] & mask]) if ((band == b)[:, None] & mask).any() else np.nan
         for b in np.unique(band)]
    ax.plot(z, np.unique(band) + 1, label='qtot')
    ax.set_xlabel('mm/yr (mean over active cells)'); ax.set_ylabel('latitude'); ax.legend(fontsize=7)
    ax.set_title('zonal means (2 degree bands)')
    fig.savefig(f'{figs}/water_balance_{year}.png', dpi=110, bbox_inches='tight'); plt.close(fig)
    return {'precipitation_km3': float(p.sum()), 'evapotranspiration_km3': float(e.sum()), 'qtot_km3': float(q.sum()),
            'p_minus_et_minus_qtot_km3': float(p.sum() - e.sum() - q.sum()),
            'storage_monthly_mean_km3': [float(x) for x in stor]}, f'water_balance_{year}.png'
