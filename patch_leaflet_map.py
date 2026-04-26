import os, sys

TARGET = r"C:\Users\Mike\Desktop\repo\index.html"

# ── Find and replace the entire map section ──────────────────────────
# Replace from <p class="section-title">Station Network to end of </div> (map-wrap)

OLD_MAP_TITLE = '  <p class="section-title">Station Network &middot; Pacific Basin</p>\n  <div class="map-wrap">'

# Find the closing </div> after map-wrap - we need to replace everything between
# section title and the closing map-wrap div

OLD_MAP_CSS = '.map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px}\n.map-wrap svg{width:100%;height:auto;display:block}'

NEW_MAP_CSS = '''.map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px;height:520px;position:relative}
#pacific-map{width:100%;height:100%}
.leaflet-container{background:#040e1a!important}
.map-station-label{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;color:#00c8ff;white-space:nowrap}
.map-station-label-dim{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:9px;color:#00c8ff;opacity:0.7;white-space:nowrap}
.map-iono-label{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:8px;color:#ff9f43;opacity:0.85;white-space:nowrap}
.leaflet-popup-content-wrapper{background:#0c1829;border:1px solid #1e3a5f;border-radius:3px;color:#cce4ff;font-family:'JetBrains Mono',monospace;font-size:11px}
.leaflet-popup-tip{background:#0c1829}
.leaflet-popup-close-button{color:#6a9cc0!important}'''

NEW_MAP_BLOCK = '''  <p class="section-title">Station Network &middot; Pacific Basin</p>
  <div class="map-wrap">
    <div id="pacific-map"></div>
  </div>'''

