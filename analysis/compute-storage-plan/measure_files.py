#!/usr/bin/env python3
"""Measure the 5 arcmin files of a smoke run: storage per variable, and what compression, precision and chunking
do to size and to write/read time. Files under runs/ are only read; every test works on copies in
scratch/compute-storage-plan/ and removes its own test output after measuring it.

Steps (tables under workdir/analysis/compute-storage-plan/tables/):
  storage   h5ls -v of the daily, monthly and state file of the run -> variable_storage.csv
  copy      copy the three files to scratch (timed) -> copy_times.csv
  sample    netCDF4 write/read tests on a sample of the daily and monthly copies (daily: 62 days, January and
            July; monthly: January and July), one file per setting -> compression_samples.csv and
            compression_samples_by_variable.csv
  lossy     error statistics of the rounding settings (GranularBitRound) per variable on the same samples ->
            compression_lossy.csv
  fullfile  nccopy of the whole copies (daily, monthly: zlib 1/4 with shuffle; state: zlib 1/4/9, lossless only
            because a restart must reproduce the run) -> compression_fullfile.csv

Usage: measure_files.py [--steps storage,copy,sample,fullfile]
"""
import argparse, csv, os, re, shutil, socket, subprocess, sys, time

import netCDF4
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csp   # noqa: E402

DAILY_STEPS = list(range(0, 31)) + list(range(181, 212))   # January and July of a non-leap year
MONTHLY_STEPS = [0, 6]

# name -> settings of the netCDF4 writer; 'vic' chunks = the chunking VIC wrote (netCDF default, one time step)
VARIANTS = {
    'zlib0':               dict(level=0, shuffle=False, dtype='f4', chunks='vic'),
    'zlib1-shuffle':       dict(level=1, shuffle=True, dtype='f4', chunks='vic'),
    'zlib2-shuffle (VIC)': dict(level=2, shuffle=True, dtype='f4', chunks='vic'),
    'zlib4-shuffle':       dict(level=4, shuffle=True, dtype='f4', chunks='vic'),
    'zlib6-shuffle':       dict(level=6, shuffle=True, dtype='f4', chunks='vic'),
    'zlib9-shuffle':       dict(level=9, shuffle=True, dtype='f4', chunks='vic'),
    'zlib2-noshuffle':     dict(level=2, shuffle=False, dtype='f4', chunks='vic'),
    'zlib4-noshuffle':     dict(level=4, shuffle=False, dtype='f4', chunks='vic'),
    'zlib2-shuffle-f64':   dict(level=2, shuffle=True, dtype='f8', chunks='vic'),
    'zlib4-shuffle-chunk-field':  dict(level=4, shuffle=True, dtype='f4', chunks=(1, 1680, 4320)),
    'zlib4-shuffle-chunk-small':  dict(level=4, shuffle=True, dtype='f4', chunks=(1, 210, 540)),
    'zlib4-shuffle-chunk-31days': dict(level=4, shuffle=True, dtype='f4', chunks=(31, 210, 540), daily_only=True),
    'zlib4-shuffle-gbr4':  dict(level=4, shuffle=True, dtype='f4', chunks='vic', quantize=('GranularBitRound', 4)),
    'zlib4-shuffle-gbr3':  dict(level=4, shuffle=True, dtype='f4', chunks='vic', quantize=('GranularBitRound', 3)),
    'zstd3-shuffle':       dict(level=3, shuffle=True, dtype='f4', chunks='vic', compression='zstd'),
}
FULLFILE = {'daily': [('zlib1-shuffle', ['-d', '1', '-s']), ('zlib4-shuffle', ['-d', '4', '-s'])],
            'monthly': [('zlib1-shuffle', ['-d', '1', '-s']), ('zlib4-shuffle', ['-d', '4', '-s'])],
            'state': [('zlib1-shuffle', ['-d', '1', '-s']), ('zlib4-shuffle', ['-d', '4', '-s']),
                      ('zlib9-shuffle', ['-d', '9', '-s'])]}


