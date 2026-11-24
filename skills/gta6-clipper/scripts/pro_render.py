#!/usr/bin/env python3
"""Pro render for gta6-clipper picks: 2160x3840 (4K vertical) output, facecam top / gameplay bottom,
accent seam, hook card with emoji, word-by-word pop captions with highlighted active word and a few
emojis, punch-in zooms on the loudest moments, progress bar, loudness-normalised audio.

Usage: python pro_render.py <run> [--top N] [--min-score 7] [--only 1,3] [--keep]
Pick extras (optional, in picks/*.json): "hook_emoji": "😱", "emojis": [["word", "🔥"], ...],
"layout": "gameplay" | "cam".
"""
import argparse, json, re, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gta6clip as g  # noqa: E402

OW, OH = 2160, 3840          # output size
FPS = 30
ACCENT = (83, 252, 24)       # Kick green
HILITE = (255, 225, 0)       # active word
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
TEXT_FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

KEYWORD_EMOJI = [
    (r"\b(lmao|lol|haha+|funny|joke)\b", "😂"), (r"\b(crazy|insane|nuts|wild)\b", "🤯"),
    (r"\b(oh my god|omg|no way|what the)\b", "😱"), (r"\b(bro|dead|died|dying|kill(ed)?)\b", "💀"),
    (r"\b(money|cash|rich|dollars?|bands)\b", "💰"), (r"\b(car|drive|driving|lambo|whip)\b", "🚗"),
    (r"\b(cops?|police|wanted|stars)\b", "🚔"), (r"\b(gun|shoot|shot|shooting)\b", "🔫"),
    (r"\b(fire|hard|goated|best)\b", "🔥"), (r"\b(love|beautiful|pretty)\b", "😍"),
    (r"\b(run|running|chase)\b", "🏃"), (r"\b(what|huh|wait)\b", "😳"), (r"\b(map|city|vice city)\b", "🌴"),
]


