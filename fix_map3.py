import os
TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()

# Fix center to properly show full Pacific -- lon -150 at zoom 2.5 shows everything
s = s.replace(
    "center: [15, 180],\n    zoom: 3,",
    "center: [10, -170],\n    zoom: 2,"
)

# Bump map height so there's more room
s = s.replace(
    ".map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px;height:520px;position:relative}",
    ".map-wrap{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:20px;height:580px;position:relative}"
)

open(TARGET, "w", encoding="utf-8").write(s)
print("Patched OK -- center:", "10, -170", "zoom: 2")
