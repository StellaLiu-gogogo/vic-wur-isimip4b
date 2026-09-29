import numpy as np, netCDF4 as nc, json
VP='/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter'
dom=nc.Dataset('/lustre/nobackup/WUR/ESG/liu297/vic_coupled/Data/VIC/domain/global/vic_global_5min_domain_nogl.nc')
mask=dom['mask'][:].filled(0).astype(bool); area=dom['area'][:].filled(0).astype('f8'); frac=dom['frac'][:].filled(0).astype('f8')
lat=dom['lat'][:]; lon=dom['lon'][:]
land=area*frac*mask
print('domain', mask.shape, 'active', int(mask.sum()), 'lat', float(lat[0]), float(lat[-1]), 'lon', float(lon[0]), float(lon[-1]))
print('land area Mkm2', land.sum()/1e12)
cov=nc.Dataset(f'{VP}/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2021.nc')['coverage'][0].filled(0).astype('f4')  # 16,1680,4320
b=nc.Dataset(f'{VP}/outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc')
Cv=b['Cv'][:].filled(0).astype('f8'); Nveg=b['Nveg'][:].filled(0)
names="evergreen_needleleaf|evergreen_broadleaf|deciduous_needleleaf|deciduous_broadleaf|mixed_forest|closed_shrubland|open_shrubland|woody_savanna|savanna|grassland|permanent_wetland|rainfed_crop|urban|irrigated_non_paddy_crop|irrigated_paddy_crop|barren".split('|')
out={}
out['coverage2021_sum_check']=dict(min=float(cov.sum(0)[mask].min()),max=float(cov.sum(0)[mask].max()))
def A(x): return float((x*land).sum()/1e12)  # Mkm2
out['coverage2021_area_Mkm2']={n:A(cov[i]) for i,n in enumerate(names)}
out['coverage2021_cropland_Mkm2']=A(cov[11]+cov[13]+cov[14]); out['coverage2021_irrigated_Mkm2']=A(cov[13]+cov[14]); out['coverage2021_paddy_Mkm2']=A(cov[14])
alloc=(Cv>0)&mask[None]
out['bundle_allocated_tiles_by_class']={n:int(alloc[i].sum()) for i,n in enumerate(names)}
out['bundle_total_tiles']=int(alloc.sum()); out['bundle_mean_tiles_per_cell']=float(alloc.sum()/mask.sum())
out['bundle_epsilon_tiles']=int(((Cv>0)&(Cv<1e-6)&mask[None]).sum())
out['bundle_Nveg_stats']=dict(mean=float(Nveg[mask].mean()),max=int(Nveg[mask].max()))
out['cells_crop_allocated_any']=int((alloc[11]|alloc[13]|alloc[14]).sum()); out['cells_irr_allocated_any']=int((alloc[13]|alloc[14]).sum())
out['cells_cov2021_crop_pos']=int(((cov[11]+cov[13]+cov[14])>0).sum()); out['cells_cov2021_irr_pos']=int(((cov[13]+cov[14])>0).sum())
# save 5' fields needed later
np.savez_compressed('vic5_fields.npz', mask=mask, land=land, lat=lat, lon=lon, cov_rf=cov[11], cov_irr=cov[13], cov_pad=cov[14], cov_urb=cov[12], cov_nat=cov[:11].sum(0), cov_bar=cov[15], alloc_rf=alloc[11], alloc_irr=alloc[13], alloc_pad=alloc[14], alloc_urb=alloc[12])
json.dump(out, open('vic_side_stats.json','w'), indent=1, ensure_ascii=False); print(json.dumps(out, indent=1))
