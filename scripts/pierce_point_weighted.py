"""
Pierce-Point-Weighted TEC Processing
======================================
Replaces equal-weight median stacking with geometry-aware weighting.

Core idea: GPS satellite arcs whose ionospheric pierce points (IPPs)
lie closest to the tsunami propagation path sample the AGW signal
most directly. Arcs whose IPPs are far off-axis sample undisturbed
ionosphere and should contribute less to the TEC estimate.

Weight formula:
  w_i = exp(-d_pp_i² / (2 × σ²))
  where d_pp_i = distance from arc's IPP to great-circle propagation path
  σ = 500 km (1-sigma ionospheric correlation length, standard in literature)

IPP calculation:
  IPP = receiver + t × (satellite - receiver)
  where t solves |IPP| = RE + H_iono (H_iono = 300 km)

Propagation path:
  Great circle from epicenter through each GPS station.
  AGW travels along this path so IPPs near it sample the signal.

Comparison:
  Runs both equal-weight (current) and pierce-point-weighted stacking
  on the same RINEX data, reports TEC amplitudes from both methods,
  and quantifies the difference. This directly addresses the amplitude
  accuracy problem.

Events processed: Chile 2010 (worst amplitude error), Haida Gwaii 2012,
                  Tōhoku 2011 (for comparison)

Run: python pierce_point_weighted.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import butter, filtfilt
import warnings
from datetime import datetime, timezone
warnings.filterwarnings("ignore")

# ── Constants ─────────────────────────────────────────────────────
F1,F2=1575.42e6,1227.60e6; LAM1=2.998e8/F1; LAM2=2.998e8/F2
K=40.3e16*(1/F2**2-1/F1**2)
MU=3.986005e14; OMEGA_E=7.2921151467e-5; RE=6371000.0
H_IONO = 300000.0      # ionospheric shell height (m)
SIGMA_PP_KM = 500.0    # IPP weighting sigma (km) - standard in literature
POLY = 4; MIN_ARC = 120; ELEV_CUT = 20; RESAMPLE = 30

CALIB_A=2283.839; CALIB_B=0.771; CALIB_C=2.614

def predict_wave(tec, mw, dist_km):
    return CALIB_A * tec * (10**(CALIB_B*mw)) / (dist_km**CALIB_C)

# ── Events ────────────────────────────────────────────────────────
EVENTS = {
    "chile_2010": {
        "name":"Chile 2010  Mw 8.8","mw":8.8,
        "rinex_dir":"rinex_chile_2010","doy":58,"yr2":"10",
        "quake_utc":datetime(2010,2,27,6,34,14,tzinfo=timezone.utc),
        "epi_lat":-36.1,"epi_lon":-72.9,
        "stations":{
            "chat":{"lat":-43.956,"lon":-176.566,"alt":63},
            "kokb":{"lat":22.127, "lon":-159.665,"alt":1167},
            "mkea":{"lat":19.801, "lon":-155.456,"alt":3763},
        },
        "tide_gauge":{"wave_m":0.464,"dist_km":10617},
        "window_h":(12.0,18.0),
    },
    "haida_gwaii_2012": {
        "name":"Haida Gwaii 2012  Mw 7.7","mw":7.7,
        "rinex_dir":"rinex_haida_gwaii_2012","doy":302,"yr2":"12",
        "quake_utc":datetime(2012,10,28,3,4,9,tzinfo=timezone.utc),
        "epi_lat":52.8,"epi_lon":-132.1,
        "stations":{
            "mkea":{"lat":19.801,"lon":-155.456,"alt":3763},
            "hnlc":{"lat":21.297,"lon":-157.816,"alt":5},
            "kokb":{"lat":22.127,"lon":-159.665,"alt":1167},
        },
        "tide_gauge":{"wave_m":0.653,"dist_km":4480},
        "window_h":(3.5,7.5),
    },
    "tohoku_2011": {
        "name":"Tōhoku 2011  Mw 9.0","mw":9.0,
        "rinex_dir":"rinex_tohoku_2011","doy":70,"yr2":"11",
        "quake_utc":datetime(2011,3,11,5,46,23,tzinfo=timezone.utc),
        "epi_lat":38.3,"epi_lon":142.4,
        "stations":{
            "mkea":{"lat":19.801,"lon":-155.456,"alt":3763},
            "kokb":{"lat":22.127,"lon":-159.665,"alt":1167},
        },
        "tide_gauge":{"wave_m":1.318,"dist_km":6200},
        "window_h":(4.0,9.0),
    },
}

# ── Geometry utilities ────────────────────────────────────────────
def haversine_km(la1,lo1,la2,lo2):
    R=6371.0; la1,lo1,la2,lo2=map(np.radians,[la1,lo1,la2,lo2])
    dlat=la2-la1; dlon=lo2-lo1
    a=np.sin(dlat/2)**2+np.cos(la1)*np.cos(la2)*np.sin(dlon/2)**2
    return R*2*np.arcsin(np.sqrt(a))

def ecef_to_latlon(x,y,z):
    """Convert ECEF to geodetic lat/lon (degrees)."""
    lon = np.degrees(np.arctan2(y, x))
    p = np.sqrt(x**2 + y**2)
    lat = np.degrees(np.arctan2(z, p * (1 - 6.694e-3)))  # approx
    return lat, lon

def compute_ipp(rx_ecef, sv_ecef):
    """
    Compute ionospheric pierce point at H_IONO altitude.
    rx_ecef, sv_ecef: numpy arrays of shape (3,)
    Returns (lat_deg, lon_deg) of IPP, or None if geometry invalid.
    """
    rx = np.array(rx_ecef, dtype=float)
    sv = np.array(sv_ecef, dtype=float)
    d = sv - rx
    d_norm = np.linalg.norm(d)
    if d_norm < 1e3: return None

    # Solve |rx + t*d| = RE + H_IONO
    a_coef = np.dot(d, d)
    b_coef = 2 * np.dot(rx, d)
    c_coef = np.dot(rx, rx) - (RE + H_IONO)**2
    disc = b_coef**2 - 4*a_coef*c_coef
    if disc < 0: return None

    t = (-b_coef + np.sqrt(disc)) / (2*a_coef)
    if not (0 < t < 1): return None

    ipp = rx + t * d
    lat, lon = ecef_to_latlon(*ipp)
    return lat, lon

def dist_point_to_great_circle(pt_lat, pt_lon, gc_lat1, gc_lon1, gc_lat2, gc_lon2):
    """
    Approximate distance from a point to the great circle path between two points.
    Uses cross-track distance formula (spherical earth).
    Returns distance in km.
    """
    # Convert to radians
    p = np.radians([pt_lat, pt_lon])
    a = np.radians([gc_lat1, gc_lon1])
    b = np.radians([gc_lat2, gc_lon2])

    # Angular distances
    d_ab = 2*np.arcsin(np.sqrt(np.sin((b[0]-a[0])/2)**2 +
                                np.cos(a[0])*np.cos(b[0])*np.sin((b[1]-a[1])/2)**2))
    d_ap = 2*np.arcsin(np.sqrt(np.sin((p[0]-a[0])/2)**2 +
                                np.cos(a[0])*np.cos(p[0])*np.sin((p[1]-a[1])/2)**2))

    # Bearing a->b and a->p
    y_ab = np.sin(b[1]-a[1])*np.cos(b[0])
    x_ab = np.cos(a[0])*np.sin(b[0]) - np.sin(a[0])*np.cos(b[0])*np.cos(b[1]-a[1])
    theta_ab = np.arctan2(y_ab, x_ab)

    y_ap = np.sin(p[1]-a[1])*np.cos(p[0])
    x_ap = np.cos(a[0])*np.sin(p[0]) - np.sin(a[0])*np.cos(p[0])*np.cos(p[1]-a[1])
    theta_ap = np.arctan2(y_ap, x_ap)

    # Cross-track distance
    xtrack = np.arcsin(np.sin(d_ap) * np.sin(theta_ap - theta_ab))
    return abs(xtrack) * 6371.0  # km

def ipp_weight(ipp_lat, ipp_lon, epi_lat, epi_lon, sta_lat, sta_lon, sigma_km=SIGMA_PP_KM):
    """Weight based on distance from IPP to great-circle propagation path."""
    d = dist_point_to_great_circle(ipp_lat, ipp_lon, epi_lat, epi_lon, sta_lat, sta_lon)
    return np.exp(-d**2 / (2 * sigma_km**2))

# ── Signal processing ─────────────────────────────────────────────
def bandpass(s, fs):
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
        return np.array([
            xo*np.cos(Ok)-yo*np.cos(ik)*np.sin(Ok),
            xo*np.sin(Ok)+yo*np.cos(ik)*np.cos(Ok),
            yo*np.sin(ik)])
    except: return None

def get_elev(nav,sv,epoch,lat,lon,alt):
    recs=nav.get(sv,[])
    if not recs: return None, None
    cl=min(recs,key=lambda r:abs((r[0]-epoch).total_seconds()))
    if abs((cl[0]-epoch).total_seconds())>7200: return None, None
    sv_ecef=keplerian_to_ecef(cl[1],epoch)
    if sv_ecef is None: return None, None
    d=np.linalg.norm(sv_ecef)
    if not 20000e3<d<30000e3: return None, None
    la=np.radians(lat); lo_=np.radians(lon); r=RE+alt
    rx=np.array([r*np.cos(la)*np.cos(lo_),r*np.cos(la)*np.sin(lo_),r*np.sin(la)])
    diff=sv_ecef-rx; dist_=np.linalg.norm(diff)
    if dist_<1e6: return None, None
    elev=float(np.degrees(np.arcsin(np.clip(np.dot(diff/dist_,rx/np.linalg.norm(rx)),-1,1))))
    return elev, (rx, sv_ecef)

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

def compute_tec_both(obs_path, nav, lat, lon, alt, epi_lat, epi_lon):
    """
    Compute both equal-weight and pierce-point-weighted TEC stacks.
    Returns (filt_equal, filt_ppw, ipp_stats)
    """
    try:
        import georinex as gr; obs=gr.load(str(obs_path))
    except: return None, None, {}

    avail=list(obs.data_vars)
    l1v=next((v for v in avail if v=="L1"),None)
    l2v=next((v for v in avail if v=="L2"),None)
    if not l1v or not l2v: return None, None, {}

    l1d=obs[l1v]; l2d=obs[l2v]
    arc_data = []  # list of (times, tec_residuals, weight, ipp_dist_km)
    nk=ne=nw=0

    for sv in obs.sv.values:
        try:
            a=l1d.sel(sv=sv); b=l2d.sel(sv=sv)
            mask=(~np.isnan(a.values))&(~np.isnan(b.values))
            times=a.time.values[mask]
            if len(times)<MIN_ARC: continue

            # Elevation + IPP
            weight = 1.0
            ipp_dist = 0.0
            if nav:
                mid=pd.Timestamp(times[len(times)//2]).to_pydatetime().replace(tzinfo=timezone.utc)
                elev, geom = get_elev(nav, str(sv), mid, lat, lon, alt)
                if elev is not None and elev < ELEV_CUT: ne+=1; continue
                if geom is not None:
                    rx_ecef, sv_ecef = geom
                    ipp = compute_ipp(rx_ecef, sv_ecef)
                    if ipp is not None:
                        ipp_lat, ipp_lon = ipp
                        w = ipp_weight(ipp_lat, ipp_lon, epi_lat, epi_lon, lat, lon)
                        ipp_d = dist_point_to_great_circle(ipp_lat, ipp_lon,
                                                           epi_lat, epi_lon, lat, lon)
                        weight = w
                        ipp_dist = ipp_d
                        if w < 0.1: nw += 1

            l4=a.values[mask]*LAM1-b.values[mask]*LAM2
            sl_=np.where(np.abs(np.diff(l4))>0.5)[0]+1
            bds=[0]+list(sl_)+[len(l4)]
            for s,e in zip(bds[:-1],bds[1:]):
                if e-s<MIN_ARC: continue
                tn=np.linspace(0,1,e-s)
                try:
                    c=np.polyfit(tn,l4[s:e],POLY)
                    r=(l4[s:e]-np.polyval(c,tn))/K
                    ts=[pd.Timestamp(t).tz_localize("UTC") for t in times[s:e]]
                    arc_data.append((ts, r, weight, ipp_dist))
                    nk+=1
                except: continue
        except: continue

    if not arc_data:
        return None, None, {}

    # Common time grid
    all_times = sorted(set(t for ts,_,_,_ in arc_data for t in ts))
    if not all_times: return None, None, {}

    idx = pd.DatetimeIndex(all_times).round(f"{RESAMPLE}s").unique()

    # Equal-weight stack
    series_list = []
    for ts, r, _, _ in arc_data:
        s = pd.Series(r, index=pd.DatetimeIndex(ts))
        series_list.append(s.resample(f"{RESAMPLE}s").mean())
    combined = pd.concat(series_list, axis=1)
    stacked_eq = combined.median(axis=1).interpolate(limit=10)

    # Pierce-point-weighted stack
    weighted_sum = pd.Series(0.0, index=combined.index)
    weight_total = pd.Series(0.0, index=combined.index)
    for (ts, r, w, _), series in zip(arc_data, series_list):
        filled = series.reindex(combined.index)
        valid = ~np.isnan(filled.values)
        weighted_sum[valid] += filled[valid] * w
        weight_total[valid] += w

    weight_total[weight_total < 1e-6] = np.nan
    stacked_ppw = (weighted_sum / weight_total).interpolate(limit=10)

    # IPP stats
    weights = [w for _,_,w,_ in arc_data]
    dists   = [d for _,_,_,d in arc_data]
    ipp_stats = {
        "n_arcs": nk, "n_elev_rej": ne, "n_low_weight": nw,
        "mean_weight": np.mean(weights) if weights else 0,
        "mean_ipp_dist_km": np.mean(dists) if dists else 0,
        "max_ipp_dist_km":  np.max(dists) if dists else 0,
    }

    fs = 1/float(RESAMPLE)
    filt_eq  = bandpass(stacked_eq,  fs)
    filt_ppw = bandpass(stacked_ppw, fs)

    print(f"    {nk} arcs  el_rej={ne}  low_weight={nw}  "
          f"mean_w={np.mean(weights):.2f}  mean_ipp_dist={np.mean(dists):.0f}km")

    return filt_eq, filt_ppw, ipp_stats

def get_peak_amp(filt, quake_utc, window_h):
    """Get peak TEC amplitude in detection window."""
    qu = pd.Timestamp(quake_utc)
    ws = qu + pd.Timedelta(hours=window_h[0])
    we = qu + pd.Timedelta(hours=window_h[1])
    pre = filt[(filt.index >= qu - pd.Timedelta(hours=3)) & (filt.index < qu)]
    win = filt[(filt.index >= ws) & (filt.index <= we)]
    if win.empty or pre.empty or pre.std() == 0: return None, None
    noise = pre.std()
    peak  = float(win.abs().max())
    return peak, peak/noise

# ── Run ───────────────────────────────────────────────────────────
print("\n=== Pierce-Point-Weighted TEC ===\n")
print("Comparing equal-weight vs pierce-point-weighted stacking\n")

results = []
fig, axes = plt.subplots(len(EVENTS), 3, figsize=(16, 4.5*len(EVENTS)))
fig.suptitle("Pierce-Point-Weighted TEC vs Equal-Weight Stacking\n"
             "Impact on TEC amplitude and wave height prediction accuracy",
             fontsize=12, fontweight='bold')

for row_idx, (eid, ecfg) in enumerate(EVENTS.items()):
    print(f"{'='*55}")
    print(f"[ {ecfg['name']} ]")
    eq_amps = {}; ppw_amps = {}; ipp_info = {}

    for sid, scfg in ecfg['stations'].items():
        og=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}o.Z"
        ng=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}n.Z"
        if not og.exists(): print(f"  {sid}: missing"); continue
        op=decompress(og)
        if not op: continue
        nav={}
        if ng.exists():
            np_=decompress(ng)
            if np_:
                nav=parse_nav(np_)
                if nav:
                    tsv=list(nav.keys())[0]; pos=keplerian_to_ecef(nav[tsv][0][1],nav[tsv][0][0])
                    if pos is not None:
                        d=np.linalg.norm(pos)/1000
                        if not 20000<d<30000: nav={}

        print(f"  {sid.upper()}:", end="")
        filt_eq, filt_ppw, stats = compute_tec_both(
            op, nav, scfg['lat'], scfg['lon'], scfg['alt'],
            ecfg['epi_lat'], ecfg['epi_lon'])

        if filt_eq is None: print(" failed"); continue

        amp_eq,  snr_eq  = get_peak_amp(filt_eq,  ecfg['quake_utc'], ecfg['window_h'])
        amp_ppw, snr_ppw = get_peak_amp(filt_ppw, ecfg['quake_utc'], ecfg['window_h'])

        if amp_eq and amp_ppw:
            change = (amp_ppw - amp_eq) / amp_eq * 100
            print(f"    EQ={amp_eq:.4f} PPW={amp_ppw:.4f} TECU  change={change:+.1f}%")
            eq_amps[sid]  = amp_eq
            ppw_amps[sid] = amp_ppw
            ipp_info[sid] = stats

    # Best station predictions
    if eq_amps:
        best_sid = max(eq_amps, key=lambda s: eq_amps[s])
        dist_km  = haversine_km(ecfg['epi_lat'],ecfg['epi_lon'],
                                ecfg['stations'][best_sid]['lat'],
                                ecfg['stations'][best_sid]['lon'])
        tide_dist = ecfg['tide_gauge']['dist_km']
        actual    = ecfg['tide_gauge']['wave_m']

        pred_eq  = predict_wave(eq_amps[best_sid],  ecfg['mw'], tide_dist)
        pred_ppw = predict_wave(ppw_amps[best_sid], ecfg['mw'], tide_dist)

        err_eq  = (pred_eq  - actual)/actual*100
        err_ppw = (pred_ppw - actual)/actual*100

        print(f"\n  Best station: {best_sid.upper()}")
        print(f"  Actual wave height: {actual:.3f} m")
        print(f"  Equal-weight pred:  {pred_eq:.3f} m  (error: {err_eq:+.0f}%)")
        print(f"  PPW pred:           {pred_ppw:.3f} m  (error: {err_ppw:+.0f}%)")
        improvement = abs(err_eq) - abs(err_ppw)
        print(f"  Error improvement:  {improvement:+.1f} percentage points")

        results.append({
            "event": ecfg['name'], "station": best_sid,
            "actual": actual,
            "pred_eq": pred_eq, "pred_ppw": pred_ppw,
            "err_eq": err_eq, "err_ppw": err_ppw,
            "improvement": improvement,
            "mean_ipp_dist": ipp_info.get(best_sid,{}).get("mean_ipp_dist_km",0),
            "mean_weight": ipp_info.get(best_sid,{}).get("mean_weight",1),
        })

        # Plot row
        qu = pd.Timestamp(ecfg['quake_utc'])
        colors_s = {"mkea":"#D85A30","kokb":"#185FA5","hnlc":"#7F77DD",
                    "guam":"#0F6E56","chat":"#BA7517"}

        # Panel 1: EQ stack
        ax = axes[row_idx,0]
        for sid in eq_amps:
            # re-load for plotting
            og=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}o.Z"
            ng=Path(ecfg["rinex_dir"])/f"{sid}{ecfg['doy']:03d}0.{ecfg['yr2']}n.Z"
            if not og.exists(): continue
            op=decompress(og); nav={}
            if ng.exists():
                np_=decompress(ng)
                if np_:
                    nav=parse_nav(np_)
            scfg=ecfg['stations'][sid]
            fe, fp, _ = compute_tec_both(op,nav,scfg['lat'],scfg['lon'],scfg['alt'],
                                          ecfg['epi_lat'],ecfg['epi_lon'])
            if fe is None: continue
            t=[(ts-qu).total_seconds()/3600 for ts in fe.index]
            ax.plot(t, fe.values, color=colors_s.get(sid,'gray'),
                    linewidth=0.8, alpha=0.8, label=sid.upper())
            t2=[(ts-qu).total_seconds()/3600 for ts in fp.index]
            axes[row_idx,1].plot(t2, fp.values, color=colors_s.get(sid,'gray'),
                                 linewidth=0.8, alpha=0.8, label=sid.upper())

        for axi in [axes[row_idx,0], axes[row_idx,1]]:
            axi.axvline(0,color='red',linestyle='--',linewidth=0.8,alpha=0.5)
            axi.axvspan(ecfg['window_h'][0],ecfg['window_h'][1],color='green',alpha=0.05)
            axi.set_xlabel("Hours after earthquake"); axi.set_ylabel("TEC (TECU)")
            axi.legend(fontsize=7,loc='upper left'); axi.grid(alpha=0.15)
            w0,w1=ecfg['window_h']
            axi.set_xlim(-1,w1+2)

        axes[row_idx,0].set_title(f"{ecfg['name']}\nEqual-weight stack", fontsize=9, fontweight='bold')
        axes[row_idx,1].set_title(f"{ecfg['name']}\nPierce-point-weighted stack", fontsize=9, fontweight='bold')

        # Panel 3: prediction comparison
        ax = axes[row_idx,2]
        labels = ['Equal\nweight', 'Pierce-pt\nweighted', 'Actual']
        vals   = [pred_eq, pred_ppw, actual]
        cols   = ['#555555','#0F6E56','#1a3a5c']
        bars = ax.bar(labels, vals, color=cols, alpha=0.85, edgecolor='white')
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x()+bar.get_width()/2, val+0.005,
                    f"{val:.3f}m", ha='center', va='bottom', fontsize=9, fontweight='bold')
        ax.axhline(actual, color='#1a3a5c', linestyle='--', alpha=0.5)
        ax.set_title(f"Wave height prediction\nErr: EQ={err_eq:+.0f}%  PPW={err_ppw:+.0f}%",
                    fontsize=9, fontweight='bold')
        ax.set_ylabel("Wave height (m)"); ax.grid(axis='y', alpha=0.2)
        ax.set_ylim(0, max(vals)*1.35)

plt.tight_layout()
plt.savefig("pierce_point_comparison.png", dpi=150)
plt.close()

# ── Summary ───────────────────────────────────────────────────────
print(f"\n{'='*55}")
print("PIERCE-POINT WEIGHTING SUMMARY")
print(f"{'='*55}")
print(f"{'Event':<30} {'EQ err':>8} {'PPW err':>8} {'Improvement':>12}")
for r in results:
    print(f"  {r['event']:<28} {r['err_eq']:>+7.0f}%  {r['err_ppw']:>+7.0f}%  "
          f"{r['improvement']:>+10.1f} pp")

avg_imp = np.mean([r['improvement'] for r in results])
print(f"\n  Average error improvement: {avg_imp:+.1f} percentage points")
if avg_imp > 5:
    print(f"  ✓ Pierce-point weighting improves amplitude accuracy")
elif avg_imp > 0:
    print(f"  ~ Minor improvement — geometry was already reasonable")
else:
    print(f"  ~ No improvement — IPP geometry not a dominant error source here")
    print(f"    → Other factors (corridor calibration, bathymetry) likely dominate")

print(f"\nSaved pierce_point_comparison.png")
print(f"Upload: pierce_point_comparison.png")
