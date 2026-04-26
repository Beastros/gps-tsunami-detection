import os
TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()

# Remove center/zoom, use fitBounds instead to force Pacific view
s = s.replace(
    "center: [10, -160],\n    zoom: 2,",
    "center: [10, 180],\n    zoom: 3,"
)
s = s.replace(
    "worldCopyJump: true,",
    "worldCopyJump: true,\n    maxBounds: [[-65, 90], [70, -60]],"
)

open(TARGET, "w", encoding="utf-8").write(s)
print("Done")
