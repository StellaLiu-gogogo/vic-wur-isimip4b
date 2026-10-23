"""Shared parts of the verifiers of the adopted components (domain, routing, irrigation, water_use) of a parameter
set: the manifest entry of a component, the integrity of its files against the manifest, the domain grid, the QC
directory, and the report and summary.

The verifiers never change a parameter file or the manifest: they write only their QC directory
qc/parameters/<status>/<set>/<component>/{summary.json,reports/verify.json,figures/}. A verifier run from a
repository that is not clean keeps its results in scratch/adopted-parameter-qc/verify-uncommitted/qc/... (contract,
rule 14); the qc_status of the component in the manifest is changed by hand, after review, from a committed run.

Check statuses are those of common/qc.py, plus `not_applicable` for a check that the file cannot support (it is
listed in the report and the summary but does not enter the combined status).
"""
import argparse, datetime, json, os

import numpy as np
import netCDF4 as nc
import yaml

from common import gitstate, hashing, provenance, qc as qcm, workdir

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRATCH = 'scratch/adopted-parameter-qc'
DEFAULT_SET = 'vic-global-5arcmin-version-a'
DOMAIN = 'domain/vic_global_5min_domain_nogl.nc'
NOT_APPLICABLE = 'not_applicable'


def manifest_path(parameter_set):
    return f'{REPO}/manifests/parameters/{parameter_set}.yaml'


def manifest(parameter_set):
    with open(manifest_path(parameter_set)) as fh:
        return yaml.safe_load(fh)


def raw(ds, name, idx=None):
    """Stored values of a variable (no masking, no scaling)."""
    v = ds[name]; v.set_auto_maskandscale(False)
    return np.asarray(v[:] if idx is None else v[idx])


def fill_value(var):
    return getattr(var, '_FillValue', None)


def is_fill(values, fill):
    """Cells holding the fill value (NaN counts as fill for a NaN fill value and for float data)."""
    values = np.asarray(values)
    bad = np.zeros(values.shape, bool)
    if values.dtype.kind == 'f':
        bad |= ~np.isfinite(values)
    if fill is not None and not (isinstance(fill, float) and np.isnan(fill)):
        bad |= values == fill
    return bad


def read_domain(path):
    """mask (bool, mask == 1), lat, lon, area (m2, float64) and frac of the domain file, stored values."""
    with nc.Dataset(path) as d:
        m = raw(d, 'mask')
        return {'mask_raw': m, 'mask': m == 1, 'lat': raw(d, 'lat'), 'lon': raw(d, 'lon'),
                'area': raw(d, 'area').astype('f8'), 'frac': raw(d, 'frac').astype('f8'),
                'area_fill': fill_value(d['area']), 'frac_fill': fill_value(d['frac'])}


def local_date(ts):
    return datetime.datetime.fromtimestamp(ts).date()


def as_date(x):
    return x if isinstance(x, datetime.date) else datetime.date.fromisoformat(str(x))


def file_integrity(pset_dir, entry, adopted_on):
    """Check `files` of a manifest component entry: md5 and size equal the manifest; the file was not changed after
    adoption (modification time not after the adoption day, the main file's modification day equal to source_mtime
    as the copy kept the source time; status-change time (ctime) not after the adoption day: a later ctime is a
    warning only, as changing permissions also sets it)."""
    adopted = as_date(entry.get('adopted_on', adopted_on))
    files = []; failed = warn = False
    for i, f in enumerate(entry['files']):
        p = f'{pset_dir}/{f["path"]}'
        rec = {'path': f['path']}
        if not os.path.exists(p):
            rec['problem'] = 'missing'; files.append(rec); failed = True
            continue
        st = os.stat(p)
        md5 = hashing.md5(p)
        rec |= {'md5': md5, 'md5_manifest': f.get('md5'), 'size_bytes': st.st_size,
                'size_manifest': f.get('size_bytes'), 'mtime': local_date(st.st_mtime).isoformat(),
                'ctime': local_date(st.st_ctime).isoformat()}
        problems = []
        if f.get('md5') is None or md5 != f['md5']:
            problems.append('md5 differs from the manifest')
        if f.get('size_bytes') is not None and st.st_size != f['size_bytes']:
            problems.append('size differs from the manifest')
        if local_date(st.st_mtime) > adopted:
            problems.append('modified after adoption')
        if i == 0 and entry.get('source_mtime') is not None and \
                local_date(st.st_mtime) != as_date(entry['source_mtime']):
            problems.append('modification day differs from source_mtime')
        if problems:
            failed = True
        if local_date(st.st_ctime) > adopted:
            rec['warning'] = 'status change (ctime) after adoption'; warn = True
        rec['problems'] = problems
        files.append(rec)
    status = 'failed' if failed else 'warning' if warn else 'passed'
    return {'adopted_on': adopted.isoformat(), 'files': files, 'status': status}


def latlon_check(ds, dom):
    eq = {c: bool(np.array_equal(raw(ds, c), dom[c])) for c in ('lat', 'lon')}
    return {**eq, 'status': 'passed' if all(eq.values()) else 'failed'}