def run_dir():
    return f'{csp.workdir()}/{csp.SMOKE_RUNS[csp.SIZE_RUN]}'


def write_csv(name, rows):
    path = f'{csp.tables()}/{name}'
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f'wrote {path} ({len(rows)} rows)', flush=True)


# ------------------------------------------------------------------------------------------------ storage
def h5_storage(path):
    """{dataset: dict(shape, chunks, logical, allocated, type, filters)} from `h5ls -v -r`."""
    out = subprocess.run(['h5ls', '-v', '-r', path], capture_output=True, text=True, check=True).stdout
    res, cur = {}, None
    for line in out.splitlines():
        m = re.match(r'^/(\S+)\s+Dataset \{([^}]*)\}', line)
        if m:
            cur = m.group(1)
            res[cur] = dict(shape=m.group(2).replace(' ', ''), chunks='', logical=0, allocated=0, type='', filters='')
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith('Chunks:'):
            res[cur]['chunks'] = s.split('{')[1].split('}')[0].replace(' ', '') if '{' in s else ''
        elif s.startswith('Storage:'):
            m = re.search(r'(\d+) logical bytes, (\d+) allocated bytes', s)
            if m:
                res[cur]['logical'], res[cur]['allocated'] = int(m.group(1)), int(m.group(2))
        elif s.startswith('Type:'):
            res[cur]['type'] = s.split(':', 1)[1].strip()
        elif s.startswith('Filter-'):
            res[cur]['filters'] += s.split(':', 1)[1].split('OPT')[0].strip() + ' '
    return res


def step_storage():
    rows = []
    for kind, rel in csp.SIZE_FILES.items():
        path = f'{run_dir()}/{rel}'
        size = os.path.getsize(path)
        for var, d in h5_storage(path).items():
            rows.append(dict(run=csp.SIZE_RUN, file=kind, path=f'{csp.SMOKE_RUNS[csp.SIZE_RUN]}/{rel}',
                             file_bytes=size, variable=var, shape=d['shape'], chunks=d['chunks'], type=d['type'],
                             filters=d['filters'].strip(), logical_bytes=d['logical'],
                             allocated_bytes=d['allocated']))
    write_csv('variable_storage.csv', rows)


# ------------------------------------------------------------------------------------------------ copy
def copies():
    return {k: f'{csp.scratch()}/copies/{os.path.basename(v)}' for k, v in csp.SIZE_FILES.items()}


def step_copy():
    os.makedirs(f'{csp.scratch()}/copies', exist_ok=True)
    rows = []
    for kind, rel in csp.SIZE_FILES.items():
        src, dst = f'{run_dir()}/{rel}', copies()[kind]
        t = time.time(); shutil.copyfile(src, dst); dt = time.time() - t
        rows.append(dict(file=kind, bytes=os.path.getsize(dst), seconds=round(dt, 1),
                         mb_per_s=round(os.path.getsize(dst) / dt / 1e6, 1), host=socket.gethostname()))
        print(rows[-1], flush=True)
    write_csv('copy_times.csv', rows)


# ------------------------------------------------------------------------------------------------ sample
def spatial_vars(ds):
    return [v for v, x in ds.variables.items()
            if x.dimensions and x.dimensions[0] == 'time' and 'lat' in x.dimensions and 'lon' in x.dimensions]


def load_sample(path, steps):
    """{var: (array with fill values kept, dims, source chunking, fill value, attributes)} for the sample steps."""
    out = {}
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        for v in spatial_vars(ds):
            x = ds.variables[v]
            out[v] = (x[steps], x.dimensions, x.chunking(), x.getncattr('_FillValue'),
                      {a: x.getncattr(a) for a in x.ncattrs() if a != '_FillValue'})
        dims = {d: (None if ds.dimensions[d].isunlimited() else len(ds.dimensions[d])) for d in ds.dimensions}
    return out, dims


