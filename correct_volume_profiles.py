#!/usr/bin/env python3
"""
TMR-based hourly volume profile correction for QLD traffic databases.

WHAT THIS DOES
--------------
Replaces the flat Austroads %-based hourly distribution with profiles
derived from real TMR count station data — keeping AADT exactly intact.

Two correction strategies:
  - Road-link councils (Gold Coast, Ipswich, Logan, Toowoomba, Tewantin):
      Match each road to a TMR AADT band -> apply that band's real hourly profile.
  - Brisbane (intersection counts):
      Spatially match each intersection to the nearest TMR station(s) within
      SPATIAL_THRESHOLD_KM -> borrow that station's real hourly profile.
      Fallback: Brisbane-region TMR average profile.

AADT IS ALWAYS PRESERVED EXACTLY.
Rounding uses Largest Remainder Method so hourly values sum to original AADT.

USAGE
-----
  python correct_volume_profiles.py [--input-dir DIR] [--output-dir DIR]

Default input-dir  : datasets/QLD
Default output-dir : datasets/QLD/corrected
"""

import argparse, json, math, os
from collections import defaultdict

SPATIAL_THRESHOLD_KM = 2.0
AADT_BANDS = [(0,5000),(5000,15000),(15000,30000),(30000,60000),(60000,10**9)]
BRISBANE_BBOX = {'lat_min':-27.8,'lat_max':-27.1,'lon_min':152.6,'lon_max':153.5}

# ── utils ──────────────────────────────────────────────────────────────────────

def get_hour(s): return int(s.split(' to ')[0])

def get_band(aadt):
    for lo,hi in AADT_BANDS:
        if lo <= aadt < hi: return (lo,hi)
    return AADT_BANDS[-1]

def normalise(lst):
    s = sum(lst)
    if s == 0: return [1/24]*24
    return [v/s for v in lst]

def lrm_round(pcts, total):
    """Largest Remainder Method: distribute total, guarantees exact sum."""
    raw   = [v*total for v in pcts]
    fl    = [int(v) for v in raw]
    rem   = sorted(enumerate(raw), key=lambda x: -(x[1]-int(x[1])))
    short = total - sum(fl)
    for i in range(short): fl[rem[i][0]] += 1
    return fl

def haversine_km(la1,lo1,la2,lo2):
    R=6371.0; dlat=math.radians(la2-la1); dlon=math.radians(lo2-lo1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(la1))*math.cos(math.radians(la2))*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(min(a,1.0)))

def load_gj(path):
    print(f"  Loading {os.path.basename(path)} ...", end=' ', flush=True)
    with open(path,encoding='utf-8') as f: gj=json.load(f)
    print(f"{len(gj['features']):,} features")
    return gj

def save_gj(gj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,'w',encoding='utf-8') as f: json.dump(gj,f,separators=(',',':'))
    print(f"  Saved  {os.path.basename(path)}  ({os.path.getsize(path)/1048576:.1f} MB)")

# ── build TMR profiles ─────────────────────────────────────────────────────────

def build_tmr_profiles(feats):
    wd_raw = defaultdict(lambda:{'lat':None,'lon':None,'dirs':defaultdict(lambda:[0]*24)})
    we_raw = defaultdict(lambda:{'dirs':defaultdict(lambda:[0]*24)})
    for f in feats:
        p=f['properties']; sid=p['SITE_ID']; hr=get_hour(p['HOURS']); dr=p.get('GAZETTAL_DIRECTION','D')
        wd_raw[sid]['lat']=p['LATITUDE']; wd_raw[sid]['lon']=p['LONGITUDE']
        wd_raw[sid]['dirs'][dr][hr]+=p['WEEKDAY_AVERAGE']
        we_raw[sid]['dirs'][dr][hr]+=p['WEEKEND_AVERAGE']

    bwd=defaultdict(list); bwe=defaultdict(list); site_profiles={}
    for sid,sd in wd_raw.items():
        agg_wd=[sum(sd['dirs'][d][h] for d in sd['dirs']) for h in range(24)]
        agg_we=[sum(we_raw[sid]['dirs'][d][h] for d in we_raw[sid]['dirs']) for h in range(24)]
        if sum(agg_wd)==0: continue
        wp=normalise(agg_wd); ep=normalise(agg_we)
        site_profiles[sid]={'lat':sd['lat'],'lon':sd['lon'],'wd_pct':wp,'we_pct':ep,'aadt_wd':sum(agg_wd)}
        b=get_band(sum(agg_wd)); bwd[b].append(wp); bwe[b].append(ep)

    band_profiles={}
    for b in AADT_BANDS:
        if b not in bwd: continue
        n=len(bwd[b])
        band_profiles[b]={
            'wd':normalise([sum(p[h] for p in bwd[b])/n for h in range(24)]),
            'we':normalise([sum(p[h] for p in bwe[b])/n for h in range(24)]),
            'n_sites':n}

    bb=BRISBANE_BBOX; bw=[0.0]*24; be=[0.0]*24; bn=0
    for sp in site_profiles.values():
        if bb['lat_min']<=sp['lat']<=bb['lat_max'] and bb['lon_min']<=sp['lon']<=bb['lon_max']:
            for h in range(24): bw[h]+=sp['wd_pct'][h]; be[h]+=sp['we_pct'][h]
            bn+=1
    bris_fallback={'wd_pct':normalise(bw),'we_pct':normalise(be),'n_sites':bn}
    return band_profiles, site_profiles, bris_fallback

# ── apply profile ──────────────────────────────────────────────────────────────

