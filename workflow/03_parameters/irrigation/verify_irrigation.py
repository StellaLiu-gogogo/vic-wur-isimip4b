#!/usr/bin/env python3
"""Independent verification of the adopted irrigation file of a parameter set (component `irrigation`, read by VIC
with IRRIGATION_PARAMETERS; plugins/irrigation/src/irr_start.c, irr_alloc_free.c and irr_init.c at VIC 39e21ff5).

Checks (each with its own status; the file passes only when all pass):
  integrity      md5 and size equal the manifest; not modified after adoption (see adopted.py)
  vic_variables  veg_class and paddy (irr_class, int), groundwater_fraction and irrigation_efficiency (lat, lon,
                 float) present; lat 1680, lon 4320; irr_class gives NIRRTYPES; irrigation_offset is absent, so the
                 runs must set OFFSET_IRRIGATION FALSE (irr_init.c reads it only then)
  latlon         lat and lon equal the domain file exactly
  classes        veg_class = EXPECTED_VEG_CLASS (14 irrigated non-paddy, 15 irrigated paddy; the 16-class contract)
                 and paddy = EXPECTED_PADDY; irr_init.c sets the groundwater fraction of a paddy class to 0 whatever
                 the file holds, so groundwater_fraction acts on class 14 only
  values         on every active cell: irrigation_efficiency in (0, 1] (irr_use.c divides the demand by it and uses
                 it as the consumed fraction) and groundwater_fraction in [0, 1], neither fill nor NaN; fill only
                 outside the mask (cells outside the mask that hold values are counted, VIC never reads them)
Writes <qc>/summary.json, <qc>/reports/verify.json and <qc>/figures/{irrigation_efficiency,groundwater_fraction}.png,
where <qc> is qc/parameters/<status>/<set>/irrigation/.

Usage: verify_irrigation.py [--parameter-set ID] [--parameter-status candidates]
"""
import os, sys

import numpy as np
import netCDF4 as nc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'domain'))
import adopted   # noqa: E402

IRRIGATION = 'irrigation/vic_global_5min_irrigation_parameters.nc'
EXPECTED_VEG_CLASS = [14, 15]
EXPECTED_PADDY = [0, 1]
VIC_READS = {'veg_class': (('irr_class',), 'i'), 'paddy': (('irr_class',), 'i'),
             'groundwater_fraction': (('lat', 'lon'), 'f'), 'irrigation_efficiency': (('lat', 'lon'), 'f')}


def value_check(values, fill, mask, low, high, low_open=False):
    """Fill and range of a (lat, lon) field on the active cells; low_open excludes `low` itself."""
    bad = adopted.is_fill(values, fill)
    v = values[mask & ~bad].astype('f8')
    below = (v <= low) if low_open else (v < low)
    res = {'active_cells_fill': int((mask & bad).sum()), 'active_cells_out_of_range': int((below | (v > high)).sum()),
           'range': f'{"(" if low_open else "["}{low}, {high}]', 'active': adopted.stats(v),
           'active_cells_0': int((v == 0).sum()), 'active_cells_1': int((v == 1).sum()),
           'cells_outside_mask_with_values': int((~mask & ~bad).sum())}
    res['status'] = 'passed' if res['active_cells_fill'] == res['active_cells_out_of_range'] == 0 else 'failed'
    return res


def main():
    run = adopted.Run('irrigation', __doc__.splitlines()[0])
    dom = adopted.read_domain(f'{run.pset}/{adopted.DOMAIN}')
    mask = dom['mask']
    checks = {'integrity': run.integrity('irrigation')}
    with nc.Dataset(f'{run.pset}/{IRRIGATION}') as d:
        checks['vic_variables'] = adopted.variables_check(d, VIC_READS, {'lat': 1680, 'lon': 4320, 'irr_class': 2})
        checks['vic_variables']['irrigation_offset_present'] = 'irrigation_offset' in d.variables
        checks['vic_variables']['required_option'] = ('OFFSET_IRRIGATION FALSE' if 'irrigation_offset' not in
                                                      d.variables else 'OFFSET_IRRIGATION TRUE or FALSE')
        checks['latlon'] = adopted.latlon_check(d, dom)
        vc = adopted.raw(d, 'veg_class').tolist(); pd_ = adopted.raw(d, 'paddy').tolist()
        checks['classes'] = {'veg_class': vc, 'paddy': pd_, 'expected_veg_class': EXPECTED_VEG_CLASS,
                             'expected_paddy': EXPECTED_PADDY,
                             'groundwater_fraction_used_for': [c for c, p in zip(vc, pd_) if p != 1],
                             'groundwater_fraction_forced_to_0_for': [c for c, p in zip(vc, pd_) if p == 1],
                             'status': 'passed' if vc == EXPECTED_VEG_CLASS and pd_ == EXPECTED_PADDY else 'failed'}
        eff = adopted.raw(d, 'irrigation_efficiency'); gw = adopted.raw(d, 'groundwater_fraction')
        fe = adopted.fill_value(d['irrigation_efficiency']); fg = adopted.fill_value(d['groundwater_fraction'])
    ce = value_check(eff, fe, mask, 0.0, 1.0, low_open=True)
    cg = value_check(gw, fg, mask, 0.0, 1.0)
    checks['values'] = {'irrigation_efficiency': ce, 'groundwater_fraction': cg,
                        'status': adopted.qcm.combine([ce['status'], cg['status']])}
    for name, v, f, cmap in (('irrigation_efficiency', eff, fe, 'viridis'), ('groundwater_fraction', gw, fg, 'magma_r')):
        show = np.where(mask & ~adopted.is_fill(v, f), v.astype('f8'), np.nan)
        adopted.save_map(f'{run.qc}/figures/{name}.png', show, dom['lat'], dom['lon'], f'{name} (active cells)',
                         name, cmap=cmap, vmin=0, vmax=1)
    run.finish([IRRIGATION], checks, 'workflow/03_parameters/irrigation/verify_irrigation.py')


if __name__ == '__main__':
    main()
