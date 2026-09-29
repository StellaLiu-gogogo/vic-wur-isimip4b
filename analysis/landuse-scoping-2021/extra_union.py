import numpy as np, netCDF4 as nc, json
u=np.load('union_fields.npz'); v=np.load('vic5_fields.npz'); mask=v['mask']; land=v['land']
hasland=u['hasland']; U={k:u[f'U_{k}'] for k in ['rf','irr','pad','urb']}; P={k:u[f'P_{k}'] for k in U}
R=6371000.0; dl=np.deg2rad(0.25); latc=np.arange(-56+0.125,84,0.25)
cellA=(R**2*dl*(np.sin(np.deg2rad(latc+0.125))-np.sin(np.deg2rad(latc-0.125))))[:,None]*np.ones((1,1440))
def sub(a): return a[24:584][::-1]
def rd(fn,var,i=0): return sub(np.ma.filled(nc.Dataset(fn)[var][i].astype('f8'),0.0))
out={}
# 1. closure classification 2021 (5 shares)
t=nc.Dataset('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc'); it=len(t['time'])-1
s5=sum(rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc',k,it) for k in ['cropland_rainfed','cropland_irrigated','pastures','forests_and_natural_vegetation'])+rd('urban_histsoc_2021.nc','urbanareas')
valid=sub(~np.ma.getmaskarray(t['cropland_rainfed'][it]))
L=land.reshape(560,3,1440,3).sum(axis=(1,3))
lf=np.where(hasland,L/cellA,0)   # VIC land fraction of parent
c=dict(valid=int(valid.sum()),s5_eq0=int((valid&(s5==0)).sum()),s5_lt_0p999=int((valid&(s5<0.999)).sum()),s5_between=int((valid&(s5>0)&(s5<0.999)).sum()))
m=valid&(s5>0)&(s5<0.999)
c['s5_between_vs_VIClandfrac_corr']=float(np.corrcoef(s5[m],lf[m])[0,1]); c['s5_between_p50']=float(np.median(s5[m])); c['s5_between_VIClandfrac_p50']=float(np.median(lf[m]))
c['s5_eq0_with_VIC_land']=int((valid&(s5==0)&hasland).sum()); c['s5_eq0_lat_gt_60N']=int((valid&(s5==0)&(latc[:,None]>60)).sum())
c['valid_no_VICland']=int((valid&~hasland).sum()); c['VICland_not_valid']=int((hasland&~valid).sum())
out['closure_classes']=c
# 2. fallback area by share magnitude bins (union time-max shares)
bins=[0,1e-5,1e-4,1e-3,1e-2,1e-1,1.01]
for k in U:
    need=(U[k]>0)&hasland&~P[k]; sh=U[k][need]; ar=(U[k]*cellA)[need]
    h=[(int(((sh>=bins[i])&(sh<bins[i+1])).sum()),float(ar[(sh>=bins[i])&(sh<bins[i+1])].sum()/1e12)) for i in range(len(bins)-1)]
    out.setdefault('fallback_by_share_bin',{})[k]={f'[{bins[i]:g},{bins[i+1]:g})':dict(parents=h[i][0],area_Mkm2=h[i][1]) for i in range(len(h))}
# 3. hybrid M3(found)+M4(rest): recompute found via same search
act_blk=mask.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9)
def found_and_pat(Ek,Pk,need):
    Ek_blk=Ek.reshape(560,3,1440,3).transpose(0,2,1,3).reshape(560,1440,9); pat=np.zeros((560,1440,9),bool); found=np.zeros(need.shape,bool)
    for r in range(1,4):
        for dy in range(-r,r+1):
            for dx in range(-r,r+1):
                if max(abs(dy),abs(dx))!=r: continue
                sh=np.roll(np.roll(Pk,dy,axis=0),dx,axis=1); shE=np.roll(np.roll(Ek_blk,dy,axis=0),dx,axis=1)
                if dy>0: sh[:dy]=False
                if dy<0: sh[dy:]=False
                take=need&~found&sh; pat[take]=shE[take]; found|=take
    return found,pat
E={'rf':v['alloc_rf'],'irr':v['alloc_irr'],'pad':v['alloc_pad'],'urb':v['alloc_urb']}
hyb={}
tot=0
for k in U:
    need=(U[k]>0)&hasland&~P[k]; found,pat=found_and_pat(E[k],P[k],need)
    n3=int((pat&act_blk&found[:,:,None]).sum()); n4=int((need&~found).sum()); hyb[k]=dict(M3_found_tiles=n3,M4_rest=n4,total=n3+n4); tot+=n3+n4
hyb['total']=tot; hyb['pct_of_current']=100*tot/9061423
out['hybrid_M3_M4']=hyb
# 4. 2021-only (bundle A) new tiles per method
rf=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','cropland_rainfed',it); ir=rd('landuse-totals_histsoc_15arcmin_annual_1850_2021.nc','cropland_irrigated',it); rice=rd('landuse-15crops_histsoc_15arcmin_2021.nc','rice_irrigated'); ur=rd('urban_histsoc_2021.nc','urbanareas')
T={'rf':rf,'irr':ir-np.minimum(rice,ir),'pad':np.minimum(rice,ir),'urb':ur}
a={}
for k in T:
    need=(T[k]>0)&hasland&~P[k]; m1=int((np.repeat(np.repeat(need,3,0),3,1)&mask&~E[k]).sum()); found,pat=found_and_pat(E[k],P[k],need)
    a[k]=dict(fallback_parents=int(need.sum()),M1_even=m1,M4_single=int(need.sum()),hybrid=int((pat&act_blk&found[:,:,None]).sum()+(need&~found).sum()),fallback_area_Mkm2=float((T[k]*cellA)[need].sum()/1e12))
a['total']={m:sum(a[k][m] for k in T) for m in ['M1_even','M4_single','hybrid']}
out['bundleA_2021_new_tiles']=a
# 5. which source drives union fallback (irrigated)
json.dump(out,open('extra_union.json','w'),indent=1); print(json.dumps(out,indent=1))
