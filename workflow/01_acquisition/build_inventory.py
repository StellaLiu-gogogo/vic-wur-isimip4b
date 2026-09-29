#!/usr/bin/env python3
"""Build the DKRZ ISIMIP4b water_global input-data inventory (sizes, dates, priorities).

Input : a listing made on DKRZ levante with
            find <dkrz-root> -printf "%y\\t%s\\t%TY-%Tm-%Td\\t%p\\t%l\\n"
        with optional section markers '#SECONDARY', '#GEO_DEREF', '#SOC_DEREF',
        '#OUTPUT', '#UPLOAD'. Sizes of directory symlinks are resolved from any
        'dkrz_deref_*.tsv' listing (find -L) in the same directory.
Output: <out-dir>/dkrz_isimip4b_inventory_<date>.csv (one row per file) and .md (summaries).

Priority rules: A = VIC-WUR reads it, B = useful for QA or documentation,
C = do not transfer. They encode the VIC-WUR forcing set (7 atmospheric
variables, land use, population, reservoirs, land-sea mask) and are the
project's transfer policy; change them here, not in batch lists.

Read-only with respect to the data: it only writes into --out-dir. The
accepted inventory of a transfer is copied to manifests/inputs/ (see the
stage README); exploratory runs write to $ISIMIP4B_WORKDIR/scratch/.
"""
import argparse, collections, csv, datetime, glob, os, re

VIC_VARS = {'tas', 'pr', 'ps', 'huss', 'rsds', 'rlds', 'sfcwind'}
QA_VARS = {'prsn', 'tasmin', 'tasmax'}
ATM_VARS = ['tas', 'tasmin', 'tasmax', 'pr', 'prsn', 'hurs', 'huss', 'ps', 'rlds', 'rsds', 'sfcwind']


def classify(p, root):
    """Return (dataset, subset, scenario, gcm_or_res, vic_use, priority) for one DKRZ path."""
    rel = p[len(root):] if p.startswith(root) else p
    parts = rel.split('/')
    if rel.startswith('InputData/climate/atmosphere/bias-adjusted'):
        scen = parts[6] if len(parts) > 6 else ''
        gcm = parts[7] if len(parts) > 7 else ''
        m = re.search(r'_(tas|tasmin|tasmax|pr|prsn|hurs|huss|ps|rlds|rsds|sfcwind)_global_', p)
        var = m.group(1) if m else ''
        if var in VIC_VARS: use, pri = 'VIC reads (7 met vars)', 'A'
        elif var in QA_VARS: use, pri = 'not read; QA of rain/snow split', 'B'
        elif var == 'hurs': use, pri = 'not read (huss used)', 'C'
        else: use, pri = 'n/a', 'C'
        return ('atmosphere', var, scen, gcm, use, pri)
    if rel.startswith('InputData/climate/atmosphere_composition'):
        gas = parts[3]
        return ('atmosphere_composition', gas, parts[4] if len(parts) > 4 else '', '',
                'not read (no CO2 response); documentation' if gas in ('co2', 'ch4') else 'not relevant (o3)',
                'B' if gas in ('co2', 'ch4') else 'C')
    if rel.startswith('InputData/socioeconomic/landuse'):
        m = re.search(r'landuse-([a-z0-9-]+)_([a-z0-9]+)_(\d+arcmin)_', p)
        ds, soc, res = (m.group(1), m.group(2), m.group(3)) if m else ('?', parts[3], '?')
        if ds in ('totals', '15crops', 'urbanareas', 'pastures'):
            use = 'landuse->coverage converter (required DHF)'
            pri = 'A' if res == '15arcmin' else 'B'
        else:
            use, pri = 'not used (5crops/forests/subgroups)', 'C'
        return ('landuse-' + ds, res, soc, '', use, pri)
    if rel.startswith('InputData/socioeconomic/population'):
        m = re.search(r'_(\d+arcmin)_', p); res = m.group(1) if m else ('national' if p.endswith('.csv') else '?')
        soc = parts[3] if len(parts) > 3 else ''
        if res == '5arcmin': use, pri = 'downscaling proxy for water demand', 'A'
        elif res == 'national': use, pri = 'QA / country totals', 'B'
        else: use, pri = 'not used', 'C'
        return ('population', res, soc, '', use, pri)
    if rel.startswith('InputData/socioeconomic/gdp') or rel.startswith('InputData/socioeconomic/fixed-assets'):
        m = re.search(r'_(\d+arcmin)_', p); res = m.group(1) if m else ('national' if p.endswith('.csv') else '?')
        soc = parts[3] if len(parts) > 3 else ''
        return (parts[2], res, soc, '', 'not used by VIC-WUR', 'B' if res == 'national' else 'C')
    if rel.startswith('InputData/socioeconomic/reservoirs_dams'):
        return ('reservoirs_dams', parts[-1].split('.')[-1], parts[3] if len(parts) > 3 else '', '',
                'dam parameter chain (if DAMS used)', 'A')
    if rel.startswith('InputData/socioeconomic/'):
        return (parts[2], '', parts[3] if len(parts) > 3 else '', '', 'not used (no N cycle / wood harvest)', 'C')
    if rel.startswith('InputData/geo_conditions'):
        sub = parts[2] if len(parts) > 2 else ''
        pri = {'landseamask': 'A', 'river_routing': 'B', 'countrymasks': 'B', 'soil': 'C', 'lakes': 'C'}.get(sub, 'C')
        use = {'landseamask': 'submission mask', 'river_routing': 'DDM30 outlet cross-check for dis',
               'countrymasks': 'QA / country aggregation', 'soil': 'not used (own soil)',
               'lakes': 'not used (LAKES FALSE)'}.get(sub, '')
        return ('geo_conditions', sub, '', '', use, pri)
    if rel.startswith('SecondaryInputData'):
        return ('SecondaryInputData', '/'.join(parts[1:3]), '', '', 'inventory only', 'C')
    return ('other', '', '', '', '', 'C')


