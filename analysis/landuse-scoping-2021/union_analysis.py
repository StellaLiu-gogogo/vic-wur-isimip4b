import numpy as np, netCDF4 as nc, json
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
VP='/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter'
v=np.load('vic5_fields.npz'); mask=v['mask']; land=v['land']
cov=nc.Dataset(f'{VP}/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2021.nc')['coverage'][0].filled(0).astype('f8')
b=nc.Dataset(f'{VP}/outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc')
Cvb=b['Cv'][:].filled(0); alloc=(Cvb>0)&mask[None]; Nveg=b['Nveg'][:].filled(0).astype(int)
R=6371000.0; dl=np.deg2rad(0.25); latc=np.arange(-56+0.125,84,0.25)
cellA=(R**2*dl*(np.sin(np.deg2rad(latc+0.125))-np.sin(np.deg2rad(latc-0.125))))[:,None]*np.ones((1,1440))
def sub(a): return a[24:584][::-1]
def rd(fn,var,i=0): return sub(np.ma.filled(nc.Dataset(fn)[var][i].astype('f8'),0.0))
def agg(x): return x.reshape(560,3,1440,3).sum(axis=(1,3))
def expand(P): return np.repeat(np.repeat(P,3,axis=0),3,axis=1)
L=agg(land); hasland=L>0
out={}
# ---------- 1. urbanareas metadata + closure (2021)
u=nc.Dataset('urban_histsoc_2021.nc'); out['urban_meta']=dict(vars=list(u.variables),units=str(getattr(u['urbanareas'],'units','?')),long_name=str(getattr(u['urbanareas'],'long_name','?')),calendar=str(getattr(u['time'],'calendar','?')),time_units=str(u['time'].units),lat0=float(u['lat'][0]),nlat=len(u['lat']),nlon=len(u['lon']))
t=nc.Dataset('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'); it=len(t['time'])-1
out['totals_meta']=dict(calendar=str(getattr(t['time'],'calendar','?')),time_units=str(t['time'].units))
rf=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','cropland_rainfed',it); ir=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','cropland_irrigated',it)
pa=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','pastures',it); na=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','forests_and_natural_vegetation',it)
ct=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','cropland_total',it)
ur=rd('urban_histsoc_2021.nc','urbanareas'); rice=rd('landuse-15crops_histsoc_15arcmin_2021.nc','rice_irrigated')
valid=sub(~np.ma.getmaskarray(t['cropland_rainfed'][it]))
s4=rf+ir+pa+na; s5=s4+ur
def dist(x,m): return dict(n=int(m.sum()),min=float(x[m].min()),p01=float(np.percentile(x[m],1)),p50=float(np.percentile(x[m],50)),p99=float(np.percentile(x[m],99)),max=float(x[m].max()),mean=float(x[m].mean()))
out['closure_2021']={'rf+irr+pas+nat':dist(s4,valid),'rf+irr+pas+nat+urb':dist(s5,valid),'urban_share':dist(ur,valid),'cropland_total_minus_rf_irr':dist(ct-rf-ir,valid),
   'cells_urb_pos':int((ur>0).sum()),'cells_s5_gt_1p001':int(((s5>1.001)&valid).sum()),'cells_s4_lt_0p999':int(((s4<0.999)&valid).sum())}
# is urban carved out of natural? compare s4 where urban>0
m=valid&(ur>0.05); out['closure_2021']['where_urb_gt_0.05']=dict(n=int(m.sum()),s4_p50=float(np.percentile(s4[m],50)),s5_p50=float(np.percentile(s5[m],50)))
# ---------- 2. global areas incl urban
Vrf=agg(land*cov[11]); Virr=agg(land*cov[13]); Vpad=agg(land*cov[14]); Vurb=agg(land*cov[12]); Vnat=agg(land*cov[:11].sum(0)); Vbar=agg(land*cov[15])
A=lambda sh:(sh*cellA)[hasland].sum()/1e12
out['global_area_Mkm2_2021']={'VIC_crop':Vrf.sum()/1e12+Virr.sum()/1e12+Vpad.sum()/1e12,'ISIMIP_crop':A(rf+ir),'VIC_irr':(Virr+Vpad).sum()/1e12,'ISIMIP_irr':A(ir),'VIC_paddy':Vpad.sum()/1e12,'ISIMIP_rice_irr':A(rice),
   'VIC_urban':Vurb.sum()/1e12,'ISIMIP_urban':A(ur),'VIC_natural_1_11':Vnat.sum()/1e12,'VIC_barren':Vbar.sum()/1e12,'ISIMIP_pastures':A(pa),'ISIMIP_forests_natural':A(na),'ISIMIP_urban_outside_VICland_parents':float((ur*cellA)[~hasland].sum()/1e12)}
with np.errstate(invalid='ignore',divide='ignore'):
    vu=np.where(hasland,Vurb/L,np.nan); iu=np.where(hasland,ur*cellA/L,np.nan)
