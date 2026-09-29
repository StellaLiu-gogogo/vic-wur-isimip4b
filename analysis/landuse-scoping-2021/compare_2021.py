import numpy as np, netCDF4 as nc, json
S='.'
v=np.load('vic5_fields.npz')
mask=v['mask']; land=v['land']; cov_rf=v['cov_rf'].astype('f8'); cov_irr=v['cov_irr'].astype('f8'); cov_pad=v['cov_pad'].astype('f8'); cov_urb=v['cov_urb'].astype('f8')
alloc_rf=v['alloc_rf']; alloc_irr=v['alloc_irr']; alloc_pad=v['alloc_pad']
out={}
# ---- ISIMIP 15' histsoc 2021
f=nc.Dataset('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc')
lat=f['lat'][:]; lon=f['lon'][:]; t=f['time']
out['isimip15_grid']=dict(nlat=len(lat),nlon=len(lon),lat0=float(lat[0]),lat1=float(lat[-1]),lon0=float(lon[0]),time_units=str(t.units),ntime=len(t))
i2021=len(t)-1
def rd(ds,var,i): 
    a=ds[var][i]; return np.ma.filled(a.astype('f8'),np.nan)
VARS=[k for k in ['cropland_rainfed','cropland_irrigated','pastures','forests_and_natural_vegetation','urbanareas','cropland_total'] if k in f.variables]; tot={k:rd(f,k,i2021) for k in VARS}
if 'urbanareas' not in tot: tot['urbanareas']=np.zeros_like(tot['cropland_rainfed'])
print('vars', list(f.variables))
# also cropland_total if exists
if 'cropland_total' in f.variables: tot['cropland_total']=rd(f,'cropland_total',i2021)
north_first = lat[0]>lat[-1]
# rows covering 84..-56
if north_first:
    r0=int(round((90-84)/0.25)); r1=int(round((90+56)/0.25))
else:
    r0=int(round((-56+90)/0.25)); r1=int(round((84+90)/0.25))
sub=lambda a: (a[r0:r1][::-1] if north_first else a[r0:r1])   # -> south->north like VIC
T={k:sub(a) for k,a in tot.items()}
out['isimip15_subset_rows']=[r0,r1, T['cropland_rainfed'].shape]
ssum=np.nansum(np.stack([T[k] for k in ['cropland_rainfed','cropland_irrigated','pastures','forests_and_natural_vegetation','urbanareas'] if k in T]),0)
valid=np.isfinite(T['cropland_rainfed'])
out['isimip15_sum_of_5_shares']=dict(valid_cells=int(valid.sum()),p01=float(np.nanpercentile(ssum[valid],1)),p50=float(np.nanpercentile(ssum[valid],50)),p99=float(np.nanpercentile(ssum[valid],99)),max=float(np.nanmax(ssum[valid])))
# 15crops rice
g=nc.Dataset('landuse-15crops_histsoc_15arcmin_2021.nc')
rice=sub(np.ma.filled(g['rice_irrigated'][0].astype('f8'),np.nan))
# ---- aggregate VIC 5' to 15' (3x3)
def agg(x):  # sum over 3x3 blocks
    return x.reshape(560,3,1440,3).sum(axis=(1,3))