def read_listing(listing, root):
    rows, geo_deref, outputs, section = [], {}, [], 'input'
    deref_files = [listing] + sorted(glob.glob(os.path.join(os.path.dirname(listing) or '.', 'dkrz_deref_*.tsv')))
    for line in (l for fn in deref_files for l in open(fn)):
        line = line.rstrip('\n')
        if not line or line.startswith('#type'):
            continue
        if line.startswith('#SECONDARY'): section = 'secondary'; continue
        if line.startswith('#GEO_DEREF') or line.startswith('#SOC_DEREF'): section = 'geo'; continue
        if line.startswith('#UPLOAD') or line.startswith('#OUTPUT'): section = 'output'; continue
        f = line.split('\t')
        if section == 'geo':
            if len(f) >= 3: geo_deref[f[2]] = (int(f[0]), f[1])
            continue
        if section == 'output':
            outputs.append(line); continue
        if len(f) < 4 or f[0] not in ('f', 'l'):
            continue
        typ, size, mtime, path = f[0], int(f[1]), f[2], f[3]; link = f[4] if len(f) > 4 else ''
        ds, sub, scen, gcm, use, pri = classify(path, root)
        rows.append(dict(path=path, type=typ, size_bytes=size, mtime=mtime, link_target=link, dataset=ds, subset=sub,
                         scenario=scen, gcm_or_res=gcm, vic_use=use, priority=pri))
    for r in rows:  # resolve symlink sizes from the -L listing
        if r['type'] == 'l':
            for p, (sz, mt) in geo_deref.items():
                if p == r['path'] or p.startswith(r['path'] + '/'):
                    r['size_bytes'] = sz; r['mtime'] = mt; break
    return rows, outputs


