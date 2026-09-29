import numpy as np, netCDF4 as nc, json
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
p=np.load('parent15_2021.npz'); hasland=p['hasland']; Pcrop=p['Pcrop']; Pirr=p['Pirr']; cellA=p['cellA']; L=p['L']
v=np.load('vic5_fields.npz'); alloc_pad=v['alloc_pad']
Ppad=alloc_pad.astype('f8').reshape(560,3,1440,3).sum(axis=(1,3))>0
def sub(a): return a[24:584][::-1]
def maxover(fn,var):
    d=nc.Dataset(fn); n=len(d['time']); mx=None
    for a in range(0,n,20):
        blk=np.ma.filled(d[var][a:a+20].astype('f8'),0.0).max(axis=0); mx=blk if mx is None else np.maximum(mx,blk)
    return sub(mx)
out={}
for tag,fn in [('histsoc_1850_2021','landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'),('ssp1vl_2022_2100','landuse-totals_ssp1vl_15arcmin_annual_2022_2100.nc'),('ssp3h_2022_2100','landuse-totals_ssp3h_15arcmin_annual_2022_2100.nc')]:
    mrf=maxover(fn,'cropland_rainfed'); mir=maxover(fn,'cropland_irrigated'); mc=mrf+mir
    out[tag]=dict(max_crop_area_Mkm2_total=float((mc*cellA)[hasland].sum()/1e12),
        max_crop_area_Mkm2_in_no_proxy_parents=float((mc*cellA)[hasland&~Pcrop].sum()/1e12),
        max_irr_area_Mkm2_total=float((mir*cellA)[hasland].sum()/1e12),
        max_irr_area_Mkm2_in_no_irrproxy_parents=float((mir*cellA)[hasland&~Pirr].sum()/1e12))
    out[tag]['pct_crop_lost_if_no_fallback']=100*out[tag]['max_crop_area_Mkm2_in_no_proxy_parents']/out[tag]['max_crop_area_Mkm2_total']
    out[tag]['pct_irr_lost_if_no_fallback']=100*out[tag]['max_irr_area_Mkm2_in_no_irrproxy_parents']/out[tag]['max_irr_area_Mkm2_total']
# 1850 snapshot (histsoc first step) vs proxy
d=nc.Dataset('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc')
c1850=sub(np.ma.filled((d['cropland_rainfed'][0]+d['cropland_irrigated'][0]).astype('f8'),0.0)); i1850=sub(np.ma.filled(d['cropland_irrigated'][0].astype('f8'),0.0))
out['snapshot_1850']=dict(crop_area_Mkm2=float((c1850*cellA)[hasland].sum()/1e12),irr_area_Mkm2=float((i1850*cellA)[hasland].sum()/1e12),
   parents_crop_pos=int(((c1850>0)&hasland).sum()),parents_crop_pos_no_proxy=int(((c1850>0)&hasland&~Pcrop).sum()),
   crop_area_in_no_proxy_parents_Mkm2=float((c1850*cellA)[hasland&~Pcrop&(c1850>0)].sum()/1e12))
# 2100 snapshots
for tag,fn in [('ssp1vl','landuse-totals_ssp1vl_15arcmin_annual_2022_2100.nc'),('ssp3h','landuse-totals_ssp3h_15arcmin_annual_2022_2100.nc')]:
    d=nc.Dataset(fn); c=sub(np.ma.filled((d['cropland_rainfed'][-1]+d['cropland_irrigated'][-1]).astype('f8'),0.0)); i=sub(np.ma.filled(d['cropland_irrigated'][-1].astype('f8'),0.0))
    out['snapshot_2100_'+tag]=dict(crop_area_Mkm2=float((c*cellA)[hasland].sum()/1e12),irr_area_Mkm2=float((i*cellA)[hasland].sum()/1e12),
       crop_area_in_no_proxy_parents_Mkm2=float((c*cellA)[hasland&~Pcrop].sum()/1e12),irr_area_in_no_irrproxy_parents_Mkm2=float((i*cellA)[hasland&~Pirr].sum()/1e12))
json.dump(out,open('extra_2021.json','w'),indent=1); print(json.dumps(out,indent=1))
# maps
vs=p['vs_crop']; isc=p['is_crop']; diff=np.where(hasland,vs-isc,np.nan)
ext=[-180,180,-56,84]
fig,ax=plt.subplots(3,1,figsize=(12,15))
im=ax[0].imshow(np.where(hasland,isc,np.nan),origin='lower',extent=ext,vmin=0,vmax=1,cmap='YlGn'); ax[0].set_title('ISIMIP4b histsoc 2021 cropland share (15 arcmin, relative to VIC land area)'); plt.colorbar(im,ax=ax[0],fraction=0.025)
im=ax[1].imshow(np.where(hasland,vs,np.nan),origin='lower',extent=ext,vmin=0,vmax=1,cmap='YlGn'); ax[1].set_title('VIC coverage_VersionA_v5 2021 cropland share (classes 12+14+15, aggregated 5\'->15\')'); plt.colorbar(im,ax=ax[1],fraction=0.025)
im=ax[2].imshow(diff,origin='lower',extent=ext,vmin=-0.5,vmax=0.5,cmap='RdBu_r'); ax[2].set_title('VIC minus ISIMIP cropland share (2021)'); plt.colorbar(im,ax=ax[2],fraction=0.025)
plt.tight_layout(); plt.savefig('cropland_2021_VIC_vs_ISIMIP_15arcmin.png',dpi=110)
fig,ax=plt.subplots(2,1,figsize=(12,10))
Ic=p['Ic']; Ii=p['Ii']
cat=np.full(hasland.shape,np.nan); cat[hasland&Ic&Pcrop]=1; cat[hasland&Ic&~Pcrop]=2; cat[hasland&~Ic&(vs>0)]=3
im=ax[0].imshow(cat,origin='lower',extent=ext,cmap='viridis',vmin=1,vmax=3); ax[0].set_title('cropland parents: 1 ISIMIP>0 & VIC proxy tile present; 2 ISIMIP>0 & NO proxy tile; 3 VIC>0 & ISIMIP=0'); plt.colorbar(im,ax=ax[0],fraction=0.025)
cat=np.full(hasland.shape,np.nan); cat[hasland&Ii&Pirr]=1; cat[hasland&Ii&~Pirr]=2; cat[hasland&~Ii&(p['vs_irr']>0)]=3
im=ax[1].imshow(cat,origin='lower',extent=ext,cmap='viridis',vmin=1,vmax=3); ax[1].set_title('irrigated parents: same categories'); plt.colorbar(im,ax=ax[1],fraction=0.025)
plt.tight_layout(); plt.savefig('cropland_2021_proxy_categories_15arcmin.png',dpi=110)
print('maps done')