NEW_MAP_JS = '''
// ── Leaflet Pacific Basin Map ─────────────────────────────────────
function initMap() {
  if (!window.L) { setTimeout(initMap, 200); return; }

  var map = L.map('pacific-map', {
    center: [15, -170],
    zoom: 3,
    minZoom: 2,
    maxZoom: 8,
    worldCopyJump: false,
    zoomControl: true,
  });

  // Dark CartoDB tiles
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
    opacity: 0.85,
  }).addTo(map);

  // ── GPS Anchor stations ─────────────────────────────────────────
  var GPS_STATIONS = [
    {id:'MKEA', lat:19.801,  lon:-155.456, note:'Mauna Kea HI — 3763m'},
    {id:'KOKB', lat:22.127,  lon:-159.665, note:'Kokee Kauai HI — 1167m'},
    {id:'HNLC', lat:21.297,  lon:-157.816, note:'Honolulu HI — 5m'},
    {id:'GUAM', lat:13.489,  lon: 144.868, note:'Guam — 83m'},
    {id:'CHAT', lat:-43.956, lon:-176.566, note:'Chatham Islands NZ — 63m'},
    {id:'THTI', lat:-17.577, lon:-149.606, note:'Tahiti — 87m'},
    {id:'AUCK', lat:-36.602, lon: 174.834, note:'Auckland NZ — 106m (V4)'},
    {id:'NOUM', lat:-22.270, lon: 166.413, note:'Noumea NC — 69m (V4)'},
    {id:'KWJ1', lat:  8.722, lon: 167.730, note:'Kwajalein — 39m (V4)'},
    {id:'HOLB', lat: 50.640, lon:-128.133, note:'Holberg BC — 180m (V4)'},
  ];

  var stationIcon = L.divIcon({
    className: '',
    html: '<div style="width:11px;height:11px;border-radius:50%;background:#00c8ff;box-shadow:0 0 8px #00c8ff;border:2px solid rgba(0,200,255,0.3)"></div>',
    iconSize: [11,11], iconAnchor: [5,5],
  });

  GPS_STATIONS.forEach(function(s) {
    var m = L.marker([s.lat, s.lon], {icon: stationIcon}).addTo(map);
    m.bindPopup('<b style="color:#00c8ff">' + s.id + '</b><br>' + s.note + '<br><span style="color:#6a9cc0">GPS Anchor Station</span>');
    L.tooltip({permanent:true, direction:'right', offset:[8,0], className:'map-station-label'})
     .setContent(s.id).setLatLng([s.lat, s.lon]).addTo(map);
  });

  // Hilo tide gauge target
  var targetIcon = L.divIcon({
    className: '',
    html: '<div style="width:9px;height:9px;border-radius:50%;background:transparent;border:2px solid #00ff9d;box-shadow:0 0 6px #00ff9d"></div>',
    iconSize: [9,9], iconAnchor: [4,4],
  });
  var hiloM = L.marker([19.730,-155.087], {icon: targetIcon}).addTo(map);
  hiloM.bindPopup('<b style="color:#00ff9d">HILO</b><br>Primary tide gauge target<br>NOAA station 1617760');
  L.tooltip({permanent:true, direction:'right', offset:[6,0], className:'map-station-label-dim'})
   .setContent('HILO').setLatLng([19.730,-155.087]).addTo(map);

  // ── GIRO Ionosonde stations ─────────────────────────────────────
  var IONOSONDES = [
    {id:'RP536', name:'Okinawa',    lat:26.30, lon:127.80},
    {id:'TW637', name:'Zhongli',    lat:24.97, lon:121.18},
    {id:'GU513', name:'Guam',       lat:13.49, lon:144.87},
    {id:'WP937', name:'Wake Is.',   lat:19.28, lon:166.65},
    {id:'KJ609', name:'Kwajalein',  lat: 8.72, lon:167.73},
    {id:'CH853', name:'Chatham Is.',lat:-43.93,lon:-176.57},
    {id:'AT138', name:'Townsville', lat:-19.63,lon:146.85},
  ];

  function makeDiamond(color) {
    return L.divIcon({
      className: '',
      html: '<div style="width:8px;height:8px;background:transparent;border:1.5px solid '+color+';transform:rotate(45deg);opacity:0.85"></div>',
      iconSize: [8,8], iconAnchor: [4,4],
    });
  }
  var ionoIcon = makeDiamond('#ff9f43');

  IONOSONDES.forEach(function(s) {
    var m = L.marker([s.lat, s.lon], {icon: ionoIcon}).addTo(map);
    m.bindPopup('<b style="color:#ff9f43">' + s.id + '</b><br>' + s.name + '<br><span style="color:#6a9cc0">GIRO Digisonde foF2</span>');
    L.tooltip({permanent:false, direction:'right', offset:[6,0], className:'map-iono-label'})
     .setContent(s.id + ' ' + s.name).setLatLng([s.lat, s.lon]).addTo(map);
  });

  // ── DART Buoys ──────────────────────────────────────────────────
  var DART_BUOYS = [
    {id:'51407', lat:19.619,  lon:-154.063},
    {id:'51406', lat:24.423,  lon:-162.058},
    {id:'46402', lat:51.019,  lon:-154.059},
    {id:'46407', lat:54.973,  lon:-162.071},
    {id:'46409', lat:53.618,  lon:-164.988},
    {id:'46403', lat:57.845,  lon:-137.981},
    {id:'46404', lat:45.858,  lon:-128.826},
    {id:'46408', lat:59.676,  lon:-144.003},
    {id:'46410', lat:53.000,  lon:-129.800},
    {id:'46411', lat:40.838,  lon:-129.079},
    {id:'46412', lat:37.374,  lon:-129.803},
    {id:'46414', lat:40.249,  lon:-134.063},
    {id:'46419', lat:48.754,  lon:-129.986},
    {id:'21413', lat:30.518,  lon:152.116},
    {id:'21414', lat:28.994,  lon:178.006},
    {id:'21415', lat:30.518,  lon:152.116},
    {id:'21416', lat:19.276,  lon:136.329},
    {id:'32401', lat:-18.032, lon:-86.485},
    {id:'32402', lat:-20.671, lon:-109.388},
    {id:'32403', lat:-14.910, lon:-105.172},
    {id:'32411', lat:-22.810, lon: -79.010},
    {id:'32412', lat: -1.877, lon: -82.398},
    {id:'43412', lat: -1.723, lon: -90.289},
    {id:'55012', lat:-18.861, lon:-173.036},
    {id:'55023', lat:-32.540, lon:-177.580},
    {id:'23227', lat: -9.924, lon:  99.562},
  ];

  var dartIcon = L.divIcon({
    className: '',
    html: '<div style="width:7px;height:7px;border-radius:50%;background:transparent;border:1.5px solid #d4880a;opacity:0.75"></div>',
    iconSize: [7,7], iconAnchor: [3,3],
  });

  DART_BUOYS.forEach(function(b) {
    var m = L.marker([b.lat, b.lon], {icon: dartIcon}).addTo(map);
    m.bindPopup('<b style="color:#d4880a">DART ' + b.id + '</b><br><span style="color:#6a9cc0">NOAA NDBC pressure sensor</span>');
  });

  // ── Subduction zones ────────────────────────────────────────────
  var SZ_STYLE = {color:'#c0392b', weight:2.2, opacity:0.75, dashArray:null};

  var subductionZones = [
    // Japan/Kuril trench
    [[46,153],[43,147],[40,143],[37,141],[34,140],[31,141],[28,140]],
    // Izu-Bonin / Mariana
    [[26,142],[22,144],[18,147],[14,145],[11,142]],
    // Aleutian
    [[52,180],[54,172],[55,163],[54,154],[52,148]],
    // Cascadia
    [[49,-127],[46,-125],[43,-125]],
    // Central America
    [[18,-104],[15,-92],[10,-84]],
    // South America (Peru-Chile)
    [[-2,-80],[-8,-79],[-15,-75],[-22,-70],[-28,-71],[-35,-72],[-43,-75]],
    // Tonga-Kermadec
    [[-15,-174],[-20,-175],[-25,-177],[-30,-178],[-35,-179]],
    // Vanuatu/Solomon
    [[-8,157],[-12,166],[-16,168],[-20,169]],
  ];

  subductionZones.forEach(function(coords) {
    L.polyline(coords, SZ_STYLE).addTo(map);
  });

  // ── Near-miss seismic events (dynamic from poll_log) ────────────
  window._leafletMap = map;
}

function renderSeismicOnMap(rs) {
  var map = window._leafletMap;
  if (!map || !rs || !rs.length) return;
  if (window._seismicLayer) { window._seismicLayer.clearLayers(); }
  else { window._seismicLayer = L.layerGroup().addTo(map); }

  var now = Date.now();
  rs.slice(-80).forEach(function(e) {
    if (e.lat == null || e.lon == null) return;
    var mag = e.mag || 5.5;
    var r = Math.max(4, (mag - 4.5) * 5);
    var age = (now - new Date(e.ts).getTime()) / (1000*3600);
    var op = Math.max(0.2, 0.75 - age/48);
    var nearMiss = e.delta != null && e.delta > -0.5 && e.delta <= 0;
    var color = nearMiss ? '#ffa726' : '#c0702a';
    var weight = nearMiss ? 1.8 : 1.0;

    var c = L.circleMarker([e.lat, e.lon], {
      radius: r, color: color, weight: weight,
      fill: false, opacity: op,
    });
    c.bindPopup(
      '<b style="color:#ffa726">Mw ' + (mag.toFixed ? mag.toFixed(1) : mag) + '</b><br>' +
      (e.place || '') + '<br>' +
      '<span style="color:#6a9cc0">Reason: ' + (e.reason || 'filtered') + '</span>' +
      (e.delta != null ? '<br><span style="color:#6a9cc0">Delta: ' + (e.delta >= 0 ? '+' : '') + e.delta.toFixed(1) + ' Mw</span>' : '')
    );
    window._seismicLayer.addLayer(c);

    if (nearMiss) {
      window._seismicLayer.addLayer(L.circleMarker([e.lat, e.lon], {
        radius: r + 4, color: '#ffa726', weight: 0.5,
        fill: false, opacity: op * 0.35,
      }));
    }
  });
}

// Hook into existing renderPoll to also update Leaflet seismic layer
var _origRenderPoll = typeof renderPoll === 'function' ? renderPoll : null;
'''