def variables_check(ds, reads, lengths=None):
    """Every variable in `reads` {name: (dims, dtype kind or None)} is present with exactly these dimensions (the order
    VIC reads them) and dtype kind ('i' int, 'f' float); dimension lengths as given."""
    missing = [v for v in reads if v not in ds.variables]
    wrong_dims = {v: list(ds[v].dimensions) for v, (dims, _) in reads.items()
                  if v in ds.variables and tuple(ds[v].dimensions) != tuple(dims)}
    wrong_type = {v: str(ds[v].dtype) for v, (_, kind) in reads.items()
                  if v in ds.variables and kind and ds[v].dtype.kind != kind}
    got = {k: len(ds.dimensions[k]) for k in (lengths or {}) if k in ds.dimensions}
    bad_len = {k: (got.get(k), n) for k, n in (lengths or {}).items() if got.get(k) != n}
    ok = not (missing or wrong_dims or wrong_type or bad_len)
    return {'required': sorted(reads), 'missing': missing, 'wrong_dimensions': wrong_dims, 'wrong_dtype': wrong_type,
            'dimension_lengths': got, 'wrong_dimension_lengths': bad_len, 'status': 'passed' if ok else 'failed'}


def stats(values):
    """Summary statistics of a 1-d array of valid values."""
    v = np.asarray(values, 'f8')
    if v.size == 0:
        return {'n': 0}
    q = np.percentile(v, [1, 5, 25, 50, 75, 95, 99])
    return {'n': int(v.size), 'min': float(v.min()), 'max': float(v.max()), 'mean': float(v.mean()),
            **{f'p{p}': float(x) for p, x in zip((1, 5, 25, 50, 75, 95, 99), q)}}


class Run:
    """Command line, Git state and QC directory of one verifier run."""

    def __init__(self, component, description, extra_args=None):
        ap = argparse.ArgumentParser(description=description)
        ap.add_argument('--parameter-set', default=DEFAULT_SET)
        ap.add_argument('--parameter-status', default='candidates', choices=['candidates'])
        ap.add_argument('--expect-commit', default=None,
                        help='set by the submit script: stop unless the repository is clean at this commit')
        ap.add_argument('--qc-to-scratch', action='store_true',
                        help='set by the submit script when the repository was not clean: results go to scratch')
        for args, kw in (extra_args or []):
            ap.add_argument(*args, **kw)
        self.args = a = ap.parse_args()
        self.component = component
        self.W = W = workdir.root()
        self.commit, self.dirty = gitstate.state(REPO)
        if a.expect_commit and (self.dirty or self.commit != a.expect_commit):
            raise SystemExit(f'the job was submitted for commit {a.expect_commit} of a clean repository, but the '
                             f'repository is now at {self.commit} and {"not clean" if self.dirty else "clean"}; '
                             f'submit the job again')
        self.uncommitted = self.dirty or a.qc_to_scratch
        self.rel_pset = f'parameters/{a.parameter_status}/{a.parameter_set}'
        self.pset = f'{W}/{self.rel_pset}'
        self.qc = (f'{W}/{SCRATCH}/verify-uncommitted/qc/{self.rel_pset}/{component}' if self.uncommitted
                   else f'{W}/qc/{self.rel_pset}/{component}')
        os.makedirs(f'{self.qc}/reports', exist_ok=True)
        os.makedirs(f'{self.qc}/figures', exist_ok=True)
        self.manifest = manifest(a.parameter_set)

    def entry(self, key):
        return self.manifest['components'][key]

    def integrity(self, key):
        return file_integrity(self.pset, self.entry(key), self.manifest['adopted_on'])

    def finish(self, objects, checks, script):
        """Write reports/verify.json and summary.json; exit with the status of the combined checks."""
        status = qcm.combine([c['status'] for c in checks.values() if c['status'] != NOT_APPLICABLE])
        report = {'object': [os.path.relpath(f'{self.pset}/{o}', self.W) for o in objects],
                  'checked_at': provenance.utcnow(), 'status': status, 'checked_by': script,
                  'code_commit': self.commit, 'code_dirty': self.dirty,
                  'manifest': os.path.relpath(manifest_path(self.args.parameter_set), REPO), 'checks': checks}
        qcm.write_json(f'{self.qc}/reports/verify.json', json.loads(json.dumps(report, default=_plain)))
        qcm.write_summary(self.qc, {k: report[k] for k in ('object', 'checked_at', 'status', 'checked_by',
                                                           'code_commit', 'code_dirty')} |
                          {'checks': {k: v['status'] for k, v in checks.items()}} |
                          ({'note': 'verifier code not committed (repository not clean): results kept in scratch, '
                                    'the status of the component is unchanged'} if self.uncommitted else {}))
        print(json.dumps({k: v['status'] for k, v in checks.items()}), status)
        qcm.exit_with(status)


def _plain(x):
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)


def save_map(path, values, lat, lon, title, label, cmap='viridis', vmin=None, vmax=None, points=None):
    """A global map of a (lat, lon) field (NaN blank), optional points [(lon, lat, text)]."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 6), dpi=120)
    extent = (lon.min(), lon.max(), lat.min(), lat.max())
    img = values[::-1] if lat[0] < lat[-1] else values
    im = ax.imshow(img, extent=extent, cmap=cmap, vmin=vmin, vmax=vmax, interpolation='nearest', aspect='auto')
    for x, y, t in points or []:
        ax.plot(x, y, 'r^', ms=6)
        ax.annotate(t, (x, y), xytext=(4, 4), textcoords='offset points', fontsize=8, color='red')
    fig.colorbar(im, ax=ax, label=label, shrink=0.8)
    ax.set_title(title); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
