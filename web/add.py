"""Add one uploaded clip to a download page's clips.json.

usage: RUN=<run folder> PAGE_DIR=<page folder> [CLIPDIR=clips_4k] python3 web/add.py N thumb_id part_id...

Reads title / description / hashtags / score from the clip's .txt (written by pro_render.py),
the ids are the asset ids returned by the Artifact asset upload (thumb first, then parts in order).
"""
import glob, json, os, re, subprocess, sys

n = int(sys.argv[1]); ids = sys.argv[2:]
run = os.path.expanduser(os.environ["RUN"])
page = os.path.expanduser(os.environ["PAGE_DIR"])
f = glob.glob(os.path.join(run, os.environ.get("CLIPDIR", "clips_4k"), f"clip_{n:02d}_*.mp4"))[0]
t = open(f[:-4] + ".txt").read()
sec = lambda k: re.search(k + r":\n(.*?)\n\n", t, re.S).group(1).strip()
score = float(re.search(r"Score: ([\d.]+)", t).group(1))
dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]))
title = sec("TITLE")
slug = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"[^\x00-\x7f]", "", title)).strip("_")[:50]
p = os.path.join(page, "clips.json")
d = [c for c in (json.load(open(p)) if os.path.exists(p) else []) if c["rank"] != n]
d.append({"rank": n, "title": title, "description": sec("DESCRIPTION"), "hashtags": sec("HASHTAGS"),
          "length": f"{round(dur)} sec", "sizeMB": os.path.getsize(f) // 1000000, "score": score,
          "filename": f"{n:02d}_{slug}_4K.mp4", "thumb": "/_blob/" + ids[0], "parts": ["/_blob/" + i for i in ids[1:]]})
d.sort(key=lambda c: c["rank"])
json.dump(d, open(p, "w"), ensure_ascii=False)
print(len(d), "clips on page; added", n, title)
