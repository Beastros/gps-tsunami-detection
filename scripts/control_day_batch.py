"""
Batch Control Day False Alarm Test
====================================
Tests the frozen coherence detector on 9 quiet days
with no tsunami or major seismic events.

Parameters imported from detector_params.py (frozen 2025-04-22).
DO NOT modify detector_params.py before running this.

All files in rinex_controls/ folder.

Run: python control_day_batch.py
Output: control_day_results.png + control_day_results.csv
"""

import sys
sys.path.insert(0, '.')  # import detector_params from current dir

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import butter, filtfilt
from itertools import combinations
import warnings
from datetime import datetime, timezone
warnings.filterwarnings("ignore")

# ── Import frozen parameters ──────────────────────────────────────
try:
    from detector_params import (
        SNR_THRESHOLD, MIN_DURATION_MIN,
        TSUNAMI_SPEED_MIN_MS, TSUNAMI_SPEED_MAX_MS,
        MIN_POST_QUAKE_HOURS, MAX_POST_QUAKE_HOURS,
        POLYNOMIAL_ORDER, BANDPASS_LO_MIN, BANDPASS_HI_MIN,
        MIN_ARC_EPOCHS, ELEV_CUTOFF_DEG, RESAMPLE_SEC,
        TIME_TOLERANCE_MIN, STATIONS, PARAMETER_VERSION, LOCKED_DATE
    )
    print(f"✓ Loaded frozen parameters v{PARAMETER_VERSION} ({LOCKED_DATE})")
except ImportError:
    print("⚠ detector_params.py not found — using defaults")
    SNR_THRESHOLD=2.0; MIN_DURATION_MIN=3
    TSUNAMI_SPEED_MIN_MS=150; TSUNAMI_SPEED_MAX_MS=350
    MIN_POST_QUAKE_HOURS=1.5; MAX_POST_QUAKE_HOURS=22.0
    POLYNOMIAL_ORDER=4; BANDPASS_LO_MIN=10; BANDPASS_HI_MIN=120
    MIN_ARC_EPOCHS=120; ELEV_CUTOFF_DEG=20; RESAMPLE_SEC=30
    TIME_TOLERANCE_MIN=10
    STATIONS={"mkea":{"lat":19.801,"lon":-155.456,"alt":3763},
               "kokb":{"lat":22.127,"lon":-159.665,"alt":1167},
               "hnlc":{"lat":21.297,"lon":-157.816,"alt":5}}

# ── Control days ──────────────────────────────────────────────────
# Each uses midnight UTC as reference (no quake, so window = full day)
CONTROL_DAYS = [
    {"id":"ctrl_2011_200","label":"Jul 19 2011","year":2011,"doy":200,"yr2":"11"},
    {"id":"ctrl_2011_250","label":"Sep 07 2011","year":2011,"doy":250,"yr2":"11"},
    {"id":"ctrl_2012_050","label":"Feb 19 2012","year":2012,"doy": 50,"yr2":"12"},
    {"id":"ctrl_2012_200","label":"Jul 18 2012","year":2012,"doy":200,"yr2":"12"},
    {"id":"ctrl_2010_100","label":"Apr 10 2010","year":2010,"doy":100,"yr2":"10"},
    {"id":"ctrl_2010_200","label":"Jul 19 2010","year":2010,"doy":200,"yr2":"10"},
    {"id":"ctrl_2009_150","label":"May 30 2009","year":2009,"doy":150,"yr2":"09"},
    {"id":"ctrl_2009_200","label":"Jul 19 2009","year":2009,"doy":200,"yr2":"09"},
    {"id":"ctrl_2006_200","label":"Jul 19 2006","year":2006,"doy":200,"yr2":"06"},
]

CTRL_DIR = Path("rinex_controls")

# GPS constants
F1,F2=1575.42e6,1227.60e6; LAM1=2.998e8/F1; LAM2=2.998e8/F2
K=40.3e16*(1/F2**2-1/F1**2); RE=6371000.0

def bandpass(s,fs,lo=BANDPASS_LO_MIN,hi=BANDPASS_HI_MIN):
    nyq=0.5*fs; b,a=butter(4,[max(1/(hi*60)/nyq,1e-6),min(1/(lo*60)/nyq,0.999)],btype="band")
    return pd.Series(filtfilt(b,a,s.values),index=s.index)

def decompress(gz):
    out=Path(str(gz).replace('.Z',''))
    if out.exists(): return out
    try:
        import ncompress; data=ncompress.decompress(open(gz,'rb').read())
        open(out,'wb').write(data); return out
    except: return None

