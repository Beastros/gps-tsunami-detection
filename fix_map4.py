import os
TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()
s = s.replace(
    "center: [10, -170],\n    zoom: 2,",
    "center: [10, -160],\n    zoom: 2,"
)
s = s.replace(
    "worldCopyJump: false,",
    "worldCopyJump: true,"
)
open(TARGET, "w", encoding="utf-8").write(s)
print("Done")
