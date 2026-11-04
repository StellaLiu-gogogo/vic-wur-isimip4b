#!/usr/bin/env python3
"""Build workdir/analysis/block-structure/report.html from the tables and figures of block_screen.py: the block signal
of every screened field grouped by source (run outputs, forcing, parameters, the MPR candidate), the figures of the
fields discussed, and the reading. Every number comes from the tables; figures are embedded (base64).

Usage: make_report.py [--dir DIR]   (DIR defaults to workdir/analysis/block-structure; login node, seconds)"""
import argparse, base64, csv, datetime, html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from block_screen import TASK, figure_name, REGIONS   # noqa: E402

RATIO_COLS = ('ratio_l2', 'ratio_l1', 'ratio_l05', 'ratio_l025')
OUTPUT_FIGURES = [('OUT_RUNOFF', '2011-2020 mean', 'Surface runoff, 2011-2020 mean (mm/month)'),
                  ('OUT_BASEFLOW', '2011-2020 mean', 'Baseflow, 2011-2020 mean (mm/month)'),
                  ('OUT_EVAP', '2011-2020 mean', 'Evapotranspiration, 2011-2020 mean (mm/month)'),
                  ('OUT_SOIL_MOIST', 'layer=2 2011-2020 mean', 'Soil moisture of layer 2 (the deepest), 2011-2020 mean (mm)')]
FORCING_FIGURES = [('forcing-clim', 'prec', 'Precipitation (mm/day): the ISIMIP 0.5-degree cells replicated'),
                   ('forcing-clim', 'tair', 'Air temperature (degC): replicated 0.5-degree values with the lapse-rate correction')]
PARAM_FIGURES = [('param-b', 'groundwater_fraction (irrigation)', '', 'Groundwater fraction of the irrigation file (WaterGAP, 0.5 degree)'),
                 ('param-b', 'irrigation_efficiency', '', 'Irrigation efficiency (one value per country)'),
                 ('param-a', 'depth', 'nlayer=1', 'Version-a: depth of layer 2 (m), the 2-degree calibration blocks'),
                 ('param-mpr', 'depth', 'nlayer=1', 'MPR candidate: depth of layer 2 (m)'),
                 ('param-mpr', 'Ds', '', 'MPR candidate: Ds (equal to Dsmax)')]
LABEL = {'ratio_l2': '2° edges', 'ratio_l1': '1° lines', 'ratio_l05': '0.5° lines', 'ratio_l025': '0.25° lines',
         'share_05': 'share on ≥0.5° lines'}


def img(path, cap):
    if not os.path.isfile(path):
        return f'<p class="note">figure missing: {html.escape(os.path.basename(path))}</p>'
    with open(path, 'rb') as fh:
        b = base64.b64encode(fh.read()).decode()
    return f'<figure><img src="data:image/png;base64,{b}" alt="{html.escape(cap)}"><figcaption>{html.escape(cap)}</figcaption></figure>'


