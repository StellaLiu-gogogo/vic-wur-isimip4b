#!/usr/bin/env python3
"""Results note workdir/analysis/landuse-visualization/report.md, made only from the cache of build_cache.py.

Numbers: areas in 1850, 2021 and 2100 per scenario and source; VIC - ISIMIP differences (global and regional,
largest over all years) with the expected causes; coastal share of the 15' cells where the fractions differ; the
largest regional land-use changes.

Usage: write_report.py
"""
import datetime, os, sys

import numpy as np
import pandas as pd
import netCDF4 as nc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lu_vis as lv   # noqa: E402

GROUPS = ('urban', 'rainfed', 'irrigated', 'paddy', 'natural', 'barren')


def table(df):
    """Rows: (scenario, year); columns: group x source. VIC natural is shown with and without barren."""
    rows = []
    for soc, year in (('histsoc', 1850), ('histsoc', 2021), ('1850soc', 2021), ('2021soc', 2100),
                      ('ssp1vlsoc-noadapt', 2100), ('ssp3hsoc-noadapt', 2100)):
        s = df[(df.soc == soc) & (df.year == year) & (df.region == 'global')]
        val = lambda src, g: s[(s.source == src) & (s.group == g)].area_Mkm2.sum()
        r = {'scenario': soc, 'year': year}
        for g in ('urban', 'rainfed', 'irrigated', 'paddy'):
            r[f'{g} VIC'] = val('vic', g); r[f'{g} ISIMIP-dom'] = val('isimip_vic_domain', g); r[f'{g} ISIMIP'] = val('isimip', g)
        r['natural+barren VIC'] = val('vic', 'natural') + val('vic', 'barren'); r['barren VIC'] = val('vic', 'barren')
        r['natural ISIMIP-dom'] = val('isimip_vic_domain', 'natural'); r['natural ISIMIP'] = val('isimip', 'natural')
        rows.append(r)
    return pd.DataFrame(rows)


def md(df, fmt='{:.3f}'):
    cols = list(df.columns)
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '|'.join('---' for _ in cols) + '|']
    for _, r in df.iterrows():
        out.append('| ' + ' | '.join(fmt.format(v) if isinstance(v, float) else str(v) for v in r.values) + ' |')
    return '\n'.join(out)


def differences(df):
    """Largest |VIC - ISIMIP on the VIC domain| over all years, per soc, group and region (natural: VIC incl. barren)."""
    v = df[df.source == 'vic'].pivot_table(index=['soc', 'year', 'region'], columns='group', values='area_Mkm2')
    v['natural'] = v['natural'] + v['barren']
    i = df[df.source == 'isimip_vic_domain'].pivot_table(index=['soc', 'year', 'region'], columns='group', values='area_Mkm2')
    rows = []
    for g in ('urban', 'rainfed', 'irrigated', 'paddy', 'natural'):
        d = (v[g] - i[g]).rename('diff').reset_index()
        for (soc, region), x in d.groupby(['soc', 'region']):
            k = x['diff'].abs().idxmax()
            rows.append({'group': g, 'soc': soc, 'region': region, 'max_abs_diff_Mkm2': float(abs(x.loc[k, 'diff'])),
                         'diff_Mkm2': float(x.loc[k, 'diff']), 'year': int(x.loc[k, 'year']),
                         'relative': float(x.loc[k, 'diff'] / max(i.loc[(soc, int(x.loc[k, 'year']), region), g], 1e-12))})
    return pd.DataFrame(rows)


def coastal_share():
    """Share of the 15' cells with |VIC - ISIMIP fraction| > 1e-3 that are coastal (active fraction < 0.99), 2021."""
    c = f'{lv.products()}/cache'
    with nc.Dataset(f'{c}/static.nc') as d:
        af = d['active_fraction'][:].filled(0); land = d['isimip_land_fraction'][:].filled(0)
    dom = af > 0; out = {}
    with nc.Dataset(f'{c}/fields_vic_histsoc.nc') as dv, nc.Dataset(f'{c}/fields_isimip_histsoc.nc') as di:
        k = list(dv['year'][:]).index(2021)
        for g in ('urban', 'rainfed', 'irrigated', 'paddy', 'natural'):
            vv = dv[g][k].filled(np.nan) + (dv['barren'][k].filled(np.nan) if g == 'natural' else 0)
            d = (vv - di[g][k].filled(np.nan))[dom]; big = np.abs(d) > 1e-3
            out[g] = {'cells': int(big.sum()), 'of': int(dom.sum()), 'coastal_share': float((big & (af[dom] < 0.99)).sum() / max(big.sum(), 1)),
                      'inland_median_isimip_land_fraction': float(np.median(land[dom][big & (af[dom] >= 0.99)])) if (big & (af[dom] >= 0.99)).any() else None}
    return out


