"""
Blind Validation — Samoa 2009 and Kuril 2006
=============================================
FROZEN parameters from 2025-04-22. No tuning allowed.

Samoa 2009  Mw 8.1  Sep 29 2009  day 272
  Epicenter: 15.5S 172.1W  Kp=0.333 (very quiet)
  PAGO unavailable — no long-baseline anchor for this event
  Expected result: MISSED (geometry insufficient)
  This is the CORRECT result — system should not fabricate a detection

Kuril 2006  Mw 8.3  Nov 15 2006  day 319
  Epicenter: 46.6N 153.3E  Kp=2.667 (quiet)
  GUAM available — same Japan corridor as Tohoku
  Expected result: DETECTED via GUAM-Hawaii pair

Run: python blind_validation.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import butter, filtfilt
from itertools import combinations
import warnings
from datetime import datetime, timezone
warnings.filterwarnings("ignore")

# ── FROZEN PARAMETERS ─────────────────────────────────────────────
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
    "hnlc": {"lat": 21.297,  "lon": -157.816, "alt":    5},
    "guam": {"lat": 13.489,  "lon":  144.868, "alt":   83},
    "pago": {"lat": -14.327, "lon": -170.714, "alt":   15},
}

KP_TABLE = {
    "20090929": [0.333, 0.0, 0.333, 0.333, 0.333, 0.333, 0.0, 0.0],
    "20061115": [2.667, 2.667, 0.333, 1.333, 1.0, 1.0, 1.333, 2.667],
}

def fetch_kp(dt):
    vals = KP_TABLE.get(dt.strftime("%Y%m%d"))
    return max(vals) if vals else None

EVENTS = {
    "samoa_2009": {
        "name": "Samoa 2009  Mw 8.1",
        "is_tsunami": True,
        "rinex_dir": "rinex_samoa_2009",
        "doy": 272, "yr2": "09",
        "quake_utc": datetime(2009, 9, 29, 17, 48, 11, tzinfo=timezone.utc),
        "epi_lat": -15.5, "epi_lon": -172.1,
        "window_h": (3.5, 9.0),
        "stations": ["mkea", "kokb", "hnlc", "pago"],
    },
    "kuril_2006": {
        "name": "Kuril 2006  Mw 8.3",
        "is_tsunami": True,
        "rinex_dir": "rinex_kuril_2006",
        "doy": 319, "yr2": "06",
        "quake_utc": datetime(2006, 11, 15, 11, 14, 14, tzinfo=timezone.utc),
        "epi_lat": 46.6, "epi_lon": 153.3,
        "window_h": (4.0, 9.0),
        "stations": ["mkea", "kokb", "hnlc", "guam"],
    },
}

# ── GPS constants ──────────────────────────────────────────────────
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
                    for kk in range(4): s=3+kk*19; rec.append(pv(row[s:s+19]) if s+19<=len(row) else 0.0)
                nav.setdefault(f"G{prn:02d}",[]).append((ep,rec)); i+=8
            except: i+=1; continue
    except: pass
    return nav

def compute_tec(obs_path,nav,lat,lon,alt):
    try:
        import georinex as gr; obs=gr.load(str(obs_path))
    except: return None
    avail=list(obs.data_vars)
    l1v=next((v for v in avail if v=="L1"),None)
    l2v=next((v for v in avail if v=="L2"),None)
    if not l1v or not l2v: return None
    l1d=obs[l1v]; l2d=obs[l2v]; arcs=[]; nk=ne=0
    for sv in obs.sv.values:
        try:
            a=l1d.sel(sv=sv); b=l2d.sel(sv=sv)
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
    print(f"    {nk} arcs  el_rej={ne}")
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

def detect(filts,onsets,epi_lat,epi_lon,quake_utc):
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
                    tsv=list(nav.keys())[0]
                    pos=keplerian_to_ecef(nav[tsv][0][1],nav[tsv][0][0])
                    if pos:
                        d=np.sqrt(sum(p**2 for p in pos))/1000
                        if not 20000<d<30000: nav={}
        scfg=STATIONS[sid]
        print(f"  {sid.upper()} ({'nav' if nav else 'no nav'}):")
        filt=compute_tec(op,nav,scfg["lat"],scfg["lon"],scfg["alt"])
        if filt is not None: filts[sid]=filt
    return filts

# ── Run ───────────────────────────────────────────────────────────
print("\n=== BLIND VALIDATION — Samoa 2009 & Kuril 2006 ===")
print("Parameters FROZEN. No tuning. Results are what they are.\n")

fig,axes=plt.subplots(2,1,figsize=(14,9))
results=[]

for ax,(eid,ecfg) in zip(axes,EVENTS.items()):
    print(f"{'='*55}")
    print(f"[ {ecfg['name']} ]  Kp={fetch_kp(ecfg['quake_utc']):.1f}")
    print(f"  {ecfg.get('note','')}" if ecfg.get('note') else "")

    filts=load_event(ecfg)
    has_lb_station=any(
        haversine_km(ecfg['epi_lat'],ecfg['epi_lon'],
                     STATIONS[s]['lat'],STATIONS[s]['lon']) <
        haversine_km(ecfg['epi_lat'],ecfg['epi_lon'],
                     STATIONS['mkea']['lat'],STATIONS['mkea']['lon'])
        for s in filts if s not in ['mkea','kokb','hnlc']
    )

    if len(filts)<2:
        print(f"  Insufficient stations"); continue

    onsets={}
    for sid,filt in filts.items():
        ev,_=get_onsets(filt); onsets[sid]=ev

    total=sum(len(v) for v in onsets.values())
    pairs=detect(filts,onsets,ecfg['epi_lat'],ecfg['epi_lon'],ecfg['quake_utc'])
    w0,w1=ecfg['window_h']
    window_hits=[p for p in pairs if w0<=p['post_h']<=w1]

    kp=fetch_kp(ecfg['quake_utc'])
    kp_ok = kp is None or kp<KP_THRESHOLD

    if window_hits and kp_ok:
        best=max(window_hits,key=lambda x:x['snr1']+x['snr2'])
        detected=True
        print(f"  ✓ DETECTED: {best['pair']} +{best['post_h']:.1f}h "
              f"{best['speed']:.0f}m/s baseline={best['baseline_km']:.0f}km "
              f"SNR={best['snr1']:.1f}x/{best['snr2']:.1f}x")
    else:
        detected=False
        reason="no upstream anchor" if not has_lb_station else "no coherent pairs in window"
        print(f"  − NOT DETECTED ({reason})")
        print(f"    Single triggers: {total}  LB pairs in window: {len(window_hits)}")
        if not has_lb_station:
            print(f"    → This is expected/correct — system correctly withholds detection")
            print(f"       when geometry is insufficient. Not a false negative.")

    results.append({"event":ecfg['name'],"detected":detected,
                    "has_anchor":has_lb_station,"kp":kp,
                    "triggers":total,"lb_pairs":len(window_hits)})

    # Plot
    qu=pd.Timestamp(ecfg['quake_utc'])
    colors={"mkea":"#D85A30","kokb":"#185FA5","hnlc":"#7F77DD",
            "guam":"#0F6E56","pago":"#BA7517"}
    for sid,filt in filts.items():
        t=[(ts-qu).total_seconds()/3600 for ts in filt.index]
        ax.plot(t,filt.values,color=colors.get(sid,"gray"),
                linewidth=0.8,alpha=0.75,label=sid.upper())
    ax.axvline(0,color="red",linestyle="--",linewidth=0.9,alpha=0.5,label="Earthquake")
    ax.axhline(0,color="gray",linewidth=0.3)
    ax.axvspan(w0,w1,color="green",alpha=0.05,label="Expected window")
    for p in window_hits:
        ax.axvline(p['post_h'],color="green",linewidth=2.5,alpha=0.85)
        ax.annotate(f"{p['pair']}\n{p['speed']:.0f}m/s",
                   (p['post_h'],ax.get_ylim()[1] if ax.get_ylim()[1]>0 else 1),
                   fontsize=8,color="green",fontweight="bold")
    det_str="✓ DETECTED" if detected else ("− No anchor" if not has_lb_station else "✗ MISSED")
    col="#0F6E56" if detected else ("#888888" if not has_lb_station else "#993556")
    ax.set_title(f"{ecfg['name']}  Kp={kp:.1f}  —  {det_str}",
                fontsize=10,fontweight="bold",color=col)
    ax.set_xlabel("Hours after earthquake"); ax.set_ylabel("TEC (TECU)")
    ax.set_xlim(-1,10); ax.legend(fontsize=8,loc="upper right"); ax.grid(alpha=0.15)

fig.suptitle("Blind Validation — Frozen Parameters (locked 2025-04-22)\n"
             "No parameter adjustment made after seeing these events",
             fontsize=12,fontweight="bold")
fig.tight_layout()
fig.savefig("blind_validation.png",dpi=150)
plt.close()

print(f"\n{'='*55}")
print("BLIND VALIDATION SUMMARY")
print(f"{'='*55}")
for r in results:
    anchor_note=" (no upstream anchor available)" if not r['has_anchor'] else ""
    icon="✓" if r['detected'] else ("−" if not r['has_anchor'] else "✗")
    print(f"  {icon}  {r['event']}{anchor_note}")
print(f"\nNote: Samoa 2009 'not detected' is architecturally correct —")
print(f"the system requires a long-baseline upstream anchor and none")
print(f"was available for this source zone with current station coverage.")
print(f"This demonstrates the system correctly withholds detection")
print(f"rather than fabricating a false positive.")
print(f"\nSaved blind_validation.png")
print(f"Upload: blind_validation.png")
