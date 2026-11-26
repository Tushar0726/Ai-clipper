"""Collect the finished shorts into output/FINAL/<creator>/ with a title,
description and hashtags for every clip (one .txt per video + metadata.csv).

Videos are hard-linked (no extra disk space). Clips listed in
output/DROP_LIST.txt (no gameplay, blurry, duplicates) are left out.
Safe to run again: it rebuilds FINAL from scratch.
"""
import csv
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shorts import HOOKS  # noqa: E402

OUT = ROOT / "output"
FINAL = OUT / "FINAL"

CREATORS = {
    "carry": {
        "name": "CarryMinati", "src": "carry_shorts", "hook_key": "carryminati",
        "credit": "Credit: CarryMinati (live on Kick: kick.com/carryminati)",
        "blurb": "CarryMinati ka GTA 6 stream ka sabse pagal moment! Pura reaction dekho end tak.",
        "tags": ["#CarryMinati", "#GTA6", "#GTAVI", "#CarryIsLive", "#GTA6Gameplay", "#ViceCity",
                 "#GTA6India", "#CarryMinatiLive", "#IndianGamer", "#HindiGaming", "#Shorts", "#Reels",
                 "#GamingShorts", "#Trending"],
    },
    "n3on": {
        "name": "N3on", "src": "n3on_shorts", "hook_key": "n3on",
        "credit": "Credit: N3on (live on Kick: kick.com/n3on)",
        "blurb": "N3on playing GTA 6 live and losing it. Watch till the end!",
        "tags": ["#N3on", "#GTA6", "#GTAVI", "#Kick", "#KickStreamer", "#GTA6Gameplay", "#ViceCity",
                 "#GTA6Funny", "#StreamerMoments", "#Shorts", "#Reels", "#GamingShorts", "#Trending",
                 "#GTA6Clips"],
    },
}


def hook_for(creator_key, clip_name):
    """Same deterministic hook the renderer burned into the video."""
    pool = HOOKS.get(creator_key, HOOKS["_"])
    return pool[int(hashlib.md5(clip_name.encode()).hexdigest(), 16) % len(pool)]


def title_case(s):
    fixed = {"GTA": "GTA", "N3ON": "N3on", "VS": "vs", "N3ON'S": "N3on's"}
    return " ".join(fixed.get(w, w.capitalize()) for w in s.split())


def main():
    drop = set()
    dl = OUT / "DROP_LIST.txt"
    if dl.exists():
        drop = {l.split("\t")[0].split("/")[-1] for l in dl.read_text().splitlines() if l.strip()}
    if FINAL.exists():
        shutil.rmtree(FINAL)
    totals = {}
    for key, c in CREATORS.items():
        src_dir = OUT / c["src"]
        dst_dir = FINAL / key
        dst_dir.mkdir(parents=True, exist_ok=True)
        originals = {}
        if (src_dir / "clips.csv").exists():
            with open(src_dir / "clips.csv", encoding="utf-8") as f:
                originals = {r["file"]: r.get("original", "") for r in csv.DictReader(f)}
        rows, n = [], 0
        for mp4 in sorted(src_dir.glob("*.mp4")):
            if mp4.name in drop:
                continue
            n += 1
            hook = hook_for(c["hook_key"], mp4.name)
            title = f"{title_case(hook.strip('?'))}{'?' if hook.endswith('?') else ''} | {c['name']} GTA 6 #Shorts"
            tags = " ".join(c["tags"])
            desc = (f"{c['blurb']}\n\n{c['credit']}\n"
                    + (f"Original clip: {originals[mp4.name]}\n" if originals.get(mp4.name) else "")
                    + f"\n{tags}")
            name = f"{key}_{n:03d}.mp4"
            dst = dst_dir / name
            try:
                dst.hardlink_to(mp4)
            except OSError:
                shutil.copy2(mp4, dst)
            (dst_dir / f"{key}_{n:03d}.txt").write_text(
                f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n\nHASHTAGS:\n{tags}\n", encoding="utf-8")
            rows.append([name, title, desc.replace("\n", " / "), tags, originals.get(mp4.name, ""), mp4.name])
        with open(dst_dir / "metadata.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "title", "description", "hashtags", "original_clip", "source_file"])
            w.writerows(rows)
        totals[key] = n
    print("FINAL:", totals, "->", FINAL)


if __name__ == "__main__":
    main()
