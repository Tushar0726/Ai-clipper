"""Vertical 2160x3840 clip, 25% facecam (cut-out cam) on top, 75% gameplay below.

Driven by a JSON spec:
{
 "src": "lucia.mp4",                 # 1080p source piece (local)
 "out": "clip.mp4",
 "keep": [[a, b], ...],              # source seconds to keep (jump cuts between them)
 "cam": [x, y, w, h],                # facecam region in the 1920x1080 source
 "game_x": 770,                      # left edge of the 810-px-wide gameplay crop
 "hook": "TEXT", "hook_emoji": "😱",
 "lines": [[t0, t1, "bhai ye kya", ["kya"], ["ye"]], ...],   # source-time caption lines, yellow words, cyan words
 "zooms": [t, ...],                  # source times of punch-ins (gameplay)
 "flash": [t, ...],                  # source times of white flashes
 "boom": [t, ...]                    # source times of a low "boom" sfx
}
Captions sit on the lower part of the facecam panel (over the chest, below the face), never on gameplay.
"""
import json, subprocess, sys, os, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OW, OH, FPS = 2160, 3840, 60
TOP = OH // 4                      # 960: facecam panel (25%)
BOT = OH - TOP                     # 2880: gameplay panel (75%)
SEAM = 8
FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
WHITE, YELLOW, CYAN = (255, 255, 255, 255), (255, 214, 10, 255), (0, 229, 255, 255)
CAP_Y = 0.70
SK = Path(os.path.expanduser("~/.claude/skills/gta6-clipper/scripts"))


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[:1500])
    return r


def emoji_img(ch, size):
    try:
        f = ImageFont.truetype(EMOJI, 109)
        im = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((0, 0), ch, font=f, embedded_color=True)
        im = im.crop(im.getbbox() or (0, 0, 136, 128))
        return im.resize((size, int(size * im.height / im.width)), Image.LANCZOS)
    except Exception:
        return None


def caption_frame(words, active, yellow, cyan, scale, path):
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    size = int(118 * scale)
    f = ImageFont.truetype(FONT, size)
    sp = int(size * 0.28)
    ws = [w.upper() for w in words]
    widths = [d.textlength(w, font=f) for w in ws]
    total = sum(widths) + sp * (len(ws) - 1)
    x = (OW - total) / 2
    y = int(OH * CAP_Y) - size // 2
    for i, (w, wd) in enumerate(zip(ws, widths)):
        base = words[i].lower().strip(",.!?")
        col = YELLOW if i == active else (CYAN if base in cyan else (YELLOW if base in yellow else WHITE))
        d.text((x, y), w, font=f, fill=col, stroke_width=max(8, size // 11), stroke_fill=(0, 0, 0, 255))
        x += wd + sp
    im.save(path)


def hook_frame(text, emo, path):
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 104)
    lines, cur = [], ""
    for w in text.upper().split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > 1700 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    if len(lines) == 2:  # balance the two lines instead of leaving one orphan word
        ws = text.upper().split(); best = None
        for k in range(1, len(ws)):
            a_, b_ = " ".join(ws[:k]), " ".join(ws[k:])
            m = max(d.textlength(a_, font=f), d.textlength(b_, font=f))
            if m <= 1700 and (best is None or m < best[0]):
                best = (m, [a_, b_])
        if best:
            lines = best[1]
    lh = 130
    bh = lh * len(lines) + 90
    bw = max(d.textlength(l, font=f) for l in lines) + 140
    x0, y0 = (OW - bw) / 2, 960
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=44, fill=(255, 255, 255, 245))
    d.rounded_rectangle((x0, y0 + bh - 16, x0 + bw, y0 + bh), radius=8, fill=(0, 229, 255, 255))
    for i, l in enumerate(lines):
        d.text(((OW - d.textlength(l, font=f)) / 2, y0 + 40 + i * lh), l, font=f, fill=(10, 10, 10, 255))
    if emo:
        e = emoji_img(emo, 190)
        if e:
            im.alpha_composite(e, (int(x0 + bw - e.width / 2), int(y0 - e.height / 2)))
    im.save(path)


