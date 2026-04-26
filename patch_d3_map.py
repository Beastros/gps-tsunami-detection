import os, sys

TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()
orig = s

# 1. Remove Leaflet CSS+JS from head, add D3+TopoJSON
s = s.replace(
    '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>\n<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n',
    ''
)

OLD_HEAD = '<link rel="preconnect" href="https://fonts.googleapis.com">'
NEW_HEAD = '''<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/topojson/3.0.2/topojson.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">'''
s = s.replace(OLD_HEAD, NEW_HEAD)

# 2. Replace map-wrap CSS
OLD_CSS = '''.map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px;height:580px;position:relative}
#pacific-map{width:100%;height:100%}
.leaflet-container{background:#040e1a!important}
.map-station-label{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;color:#00c8ff;white-space:nowrap}
.map-station-label-dim{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:9px;color:#00c8ff;opacity:0.7;white-space:nowrap}
.map-iono-label{background:transparent;border:none;box-shadow:none;font-family:'JetBrains Mono',monospace;font-size:8px;color:#ff9f43;opacity:0.85;white-space:nowrap}
.leaflet-popup-content-wrapper{background:#0c1829;border:1px solid #1e3a5f;border-radius:3px;color:#cce4ff;font-family:'JetBrains Mono',monospace;font-size:11px}
.leaflet-popup-tip{background:#0c1829}
.leaflet-popup-close-button{color:#6a9cc0!important}'''

NEW_CSS = '.map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px;position:relative}'

s = s.replace(OLD_CSS, NEW_CSS)

# 3. Replace map HTML
OLD_MAP = '''  <p class="section-title">Station Network &middot; Pacific Basin</p>
  <div class="map-wrap">
    <div id="pacific-map"></div>
  </div>'''

NEW_MAP = '''  <p class="section-title">Station Network &middot; Pacific Basin</p>
  <div class="map-wrap">
    <svg id="pmap" style="width:100%;display:block"></svg>
    <div id="mtt" style="position:absolute;display:none;background:#0c1829;border:1px solid #1e3a5f;border-radius:3px;padding:6px 10px;font-size:11px;color:#cce4ff;pointer-events:none;z-index:10;max-width:200px;line-height:1.5"></div>
    <div style="position:absolute;bottom:10px;left:10px;background:rgba(4,14,26,0.88);border:1px solid #1e3a5f;border-radius:3px;padding:7px 11px;font-family:var(--font-m);font-size:9px;color:#4a7a94;line-height:2.1">
      <div><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#00c8ff;margin-right:6px;vertical-align:middle"></span>GPS anchor station</div>
      <div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;border:1.5px solid #d4880a;margin-right:6px;vertical-align:middle"></span>DART buoy</div>
      <div><span style="display:inline-block;width:7px;height:7px;border:1.5px solid #ff9f43;transform:rotate(45deg);margin-right:7px;vertical-align:middle"></span>Ionosonde</div>
      <div><span style="display:inline-block;width:14px;height:2px;background:#c0392b;margin-right:6px;vertical-align:middle;opacity:0.75"></span>Subduction zone</div>
      <div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;border:1.5px solid #ffa726;margin-right:6px;vertical-align:middle"></span>Near-miss seismic</div>
    </div>
  </div>'''

s = s.replace(OLD_MAP, NEW_MAP)

# 4. Replace entire initMap + renderSeismicOnMap JS block
START = 'function initMap() {'
END = '// Hook into existing renderPoll'
si = s.find(START)
ei = s.find(END)
if si == -1 or ei == -1:
    print("ERROR: JS block boundaries not found")
    sys.exit(1)