def haversine_km(lat1,lon1,lat2,lon2):
    R=6371.0; la1,lo1,la2,lo2=map(np.radians,[lat1,lon1,lat2,lon2])
    dlat=la2-la1; dlon=lo2-lo1
    a=np.sin(dlat/2)**2+np.cos(la1)*np.cos(la2)*np.sin(dlon/2)**2
    return R*2*np.arcsin(np.sqrt(a))

def compute_tec(obs_path,lat,lon,alt,poly=POLYNOMIAL_ORDER):
    try:
        import georinex as gr; obs=gr.load(str(obs_path))
    except: return None
    avail=list(obs.data_vars)
    l1v=next((v for v in avail if v=="L1"),None)
    l2v=next((v for v in avail if v=="L2"),None)
    if not l1v or not l2v: return None
    l1d=obs[l1v]; l2d=obs[l2v]; arcs=[]
    for sv in obs.sv.values:
        try:
            a=l1d.sel(sv=sv); b=l2d.sel(sv=sv)
            mask=(~np.isnan(a.values))&(~np.isnan(b.values))
            times=a.time.values[mask]
            if len(times)<MIN_ARC_EPOCHS: continue
            l4=a.values[mask]*LAM1-b.values[mask]*LAM2
            sl_=np.where(np.abs(np.diff(l4))>0.5)[0]+1
            bds=[0]+list(sl_)+[len(l4)]
            for s,e in zip(bds[:-1],bds[1:]):
                if e-s<MIN_ARC_EPOCHS: continue
                tn=np.linspace(0,1,e-s)
                try:
                    c=np.polyfit(tn,l4[s:e],poly)
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
                events.append({"time":start,"dur_min":dur,
                               "snr":float(seg.abs().max()/noise)})
            in_ev=False
    return events, noise

def check_coherence_blind(filts, onsets, ref_time):
    """
    Blind coherence check — no epicenter assumed.
    For control days we use a dummy epicenter at MKEA
    (worst case — maximum false alarms since direction
    check is always satisfied for nearby stations).
    Any coherent pair found = false alarm.
    """
    qu=pd.Timestamp(ref_time); coherent=[]
    station_list=list(filts.keys())
    for s1,s2 in combinations(station_list,2):
        ev1=onsets.get(s1,[]); ev2=onsets.get(s2,[])
        if not ev1 or not ev2: continue
        s2s=haversine_km(STATIONS[s1]["lat"],STATIONS[s1]["lon"],
                         STATIONS[s2]["lat"],STATIONS[s2]["lon"])*1000
        for o1 in ev1:
            for o2 in ev2:
                # Apply time gates
                if (o1["time"]-qu).total_seconds()<MIN_POST_QUAKE_HOURS*3600: continue
                if (o1["time"]-qu).total_seconds()>MAX_POST_QUAKE_HOURS*3600: continue
                if (o2["time"]-qu).total_seconds()<MIN_POST_QUAKE_HOURS*3600: continue
                if (o2["time"]-qu).total_seconds()>MAX_POST_QUAKE_HOURS*3600: continue
                dt=abs((o1["time"]-o2["time"]).total_seconds())/60
                speed=s2s/(dt*60) if dt>0.5 else float('inf')
                if TSUNAMI_SPEED_MIN_MS<=speed<=TSUNAMI_SPEED_MAX_MS:
                    coherent.append({
                        "pair":f"{s1}-{s2}",
                        "t":min(o1["time"],o2["time"]),
                        "hours":(min(o1["time"],o2["time"])-qu).total_seconds()/3600,
                        "speed_ms":speed,"delay_min":dt,
                        "snr1":o1["snr"],"snr2":o2["snr"]
                    })
    return coherent

# ── Run all control days ──────────────────────────────────────────
print(f"\n=== Control Day Batch Test ===")
print(f"Parameters: SNR={SNR_THRESHOLD}σ  speed={TSUNAMI_SPEED_MIN_MS}-{TSUNAMI_SPEED_MAX_MS}m/s  "
      f"dur≥{MIN_DURATION_MIN}min  window={MIN_POST_QUAKE_HOURS}-{MAX_POST_QUAKE_HOURS}h\n")

results=[]

