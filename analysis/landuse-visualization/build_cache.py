#!/usr/bin/env python3
"""Derived data cache of the land-use visualisation: areas and 15' fraction fields, VIC 5' forcing and ISIMIP 15' inputs.

Reads every coverage file of the five accepted land-use forcing units (forcing/landuse/<soc>/) and the matching
year of the ISIMIP4b landuse-15crops, -urbanareas and -totals files, once, and writes to
workdir/analysis/landuse-visualization/cache/:
  areas.csv, areas.nc   area (Mkm2) per source, soc, year, group and region; sources:
                          vic                 sum over active 5' cells of coverage x cell area
                          isimip              sum over all 15' cells of fraction x cell area
                          isimip_vic_domain   as isimip, over the 15' cells that contain an active VIC cell (the
                                              area the land-use converter distributes, so comparable with vic)
  fields_<source>_<soc>.nc  15' fraction fields of every group for the frame years (lu_vis.FIELD_YEARS):
                          vic     area-weighted mean over the active 5' cells of each 15' cell (fraction of the
                                  active area; NaN where the 15' cell has no active cell)
                          isimip  whole-cell fraction as delivered
  static.nc               active-area fraction of each 15' cell, ISIMIP land fraction (histsoc 2021), cell area,
                          region masks
All areas use the WGS84 cell area (the domain file's 5' area; 15' cells: the analytic WGS84 area).

Groups (D04): urban = VIC 13 | urbanareas; rainfed = VIC 12 | sum of the 17 *_rainfed* variables (incl.
rice_rainfed, *_rainfed_bf); irrigated = VIC 14+15 | sum of the 17 *_irrigated* variables (incl. *_irrigated_bf);
paddy = VIC 15 | rice_irrigated; natural = VIC 1-11 | forests_and_natural_vegetation + pastures (landuse-totals;
VIC puts pastures into the natural remainder); barren = VIC 16 (no ISIMIP counterpart).

Usage: build_cache.py [--processes 16]   (run as a Slurm job: submit_cache.py)
"""
import argparse, datetime, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import netCDF4 as nc
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lu_vis as lv   # noqa: E402

DOMAIN = 'parameters/candidates/vic-global-5arcmin-version-a/domain/vic_global_5min_domain_nogl.nc'
RAW = 'raw/ISIMIP4b/InputData/socioeconomic/landuse'
ROW0, ROW1 = 24, 584            # ISIMIP rows (N->S) covered by the VIC domain
_S = {}                         # static arrays, set before the workers are forked


def isimip_file(kind, soc):
    span = '1850_2021' if lv.FIRST_YEAR[soc] == 1850 else '2022_2100'
    return f'{lv.workdir()}/{RAW}/{soc}/landuse-{kind}_{lv.ISIMIP_TAG[soc]}_15arcmin_annual_{span}.nc'


