import os
TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()

# Fix center and zoom
s = s.replace(
    "center: [15, -170],\n    zoom: 3,",
    "center: [15, 180],\n    zoom: 3,"
)

# Fix label directions for crowded Hawaii stations
s = s.replace(
    "{id:'MKEA', lat:19.801,  lon:-155.456, note:'Mauna Kea HI \u2014 3763m'},\n    {id:'KOKB', lat:22.127,  lon:-159.665, note:'Kokee Kauai HI \u2014 1167m'},\n    {id:'HNLC', lat:21.297,  lon:-157.816, note:'Honolulu HI \u2014 5m'},",
    "{id:'MKEA', lat:19.801,  lon:-155.456, note:'Mauna Kea HI \u2014 3763m', ldir:'right'},\n    {id:'KOKB', lat:22.127,  lon:-159.665, note:'Kokee Kauai HI \u2014 1167m', ldir:'top'},\n    {id:'HNLC', lat:21.297,  lon:-157.816, note:'Honolulu HI \u2014 5m', ldir:'bottom'},"
)

# Fix HOLB label direction
s = s.replace(
    "{id:'HOLB', lat: 50.640, lon:-128.133, note:'Holberg BC \u2014 180m (V4)'},",
    "{id:'HOLB', lat: 50.640, lon:-128.133, note:'Holberg BC \u2014 180m (V4)', ldir:'left'},"
)

# Fix CHAT label direction
s = s.replace(
    "{id:'CHAT', lat:-43.956, lon:-176.566, note:'Chatham Islands NZ \u2014 63m'},",
    "{id:'CHAT', lat:-43.956, lon:-176.566, note:'Chatham Islands NZ \u2014 63m', ldir:'left'},"
)

# Update label placement to use ldir
s = s.replace(
    "L.tooltip({permanent:true, direction:'right', offset:[8,0], className:'map-station-label'})\n     .setContent(s.id).setLatLng([s.lat, s.lon]).addTo(map);",
    "L.tooltip({permanent:true, direction:s.ldir||'right', offset:[8,0], className:'map-station-label'})\n     .setContent(s.id).setLatLng([s.lat, s.lon]).addTo(map);"
)

if "center: [15, 180]" in s:
    print("Center fixed")
open(TARGET, "w", encoding="utf-8").write(s)
print("Patched OK")
