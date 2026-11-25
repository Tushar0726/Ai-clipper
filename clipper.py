#!/usr/bin/env python3
"""Ai-clipper: pull the most-viewed stream clips from Kick / Twitch and
turn them into ready-to-upload 9:16 Shorts / Reels.

Examples
  # top GTA 6 clips from CarryMinati's Kick channel
  python clipper.py kick-channel carryminati --game "Grand Theft Auto VI" --top 20

  # top GTA 6 clips across ALL Kick streamers this week
  python clipper.py kick-category grand-theft-auto-vi --time week --top 30

  # best moments of a long YouTube stream (run this on YOUR PC)
  python clipper.py youtube "https://www.youtube.com/live/qSyo5d-dVzA" --top 25

  # hype moments from a Kick channel's full past streams (100+ clips)
  python clipper.py kick-vods carryminati --game "Grand Theft Auto VI" --top 80

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
        "stream": str(c.get("livestream_id") or ""),
        "mature": bool(c.get("is_mature")),
        "thumb": c.get("thumbnail_url") or "",
        "created_ts": c.get("created_at") or "",
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


def _ytdlp(cookies):
    cmd = ["yt-dlp"]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    return cmd


def _loudness_per_second(path):
    """RMS level (dB) for every second of audio, via ffmpeg astats."""
    af = ("aresample=8000,asetnsamples=n=8000:p=0,"
          "astats=metadata=1:reset=1,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
    out = subprocess.run(["ffmpeg", "-nostats", "-loglevel", "error", "-i", str(path),
                          "-vn", "-ac", "1", "-af", af, "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stdout
    levels = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1]
            levels.append(-90.0 if v in ("-inf", "inf", "nan") else max(float(v), -90.0))
    return levels


def _pick_peaks(levels, offset, n, spacing):
    """Loudest moments (5s smoothed), at least `spacing` seconds apart."""
    k = 5
    sm = [sum(levels[max(0, i - k):i + k + 1]) / len(levels[max(0, i - k):i + k + 1])
          for i in range(len(levels))]
    if not sm:
        return []
    mean = sum(sm) / len(sm)
    order = sorted(range(len(sm)), key=lambda i: sm[i], reverse=True)
    picked = []
    for i in order:
        if all(abs(i - j) >= spacing for j, _ in picked):
            picked.append((i, sm[i] - mean))
        if len(picked) >= n:
            break
    return [(offset + i, score) for i, score in picked]


def kick_vods(slug, game, limit, clip_len, max_vods=30, workers=3):
    """Find hype moments inside a Kick channel's past streams (VODs).

    Audio is analysed from the tiny 160p rendition (cheap); clips are cut
    from the 1080p rendition. Moments that viewers already clipped are
    skipped, so this complements `kick-channel`.
    """
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime
    vods = _kick_get(f"https://kick.com/api/v2/channels/{slug}/videos")
    vods = vods if isinstance(vods, list) else vods.get("data", [])
    if game:
        vods = [v for v in vods if any(game.lower() in (x.get("name") or "").lower()
                                       for x in v.get("categories") or [])]
    vods = vods[:max_vods]
    if not vods:
        return []

    def ts(s):
        return datetime.fromisoformat(s.replace("Z", "")[:19]).timestamp()

    # end-times (seconds into each VOD) of clips viewers already made
    taken = {}
    for c in _kick_paged(f"https://kick.com/api/v2/channels/{slug}/clips", "month", 300):
        taken.setdefault(str(c.get("livestream_id")), []).append(ts(c["created_at"]))

    per_vod = max(2, -(-limit // len(vods)) + 2)

    def analyse(v):
        master = v["source"]
        start_ts = ts(v["start_time"])
        print(f"  analysing {v.get('session_title', '')[:40]} ({v['duration'] / 3.6e6:.1f}h)", flush=True)
        try:
            levels = _loudness_per_second(master.replace("master.m3u8", "160p30/playlist.m3u8"))
        except subprocess.CalledProcessError:
            return []
        done = [t - start_ts for t in taken.get(str(v.get("id")), [])]
        peaks = [(t, s) for t, s in _pick_peaks(levels, 0, per_vod * 3, clip_len)
                 if all(abs(t - d) > clip_len * 1.5 for d in done)][:per_vod]
        hd = master.replace("master.m3u8", "1080p60/playlist.m3u8")
        out = []
        for t, score in peaks:
            st = max(0, t - int(clip_len * 0.6))
            out.append({
                "creator": slug,
                "title": f"{(v.get('session_title') or '')[:28]} @{st // 3600}h{st % 3600 // 60:02d}m{st % 60:02d}s",
                "views": int(score * 100), "duration": clip_len, "game": game,
                "created": v["start_time"][:10], "source": hd, "start": st, "end": st + clip_len,
                "page": f"https://kick.com/{slug}/videos/{(v.get('video') or {}).get('uuid', '')}?t={st}",
            })
        return out

    with ThreadPoolExecutor(workers) as ex:
        clips = [c for group in ex.map(analyse, vods) for c in group]
    clips.sort(key=lambda c: c["views"], reverse=True)
    return clips[:limit]


def youtube_stream(url, limit, clip_len, cookies, workdir):
    """Find the best moments of a long YouTube stream/VOD.

    1. Use YouTube's 'Most replayed' heatmap to find the hottest regions.
    2. Download ONLY the audio of those regions and find the loudest moments
       (screams / hype) inside them.
    Falls back to scanning the whole audio if the video has no heatmap.
    """
    info = json.loads(subprocess.run(_ytdlp(cookies) + ["-J", "--skip-download", url],
                                     capture_output=True, text=True, check=True).stdout)
    duration = info.get("duration") or 0
    title, channel = info.get("title", ""), info.get("channel") or info.get("uploader") or "youtube"
    heat = info.get("heatmap") or []
    if heat:
        n_regions = min(len(heat), max(3, limit))
        regions = sorted(heat, key=lambda h: h["value"], reverse=True)[:n_regions]
        regions = [(int(h["start_time"]), int(h["end_time"]) + 1, h["value"]) for h in regions]
        print(f"Using 'Most replayed' heatmap: {len(regions)} hot regions")
    else:
        regions = [(0, int(duration), 1.0)]
        print("No heatmap on this video: scanning the whole audio (slower)")

    per_region = max(1, -(-limit // len(regions)) + 1)
    cands = []
    workdir.mkdir(parents=True, exist_ok=True)
    for idx, (s, e, value) in enumerate(regions, 1):
        audio = workdir / f"audio_{idx}.m4a"
        print(f"  audio region {idx}/{len(regions)}: {s // 3600}h{s % 3600 // 60:02d}m - {e // 3600}h{e % 3600 // 60:02d}m")
        subprocess.run(_ytdlp(cookies) + ["-q", "-f", "worstaudio/bestaudio", "--force-overwrites",
                                          "--download-sections", f"*{s}-{e}", "-o", str(audio), url],
                       check=True)
        for t, score in _pick_peaks(_loudness_per_second(audio), s, per_region, clip_len):
            cands.append((t, score * (0.5 + value)))
        audio.unlink(missing_ok=True)

    cands.sort(key=lambda c: c[1], reverse=True)
    chosen = []
    for t, score in cands:
        if all(abs(t - u) >= clip_len for u, _ in chosen):
            chosen.append((t, score))
        if len(chosen) >= limit:
            break

    clips = []
    for t, score in chosen:
        start = max(0, t - int(clip_len * 0.6))  # keep the build-up before the peak
        end = min(int(duration) or start + clip_len, start + clip_len)
        clips.append({
            "creator": safe_name(channel, 20),
            "title": f"{title[:30]} @{start // 3600}h{start % 3600 // 60:02d}m{start % 60:02d}s",
            "views": int(score * 100),  # hype score, used for ranking
            "duration": end - start,
            "created": info.get("upload_date") or "",
            "game": "",
            "source": url,
            "start": start,
            "end": end,
            "page": f"{info.get('webpage_url', url)}&t={start}s",
        })
    return clips


NSFW_WORDS = ("strip", "nude", "naked", "lap dance", "lapdance", "twerk", "boob", "sex",
              "porn", "nsfw", "18+", "çıplak", "çiplak", "ciplak", "cıplak", "gacie", "bikini", "hooker")


def is_nsfw(c):
    t = c["title"].lower()
    return c.get("mature") or any(w in t for w in NSFW_WORDS)


def drop_duplicates(clips):
    """Several viewers often clip the same moment. Keep only the most-viewed
    clip when two clips come from the same stream and were made within
    each other's duration."""
    from datetime import datetime
    def ts(c):
        try:
            return datetime.fromisoformat(c["created_ts"][:19]).timestamp()
        except (KeyError, ValueError):
            return None
    kept = []
    for c in clips:  # already sorted by views, best first
        t = ts(c)
        dup = t is not None and c.get("stream") and any(
            k.get("stream") == c["stream"] and ts(k) is not None
            and abs(ts(k) - t) < max(k["duration"], c["duration"], 30) for k in kept)
        if not dup:
            kept.append(c)
    return kept