def main(spec_path):
    S = json.loads(Path(spec_path).read_text())
    global CAP_Y
    CAP_Y = S.get("cap_y", 0.62)   # caption height; move up when the car/character sits low in frame
    base = Path(spec_path).resolve().parent
    src = str(base / S["src"])
    work = base / (Path(spec_path).stem + "_work"); work.mkdir(exist_ok=True)
    keep = S["keep"]
    # source time -> output time
    def remap(t):
        o = 0.0
        for a, b in keep:
            if a <= t <= b:
                return o + t - a
            o += b - a
        return None
    dur = sum(b - a for a, b in keep)

    # ---------- caption + hook overlay timeline (ffconcat of PNGs)
    blank = work / "blank.png"; Image.new("RGBA", (OW, OH), (0, 0, 0, 0)).save(blank)
    hook = work / "hook.png"; hook_frame(S["hook"], S.get("hook_emoji"), hook)
    events = []  # (out_t0, out_t1, png)
    HOOK_T = 3.0
    k = 0
    for ln in S["lines"]:
        t0, t1, text, yel, cyan = ln[:5]
        wt = ln[5] if len(ln) > 5 else None   # optional per-word start times (source seconds) from word-level ASR
        a, b = remap(t0), remap(t1)
        if a is None or b is None:
            continue
        words = text.split()
        # split the line into on-screen groups that fit the width (max 3 words)
        mf = ImageFont.truetype(FONT, int(118 * 1.18)); md = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        groups, cur = [], []
        for w in words:
            t = " ".join(cur + [w]).upper()
            if cur and (len(cur) >= 3 or md.textlength(t, font=mf) > 1900):
                groups.append(cur); cur = [w]
            else:
                cur.append(w)
        groups.append(cur)
        owner = [(gi, wi) for gi, g in enumerate(groups) for wi in range(len(g))]
        step = (b - a) / len(words)
        for i in range(len(words)):
            ws, we = a + i * step, a + (i + 1) * step
            if wt:
                ws = remap(wt[i]); we = remap(wt[i + 1]) if i + 1 < len(wt) else b
                if ws is None or we is None or we <= ws:
                    continue
            gi, wi = owner[i]
            for j, sc in enumerate((1.18, 1.08, 1.0)):   # pop-in animation
                p = work / f"c{k:04d}.png"; k += 1
                caption_frame(groups[gi], wi, set(yel), set(cyan), sc, p)
                s0 = ws + j * 0.05
                s1 = ws + (j + 1) * 0.05 if j < 2 else we
                if s1 > s0:
                    events.append((s0, s1, p))
    events.sort()
    # merge with hook: during [0, HOOK_T] composite hook over captions
    def with_hook(p, name):
        im = Image.open(p).convert("RGBA"); im.alpha_composite(Image.open(hook)); out = work / name; im.save(out); return out
    lines, t = ["ffconcat version 1.0"], 0.0
    def add(png, d):
        nonlocal t
        if d > 0.0005:
            lines.append(f"file '{png}'"); lines.append(f"duration {d:.4f}"); t += d
    def add_span(png_plain, a, b, idx):
        # split at HOOK_T so the hook card shows only for the first seconds
        if a < HOOK_T:
            m = min(b, HOOK_T)
            add(with_hook(png_plain, f"h{idx:04d}.png"), m - a)
            if b > HOOK_T:
                add(png_plain, b - HOOK_T)
        else:
            add(png_plain, b - a)
    idx = 0
    for a, b, p in events:
        if a > t:
            add_span(blank, t, a, idx); idx += 1
        a = max(a, t)
        add_span(p, a, b, idx); idx += 1
    if t < dur:
        add_span(blank, t, dur, idx)
    lines.append(f"file '{blank}'")
    (work / "caps.ffconcat").write_text("\n".join(lines) + "\n")

    # ---------- video filter
    sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    zt = [remap(z) for z in S.get("zooms", []) if remap(z) is not None]
    # transition at every jump cut: quick punch-in + white flash + whoosh
    cuts = []
    o = 0.0
    for a_, b_ in keep[:-1]:
        o += b_ - a_
        cuts.append(round(o, 3))
    zt = sorted(set(zt + [c for c in cuts if all(abs(c - z) > 0.8 for z in zt)]))
    S["_cuts"] = cuts
    # zoom curve: ease to 1.14 in 0.2 s, hold 1.0 s, ease back 0.3 s
    zexpr = "1"
    for z in zt:
        zexpr += (f"+0.14*if(between(t,{z:.3f},{z+0.2:.3f}),(t-{z:.3f})/0.2,"
                  f"if(between(t,{z+0.2:.3f},{z+1.2:.3f}),1,if(between(t,{z+1.2:.3f},{z+1.5:.3f}),1-(t-{z+1.2:.3f})/0.3,0)))")
    shake = "+".join(f"if(between(t,{z:.3f},{z+0.5:.3f}),14*sin(t*90),0)" for z in zt) or "0"
    cx, cy, cw, ch = S["cam"]
    # gameplay window: 608x1080 (9:16) centred on the main character; game_x = [[src_t, centre_x], ...]
    TT = int(S.get("trim_top", 0))           # source has a black bar on top in some scenes
    GH = 1080 - TT
    GW = int(GH * 9 / 16) // 2 * 2
    gxs = S.get("game_x", [[0, 960]])
    if isinstance(gxs, (int, float)):
        gxs = [[0, gxs]]
    pts = sorted((remap(t) if remap(t) is not None else (0 if t <= keep[0][0] else None), x) for t, x in gxs)
    pts = [(t, x) for t, x in pts if t is not None]
    # keep the stream's own bottom-left facecam OUT of the window (no blur patches): window starts right of it
    # Carry sits bottom-left (over the spot where the stream's own facecam is), so the window may
    # overlap that facecam as long as our overlay covers it
    CAMW = S.get("cam_w", 1250)
    CAMH = int(CAMW * ch / cw) // 2 * 2
    sc = OH / GH
    minlo = cx + cw - int((CAMW - 260) / sc)
    clampx = lambda x: int(max(minlo, min(1920 - GW, x - GW / 2)))
    gexpr = str(clampx(pts[0][1]))
    for t, x in pts[1:]:
        gexpr = f"if(gte(t,{t:.3f}),{clampx(x)},{gexpr})"
    strip = ""
    CAMX, CAMY = 0, OH - CAMH
    from PIL import ImageFilter
    mk = Image.new("L", (CAMW, CAMH), 0)
    ImageDraw.Draw(mk).rounded_rectangle((-200, 110, CAMW - 110, CAMH + 200), radius=90, fill=255)
    mk = mk.filter(ImageFilter.GaussianBlur(50))  # left/bottom touch the frame, short fade on top/right
    maskp = work / "cammask.png"; mk.save(maskp)
    S["_mask"] = str(maskp)
    fl = [remap(f) for f in S.get("flash", []) if remap(f) is not None] + S["_cuts"]
    flen = "+".join(f"between(t,{f:.3f},{f+0.1:.3f})" for f in fl) or "0"
    zexpr = zexpr.replace("0.14*", "0.08*")
    vf = (
        f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,fps={FPS},split=2[b][c];"
        # full-screen gameplay, character centred, punch-in zoom + shake on peaks
        f"[c]crop={GW}:{GH}:'{gexpr}':{TT},{strip}scale=w='trunc({OW}*({zexpr})/2)*2':h='trunc({OH}*({zexpr})/2)*2':eval=frame:flags=lanczos,"
        f"crop={OW}:{OH}:'(iw-{OW})/2+({shake})':'(ih-{OH})/2',unsharp=5:5:0.45,eq=saturation=1.1:contrast=1.04[base0];"
        # Carry in the bottom-left corner, soft blended edges like on stream
        f"[b]crop={cw}:{ch}:{cx}:{cy},scale={CAMW}:{CAMH}:flags=lanczos,unsharp=5:5:0.5,format=rgba[camc];"
        f"[2:v]format=gray,scale={CAMW}:{CAMH}[cm];[camc][cm]alphamerge[cam];"
        f"[base0][cam]overlay={CAMX}:{CAMY}:shortest=1[base];"
        f"[1:v]format=rgba[caps];[base][caps]overlay=0:0:shortest=0:eof_action=pass[v1];"
        f"color=white:s={OW}x{OH}:r={FPS},format=rgba,colorchannelmixer=aa=0.75[fl];"
        f"[v1][fl]overlay=0:0:shortest=1:enable='{flen}',"
        f"drawbox=x=0:y={OH-14}:w='iw*t/{dur:.3f}':h=14:color=0x00e5ff@0.95:t=fill:replace=0[v]"
    )
    asel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    booms = [remap(b) for b in S.get("boom", []) if remap(b) is not None]
    af = f"[0:a]aselect='{asel}',asetpts=N/SR/TB,aresample=48000,highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=10:release=200[voice];"
    sfx_in, mix = [], ["[voice]"]
    af += f"anoisesrc=color=pink:d=0.55:a=0.6:r=48000,lowpass=f=2500,highpass=f=300,afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.2,volume=0.35,aformat=channel_layouts=stereo[wh0];"
    mix.append("[wh0]")
    for i, c in enumerate(S["_cuts"]):
        ms = max(0, int((c - 0.25) * 1000))
        af += (f"anoisesrc=color=pink:d=0.45:a=0.6:r=48000,lowpass=f=3000,highpass=f=400,afade=t=in:d=0.25,afade=t=out:st=0.25:d=0.2,"
               f"volume=0.22,aformat=channel_layouts=stereo,adelay={ms}|{ms}[cw{i}];")
        mix.append(f"[cw{i}]")
    for i, b in enumerate(booms):
        af += (f"sine=f=55:d=0.6:r=48000,volume='0.9*exp(-6*t)':eval=frame,aformat=channel_layouts=stereo,"
               f"adelay={int(b*1000)}|{int(b*1000)}[bm{i}];")
        mix.append(f"[bm{i}]")
    af += f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    out = str(base / S["out"])
    fpath = work / "graph.txt"; fpath.write_text(vf + ";" + af)
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-f", "concat", "-safe", "0", "-i", str(work / "caps.ffconcat"), "-loop", "1", "-i", S["_mask"],
        "-filter_complex_script", str(fpath), "-map", "[v]", "-map", "[aout]", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high", "-level", "5.2", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out])
    print("done", out, f"{dur:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1])
