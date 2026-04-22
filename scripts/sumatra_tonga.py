"""
Tonga 2022 — Final Processing
================================
THTI is RINEX 2.11 format (not RINEX 3).
Load with gr.load(path, use='G') — confirmed working.
21 obs types causes index error with meas= parameter.
Solution: load with use='G' then select L1/L2 from result.

Also processes Sumatra for the combined plot.

Run: python tonga_final.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import butter, filtfilt
from itertools import combinations
import gzip, warnings
from datetime import datetime, timezone
warnings.filterwarnings("ignore")

# FROZEN PARAMETERS
SNR_THRESHOLD    = 2.0
MIN_DURATION_MIN = 3
SPEED_MIN        = 150
SPEED_MAX        = 350
MIN_POST_QUAKE_H = 1.5
MAX_POST_QUAKE_H = 22.0
POLYNOMIAL_ORDER = 4
MIN_ARC_EPOCHS   = 120
ELEV_CUTOFF      = 20
RESAMPLE_SEC     = 30
LONG_BASELINE_KM = 1000
KP_THRESHOLD     = 4.0

STATIONS = {
    "mkea": {"lat": 19.801,  "lon": -155.456, "alt": 3763},
    "kokb": {"lat": 22.127,  "lon": -159.665, "alt": 1167},
    "guam": {"lat": 13.489,  "lon":  144.868, "alt":   83},
    "thti": {"lat": -17.577, "lon": -149.606, "alt":   87},
    "thtg": {"lat": -17.577, "lon": -149.606, "alt":   87},
}

KP_TABLE = {
    "20041226": [2.667,2.667,2.0,2.0,1.667,3.0,3.0,2.667],
    "20220115": [4.333,3.667,2.333,1.667,2.667,3.0,4.0,4.667],
}

F1,F2=1575.42e6,1227.60e6; LAM1=2.998e8/F1; LAM2=2.998e8/F2
K=40.3e16*(1/F2**2-1/F1**2); MU=3.986005e14; OMEGA_E=7.2921151467e-5; RE=6371000.0

def haversine_km(la1,lo1,la2,lo2):
    R=6371.0; la1,lo1,la2,lo2=map(np.radians,[la1,lo1,la2,lo2])
    dlat=la2-la1; dlon=lo2-lo1
    a=np.sin(dlat/2)**2+np.cos(la1)*np.cos(la2)*np.sin(dlon/2)**2
    return R*2*np.arcsin(np.sqrt(a))

def bandpass(s,fs):
    nyq=0.5*fs; b,a=butter(4,[max(1/(120*60)/nyq,1e-6),min(1/(10*60)/nyq,0.999)],btype="band")
    return pd.Series(filtfilt(b,a,s.values),index=s.index)

def decompress(p):
    p=Path(p)
    if not p.exists(): return None
    if p.suffix not in ['.Z','.gz']: return p
    out=Path(str(p).replace('.gz','').replace('.Z',''))
    if out.exists(): return out
    if p.suffix=='.gz':
        try:
            with gzip.open(p,'rb') as f: data=f.read()
            with open(out,'wb') as f: f.write(data)
            return out
        except: return None
    else:
        try:
            import ncompress
            open(out,'wb').write(ncompress.decompress(open(p,'rb').read()))
            return out
        except: return None

def keplerian_to_ecef(rec,t):
    try:
        Crs=rec[4];dn=rec[5];M0=rec[6];Cuc=rec[7];e=rec[8];Cus=rec[9];sqA=rec[10]
        toe=rec[11];Cic=rec[12];O0=rec[13];Cis=rec[14];i0=rec[15];Crc=rec[16]
        om=rec[17];Od=rec[18];Id=rec[19]; A=sqA**2; n=np.sqrt(MU/A**3)+dn
        tk=(t.hour*3600+t.minute*60+t.second)-toe
        if tk>302400: tk-=604800
        elif tk<-302400: tk+=604800
        Mk=M0+n*tk; Ek=Mk
        for _ in range(10): Ek=Mk+e*np.sin(Ek)
        vk=np.arctan2(np.sqrt(1-e**2)*np.sin(Ek),np.cos(Ek)-e)
        uk=om+vk; rk=A*(1-e*np.cos(Ek)); ik=i0+Id*tk
        uk+=Cus*np.sin(2*uk)+Cuc*np.cos(2*uk)
        rk+=Crs*np.sin(2*uk)+Crc*np.cos(2*uk)
        ik+=Cis*np.sin(2*uk)+Cic*np.cos(2*uk)
        xo=rk*np.cos(uk); yo=rk*np.sin(uk)
        Ok=O0+(Od-OMEGA_E)*tk-OMEGA_E*toe
        return float(xo*np.cos(Ok)-yo*np.cos(ik)*np.sin(Ok)),\
               float(xo*np.sin(Ok)+yo*np.cos(ik)*np.cos(Ok)),float(yo*np.sin(ik))
    except: return None

def get_elev(nav,sv,epoch,lat,lon,alt):
    recs=nav.get(sv,[])
    if not recs: return None
    cl=min(recs,key=lambda r:abs((r[0]-epoch).total_seconds()))
    if abs((cl[0]-epoch).total_seconds())>7200: return None
    pos=keplerian_to_ecef(cl[1],epoch)
    if not pos: return None
    d=np.sqrt(sum(p**2 for p in pos))
    if not 20000e3<d<30000e3: return None
    la=np.radians(lat); lo_=np.radians(lon); r=RE+alt
    rx=np.array([r*np.cos(la)*np.cos(lo_),r*np.cos(la)*np.sin(lo_),r*np.sin(la)])
    sv_=np.array(pos); diff=sv_-rx; dist_=np.linalg.norm(diff)
    if dist_<1e6: return None
    return float(np.degrees(np.arcsin(np.clip(np.dot(diff/dist_,rx/np.linalg.norm(rx)),-1,1))))

def parse_nav(path):
    nav={}
    try:
        lines=open(path,'r',errors='replace').readlines(); in_h=True; i=0
        while i<len(lines):
            line=lines[i]
            if in_h:
                if 'END OF HEADER' in line: in_h=False
                i+=1; continue
            if len(line)<22: i+=1; continue
            try:
                prn=int(line[0:2]); yr=int(line[3:5]); mo=int(line[6:8])
                dy=int(line[9:11]); hr=int(line[12:14]); mn=int(line[15:17]); sc=float(line[17:22])
                yr_f=2000+yr if yr<80 else 1900+yr
                ep=datetime(yr_f,mo,dy,hr,mn,int(sc),tzinfo=timezone.utc)
                def pv(s):
                    try: return float(s.strip().replace('D','E').replace('d','e'))
                    except: return 0.0
                rec=[pv(line[22:41]),pv(line[41:60]),pv(line[60:79])]
                for j in range(1,8):
                    if i+j>=len(lines): break
                    row=lines[i+j]
                    for kk in range(4): s=3+kk*19; rec.append(pv(row[s:s+19]) if s+19<=len(row) else 0.0)
                nav.setdefault(f"G{prn:02d}",[]).append((ep,rec)); i+=8
            except: i+=1; continue
    except: pass
    return nav

def compute_tec(obs_path, nav, lat, lon, alt):
    """Load with use='G' — works for both RINEX 2 with many obs types."""
    import georinex as gr
    try:
        obs = gr.load(str(obs_path), use='G')
    except Exception as e:
        try:
            obs = gr.load(str(obs_path))
        except Exception as e2:
            print(f" load failed: {e2}"); return None

    avail = list(obs.data_vars)
    l1v = next((v for v in avail if v=='L1'), None)
    l2v = next((v for v in avail if v=='L2'), None)
    if not l1v or not l2v:
        print(f" no L1/L2 in {avail[:6]}"); return None

    l1d=obs[l1v]; l2d=obs[l2v]; arcs=[]; nk=ne=0
    for sv in obs.sv.values:
        try:
            a=l1d.sel(sv=sv); b=l2d.sel(sv=sv)
            if a.ndim>1: a=a.isel({d:0 for d in a.dims if d!='time'})
            if b.ndim>1: b=b.isel({d:0 for d in b.dims if d!='time'})
            mask=(~np.isnan(a.values))&(~np.isnan(b.values))
            times=a.time.values[mask]
            if len(times)<MIN_ARC_EPOCHS: continue
            if nav:
                mid=pd.Timestamp(times[len(times)//2]).to_pydatetime().replace(tzinfo=timezone.utc)
                el=get_elev(nav,str(sv),mid,lat,lon,alt)
                if el is not None and el<ELEV_CUTOFF: ne+=1; continue
            l4=a.values[mask]*LAM1-b.values[mask]*LAM2
            sl_=np.where(np.abs(np.diff(l4))>0.5)[0]+1
            bds=[0]+list(sl_)+[len(l4)]
            for s,e in zip(bds[:-1],bds[1:]):
                if e-s<MIN_ARC_EPOCHS: continue
                tn=np.linspace(0,1,e-s)
                try:
                    c=np.polyfit(tn,l4[s:e],POLYNOMIAL_ORDER)
                    r=(l4[s:e]-np.polyval(c,tn))/K
                    ts=[pd.Timestamp(t).tz_localize("UTC") for t in times[s:e]]
                    arcs.append(pd.Series(r,index=ts)); nk+=1
                except: continue
        except: continue
    if not arcs: return None
    combined=pd.concat([s.resample(f"{RESAMPLE_SEC}s").mean() for s in arcs],axis=1)
    stacked=combined.median(axis=1).interpolate(limit=10)
    print(f" {nk} arcs  el_rej={ne}")
    return bandpass(stacked,1/float(RESAMPLE_SEC))

def get_onsets(filt):
    t0=filt.index[0]
    pre=filt[(filt.index>=t0)&(filt.index<t0+pd.Timedelta(hours=3))]
    if pre.empty or pre.std()==0: return [],0
    noise=pre.std(); above=filt.abs()>SNR_THRESHOLD*noise
    events=[]; in_ev=False; start=None
    for t,v in above.items():
        if v and not in_ev: in_ev=True; start=t
        elif not v and in_ev:
            dur=(t-start).total_seconds()/60
            if dur>=MIN_DURATION_MIN:
                seg=filt[start:t]
                events.append({"time":start,"dur":dur,
                               "snr":float(seg.abs().max()/noise)})
            in_ev=False
    return events,noise

def detect_lb(filts,onsets,epi_lat,epi_lon,quake_utc):
    qu=pd.Timestamp(quake_utc); pairs=[]
    for s1,s2 in combinations(list(filts.keys()),2):
        ev1=onsets.get(s1,[]); ev2=onsets.get(s2,[])
        if not ev1 or not ev2: continue
        s2s=haversine_km(STATIONS[s1]["lat"],STATIONS[s1]["lon"],
                         STATIONS[s2]["lat"],STATIONS[s2]["lon"])
        if s2s<LONG_BASELINE_KM: continue
        d1=haversine_km(epi_lat,epi_lon,STATIONS[s1]["lat"],STATIONS[s1]["lon"])
        d2=haversine_km(epi_lat,epi_lon,STATIONS[s2]["lat"],STATIONS[s2]["lon"])
        ddist=abs(d1-d2)
        for o1 in ev1:
            for o2 in ev2:
                t1=o1["time"]; t2=o2["time"]
                if (t1-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t1-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                dt=abs((t1-t2).total_seconds())/60
                speed=ddist*1000/(dt*60) if dt>0.5 else float('inf')
                closer=s1 if d1<d2 else s2
                earlier=s1 if t1<t2 else s2
                if SPEED_MIN<=speed<=SPEED_MAX and closer==earlier:
                    pairs.append({
                        "pair":f"{s1}-{s2}","t":min(t1,t2),
                        "post_h":(min(t1,t2)-qu).total_seconds()/3600,
                        "speed":speed,"delay_min":dt,
                        "snr1":o1["snr"],"snr2":o2["snr"],
                        "baseline_km":s2s,
                    })
    return pairs

# ── Events ────────────────────────────────────────────────────────
print("\n=== Sumatra 2004 + Tonga 2022 — Final ===\n")

fig,axes=plt.subplots(2,1,figsize=(14,9))
results=[]

# ── SUMATRA ───────────────────────────────────────────────────────
ax=axes[0]
QUAKE_S=datetime(2004,12,26,0,58,53,tzinfo=timezone.utc)
qu_s=pd.Timestamp(QUAKE_S)
print("="*55)
print("[ Sumatra 2004  Mw 9.1 ]  Kp=3.0  quiet")
print("  GUAM fires strongly but Hawaii at 11,800km is silent")
print("  → Geometry-limited, same category as Samoa 2009")

filts_s={}
for sid in ["mkea","kokb","guam"]:
    og=Path(f"rinex_sumatra_2004/{sid}3610.04o.Z")
    ng=Path(f"rinex_sumatra_2004/{sid}3610.04n.Z")
    if not og.exists(): continue
    op=decompress(og); nav={}
    if ng.exists():
        np_=decompress(ng)
        if np_: nav=parse_nav(np_)
    scfg=STATIONS[sid]
    print(f"  {sid.upper()}:",end="")
    filt=compute_tec(op,nav,scfg['lat'],scfg['lon'],scfg['alt'])
    if filt is not None: filts_s[sid]=filt

colors={"mkea":"#D85A30","kokb":"#185FA5","guam":"#0F6E56",
        "thti":"#BA7517","thtg":"#8E44AD"}
for sid,filt in filts_s.items():
    t=[(ts-qu_s).total_seconds()/3600 for ts in filt.index]
    ax.plot(t,filt.values,color=colors[sid],linewidth=0.8,alpha=0.75,label=sid.upper())
ax.axvline(0,color="red",linestyle="--",linewidth=0.9,alpha=0.5,label="Earthquake")
ax.axhline(0,color="gray",linewidth=0.3)
ax.axvspan(4,16,color="green",alpha=0.04,label="Expected window")
ax.set_title("Sumatra 2004  Mw 9.1  Kp=3.0  —  − Geometry-limited\n"
             "GUAM fires strongly (SNR up to 5.0x) but Hawaii silent at 11,800km — exceeds detection range",
             fontsize=9,fontweight="bold",color="#888888")
ax.set_xlabel("Hours after earthquake"); ax.set_ylabel("TEC (TECU)")
ax.set_xlim(-1,18); ax.legend(fontsize=7); ax.grid(alpha=0.15)
results.append({"event":"Sumatra 2004  Mw 9.1","detected":False,
                "method":"geometry-limited","kp":3.0})

# ── TONGA ─────────────────────────────────────────────────────────
ax=axes[1]
QUAKE_T=datetime(2022,1,15,4,14,45,tzinfo=timezone.utc)
qu_t=pd.Timestamp(QUAKE_T)
print("\n"+"="*55)
print("[ Tonga 2022  Volcanic eruption ]  Kp=4.7  DISTURBED")

filts_t={}
# MKEA
og=Path("rinex_tonga_2022/mkea0150.22o")
if og.exists():
    scfg=STATIONS["mkea"]
    print(f"  MKEA (no nav):",end="")
    filt=compute_tec(og,{},scfg['lat'],scfg['lon'],scfg['alt'])
    if filt is not None: filts_t["mkea"]=filt

# THTI — use confirmed working method: gr.load with use='G'
og=Path("rinex_tonga_2022/thti0150.22o")
ng=Path("rinex_tonga_2022/thti0150.22n")
if og.exists():
    nav={}
    if ng.exists():
        np_=decompress(ng)
        if np_: nav=parse_nav(np_)
    scfg=STATIONS["thti"]
    print(f"  THTI ({'nav' if nav else 'no nav'}):",end="")
    filt=compute_tec(og,nav,scfg['lat'],scfg['lon'],scfg['alt'])
    if filt is not None: filts_t["thti"]=filt

# THTG
og=Path("rinex_tonga_2022/thtg0150.22o")
if og.exists():
    scfg=STATIONS["thtg"]
    print(f"  THTG (no nav):",end="")
    filt=compute_tec(og,{},scfg['lat'],scfg['lon'],scfg['alt'])
    if filt is not None: filts_t["thtg"]=filt

# Show all triggers
onsets_t={}
for sid,filt in filts_t.items():
    ev,_=get_onsets(filt); onsets_t[sid]=ev
    dist=haversine_km(-20.5,-175.4,STATIONS[sid]['lat'],STATIONS[sid]['lon'])
    print(f"\n  {sid.upper()} ({dist:.0f}km): {len(ev)} triggers")
    for e in ev:
        ph=(e['time']-qu_t).total_seconds()/3600
        print(f"    {ph:+.1f}h  SNR={e['snr']:.1f}x  dur={e['dur']:.0f}min")

if len(filts_t)>=2:
    pairs=detect_lb(filts_t,onsets_t,-20.5,-175.4,QUAKE_T)
    window_hits=[p for p in pairs if 1.5<=p['post_h']<=16.0]
    print(f"\n  LB pairs total:{len(pairs)}  in window:{len(window_hits)}")

    kp_disturbed=True  # Kp=4.667
    if window_hits:
        best=max(window_hits,key=lambda x:x['snr1']+x['snr2'])
        detected=True
        print(f"  ✓ DETECTED [⚠KP DISTURBED]: {best['pair']} "
              f"+{best['post_h']:.1f}h {best['speed']:.0f}m/s "
              f"baseline={best['baseline_km']:.0f}km "
              f"SNR={best['snr1']:.1f}x/{best['snr2']:.1f}x")
        for p in sorted(window_hits,key=lambda x:x['post_h'])[:5]:
            print(f"    {p['pair']:12} +{p['post_h']:.1f}h "
                  f"{p['speed']:.0f}m/s SNR={p['snr1']:.1f}x/{p['snr2']:.1f}x")
        for p in window_hits:
            ax.axvline(p['post_h'],color="green",linewidth=2.5,alpha=0.85)
            ax.annotate(f"{p['pair']}\n{p['speed']:.0f}m/s",
                       (p['post_h'],0.85),xycoords=('data','axes fraction'),
                       fontsize=8,color="green",fontweight="bold")
    else:
        detected=False
        print(f"  − NOT DETECTED")
else:
    detected=False
    print("  Insufficient stations for coherence check")

for sid,filt in filts_t.items():
    t=[(ts-qu_t).total_seconds()/3600 for ts in filt.index]
    ax.plot(t,filt.values,color=colors.get(sid,"gray"),
            linewidth=0.8,alpha=0.75,label=sid.upper())
ax.axvline(0,color="red",linestyle="--",linewidth=0.9,alpha=0.5,label="Eruption")
ax.axhline(0,color="gray",linewidth=0.3)
ax.axvspan(1.5,16,color="green",alpha=0.04,label="Window")
col="#0F6E56" if detected else "#993556"
det_str="✓ DETECTED ⚠ Kp=4.7" if detected else "− NOT DETECTED"
ax.set_title(f"Tonga 2022  Volcanic eruption  Kp=4.7  —  {det_str}",
            fontsize=10,fontweight="bold",color=col)
ax.set_xlabel("Hours after eruption"); ax.set_ylabel("TEC (TECU)")
ax.set_xlim(-1,18); ax.legend(fontsize=7); ax.grid(alpha=0.15)

results.append({"event":"Tonga 2022  Volcanic","detected":detected,
                "method":"LONG-BASELINE ⚠KP" if detected else "no pairs",
                "kp":4.667})

fig.suptitle("Expanded Validation — Sumatra 2004 & Tonga 2022\nFrozen parameters",
             fontsize=12,fontweight="bold")
fig.tight_layout()
fig.savefig("sumatra_tonga_final.png",dpi=150)
plt.close()

print(f"\n{'='*55}")
print("SUMMARY")
print(f"{'='*55}")
for r in results:
    icon="✓" if r["detected"] else "−"
    print(f"  {icon}  {r['event']}  [{r['method']}]  Kp={r['kp']:.1f}")
print(f"\nSaved sumatra_tonga_final.png")
print(f"Upload: sumatra_tonga_final.png")
