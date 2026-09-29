#!/usr/bin/env python3
"""Write per-batch transfer lists (paths relative to the DKRZ root) from an inventory CSV.

Batches (project transfer policy; the approval of a batch is recorded in
manifests/inputs/, not here):
  1  all non-atmosphere priority A and B files, plus geo_conditions soil and lakes
  2  EC-Earth3-ESM-1-1, 7 VIC variables, QA decades (esm-hist 2011-2020, esm-scen7-* 2022-2030)
  3  EC-Earth3-ESM-1-1, 7 VIC variables, esm-hist, esm-scen7-vl, esm-scen7-h (remaining decades)
  4  EC-Earth3-ESM-1-1, 7 VIC variables, esm-picontrol
  5  other GCMs, 7 VIC variables, all scenarios
  6  priority B atmosphere variables (prsn, tasmin, tasmax), all GCMs

Outputs per batch: batch_<n>_files.txt (one relative path per line) and
batch_<n>_expected_sizes.tsv (size, mtime, path, link target).
"""
import argparse, csv, os

VIC = {'tas', 'pr', 'ps', 'huss', 'rsds', 'rlds', 'sfcwind'}
FIRST_GCM = 'EC-Earth3-ESM-1-1'


def assign(rows, root):
    b = {k: [] for k in range(1, 7)}
    for r in rows:
        if r['dataset'] == 'SecondaryInputData':
            continue
        if r['dataset'] != 'atmosphere':
            if r['priority'] in 'AB' or (r['dataset'] == 'geo_conditions' and r['subset'] in ('soil', 'lakes')):
                b[1].append(r)
            continue
        var = r['subset']; first = r['gcm_or_res'] == FIRST_GCM
        qa_decade = ('esm-hist' in r['path'] and '_2011_2020' in r['path']) or \
                    ('esm-scen7' in r['path'] and '_2022_2030' in r['path'])
        if first and var in VIC:
            if qa_decade: b[2].append(r)
            elif r['scenario'] in ('esm-hist', 'esm-scen7-vl', 'esm-scen7-h'): b[3].append(r)
            elif r['scenario'] == 'esm-picontrol': b[4].append(r)
        elif (not first) and var in VIC:
            b[5].append(r)
        elif r['priority'] == 'B':
            b[6].append(r)
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--inventory', required=True, help='dkrz_isimip4b_inventory_<date>.csv from build_inventory.py')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--dkrz-root', default='/work/bb0820/ISIMIP/ISIMIP4b/')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    rows = list(csv.DictReader(open(a.inventory)))
    rel = lambda r: r['path'][len(a.dkrz_root):] if r['path'].startswith(a.dkrz_root) else r['path']
    for k, lst in assign(rows, a.dkrz_root).items():
        lst = sorted(lst, key=lambda r: r['path'])
        with open(f'{a.out_dir}/batch_{k}_files.txt', 'w') as fh:
            for r in lst: fh.write(rel(r) + '\n')
        with open(f'{a.out_dir}/batch_{k}_expected_sizes.tsv', 'w') as fh:
            for r in lst: fh.write(f"{r['size_bytes']}\t{r['mtime']}\t{rel(r)}\t{r['link_target']}\n")
        print(f'batch {k}: {len(lst)} files, {sum(int(r["size_bytes"]) for r in lst) / 1e9:.1f} GB')


if __name__ == '__main__':
    main()
