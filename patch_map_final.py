import os, sys

TARGET = r"C:\Users\Mike\Desktop\repo\index.html"

s = open(TARGET, encoding="utf-8").read()
orig = s

# Replace the entire initMap function with a clean rewrite
# Find start and end of initMap
START = "function initMap() {"
END = "// Hook into existing renderPoll"

si = s.find(START)
ei = s.find(END)
if si == -1 or ei == -1:
    print("ERROR: could not find initMap boundaries")
    sys.exit(1)

NEW_INIT_MAP = r"""function initMap() {
  // Use a simple WMS/tile approach but pan to show Pacific correctly.
  // Key insight: center at lon=180 wraps correctly at zoom 3 with worldCopyJump.
  // We use CRS.Simple alternative: Leaflet with noWrap=false and a W-Pacific center.

  var map = L.map('pacific-map', {
    center: [5, 170],
    zoom: 3,
    minZoom: 2,
    maxZoom: 9,
    worldCopyJump: false,
    zoomControl: true,
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
    opacity: 0.9,
    noWrap: false,
  }).addTo(map);

  // Force pan after tiles load to center on Pacific properly
  map.once('load', function() { map.setView([5, 170], 3); });
  setTimeout(function(){ map.setView([5, 170], 3); }, 300);

  // ── GPS Anchor stations ─────────────────────────────────────────
  var GPS_STATIONS = [
    {id:'GUAM', lat:13.489,  lon: 144.868, note:'Guam — 83m',                  ldir:'right'},
    {id:'MKEA', lat:19.801,  lon:-155.456, note:'Mauna Kea HI — 3763m',        ldir:'right'},
    {id:'KOKB', lat:22.127,  lon:-159.665, note:'Kokee Kauai HI — 1167m',      ldir:'top'},
    {id:'HNLC', lat:21.297,  lon:-157.816, note:'Honolulu HI — 5m',            ldir:'bottom'},
    {id:'CHAT', lat:-43.956, lon:-176.566, note:'Chatham Islands NZ — 63m',    ldir:'right'},
    {id:'THTI', lat:-17.577, lon:-149.606, note:'Tahiti — 87m',                ldir:'right'},
    {id:'AUCK', lat:-36.602, lon: 174.834, note:'Auckland NZ — 106m (V4)',     ldir:'right'},
    {id:'NOUM', lat:-22.270, lon: 166.413, note:'Noumea NC — 69m (V4)',        ldir:'right'},
    {id:'KWJ1', lat:  8.722, lon: 167.730, note:'Kwajalein — 39m (V4)',        ldir:'right'},
    {id:'HOLB', lat: 50.640, lon:-128.133, note:'Holberg BC — 180m (V4)',      ldir:'right'},
  ];

  var stationIcon = L.divIcon({
    className: '',
    html: '<div style="width:11px;height:11px;border-radius:50%;background:#00c8ff;box-shadow:0 0 8px #00c8ff;border:2px solid rgba(0,200,255,0.3)"></div>',
    iconSize: [11,11], iconAnchor: [5,5],
  });

  GPS_STATIONS.forEach(function(st) {
    var m = L.marker([st.lat, st.lon], {icon: stationIcon}).addTo(map);
    m.bindPopup('<b style="color:#00c8ff">' + st.id + '</b><br>' + st.note + '<br><span style="color:#6a9cc0">GPS Anchor Station</span>');
    L.tooltip({permanent:true, direction: st.ldir||'right', offset:[8,0], className:'map-station-label'})
     .setContent(st.id).setLatLng([st.lat, st.lon]).addTo(map);
  });

  // Hilo tide gauge
  var targetIcon = L.divIcon({
    className: '',
    html: '<div style="width:9px;height:9px;border-radius:50%;background:transparent;border:2px solid #00ff9d;box-shadow:0 0 6px #00ff9d"></div>',
    iconSize: [9,9], iconAnchor: [4,4],
  });
  var hiloM = L.marker([19.730,-155.087], {icon: targetIcon}).addTo(map);
  hiloM.bindPopup('<b style="color:#00ff9d">HILO</b><br>Primary tide gauge target<br>NOAA station 1617760');
  L.tooltip({permanent:true, direction:'bottom', offset:[0,6], className:'map-station-label-dim'})
   .setContent('HILO').setLatLng([19.730,-155.087]).addTo(map);

  // ── GIRO Ionosonde stations ─────────────────────────────────────
  var IONOSONDES = [
    {id:'RP536', name:'Okinawa',     lat:26.30,  lon:127.80},
    {id:'TW637', name:'Zhongli',     lat:24.97,  lon:121.18},
    {id:'GU513', name:'Guam',        lat:13.49,  lon:144.87},
    {id:'WP937', name:'Wake Is.',    lat:19.28,  lon:166.65},
    {id:'KJ609', name:'Kwajalein',   lat: 8.72,  lon:167.73},
    {id:'CH853', name:'Chatham Is.', lat:-43.93, lon:-176.57},
    {id:'AT138', name:'Townsville',  lat:-19.63, lon:146.85},
  ];

  var ionoIcon = L.divIcon({
    className: '',
    html: '<div style="width:8px;height:8px;background:transparent;border:1.5px solid #ff9f43;transform:rotate(45deg);opacity:0.85"></div>',
    iconSize: [8,8], iconAnchor: [4,4],
  });

  IONOSONDES.forEach(function(io) {
    var m = L.marker([io.lat, io.lon], {icon: ionoIcon}).addTo(map);
    m.bindPopup('<b style="color:#ff9f43">' + io.id + '</b><br>' + io.name + '<br><span style="color:#6a9cc0">GIRO Digisonde foF2</span>');
  });

  // ── DART Buoys ──────────────────────────────────────────────────
  var DART_BUOYS = [
    [19.619,-154.063],[24.423,-162.058],[51.019,-154.059],[54.973,-162.071],
    [53.618,-164.988],[57.845,-137.981],[45.858,-128.826],[59.676,-144.003],
    [53.000,-129.800],[40.838,-129.079],[37.374,-129.803],[40.249,-134.063],
    [48.754,-129.986],[30.518, 152.116],[28.994, 178.006],[19.276, 136.329],
    [-18.032,-86.485],[-20.671,-109.388],[-14.910,-105.172],[-22.810,-79.010],
    [-1.877,-82.398],[-1.723,-90.289],[-18.861,-173.036],[-32.540,-177.580],
    [-9.924, 99.562],
  ];

  var dartIcon = L.divIcon({
    className: '',
    html: '<div style="width:7px;height:7px;border-radius:50%;background:transparent;border:1.5px solid #d4880a;opacity:0.75"></div>',
    iconSize: [7,7], iconAnchor: [3,3],
  });

  DART_BUOYS.forEach(function(b) {
    L.marker(b, {icon: dartIcon}).addTo(map)
     .bindPopup('<b style="color:#d4880a">DART Buoy</b><br><span style="color:#6a9cc0">NOAA NDBC pressure sensor</span>');
  });

  // ── Subduction zones ────────────────────────────────────────────
  var SZ = {color:'#c0392b', weight:2, opacity:0.7};
  [
    [[46,153],[43,147],[40,143],[37,141],[34,140],[31,141],[28,140],[26,142],[22,144],[18,147],[14,145],[11,142]],
    [[52,190],[54,197],[55,196],[54,206],[52,215]],
    [[49,-127],[46,-125],[43,-125],[18,-104],[15,-92],[10,-84]],
    [[-2,-80],[-8,-79],[-15,-75],[-22,-70],[-28,-71],[-35,-72],[-43,-75]],
    [[-15,-174],[-20,-175],[-25,-177],[-30,-178],[-35,180]],
    [[-8,157],[-12,166],[-16,168],[-20,169]],
  ].forEach(function(c){ L.polyline(c, SZ).addTo(map); });

  window._leafletMap = map;
}

"""

s = s[:si] + NEW_INIT_MAP + s[ei:]

if s == orig:
    print("ERROR: no changes")
    sys.exit(1)

open(TARGET, "w", encoding="utf-8").write(s)
print("Patched OK")