print("Patch script loaded OK")

s = open(TARGET, encoding="utf-8").read()
orig = s

# 1. Update CSS
if OLD_MAP_CSS not in s:
    print("ERROR: CSS anchor not found")
    sys.exit(1)
s = s.replace(OLD_MAP_CSS, NEW_MAP_CSS)

# 2. Replace map HTML block (section title + map-wrap with SVG)
# Find the section title start
TITLE_START = '  <p class="section-title">Station Network &middot; Pacific Basin</p>'
MAP_END_MARKER = '  <p class="section-title">Performance Metrics</p>'

ti = s.find(TITLE_START)
pe = s.find(MAP_END_MARKER)
if ti == -1 or pe == -1:
    print("ERROR: map block boundaries not found")
    sys.exit(1)

s = s[:ti] + NEW_MAP_BLOCK + '\n\n  ' + s[pe:]

# 3. Add Leaflet CSS+JS to <head>
OLD_HEAD = '<link rel="preconnect" href="https://fonts.googleapis.com">'
NEW_HEAD = '''<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">'''
if OLD_HEAD not in s:
    print("ERROR: head anchor not found")
    sys.exit(1)
s = s.replace(OLD_HEAD, NEW_HEAD)

# 4. Add map init call and seismic render function before closing </script>
OLD_LOADPIPELINE = 'loadSW(); loadPipeline(); setInterval(loadSW,300000); setInterval(loadPipeline,300000);'
if OLD_LOADPIPELINE not in s:
    # try alternate
    OLD_LOADPIPELINE = 'loadSW();\nloadPipeline();\nsetInterval(loadSW,300000);\nsetInterval(loadPipeline,300000);'

