"""
Automated Detector Runner
==========================
Reads event_queue.json, finds events with RINEX downloaded,
runs the frozen coherence detector, and writes predictions.

Run after rinex_downloader.py:
  python detector_runner.py

Or for a specific event:
  python detector_runner.py --event <usgs_id>

Output: predictions appended to event_queue.json
        per-event plots saved to rinex_live/<event_id>/
"""

import json
import logging
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from pathlib import Path
from scipy.signal import butter, filtfilt
from itertools import combinations
from space_weather import get_space_weather_quality

EVENT_QUEUE_FILE = "event_queue.json"
LOG_FILE = "runner.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── FROZEN PARAMETERS (locked 2025-04-22) ─────────────────────────
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
PARAM_FREEZE_DATE = "2025-04-22"

# ── Calibration model (frozen) ─────────────────────────────────────
CALIB_A = 2283.839
CALIB_B = 0.771
CALIB_C = 2.614

def predict_wave(tec, mw, dist_km):
    return CALIB_A * tec * (10**(CALIB_B*mw)) / (dist_km**CALIB_C)

STATIONS = {
    "mkea": {"lat": 19.801,  "lon": -155.456, "alt": 3763},
    "kokb": {"lat": 22.127,  "lon": -159.665, "alt": 1167},
    "hnlc": {"lat": 21.297,  "lon": -157.816, "alt":    5},
    "guam": {"lat": 13.489,  "lon":  144.868, "alt":   83},
    "chat": {"lat": -43.956, "lon": -176.566, "alt":   63},
    "thti": {"lat": -17.577, "lon": -149.606, "alt":   87},
    "thtg": {"lat": -17.577, "lon": -149.606, "alt":   87},
}

HILO = {"lat": 19.730, "lon": -155.087}  # tide gauge target

F1,F2=1575.42e6,1227.60e6; LAM1=2.998e8/F1; LAM2=2.998e8/F2
K=40.3e16*(1/F2**2-1/F1**2); MU=3.986005e14; OMEGA_E=7.2921151467e-5; RE=6371000.0

def fetch_kp(quake_utc_str):
    """
    Fetch the actual Kp index from NOAA Space Weather at the time of the quake.
    Returns float Kp value or None on failure.
    NOAA SWPC planetary K-index feed: 3-hour cadence, past 7 days.
    """
    try:
        import urllib.request
        url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
        req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-detector"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        # data[0] is the header row: ["time_tag","Kp","Kp_fraction","a_running","station_count"]
        quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))

        best_kp = None
        best_dt = None
        for row in data[1:]:
            try:
                t = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                kp_val = float(row[1])
                dt = abs((t - quake_dt).total_seconds())
                if best_dt is None or dt < best_dt:
                    best_dt = dt
                    best_kp = kp_val
            except:
                continue

        if best_kp is not None:
            log.info(f"  Kp index at quake time: {best_kp} "
                     f"({'DISTURBED — gate active' if best_kp >= KP_THRESHOLD else 'quiet'})")
        return best_kp

    except Exception as e:
        log.warning(f"  Kp fetch failed: {e} — gate disabled for this event")
        return None