def table(head, rows, note=None):
    h = ''.join(f'<th>{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    n = f'<p class="note">{note}</p>' if note else ''
    return f'<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>{n}'


def fl(x, d=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 'n/a'
    return 'n/a' if x != x else f'{x:.{d}f}'


def ratio_rows(rows):
    return [[html.escape(r['field']), html.escape(r['index'] or ''), *[fl(r[c]) for c in RATIO_COLS], fl(r['share_05'], 3),
             r['signal']] for r in rows]


RATIO_HEAD = ['field', 'slice', *[LABEL[c] for c in RATIO_COLS], LABEL['share_05'], 'signal']


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dir', default=None)
    a = ap.parse_args()
    if a.dir is None:
        sys.path.insert(0, os.path.join(HERE, '..', '..', 'workflow'))
        from common import workdir
        a.dir = f'{workdir.root()}/analysis/{TASK}'
    T, F = f'{a.dir}/tables', f'{a.dir}/figures'
    with open(f'{T}/block_screen.csv', newline='') as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in (*RATIO_COLS, 'share_05', 'field_mean', 'mean_interior'):
            r[k] = float(r[k]) if r[k] not in ('', 'nan') else float('nan')
    summary = json.load(open(f'{T}/summary.json'))
    mpr = list(csv.DictReader(open(f'{T}/mpr_vs_a.csv', newline='')))
    pct = json.load(open(f'{T}/mpr_depth_percentiles.json'))
    fig = lambda g, n, i: f'{F}/{figure_name(g, n, i)}.png'   # noqa: E731
    by = lambda g: [r for r in rows if r['group'] == g]        # noqa: E731
    get = lambda g, n, i='': next((r for r in rows if r['group'] == g and r['field'] == n and r['index'] == i), None)  # noqa: E731
    runs = sorted(set(r['group'] for r in rows if r['group'].startswith('output-')))
    parts = []

    # ---- head
    parts.append(f'<h1>Block structure in the VIC-WUR inputs and outputs</h1>'
                 f'<p>Analysis <code>analysis/{TASK}/</code> (task Z follow-up, user 2026-11-04). For every field the absolute '
                 f'difference between neighbouring active cells is averaged separately for cell pairs that straddle a 2-degree '
                 f'calibration-block edge (the version-a rule), a 1-degree line, a 0.5-degree line (the ISIMIP grid), a 0.25-degree '
                 f'line, and for all other pairs (interior). The tables show each line class divided by the interior mean: about 1 for '
                 f'a field without that structure, large for a field that is piecewise constant on that grid. "{LABEL["share_05"]}" '
                 f'is the share of the total cell-to-cell variation on lines of 0.5 degree or coarser (such pairs are 1/6 of all '
                 f'pairs). Zoom regions of the figures: {"; ".join(REGIONS)}. {summary["rows"]} field slices screened; signals: '
                 f'{", ".join(f"{k} {v}" for k, v in sorted(summary["signals"].items()))}. Built {datetime.date.today()}.</p>')

    # ---- 1 outputs
    parts.append('<h2>1. Run outputs (2011-2020 mean of the monthly output)</h2>')
    for g in runs:
        v = g.split('-')[1]
        rr = sorted(by(g), key=lambda r: -r['ratio_l05'])
        runoff, base = get(g, 'OUT_RUNOFF', '2011-2020 mean'), get(g, 'OUT_BASEFLOW', '2011-2020 mean')
        parts.append(f'<h3>Comparison run with parameter set version-{v} ({len(rr)} slices)</h3>')
        parts.append(table(RATIO_HEAD, ratio_rows(rr)))
        if runoff and base:
            parts.append(f'<p>The 2-, 1- and 0.5-degree lines carry about the same ratio and the 0.25-degree lines none: the structure '
                         f'in the outputs is the 0.5-degree grid of the ISIMIP inputs, not the 2-degree calibration blocks. Surface runoff '
                         f'{fl(runoff["ratio_l05"])} and baseflow {fl(base["ratio_l05"])} on the 0.5-degree lines: a 0.5-degree line carries '
                         f'about twice the cell-to-cell difference of the interior.</p>')
        for n, i, cap in OUTPUT_FIGURES:
            parts.append(img(fig(g, n, i), f'version-{v}: {cap}'))

    # ---- 2 forcing
    parts.append(f'<h2>2. Forcing ({summary["inputs"]["forcing_year"]}: climate annual mean, water use, land-use coverage)</h2>')
    fr = [r for r in rows if r['group'].startswith('forcing-') and (r['group'] == 'forcing-clim' or r['ratio_l05'] > 1.1)]
    parts.append(table(['group'] + RATIO_HEAD, [[r['group'], *x] for r, x in zip(fr, ratio_rows(fr))],
                       'The climate variables in full; water-use and land-use slices only where the 0.5-degree ratio exceeds 1.1. '
                       'A field that is exactly constant inside every 0.5-degree cell has an interior mean of zero: ratio n/a, share 1.'))
    parts.append('<p>prec: pure 0.5-degree blocks (the ISIMIP value replicated to the 36 cells of each 0.5-degree cell, method 1.1 '
                 'of 04_forcing/climate; the interior difference is exactly zero). tair and lwdown: replication plus the elevation '
                 'correction, so the blocks show through where the terrain is flat. psurf, vp, swdown, wind: no blocks (bilinear '
                 'interpolation, or the hypsometric pressure of a smooth field). Water-use consumption and groundwater fractions: pure '
                 '0.5-degree blocks (ISIMIP/WaterGAP values per 0.5-degree cell); the demands are distributed by population and carry '
                 'no block signal. Land-use coverage: no 0.5-degree structure beyond the threshold.</p>')
    for g, n, cap in FORCING_FIGURES:
        parts.append(img(fig(g, n, f'{summary["inputs"]["forcing_year"]} mean'), cap))

    # ---- 3 parameters
    parts.append('<h2>3. Parameter files</h2><h3>The calibration fields: version-a (2-degree blocks) and version-b (smoothed)</h3>')
    pa = by('param-a')
    pb = [get('param-b', r['field'], r['index']) for r in pa]
    parts.append(table(['field', 'slice', 'version-a 2° edges', 'version-a 0.5° lines', 'version-a signal', 'version-b 2° edges',
                        'version-b 0.5° lines', 'version-b signal'],
                       [[html.escape(r['field']), html.escape(r['index']), fl(r['ratio_l2']), fl(r['ratio_l05']), r['signal'],
                         fl(b['ratio_l2']) if b else 'n/a', fl(b['ratio_l05']) if b else 'n/a', b['signal'] if b else 'n/a']
                        for r, b in zip(pa, pb)]))
    pbs = by('param-b')
    exc = [r for r in pbs if r['signal'] not in ('none', 'constant')]
    parts.append(f'<h3>Version-b file and the irrigation file: slices with a signal ({len(exc)} of {len(pbs)})</h3>')
    parts.append(table(RATIO_HEAD, ratio_rows(exc)))
    parts.append('<p>groundwater_fraction of the irrigation file is the WaterGAP groundwater share per 0.5-degree cell (pure blocks; '
                 'it sets the groundwater share of the irrigation withdrawal). irrigation_efficiency is one value per country with '
                 'hard edges along the borders: not grid blocks, the ratios are large because the field is constant inside a country. '
                 'soil_depth_source_class and phi_s_compatibility_flag are bookkeeping flags VIC does not read. Slices that are almost '
                 'everywhere zero (a snow band or a backfill level with a handful of cells) give large ratios from a few cells.</p>')
    for g, n, i, cap in PARAM_FIGURES[:3]:
        parts.append(img(fig(g, n, i), cap))

    # ---- 4 MPR
    parts.append('<h2>4. The MPR soil candidate (the soil of version-c)</h2>')
    pm = by('param-mpr')
    parts.append(table(RATIO_HEAD, ratio_rows(pm)))
    soil = [m for m in mpr if m.get('kind') == 'soil']
    parts.append(table(['field', 'mean MPR', 'mean version-a', 'largest difference', 'cells that differ', 'cells compared'],
                       [[m['field'], fl(m['mean_mpr'], 4), fl(m['mean_a'], 4), fl(m['max_abs_diff'], 4), m['cells_differ'],
                         m['cells_compared']] for m in soil],
                       'Means over the active cells, every layer together; a 3-D field counts every layer in the cells compared.'))
    tmpl = [m for m in mpr if m.get('kind') == 'template']
    same = [m['field'] for m in tmpl if m['cells_differ'] == '0']
    diff = [f"{m['field']} ({m['cells_differ']} cells)" for m in tmpl if m['cells_differ'] != '0']
    missing = [m['field'] for m in mpr if m.get('kind') is None]
    parts.append(f'<p>No block structure in the soil fields of the MPR candidate: they come from SoilGrids through the Cosby transfer '
                 f'functions and the MPR operators on the 5-arcmin grid. Template fields equal to version-a bitwise: {", ".join(same)}; '
                 f'differing: {", ".join(diff) or "none"}; not in both files: {", ".join(missing) or "none"}. Depth of layer 2 '
                 f'(m), percentiles 5 / 25 / 50 / 95: {fl(pct["layer1"]["5"])} / {fl(pct["layer1"]["25"])} / {fl(pct["layer1"]["50"])} / '
                 f'{fl(pct["layer1"]["95"])}; layer 3: {fl(pct["layer2"]["5"])} / {fl(pct["layer2"]["25"])} / {fl(pct["layer2"]["50"])} / '
                 f'{fl(pct["layer2"]["95"])}.</p>')
    for g, n, i, cap in PARAM_FIGURES[3:]:
        parts.append(img(fig(g, n, i), cap))

    # ---- 5 reading
    r_out = {}
    for g in runs:
        for n, i in (('OUT_RUNOFF', '2011-2020 mean'), ('OUT_BASEFLOW', '2011-2020 mean'), ('OUT_RECHARGE', '2011-2020 mean'),
                     ('OUT_EVAP', '2011-2020 mean'), ('OUT_SOIL_MOIST', 'layer=2 2011-2020 mean')):
            r = get(g, n, i)
            if r:
                r_out.setdefault(g, []).append(f'{n} {fl(r["ratio_l05"])}')
    parts.append('<h2>5. Reading</h2>')
    parts.append(table(['structure', 'source', 'where it shows', 'what could change it'], [
        ['2-degree blocks', 'the five Nijssen calibration fields of version-a (depth[2], Ds, Dsmax, Ws, c)',
         'layer-2 soil moisture, baseflow and discharge of runs with version-a; gone in version-b (smoothed) and version-c (MPR)',
         'the parameter set (task Z: version-b or version-c)'],
        ['0.5-degree blocks', 'the ISIMIP climate input replicated to the 5-arcmin cells: prec (pure), tair and lwdown (with the '
         'elevation correction)', 'runoff, baseflow and recharge of every run (0.5-degree ratio about 2), evaporation and soil '
         'moisture (1.3-1.6), most visibly in dry regions', 'the downscaling method of 04_forcing/climate (method 1.1): an '
         'interpolation of prec would change the water balance of every 0.5-degree cell (bilinear interpolation is not conservative)'],
        ['0.5-degree blocks', 'the water-use forcing (consumption and groundwater fractions) and groundwater_fraction of the '
         'irrigation file (WaterGAP)', 'the groundwater and consumption split of the water-use outputs', 'the water-use forcing method'],
        ['country polygons', 'irrigation_efficiency of the irrigation file (one value per country)', 'irrigation withdrawal across '
         'borders', 'the irrigation parameter method'],
        ['none', 'every other parameter field of version-b, the soil of the MPR candidate, psurf, vp, swdown, wind, the land-use '
         'coverage', '', '']]))
    parts.append('<ul>' + ''.join(f'<li>{html.escape(s)}</li>' for s in [
        'The 2-degree blocks are gone from version-b and from its run outputs (the 2-degree edges carry no more than the 1- and '
        '0.5-degree lines).',
        'What remains in the outputs is the 0.5-degree grid of the ISIMIP inputs. 0.5-degree ratios of the run outputs: '
        + '; '.join(f'{g}: {", ".join(v)}' for g, v in r_out.items()) + '.',
        'These 0.5-degree blocks are the resolution of the protocol input; the ISIMIP products are delivered at 0.5 degree (D07), '
        'where they disappear by construction. Changing them is a decision about the forcing method, not about the parameters.']) + '</ul>')

    css = ('body{font-family:sans-serif;max-width:1400px;margin:1em auto;padding:0 1em;font-size:14px}table{border-collapse:collapse;'
           'margin:.5em 0;font-size:12px}th,td{border:1px solid #bbb;padding:2px 6px;text-align:right}th:first-child,td:first-child,'
           'td:nth-child(2){text-align:left}figure{margin:1em 0}img{max-width:100%}figcaption{font-size:12px;color:#444}'
           '.note{font-size:12px;color:#555}')
    out = f'{a.dir}/report.html'
    with open(out, 'w') as fh:
        fh.write(f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Block structure</title><style>{css}</style></head>'
                 f'<body>{"".join(parts)}</body></html>')
    print(f'wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