NEW_JS = r"""function initMap() {
  var W=960, H=500;
  var svg=d3.select('#pmap').attr('viewBox','0 0 '+W+' '+H).attr('height',H);
  var proj=d3.geoNaturalEarth1().rotate([150,0]).scale(160).translate([W/2,H/2]);
  var path=d3.geoPath(proj);
  var tt=document.getElementById('mtt');
  var mapEl=document.getElementById('pmap');

  function showTip(html,e){
    tt.innerHTML=html; tt.style.display='block';
    var r=mapEl.getBoundingClientRect();
    var mx=e.clientX-r.left, my=e.clientY-r.top;
    tt.style.left=(mx+12)+'px'; tt.style.top=(my-10)+'px';
  }
  function hideTip(){ tt.style.display='none'; }

  var GPS=[
    {id:'GUAM',lat:13.489,lon:144.868,note:'Guam \u00b7 83m'},
    {id:'MKEA',lat:19.801,lon:-155.456,note:'Mauna Kea HI \u00b7 3763m'},
    {id:'KOKB',lat:22.127,lon:-159.665,note:'Kokee Kauai HI \u00b7 1167m'},
    {id:'HNLC',lat:21.297,lon:-157.816,note:'Honolulu HI \u00b7 5m'},
    {id:'CHAT',lat:-43.956,lon:-176.566,note:'Chatham Islands NZ \u00b7 63m'},
    {id:'THTI',lat:-17.577,lon:-149.606,note:'Tahiti \u00b7 87m'},
    {id:'AUCK',lat:-36.602,lon:174.834,note:'Auckland NZ \u00b7 106m (V4)'},
    {id:'NOUM',lat:-22.270,lon:166.413,note:'Noumea NC \u00b7 69m (V4)'},
    {id:'KWJ1',lat:8.722,lon:167.730,note:'Kwajalein \u00b7 39m (V4)'},
    {id:'HOLB',lat:50.640,lon:-128.133,note:'Holberg BC \u00b7 180m (V4)'},
  ];
  var IONO=[
    {id:'RP536',name:'Okinawa',lat:26.3,lon:127.8},
    {id:'TW637',name:'Zhongli',lat:24.97,lon:121.18},
    {id:'GU513',name:'Guam',lat:13.49,lon:144.87},
    {id:'WP937',name:'Wake Is.',lat:19.28,lon:166.65},
    {id:'KJ609',name:'Kwajalein',lat:8.72,lon:167.73},
    {id:'CH853',name:'Chatham Is.',lat:-43.93,lon:-176.57},
    {id:'AT138',name:'Townsville',lat:-19.63,lon:146.85},
  ];
  var DART=[
    [19.619,-154.063],[24.423,-162.058],[51.019,-154.059],[54.973,-162.071],
    [53.618,-164.988],[57.845,-137.981],[45.858,-128.826],[59.676,-144.003],
    [53.0,-129.8],[40.838,-129.079],[37.374,-129.803],[40.249,-134.063],
    [48.754,-129.986],[30.518,152.116],[28.994,178.006],[19.276,136.329],
    [-18.032,-86.485],[-20.671,-109.388],[-14.91,-105.172],[-22.81,-79.01],
    [-1.877,-82.398],[-1.723,-90.289],[-18.861,-173.036],[-32.54,-177.58],[-9.924,99.562],
  ];
  var SZ=[
    [[153,46],[147,43],[143,40],[141,37],[140,34],[141,31],[140,28],[142,26],[144,22],[147,18],[145,14],[142,11]],
    [[180,52],[172,54],[163,55],[154,54],[148,52]],
    [[-127,49],[-125,46],[-125,43]],
    [[-104,18],[-92,15],[-84,10]],
    [[-80,-2],[-79,-8],[-75,-15],[-70,-22],[-71,-28],[-72,-35],[-75,-43]],
    [[-174,-15],[-175,-20],[-177,-25],[-178,-30],[-179.5,-35]],
    [[157,-8],[166,-12],[168,-16],[169,-20]],
  ];

  fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json')
  .then(function(r){return r.json();})
  .then(function(world){
    svg.append('rect').attr('width',W).attr('height',H).attr('fill','#040e1a');
    var grat=d3.geoGraticule().step([30,30]);
    svg.append('path').datum(grat()).attr('d',path).attr('fill','none').attr('stroke','#0e2a3f').attr('stroke-width',0.4);
    svg.append('path').datum({type:'Sphere'}).attr('d',path).attr('fill','none').attr('stroke','#0e2a3f').attr('stroke-width',0.8);
    svg.append('path').datum(topojson.feature(world,world.objects.countries)).attr('d',path).attr('fill','#0d2236').attr('stroke','#1e4060').attr('stroke-width',0.6);

    SZ.forEach(function(coords){
      svg.append('path').datum({type:'Feature',geometry:{type:'LineString',coordinates:coords}})
        .attr('d',path).attr('fill','none').attr('stroke','#c0392b').attr('stroke-width',2).attr('opacity',0.72);
    });

    DART.forEach(function(b){
      var p=proj([b[1],b[0]]);
      if(!p)return;
      svg.append('circle').attr('cx',p[0]).attr('cy',p[1]).attr('r',3.5)
        .attr('fill','none').attr('stroke','#d4880a').attr('stroke-width',1.2).attr('opacity',0.75)
        .style('cursor','pointer')
        .on('mouseover',function(e){showTip('<b style="color:#d4880a">DART buoy</b><br><span style="color:#6a9cc0">NOAA NDBC pressure sensor</span>',e);})
        .on('mouseout',hideTip);
    });

    IONO.forEach(function(io){
      var p=proj([io.lon,io.lat]);
      if(!p)return;
      var s2=5;
      svg.append('rect').attr('x',p[0]-s2/2).attr('y',p[1]-s2/2).attr('width',s2).attr('height',s2)
        .attr('fill','none').attr('stroke','#ff9f43').attr('stroke-width',1.3)
        .attr('transform','rotate(45,'+p[0]+','+p[1]+')').attr('opacity',0.85)
        .style('cursor','pointer')
        .on('mouseover',function(e){showTip('<b style="color:#ff9f43">'+io.id+'</b><br>'+io.name+'<br><span style="color:#6a9cc0">GIRO Digisonde foF2</span>',e);})
        .on('mouseout',hideTip);
    });

    GPS.forEach(function(st){
      var p=proj([st.lon,st.lat]);
      if(!p)return;
      svg.append('circle').attr('cx',p[0]).attr('cy',p[1]).attr('r',7).attr('fill','#00c8ff').attr('opacity',0.12);
      svg.append('circle').attr('cx',p[0]).attr('cy',p[1]).attr('r',4.5).attr('fill','#00c8ff')
        .style('cursor','pointer')
        .on('mouseover',function(e){showTip('<b style="color:#00c8ff">'+st.id+'</b><br>'+st.note+'<br><span style="color:#6a9cc0">GPS anchor station</span>',e);})
        .on('mouseout',hideTip);
      svg.append('text').attr('x',p[0]+7).attr('y',p[1]+3)
        .attr('fill','#00c8ff').attr('font-size',9).attr('font-weight',600)
        .attr('font-family','JetBrains Mono,monospace').attr('pointer-events','none').text(st.id);
    });

    var hilo=proj([-155.087,19.730]);
    if(hilo){
      svg.append('circle').attr('cx',hilo[0]).attr('cy',hilo[1]).attr('r',5).attr('fill','none').attr('stroke','#00ff9d').attr('stroke-width',1.8)
        .style('cursor','pointer')
        .on('mouseover',function(e){showTip('<b style="color:#00ff9d">HILO</b><br>Primary tide gauge target<br>NOAA station 1617760',e);})
        .on('mouseout',hideTip);
      svg.append('circle').attr('cx',hilo[0]).attr('cy',hilo[1]).attr('r',2).attr('fill','#00ff9d').attr('pointer-events','none');
    }

    window._mapSvg=svg; window._mapProj=proj;
  }).catch(function(){
    svg.append('rect').attr('width',W).attr('height',H).attr('fill','#040e1a');
    svg.append('text').attr('x',W/2).attr('y',H/2).attr('text-anchor','middle').attr('fill','#6a9cc0').attr('font-size',13).text('Could not load world geography');
  });
}

function renderSeismicOnMap(rs) {
  var svg=window._mapSvg, proj=window._mapProj;
  if(!svg||!proj||!rs||!rs.length) return;
  svg.selectAll('.seismic-marker').remove();
  var now=Date.now();
  rs.slice(-80).forEach(function(e){
    if(e.lat==null||e.lon==null) return;
    var p=proj([e.lon,e.lat]);
    if(!p) return;
    var mag=e.mag||5.5;
    var r=Math.max(3,(mag-4.5)*4);
    var age=(now-new Date(e.ts).getTime())/(1000*3600);
    var op=Math.max(0.2,0.75-age/48);
    var nearMiss=e.delta!=null&&e.delta>-0.5&&e.delta<=0;
    var color=nearMiss?'#ffa726':'#c0702a';
    svg.append('circle').attr('class','seismic-marker')
      .attr('cx',p[0]).attr('cy',p[1]).attr('r',r)
      .attr('fill','none').attr('stroke',color).attr('stroke-width',nearMiss?1.8:1.0).attr('opacity',op);
    if(nearMiss){
      svg.append('circle').attr('class','seismic-marker')
        .attr('cx',p[0]).attr('cy',p[1]).attr('r',r+3)
        .attr('fill','none').attr('stroke','#ffa726').attr('stroke-width',0.5).attr('opacity',op*0.35);
    }
  });
}

"""