L=agg(land)                     # VIC land area per parent (m2)
A15 = None
# parent full cell area (spherical) for ISIMIP-share interpretation
latc=np.arange(-56+0.125,84,0.25); R=6371000.0
dlat=np.deg2rad(0.25); dlon=np.deg2rad(0.25)
cellA=(R**2*dlon*(np.sin(np.deg2rad(latc+0.125))-np.sin(np.deg2rad(latc-0.125))))[:,None]*np.ones((1,1440))
Vrf=agg(land*cov_rf); Virr=agg(land*cov_irr); Vpad=agg(land*cov_pad); Vurb=agg(land*cov_urb)
Vcrop=Vrf+Virr+Vpad
hasland=L>0
# ISIMIP crop area under two interpretations: share of full cell area (A) / share of VIC land area (B)
Icrop_sh=np.nan_to_num(T['cropland_rainfed']+T['cropland_irrigated']); Iirr_sh=np.nan_to_num(T['cropland_irrigated']); Irf_sh=np.nan_to_num(T['cropland_rainfed']); Irice_sh=np.nan_to_num(rice); Iurb_sh=np.nan_to_num(T['urbanareas']); Ipas_sh=np.nan_to_num(T['pastures'])
out['global_area_Mkm2']={
 'VIC_crop':Vcrop.sum()/1e12,'VIC_irrigated':(Virr+Vpad).sum()/1e12,'VIC_paddy':Vpad.sum()/1e12,'VIC_rainfed':Vrf.sum()/1e12,'VIC_urban':Vurb.sum()/1e12,
 'ISIMIP_crop_x_fullcell':(Icrop_sh*cellA).sum()/1e12,'ISIMIP_irr_x_fullcell':(Iirr_sh*cellA).sum()/1e12,'ISIMIP_rice_irr_x_fullcell':(Irice_sh*cellA).sum()/1e12,'ISIMIP_urban_x_fullcell':(Iurb_sh*cellA).sum()/1e12,'ISIMIP_pastures_x_fullcell':(Ipas_sh*cellA).sum()/1e12,
 'ISIMIP_crop_x_VICland':(Icrop_sh*L).sum()/1e12,'ISIMIP_irr_x_VICland':(Iirr_sh*L).sum()/1e12,'ISIMIP_rice_irr_x_VICland':(Irice_sh*L).sum()/1e12,
 'ISIMIP_crop_x_fullcell_outside_VICdomain_rows':float(((np.nan_to_num(tot['cropland_rainfed']+tot['cropland_irrigated']))*1).sum()*0)  # placeholder
}
# crop outside VIC latitude window (whole ISIMIP grid minus subset)
full_crop=np.nan_to_num(tot['cropland_rainfed']+tot['cropland_irrigated'])
latf=np.asarray(lat); cellAf=(R**2*dlon*(np.sin(np.deg2rad(latf+0.125))-np.sin(np.deg2rad(latf-0.125))))[:,None]*np.ones((1,1440))
out['global_area_Mkm2']['ISIMIP_crop_x_fullcell_ALLROWS']=(full_crop*cellAf).sum()/1e12
out['global_area_Mkm2']['ISIMIP_crop_in_parents_with_no_VIC_land']=float((Icrop_sh*cellA)[~hasland].sum()/1e12)
# per-parent shares (relative to VIC land area) for comparison
with np.errstate(invalid='ignore',divide='ignore'):
    vs_crop=np.where(hasland,Vcrop/L,np.nan); vs_irr=np.where(hasland,(Virr+Vpad)/L,np.nan); vs_pad=np.where(hasland,Vpad/L,np.nan)
    # ISIMIP share relative to full cell -> convert to share of VIC land for fair comparison: crop area/VIC land
    is_crop=np.where(hasland,Icrop_sh*cellA/L,np.nan); is_irr=np.where(hasland,Iirr_sh*cellA/L,np.nan); is_pad=np.where(hasland,Irice_sh*cellA/L,np.nan)
def stats(d,name,w):
    m=np.isfinite(d)
    out[name]=dict(n=int(m.sum()),mean_diff=float(np.nanmean(d)),area_weighted_mean_diff=float(np.nansum(d[m]*w[m])/w[m].sum()),
        p05=float(np.nanpercentile(d[m],5)),p25=float(np.nanpercentile(d[m],25)),p50=float(np.nanpercentile(d[m],50)),p75=float(np.nanpercentile(d[m],75)),p95=float(np.nanpercentile(d[m],95)),
        frac_abs_gt_0p1=float((np.abs(d[m])>0.1).mean()),frac_abs_gt_0p25=float((np.abs(d[m])>0.25).mean()))
stats(vs_crop-is_crop,'per_parent15_crop_share_diff_VIC_minus_ISIMIP',L)
stats(vs_irr-is_irr,'per_parent15_irr_share_diff_VIC_minus_ISIMIP',L)
stats(vs_pad-is_pad,'per_parent15_paddy_share_diff_VIC_minus_ISIMIP',L)
m=hasland&np.isfinite(vs_crop)&np.isfinite(is_crop)
out['per_parent15_crop_share_corr']=float(np.corrcoef(vs_crop[m],is_crop[m])[0,1]); out['per_parent15_irr_share_corr']=float(np.corrcoef(vs_irr[m],is_irr[m])[0,1])
# parents categories (proxy = any allocated crop tile among active children)
Prf=agg(alloc_rf.astype('f8'))>0; Pirr=agg(alloc_irr.astype('f8'))>0; Ppad=agg(alloc_pad.astype('f8'))>0
Pcrop=Prf|Pirr|Ppad
Pirr_any=Pirr|Ppad
Ic=Icrop_sh>0; Ii=Iirr_sh>0; Ip=Irice_sh>0
Vc=Vcrop>0; Vi=(Virr+Vpad)>0
def cat(I,P,V,area_sh,label):
    out[label]=dict(
      parents_ISIMIP_pos=int((I&hasland).sum()),
      parents_ISIMIP_pos_no_proxy_tile=int((I&hasland&~P).sum()),
      area_Mkm2_ISIMIP_in_no_proxy_parents=float((area_sh*cellA)[I&hasland&~P].sum()/1e12),
      parents_ISIMIP_pos_but_VIC2021_zero=int((I&hasland&~V).sum()),
      parents_VIC2021_pos_but_ISIMIP_zero=int((V&hasland&~I).sum()),
      area_Mkm2_VIC_in_parents_ISIMIP_zero=float(0.0),
      parents_ISIMIP_pos_no_VIC_land=int((I&~hasland).sum()))