NEW_LOADPIPELINE = OLD_LOADPIPELINE + '\ninitMap();'

# 5. Inject map JS before the final </script>
SCRIPT_END = '</script>\n</body>'
MAP_JS_INJECT = NEW_MAP_JS + '\n</script>\n</body>'

if SCRIPT_END not in s:
    print("ERROR: script end not found")
    sys.exit(1)
s = s.replace(SCRIPT_END, MAP_JS_INJECT)

# Also replace renderSeismicOnMap call in existing renderPoll
# After the seismic table is built, call renderSeismicOnMap
OLD_SEISMIC_END = "    el('seismic-body').innerHTML='<table class=\"data-table\"><thead><tr><th>Time (UTC)</th><th>Mag</th><th>Location</th><th>Depth</th><th>Reason</th><th title=\"Delta from qualifying threshold\">Delta Mw</th></tr></thead><tbody>'+rows+'</tbody></table>';"
NEW_SEISMIC_END = OLD_SEISMIC_END + "\n    renderSeismicOnMap(rs);"

if OLD_SEISMIC_END in s:
    s = s.replace(OLD_SEISMIC_END, NEW_SEISMIC_END)
else:
    print("WARNING: seismic render hook not found - map seismic markers may not auto-update")

# Also wire up initMap call
if OLD_LOADPIPELINE in s:
    s = s.replace(OLD_LOADPIPELINE, NEW_LOADPIPELINE)
else:
    print("WARNING: loadPipeline call not found - map may not auto-init")

if s == orig:
    print("ERROR: no changes applied")
    sys.exit(1)

open(TARGET, "w", encoding="utf-8").write(s)
print("Patched OK:", TARGET)
