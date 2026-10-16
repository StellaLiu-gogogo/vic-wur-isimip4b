"""Source records of the dam component (decision D19): readers, ISIMIP4b-GDW crosswalk, purposes, SSP sites.

Readers
  read_gdw_barriers   GDW v1.0 barriers layer (raw/external/global-dam-watch/1.0/): attribute table (.dbf, encoding
                      from .cpg) and point geometry (.shp, shape type 1). The point is GDW's river location of the
                      dam (equal to LAT_RIV/LONG_RIV); LAT_DAM/LONG_DAM of the .dbf are 0 in most records and are not
                      used. Every reservoirs-layer record is also a barriers record with the same GDW_ID, so the
                      barriers layer is the only GDW table read. -99 means missing.
  read_isimip_histsoc ISIMIP4b reservoirs-dams histsoc workbook (.xlsx, read with the standard library: one sheet,
                      the header row holds YEAR and CAP_MCM).
  read_ssp            ISIMIP4b SSP future hydropower dams (WaterGAP2-2e csv).

Crosswalk (match_isimip_gdw), one to one, each GDW record used at most once:
  1. manual entries of the decisions file (gdw_id or ISIMIP coordinates);
  2. GRanD ID for ISIMIP records whose SOURCE is empty (GRanD-sourced) and whose ID is numeric: the GDW record with
     GRAND_ID == ID (nearest if several); pairs farther apart than REVIEW_KM or with a capacity ratio outside
     RATIO are matched but flagged for review;
  3. location: the nearest unused GDW record within MATCH_KM whose capacity ratio GDW/ISIMIP is within RATIO,
     nearest pairs first.
The code follows compare_gdw_isimip.py of the analysis task dam-distribution-review (promoted, task L) with
the barriers layer as the only GDW pool and the 2 km tier only.
"""
import os, re, struct, zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

EARTH_KM = 6371.0
MATCH_KM = 2.0
REVIEW_KM = 10.0
RATIO = (0.5, 2.0)
GDW_USE = ('USE_IRRI', 'USE_ELEC', 'USE_SUPP', 'USE_FCON', 'USE_RECR', 'USE_NAVI', 'USE_FISH', 'USE_PCON', 'USE_LIVE',
           'USE_OTHR')
SUPPLY_MAIN_USE = ('irrigation', 'water supply')
MISSING_TEXT = ('', 'na', 'nan', 'none')
SSP_RIVER_POWER = 2          # SystemID: 1 diversion canal power (no lake volume), 2 river power (with a reservoir)
SSP_SYSTEM = 'SystemID [1 DiversionalCanalPower.2.RiverPower]'
SSP_VOLUME = 'Lake volume [m3]'
SSP_AREA = 'DDM30/ISIMIP routing area [km2]'


# ------------------------------------------------------------------------------------------------------- readers
def read_dbf(path):
    """Attribute table of a shapefile (.dbf, dBASE III) as stripped strings, plus the column `deleted`."""
    cpg = path[:-4] + '.cpg'
    enc = 'latin-1'
    if os.path.exists(cpg):
        with open(cpg) as fh:
            enc = fh.read().strip()
    with open(path, 'rb') as fh:
        n, header_len, record_len = struct.unpack('<IHH', fh.read(32)[4:12])
        fields = []
        while True:
            d = fh.read(32)
            if d[0] == 0x0D:
                break
            fields.append((d[:11].split(b'\0')[0].decode('ascii'), d[16]))
        fh.seek(header_len)
        raw = fh.read(n * record_len)
    rows = []
    for i in range(n):
        rec = raw[i * record_len:(i + 1) * record_len]
        pos, row = 1, [rec[:1] == b'*']
        for _, width in fields:
            row.append(rec[pos:pos + width].decode(enc, errors='replace').strip())
            pos += width
        rows.append(row)
    return pd.DataFrame(rows, columns=['deleted'] + [f for f, _ in fields])


def read_shp_points(path):
    """(x, y) of every record of a point shapefile (shape type 1), in record order; stops on another shape type."""
    with open(path, 'rb') as fh:
        data = fh.read()
    shape_type = struct.unpack('<i', data[32:36])[0]
    if shape_type != 1:
        raise ValueError(f'{path}: shape type {shape_type}, expected 1 (point)')
    xs, ys, pos = [], [], 100
    while pos < len(data):
        _, words = struct.unpack('>ii', data[pos:pos + 8])
        st = struct.unpack('<i', data[pos + 8:pos + 12])[0]
        x, y = struct.unpack('<dd', data[pos + 12:pos + 28]) if st == 1 else (np.nan, np.nan)
        xs.append(x); ys.append(y)
        pos += 8 + 2 * words
    return np.array(xs), np.array(ys)