def chunks_for(spec, dims_of_var, src_chunks, shape):
    if spec == 'vic':
        return list(src_chunks) if src_chunks != 'contiguous' else None
    t, y, x = spec
    c = [1] * len(dims_of_var)
    c[0] = min(t, shape[0]); c[-2] = y; c[-1] = x
    return c


def write_variant(path, sample, dims, s):
    t0 = time.time()
    with netCDF4.Dataset(path, 'w', format='NETCDF4') as ds:
        for d, n in dims.items():
            ds.createDimension(d, n)
        for v, (a, vdims, src_chunks, fill, attrs) in sample.items():
            kw = dict(zlib=False)
            if s['level'] > 0:
                kw = dict(compression=s.get('compression', 'zlib'), complevel=s['level'], shuffle=s['shuffle'])
            if 'quantize' in s:
                kw.update(quantize_mode=s['quantize'][0], significant_digits=s['quantize'][1])
            c = chunks_for(s['chunks'], vdims, src_chunks, a.shape)
            x = ds.createVariable(v, s['dtype'], vdims, fill_value=np.array(fill).astype(s['dtype']),
                                  chunksizes=c, **kw)
            x.set_auto_mask(False)
            x[:] = a.astype(s['dtype'])
    return time.time() - t0


def read_all(path):
    t0 = time.time()
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        for v in ds.variables:
            ds.variables[v][:]
    return time.time() - t0


def lossy_error(path, sample):
    """Largest relative and absolute difference over valid values (lossy variants)."""
    rel = ab = 0.0
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        for v, (a, _, _, fill, _) in sample.items():
            b = ds.variables[v][:].astype('f8'); a8 = a.astype('f8')
            ok = (a != fill) & np.isfinite(a8) & (np.abs(a8) < 1e30)
            if not ok.any():
                continue
            d = np.abs(b[ok] - a8[ok]); ab = max(ab, float(d.max()))
            nz = np.abs(a8[ok]) > 0
            if nz.any():
                rel = max(rel, float((d[nz] / np.abs(a8[ok][nz])).max()))
    return rel, ab


def step_sample():
    tmp = f'{csp.scratch()}/sample'; os.makedirs(tmp, exist_ok=True)
    rows, by_var = [], []
    for kind, steps, per_year in (('daily', DAILY_STEPS, 365), ('monthly', MONTHLY_STEPS, 12)):
        sample, dims = load_sample(copies()[kind], steps)
        print(f'{kind}: {len(sample)} variables, {len(steps)} steps loaded', flush=True)
        for name, s in VARIANTS.items():
            if s.get('daily_only') and kind != 'daily':
                continue
            path = f'{tmp}/{kind}_{re.sub(r"[^a-z0-9-]", "", name)}.nc'
            wt = write_variant(path, sample, dims, s)
            size = os.path.getsize(path)
            rt = read_all(path)
            rel, ab = lossy_error(path, sample) if 'quantize' in s else (0.0, 0.0)
            rows.append(dict(file=kind, variant=name, level=s['level'], shuffle=s['shuffle'], dtype=s['dtype'],
                             compression=s.get('compression', 'zlib' if s['level'] else 'none'),
                             chunks=str(s['chunks']), quantize=str(s.get('quantize', '')),
                             sample_steps=len(steps), steps_per_year=per_year, sample_bytes=size,
                             bytes_per_year=round(size * per_year / len(steps)), write_s=round(wt, 1),
                             read_s=round(rt, 1), write_s_per_year=round(wt * per_year / len(steps), 1),
                             read_s_per_year=round(rt * per_year / len(steps), 1),
                             max_rel_error=rel, max_abs_error=ab, host=socket.gethostname()))
            print(rows[-1], flush=True)
            for v, d in h5_storage(path).items():
                if v in sample:
                    by_var.append(dict(file=kind, variant=name, variable=v, sample_steps=len(steps),
                                       allocated_bytes=d['allocated'],
                                       bytes_per_year=round(d['allocated'] * per_year / len(steps))))
            os.remove(path)
    write_csv('compression_samples.csv', rows)
    write_csv('compression_samples_by_variable.csv', by_var)