s = s[:si] + NEW_JS + s[ei:]

# 5. Wire initMap call
s = s.replace(
    'loadSW();\nloadPipeline();\nsetInterval(loadSW,5*60*1000);',
    'loadSW();\nloadPipeline();\nsetInterval(loadSW,5*60*1000);\ninitMap();'
)

# 6. Wire renderSeismicOnMap into renderPoll
OLD_SEISMIC = "    el('seismic-body').innerHTML='<table class=\"data-table\"><thead><tr><th>Time (UTC)</th><th>Mag</th><th>Location</th><th>Depth</th><th>Reason</th><th title=\"Delta from qualifying threshold\">Delta Mw</th></tr></thead><tbody>'+rows+'</tbody></table>';\n    renderSeismicOnMap(rs);"
if OLD_SEISMIC not in s:
    OLD_SEISMIC2 = "    el('seismic-body').innerHTML='<table class=\"data-table\"><thead><tr><th>Time (UTC)</th><th>Mag</th><th>Location</th><th>Depth</th><th>Reason</th><th title=\"Delta from qualifying threshold\">Delta Mw</th></tr></thead><tbody>'+rows+'</tbody></table>';"
    NEW_SEISMIC = OLD_SEISMIC2 + "\n    renderSeismicOnMap(rs);"
    s = s.replace(OLD_SEISMIC2, NEW_SEISMIC)

if s == orig:
    print("ERROR: no changes applied")
    sys.exit(1)

open(TARGET, "w", encoding="utf-8").write(s)
print("Patched OK:", TARGET)