cat(Ic,Pcrop,Vc,Icrop_sh,'cat_cropland'); out['cat_cropland']['area_Mkm2_VIC_in_parents_ISIMIP_zero']=float(Vcrop[Vc&hasland&~Ic].sum()/1e12)
cat(Ii,Pirr_any,Vi,Iirr_sh,'cat_irrigated'); out['cat_irrigated']['area_Mkm2_VIC_in_parents_ISIMIP_zero']=float((Virr+Vpad)[Vi&hasland&~Ii].sum()/1e12)
cat(Ip,Ppad,Vpad>0,Irice_sh,'cat_paddy'); out['cat_paddy']['area_Mkm2_VIC_in_parents_ISIMIP_zero']=float(Vpad[(Vpad>0)&hasland&~Ip].sum()/1e12)
# ---- missing tiles at 5': children of no-proxy parents (even-split fallback would need a tile in every active child)
def expand(P): return np.repeat(np.repeat(P,3,axis=0),3,axis=1)
act=mask
need_rf = expand(Irf_sh>0) & ~expand(Prf) & act        # rainfed tile needed via fallback
need_irr= expand(Iirr_sh>0) & ~expand(Pirr_any) & act
need_pad= expand(Irice_sh>0) & ~expand(Ppad) & act
out['missing_tiles_2021_histsoc_evenfallback']=dict(rainfed_cells=int(need_rf.sum()),irrigated_cells=int(need_irr.sum()),paddy_cells=int(need_pad.sum()),
    any_new_tile_cells=int((need_rf|need_irr|need_pad).sum()), new_tiles_total=int(need_rf.sum()+need_irr.sum()+need_pad.sum()))
# proxy-nonzero parents: no new tile needed (allocation stays within existing tiles)
# ---- Group III / histsoc unions: max over time of ISIMIP crop shares per parent
def maxover(fn,var):
    d=nc.Dataset(fn); n=len(d['time']); mx=None
    for a in range(0,n,20):
        blk=np.ma.filled(d[var][a:a+20].astype('f8'),0.0).max(axis=0)
        mx=blk if mx is None else np.maximum(mx,blk)
    return sub(mx)
unions={}
for tag,fn in [('histsoc_1850_2021','landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'),('ssp1vl_2022_2100','landuse-totals_ssp1vl_15arcmin_annual_2022_2100.nc'),('ssp3h_2022_2100','landuse-totals_ssp3h_15arcmin_annual_2022_2100.nc')]:
    mrf=maxover(fn,'cropland_rainfed'); mir=maxover(fn,'cropland_irrigated')
    nrf=expand(mrf>0)&~expand(Prf)&act; nir=expand(mir>0)&~expand(Pirr_any)&act
    unions[tag]=dict(parents_crop_pos=int(((mrf+mir)>0).sum()),parents_crop_pos_no_proxy=int((((mrf+mir)>0)&hasland&~Pcrop).sum()),
                     parents_irr_pos_no_proxy=int(((mir>0)&hasland&~Pirr_any).sum()),
                     new_rainfed_tiles=int(nrf.sum()),new_irrigated_tiles=int(nir.sum()),new_tiles_total=int(nrf.sum()+nir.sum()))
out['union_missing_tiles_evenfallback']=unions
# rice future
for tag,fn in [('ssp1vl_2100','landuse-15crops_ssp1vl_15arcmin_2100.nc'),('ssp3h_2100','landuse-15crops_ssp3h_15arcmin_2100.nc')]:
    r=sub(np.ma.filled(nc.Dataset(fn)['rice_irrigated'][0].astype('f8'),0.0))
    out['union_missing_tiles_evenfallback'][tag+'_paddy']=dict(parents_rice_pos_no_proxy=int(((r>0)&hasland&~Ppad).sum()),new_paddy_tiles=int((expand(r>0)&~expand(Ppad)&act).sum()))
# bundle size / cost
base=int(v['alloc_rf'].sum()+v['alloc_irr'].sum()+v['alloc_pad'].sum()+v['alloc_urb'].sum())
tot_tiles=9061423
for k,d in unions.items():
    if 'new_tiles_total' in d: d['pct_increase_total_tiles']=100.0*d['new_tiles_total']/tot_tiles
out['missing_tiles_2021_histsoc_evenfallback']['pct_increase_total_tiles']=100.0*out['missing_tiles_2021_histsoc_evenfallback']['new_tiles_total']/tot_tiles
# save parent-level arrays for plotting later
np.savez_compressed('parent15_2021.npz',vs_crop=vs_crop,is_crop=is_crop,vs_irr=vs_irr,is_irr=is_irr,hasland=hasland,Pcrop=Pcrop,Ic=Ic,Ii=Ii,Pirr=Pirr_any,L=L,cellA=cellA)
json.dump(out,open('compare_2021.json','w'),indent=1); print(json.dumps(out,indent=1))
