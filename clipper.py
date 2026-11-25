#!/usr/bin/env python3
"""Ai-clipper: pull the most-viewed stream clips from Kick / Twitch and
turn them into ready-to-upload 9:16 Shorts / Reels.

Examples
  # top GTA 6 clips from CarryMinati's Kick channel
  python clipper.py kick-channel carryminati --game "Grand Theft Auto VI" --top 20

  # top GTA 6 clips across ALL Kick streamers this week
  python clipper.py kick-category grand-theft-auto-vi --time week --top 30

  # top clips from a Twitch channel (last 7 days)
  python clipper.py twitch-channel kaicenat --range 7d --top 10
"""
import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


# ---------------------------------------------------------------- sources
def _kick_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _kick_paged(base, time_range, limit):
    clips, cursor = [], None
    while len(clips) < limit:
        q = {"sort": "view", "time": time_range}
        if cursor:
            q["cursor"] = cursor
        data = _kick_get(f"{base}?{urllib.parse.urlencode(q)}")
        page = data.get("clips", [])
        if not page:
            break
        clips += page
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return clips


def _kick_normalize(c):
    return {
        "creator": (c.get("channel") or {}).get("slug") or str(c.get("channel_id")),
        "title": c.get("title") or "",
        "views": c.get("views") or c.get("view_count") or 0,
        "duration": c.get("duration") or 0,
        "created": (c.get("created_at") or "")[:10],
        "game": (c.get("category") or {}).get("name", ""),
        "source": c["clip_url"],
        "page": f"https://kick.com/{(c.get('channel') or {}).get('slug', '')}/clips/{c['id']}",
    }


def kick_channel(slug, time_range, limit):
    raw = _kick_paged(f"https://kick.com/api/v2/channels/{slug}/clips", time_range, limit * 3)
    return [_kick_normalize(c) for c in raw]


def kick_category(slug, time_range, limit):
    raw = _kick_paged(f"https://kick.com/api/v2/categories/{slug}/clips", time_range, limit * 3)
    return [_kick_normalize(c) for c in raw]


def twitch_channel(login, rng, limit):
    url = f"https://www.twitch.tv/{login}/clips?filter=clips&range={rng}"
    out = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--playlist-end", str(limit * 3), "-J", url],
        capture_output=True, text=True, check=True,
    ).stdout
    entries = json.loads(out).get("entries") or []
    return [{
        "creator": login,
        "title": e.get("title") or "",
        "views": e.get("view_count") or 0,
        "duration": e.get("duration") or 0,
        "created": e.get("upload_date") or "",
        "game": "",
        "source": e.get("url") or e.get("webpage_url"),
        "page": e.get("url") or e.get("webpage_url"),
    } for e in entries]


# ---------------------------------------------------------------- video
def safe_name(s, n=40):
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "_")
    return (s or "clip")[:n]


def fetch(src, dst, max_seconds):
    """Download a clip (m3u8 or page URL) to dst."""
    if src.endswith(".m3u8"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-user_agent", UA, "-i", src]
        if max_seconds:
            cmd += ["-t", str(max_seconds)]
        cmd += ["-c", "copy", str(dst)]
    else:
        cmd = ["yt-dlp", "-q", "-f", "best[ext=mp4]/best", "-o", str(dst), "--force-overwrites", src]
        if max_seconds:
            cmd += ["--download-sections", f"*0-{max_seconds}"]
    subprocess.run(cmd, check=True)


def to_vertical(src, dst, style):
    """1080x1920. 'blur': full frame centered over a blurred zoomed copy.
    'crop': center crop (fills screen, loses the sides)."""
    if style == "crop":
        vf = "scale=-2:1920,crop=1080:1920"
    else:
        vf = ("split[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5,eq=brightness=-0.08[bg];"
              "[b]scale=1080:-2[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-filter_complex", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst),
    ], check=True)


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", choices=["kick-channel", "kick-category", "twitch-channel"])
    p.add_argument("name", help="channel slug / category slug / twitch login")
    p.add_argument("--top", type=int, default=20, help="how many clips to make")
    p.add_argument("--time", default="month", help="kick: day | week | month | all")
    p.add_argument("--range", default="7d", help="twitch: 24hr | 7d | 30d | all")
    p.add_argument("--game", default="", help="keep only clips whose category contains this (kick)")
    p.add_argument("--min-views", type=int, default=0)
    p.add_argument("--max-seconds", type=int, default=60, help="trim longer clips (0 = no trim)")
    p.add_argument("--style", choices=["blur", "crop"], default="blur")
    p.add_argument("--out", default="output")
    p.add_argument("--list-only", action="store_true", help="just print the ranking")
    a = p.parse_args()

    for tool in ("ffmpeg",) + (("yt-dlp",) if a.source.startswith("twitch") else ()):
        if not shutil.which(tool):
            sys.exit(f"'{tool}' is not installed / not on PATH")

    if a.source == "kick-channel":
        clips = kick_channel(a.name, a.time, a.top)
    elif a.source == "kick-category":
        clips = kick_category(a.name, a.time, a.top)
    else:
        clips = twitch_channel(a.name, a.range, a.top)

    if a.game:
        clips = [c for c in clips if a.game.lower() in c["game"].lower()]
    clips = [c for c in clips if c["views"] >= a.min_views]
    clips.sort(key=lambda c: c["views"], reverse=True)
    clips = clips[: a.top]
    if not clips:
        sys.exit("No clips found for that source / filter.")

    for i, c in enumerate(clips, 1):
        print(f"{i:>3}. {c['views']:>8,} views | {c['creator']:<15} | {c['duration']:>4}s | {c['title'][:50]}")
    if a.list_only:
        return

    out = Path(a.out) / safe_name(a.name)
    tmp = out / "_raw"
    tmp.mkdir(parents=True, exist_ok=True)
    index = out / "clips.csv"
    with index.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "file", "creator", "views", "title", "created", "original"])
        for i, c in enumerate(clips, 1):
            name = f"{i:02d}_{c['creator']}_{c['views']}v_{safe_name(c['title'])}.mp4"
            raw, final = tmp / name, out / name
            try:
                print(f"[{i}/{len(clips)}] {name}")
                fetch(c["source"], raw, a.max_seconds)
                to_vertical(raw, final, a.style)
                raw.unlink(missing_ok=True)
                w.writerow([i, name, c["creator"], c["views"], c["title"], c["created"], c["page"]])
            except subprocess.CalledProcessError as e:
                print(f"   failed: {e}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nDone -> {out}  (index: {index})")


if __name__ == "__main__":
    main()
