#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "index.html"
D = "d" + "iv"
text = ROOT.read_text(encoding="utf-8")

# CSS
text = text.replace(
    "#alert-banner{border-bottom:1px solid rgba(255,74,74,0.38);padding:11px 32px;background:rgba(255,40,40,0.1);animation:alert-bg-pulse 3s ease-in-out infinite}",
    "#alert-banner{border-bottom:1px solid var(--border);padding:12px 32px;background:var(--surface2)}\n"
    "#alert-banner.tone-alert{border-color:rgba(255,74,74,0.45);background:rgba(255,40,40,0.12);animation:alert-bg-pulse 3s ease-in-out infinite}\n"
    "#alert-banner.tone-warn{border-color:rgba(255,167,38,0.45);background:rgba(255,167,38,0.08)}\n"
    "#alert-banner.tone-error{border-color:rgba(255,74,74,0.5);background:rgba(255,40,40,0.14)}\n"
    "#alert-banner.tone-info{border-color:rgba(0,200,255,0.35);background:rgba(0,200,255,0.06)}",
)
if ".det-badge.ok{" not in text:
    text = text.replace(
        ".det-badge.silent{background:",
        ".det-badge.ok{background:rgba(0,255,157,.12);color:var(--accent2);border:1px solid rgba(0,255,157,.25)}\n"
        ".det-badge.warn{background:rgba(255,167,38,.1);color:var(--warn);border:1px solid rgba(255,167,38,.25)}\n"
        ".det-badge.silent{background:",
    )

# Banner HTML
banner_old = (
    f'<{D} id="alert-banner" style="display:none">\n'
    f'  <{D} style="display:flex;align-items:center;gap:16px;max-width:1400px;margin:0 auto">\n'
    f'    <{D} style="width:10px;height:10px;border-radius:50%;background:#ff4a4a;flex-shrink:0;animation:pulse-red 1.5s ease-in-out infinite"></{D}>\n'
    '    <span style="font-family:var(--font-d);font-size:11px;letter-spacing:.14em;color:#ff4a4a" id="alert-title">DETECTION ACTIVE</span>\n'
    '    <span style="font-family:var(--font-m);font-size:11px;color:#ffaaaa;flex:1" id="alert-detail"></span>\n'
    '    <span style="font-family:var(--font-m);font-size:10px;color:#ff7675;letter-spacing:.1em;border:1px solid rgba(255,74,74,0.4);padding:3px 10px;border-radius:2px;white-space:nowrap">FAST POLL &middot; 2 MIN CYCLES</span>\n'
    f"  </{D}>\n"
    f"</{D}>"
)
banner_new = (
    f'<{D} id="alert-banner" style="display:none">\n'
    f'  <{D} style="display:flex;align-items:center;gap:16px;max-width:1400px;margin:0 auto">\n'
    f'    <{D} data-alert-dot style="width:10px;height:10px;border-radius:50%;background:#ff4a4a;flex-shrink:0;animation:pulse-red 1.5s ease-in-out infinite"></{D}>\n'
    '    <span style="font-family:var(--font-d);font-size:11px;letter-spacing:.14em;color:var(--text-hi)" id="alert-title">MONITORING</span>\n'
    '    <span style="font-family:var(--font-m);font-size:11px;color:var(--text);flex:1;line-height:1.45" id="alert-detail"></span>\n'
    '    <span style="font-family:var(--font-m);font-size:10px;color:var(--dim);letter-spacing:.06em;border:1px solid var(--border);padding:3px 10px;border-radius:2px;white-space:nowrap" id="alert-badge-tag">Research monitor</span>\n'
    f"  </{D}>\n"
    f"</{D}>"
)
if banner_old in text:
    text = text.replace(banner_old, banner_new)

# Helpers
if "function describeLiveEvent" not in text:
    anchor = "  }) + ' UTC';\n}\n\n"
    helpers = (Path(__file__).parent / "_dashboard_ux_helpers.js.txt").read_text(encoding="utf-8")
    text = text.replace(anchor, anchor + helpers + "\n", 1)