def _num(s):
    v = pd.to_numeric(s, errors='coerce')
    return v.where(v != -99)


def read_gdw_barriers(shp_dir):
    """GDW barriers layer: one row per record with numeric GDW_ID, GRAND_ID, CAP_MCM, YEAR_DAM, CATCH_SKM (NaN for
    -99 or <= 0 where a positive value is required), lat/lon of the point geometry and the purpose fields."""
    t = read_dbf(f'{shp_dir}/GDW_barriers_v1_0.dbf')
    x, y = read_shp_points(f'{shp_dir}/GDW_barriers_v1_0.shp')
    if len(x) != len(t):
        raise ValueError(f'GDW barriers: {len(x)} shapes, {len(t)} attribute records')
    t['lon'], t['lat'] = x, y
    t = t[~t.deleted].drop(columns='deleted').reset_index(drop=True)
    for c in ('GDW_ID', 'GRAND_ID', 'YEAR_DAM'):
        t[c] = _num(t[c])
    for c in ('CAP_MCM', 'CATCH_SKM', 'AREA_SKM', 'DAM_HGT_M'):
        v = _num(t[c]); t[c] = v.where(v > 0)
    t['GRAND_ID'] = t.GRAND_ID.where(t.GRAND_ID > 0)
    if t.GDW_ID.isna().any() or not t.GDW_ID.is_unique:
        raise ValueError('GDW barriers: GDW_ID missing or not unique')
    if not (np.isfinite(t.lat) & np.isfinite(t.lon)).all():
        raise ValueError('GDW barriers: records without a point geometry')
    t['GDW_ID'] = t.GDW_ID.astype(int)
    return t


def read_xlsx_table(path, header_keys=('YEAR', 'CAP_MCM')):
    """Data table of a one-sheet workbook: the first row holding all `header_keys` is the header; cell values as
    strings (shared strings resolved)."""
    z = zipfile.ZipFile(path)
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared = [''.join(x.text or '' for x in si.iter(f'{{{ns["m"]}}}t')) for si in root.findall('m:si', ns)]
    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows = []
    for row in root.iter(f'{{{ns["m"]}}}row'):
        d = {}
        for cell in row.findall('m:c', ns):
            col = re.match(r'[A-Z]+', cell.get('r')).group(0)
            v = cell.find('m:v', ns)
            if v is not None:
                d[col] = shared[int(v.text)] if cell.get('t') == 's' else v.text
            elif cell.get('t') == 'inlineStr':
                d[col] = ''.join(x.text or '' for x in cell.iter(f'{{{ns["m"]}}}t'))
        rows.append(d)
    i = next(j for j, r in enumerate(rows) if all(k in r.values() for k in header_keys))
    cols = sorted(rows[i], key=lambda s: (len(s), s))
    return pd.DataFrame([[r.get(k) for k in cols] for r in rows[i + 1:]], columns=[rows[i][k] for k in cols])


def isimip_key(id_value, name):
    """Stable key of an ISIMIP4b histsoc record: the numeric ID, else 'name:<DAM_NAME>'."""
    return str(int(id_value)) if pd.notna(id_value) else f'name:{name}'


def read_isimip_histsoc(path):
    """ISIMIP4b histsoc dams: one row per dam (rows without CAP_MCM, e.g. notes below the table, are dropped);
    numeric columns coerced, `key` (isimip_key), `grand_sourced` (SOURCE empty: a GRanD record)."""
    t = read_xlsx_table(path)
    t['ID_text'] = t['ID'].astype(str)
    for c in ('ID', 'YEAR', 'FLAG_ART', 'CAP_MCM', 'LAT_ORIG', 'LON_ORIG', 'CATCH_SKM_GranD', 'CATCH_SKM_DDM30',
              'R_Area_km2', 'D_Hght_m'):
        t[c] = pd.to_numeric(t[c], errors='coerce')
    t = t.dropna(subset=['CAP_MCM']).reset_index(drop=True)
    t['row'] = np.arange(len(t))
    t['DAM_NAME'] = t.DAM_NAME.astype(str).str.strip()
    t['key'] = [isimip_key(i, n) for i, n in zip(t.ID, t.DAM_NAME)]
    if not t.key.is_unique:
        raise ValueError(f'ISIMIP histsoc: keys not unique: {t.key[t.key.duplicated()].tolist()}')
    t['grand_sourced'] = t.SOURCE.astype(str).str.strip().str.lower().isin(MISSING_TEXT) & t.ID.notna()
    for c in ('CATCH_SKM_GranD', 'CATCH_SKM_DDM30', 'R_Area_km2', 'D_Hght_m'):
        t[c] = t[c].where(t[c] > 0)
    return t