# ---------------------------------------------------------------- video
def safe_name(s, n=40):
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE).strip().replace(" ", "_")
    return (s or "clip")[:n]


def fetch(src, dst, max_seconds, start=None, end=None, cookies=None, duration=0):
    """Download a clip (m3u8 or page URL) to dst. Clips longer than
    max_seconds keep their LAST max_seconds (where the moment usually is)."""
    tail_from = max(0, int(duration) - max_seconds) if max_seconds and duration else 0
    if start is None and tail_from and not src.endswith(".m3u8"):
        start, end = tail_from, int(duration)
    if start is not None and src.endswith(".m3u8"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-user_agent", UA, "-ss", str(start),
                        "-i", src, "-t", str(end - start), "-c", "copy", str(dst)], check=True)
        return
    if start is not None:
        subprocess.run(_ytdlp(cookies) + [
            "-q", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
            "--merge-output-format", "mp4", "--force-overwrites",
            "--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts",
            "-o", str(dst), src], check=True)
        return
    if src.endswith(".m3u8"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-user_agent", UA]
        if tail_from:  # the hype moment is usually at the END of a clip
            cmd += ["-ss", str(tail_from)]
        cmd += ["-i", src]
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
    p.add_argument("source", choices=["kick-channel", "kick-vods", "kick-category", "twitch-channel", "youtube"])
    p.add_argument("name", help="channel slug / category slug / twitch login / youtube URL")
    p.add_argument("--clip-len", type=int, default=35, help="youtube: seconds per clip")
    p.add_argument("--cookies-from-browser", default="",
                   help="youtube: e.g. chrome / firefox / edge, if YouTube asks to sign in")
    p.add_argument("--top", type=int, default=20, help="how many clips to make")
    p.add_argument("--time", default="month", help="kick: day | week | month | all")
    p.add_argument("--range", default="7d", help="twitch: 24hr | 7d | 30d | all")
    p.add_argument("--game", default="", help="keep only clips whose category contains this (kick)")
    p.add_argument("--min-views", type=int, default=0)
    p.add_argument("--max-seconds", type=int, default=60, help="trim longer clips (0 = no trim)")
    p.add_argument("--style", choices=["blur", "crop"], default="blur")
    p.add_argument("--out", default="output")
    p.add_argument("--safe", action="store_true",
                   help="skip clips marked mature or with strip-club / nudity titles")
    p.add_argument("--exclude-creators", nargs="*", default=[])
    p.add_argument("--skip-existing", nargs="*", default=[],
                   help="clips.csv file(s) from earlier runs: skip clips already made")
    p.add_argument("--list-only", action="store_true", help="just print the ranking")
    a = p.parse_args()

    for tool in ("ffmpeg",) + (("yt-dlp",) if a.source in ("twitch-channel", "youtube") else ()):
        if not shutil.which(tool):
            sys.exit(f"'{tool}' is not installed / not on PATH")

    cookies = a.cookies_from_browser or None
    out_name = safe_name(a.name)
    if a.source == "youtube":
        vid = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([\w-]{11})", a.name)
        out_name = vid.group(1) if vid else safe_name(a.name)
        clips = youtube_stream(a.name, a.top, a.clip_len, cookies, Path(a.out) / out_name / "_raw")
    elif a.source == "kick-vods":
        clips = kick_vods(a.name, a.game, a.top, a.clip_len)
        a.game = ""  # already filtered by stream category
    elif a.source == "kick-channel":
        clips = kick_channel(a.name, a.time, a.top)
    elif a.source == "kick-category":
        clips = kick_category(a.name, a.time, a.top)
    else:
        clips = twitch_channel(a.name, a.range, a.top)

    if a.game:
        clips = [c for c in clips if a.game.lower() in c["game"].lower()]
    clips = [c for c in clips if c["views"] >= a.min_views]
    clips.sort(key=lambda c: c["views"], reverse=True)
    before = len(clips)
    clips = drop_duplicates(clips)
    if before != len(clips):
        print(f"Removed {before - len(clips)} duplicate clips of the same moment")
    if a.safe:
        n = len(clips)
        clips = [c for c in clips if not is_nsfw(c)]
        print(f"--safe: removed {n - len(clips)} mature / strip-club clips")
    if a.exclude_creators:
        ex = {x.lower() for x in a.exclude_creators}
        clips = [c for c in clips if c["creator"].lower() not in ex]
    if a.skip_existing:
        seen = set()
        for csv_path in a.skip_existing:
            with open(csv_path, encoding="utf-8") as f:
                seen |= {row["original"] for row in csv.DictReader(f)}
        clips = [c for c in clips if c["page"] not in seen]
    clips = clips[: a.top]
    if not clips:
        sys.exit("No clips found for that source / filter.")

    for i, c in enumerate(clips, 1):
        label = "hype" if a.source in ("youtube", "kick-vods") else "views"
        print(f"{i:>3}. {c['views']:>8,} {label} | {c['creator']:<15} | {c['duration']:>4}s | {c['title'][:50]}")
    if a.list_only:
        return

    out = Path(a.out) / out_name
    tmp = out / "_raw"
    tmp.mkdir(parents=True, exist_ok=True)
    index = out / "clips.csv"
    with index.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "file", "creator", "views", "title", "created", "original"])
        for i, c in enumerate(clips, 1):
            tag = "" if a.source in ("youtube", "kick-vods") else f"_{c['views']}v"
            name = f"{i:02d}_{c['creator']}{tag}_{safe_name(c['title'])}.mp4"
            raw, final = tmp / name, out / name
            try:
                print(f"[{i}/{len(clips)}] {name}")
                fetch(c["source"], raw, a.max_seconds, c.get("start"), c.get("end"), cookies,
                      0 if "start" in c else c["duration"])
                to_vertical(raw, final, a.style)
                raw.unlink(missing_ok=True)
                w.writerow([i, name, c["creator"], c["views"], c["title"], c["created"], c["page"]])
            except subprocess.CalledProcessError as e:
                print(f"   failed: {e}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nDone -> {out}  (index: {index})")


if __name__ == "__main__":
    main()
