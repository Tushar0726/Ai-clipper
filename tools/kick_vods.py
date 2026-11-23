"""List a Kick channel's past streams (VODs) with the direct HLS link the clipper can download.

usage: python3 tools/kick_vods.py <channel> [--gta]          e.g.  python3 tools/kick_vods.py n3on --gta
Kick VOD page links (kick.com/<ch>/videos/<uuid>) don't work with yt-dlp here; the "source" .m3u8
printed below does. Pass that .m3u8 to `gta6clip.py prep`.
"""
import json, re, subprocess, sys

ch = sys.argv[1].lower().lstrip("@")
gta_only = "--gta" in sys.argv
seen = {}
for page in range(1, 6):
    try:
        out = subprocess.run(["curl", "-s", "-m", "20", "-A", "Mozilla/5.0",
                              f"https://kick.com/api/v2/channels/{ch}/videos?page={page}"], capture_output=True, text=True).stdout
        data = json.loads(out)
    except Exception as e:
        print("request failed:", e); break
    if not data:
        break
    new = [v for v in data if v["id"] not in seen]
    if not new:
        break
    for v in new:
        seen[v["id"]] = v
rows = sorted(seen.values(), key=lambda v: v.get("start_time", ""), reverse=True)
if gta_only:
    rows = [v for v in rows if re.search(r"gta|grand theft", v.get("session_title", ""), re.I)]
print(f"{len(rows)} streams for {ch}\n")
for i, v in enumerate(rows):
    print(f"[{i}] {v.get('start_time','')[:16]}  {v['duration']/3600000:.1f} h  {v.get('viewer_count',0):>6} viewers  {v.get('session_title','')[:70]}")
    print(f"     {v.get('source')}")