def read_ssp(path):
    t = pd.read_csv(path)
    t['row'] = np.arange(len(t))
    return t


# ------------------------------------------------------------------------------------------------------ geometry
def unit_vectors(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def great_circle_km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ----------------------------------------------------------------------------------------------------- crosswalk
def match_isimip_gdw(isi, gdw, manual=(), skip=(), match_km=MATCH_KM, review_km=REVIEW_KM, ratio=RATIO):
    """One row per ISIMIP record (index aligned with `isi`): gdw_row (row of `gdw` or -1), method, distance_km,
    capacity_ratio (GDW / ISIMIP), review (reason text, '' when none). `manual` is a list of dicts with `isimip`
    (key) and either `gdw_id` or `use: isimip_coordinates`; records whose key is in `skip` (combined into another
    record by the decisions file) are not matched (method 'combined')."""
    from scipy.spatial import cKDTree
    n = len(isi)
    out = pd.DataFrame({'gdw_row': np.full(n, -1), 'method': [''] * n, 'distance_km': np.nan,
                        'capacity_ratio': np.nan, 'review': [''] * n}, index=isi.index)
    used = set()
    by_key = {k: i for i, k in zip(isi.index, isi.key)}
    gdw_row_of_id = {int(g): j for j, g in zip(gdw.index, gdw.GDW_ID)}

    def pair(i, j, method):
        d = float(great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], gdw.at[j, 'lat'], gdw.at[j, 'lon']))
        cap = gdw.at[j, 'CAP_MCM']
        r = cap / isi.at[i, 'CAP_MCM'] if pd.notna(cap) and isi.at[i, 'CAP_MCM'] > 0 else np.nan
        out.loc[i, ['gdw_row', 'method', 'distance_km', 'capacity_ratio']] = [j, method, d, r]
        used.add(j)
        return d, r

    out.loc[isi.key.isin(list(skip)).to_numpy(), 'method'] = 'combined'
    for m in manual:
        if m['isimip'] not in by_key:
            raise ValueError(f'decisions file: unknown ISIMIP key {m["isimip"]!r}')
        i = by_key[m['isimip']]
        if 'gdw_id' in m:
            if int(m['gdw_id']) not in gdw_row_of_id:
                raise ValueError(f'decisions file: unknown GDW_ID {m["gdw_id"]}')
            j = gdw_row_of_id[int(m['gdw_id'])]
            if j in used:
                raise ValueError(f'decisions file: GDW_ID {m["gdw_id"]} given to two ISIMIP dams')
            pair(i, j, 'manual_gdw')
        elif m.get('use') == 'isimip_coordinates':
            out.at[i, 'method'] = 'manual_isimip_coordinates'
        else:
            raise ValueError(f'decisions file: manual location of {m["isimip"]} needs gdw_id or use: isimip_coordinates')

    grand = gdw[gdw.GRAND_ID.notna()]
    grand_rows = {}
    for j, g in zip(grand.index, grand.GRAND_ID.astype(int)):
        grand_rows.setdefault(g, []).append(j)
    for i in isi.index[(out.method == '') & isi.grand_sourced]:
        cands = [j for j in grand_rows.get(int(isi.at[i, 'ID']), []) if j not in used]
        if not cands:
            continue
        d = great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], gdw.loc[cands, 'lat'].to_numpy(),
                            gdw.loc[cands, 'lon'].to_numpy())
        dist, r = pair(i, cands[int(np.argmin(d))], 'grand_id')
        reasons = []
        if dist > review_km:
            reasons.append(f'distance > {review_km:g} km')
        if np.isfinite(r) and not ratio[0] <= r <= ratio[1]:
            reasons.append(f'capacity ratio outside [{ratio[0]:g}, {ratio[1]:g}]')
        out.at[i, 'review'] = '; '.join(reasons)

    todo = isi.index[out.method == '']
    free = gdw.index[~gdw.index.isin(used) & gdw.CAP_MCM.notna()]
    if len(todo) and len(free):
        tree = cKDTree(unit_vectors(gdw.loc[free, 'lat'], gdw.loc[free, 'lon']))
        chord = 2 * np.sin(match_km / EARTH_KM / 2)
        pairs = []
        for k, cands in enumerate(tree.query_ball_point(unit_vectors(isi.loc[todo, 'LAT_ORIG'], isi.loc[todo, 'LON_ORIG']),
                                                        chord)):
            i = todo[k]
            for c in cands:
                j = free[c]
                r = gdw.at[j, 'CAP_MCM'] / isi.at[i, 'CAP_MCM']
                if not ratio[0] <= r <= ratio[1]:
                    continue
                d = float(great_circle_km(isi.at[i, 'LAT_ORIG'], isi.at[i, 'LON_ORIG'], gdw.at[j, 'lat'], gdw.at[j, 'lon']))
                if d <= match_km:
                    pairs.append((d, i, j))
        done = set()
        for d, i, j in sorted(pairs):
            if i in done or j in used:
                continue
            pair(i, j, f'location_{match_km:g}km')
            done.add(i)
    out['gdw_row'] = out.gdw_row.astype(int)
    return out