for ctrl in CONTROL_DAYS:
    yr=ctrl["year"]; doy=ctrl["doy"]; yr2=ctrl["yr2"]
    ref_utc=datetime(yr,1,1,0,0,0,tzinfo=timezone.utc)+pd.Timedelta(days=doy-1)
    print(f"[ {ctrl['label']} (day {doy}/{yr}) ]")

    filts={}
    for sid in ["mkea","kokb","hnlc"]:
        og=CTRL_DIR/f"{sid}{doy:03d}0.{yr2}o.Z"
        if not og.exists(): print(f"  {sid}: missing"); continue
        op=decompress(og)
        if not op: continue
        scfg=STATIONS[sid]
        filt=compute_tec(op,scfg["lat"],scfg["lon"],scfg["alt"])
        if filt is not None: filts[sid]=filt

    if len(filts)<2:
        print(f"  Only {len(filts)} stations — skip\n")
        continue

    onsets={}; total_single=0
    for sid,filt in filts.items():
        ev,noise=get_onsets(filt)
        onsets[sid]=ev; total_single+=len(ev)

    coherent=check_coherence_blind(filts,onsets,ref_utc)

    print(f"  Stations: {list(filts.keys())}  "
          f"Single triggers: {total_single}  "
          f"Coherent pairs: {len(coherent)}")

    if coherent:
        for c in coherent:
            print(f"    ⚠ FALSE ALARM: {c['pair']} +{c['hours']:.1f}h  "
                  f"{c['speed_ms']:.0f}m/s  SNR={c['snr1']:.1f}x/{c['snr2']:.1f}x")
    else:
        print(f"    ✓ No false alarms")
    print()

    results.append({
        "date":ctrl["label"],"doy":doy,"year":yr,
        "stations":len(filts),
        "single_triggers":total_single,
        "coherent_pairs":len(coherent),
        "false_alarm": len(coherent)>0
    })

# ── Summary ───────────────────────────────────────────────────────
df=pd.DataFrame(results)
n_tested=len(df)
n_fa=df["false_alarm"].sum()
n_clean=n_tested-n_fa

print("="*55)
print(f"CONTROL DAY SUMMARY")
print("="*55)
print(df[["date","stations","single_triggers","coherent_pairs","false_alarm"]].to_string(index=False))
print(f"\n  Days tested:    {n_tested}")
print(f"  False alarms:   {n_fa}")
print(f"  Clean days:     {n_clean}")
print(f"  False alarm rate: {n_fa}/{n_tested} = {n_fa/n_tested:.2f}")

if n_fa==0:
    print(f"\n  ✓ ZERO FALSE ALARMS across all {n_tested} control days")
    print(f"  Combined with previous controls: 0/{n_tested+2} = 0.00 FAR")
else:
    print(f"\n  ⚠ {n_fa} false alarm(s) — review above for details")

df.to_csv("control_day_results.csv",index=False)

# ── Plot ──────────────────────────────────────────────────────────
fig,ax=plt.subplots(figsize=(12,5))
colors=["#0F6E56" if not r["false_alarm"] else "#993556" for _,r in df.iterrows()]
bars=ax.bar(range(len(df)),df["coherent_pairs"],color=colors,alpha=0.85,edgecolor="white")
ax.bar(range(len(df)),df["single_triggers"],color="lightgray",alpha=0.4,
       label=f"Single-station triggers (mean={df['single_triggers'].mean():.1f}/day)")

for i,(bar,row) in enumerate(zip(bars,df.itertuples())):
    ax.text(i,row.single_triggers+0.3,str(row.single_triggers),
            ha="center",va="bottom",fontsize=8,color="#555")

ax.set_xticks(range(len(df)))
ax.set_xticklabels([r["date"] for _,r in df.iterrows()],rotation=30,ha="right",fontsize=9)
ax.set_ylabel("Number of triggers",fontsize=11)
ax.set_title(f"Control Day False Alarm Test — {n_tested} quiet days\n"
             f"Coherent pairs (colored) vs single-station triggers (gray)\n"
             f"False alarm rate: {n_fa}/{n_tested}  "
             f"Parameters frozen v{PARAMETER_VERSION if 'PARAMETER_VERSION' in dir() else '1.0'}",
             fontsize=11,fontweight="bold")
ax.axhline(0.5,color="gray",linestyle=":",linewidth=0.8,alpha=0.5)
from matplotlib.patches import Patch
legend_elements=[Patch(facecolor="#0F6E56",label="✓ No false alarm"),
                 Patch(facecolor="#993556",label="✗ False alarm"),
                 Patch(facecolor="lightgray",alpha=0.6,label="Single-station triggers")]
ax.legend(handles=legend_elements,fontsize=9,loc="upper right")
ax.set_ylim(0,max(df["single_triggers"].max()*1.2,3))
ax.grid(axis="y",alpha=0.2)
fig.tight_layout()
fig.savefig("control_day_results.png",dpi=150)
plt.close()
print("\nSaved control_day_results.png + control_day_results.csv")
print("Upload: control_day_results.png")