def write_summary(rows, outputs, root, date, path):
    gb = lambda b: b / 1e9
    agg = collections.OrderedDict()
    for r in rows:
        key = (r['dataset'], r['subset'] if r['dataset'] != 'atmosphere' else '', r['scenario'], r['gcm_or_res'], r['priority'])
        a = agg.setdefault(key, dict(n=0, bytes=0, smin=None, smax=0, dmin=None, dmax=None))
        a['n'] += 1; a['bytes'] += r['size_bytes']; a['smax'] = max(a['smax'], r['size_bytes'])
        a['smin'] = r['size_bytes'] if a['smin'] is None else min(a['smin'], r['size_bytes'])
        a['dmin'] = r['mtime'] if a['dmin'] is None else min(a['dmin'], r['mtime'])
        a['dmax'] = r['mtime'] if a['dmax'] is None else max(a['dmax'], r['mtime'])
    tot, cnt = collections.Counter(), collections.Counter()
    for r in rows:
        tot[r['priority']] += r['size_bytes']; cnt[r['priority']] += 1
    md = [f'# DKRZ ISIMIP4b input-data inventory for water_global ({date})', '',
          f'Source: `find` on levante `{root}` ({date}). Sizes in GB (1e9 bytes).', '',
          '## Totals by priority', '', '| priority | files | GB | TB |', '|---|---|---|---|']
    for p in ['A', 'B', 'C']:
        md.append(f'| {p} | {cnt[p]} | {gb(tot[p]):.1f} | {gb(tot[p]) / 1000:.2f} |')
    allb = sum(tot.values())
    md.append(f'| **all** | {sum(cnt.values())} | {gb(allb):.1f} | {gb(allb) / 1000:.2f} |')
    md.append(f'| **A+B** | {cnt["A"] + cnt["B"]} | {gb(tot["A"] + tot["B"]):.1f} | {gb(tot["A"] + tot["B"]) / 1000:.2f} |')
    md += ['', '## Dataset x scenario x GCM/resolution', '',
           '| dataset | subset | scenario | GCM / resolution | priority | files | GB | file size range (MB) | mtime range |',
           '|---|---|---|---|---|---|---|---|---|']
    for (ds, sub, scen, gcm, pri), a in sorted(agg.items(), key=lambda kv: (kv[0][4], kv[0][0], kv[0][2], kv[0][3], kv[0][1])):
        md.append(f'| {ds} | {sub} | {scen} | {gcm} | {pri} | {a["n"]} | {gb(a["bytes"]):.2f} | '
                  f'{a["smin"] / 1e6:.1f}-{a["smax"] / 1e6:.1f} | {a["dmin"]}..{a["dmax"]} |')
    atm = collections.defaultdict(lambda: dict(n=0, bytes=0))
    for r in rows:
        if r['dataset'] == 'atmosphere':
            k = (r['gcm_or_res'], r['scenario'], r['subset']); atm[k]['n'] += 1; atm[k]['bytes'] += r['size_bytes']
    md += ['', '## Atmosphere: GCM x scenario x variable (GB)', '',
           '| GCM | scenario | ' + ' | '.join(ATM_VARS) + ' | total |', '|---|---|' + '---|' * (len(ATM_VARS) + 1)]
    for g in sorted({k[0] for k in atm}):
        for s in sorted({k[1] for k in atm if k[0] == g}):
            vals = [atm[(g, s, v)]['bytes'] for v in ATM_VARS]
            md.append(f'| {g} | {s} | ' + ' | '.join(f'{gb(x):.1f}' for x in vals) + f' | {gb(sum(vals)):.1f} |')
    md += ['', '## OutputData / UploadArea (depth<=3)', '', '```'] + outputs[:80] + ['```']
    open(path, 'w').write('\n'.join(md) + '\n')
    return md


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--listing', required=True, help='find listing made on DKRZ (dkrz_find_raw_<date>.tsv)')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--dkrz-root', default='/work/bb0820/ISIMIP/ISIMIP4b/')
    ap.add_argument('--date', default=datetime.date.today().isoformat(), help='inventory date (default: today)')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    rows, outputs = read_listing(a.listing, a.dkrz_root)
    if not rows:
        raise SystemExit('no file rows found in the listing')
    with open(f'{a.out_dir}/dkrz_isimip4b_inventory_{a.date}.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    md = write_summary(rows, outputs, a.dkrz_root, a.date, f'{a.out_dir}/dkrz_isimip4b_inventory_{a.date}.md')
    print('\n'.join(md[:12])); print('rows', len(rows))


if __name__ == '__main__':
    main()