# ------------------------------------------------------------------------------------------------- review rules
# Rules for the pairs flagged by the crosswalk (user, 2026-10-16); the decisions file may override single pairs.
DEPTH_BAND = (0.05, 1.0)        # plausible mean depth (capacity / surface area) as a fraction of the dam height
LAKE_CONTROL = ('yes', 'enlarged')
FIT_MAX = 1.5                   # upstream area within this factor of the catchment area


def capacity_rule(cap_isimip, cap_gdw, lake_ctrl, area_km2, height_m, band=DEPTH_BAND):
    """(choice 'isimip' or 'gdw', rule id, depth_isimip_m, depth_gdw_m) for a pair whose capacities differ.
    C1 a regulated natural lake (GDW LAKE_CTRL Yes or Enlarged): GDW, the volume the dam regulates (ISIMIP gives the
       volume of the whole lake);
    C2 the mean depth (capacity / surface area) is within [band[0], band[1]] x dam height for one source only: that
       source;
    C3 otherwise ISIMIP (D19)."""
    a = area_km2 if area_km2 and area_km2 > 0 else np.nan
    d_i, d_g = cap_isimip / a, cap_gdw / a          # hm3 / km2 = m
    if _filled(lake_ctrl) and lake_ctrl.strip().lower() in LAKE_CONTROL:
        return 'gdw', 'C1', d_i, d_g
    if height_m and height_m > 0 and np.isfinite(a):
        ok_i = band[0] * height_m <= d_i <= band[1] * height_m
        ok_g = band[0] * height_m <= d_g <= band[1] * height_m
        if ok_g and not ok_i:
            return 'gdw', 'C2', d_i, d_g
        if ok_i and not ok_g:
            return 'isimip', 'C2', d_i, d_g
    return 'isimip', 'C3', d_i, d_g


def location_rule(fit_isimip, fit_gdw, fit_max=FIT_MAX):
    """(choice, rule id) for a pair whose points are far apart; a fit is the best max(ratio, 1/ratio) between the
    upstream area of the 3x3 cells around a point and the catchment area of the same source.
    L1 the GDW point fits: GDW (the newer database; its point lies on the HydroSHEDS river);
    L2 only the ISIMIP point fits: ISIMIP;
    L3 neither fits: GDW."""
    if fit_gdw <= fit_max:
        return 'gdw', 'L1'
    if fit_isimip <= fit_max:
        return 'isimip', 'L2'
    return 'gdw', 'L3'


# ------------------------------------------------------------------------------------------------------ purposes
def _filled(v):
    return isinstance(v, str) and v.strip().lower() not in MISSING_TEXT


def isimip_purpose(text):
    """(known, supply) of an ISIMIP4b PURPOSE text: supply when it names irrigation or water supply."""
    if not _filled(text):
        return False, False
    s = text.lower()
    return True, ('irrigation' in s or 'water supply' in s)


