import os
path = os.path.join(r"C:\Users\Mike\Desktop\repo", "pipeline.py")

imports = [l for l in s.splitlines() if "notify_discord" in l and l.startswith("import")]
discord_blocks = s.count("discord_alerted")
error_blocks = s.count("send_pipeline_error")

print("=== pipeline.py verification ===")
print(f"notify_discord imports: {len(imports)} (should be 1)")
for i in imports:
    print(" ", i)
print(f"discord_alerted blocks: {discord_blocks} (should be 2 -- one check, one set)")
print(f"send_pipeline_error calls: {error_blocks} (should be 1)")

if len(imports) == 1 and error_blocks == 1:
    print("\nOK: duplicates removed")
else:
    print("\nWARNING: duplicates may still be present")

os.remove(__file__)
print("Self-deleted.")
