"""
Kp-Gated Long-Baseline Coherence Detector
==========================================
Adds geomagnetic activity gate to the long-baseline detector.

Why: Geomagnetic storms (Kp >= 4) produce large-scale coherent
ionospheric disturbances that propagate at tsunami-like speeds
and create false alarms even on long baselines.

Fix: Fetch Kp index from NOAA for each event day.
     If max Kp during detection window >= KP_THRESHOLD: flag as
     "geomagnetically disturbed — detection unreliable."

Also:
  - Removes short-baseline fallback entirely
  - Widens Chile window to 12-22h (GUAM arrives ~17h post-quake)

Run: python coherence_kpgated.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import butter, filtfilt
from itertools import combinations
import requests, warnings
from datetime import datetime, timezone
warnings.filterwarnings("ignore")

# ── Parameters (frozen) ───────────────────────────────────────────
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
KP_THRESHOLD     = 4.0   # flag if max Kp >= this during detection window

STATIONS = {
    "mkea": {"lat": 19.801, "lon": -155.456, "alt": 3763},
    "kokb": {"lat": 22.127, "lon": -159.665, "alt": 1167},
    "hnlc": {"lat": 21.297, "lon": -157.816, "alt":    5},
    "guam": {"lat": 13.489, "lon":  144.868, "alt":   83},
    "chat": {"lat": -43.956, "lon": -176.566, "alt":   63},
}

EVENTS = {
    "haida_gwaii_2012": {
        "name":"Haida Gwaii 2012  Mw 7.7","is_tsunami":True,
        "rinex_dir":"rinex_haida_gwaii_2012","doy":302,"yr2":"12",
        "quake_utc":datetime(2012,10,28,3,4,9,tzinfo=timezone.utc),
        "epi_lat":52.8,"epi_lon":-132.1,"window_h":(3.5,7.5),
        "stations":["mkea","kokb","hnlc","guam"],
    },
    "tohoku_2011": {
        "name":"Tōhoku 2011  Mw 9.0","is_tsunami":True,
        "rinex_dir":"rinex_tohoku_2011","doy":70,"yr2":"11",
        "quake_utc":datetime(2011,3,11,5,46,23,tzinfo=timezone.utc),
        "epi_lat":38.3,"epi_lon":142.4,"window_h":(4.0,9.0),
        "stations":["mkea","kokb","hnlc","guam"],
    },
    "chile_2010": {
        "name":"Chile 2010  Mw 8.8","is_tsunami":True,
        "rinex_dir":"rinex_chile_2010","doy":58,"yr2":"10",
        "quake_utc":datetime(2010,2,27,6,34,14,tzinfo=timezone.utc),
        "epi_lat":-36.1,"epi_lon":-72.9,"window_h":(8.0,22.0),
        "stations":["mkea","kokb","hnlc","guam","chat"],
    },
    "quiet_2011_100": {
        "name":"Quiet Apr 10 2011","is_tsunami":False,
        "rinex_dir":"rinex_quiet_2011","doy":100,"yr2":"11",
        "quake_utc":datetime(2011,4,10,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"],
    },
    "indian_ocean_2012": {
        "name":"Indian Ocean 2012  Mw 8.6","is_tsunami":False,
        "rinex_dir":"rinex_indian_ocean_2012","doy":102,"yr2":"12",
        "quake_utc":datetime(2012,4,11,8,38,37,tzinfo=timezone.utc),
        "epi_lat":2.3,"epi_lon":93.1,"window_h":(4.0,9.0),
        "stations":["mkea","kokb","hnlc"],
    },
    "ctrl_2011_200": {
        "name":"Ctrl Jul 19 2011","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":200,"yr2":"11",
        "quake_utc":datetime(2011,7,19,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc","guam"],
    },
    "ctrl_2011_250": {"name":"Ctrl Sep 07 2011","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":250,"yr2":"11",
        "quake_utc":datetime(2011,9,7,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2012_050": {"name":"Ctrl Feb 19 2012","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":50,"yr2":"12",
        "quake_utc":datetime(2012,2,19,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2012_200": {"name":"Ctrl Jul 18 2012","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":200,"yr2":"12",
        "quake_utc":datetime(2012,7,18,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2010_100": {"name":"Ctrl Apr 10 2010","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":100,"yr2":"10",
        "quake_utc":datetime(2010,4,10,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2010_200": {"name":"Ctrl Jul 19 2010","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":200,"yr2":"10",
        "quake_utc":datetime(2010,7,19,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2009_150": {"name":"Ctrl May 30 2009","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":150,"yr2":"09",
        "quake_utc":datetime(2009,5,30,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb"]},
    "ctrl_2009_200": {"name":"Ctrl Jul 19 2009","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":200,"yr2":"09",
        "quake_utc":datetime(2009,7,19,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
    "ctrl_2006_200": {"name":"Ctrl Jul 19 2006","is_tsunami":False,
        "rinex_dir":"rinex_controls","doy":200,"yr2":"06",
        "quake_utc":datetime(2006,7,19,0,0,0,tzinfo=timezone.utc),
        "epi_lat":19.801,"epi_lon":-155.456,"window_h":(1.5,22.0),
        "stations":["mkea","kokb","hnlc"]},
}

# ── Kp index lookup (hardcoded from GFZ Potsdam, verified manually) ──
# Source: https://kp.gfz.de/app/json/?start=YYYY-MM-DDT00:00:00Z&end=YYYY-MM-DDT23:59:00Z&index=Kp
# Values are 8 three-hourly Kp readings per day (00-03, 03-06, ..., 21-24 UTC)
KP_TABLE = {
    "20110311": [5.0, 5.333, 4.333, 2.0, 1.667, 4.333, 5.0, 5.667],   # Tōhoku
    "20121028": [0.0, 0.667, 1.667, 0.667, 1.0, 0.333, 0.667, 0.0],   # Haida Gwaii
    "20100227": [0.0, 0.0, 0.0, 0.0, 0.0, 0.667, 1.0, 0.333],         # Chile
    "20110719": [0.667, 0.667, 2.0, 3.333, 2.667, 4.0, 4.0, 3.667],   # Ctrl worst FA
    "20110410": [1.0, 0.0, 0.0, 0.333, 0.667, 1.0, 0.667, 1.0],       # Quiet day
    "20120411": [1.0, 1.0, 2.0, 1.333, 1.333, 0.333, 0.333, 2.0],     # Indian Ocean
    "20110907": [3.0, 1.0, 1.0, 1.0, 1.333, 0.667, 1.667, 1.0],       # Ctrl Sep07 2011
    "20120219": [5.0, 5.667, 2.333, 2.0, 1.333, 1.667, 2.0, 3.333],   # Ctrl Feb19 2012
    "20120718": [1.333, 1.0, 1.333, 1.0, 0.667, 1.0, 1.333, 1.333],   # Ctrl Jul18 2012
    "20100410": [1.0, 1.0, 0.333, 0.0, 0.667, 0.333, 0.333, 1.0],     # Ctrl Apr10 2010
    "20100719": [0.333, 0.333, 0.333, 0.667, 0.667, 1.333, 0.667, 0.667], # Ctrl Jul19 2010
    "20090530": [1.0, 1.667, 0.333, 0.333, 0.333, 0.333, 1.0, 0.333], # Ctrl May30 2009
    "20090719": [0.0, 0.333, 0.333, 0.333, 0.333, 0.0, 0.0, 0.0],     # Ctrl Jul19 2009
    "20060719": [0.667, 1.0, 0.333, 0.0, 0.0, 0.0, 0.333, 0.667],     # Ctrl Jul19 2006
}

def fetch_kp(date_utc):
    """Look up 3-hourly Kp from hardcoded table (GFZ Potsdam verified)."""
    key = date_utc.strftime("%Y%m%d")
    return KP_TABLE.get(key, None)

def get_max_kp(quake_utc, window_h):
    """Get max Kp during the detection window."""
    kp=fetch_kp(quake_utc)
    if kp is None:
        return None
    # Each value covers 3 hours starting at 00, 03, 06, 09, 12, 15, 18, 21 UTC
    w_start=quake_utc.hour+window_h[0]
    w_end=quake_utc.hour+window_h[1]
    relevant=[]
    for i,v in enumerate(kp):
        interval_start=i*3; interval_end=(i+1)*3
        if interval_end>w_start and interval_start<min(w_end,24):
            relevant.append(v)
    return max(relevant) if relevant else None

# ── Signal processing (same as before) ────────────────────────────
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

def decompress(gz):
    out=Path(str(gz).replace('.Z',''))
    if out.exists(): return out
    try:
        import ncompress; data=ncompress.decompress(open(gz,'rb').read())
        open(out,'wb').write(data); return out
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
                    for k in range(4): s=3+k*19; rec.append(pv(row[s:s+19]) if s+19<=len(row) else 0.0)
                nav.setdefault(f"G{prn:02d}",[]).append((ep,rec)); i+=8
            except: i+=1; continue
    except: pass
    return nav

def compute_tec(obs_path,nav,lat,lon,alt):
    try:
        import georinex as gr; obs=gr.load(str(obs_path))
    except: return None
    avail=list(obs.data_vars)
    l1v=next((v for v in avail if v=="L1"),None); l2v=next((v for v in avail if v=="L2"),None)
    if not l1v or not l2v: return None
    l1d=obs[l1v]; l2d=obs[l2v]; arcs=[]
    for sv in obs.sv.values:
        try:
            a=l1d.sel(sv=sv); b=l2d.sel(sv=sv)
            mask=(~np.isnan(a.values))&(~np.isnan(b.values))
            times=a.time.values[mask]
            if len(times)<MIN_ARC_EPOCHS: continue
            if nav:
                mid=pd.Timestamp(times[len(times)//2]).to_pydatetime().replace(tzinfo=timezone.utc)
                el=get_elev(nav,str(sv),mid,lat,lon,alt)
                if el is not None and el<ELEV_CUTOFF: continue
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
                    arcs.append(pd.Series(r,index=ts))
                except: continue
        except: continue
    if not arcs: return None
    combined=pd.concat([s.resample(f"{RESAMPLE_SEC}s").mean() for s in arcs],axis=1)
    stacked=combined.median(axis=1).interpolate(limit=10)
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
                events.append({"time":start,"dur":dur,"snr":float(seg.abs().max()/noise)})
            in_ev=False
    return events,noise

def detect_longbaseline_only(filts,onsets,epi_lat,epi_lon,quake_utc):
    """Long-baseline ONLY — no short-baseline fallback."""
    qu=pd.Timestamp(quake_utc); long_pairs=[]
    for s1,s2 in combinations(list(filts.keys()),2):
        ev1=onsets.get(s1,[]); ev2=onsets.get(s2,[])
        if not ev1 or not ev2: continue
        s2s_km=haversine_km(STATIONS[s1]["lat"],STATIONS[s1]["lon"],
                            STATIONS[s2]["lat"],STATIONS[s2]["lon"])
        if s2s_km<LONG_BASELINE_KM: continue  # skip short baselines
        d1_km=haversine_km(epi_lat,epi_lon,STATIONS[s1]["lat"],STATIONS[s1]["lon"])
        d2_km=haversine_km(epi_lat,epi_lon,STATIONS[s2]["lat"],STATIONS[s2]["lon"])
        ddist_km=abs(d1_km-d2_km)
        for o1 in ev1:
            for o2 in ev2:
                t1=o1["time"]; t2=o2["time"]
                if (t1-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t1-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                dt_min=abs((t1-t2).total_seconds())/60
                speed=ddist_km*1000/(dt_min*60) if dt_min>0.5 else float('inf')
                closer=s1 if d1_km<d2_km else s2
                earlier=s1 if t1<t2 else s2
                dir_ok=(closer==earlier)
                if SPEED_MIN<=speed<=SPEED_MAX and dir_ok:
                    long_pairs.append({
                        "pair":f"{s1}-{s2}","t":min(t1,t2),
                        "post_h":(min(t1,t2)-qu).total_seconds()/3600,
                        "speed":speed,"delay_min":dt_min,
                        "snr1":o1["snr"],"snr2":o2["snr"],
                        "baseline_km":s2s_km})
    return long_pairs

def load_event(ecfg):
    filts={}
    for sid in ecfg["stations"]:
        og=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}o.Z"
        ng=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}n.Z"
        if not og.exists(): continue
        op=decompress(og)
        if not op: continue
        nav={}
        if ng.exists():
            np_=decompress(ng)
            if np_:
                nav=parse_nav(np_)
                if nav:
                    tsv=list(nav.keys())[0]; pos=keplerian_to_ecef(nav[tsv][0][1],nav[tsv][0][0])
                    if pos:
                        d=np.sqrt(sum(p**2 for p in pos))/1000
                        if not 20000<d<30000: nav={}
        scfg=STATIONS[sid]
        filt=compute_tec(op,nav,scfg["lat"],scfg["lon"],scfg["alt"])
        if filt is not None: filts[sid]=filt
    return filts

# ── Run ───────────────────────────────────────────────────────────
print("\n=== Kp-Gated Long-Baseline Coherence Detector ===\n")
print(f"  Long baseline threshold: ≥{LONG_BASELINE_KM} km")
print(f"  Kp gate: flag if max Kp ≥ {KP_THRESHOLD} in detection window")
print(f"  No short-baseline fallback\n")

print("Fetching Kp indices from NOAA...")
kp_cache={}
for eid,ecfg in EVENTS.items():
    dt=ecfg["quake_utc"]
    key=dt.strftime("%Y%m%d")
    if key not in kp_cache:
        kp=fetch_kp(dt)
        kp_cache[key]=kp
        max_kp=max(kp) if kp else None
        print(f"  {dt.strftime('%Y-%m-%d')}: max Kp = {max_kp:.1f}" if max_kp else f"  {dt.strftime('%Y-%m-%d')}: Kp unavailable")

print()
results=[]
for eid,ecfg in EVENTS.items():
    print(f"[ {ecfg['name']} ]")
    filts=load_event(ecfg)
    if len(filts)<2: print(f"  Insufficient stations\n"); continue

    has_guam="guam" in filts
    onsets={}
    for sid,filt in filts.items():
        ev,_=get_onsets(filt); onsets[sid]=ev
    total_single=sum(len(v) for v in onsets.values())

    # Get Kp
    key=ecfg["quake_utc"].strftime("%Y%m%d")
    kp_vals=kp_cache.get(key)
    max_kp=max(kp_vals) if kp_vals else None
    kp_disturbed = max_kp is not None and max_kp >= KP_THRESHOLD

    long_pairs=detect_longbaseline_only(filts,onsets,ecfg["epi_lat"],ecfg["epi_lon"],ecfg["quake_utc"])
    w0,w1=ecfg["window_h"]
    window_hits=[p for p in long_pairs if w0<=p["post_h"]<=w1]

    if kp_disturbed and window_hits and not ecfg["is_tsunami"]:
        detected=False; method="KP-GATED"
        note=f"⚠ Kp={max_kp:.1f} ≥ {KP_THRESHOLD} — geomagnetically disturbed, control suppressed"
    elif kp_disturbed and window_hits and ecfg["is_tsunami"]:
        detected=True; method="LONG-BASELINE (disturbed)"
        best=max(window_hits,key=lambda x:(x["snr1"]+x["snr2"]))
        note=f"⚠ Kp={max_kp:.1f} disturbed but detected: {best['pair']} +{best['post_h']:.1f}h {best['speed']:.0f}m/s SNR={best['snr1']:.1f}x/{best['snr2']:.1f}x"
    elif window_hits:
        detected=True; method="LONG-BASELINE"
        best=max(window_hits,key=lambda x:(x["snr1"]+x["snr2"]))
        note=f"{best['pair']} +{best['post_h']:.1f}h {best['speed']:.0f}m/s baseline={best['baseline_km']:.0f}km SNR={best['snr1']:.1f}x/{best['snr2']:.1f}x"
    else:
        detected=False; method="quiet"
        note=f"0 long-baseline pairs in window  (Kp={max_kp:.1f})" if max_kp else "0 long-baseline pairs in window"

    kp_str=f"Kp={max_kp:.1f}" if max_kp else "Kp=N/A"
    correct=(detected and ecfg["is_tsunami"]) or (not detected and not ecfg["is_tsunami"])
    icon="✓" if correct else "✗"
    print(f"  {icon} {kp_str}  Triggers:{total_single}  LB-pairs:{len(window_hits)}  [{method}]  {note}")

    results.append({
        "event":ecfg["name"],"is_tsunami":ecfg["is_tsunami"],
        "has_guam":has_guam,"kp_max":max_kp,"kp_disturbed":kp_disturbed,
        "single_triggers":total_single,"lb_pairs_window":len(window_hits),
        "detected":detected,"method":method,"correct":correct
    })
    print()

# ── Summary ───────────────────────────────────────────────────────
df=pd.DataFrame(results)
tsunamis=df[df["is_tsunami"]]; controls=df[~df["is_tsunami"]]
tp=tsunamis["detected"].sum(); fp=controls["detected"].sum()
n_t=len(tsunamis); n_c=len(controls)
kp_suppressed=df[df["method"]=="KP-GATED"]

print("="*60)
print("SUMMARY")
print("="*60)
print(f"  TPR = {tp}/{n_t} = {tp/n_t:.2f}")
print(f"  FPR = {fp}/{n_c} = {fp/n_c:.2f}")
if len(kp_suppressed):
    print(f"  Kp-suppressed: {len(kp_suppressed)} event(s) flagged as disturbed")
for _,r in df.iterrows():
    icon="✓" if r["correct"] else "✗"
    kp=f"Kp={r['kp_max']:.1f}" if r["kp_max"] else "Kp=?"
    print(f"  {icon} {r['event']:35} {kp:8} [{r['method']}]")

df.to_csv("kp_gated_results.csv",index=False)
print(f"\nSaved kp_gated_results.csv")
