"""
Peru 2001 — Two-Day Processing
================================
Quake at 20:33 UTC day 174. Detection window +10-16h = 06:33-12:33 UTC day 175.
Day 174 RINEX ends at midnight — need day 175 files for the full window.

Run: python peru_twoday.py
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

SNR_THRESHOLD=2.0; MIN_DURATION_MIN=3; SPEED_MIN=150; SPEED_MAX=350
MIN_POST_QUAKE_H=1.5; MAX_POST_QUAKE_H=22.0; POLYNOMIAL_ORDER=4
MIN_ARC_EPOCHS=120; ELEV_CUTOFF=20; RESAMPLE_SEC=30; LONG_BASELINE_KM=1000

STATIONS = {
    "mkea": {"lat": 19.801,  "lon": -155.456, "alt": 3763},
    "kokb": {"lat": 22.127,  "lon": -159.665, "alt": 1167},
    "hnlc": {"lat": 21.297,  "lon": -157.816, "alt":    5},
    "chat": {"lat": -43.956, "lon": -176.566, "alt":   63},
}

QUAKE_UTC = datetime(2001, 6, 23, 20, 33, 14, tzinfo=timezone.utc)
EPI_LAT, EPI_LON = -16.3, -73.6
TIDE_M = 0.282
TIDE_DIST_KM = 10500
MW = 8.4
CALIB_A=2283.839; CALIB_B=0.771; CALIB_C=2.614

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

def compute_tec_twoday(obs1, obs2, nav, lat, lon, alt):
    """Load two consecutive RINEX obs files and concatenate arcs."""
    import georinex as gr
    arcs = []; nk = ne = 0

    for obs_path in [obs1, obs2]:
        if obs_path is None or not Path(obs_path).exists():
            continue
        try:
            obs = gr.load(str(obs_path))
        except Exception as e:
            print(f"  load failed {obs_path}: {e}"); continue

        avail = list(obs.data_vars)
        l1v = next((v for v in avail if v=="L1"), None)
        l2v = next((v for v in avail if v=="L2"), None)
        if not l1v or not l2v: continue
        l1d=obs[l1v]; l2d=obs[l2v]

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
    print(f"  {nk} arcs  el_rej={ne}")
    # Use first 3 hours of day 174 for noise baseline — bandpass over full span
    return bandpass(stacked, 1/float(RESAMPLE_SEC))

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

def detect_lb(filts,onsets):
    qu=pd.Timestamp(QUAKE_UTC); pairs=[]
    for s1,s2 in combinations(list(filts.keys()),2):
        ev1=onsets.get(s1,[]); ev2=onsets.get(s2,[])
        if not ev1 or not ev2: continue
        s2s=haversine_km(STATIONS[s1]["lat"],STATIONS[s1]["lon"],
                         STATIONS[s2]["lat"],STATIONS[s2]["lon"])
        if s2s<LONG_BASELINE_KM: continue
        d1=haversine_km(EPI_LAT,EPI_LON,STATIONS[s1]["lat"],STATIONS[s1]["lon"])
        d2=haversine_km(EPI_LAT,EPI_LON,STATIONS[s2]["lat"],STATIONS[s2]["lon"])
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

# ── Run ───────────────────────────────────────────────────────────
print("\n=== Peru 2001 Mw 8.4 — Two-Day Processing ===")
print("Quake: 20:33 UTC Jun 23  |  Window: +10-16h = 06:33-12:33 UTC Jun 24\n")

filts = {}
DIR = Path("rinex_peru_2001")

for sid in ["mkea","kokb","hnlc","chat"]:
    o1 = DIR/f"{sid}1740.01o.Z"
    o2 = DIR/f"{sid}1750.01o.Z"
    n1 = DIR/f"{sid}1740.01n.Z"
    n2 = DIR/f"{sid}1750.01n.Z"

    op1 = decompress(o1) if o1.exists() else None
    op2 = decompress(o2) if o2.exists() else None

    if not op1 and not op2:
        print(f"  {sid.upper()}: no files"); continue

    # Load nav — prefer day 174, fall back to 175
    nav = {}
    for nf in [n1, n2]:
        if nf.exists():
            np_ = decompress(nf)
            if np_:
                nav = parse_nav(np_)
                if nav:
                    tsv=list(nav.keys())[0]; pos=keplerian_to_ecef(nav[tsv][0][1],nav[tsv][0][0])
                    if pos:
                        d=np.sqrt(sum(p**2 for p in pos))/1000
                        if not 20000<d<30000: nav={}
                    if nav: break

    print(f"  {sid.upper()} ({'nav' if nav else 'no nav'} | "
          f"d174={'✓' if op1 else '✗'} d175={'✓' if op2 else '✗'}):", end="")
    filt = compute_tec_twoday(op1, op2, nav,
                               STATIONS[sid]['lat'],
                               STATIONS[sid]['lon'],
                               STATIONS[sid]['alt'])
    if filt is not None: filts[sid] = filt

print()
onsets = {}
qu = pd.Timestamp(QUAKE_UTC)
for sid, filt in filts.items():
    ev, _ = get_onsets(filt); onsets[sid] = ev
    dist = haversine_km(EPI_LAT, EPI_LON, STATIONS[sid]['lat'], STATIONS[sid]['lon'])
    triggers_in_window = [e for e in ev
                         if 10.0 <= (e['time']-qu).total_seconds()/3600 <= 16.0]
    print(f"  {sid.upper()} ({dist:.0f}km): {len(ev)} total triggers, "
          f"{len(triggers_in_window)} in window")
    for e in ev:
        ph = (e['time']-qu).total_seconds()/3600
        if -2 <= ph <= 18:
            print(f"    {ph:+.1f}h  SNR={e['snr']:.1f}x  dur={e['dur']:.0f}min")

pairs = detect_lb(filts, onsets)
window_hits = [p for p in pairs if 10.0<=p['post_h']<=16.0]
print(f"\nLong-baseline pairs: {len(pairs)} total, {len(window_hits)} in window")

if window_hits:
    best = max(window_hits, key=lambda x: x['snr1']+x['snr2'])
    print(f"\n✓ DETECTED: {best['pair']} +{best['post_h']:.1f}h "
          f"{best['speed']:.0f}m/s baseline={best['baseline_km']:.0f}km "
          f"SNR={best['snr1']:.1f}x/{best['snr2']:.1f}x")
    # Calibration
    detecting_sta = best['pair'].split('-')[0]
    filt_s = filts[detecting_sta]
    onset_t = best['t']
    win = filt_s[(filt_s.index>=onset_t)&(filt_s.index<=onset_t+pd.Timedelta(hours=2))]
    pre = filt_s[(filt_s.index>=onset_t-pd.Timedelta(hours=2))&(filt_s.index<onset_t)]
    if not win.empty and not pre.empty and pre.std()>0:
        tec_amp = float(win.abs().max())
        pred = CALIB_A * tec_amp * (10**(CALIB_B*MW)) / (TIDE_DIST_KM**CALIB_C)
        err = (pred-TIDE_M)/TIDE_M*100
        print(f"  TEC amplitude: {tec_amp:.3f} TECU")
        print(f"  Predicted wave: {pred:.3f}m  Actual: {TIDE_M:.3f}m  Error: {err:+.0f}%")
else:
    print("− NOT DETECTED in window")
    print("\nAll pairs regardless of window:")
    for p in sorted(pairs, key=lambda x:x['post_h'])[:8]:
        print(f"  {p['pair']} +{p['post_h']:.1f}h {p['speed']:.0f}m/s "
              f"SNR={p['snr1']:.1f}x/{p['snr2']:.1f}x")

# Plot
fig, axes = plt.subplots(len(filts), 1, figsize=(14, 3*len(filts)+1))
if len(filts)==1: axes=[axes]
colors={"mkea":"#D85A30","kokb":"#185FA5","hnlc":"#7F77DD","chat":"#BA7517"}
for ax,(sid,filt) in zip(axes,filts.items()):
    t=[(ts-qu).total_seconds()/3600 for ts in filt.index]
    ax.plot(t,filt.values,color=colors.get(sid,"gray"),linewidth=0.8,alpha=0.85)
    ax.axvline(0,color="red",linestyle="--",linewidth=0.8,alpha=0.5,label="Quake")
    ax.axhline(0,color="gray",linewidth=0.3)
    ax.axvspan(10,16,color="green",alpha=0.07,label="Window (+10-16h)")
    if window_hits and sid in window_hits[0]['pair']:
        ax.axvline(window_hits[0]['post_h'],color="green",linewidth=2.5,alpha=0.85)
    dist=haversine_km(EPI_LAT,EPI_LON,STATIONS[sid]['lat'],STATIONS[sid]['lon'])
    ax.set_title(f"{sid.upper()}  ({dist:.0f}km from epicenter)",fontsize=9,fontweight='bold')
    ax.set_xlabel("Hours after earthquake"); ax.set_ylabel("TEC (TECU)")
    ax.set_xlim(-2,20); ax.legend(fontsize=7); ax.grid(alpha=0.15)
    # Mark day boundary
    day_boundary = (24*60-20*60-33)/60  # hours from quake to midnight
    ax.axvline(day_boundary,color="gray",linestyle=":",linewidth=1,alpha=0.5,label="Midnight UTC")

fig.suptitle("Peru 2001  Mw 8.4  —  Two-Day Processing\n"
             "Quake 20:33 UTC Jun 23  |  Detection window Jun 24 06:33-12:33 UTC",
             fontsize=11,fontweight='bold')
fig.tight_layout()
fig.savefig("peru_twoday.png",dpi=150)
plt.close()
print(f"\nSaved peru_twoday.png")
print(f"Upload: peru_twoday.png")