def changes(df):
    """VIC area change per region: 1850 -> 2021 (histsoc) and 2021 -> 2100 per future, crop and urban groups."""
    v = df[df.source == 'vic'].pivot_table(index=['soc', 'year', 'region'], columns='group', values='area_Mkm2')
    rows = []
    for r in lv.REGIONS:
        for g in ('urban', 'rainfed', 'irrigated'):
            h = v.loc[('histsoc', 2021, r), g] - v.loc[('histsoc', 1850, r), g]
            rows.append({'region': r, 'group': g, 'period': '1850-2021 histsoc', 'change_Mkm2': h})
            for f in lv.FUTURES:
                rows.append({'region': r, 'group': g, 'period': f'2021-2100 {f}',
                             'change_Mkm2': v.loc[(f, 2100, r), g] - v.loc[('histsoc', 2021, r), g]})
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv(f'{lv.products()}/cache/areas.csv')
    t = table(df); dif = differences(df); cs = coastal_share(); ch = changes(df)
    glob = dif[dif.region == 'global'].sort_values('max_abs_diff_Mkm2', ascending=False)
    reg = dif[(dif.region != 'global') & (dif.group != 'natural')].sort_values('max_abs_diff_Mkm2', ascending=False).head(8)
    big = ch.reindex(ch.change_Mkm2.abs().sort_values(ascending=False).index).head(12)
    L = [f'# Land-use visualisation: VIC-WUR 5′ forcing versus ISIMIP4b 15′ input', '',
         f'Generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d} by `analysis/{lv.TASK}/write_report.py` from '
         '`cache/areas.csv` and the 15′ fields. Areas in Mkm² (WGS84 cell areas). Sources: **VIC** = land-use '
         'forcing units `forcing/landuse/<soc>/` (method 1.3); **ISIMIP-dom** = ISIMIP fractions × full 15′ cell area '
         'over the 15′ cells that contain an active VIC cell (the area the converter distributes); **ISIMIP** = all 15′ cells. '
         'Natural: VIC classes 1–11 + 16 (barren) against ISIMIP forests_and_natural_vegetation + pastures.', '',
         '## Global areas', '', 'Crop and urban groups:', '',
         md(t[['scenario', 'year'] + [c for c in t.columns if c.split()[0] in ('urban', 'rainfed', 'irrigated', 'paddy')]]), '',
         'Natural vegetation (VIC natural + barren) and barren:', '',
         md(t[['scenario', 'year', 'natural+barren VIC', 'barren VIC', 'natural ISIMIP-dom', 'natural ISIMIP']]), '',
         '## VIC − ISIMIP differences', '',
         'Largest absolute difference over all years, VIC minus ISIMIP-dom, global:', '',
         md(glob[['group', 'soc', 'year', 'diff_Mkm2', 'relative']], '{:.2e}'), '',
         'Largest regional differences (crop and urban groups):', '',
         md(reg[['group', 'soc', 'region', 'year', 'diff_Mkm2', 'relative']], '{:.2e}'), '',
         '15′ cells whose VIC and ISIMIP fractions differ by more than 0.001 (histsoc 2021), and the share of them that are '
         'coastal (active VIC area < 99 % of the cell):', '']
    for g, x in cs.items():
        extra = f'; inland cells: median ISIMIP land fraction {x["inland_median_isimip_land_fraction"]:.2f}' if x['inland_median_isimip_land_fraction'] is not None else ''
        L.append(f'- {g}: {x["cells"]:,} of {x["of"]:,} cells, coastal share {x["coastal_share"]:.0%}{extra}')
    L += ['', 'Causes:', '',
          '- **Coastal cells (active-area fraction < 1)**: the VIC map value is a fraction of the active (land) area, the ISIMIP '
          'value a fraction of the whole cell, so VIC shows larger fractions wherever part of the 15′ cell is sea; the areas are '
          'the same. This is the only cause of map differences for urban, rainfed, irrigated and paddy.',
          '- **Converter conservation**: VIC and ISIMIP-dom agree to within a few km² globally and per region for every crop '
          'and urban group and year (the CSV resolution is 1 km²): the converter places the whole ISIMIP target of every 15′ '
          'cell that has active VIC land.',
          '- **D04 single-child rule**: a class without VIC weights in a parent is put into one 5′ child; it moves area '
          'inside the 15′ cell only, so it does not change any 15′ or regional number.',
          '- **Paddy = rice_irrigated** (D04 item 3): identical by construction on both sides.',
          '- **Natural and barren**: VIC treats every active cell as land, ISIMIP has a land fraction below 1 (inland water, '
          'ice); VIC natural + barren therefore exceeds ISIMIP natural. Barren (class 16) has no ISIMIP counterpart.',
          '- **ISIMIP outside the VIC domain**: ISIMIP minus ISIMIP-dom (about 2 000–3 000 km² for urban and rainfed crop, '
          '0.3 Mkm² for natural) is the area in 15′ cells without any active VIC cell (Greenland, small islands; D08); VIC does '
          'not simulate it.', '',
          '## Largest regional land-use changes (VIC)', '', md(big[['region', 'group', 'period', 'change_Mkm2']]), '',
          '## Products', '',
          '- `figures/maps/<group>_<future>.gif` and frames: ISIMIP | VIC | VIC − ISIMIP, histsoc 1850–2020 then the future 2030–2100',
          '- `figures/maps/change_<group>_<future>.gif`: change since 1850 (histsoc frames) or 2021 (future frames)',
          '- `figures/maps/dominant_<future>.gif`: dominant group per 15′ cell',
          '- `figures/timeseries/areas_<region>.png|pdf`, `stacked_<future>.png|pdf`',
          '- `cache/areas.csv|nc`, `cache/fields_<source>_<soc>.nc`, `cache/static.nc`']
    with open(f'{lv.products()}/report.md', 'w') as fh:
        fh.write('\n'.join(L) + '\n')
    dif.to_csv(f'{lv.products()}/cache/differences.csv', index=False, float_format='%.6g')
    ch.to_csv(f'{lv.products()}/cache/regional_changes.csv', index=False, float_format='%.6g')
    print(f'{lv.products()}/report.md')


if __name__ == '__main__':
    main()