def lossy_stats(path, sample):
    """Per variable: largest relative error over values with |x| >= 1e-3 (mm or m3 s-1), 99.9th percentile of the
    relative error over non-zero values, largest absolute error, and the share of non-zero values that became zero."""
    rows = []
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        for v, (a, _, _, fill, _) in sample.items():
            b = ds.variables[v][:].astype('f8'); a8 = a.astype('f8')
            ok = (a != fill) & np.isfinite(a8) & (np.abs(a8) < 1e30)
            x, y = a8[ok], b[ok]
            d = np.abs(y - x); nz = x != 0
            rel = d[nz] / np.abs(x[nz])
            big = np.abs(x) >= 1e-3
            rows.append(dict(variable=v, values=int(ok.sum()), max_abs_error=float(d.max()) if d.size else 0.0,
                             max_rel_error_above_1e3=float((d[big] / np.abs(x[big])).max()) if big.any() else 0.0,
                             p999_rel_error=float(np.percentile(rel, 99.9)) if rel.size else 0.0,
                             nonzero_to_zero_share=float(((y == 0) & nz).sum() / max(1, nz.sum()))))
    return rows


def step_lossy():
    tmp = f'{csp.scratch()}/lossy'; os.makedirs(tmp, exist_ok=True)
    rows = []
    for kind, steps in (('daily', DAILY_STEPS), ('monthly', MONTHLY_STEPS)):
        sample, dims = load_sample(copies()[kind], steps)
        for name, s in VARIANTS.items():
            if 'quantize' not in s:
                continue
            path = f'{tmp}/{kind}_{re.sub(r"[^a-z0-9-]", "", name)}.nc'
            write_variant(path, sample, dims, s)
            for r in lossy_stats(path, sample):
                rows.append(dict(file=kind, variant=name, **r))
                print(rows[-1], flush=True)
            os.remove(path)
    write_csv('compression_lossy.csv', rows)


# ------------------------------------------------------------------------------------------------ fullfile
def step_fullfile():
    tmp = f'{csp.scratch()}/fullfile'; os.makedirs(tmp, exist_ok=True)
    rows = []
    for kind, settings in FULLFILE.items():
        src = copies()[kind]
        rows.append(dict(file=kind, variant='as written by VIC', bytes=os.path.getsize(src), seconds='',
                         read_s=round(read_all(src), 1), host=socket.gethostname()))
        for name, args in settings:
            dst = f'{tmp}/{kind}_{name}.nc'
            t0 = time.time()
            subprocess.run(['nccopy'] + args + [src, dst], check=True)
            dt = time.time() - t0
            rows.append(dict(file=kind, variant=name, bytes=os.path.getsize(dst), seconds=round(dt, 1),
                             read_s=round(read_all(dst), 1), host=socket.gethostname()))
            print(rows[-1], flush=True)
            os.remove(dst)
    write_csv('compression_fullfile.csv', rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--steps', default='storage,copy,sample,lossy,fullfile')
    a = ap.parse_args()
    print(f'netCDF4 {netCDF4.__version__}, netCDF-C {netCDF4.__netcdf4libversion__}, '
          f'HDF5 {netCDF4.__hdf5libversion__}, host {socket.gethostname()}', flush=True)
    for step in a.steps.split(','):
        t = time.time()
        {'storage': step_storage, 'copy': step_copy, 'sample': step_sample, 'lossy': step_lossy,
         'fullfile': step_fullfile}[step]()
        print(f'step {step}: {time.time() - t:.0f} s', flush=True)


if __name__ == '__main__':
    main()