def apply_profile(group, wd_pct, we_pct, method):
    aadt_wd=sum(f['properties']['WEEKDAY_AVERAGE'] for _,f in group)
    aadt_we=sum(f['properties']['WEEKEND_AVERAGE'] for _,f in group)
    nwd=lrm_round(wd_pct,aadt_wd); nwe=lrm_round(we_pct,aadt_we)
    result=[]
    for h,(idx,f) in enumerate(group):
        result.append((idx,{**f,'properties':{**f['properties'],
            'WEEKDAY_AVERAGE':nwd[h],'WEEKEND_AVERAGE':nwe[h],
            'ORIGINAL_WD':f['properties']['WEEKDAY_AVERAGE'],
            'ORIGINAL_WE':f['properties']['WEEKEND_AVERAGE'],
            'CORRECTION_METHOD':method}}))
    return result

# ── correct road-link councils ─────────────────────────────────────────────────

def correct_link(feats, band_profiles):
    groups=defaultdict(list)
    for i,f in enumerate(feats):
        p=f['properties']; groups[(p['SITE_ID'],p.get('GAZETTAL_DIRECTION',''))].append((i,f))
    corrected=list(feats)
    for key,grp in groups.items():
        grp.sort(key=lambda x:get_hour(x[1]['properties']['HOURS']))
        awd=sum(f['properties']['WEEKDAY_AVERAGE'] for _,f in grp)
        awe=sum(f['properties']['WEEKEND_AVERAGE'] for _,f in grp)
        ref=awd if awd>0 else awe; b=get_band(ref)
        if b not in band_profiles: b=min(band_profiles,key=lambda x:abs((x[0]+x[1])/2-ref))
        bp=band_profiles[b]
        for idx,nf in apply_profile(grp,bp['wd'],bp['we'],f'TMR_BAND_{b[0]}-{b[1]}'): corrected[idx]=nf
    return corrected

# ── correct Brisbane spatial ───────────────────────────────────────────────────

def find_tmr(lat,lon,sps,thresh):
    cands=[(haversine_km(lat,lon,sp['lat'],sp['lon']),sp) for sp in sps.values()
           if haversine_km(lat,lon,sp['lat'],sp['lon'])<=thresh]
    if not cands: return None
    ws=[1/max(d,0.05) for d,_ in cands]; tw=sum(ws)
    wd=[0.0]*24; we=[0.0]*24
    for w,(d,sp) in zip(ws,cands):
        for h in range(24): wd[h]+=w*sp['wd_pct'][h]; we[h]+=w*sp['we_pct'][h]
    return {'wd_pct':normalise([v/tw for v in wd]),'we_pct':normalise([v/tw for v in we]),
            'meta':f"{len(cands)}stations_{min(d for d,_ in cands):.2f}km"}

def correct_brisbane(feats, sps, fallback, thresh=SPATIAL_THRESHOLD_KM):
    groups=defaultdict(list)
    for i,f in enumerate(feats):
        p=f['properties']; groups[(p['SITE_ID'],p.get('GAZETTAL_DIRECTION',''))].append((i,f))
    corrected=list(feats); ns=0; nf=0
    for key,grp in groups.items():
        grp.sort(key=lambda x:get_hour(x[1]['properties']['HOURS']))
        lat=grp[0][1]['properties']['LATITUDE']; lon=grp[0][1]['properties']['LONGITUDE']
        m=find_tmr(lat,lon,sps,thresh)
        if m: wp=m['wd_pct']; ep=m['we_pct']; met=f"TMR_SPATIAL_{m['meta']}"; ns+=1
        else: wp=fallback['wd_pct']; ep=fallback['we_pct']; met='TMR_BRISBANE_REGION_AVG'; nf+=1
        for idx,nf_ in apply_profile(grp,wp,ep,met): corrected[idx]=nf_
    print(f"    Spatial matches : {ns:,}"); print(f"    Fallback (avg)  : {nf:,}")
    return corrected

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-dir',default='datasets/QLD')
    ap.add_argument('--output-dir',default='datasets/QLD/corrected'); args=ap.parse_args()
    inp=args.input_dir; out=args.output_dir

    print("\n[1/5] Loading TMR ..."); tmr=load_gj(os.path.join(inp,'tmr.geojson'))
    print("[2/5] Building TMR profiles ...")
    bp,sps,bfb=build_tmr_profiles(tmr['features'])
    for b,p in sorted(bp.items()):
        print(f"  {b[0]:>6}-{b[1]:<12,} sites={p['n_sites']:>4}  "
              f"night={sum(p['wd'][h] for h in range(5))*100:.2f}%  peak={max(p['wd'])*100:.2f}%")
    print(f"  Brisbane fallback: {bfb['n_sites']} sites, night={sum(bfb['wd_pct'][:5])*100:.2f}%")

    print("\n[3/5] Correcting Brisbane ...")
    gj=load_gj(os.path.join(inp,'brisbane.geojson'))
    gj['features']=correct_brisbane(gj['features'],sps,bfb)
    save_gj(gj,os.path.join(out,'brisbane.geojson'))

    print("\n[4/5] Correcting road-link councils ...")
    for fn in ['goldcoast.geojson','ipswich.geojson','logan.geojson','toowoomba.geojson','tewantin.geojson']:
        fp=os.path.join(inp,fn)
        if not os.path.exists(fp): print(f"  Skip {fn}"); continue
        print(f"  {fn} ..."); gj=load_gj(fp)
        gj['features']=correct_link(gj['features'],bp)
        save_gj(gj,os.path.join(out,fn))

    print(f"\n[5/5] Done. Output: {out}\n")

if __name__=='__main__': main()