# updateAlertBanner
ub_start = text.find("function updateAlertBanner(queue)")
ub_end = text.find("\n}\n\n</script>", ub_start)
new_ub = r"""function updateAlertBanner(queue){
  var banner=document.getElementById('alert-banner');
  if(!banner)return;
  var events=(queue.events||[]).filter(function(e){return e.status&&e.status!=='scored';});
  var liveBadge=document.querySelector('.live-badge');
  if(!events.length){
    banner.style.display='none';
    applyBannerTone(banner,null);
    if(liveBadge)liveBadge.innerHTML='<div class="pulse"></motion>LIVE · NEXT POLL';
    if(window._mapSvg)window._mapSvg.selectAll('.event-marker').remove();
    return;
  }
  banner.style.display='block';
  var ev=events[0];
  var info=describeLiveEvent(ev);
  applyBannerTone(banner,info.tone);
  var titleEl=document.getElementById('alert-title');
  var detailEl=document.getElementById('alert-detail');
  var tagEl=document.getElementById('alert-badge-tag');
  if(titleEl)titleEl.textContent=info.title;
  if(detailEl){
    detailEl.innerHTML='<strong>'+esc(info.detail)+'</strong>'
      +(info.note?'<br><span style="color:var(--dim)">'+esc(info.note)+'</span>':'');
  }
  if(tagEl)tagEl.textContent=info.tag||'Research monitor';
  if(liveBadge){
    var urgent=info.tone==='alert'||info.tone==='error';
    liveBadge.innerHTML='<div class="pulse" style="background:'+(urgent?'#ff4a4a':'var(--accent2)')+';box-shadow:0 0 8px '+(urgent?'#ff4a4a':'var(--accent2)')+'"></div>'
      +'<span style="color:'+(urgent?'#ff4a4a':'var(--accent2)')+'">'+(urgent?'LIVE · EVENT WATCH':'LIVE · NEXT POLL')+'</span>';
  }
  if(window._mapSvg&&window._mapProj){renderActiveEvent(events);}
  else{setTimeout(function(){if(window._mapSvg&&window._mapProj)renderActiveEvent(events);},2500);}
}"""
new_ub = new_ub.replace("</motion>", f"</{D}>").replace("<motion ", f"<{D} ")
if ub_start >= 0 and ub_end >= 0:
    text = text[:ub_start] + new_ub + text[ub_end + 2 :]