d=vu-iu; mm=np.isfinite(d)
out['per_parent15_urban_share_diff_VIC_minus_ISIMIP']=dict(n=int(mm.sum()),p05=float(np.percentile(d[mm],5)),p50=float(np.percentile(d[mm],50)),p95=float(np.percentile(d[mm],95)),corr=float(np.corrcoef(vu[mm],iu[mm])[0,1]),frac_abs_gt_0p05=float((np.abs(d[mm])>0.05).mean()))
# ---------- 3. ledgers for 2021 (per class), with ISIMIP share x full cell area as target
E={'rf':alloc[11],'irr':alloc[13],'pad':alloc[14],'urb':alloc[12]}
P={k:agg(e.astype('f8'))>0 for k,e in E.items()}
T2021={'rf':rf*cellA,'irr':(ir-np.minimum(rice,ir))*cellA,'pad':np.minimum(rice,ir)*cellA,'urb':ur*cellA}
led={}
for k,T in T2021.items():
    pos=T>0
    led[k]=dict(target_Mkm2=float(T[pos].sum()/1e12),no_active_child_Mkm2=float(T[pos&~hasland].sum()/1e12),
        overflow_parents=int((pos&hasland&(T>L)).sum()),overflow_Mkm2=float(np.clip(T-L,0,None)[pos&hasland].sum()/1e12),
        fallback_parents=int((pos&hasland&~P[k]).sum()),fallback_Mkm2=float(T[pos&hasland&~P[k]].sum()/1e12))
Tall=sum(T2021.values()); led['all_crop_urb_vs_land']=dict(parents_target_gt_VICland=int(((Tall>L)&hasland).sum()),overflow_Mkm2=float(np.clip(Tall-L,0,None)[hasland].sum()/1e12))
out['ledgers_2021']=led
# ---------- 4. FULL UNION  (1850soc=histsoc1850, 2021soc=histsoc2021 verified -> union of time-maxima)
def tmax(fn,var):
    d=nc.Dataset(fn); n=len(d['time']); mx=None
    for a in range(0,n,20):
        blk=np.ma.filled(d[var][a:a+20].astype('f8'),0.0).max(axis=0); mx=blk if mx is None else np.maximum(mx,blk)
    return sub(mx)
srcs={'histsoc':'landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','ssp1vl':'landuse-totals_ssp1vl_15arcmin_annual_2022_2100.nc','ssp3h':'landuse-totals_ssp3h_15arcmin_annual_2022_2100.nc'}
U={'rf':np.zeros_like(rf),'irr':np.zeros_like(rf),'pad':np.zeros_like(rf),'urb':np.zeros_like(rf)}
per_src={}
for s,fn in srcs.items():
    mrf=tmax(fn,'cropland_rainfed'); mir=tmax(fn,'cropland_irrigated'); mrice=rd(f'rice_{s}_timmax.nc','rice_irrigated'); murb=rd(f'urban_{s}_timmax.nc','urbanareas')
    mpad=np.minimum(mrice,mir); mirn=mir-mpad
    per_src[s]={'rf':mrf,'irr':mirn,'pad':mpad,'urb':murb}
    for k in U: U[k]=np.maximum(U[k],per_src[s][k])
Upos={k:(U[k]>0)&hasland for k in U}
out['union_parents_pos']={k:int(Upos[k].sum()) for k in U}
out['union_parents_pos_by_source']={s:{k:int(((per_src[s][k]>0)&hasland).sum()) for k in U} for s in per_src}
out['union_fallback_parents']={k:int((Upos[k]&~P[k]).sum()) for k in U}
out['union_fallback_area_Mkm2_timemax']={k:float((U[k]*cellA)[Upos[k]&~P[k]].sum()/1e12) for k in U}
out['union_target_area_Mkm2_timemax']={k:float((U[k]*cellA)[Upos[k]].sum()/1e12) for k in U}
# ---------- 5. new tiles under fallback methods (per class, union targets)
act=mask
# child land per parent block for M4 (largest-area child)
land_blk=land.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
act_blk=mask.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
# suitability for M2 from 2021 natural composition (class idx 0-based): grass9->1.0, savanna8 .8, woodysav7 .8, openshrub6 .6, closedshrub5 .5, forests0-4 .3, barren15 .05, wetland10 0
w=np.array([.3,.3,.3,.3,.3,.5,.6,.8,.8,1.0,0.,0.,0.,0.,0.,.05])
suit=(cov*w[:,None,None]).sum(0)*mask
suit_blk=suit.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
def nn_donor_pattern(Ek,Pk,need):
    """for parents in `need`, find nearest parent (Chebyshev radius<=3) with Pk True; return child-pattern (560,1440,9) bool of donor's Ek"""
    Ek_blk=Ek.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
    pat=np.zeros((560,1440,9),bool); found=np.zeros(need.shape,bool)
    for r in range(1,4):
        for dy in range(-r,r+1):
            for dx in range(-r,r+1):
                if max(abs(dy),abs(dx))!=r: continue
                sh=np.roll(np.roll(Pk,dy,axis=0),dx,axis=1); shE=np.roll(np.roll(Ek_blk,dy,axis=0),dx,axis=1)
                if dy>0: sh[:dy]=False
                if dy<0: sh[dy:]=False
                take=need&~found&sh
                pat[take]=shE[take]; found|=take
    return pat,found
