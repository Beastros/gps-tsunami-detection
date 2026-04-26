import os
TARGET = r"C:\Users\Mike\Desktop\repo\index.html"
s = open(TARGET, encoding="utf-8").read()
OLD = "loadSW();\nloadPipeline();\nsetInterval(loadSW,5*60*1000);"
NEW = "loadSW();\nloadPipeline();\nsetInterval(loadSW,5*60*1000);\ninitMap();"
if OLD in s:
    s = s.replace(OLD, NEW)
    open(TARGET, "w", encoding="utf-8").write(s)
    print("Patched OK")
else:
    print("ERROR: anchor not found")