# renderLog events table body
old_rows = "  const rows = events.slice().reverse().map(e=>{\n    // scored events have fields at top level (from scorer.py)\n    const det = e.algo_detected ?? false;"
if old_rows in text:
    new_rows = r"""  const rows = events.slice().reverse().map(e=>{
    const tec = humanTec(e);
    const out = humanOutcome(e);
    const stList = stationListUpper(e);
    const conf = e.combined_confidence;
    let confCell = '<span style="color:var(--dim)">--</span>';
    if(conf!=null){
      const pct = Math.round(conf*100);
      const col = conf>=0.7?'var(--accent2)':conf>=0.35?'var(--warn)':'var(--dim)';
      confCell = '<div style="display:flex;align-items:center;gap:5px"><motion style="width:52px;height:5px;background:var(--surface3);border-radius:3px;overflow:hidden"><motion style="width:'+pct+'%;height:100%;background:'+col+';border-radius:3px"></motion></motion><span style="font-family:var(--font-m);font-size:11px;color:'+col+'">'+conf.toFixed(2)+'</span></motion>';
    }
    const ds = e.dart_status_prediction;
    const dart = humanDart(ds);
    const sw = e.space_weather_score;
    const swTxt = sw!=null?sw.toFixed(2):'--';
    const swCol = sw>=0.5?'var(--danger)':sw>=0.3?'var(--warn)':'var(--accent2)';
    const swTip = sw>=0.5?'Stormy ionosphere — GPS less reliable':sw>=0.3?'Elevated space weather':'Calm space weather';
    const outCol = out.tone==='good'?'var(--accent2)':out.tone==='bad'?'var(--danger)':out.tone==='warn'?'var(--warn)':'var(--dim)';
    return '<tr><td>'+fmtDate(e.quake_utc)+'</td><td>'+esc(e.place||'--')+'</td><td style="font-family:var(--font-m)">Mw '+(e.magnitude!=null?e.magnitude.toFixed(1):'--')+'</td><td>'+confCell+'</td><td title="'+esc(tec.tip)+'"><span class="det-badge '+tec.badge+'">'+esc(tec.label)+'</span>'+(stList.length?'<span style="display:block;font-size:10px;color:var(--dim);margin-top:2px">'+esc(stList.slice(0,4).join(' ')+(stList.length>4?' +'+ (stList.length-4):''))+'</span>':'')+'</td><td style="font-family:var(--font-m);color:'+outCol+'" title="'+esc(out.tip)+'">'+esc(out.label)+'</td><td title="Other constellations vs GPS" style="font-family:var(--font-m);color:var(--dim);text-align:center">'+(e.constellation_agreement?(e.constellation_agreement.n_detecting+'/'+e.constellation_agreement.n_available):'--')+'</td><td style="text-align:center;color:'+(e.dtec_corroborates?'var(--accent2)':'var(--dim)')+'" title="Rate of TEC change">'+(e.dtec_corroborates?'\u25CF':'\u25CB')+'</td><td style="text-align:center;color:'+(e.ionosonde_confirmed?'var(--accent2)':'var(--dim)')+'" title="Ionosphere sounder">'+(e.ionosonde_confirmed?'\u25CF':'\u25CB')+'</td><td style="text-align:center;font-size:11px;color:'+(e.dyfi_responses!=null&&e.dyfi_confirmed?'var(--accent2)':'var(--dim)')+'" title="USGS felt reports">'+(e.dyfi_responses!=null?String(e.dyfi_responses):'\u2014')+'</td><td title="'+esc(dart.tip)+'" style="font-family:var(--font-m);color:'+dart.col+';text-align:center">'+dart.sym+'</td><td style="font-family:var(--font-m);color:'+swCol+'" title="'+esc(swTip)+'">'+swTxt+'</td></tr>';
  }).join('');

  el('events-body').innerHTML='<table class="data-table"><thead><tr><th>Date (UTC)</th><th>Location</th><th>Mw</th><th title="Fusion confidence">Confidence</th><th title="GPS ionosphere check">GPS</th><th title="vs tide gauges after 24h">Result</th>"""
    new_rows = new_rows.replace("<motion ", f"<{D} ").replace("</motion>", f"</{D}>")
    i0 = text.find(old_rows)
    i1 = text.find("  }).join('');\n\n  el('events-body').innerHTML='<table class=\"data-table\"><thead><tr>'\n    +'<th>Date (UTC)</th>", i0)
    if i0 >= 0 and i1 >= 0:
        i1b = text.find("'</tr></thead><tbody>'+rows+'</tbody></table>';", i1)
        if i1b >= 0:
            text = text[:i0] + new_rows + "\n    +'<th title=\"GLONASS/Galileo vs GPS\">Const</th><th title=\"Rate of TEC change\">ΔTEC</th><th title=\"Ionosphere sounder\">Iono</th><th title=\"USGS felt reports\">DYFI</th><th title=\"Ocean buoys\">Buoys</th><th title=\"Space weather\">Space Wx</th>" + text[i1b:]

# misc
text = text.replace("b.textContent='GATED';", "b.textContent='STORM HOLD';")
text = text.replace("else if(score>=0.3){b.textContent='ACTIVE';b.className='sw-badge active';}", "else if(score>=0.3){b.textContent='ELEVATED';b.className='sw-badge active';}")
text = text.replace("else{b.textContent='CLEAR';b.className='sw-badge clear';}", "else{b.textContent='CALM';b.className='sw-badge clear';}")
text = text.replace(">TP</div>", ">Confirmed</motion>".replace("motion", D))
text = text.replace(">TN</div>", ">Quiet</motion>".replace("motion", D))
text = text.replace(">FP</motion>", ">GPS only</motion>".replace("motion", D))
text = text.replace(">FN</motion>", ">Gauges only</motion>".replace("motion", D))
text = text.replace(">GEO</motion>", ">Limited</motion>".replace("motion", D))
text = text.replace("True Positive Rate", "Detection rate")
text = text.replace("False Alarm Rate", "False alarm rate")
text = text.replace("+(ok?'OK':'ERR')+'</span>", "+(ok?'Healthy':'Issue')+'</span>")
text = text.replace("errN?'ERR':'OK'", "errN?'Issue':'Healthy'")
text = text.replace("setErr('Could not load poll_log.json from GitHub');", "setErr('Cannot reach GitHub');")
text = text.replace(".text('ACTIVE');", ".text((function(){var st=(ev.status||'').toLowerCase();if(st==='predicted'&&ev.prediction&&ev.prediction.detected)return 'SIGNAL';if(st==='predicted')return 'CLEAR';if(st==='rinex_failed'||st==='detector_failed')return 'RETRY';return 'WATCH';})());")
text = text.replace("+(e.reason||'--')+'</span></td>", "+(humanNearMiss(e.reason))+'</span></td>")

ROOT.write_text(text, encoding="utf-8")
print("OK:", ROOT)
