import numpy as np, netCDF4 as nc, json
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
VP='/lustre/nobackup/WUR/ESG/liu297/vic_global/vic_parameter'
v=np.load('vic5_fields.npz'); mask=v['mask']; land=v['land']
u=np.load('union_fields.npz'); hasland=u['hasland']; U={k:u[f'U_{k}'] for k in ['rf','irr','pad','urb']}; P={k:u[f'P_{k}'] for k in U}
b=nc.Dataset(f'{VP}/outputs/human_impact/version_a/v1/vic_global_5min_HumanImpact_VersionA_16class_soil-v10_root-b_v3.nc')
Cvb=b['Cv'][:].filled(0); alloc=(Cvb>0)&mask[None]
names="evergreen_needleleaf|evergreen_broadleaf|deciduous_needleleaf|deciduous_broadleaf|mixed_forest|closed_shrubland|open_shrubland|woody_savanna|savanna|grassland|permanent_wetland|rainfed_crop|urban|irrigated_non_paddy_crop|irrigated_paddy_crop|barren".split('|')
cls={'rf':11,'urb':12,'irr':13,'pad':14}
cov=nc.Dataset(f'{VP}/work/human_impact/landuse_forcing_v5/coverage_VersionA_v5_2021.nc')['coverage'][0].filled(0).astype('f8')
w=np.array([.3,.3,.3,.3,.3,.5,.6,.8,.8,1.0,0.,0.,0.,0.,0.,.05]); suit=(cov*w[:,None,None]).sum(0)*mask
def blk(x): return x.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
def unblk(x): return x.reshape(560,1440,3,3).transpose(0,2,1,3).reshape(1680,4320)
act_blk=blk(mask); land_blk=blk(land); suit_blk=blk(suit)
def hybrid_mask(Ek,Pk,need):
    Ek_blk=blk(Ek); pat=np.zeros((560,1440,9),bool); found=np.zeros(need.shape,bool)
    for r in range(1,4):
        for dy in range(-r,r+1):
            for dx in range(-r,r+1):
                if max(abs(dy),abs(dx))!=r: continue
                sh=np.roll(np.roll(Pk,dy,axis=0),dx,axis=1); shE=np.roll(np.roll(Ek_blk,dy,axis=0),dx,axis=1)
                if dy>0: sh[:dy]=False
                if dy<0: sh[dy:]=False
                take=need&~found&sh; pat[take]=shE[take]; found|=take
    m3=pat&act_blk&found[:,:,None]
    # donor pattern may have no active overlap -> single child
    nohit=found&(m3.sum(2)==0)
    single=np.zeros((560,1440,9),bool); idx=np.argmax(np.where(act_blk,suit_blk+1e-9*land_blk,-1),axis=2)
    single[np.arange(560)[:,None],np.arange(1440)[None,:],idx]=True
    m4=single&((~found)|nohit)[:,:,None]&need[:,:,None]&act_blk
    return unblk(m3|m4)
out={}; union_tiles=alloc.copy()
for k,c in cls.items():
    need=(U[k]>0)&hasland&~P[k]
    newm=hybrid_mask(alloc[c],P[k],need)&~alloc[c]
    # spill: parents with proxy but capacity short -> add children by suitability until capacity >= target (M1 bound used earlier; here greedy)
    capk=blk((alloc[c]*land).astype('f8')).sum(2); R=6371000.0; dl=np.deg2rad(0.25); latc=np.arange(-56+0.125,84,0.25)
    cellA=(R**2*dl*(np.sin(np.deg2rad(latc+0.125))-np.sin(np.deg2rad(latc-0.125))))[:,None]*np.ones((1,1440))
    T=U[k]*cellA; spill=(T>0)&hasland&P[k]&(T>capk)
    sp=np.zeros((560,1440,9),bool)
    if spill.any():
        order=np.argsort(-np.where(act_blk&~blk(alloc[c]),suit_blk+1e-9*land_blk,-1),axis=2)
        cum=capk.copy(); lb=land_blk
        for r in range(9):
            j=order[:,:,r]; a=np.take_along_axis(lb,j[:,:,None],2)[:,:,0]; ok=spill&(cum<T)&(np.take_along_axis(act_blk&~blk(alloc[c]),j[:,:,None],2)[:,:,0])
            sp[np.arange(560)[:,None],np.arange(1440)[None,:],j]|=ok; cum=cum+np.where(ok,a,0)
    spm=unblk(sp)
    union_tiles[c]|=newm|spm
    out[k]=dict(union_parents=int(((U[k]>0)&hasland).sum()),fallback_parents=int(need.sum()),new_tiles_fallback=int(newm.sum()),new_tiles_spill=int(spm.sum()),tiles_before=int(alloc[c].sum()),tiles_after=int(union_tiles[c].sum()))