def fnt(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(TEXT_FONT, size)
    except OSError:
        return ImageFont.load_default()


_emoji_cache = {}


def emoji_img(ch, size):
    from PIL import Image, ImageDraw, ImageFont
    key = (ch, size)
    if key not in _emoji_cache:
        f = ImageFont.truetype(EMOJI_FONT, 109)
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((80, 80), ch, font=f, embedded_color=True, anchor="mm")
        bb = im.getbbox() or (0, 0, 160, 160)
        im = im.crop(bb)
        r = size / max(im.size)
        _emoji_cache[key] = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    return _emoji_cache[key]


def clean_words(words):
    """Drop Whisper sound tags like (UPBEAT MUSIC) / [Music] / *laughs* even when split over words."""
    out, depth = [], 0
    for w in words:
        t = w["t"]
        opens = len(re.findall(r"[\(\[]", t)) + (1 if t.startswith("*") else 0)
        closes = len(re.findall(r"[\)\]]", t)) + (1 if t.endswith("*") and len(t) > 1 else 0)
        if depth > 0 or opens:
            depth = max(0, depth + opens - closes)
            continue
        t = re.sub(r"^[\-–—]+|[\-–—]+$", "", t).strip()
        if t:
            out.append({**w, "t": t})
    return out


def group_words(words):
    words = clean_words(words)
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or w["s"] - cur[-1]["e"] > 0.4 or re.search(r"[.?!,]$", cur[-1]["t"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def choose_emojis(groups, pick):
    """Few emojis: pick-provided ones first, then keyword matches, >= 4 s apart, max 6."""
    custom = [(w.lower(), e) for w, e in (pick.get("emojis") or [])]
    out, last = {}, -99
    for gi, gr in enumerate(groups):
        text = " ".join(w["t"] for w in gr).lower()
        e = next((e for w, e in custom if w in text), None)
        if e is None:
            e = next((e for rx, e in KEYWORD_EMOJI if re.search(rx, text)), None)
        if e and gr[0]["s"] - last >= 4 and len(out) < 6:
            out[gi] = e
            last = gr[0]["s"]
    return out


def caption_track(words, pick, seam_y, cap_y, dur, outdir):
    from PIL import Image, ImageDraw
    outdir.mkdir(exist_ok=True)
    hook = (pick.get("hook") or pick.get("title") or "").upper()
    hook_emoji = pick.get("hook_emoji")
    hf = fnt(100)

    def base():
        im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if hook:
            lines = g.wrap(d, hook, hf, 1800)[:3]
            lh = 122
            bh = lh * len(lines) + 70
            top = seam_y - bh // 2
            bw = max(d.textlength(l, font=hf) for l in lines) + 120
            # shadow + card + accent underline
            d.rounded_rectangle([OW / 2 - bw / 2 + 12, top + 14, OW / 2 + bw / 2 + 12, top + bh + 14], 40,
                                fill=(0, 0, 0, 120))
            d.rounded_rectangle([OW / 2 - bw / 2, top, OW / 2 + bw / 2, top + bh], 40, fill=(255, 255, 255, 255))
            d.rounded_rectangle([OW / 2 - bw / 2 + 40, top + bh - 16, OW / 2 + bw / 2 - 40, top + bh - 6], 5,
                                fill=ACCENT + (255,))
            for i, l in enumerate(lines):
                d.text((OW / 2, top + 32 + i * lh + lh / 2), l, font=hf, fill=(10, 10, 10), anchor="mm")
            if hook_emoji:
                e = emoji_img(hook_emoji, 170)
                im.alpha_composite(e, (int(OW / 2 + bw / 2 - e.width * 0.55), int(top - e.height * 0.55)))
        return im

    groups = group_words(words)
    emo = choose_emojis(groups, pick)
    states = []  # (t0, t1, gi, active, scale)
    for gi, gr in enumerate(groups):
        for i, w in enumerate(gr):
            t1 = gr[i + 1]["s"] if i + 1 < len(gr) else w["e"] + 0.15
            if i == 0:  # pop-in: 2 quick frames smaller, then full size
                states.append((w["s"], w["s"] + 0.07, gi, i, 0.82))
                states.append((w["s"] + 0.07, max(t1, w["s"] + 0.14), gi, i, 1.0))
            else:
                states.append((w["s"], max(t1, w["s"] + 0.08), gi, i, 1.0))

    blank = outdir / "blank.png"
    base_im = base()
    base_im.save(blank)
    HOOK_T = 3.5  # hook card only for the first seconds, then the gameplay is clean
    plain_im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    blank_plain = outdir / "blank_plain.png"
    plain_im.save(blank_plain)
    timeline, t, k = [], 0.0, 0

    def add_blank(a, b):
        if a < HOOK_T and min(b, HOOK_T) - a > 0.001:
            timeline.append((blank, min(b, HOOK_T) - a))
        if b > HOOK_T and b - max(a, HOOK_T) > 0.001:
            timeline.append((blank_plain, b - max(a, HOOK_T)))
    for t0, t1, gi, ai, sc in states:
        if t0 < t:
            t0 = t
        if t1 - t0 < 0.03:
            continue
        if t0 > t + 0.02:
            add_blank(t, t0)
        im = (base_im if t0 < HOOK_T else plain_im).copy()
        d = ImageDraw.Draw(im)
        text = [w["t"].upper() for w in groups[gi]]
        size = int(140 * sc)
        cf = fnt(size)
        widths = [d.textlength(x, font=cf) for x in text]
        space = d.textlength(" ", font=cf)
        total = sum(widths) + space * (len(text) - 1)
        if total > 1700:
            size = int(size * 1700 / total)
            cf = fnt(size)
            widths = [d.textlength(x, font=cf) for x in text]
            space = d.textlength(" ", font=cf)
            total = sum(widths) + space * (len(text) - 1)
        x = OW / 2 - total / 2
        for j, (word, wd) in enumerate(zip(text, widths)):
            # soft shadow then stroked text
            d.text((x + 8, cap_y + 10), word, font=cf, anchor="lm", fill=(0, 0, 0, 150))
            d.text((x, cap_y), word, font=cf, anchor="lm", fill=HILITE if j == ai else (255, 255, 255),
                   stroke_width=max(6, size // 12), stroke_fill=(0, 0, 0))
            x += wd + space
        if gi in emo:
            e = emoji_img(emo[gi], int(170 * sc))
            im.alpha_composite(e, (int(min(OW - e.width - 20, OW / 2 + total / 2 + 24)), int(cap_y - e.height / 2)))
        p = outdir / f"c{k:05d}.png"
        im.save(p, compress_level=1)
        k += 1
        timeline.append((p, t1 - t0))
        t = t1
    if t < dur:
        add_blank(t, dur)
    lst = outdir / "list.ffconcat"
    body = ["ffconcat version 1.0"]
    for p, d_ in timeline:
        body += [f"file '{p.name}'", f"duration {d_:.3f}"]
    body.append(f"file '{timeline[-1][0].name}'")
    lst.write_text("\n".join(body) + "\n")
    return lst, emo


def loud_peaks(src, ss, dur, work, n=3):
    """Times (clip-relative) of the loudest moments, for punch-in zooms."""
    import numpy as np
    raw = work / "pk.raw"
    g.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
           "-ac", "1", "-ar", "8000", "-f", "s16le", str(raw)])
    a = np.frombuffer(raw.read_bytes(), dtype=np.int16).astype(np.float32)
    raw.unlink(missing_ok=True)
    win = 4000  # 0.5 s
    if len(a) < win * 4:
        return []
    rms = np.sqrt(np.array([np.mean(a[i:i + win] ** 2) for i in range(0, len(a) - win, win)]) + 1e-6)
    db = 20 * np.log10(rms)
    med = np.median(db)
    peaks = []
    for i in np.argsort(-db):
        tt = i * 0.5
        if db[i] < med + 6 or tt < 1.5 or tt > dur - 2:
            continue
        if all(abs(tt - p) > 5 for p in peaks):
            peaks.append(tt)
        if len(peaks) >= n:
            break
    return sorted(peaks)


def loud_mask(src, ss, dur, work, step=0.1):
    """dB per 0.1 s window and its median, for deciding which silent-looking gaps are actually loud."""
    import numpy as np
    raw = work / "lm.raw"
    g.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
           "-ac", "1", "-ar", "8000", "-f", "s16le", str(raw)])
    a = np.frombuffer(raw.read_bytes(), dtype=np.int16).astype(np.float32)
    raw.unlink(missing_ok=True)
    win = int(8000 * step)
    n = max(1, len(a) // win)
    db = np.array([20 * np.log10(np.sqrt(np.mean(a[i * win:(i + 1) * win] ** 2) + 1e-6)) for i in range(n)])
    return db, float(np.median(db))


def plan_cuts(words, db, med, target, win, min_len=30.0, max_len=60.0, keep_gap=0.22, max_gap=0.45):
    """Jump cuts: keep speech (+ loud non-speech like screams/gunfire), squeeze pauses longer than
    max_gap down to keep_gap. Returns frame-aligned (start, end) segments in source-clip time."""
    step = 0.1
    act = []
    for w in words:
        act.append([max(0.0, w["s"] - 0.08), w["e"] + 0.12])
    for i, v in enumerate(db):
        if v > med + 8:
            act.append([i * step, (i + 1) * step])
    act.sort()
    merged = []
    for s, e in act:
        if s > win:
            break
        e = min(e, win)
        if merged and s - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    if not merged:
        return [(0.0, min(target, max_len))]
    merged[0][0] = 0.0  # always start exactly on the hook
    half = keep_gap / 2
    segs = []
    for i, (s, e) in enumerate(merged):
        s2 = s if i == 0 else s - half
        e2 = e + half
        segs.append([max(0.0, s2), min(win, e2)])
    # accumulate until we pass the picked end (and have >= min_len), never beyond max_len
    out, total = [], 0.0
    sentence_end = {round(w["e"], 2) for w in words if re.search(r"[.?!]$", w["t"])}
    for s, e in segs:
        if total + (e - s) > max_len:
            e = s + (max_len - total)
            out.append([s, e])
            total = max_len
            break
        out.append([s, e])
        total += e - s
        if s >= target - 0.5 and total >= min_len:
            break
        if e >= target and total >= min_len:
            break
    fr = 1.0 / FPS
    snapped = []
    for s, e in out:
        s, e = round(s / fr) * fr, round(e / fr) * fr
        if e - s >= 2 * fr:
            snapped.append((round(s, 4), round(e, 4)))
    return snapped


def remap(t, segs):
    """Source-clip time -> edited time; None if t falls in a cut."""
    acc = 0.0
    for s, e in segs:
        if t < s:
            return None
        if t <= e:
            return acc + (t - s)
        acc += e - s
    return None


def zoom_expr(peaks, amt=0.14):
    """1 + bump(t) where each bump eases in over 0.12 s, holds 1.1 s, eases out over 0.35 s."""
    parts = ["0.8*max(0,1-t/0.6)"]  # opening push-in: starts zoomed and eases out in 0.6 s
    for p in peaks:
        a0, a1, b0, b1 = p - 0.12, p, p + 1.1, p + 1.45
        parts.append(f"if(between(t,{a0:.2f},{a1:.2f}),(t-{a0:.2f})/0.12,"
                     f"if(between(t,{a1:.2f},{b0:.2f}),1,if(between(t,{b0:.2f},{b1:.2f}),({b1:.2f}-t)/0.35,0)))")
    return f"(1+{amt}*({'+'.join(parts)}))"


def render(rd, info, c, n, keep):
    clips = rd / "clips_4k"
    clips.mkdir(exist_ok=True)
    work = rd / f"work4k_{n:02d}"
    work.mkdir(exist_ok=True)
    a, b = max(0, c["_s"] - 3), c["_e"] + 25  # extra tail so cut clips can still reach 30 s
    src = next((p for p in work.glob("src.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
    if not src:
        r = g.run(g.YTDLP + ["--no-playlist", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                             "--download-sections", f"*{a:.1f}-{b:.1f}", "--merge-output-format", "mp4",
                             "-o", str(work / "src.%(ext)s"), info["webpage_url"]])
        src = next((p for p in work.glob("src.*") if p.suffix in (".mp4", ".mkv", ".webm")), None)
        if not src:
            raise RuntimeError("section download failed: " + r.stderr[-300:])
    pr = json.loads(g.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height:format=duration", "-of", "json", str(src)]).stdout)
    W, H = pr["streams"][0]["width"], pr["streams"][0]["height"]
    sdur = float(pr["format"]["duration"])
    ss = min(c["_s"] - a, max(0, sdur - 5))
    target = c["_e"] - c["_s"]
    win = min(target + 24, sdur - ss)

    from overlay_box import overlay_box  # exact overlay edges; the face-based guess sometimes grabbed only the face
    ob = overlay_box(src)
    fc = {"mode": "facecam", "box": list(ob)} if ob else g.find_facecam(src, W, H)
    forced = c.get("layout")
    if forced == "gameplay" or (forced == "cam" and "face" not in fc):
        fc = {"mode": "gameplay"}
    elif forced == "cam":
        fc = {"mode": "cam", "face": fc["face"]}
    raw_words = g.clip_words(src, ss, win, work)
    db, med = loud_mask(src, ss, win, work)
    segs = plan_cuts(clean_words(raw_words), db, med, target, win)
    dur = sum(e - s for s, e in segs)
    cut_away = (segs[-1][1] - segs[0][0]) - dur
    words = []
    for w in raw_words:
        s2, e2 = remap(w["s"], segs), remap(min(w["e"], w["s"] + 3), segs)
        if s2 is None:
            continue
        words.append({**w, "s": s2, "e": e2 if e2 is not None else s2 + 0.25})
    peaks = [p for p in (remap(p, segs) for p in loud_peaks(src, ss, segs[-1][1], work)) if p is not None
             and 1.5 < p < dur - 2]
    z = zoom_expr(peaks)
    sel = "+".join(f"between(t,{s:.4f},{e - 0.0005:.4f})" for s, e in segs)
    asel = "+".join(f"between(t,{s:.4f},{e:.4f})" for s, e in segs)
    up = "flags=lanczos"
    sharpen = "unsharp=5:5:0.7:5:5:0.0"
    seam_px = 14
    if fc["mode"] == "facecam":
        # owner's layout: Neon = top 30 %, then a dark caption band (subtitles live here: not on
        # Neon's face, not on the gameplay), then the gameplay
        L, T, cw, ch = fc["box"]
        top_h = int(OH * 0.30) // 2 * 2
        band_h = 300
        bot_h = OH - top_h - band_h - 2 * seam_px
        gw, gh = H * OW / bot_h, H
        if gw > W:
            gw, gh = W, W * bot_h / OW
        gx, gy = (W - gw) / 2, (H - gh) / 2
        if L + cw + 4 + gw <= W: gx = max(gx, L + cw + 4)  # keep the facecam overlay out of the gameplay panel
        acc = f"0x{ACCENT[0]:02x}{ACCENT[1]:02x}{ACCENT[2]:02x}"
        vf = (f"[0:v]fps={FPS},split[a][b];"
              f"[a]crop={cw}:{ch}:{L}:{T},scale={OW}:-2:{up},"
              f"crop={OW}:'min(ih,{top_h})':0:'max(0,(ih-{top_h})*0.15)',scale={OW}:{top_h}:{up},{sharpen},eq=saturation=1.08[top];"
              f"[b]crop={int(gw)}:{int(gh)}:{int(gx)}:{int(gy)},"
              f"scale=w='trunc({OW}*{z}/2)*2':h='trunc({bot_h}*{z}/2)*2':eval=frame:{up},"
              f"crop={OW}:{bot_h}:(iw-{OW})/2:(ih-{bot_h})/2,{sharpen},eq=saturation=1.12:contrast=1.04[bot];"
              f"color=c={acc}:s={OW}x{seam_px}:r={FPS}[seam];color=c={acc}:s={OW}x{seam_px}:r={FPS}[seam2];"
              f"color=c=0x0b0d09:s={OW}x{band_h}:r={FPS}[band];"
              f"[top][seam][band][seam2][bot]vstack=5:shortest=1[base]")
        band_mid = top_h + seam_px + band_h // 2
        seam, cap_y = top_h + 2 * seam_px + band_h + 220, band_mid  # hook (first 3.5 s) just below the band
    elif fc["mode"] == "cam":
        fx, fy, fw, fh = fc["face"]
        cw = min(W, H * 9 / 16)
        cx = min(max(0, fx + fw / 2 - cw / 2), W - cw)
        vf = (f"[0:v]fps={FPS},crop={int(cw)}:{H}:{int(cx)}:0,"
              f"scale=w='trunc({OW}*{z}/2)*2':h='trunc({OH}*{z}/2)*2':eval=frame:{up},"
              f"crop={OW}:{OH}:(iw-{OW})/2:(ih-{OH})/2,{sharpen}[base]")
        seam, cap_y = 600, 2760
    else:
        vf = (f"[0:v]fps={FPS},split[a][b];[a]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,"
              f"boxblur=20:3,eq=brightness=-0.18,scale={OW}:{OH}[bg];"
              f"[b]scale=w='trunc({OW}*{z}/2)*2':h='trunc({OW * 9 // 16}*{z}/2)*2':eval=frame:{up},"
              f"crop={OW}:{OW * 9 // 16 // 2 * 2}:(iw-{OW})/2:(ih-{OW * 9 // 16 // 2 * 2})/2,{sharpen}[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
        seam, cap_y = 1100, 2840
    vf = vf.replace(f"[0:v]fps={FPS}", f"[0:v]fps={FPS},select='{sel}',setpts=N/{FPS}/TB", 1)
    src_span = segs[-1][1] + 0.2
    lst, emo = caption_track(words, c, seam, cap_y, dur, work / "cap")
    out = clips / f"clip_{n:02d}_{g.slug(c.get('title') or c.get('hook'), 40)}_4K.mp4"
    bar = f"color=c=0x{ACCENT[0]:02x}{ACCENT[1]:02x}{ACCENT[2]:02x}:s={OW}x18:r={FPS}"
    fo = max(0.0, dur - 0.35)
    fc_graph = (vf + f";[1:v]format=rgba[ov];[base][ov]overlay=0:0:eof_action=repeat:format=auto[cv];"
                f"{bar}[bar];[cv][bar]overlay=x='-W+W*t/{dur:.3f}':y=H-h:shortest=1,format=yuv420p[v];"
                f"[0:a]aselect='{asel}',asetpts=N/SR/TB,loudnorm=I=-14:TP=-1.0:LRA=9,afade=t=in:d=0.05,afade=t=out:st={fo:.2f}:d=0.35,"
                f"aresample=48000[aout]")
    r = g.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.3f}", "-t", f"{src_span:.3f}", "-i", str(src),
               "-f", "concat", "-safe", "0", "-i", str(lst), "-filter_complex", fc_graph,
               "-map", "[v]", "-map", "[aout]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium",
               "-crf", "17", "-profile:v", "high", "-level", "5.2", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    if r.returncode != 0:
        raise RuntimeError("render failed: " + r.stderr[-800:])
    tags = " ".join(c.get("hashtags") or ["#GTA6", "#GTAVI", "#gta6clips"])
    out.with_suffix(".txt").write_text(
        f"TITLE:\n{c.get('title', '')}\n\nDESCRIPTION:\n{c.get('description') or c.get('caption', '')}\n\n"
        f"HASHTAGS:\n{tags}\n\n---\n"
        f"Source: {info['streamer']} at {g.hms(c['_s'])}\nScore: {c.get('score')}  Layout: {fc['mode']}  "
        f"Zooms at: {', '.join(f'{p:.1f}s' for p in peaks) or 'none'}  Emojis: {' '.join(emo.values())}\n"
        f"Length: {dur:.1f}s  Jump cuts: {len(segs) - 1} (removed {cut_away:.1f}s of pauses)\n")
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return out, fc["mode"], peaks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min-score", type=float, default=7.0)
    p.add_argument("--only", help="comma list of clip numbers to (re)render")
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    rd = Path(a.run)
    info = json.loads((rd / "stream.json").read_text())
    picks, total = g.select(rd, a.top, a.min_score)
    # Shorts / Reels: every clip 30-60 s, ends snapped to a sentence end where possible
    segs = json.loads((rd / "transcript.json").read_text())
    for c in picks:
        d = c["_e"] - c["_s"]
        if d < 30:  # (>60 is handled after jump cuts, on the final edited length)
            ends = [s["end"] + 0.3 for s in segs if c["_s"] + 30 <= s["end"] + 0.3 <= c["_s"] + 60]
            c["_e"] = min(ends) if ends else c["_s"] + 30
    only = {int(x) for x in a.only.split(",")} if a.only else None
    g.log(f"[{info['streamer']}] {total} candidate moments -> rendering {len(picks)} in 4K")
    made = []
    for n, c in enumerate(picks, 1):
        if only and n not in only:
            continue
        t0 = time.time()
        slug = g.slug(c.get('title') or c.get('hook'), 40)
        want = rd / "clips_4k" / f"clip_{n:02d}_{slug}_4K.mp4"
        prev = [p for p in (rd / "clips_4k").glob(f"clip_*_{slug}_4K.mp4") if p.with_suffix(".txt").exists()]
        if prev and not only:
            if prev[0] != want:
                prev[0].rename(want)
                prev[0].with_suffix(".txt").rename(want.with_suffix(".txt"))
            g.log(f"  clip {n}: already rendered -> {want.name}")
            made.append({"file": str(want), "title": c.get("title"), "score": c.get("score"), "at": g.hms(c["_s"])})
            continue
        try:
            out, mode, peaks = render(rd, info, c, n, a.keep)
            made.append({"file": str(out), "title": c.get("title"), "score": c.get("score"), "layout": mode,
                         "at": g.hms(c["_s"]), "len": round(c["_e"] - c["_s"])})
            g.log(f"  clip {n}: {c.get('title')} ({g.hms(c['_s'])}, {round(c['_e'] - c['_s'])}s, {mode}, "
                  f"{len(peaks)} zooms, {round(time.time() - t0)}s) -> {out.name}")
        except Exception as e:
            if c.get("layout") != "gameplay":  # facecam box went bad (cam off / scene switch): retry full-frame
                g.log(f"  clip {n}: layout failed ({str(e)[:80]}), retrying as gameplay")
                c["layout"] = "gameplay"
                try:
                    out, mode, peaks = render(rd, info, c, n, a.keep)
                    made.append({"file": str(out), "title": c.get("title"), "score": c.get("score"), "layout": mode,
                                 "at": g.hms(c["_s"]), "len": round(c["_e"] - c["_s"])})
                    g.log(f"  clip {n}: {c.get('title')} ({g.hms(c['_s'])}, {mode}, retry) -> {out.name}")
                    continue
                except Exception as e2:
                    e = e2
            g.log(f"  clip {n} FAILED: {e}")
    (rd / "clips_4k").mkdir(exist_ok=True)
    (rd / "clips_4k" / "summary.json").write_text(json.dumps({"stream": info["title"], "clips": made}, indent=1))


if __name__ == "__main__":
    main()