tiles={}; newtile_cells_total=np.zeros(mask.shape,int)
for k in U:
    need=Upos[k]&~P[k]
    m1=expand(need)&act&~E[k]
    # M4: single largest-land active child
    idx=np.argmax(np.where(act_blk,land_blk,-1),axis=2); m4c=np.zeros((560,1440,9),bool); m4c[np.arange(560)[:,None],np.arange(1440)[None,:],idx]=True
    m4=(m4c&need[:,:,None]&act_blk)
    m2=(suit_blk>0)&need[:,:,None]&act_blk
    pat,found=nn_donor_pattern(E[k],P[k],need); m3=(pat&act_blk)|((~found)[:,:,None]&need[:,:,None]&act_blk)   # unfound -> even
    m3_any=(m3.sum(2)>0)
    tiles[k]=dict(fallback_parents=int(need.sum()),M1_even=int(m1.sum()),M2_suitability=int(m2.sum()),M3_nn_donor=int(m3.sum()),M3_parents_with_donor_within_3=int(found.sum()),M4_single_child=int(m4.sum()))
    # spill: parents WITH proxy whose proxy-child land < union target
    capk=agg((E[k]*land).astype('f8')); spill=Upos[k]&P[k]&(U[k]*cellA>capk)
    tiles[k]['spill_parents_proxy_capacity_lt_target']=int(spill.sum()); tiles[k]['spill_deficit_Mkm2']=float(np.clip(U[k]*cellA-capk,0,None)[spill].sum()/1e12)
    tiles[k]['spill_new_tiles_M1_bound']=int((expand(spill)&act&~E[k]).sum())
    newtile_cells_total+= (expand(need)&act&~E[k]).astype(int)   # M1 bound per cell (for Nveg)
out['union_new_tiles_by_method']=tiles
tot=int(alloc.sum())
for meth in ['M1_even','M2_suitability','M3_nn_donor','M4_single_child']:
    s=sum(tiles[k][meth] for k in tiles); out.setdefault('union_new_tiles_total',{})[meth]=dict(new_tiles=s,pct_of_current=100.0*s/tot)
out['union_new_tiles_total']['spill_M1_bound']=int(sum(tiles[k]['spill_new_tiles_M1_bound'] for k in tiles))
# Nveg after (M1 bound; classes 12-15 are non-bare)
Nn=Nveg+newtile_cells_total
out['Nveg']=dict(current_max=int(Nveg[mask].max()),current_mean=float(Nveg[mask].mean()),after_M1_max=int(Nn[mask].max()),after_M1_mean=float(Nn[mask].mean()),cells_gt_13=int((Nn[mask]>13).sum()),cells_15=int((Nn[mask]>=15).sum()))
out['bundle_cost']=dict(current_tiles=tot,bundle_file_bytes_unchanged=True,runtime_scaling='~linear in tiles')
# maps
nt=agg(newtile_cells_total.astype('f8')); nt=np.where(hasland,nt,np.nan)
fig,ax=plt.subplots(2,1,figsize=(12,10)); ext=[-180,180,-56,84]
im=ax[0].imshow(np.where(nt>0,nt,np.nan),origin='lower',extent=ext,cmap='magma_r',vmin=1,vmax=9); ax[0].set_title('full-union fallback parents: new tiles per 15\' parent (M1 even-split bound, all classes)'); plt.colorbar(im,ax=ax[0],fraction=0.025)
cat=np.full(hasland.shape,np.nan)
for i,k in enumerate(['rf','irr','pad','urb']): cat[Upos[k]&~P[k]]=i+1
im=ax[1].imshow(cat,origin='lower',extent=ext,cmap='tab10',vmin=1,vmax=4); ax[1].set_title('fallback parents by class (last wins): 1 rainfed 2 irrigated non-paddy 3 paddy 4 urban'); plt.colorbar(im,ax=ax[1],fraction=0.025)
plt.tight_layout(); plt.savefig('union_fallback_parents_15arcmin.png',dpi=110)
# urban map 2021
with np.errstate(invalid='ignore'):
    fig,ax=plt.subplots(1,1,figsize=(12,5)); im=ax.imshow(np.where(hasland,vu-iu,np.nan),origin='lower',extent=ext,vmin=-0.2,vmax=0.2,cmap='RdBu_r'); ax.set_title('VIC class-13 urban minus ISIMIP urbanareas share (2021, 15 arcmin)'); plt.colorbar(im,ax=ax,fraction=0.025); plt.tight_layout(); plt.savefig('urban_2021_VIC_vs_ISIMIP_15arcmin.png',dpi=110)
np.savez_compressed('union_fields.npz',**{f'U_{k}':U[k] for k in U},**{f'P_{k}':P[k] for k in P},hasland=hasland,newtile_cells_total=newtile_cells_total)
json.dump(out,open('union_analysis.json','w'),indent=1); print(json.dumps(out,indent=1))