# natural-remainder check: cells with a crop/urban tile but no natural/barren tile allocated
nat_any=alloc[:11].any(0)|alloc[15]
crop_any=union_tiles[11]|union_tiles[12]|union_tiles[13]|union_tiles[14]
out['cells_with_crop_or_urban_tile_but_no_natural_or_barren_tile']=int((crop_any&~nat_any&mask).sum())
out['cells_2021_coverage_100pct_crop_urban']=int(((cov[[11,12,13,14]].sum(0)>0.999)&mask).sum())
# ---- completeness per class over union tiles
def inv(a): return ~np.isfinite(a)
res={}
LAI=b['LAI']; ALB=b['albedo']; FC=b['fcanopy']; RD=b['root_depth']; RF=b['root_fract']
for c in range(16):
    ut=union_tiles[c]; al=alloc[c]; new=ut&~al
    lai_bad=np.zeros(mask.shape,bool); alb_bad=lai_bad.copy(); fc_bad=lai_bad.copy()
    for m in range(12):
        lai_bad|=inv(LAI[c,m].filled(np.nan)); alb_bad|=inv(ALB[c,m].filled(np.nan)); fc_bad|=inv(FC[c,m].filled(np.nan))
    rd=RD[c].filled(np.nan); rf=RF[c].filled(np.nan)
    root_bad=inv(rd).any(0)|inv(rf).any(0)|(np.nansum(rd,0)<=0)|(np.abs(np.nansum(rf,0)-1)>1e-6)
    stat_bad=np.zeros(mask.shape,bool)
    for var in ['rmin','rarc','RGL','rad_atten','wind_atten','trunk_ratio','wind_h','overstory']:
        stat_bad|=inv(b[var][c].filled(np.nan))
    for var in ['displacement','veg_rough']:
        for m in range(12): stat_bad|=inv(b[var][c,m].filled(np.nan))
    res[names[c]]=dict(allocated=int(al.sum()),union=int(ut.sum()),new=int(new.sum()),
        LAI12_missing_allocated=int((lai_bad&al).sum()),LAI12_missing_union=int((lai_bad&ut).sum()),
        fcanopy12_missing_union=int((fc_bad&ut).sum()),albedo12_missing_union=int((alb_bad&ut).sum()),
        root_missing_union=int((root_bad&ut).sum()),static_lib_missing_union=int((stat_bad&ut).sum()))
    if c==15: res[names[c]]['note']='bare class: root/rmin zero by design'
out['completeness']=res
# veghist monthly 2015 on union tiles (class 12-15 already known fill where Cv==0)
vh=nc.Dataset(f'{VP}/outputs/human_impact/version_a/option2/monthly_veghist/v1/HumanImpact_VersionA_Option2_16class_monthly_veghist_2015.nc')
vres={}
for c in [11,12,13,14]:
    bad=np.zeros(mask.shape,bool)
    for m in range(12): bad|=inv(np.ma.filled(vh['lai'][m,c].astype('f8'),np.nan))
    vres[names[c]]=dict(lai12_missing_union=int((bad&union_tiles[c]).sum()),lai12_missing_new=int((bad&union_tiles[c]&~alloc[c]).sum()),lai12_missing_allocated=int((bad&alloc[c]).sum()))
out['veghist_2015']=vres
# irrigation params on new irrigated cells
ir=nc.Dataset(f'{VP}/outputs/human_impact/irrigation_parameter_candidate_v2_efficiency_corrected/irrigationParameters_5min_candidate_v2.nc')
eff=ir['irrigation_efficiency'][:].filled(np.nan); gw=ir['groundwater_fraction'][:].filled(np.nan)
irr_cells=union_tiles[13]|union_tiles[14]; new_irr=irr_cells&~(alloc[13]|alloc[14])
out['irrigation_params']=dict(active_invalid_eff=int((~np.isfinite(eff)|(eff<=0))[mask].sum()),active_invalid_gw=int((~np.isfinite(gw)|(gw<0)|(gw>1))[mask].sum()),
   new_irr_cells=int(new_irr.sum()),new_irr_cells_invalid_eff=int((~np.isfinite(eff)|(eff<=0))[new_irr].sum()),new_irr_cells_invalid_gw=int((~np.isfinite(gw)|(gw<0)|(gw>1))[new_irr].sum()),
   union_irr_cells=int(irr_cells.sum()),union_irr_cells_invalid_eff=int((~np.isfinite(eff)|(eff<=0))[irr_cells].sum()))
# totals
out['tiles']=dict(before=int(alloc.sum()),after=int(union_tiles.sum()),new=int((union_tiles&~alloc).sum()),pct=100*float((union_tiles&~alloc).sum())/float(alloc.sum()))
Nveg_after=(union_tiles[:15].sum(0)); out['Nveg_after']=dict(max=int(Nveg_after[mask].max()),mean=float(Nveg_after[mask].mean()),hist=np.bincount(Nveg_after[mask]).tolist())
np.savez_compressed('union_tiles.npz',union_tiles=union_tiles,alloc=alloc)
# maps of new tiles per class (5' -> 15' count)
fig,ax=plt.subplots(4,1,figsize=(12,18)); ext=[-180,180,-56,84]
for i,k in enumerate(['rf','irr','pad','urb']):
    c=cls[k]; n=(union_tiles[c]&~alloc[c]).astype('f8').reshape(560,3,1440,3).sum(axis=(1,3)); n=np.where(hasland,n,np.nan)
    im=ax[i].imshow(np.where(n>0,n,np.nan),origin='lower',extent=ext,cmap='magma_r',vmin=1,vmax=9); ax[i].set_title(f'new {names[c]} tiles per 15\' parent (hybrid donor/single-child, full union)'); plt.colorbar(im,ax=ax[i],fraction=0.025)
plt.tight_layout(); plt.savefig('union_new_tiles_by_class_hybrid.png',dpi=100)
json.dump(out,open('union_completeness.json','w'),indent=1); print(json.dumps(out,indent=1))
