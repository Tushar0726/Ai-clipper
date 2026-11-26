"""One queue, one clip at a time (RAM): N3on and Carry interleaved."""
import sys, json, csv, traceback, itertools
from pathlib import Path
sys.path.insert(0, "/home/user/Ai-clipper")
import clipper as c
from shorts import render_short, find_streamer_face, probe


def is_camera_only(path):
    """True when the streamer fills the screen (just chatting, no gameplay)."""
    w, _, _ = probe(path)
    face = find_streamer_face(path)
    return face is not None and face[2] > w * 0.11  # overlay cams ~60-160px, full camera ~280px+
S = None
c1 = json.load(open(Path(__file__).with_name("cands.json")))
JOBS = {}
for who, layout, creator, picks, n_vod in [("n3on", "panel", "n3on", [22, 24, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35], 30),
                                           ("carry", "inline", "carryminati", [3, 6, 9, 10, 11, 13, 14, 15, 17, 18, 20], 80)]:
    out = Path(f"/home/user/Ai-clipper/output/{who}_shorts"); (out / "_raw").mkdir(parents=True, exist_ok=True)
    print(f"analysing {who} streams...", flush=True)
    vod = c.kick_vods(creator, "Grand Theft Auto VI", n_vod * 2, 45)
    vod = [x for x in vod if x["start"] >= 1200]  # first 20 min of a stream = countdown / intro, no gameplay
    items = [("clip", c1[i][1]) for i in picks] + [("stream", x) for x in vod]
    JOBS[who] = [(who, layout, creator, out, n, kind, x) for n, (kind, x) in enumerate(items, 1)]
rows = {k: [] for k in JOBS}
queue = [j for pair in itertools.zip_longest(*JOBS.values()) for j in pair if j]
target = {"n3on": 12 + 30, "carry": 11 + 80}
DROP = set()
_drop = Path("/home/user/Ai-clipper/output/DROP_LIST.txt")
if _drop.exists():
    DROP = {line.split("\t")[0].split("/")[-1] for line in _drop.read_text().splitlines() if line.strip()}
for k, (who, layout, creator, out, n, kind, x) in enumerate(queue, 1):
    if len([r for r in rows[who]]) >= target[who]:
        continue
    name = f"{n:02d}_{who}_{kind}_{c.safe_name(x['title'], 28)}.mp4"
    final, raw = out / name, out / "_raw" / name
    if name in DROP:  # reviewed earlier: no gameplay / blurry / duplicate
        continue
    if not final.exists():
        try:
            c.fetch(x["source"], raw, 60, x.get("start"), x.get("end"), None, 0 if "start" in x else x["duration"])
            if kind == "stream" and layout == "panel" and find_streamer_face(raw) is None:
                raw.unlink(missing_ok=True)  # no webcam visible: broken / blurred stretch of the stream
                print(f"skip [{k}/{len(queue)}] {who}/{name}: no webcam found", flush=True)
                continue
            if kind == "stream" and is_camera_only(raw):
                raw.unlink(missing_ok=True)
                print(f"skip [{k}/{len(queue)}] {who}/{name}: camera only, no gameplay", flush=True)
                continue
            info = render_short(raw, final, layout, creator, 2160, 3840)
            raw.unlink(missing_ok=True)
            print(f"ok [{k}/{len(queue)}] {who}/{name} hook={info['hook']!r} fx={info['transition']}", flush=True)
        except Exception as e:
            final.unlink(missing_ok=True)
            print(f"FAIL [{k}/{len(queue)}] {who}/{name}: {str(e)[-300:]}", flush=True); continue
    rows[who].append([n, name, kind, x["views"], x["title"], x["page"]])
    with open(out / "clips.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["n", "file", "source", "views_or_hype", "title", "original"]); w.writerows(rows[who])
print("DONE", sum(map(len, rows.values())), "of", len(queue), flush=True)