def blocksum(x):
    """(…, 1680, 4320) -> (…, 560, 1440) sums of 3 x 3 blocks."""
    s = x.shape
    return x.reshape(s[:-2] + (s[-2] // 3, 3, s[-1] // 3, 3)).sum(axis=(-3, -1))


def isimip_groups(soc, t):
    """Whole-cell fractions (720, 1440) of every ISIMIP group in year index t, plus the land fraction."""
    g = {}
    with nc.Dataset(isimip_file('15crops', soc)) as d:
        rf = [v for v in d.variables if '_rainfed' in v]; ir = [v for v in d.variables if '_irrigated' in v]
        assert len(rf) == 17 and len(ir) == 17
        get = lambda v: d[v][t].filled(0).astype('f8')
        g['rainfed'] = sum(get(v) for v in rf); g['irrigated'] = sum(get(v) for v in ir); g['paddy'] = get('rice_irrigated')
    with nc.Dataset(isimip_file('urbanareas', soc)) as d:
        g['urban'] = d['urbanareas'][t].filled(0).astype('f8')
    with nc.Dataset(isimip_file('totals', soc)) as d:
        nat = d['forests_and_natural_vegetation'][t].filled(0).astype('f8'); past = d['pastures'][t].filled(0).astype('f8')
        land = nat + past + d['cropland_total'][t].filled(0).astype('f8') + g['urban']
    g['natural'] = nat + past
    return g, land


def year_job(job):
    soc, year = job; S = _S; t = year - lv.FIRST_YEAR[soc]; t0 = time.time()
    out_area, out_field = [], {}
    # ---- VIC: 5' coverage -> 15' areas and fractions
    with nc.Dataset(f'{lv.workdir()}/forcing/landuse/{soc}/coverage_{soc}_{year}.nc') as d:
        cov = np.nan_to_num(d['coverage'][0].filled(np.nan))
    a5 = S['a5']; act15 = S['act15']
    vic = {}
    for grp, ks in lv.VIC_GROUP.items():
        area15 = blocksum(sum(cov[k].astype('f8') for k in ks) * a5)
        vic[grp] = area15
        for r, m in S['regions'].items():
            out_area.append(('vic', soc, year, grp, r, float(area15[m].sum() * 1e-12)))
    del cov
    # ---- ISIMIP: whole-cell fractions; full grid and the VIC-domain part
    g, _land = isimip_groups(soc, t)
    A15 = S['A15full']; dom = S['dom15']
    for grp in lv.GROUPS:
        if grp == 'barren':
            continue
        f = g[grp]; sub = f[ROW0:ROW1][::-1]
        for r, m in S['regions_full'].items():
            out_area.append(('isimip', soc, year, grp, r, float((f * A15)[m].sum() * 1e-12)))
        for r, m in S['regions'].items():
            out_area.append(('isimip_vic_domain', soc, year, grp, r, float((sub * S['A15'])[m & dom].sum() * 1e-12)))
    if year in lv.FIELD_YEARS[soc]:
        out_field['vic'] = {grp: np.where(dom, vic[grp] / np.where(dom, act15, 1), np.nan).astype('f4') for grp in lv.GROUPS}
        out_field['isimip'] = {grp: g[grp][ROW0:ROW1][::-1].astype('f4') for grp in lv.GROUPS if grp != 'barren'}
    print(f'{soc} {year}: {time.time() - t0:.0f} s', flush=True)
    return soc, year, out_area, out_field


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--processes', type=int, default=16)
    a = ap.parse_args(); t0 = time.time(); W = lv.workdir()
    out = f'{lv.products()}/cache'; os.makedirs(out, exist_ok=True)
    with nc.Dataset(f'{W}/{DOMAIN}') as d:
        mask = d['mask'][:].filled(0).astype(bool); a5 = np.where(mask, d['area'][:].astype('f8'), 0.0)
        vlat = d['lat'][:]; vlon = d['lon'][:]
    with nc.Dataset(isimip_file('totals', 'histsoc')) as d:
        ilat = d['lat'][:]; ilon = d['lon'][:]
    lat15 = vlat.reshape(-1, 3).mean(axis=1); lon15 = vlon.reshape(-1, 3).mean(axis=1)
    if not (np.abs(ilat[ROW0:ROW1][::-1] - lat15).max() < 1e-9 and np.abs(ilon - lon15).max() < 1e-9):
        raise SystemExit('the VIC 5 arcmin grid is not a 3 x 3 subdivision of the ISIMIP 15 arcmin grid')
    act15 = blocksum(a5); dom15 = act15 > 0
    A15 = lv.ellipsoid_cell_area(lat15, 0.25, 0.25)[:, None] * np.ones((1, 1440))
    A15full = lv.ellipsoid_cell_area(ilat, 0.25, 0.25)[:, None] * np.ones((1, 1440))
    _S.update(a5=a5, act15=act15, dom15=dom15, A15=A15, A15full=A15full,
              regions=lv.region_masks(lat15, lon15), regions_full=lv.region_masks(ilat, ilon))
    _g21, land21 = isimip_groups('histsoc', 2021 - 1850)
    with nc.Dataset(f'{out}/static.nc.part', 'w') as o:
        o.createDimension('lat', len(lat15)); o.createDimension('lon', len(lon15))
        v = o.createVariable('lat', 'f8', ('lat',)); v[:] = lat15; v.units = 'degrees_north'
        v = o.createVariable('lon', 'f8', ('lon',)); v[:] = lon15; v.units = 'degrees_east'
        v = o.createVariable('active_fraction', 'f4', ('lat', 'lon'), zlib=True); v[:] = act15 / A15
        v.long_name = 'active VIC area / 15 arcmin cell area (WGS84)'
        v = o.createVariable('isimip_land_fraction', 'f4', ('lat', 'lon'), zlib=True); v[:] = land21[ROW0:ROW1][::-1]
        v.long_name = 'ISIMIP land fraction (cropland + pastures + forests and natural vegetation + urban), histsoc 2021'
        v = o.createVariable('cell_area', 'f8', ('lat', 'lon'), zlib=True); v[:] = A15; v.units = 'm2'
        for r, m in _S['regions'].items():
            v = o.createVariable(f'region_{r}', 'i1', ('lat', 'lon'), zlib=True); v[:] = m.astype('i1')
        o.title = 'land-use visualisation: static 15 arcmin fields'; o.created_at = utcnow()
    os.replace(f'{out}/static.nc.part', f'{out}/static.nc')

    jobs = [(s, y) for s in lv.SOC for y in range(lv.FIRST_YEAR[s], lv.LAST_YEAR[s] + 1)]
    rows = []; fields = {(src, s): {} for src in ('vic', 'isimip') for s in lv.SOC}
    with ProcessPoolExecutor(a.processes, mp_context=get_context('fork')) as ex:
        for soc, year, ar, fl in ex.map(year_job, jobs, chunksize=1):
            rows += ar
            for src, gg in fl.items():
                fields[(src, soc)][year] = gg
    df = pd.DataFrame(rows, columns=['source', 'soc', 'year', 'group', 'region', 'area_Mkm2']).sort_values(
        ['source', 'soc', 'group', 'region', 'year'])
    df.to_csv(f'{out}/areas.csv', index=False, float_format='%.6f')
    ds = df.set_index(['source', 'soc', 'group', 'region', 'year']).to_xarray()
    ds['area_Mkm2'].attrs.update(units='1e6 km2', long_name='land-use area')
    ds.attrs.update(title='land-use visualisation: areas per source, soc, group, region and year', created_at=utcnow(),
                    sources='vic: forcing/landuse/<soc>; isimip and isimip_vic_domain: ' + RAW)
    ds.to_netcdf(f'{out}/areas.nc')
    for (src, soc), byyear in fields.items():
        years = sorted(byyear)
        with nc.Dataset(f'{out}/fields_{src}_{soc}.nc.part', 'w') as o:
            o.createDimension('year', len(years)); o.createDimension('lat', len(lat15)); o.createDimension('lon', len(lon15))
            o.createVariable('year', 'i4', ('year',))[:] = years
            v = o.createVariable('lat', 'f8', ('lat',)); v[:] = lat15; v.units = 'degrees_north'
            v = o.createVariable('lon', 'f8', ('lon',)); v[:] = lon15; v.units = 'degrees_east'
            for grp in byyear[years[0]]:
                v = o.createVariable(grp, 'f4', ('year', 'lat', 'lon'), zlib=True, complevel=4, fill_value=np.float32(np.nan),
                                     chunksizes=(1, len(lat15), len(lon15)))
                v[:] = np.stack([byyear[y][grp] for y in years]); v.long_name = f'{lv.LABEL[grp]} fraction'
            o.source = src; o.soc_scenario = soc; o.created_at = utcnow()
            o.fraction_definition = ('area-weighted mean over the active VIC 5 arcmin cells (fraction of the active area)'
                                     if src == 'vic' else 'ISIMIP whole-cell fraction')
        os.replace(f'{out}/fields_{src}_{soc}.nc.part', f'{out}/fields_{src}_{soc}.nc')
    print(f'done: {len(jobs)} years in {time.time() - t0:.0f} s -> {out}')


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


if __name__ == '__main__':
    main()