def haversine_km(la1, lo1, la2, lo2):
    import math
    R=6371.0; la1,lo1,la2,lo2=map(math.radians,[la1,lo1,la2,lo2])
    dlat=la2-la1; dlon=lo2-lo1
    a=math.sin(dlat/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def compute_dart_score(dart_result):
    """
    Convert check_dart_network() result to 0-1 score.
    0.0 = no data or no signal.  1.0 = strong multi-buoy confirmation.
    """
    if not dart_result or dart_result.get("buoys_with_data", 0) == 0:
        return 0.0
    confirming = dart_result.get("confirming_buoys", 0)
    if confirming == 0:
        return 0.0
    base = {1: 0.45, 2: 0.72}.get(confirming, 0.90)
    max_sigma = 0.0
    for b in dart_result.get("results", {}).values():
        if b.get("detected") and b.get("detection"):
            max_sigma = max(max_sigma, b["detection"].get("sigma_score", 0))
    sigma_boost = min((max_sigma - 3.0) / 10.0, 0.10) if max_sigma > 3 else 0.0
    return min(round(base + sigma_boost, 3), 1.0)


def compute_combined_confidence(tec_detected, dart_score, dart_status, sw_score, const_agreement=None, dtec_corroborates=False, ionosonde_confirmed=False):
    """
    Multi-sensor fusion confidence score (0-1).

    TEC coherence (GPS):  up to 0.55  — reliability reduced by space weather
    DART ocean pressure:  up to 0.45  — independent of ionosphere

    dart_status: 'pending' | 'no_buoys' | 'negative' | 'confirmed'
    """
    tec_reliability = max(1.0 - sw_score * 0.6, 0.2)
    tec_contrib = 0.55 * tec_reliability if tec_detected else 0.0
    if dart_status in ("pending", "no_buoys"):
        dart_contrib = 0.0
    elif dart_status == "negative":
        dart_contrib = -0.08 if tec_detected else 0.0
    else:
        dart_contrib = dart_score * 0.45
    # Constellation agreement bonus/penalty (0 if only GPS available)
    const_contrib = 0.0
    if const_agreement is not None and tec_detected:
        lbl = const_agreement.get('agreement_label', 'single_constellation')
        if const_agreement.get('n_available', 1) >= 2:
            if lbl == 'agreement':     const_contrib =  0.10
            elif lbl == 'disagreement': const_contrib = -0.10
            elif lbl == 'partial':      const_contrib =  0.03
    # dTEC/dt corroboration — small boost (not independent, same GPS data)
    dtec_contrib = 0.05 if (dtec_corroborates and tec_detected) else 0.0
    # Ionosonde foF2 — truly independent HF radar, significant boost
    iono_contrib = 0.12 if (ionosonde_confirmed and tec_detected) else 0.0
    confidence = max(tec_contrib + dart_contrib + const_contrib + dtec_contrib + iono_contrib, 0.0)
    return min(round(confidence, 3), 1.0)


CONST_FREQ = {
    'G': (1575.42e6, 1227.60e6),
    'R': (1602.00e6, 1246.00e6),
    'E': (1575.42e6, 1207.14e6),
}
CONST_K   = {c: 40.3e16*(1/f2**2-1/f1**2) for c,(f1,f2) in CONST_FREQ.items()}
CONST_LAM = {c: (2.998e8/f1, 2.998e8/f2)  for c,(f1,f2) in CONST_FREQ.items()}


def compute_tec_for_constellation(obs_path, constellation, lat, lon, alt):
    if constellation not in CONST_FREQ:
        return None
    lam1, lam2 = CONST_LAM[constellation]
    k_val = CONST_K[constellation]
    try:
        import georinex as gr
        obs = gr.load(str(obs_path), use=constellation)
    except Exception as exc:
        log.debug(f'  [{constellation}] RINEX load failed: {exc}')
        return None
    avail = list(obs.data_vars)
    l1v = next((v for v in avail if v.startswith('L1')), None)
    l2v = next((v for v in avail if v.startswith('L2') or v.startswith('L7') or v.startswith('L5')), None)
    if not l1v or not l2v:
        return None
    l1d = obs[l1v]; l2d = obs[l2v]; arcs = []
    for sv in obs.sv.values:
        try:
            a = l1d.sel(sv=sv); b = l2d.sel(sv=sv)
            if a.ndim > 1: a = a.isel({d: 0 for d in a.dims if d != 'time'})
            if b.ndim > 1: b = b.isel({d: 0 for d in b.dims if d != 'time'})
            mask = (~np.isnan(a.values)) & (~np.isnan(b.values))
            times = a.time.values[mask]
            if len(times) < MIN_ARC_EPOCHS: continue
            l4 = a.values[mask] * lam1 - b.values[mask] * lam2
            sl_ = np.where(np.abs(np.diff(l4)) > 0.5)[0] + 1
            bds = [0] + list(sl_) + [len(l4)]
            for s, e in zip(bds[:-1], bds[1:]):
                if e - s < MIN_ARC_EPOCHS: continue
                tn = np.linspace(0, 1, e - s)
                try:
                    c = np.polyfit(tn, l4[s:e], POLYNOMIAL_ORDER)
                    r = (l4[s:e] - np.polyval(c, tn)) / k_val
                    ts = [pd.Timestamp(t).tz_localize('UTC') for t in times[s:e]]
                    arcs.append(pd.Series(r, index=ts))
                except: continue
        except: continue
    if not arcs: return None
    combined = pd.concat([s.resample(f'{RESAMPLE_SEC}s').mean() for s in arcs], axis=1)
    stacked = combined.median(axis=1).interpolate(limit=10)
    try:
        return bandpass(stacked, 1 / float(RESAMPLE_SEC))
    except Exception:
        return None


def compute_constellation_agreement(filts_by_const, quake_utc):
    qu = pd.Timestamp(quake_utc)
    window_start = qu + pd.Timedelta(hours=MIN_POST_QUAKE_H)
    window_end   = qu + pd.Timedelta(hours=MAX_POST_QUAKE_H)
    const_results = {}
    for const, filts in filts_by_const.items():
        if not filts:
            const_results[const] = {'available': False, 'anomaly': False, 'n_stations': 0}
            continue
        has_anomaly = False
        for sid, filt in filts.items():
            try:
                win = filt[(filt.index >= window_start) & (filt.index <= window_end)]
                pre = filt[filt.index < qu]
                if win.empty or pre.empty: continue
                noise = max(float(pre.std()), 1e-4)
                if float(win.abs().max()) > SNR_THRESHOLD * noise:
                    has_anomaly = True; break
            except Exception: continue
        const_results[const] = {'available': True, 'anomaly': has_anomaly, 'n_stations': len(filts)}
    available = [c for c, v in const_results.items() if v['available']]
    detecting = [c for c, v in const_results.items() if v.get('anomaly')]
    n_avail = len(available); n_detect = len(detecting)
    if n_avail == 0:       label, score = 'no_data', 0.0
    elif n_avail == 1:     label, score = 'single_constellation', 0.5
    else:
        frac = n_detect / n_avail
        if frac >= 0.67:   label, score = 'agreement', round(0.8 + 0.2*frac, 2)
        elif frac <= 0.34: label, score = 'disagreement', 0.2
        else:              label, score = 'partial', 0.5
    return {'constellations': const_results, 'n_available': n_avail,
            'n_detecting': n_detect, 'detecting': detecting,
            'agreement_score': score, 'agreement_label': label}




def bandpass(s,fs):
    nyq=0.5*fs; b,a=butter(4,[max(1/(120*60)/nyq,1e-6),min(1/(10*60)/nyq,0.999)],btype="band")
    return pd.Series(filtfilt(b,a,s.values),index=s.index)


def compute_dtec(filt):
    """
    Compute rate of change of TEC in TECU/min.
    Tsunami-driven ionospheric disturbances have a sharp leading-edge
    dTEC/dt spike at the wave front, distinct from smooth geomagnetic changes.
    """
    if filt is None or len(filt) < 5:
        return None
    diff = filt.diff().dropna()
    dtec_per_min = diff * (60.0 / RESAMPLE_SEC)
    smoothed = dtec_per_min.rolling(window=5, center=True, min_periods=3).mean()
    return smoothed.dropna()


def get_dtec_onsets(dtec, quake_utc):
    """
    Detect sharp dTEC/dt spikes in the post-quake detection window.
    Uses 3-sigma threshold relative to pre-quake baseline.
    Returns list of onset dicts.
    """
    if dtec is None or dtec.empty:
        return []
    qu = pd.Timestamp(quake_utc)
    pre = dtec[dtec.index < qu]
    if pre.empty or len(pre) < 6:
        return []
    noise = max(float(pre.abs().std()), 1e-5)
    threshold = 3.0 * noise
    win_start = qu + pd.Timedelta(hours=MIN_POST_QUAKE_H)
    win_end   = qu + pd.Timedelta(hours=MAX_POST_QUAKE_H)
    window = dtec[(dtec.index >= win_start) & (dtec.index <= win_end)]
    if window.empty:
        return []
    onsets = []; in_ev = False; ev_start = None; ev_peak = 0.0
    for t, v in window.items():
        if abs(v) >= threshold:
            if not in_ev: in_ev = True; ev_start = t; ev_peak = abs(v)
            else: ev_peak = max(ev_peak, abs(v))
        else:
            if in_ev and ev_peak > threshold:
                post_h = (ev_start - qu).total_seconds() / 3600
                onsets.append({
                    "time":              ev_start.isoformat(),
                    "post_h":            round(post_h, 2),
                    "dtec_max_tecu_min": round(ev_peak, 4),
                    "noise_std":         round(noise, 5),
                    "snr_dtec":          round(ev_peak / noise, 1),
                })
            in_ev = False; ev_peak = 0.0
    return onsets


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

def compute_tec(obs_path, nav, lat, lon, alt):
    try:
        import georinex as gr
        obs = gr.load(str(obs_path), use='G')
    except Exception as e:
        log.warning(f"Load failed {obs_path}: {e}"); return None
    avail=list(obs.data_vars)
    l1v=next((v for v in avail if 'L1' in v),None)
    l2v=next((v for v in avail if 'L2' in v),None)
    if not l1v or not l2v: return None
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
                events.append({"time":start.isoformat(),"dur_min":dur,
                               "snr":float(seg.abs().max()/noise)})
            in_ev=False
    return events, float(noise)

def detect_lb(filts, onsets, epi_lat, epi_lon, quake_utc):
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
                t1=pd.Timestamp(o1["time"]); t2=pd.Timestamp(o2["time"])
                if (t1-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t1-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()<MIN_POST_QUAKE_H*3600: continue
                if (t2-qu).total_seconds()>MAX_POST_QUAKE_H*3600: continue
                dt=abs((t1-t2).total_seconds())/60
                speed=ddist*1000/(dt*60) if dt>0.5 else float('inf')
                closer=s1 if d1<d2 else s2
                earlier=s1 if t1<t2 else s2
                if SPEED_MIN<=speed<=SPEED_MAX and closer==earlier:
                    post_h=(min(t1,t2)-qu).total_seconds()/3600
                    pairs.append({
                        "pair":f"{s1}-{s2}",
                        "onset_utc":min(t1,t2).isoformat(),
                        "post_h":round(post_h,2),
                        "speed_ms":round(speed,1),
                        "delay_min":round(dt,1),
                        "snr_near":round(o1["snr"] if d1<d2 else o2["snr"],2),
                        "snr_far":round(o2["snr"] if d1<d2 else o1["snr"],2),
                        "baseline_km":round(s2s),
                    })
    return pairs

def run_event(event, kp_override=None):
    """Run detector on a single event. Returns prediction dict."""
    rinex_dir = Path(event.get("rinex_dir", f"rinex_live/{event['usgs_id']}"))
    quake_utc = event["quake_utc"]
    epi_lat   = event["lat"]
    epi_lon   = event["lon"]
    mw        = event["magnitude"]

    quake_dt = datetime.fromisoformat(quake_utc.replace("Z","+00:00"))
    year = quake_dt.year
    doy  = quake_dt.timetuple().tm_yday
    yr2  = str(year)[-2:]

    log.info(f"\nRunning detector: {event['usgs_id']}")
    log.info(f"  {event['place']}  Mw{mw}  {quake_utc[:16]}")

    # Determine which stations have files
    filts = {}
    for sid in STATIONS:
        og = rinex_dir / f"{sid}{doy:03d}0.{yr2}o.Z"
        ng = rinex_dir / f"{sid}{doy:03d}0.{yr2}n.Z"
        if not og.exists(): continue
        op = decompress(og)
        if not op: continue
        nav = {}
        if ng.exists():
            np_ = decompress(ng)
            if np_:
                nav = parse_nav(np_)
                if nav:
                    tsv=list(nav.keys())[0]; pos=keplerian_to_ecef(nav[tsv][0][1],nav[tsv][0][0])
                    if pos:
                        d=np.sqrt(sum(p**2 for p in pos))/1000
                        if not 20000<d<30000: nav={}
        scfg = STATIONS[sid]
        log.info(f"  Processing {sid.upper()}...")
        filt = compute_tec(op, nav, scfg['lat'], scfg['lon'], scfg['alt'])
        if filt is not None:
            filts[sid] = filt
            log.info(f"    → {sid.upper()} OK")


    # Multi-constellation TEC (GLONASS + Galileo cross-check)
    filts_by_const = {'G': filts}
    for _const in ('R', 'E'):
        _cfilts = {}
        for _sid in STATIONS:
            _og = rinex_dir / f"{_sid}{doy:03d}0.{yr2}o.Z"
            if not _og.exists(): continue
            _op = decompress(_og)
            if not _op: continue
            _scfg = STATIONS[_sid]
            _cf = compute_tec_for_constellation(_op, _const, _scfg['lat'], _scfg['lon'], _scfg['alt'])
            if _cf is not None: _cfilts[_sid] = _cf
        if _cfilts: log.info(f"  [{_const}] {len(_cfilts)} station(s) with data")
        filts_by_const[_const] = _cfilts
    if len(filts) < 2:
        log.warning(f"  Insufficient stations ({len(filts)})")
        return {"detected": False, "reason": "insufficient_stations",
                "stations_processed": list(filts.keys())}


    # dTEC/dt rate-of-change computation
    # Tsunami wave fronts create sharp dTEC/dt spikes that precede
    # the sustained amplitude disturbance the main detector sees.
    dtec_filts  = {}
    dtec_onsets_map = {}
    for _sid, _filt in filts.items():
        _dtec = compute_dtec(_filt)
        if _dtec is not None:
            dtec_filts[_sid]      = _dtec
            dtec_onsets_map[_sid] = get_dtec_onsets(_dtec, quake_utc)
            _n = len(dtec_onsets_map[_sid])
            if _n > 0:
                _best = max(dtec_onsets_map[_sid], key=lambda x: x['snr_dtec'])
                log.info(f"  [{_sid.upper()}] dTEC/dt: {_n} onset(s) "
                         f"peak_snr={_best['snr_dtec']:.1f} "
                         f"at +{_best['post_h']:.1f}h")

    # Get onsets
    onsets = {}
    onset_summary = {}
    for sid, filt in filts.items():
        ev, noise = get_onsets(filt)
        onsets[sid] = ev
        onset_summary[sid] = {
            "n_triggers": len(ev),
            "noise_tecu": round(noise, 4),
            "triggers": ev[:5]  # first 5 only
        }

    # Detect long-baseline pairs
    pairs = detect_lb(filts, onsets, epi_lat, epi_lon, quake_utc)

    # Apply Kp gate
    kp = kp_override  # will be filled in later if not provided
    kp_disturbed = kp is not None and kp >= KP_THRESHOLD

    # Best detection in window
    window_pairs = [p for p in pairs if MIN_POST_QUAKE_H <= p['post_h'] <= MAX_POST_QUAKE_H]

    prediction = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "param_freeze_date": PARAM_FREEZE_DATE,
        "stations_processed": list(filts.keys()),
        "onset_summary": onset_summary,
        "lb_pairs_total": len(pairs),
        "lb_pairs_in_window": len(window_pairs),
        "kp": kp,
        "kp_disturbed": kp_disturbed,
        "detected": False,
        "detection": None,
        "wave_forecast": None,
    }

    if window_pairs and not (kp_disturbed and not event.get("is_tsunami_expected")):
        best = max(window_pairs, key=lambda x: x['snr_near']+x['snr_far'])
        prediction["detected"] = True
        prediction["detection"] = best

        # Wave height forecast
        detecting_sta = best['pair'].split('-')[0]
        dist_hilo = haversine_km(epi_lat, epi_lon, HILO['lat'], HILO['lon'])
        filt_s = filts[detecting_sta]
        onset_t = pd.Timestamp(best['onset_utc'])
        win = filt_s[(filt_s.index>=onset_t)&(filt_s.index<=onset_t+pd.Timedelta(hours=2))]
        if not win.empty:
            tec_amp = float(win.abs().max())
            pred_wave = predict_wave(tec_amp, mw, dist_hilo)
            wave_arrival_h = dist_hilo*1000/(200*3600)
            lead_min = (wave_arrival_h - best['post_h'])*60
            prediction["wave_forecast"] = {
                "tec_amp_tecu": round(tec_amp, 4),
                "detecting_station": detecting_sta,
                "dist_hilo_km": round(dist_hilo),
                "predicted_wave_m": round(pred_wave, 3),
                "predicted_arrival_h": round(wave_arrival_h, 1),
                "estimated_lead_min": round(lead_min),
                "model": f"w={CALIB_A}*TEC*10^({CALIB_B}*Mw)/d^{CALIB_C}",
                "note": "calibrated on Hawaii-corridor stations; "
                        "CHAT/GUAM may have higher error"
            }

        log.info(f"  ✓ DETECTED: {best['pair']} +{best['post_h']:.1f}h "
                 f"{best['speed_ms']:.0f}m/s")
        if prediction["wave_forecast"]:
            wf = prediction["wave_forecast"]
            log.info(f"  FORECAST: {wf['predicted_wave_m']:.3f}m at Hilo "
                     f"(+{wf['predicted_arrival_h']:.1f}h) "
                     f"lead={wf['estimated_lead_min']}min")
    else:
        reason = "kp_gated" if kp_disturbed else \
                 "no_coherent_pairs" if not window_pairs else "no_pairs"
        prediction["detected"] = False
        prediction["reason"] = reason
        log.info(f"  − No detection: {reason}")

    # Save plot
    plot_path = rinex_dir / "tec_plot.png"
    try:
        fig, ax = plt.subplots(figsize=(12, 4))
        qu = pd.Timestamp(quake_utc)
        colors = {"mkea":"#D85A30","kokb":"#185FA5","hnlc":"#7F77DD",
                  "guam":"#0F6E56","chat":"#BA7517","thti":"#8E44AD"}
        for sid, filt in filts.items():
            t = [(ts-qu).total_seconds()/3600 for ts in filt.index]
            ax.plot(t, filt.values, color=colors.get(sid,"gray"),
                    linewidth=0.8, alpha=0.75, label=sid.upper())
        ax.axvline(0, color="red", linestyle="--", linewidth=0.9, alpha=0.5)
        ax.axhline(0, color="gray", linewidth=0.3)
        if prediction["detection"]:
            d = prediction["detection"]
            ax.axvline(d['post_h'], color="green", linewidth=2.5, alpha=0.85)
            ax.annotate(f"{d['pair']}\n{d['speed_ms']:.0f}m/s",
                       (d['post_h'], 0.85), xycoords=('data','axes fraction'),
                       fontsize=8, color="green", fontweight="bold")
        status = "✓ DETECTED" if prediction["detected"] else "− No detection"
        ax.set_title(f"{event['place']}  Mw{mw}  {quake_utc[:16]} UTC  —  {status}",
                    fontsize=10, fontweight="bold")
        ax.set_xlabel("Hours after earthquake"); ax.set_ylabel("TEC (TECU)")
        ax.set_xlim(-1, 16); ax.legend(fontsize=7); ax.grid(alpha=0.15)
        fig.tight_layout()
        fig.savefig(plot_path, dpi=120)
        plt.close()
        prediction["plot_path"] = str(plot_path)
        log.info(f"  Saved plot: {plot_path}")
    except Exception as e:
        log.warning(f"  Plot failed: {e}")


    # Constellation agreement
    const_agreement = compute_constellation_agreement(filts_by_const, quake_utc)
    log.info(f"  CONSTELLATION: {const_agreement['n_detecting']}/{const_agreement['n_available']} "
             f"detecting  label={const_agreement['agreement_label']}  score={const_agreement['agreement_score']}")


    # dTEC/dt corroboration check
    # Does dTEC/dt onset precede or coincide with amplitude detection?
    dtec_corroboration = []
    if prediction.get('detected') and prediction.get('detection'):
        _det = prediction['detection']
        _amp_onset = pd.Timestamp(_det['onset_utc'])
        for _sid in _det['pair'].split('-'):
            for _de in dtec_onsets_map.get(_sid, []):
                _dt_min = (_amp_onset - pd.Timestamp(_de['time'])).total_seconds() / 60
                if -10 <= _dt_min <= 90:  # dTEC/dt within 90min before amplitude
                    dtec_corroboration.append({
                        'station':      _sid,
                        'dtec_post_h':  _de['post_h'],
                        'amp_post_h':   _det['post_h'],
                        'lead_min':     round(_dt_min, 1),
                        'snr_dtec':     _de['snr_dtec'],
                    })
                    break
    dtec_corroborates = len(dtec_corroboration) > 0
    prediction['dtec_onsets']        = dtec_onsets_map
    prediction['dtec_corroborates']  = dtec_corroborates
    prediction['dtec_corroboration'] = dtec_corroboration
    if dtec_corroborates:
        log.info(f"  dTEC/dt CORROBORATES detection — "
                 f"{len(dtec_corroboration)} station(s)")


    # Ionosonde foF2 cross-check (independent HF radar — GIRO Digisonde network)
    ionosonde_result    = None
    ionosonde_confirmed = False
    try:
        from ionosonde_checker import check_ionosonde_network
        _elat2 = event.get('lat') or event.get('latitude')
        _elon2 = event.get('lon') or event.get('longitude')
        if _elat2 is not None and _elon2 is not None:
            ionosonde_result    = check_ionosonde_network(quake_utc, _elat2, _elon2)
            ionosonde_confirmed = ionosonde_result.get('ionosonde_detected', False)
            _ci = ionosonde_result.get('confirming_stations', 0)
            _di = ionosonde_result.get('stations_with_data', 0)
            log.info(f'  IONOSONDE: confirmed={ionosonde_confirmed} {_ci}/{_di} stations')
    except ImportError:
        log.debug('  ionosonde_checker not available — skipping')
    except Exception as _ie:
        log.warning(f'  Ionosonde check failed: {_ie}')

    # DART buoy check (runs after TEC; skipped if wave hasn't had time to arrive)
    from datetime import datetime as _dt
    _now      = _dt.now(timezone.utc)
    _qdt2     = _dt.fromisoformat(quake_utc.replace("Z", "+00:00"))
    _post_h   = (_now - _qdt2).total_seconds() / 3600
    dart_result = None
    dart_score  = 0.0
    dart_status = "no_buoys"
    try:
        from dart_checker import check_dart_network
        _elat = event.get("lat") or event.get("latitude")
        _elon = event.get("lon") or event.get("longitude")
        if _elat is not None and _elon is not None:
            if _post_h < 1.5:
                dart_status = "pending"
                log.info(f"  DART: too early ({_post_h:.1f}h post-quake) — skipping")
            else:
                dart_result = check_dart_network(quake_utc, _elat, _elon)
                dart_score  = compute_dart_score(dart_result)
                if dart_result["buoys_checked"] == 0:
                    dart_status = "no_buoys"
                elif dart_result["tsunami_detected"]:
                    dart_status = "confirmed"
                else:
                    dart_status = "negative"
                log.info(
                    f"  DART: {dart_status}  score={dart_score:.2f}  "
                    f"confirming={dart_result['confirming_buoys']}/"
                    f"{dart_result['buoys_with_data']}"
                )
        else:
            log.warning("  DART: no epicenter coords in event — skipping")
    except Exception as _e:
        log.warning(f"  DART check failed: {_e}")
        dart_status = "no_buoys"

    _tec  = prediction.get("detected", False)
    _sw   = prediction.get("space_weather_score", 0.0)
    combined_confidence = compute_combined_confidence(
        _tec, dart_score, dart_status, _sw, const_agreement,
        dtec_corroborates=dtec_corroborates,
        ionosonde_confirmed=ionosonde_confirmed
    )
    prediction["constellation_agreement"] = const_agreement
    prediction["ionosonde_result"]         = ionosonde_result
    prediction["ionosonde_confirmed"]      = ionosonde_confirmed
    prediction["dart_result"]              = dart_result
    prediction["dart_score"]          = dart_score
    prediction["dart_status"]         = dart_status
    prediction["combined_confidence"] = combined_confidence
    log.info(f"  CONFIDENCE: TEC={'yes' if _tec else 'no'}  "
             f"DART={dart_status}({dart_score:.2f})  sw={_sw:.2f}  "
             f"combined={combined_confidence:.3f}")

    return prediction

def load_queue():
    if not Path(EVENT_QUEUE_FILE).exists():
        return None
    return json.loads(Path(EVENT_QUEUE_FILE).read_text())

def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2))

def main(event_id=None):
    log.info("="*55)
    log.info("GPS Tsunami Detector — Detector Runner")
    log.info(f"Parameters frozen: {PARAM_FREEZE_DATE}")
    log.info("="*55)

    queue = load_queue()
    if not queue:
        log.error("Queue not found")
        return

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]

    ready = [e for e in events
             if e.get("status") == "rinex_ready" and not e.get("detector_run")]

    log.info(f"Events ready to run: {len(ready)}")

    for event in ready:
        try:
            kp = fetch_kp(event["quake_utc"])
            prediction = run_event(event, kp_override=kp)
            event["prediction"] = prediction
            event["detector_run"] = True
            event["detector_run_utc"] = datetime.now(timezone.utc).isoformat()
            event["status"] = "predicted"
            save_queue(queue)
            log.info(f"Updated queue: {event['usgs_id']} → predicted")
        except Exception as e:
            log.error(f"Detector failed for {event['usgs_id']}: {e}")
            import traceback; traceback.print_exc()
            event["status"] = "detector_failed"
            event["detector_error"] = str(e)
            save_queue(queue)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Process specific USGS event ID")
    args = parser.parse_args()
    main(event_id=args.event)