def gdw_purpose(rec):
    """(known, supply) of a GDW record: supply when USE_IRRI or USE_SUPP is filled or MAIN_USE is Irrigation or
    Water supply; known when any USE_* field or MAIN_USE is filled."""
    if rec is None:
        return False, False
    uses = [rec.get(c) for c in GDW_USE]
    main = rec.get('MAIN_USE')
    known = any(_filled(u) for u in uses) or _filled(main)
    supply = _filled(rec.get('USE_IRRI')) or _filled(rec.get('USE_SUPP')) or \
        (_filled(main) and main.strip().lower() in SUPPLY_MAIN_USE)
    return known, supply


def purpose_rule(isimip_text, gdw_rec):
    """'supply' (irrigation or water supply in either source), 'unknown' (no purpose in either source) or
    'no_supply' (a known purpose without irrigation or water supply). A global dam keeps its service map unless
    the rule is 'no_supply' (user, 2026-10-11)."""
    k1, s1 = isimip_purpose(isimip_text)
    k2, s2 = gdw_purpose(gdw_rec)
    if s1 or s2:
        return 'supply'
    return 'no_supply' if (k1 or k2) else 'unknown'


def combine_rules(rules):
    """Purpose rule of one dam made of several records: 'supply' if any record supplies, else 'no_supply' if any
    record has a known purpose, else 'unknown'."""
    return 'supply' if 'supply' in rules else ('no_supply' if 'no_supply' in rules else 'unknown')


def keeps_service(dam_type, rule):
    """A local dam keeps its service map; a global dam unless its purpose rule is no_supply; never an SSP future
    dam (rule 'ssp_future')."""
    if rule == 'ssp_future':
        return False
    return dam_type == 0 or rule in ('supply', 'unknown')


# ----------------------------------------------------------------------------------------------------- SSP sites
def ssp_sites(tables):
    """Future river-power dams of the SSP tables {scenario: DataFrame} as sites (one per exact latitude/longitude):
    DataFrame with lat, lon, capacity_mcm (lake volume / 1e6), catchment_km2 (DDM30 routing area), year_<scenario>
    (NaN where the site is not in that table), name. Also returns the per-row outcome table of every SSP record.
    Diversion-canal plants (SystemID 1) have no lake volume and are left out (user, 2026-10-11). Stops when a site
    has different volumes in two tables."""
    rows, sites = [], {}
    for scen, t in tables.items():
        for _, r in t.iterrows():
            rec = {'source': scen, 'source_row': int(r.row), 'lat': r.latitude, 'lon': r.longitude,
                   'year_built': int(r.year_built), 'system_id': int(r[SSP_SYSTEM]), 'volume_m3': r[SSP_VOLUME]}
            if int(r[SSP_SYSTEM]) != SSP_RIVER_POWER or not (pd.notna(r[SSP_VOLUME]) and r[SSP_VOLUME] > 0):
                rec['outcome'] = 'excluded: diversion canal plant without reservoir volume' \
                    if int(r[SSP_SYSTEM]) != SSP_RIVER_POWER else 'excluded: no reservoir volume'
                rows.append(rec); continue
            k = (float(r.latitude), float(r.longitude))
            s = sites.setdefault(k, {'lat': k[0], 'lon': k[1], 'capacity_mcm': r[SSP_VOLUME] / 1e6,
                                     'catchment_km2': float(r[SSP_AREA]) if pd.notna(r[SSP_AREA]) and r[SSP_AREA] > 0
                                     else np.nan})
            if not np.isclose(s['capacity_mcm'], r[SSP_VOLUME] / 1e6, rtol=1e-9):
                raise ValueError(f'SSP site {k}: lake volume differs between tables')
            if f'year_{scen}' in s:
                raise ValueError(f'SSP site {k} twice in {scen}')
            s[f'year_{scen}'] = int(r.year_built)
            rec['outcome'] = 'site'; rec['site'] = k
            rows.append(rec)
    st = pd.DataFrame(list(sites.values()))
    for scen in tables:
        if f'year_{scen}' not in st:
            st[f'year_{scen}'] = np.nan
    st = st.sort_values(['capacity_mcm', 'lat', 'lon'], ascending=[False, True, True]).reset_index(drop=True)
    st['name'] = [f'ssp-future {la:.5f} {lo:.5f}' for la, lo in zip(st.lat, st.lon)]
    return st, pd.DataFrame(rows)
