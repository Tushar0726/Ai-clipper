#!/usr/bin/env python3
"""Render a stream clip as a 9:16 Short / Reel with a streamer + gameplay layout.

Layouts
  inline  The streamer is already composited into the game (e.g. a green-screen
          cut-out like CarryMinati). One 9:16 gameplay crop that keeps the
          streamer inside it (so he is never shown twice), plus a text band on
          top for the hook and subtitles.
            [ hook + subtitles 20% ]
            [ gameplay incl. cam 80% ]
  panel   The streamer has a separate webcam box (e.g. N3on). Gameplay on top,
          webcam panel at the bottom; subtitles sit on the webcam panel.
            [ gameplay 80% ]
            [ webcam 20% ]

Extras: streamer face auto-detected per clip, word-by-word subtitles (Whisper)
kept OFF the gameplay, a hook intro (the loudest moment played first with a
zoom punch + white flash), and a progress bar.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
FONT = "Anton"

TRANSITIONS = ["zoomin", "circleopen", "slideup", "fadewhite", "pixelize", "radial",
               "smoothup", "hblur", "squeezev", "wipeup"]

HOOKS = {
    "carryminati": ["CARRY KO YE NAHI PATA THA", "GTA 6 MEIN YE KYA HO GAYA", "CARRY KA DIMAG GHOOM GAYA",
                    "END TAK DEKHNA", "CARRY VS GTA 6", "YE GTA 6 HAI YA REAL LIFE?",
                    "CARRY KA REACTION DEKHO", "SABSE PAGAL GTA 6 MOMENT", "YE KYA HO GAYA BHAI",
                    "CARRY VS POLICE", "GTA 6 MEIN CARRY KA SCENE", "BHAI NE KAR DIYA"],
    "n3on": ["N3ON LOST IT IN GTA 6", "WAIT FOR THE END", "GTA 6 IS INSANE",
             "N3ON CAN'T BELIEVE THIS", "CRAZIEST GTA 6 MOMENT", "N3ON VS GTA 6", "HE DID NOT EXPECT THIS",
             "GTA 6 WENT WRONG", "WATCH TILL THE END", "N3ON IS DONE"],
    "_": ["WAIT FOR IT", "GTA 6 IS INSANE", "CRAZIEST GTA 6 MOMENT"],
}


# ------------------------------------------------------------------ analysis
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    return s["width"], s["height"], float(d["format"]["duration"])


def find_streamer_face(path, samples=14):
    """Return the streamer's face box (x, y, w, h) in source pixels, or None.

    Game characters move around; the streamer's webcam stays put. So detect
    faces on many frames and keep the position that repeats the most.
    """
    import cv2
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    hits = []  # (frame_idx, x, y, w, h)
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for (x, y, w, h) in cascade.detectMultiScale(gray, 1.1, 6, minSize=(50, 50)):
            hits.append((k, x, y, w, h))
    cap.release()
    best, best_frames = None, 0
    for _, x, y, w, h in hits:
        cx, cy = x + w / 2, y + h / 2
        group = [b for b in hits if abs(b[1] + b[3] / 2 - cx) < w * 0.6 and abs(b[2] + b[4] / 2 - cy) < h * 0.6]
        frames = len({b[0] for b in group})
        if frames > best_frames:
            best_frames, best = frames, group
    if not best or best_frames < max(3, samples // 4):
        return None
    med = lambda i: sorted(b[i] for b in best)[len(best) // 2]
    return med(1), med(2), med(3), med(4)


_segmenter = None


def cam_mask_video(src, box, dst, fps=30):
    """Write a greyscale matte video for box=(x,y,w,h): white = streamer + chair.

    Person pixels come from MediaPipe's selfie segmenter (per frame). The chair
    is found as the pixels that never change while the game behind them moves
    (a green-screen cut-out is static), kept only close to the person.
    """
    import cv2
    import numpy as np
    global _segmenter
    import mediapipe as mp
    from mediapipe.tasks.python import vision, BaseOptions
    if _segmenter is None:
        _segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "models" / "selfie_segmenter.tflite")),
            output_confidence_masks=True))
    x, y, w, h = box
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf",
                          f"fps={fps},crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    people = []
    for f in frames:
        m = _segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(f)))
        m = m.confidence_masks[0].numpy_view().squeeze()
        people.append(m)
    people = np.array(people, np.float32)
    # confidence_masks[0] of the selfie segmenter = person (1.0 on the streamer)
    # chair / static parts next to the person
    idx = np.linspace(0, len(frames) - 1, min(40, len(frames))).astype(int)
    grey = np.array([cv2.cvtColor(frames[i], cv2.COLOR_RGB2GRAY) for i in idx], np.float32)
    static = (grey.std(0) < 9).astype(np.uint8)
    hsv = np.array([cv2.cvtColor(frames[i], cv2.COLOR_RGB2HSV) for i in idx[:10]])
    dark = ((grey.mean(0) < 85) & (hsv[..., 1].mean(0) < 90)).astype(np.uint8)  # black / grey, not red
    near = (people.max(0) > 0.5).astype(np.uint8)
    k = max(15, int(min(w, h) * 0.22)) | 1
    near = cv2.dilate(near, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    # thin lines / specks are game pixels that happened to stay still: drop them, keep only
    # solid static blobs that touch the person (the chair, a can on the desk ...)
    blob = cv2.morphologyEx(static & dark & near, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    person_any = (people.mean(0) > 0.5).astype(np.uint8)
    n, lab = cv2.connectedComponents(blob | person_any)
    keep = set(np.unique(lab[person_any > 0])) - {0}
    chair = (np.isin(lab, list(keep)) & (blob > 0)).astype(np.uint8)
    chair = cv2.morphologyEx(chair, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(np.float32)
    # RGBA cut-out video (streamer pixels + alpha), so no frame-sync between two streams later
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                            "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "qtrle", str(dst)],
                           stdin=subprocess.PIPE)
    # the segmenter sometimes marks road lines / smoke as "person" for a few frames:
    # keep each frame's mask close to the streamer's usual shape, and fall back to that
    # usual (median) shape whenever a frame's mask is clearly broken
    med = (np.median(people, 0) > 0.5).astype(np.uint8)
    med_area = max(1, int(med.sum()))
    kk = max(7, int(min(w, h) * 0.05)) | 1
    region = cv2.dilate(med, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))
    _cols = np.where(med.any(0))[0]
    med_left = int(_cols.min()) if len(_cols) else 0
    med_mid = (_cols.min() + _cols.max()) / 2 - 0.12 * w if len(_cols) else 0
    for i, (f, m) in enumerate(zip(frames, people)):
        cur = (m > 0.5).astype(np.uint8)
        outside = int((cur & (1 - region)).sum())
        if outside > 0.08 * med_area or abs(int(cur.sum()) - med_area) > 0.35 * med_area:
            cur = med
        person = (cur & region).astype(np.uint8)
        # biggest person blob only (drops cans / edge leftovers), then add the chair
        n, lab, st, _ = cv2.connectedComponentsWithStats(person)
        if n > 2:
            person = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        a = np.maximum(person.astype(np.float32), chair)
        a[:, :max(0, med_left - 8)] = 0   # nothing left of the streamer (cans, overlays)
        # bright red/orange product cans next to the streamer (his maroon shirt is much darker)
        hv = cv2.cvtColor(f, cv2.COLOR_RGB2HSV)
        can = (hv[..., 1] > 120) & (hv[..., 2] > 150)
        can[:, int(med_mid):] = False
        can = cv2.dilate(can.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        a[can] = 0
        a = cv2.GaussianBlur(a, (7, 7), 0)
        enc.stdin.write(np.dstack([f, (a * 255).astype(np.uint8)]).tobytes())
    enc.stdin.close()
    enc.wait()
    cols = np.where(med.any(0))[0]
    return (int(cols.min()), int(cols.max())) if len(cols) else (0, w)


def loudest_second(path):
    """Second (float) with the loudest 3s window - used for the hook."""
    af = ("aresample=8000,asetnsamples=n=4000:p=0,astats=metadata=1:reset=1,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
    out = subprocess.run(["ffmpeg", "-nostats", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-af", af, "-f", "null", "-"], capture_output=True, text=True).stdout
    lv = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1]
            lv.append(-90.0 if v in ("-inf", "inf", "nan") else max(float(v), -90.0))
    if len(lv) < 8:
        return 0.0
    win = 6  # 6 x 0.5s = 3s
    sm = [sum(lv[i:i + win]) / win for i in range(len(lv) - win)]
    i = max(range(len(sm)), key=sm.__getitem__)
    return (i + win / 2) * 0.5


_whisper = {}
# Hindi needs the big model; English is fine with the small one
WHISPER_MODEL = {"hi": "large-v3-turbo", "en": "small"}

# swear words are starred out in subtitles (YouTube / Instagram friendly)
SWEARS = ("gandu", "gaandu", "laude", "lode", "lauda", "loda", "lavde", "chutiya", "chutiye", "madarchod",
          "bhenchod", "behenchod", "bhosdi", "bhosdike", "bsdk", "bc", "mc", "randi", "harami", "kamina",
          "fuck", "fucking", "fucked", "motherfucker", "motherfuckers", "fucker", "fuckers", "shit", "bitch", "nigga", "nigger", "dick", "pussy", "ass", "asshole")


def censor(word):
    core = "".join(ch for ch in word.lower() if ch.isalpha())
    if core in SWEARS and len(core) > 2:
        return core[0] + "*" * (len(core) - 2) + core[-1]
    if core in SWEARS:
        return "*" * len(core)
    return word


# creators who speak Hindi: transcribe in Hindi, then write it in Roman letters (Hinglish)
HINGLISH = {"carryminati"}


_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
         "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
         "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
         "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "gh",
         "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y"}
_VOW = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o",
        "औ": "au", "ऋ": "ri", "ऑ": "o", "ऍ": "e"}
_MATRA = {"ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
          "ृ": "ri", "ॉ": "o", "ॅ": "e"}
_NUKTA, _VIRAMA = "\u093c", "\u094d"


def to_hinglish(word):
    """Devanagari -> casual Roman Hinglish ('क्या हो गया' -> 'kya ho gaya'),
    dropping the silent 'a' the way Hindi is actually spoken."""
    if not any("\u0900" <= ch <= "\u097f" for ch in word):
        return word
    # tokens: (kind, roman) with kind c = consonant (inherent a), C = consonant (no a), v = vowel
    toks, i = [], 0
    while i < len(word):
        ch = word[i]
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch + nxt in _CONS and nxt == _NUKTA:
            ch, i = ch + nxt, i + 1
            nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in _CONS:
            if nxt == _VIRAMA:
                toks.append(("C", _CONS[ch])); i += 2; continue
            if nxt in _MATRA:
                toks.append(("C", _CONS[ch])); toks.append(("v", _MATRA[nxt])); i += 2; continue
            toks.append(("c", _CONS[ch]))
        elif ch in _VOW:
            toks.append(("v", _VOW[ch]))
        elif ch in ("ं", "ँ"):
            toks.append(("v", "n"))
        elif ch == "ः":
            toks.append(("v", "h"))
        elif ch not in (_NUKTA, _VIRAMA):
            toks.append(("v", ch))
        i += 1
    out = []
    for k, (kind, r) in enumerate(toks):
        out.append(r)
        if kind != "c":
            continue
        last = k == len(toks) - 1
        # schwa deletion: drop the 'a' at the end of a word, and in the middle when a
        # vowel comes before and a consonant+vowel comes after (shaanadaara -> shaandaar)
        prev_vowel = k > 0 and toks[k - 1][0] in ("v", "c")
        nxt_cv = k + 2 < len(toks) and toks[k + 1][0] in ("c", "C") and toks[k + 2][0] == "v"
        if last and k > 0:
            continue
        if prev_vowel and nxt_cv and k > 0:
            continue
        out.append("a")
    r = "".join(out)
    r = r.replace("ee", "i").replace("aaya", "aaya")  # naheen -> nahin, jeepees -> jipis
    if r.endswith("oo"):                             # gandoo -> gandu
        r = r[:-2] + "u"
    return r.replace("aai", "ai") if r.endswith("aai") else r


def transcribe(path, model=None, lang="en"):
    """Word timestamps [(start, end, word)] in Roman letters (English or Hinglish)."""
    import numpy as np
    from faster_whisper import WhisperModel
    model = model or WHISPER_MODEL.get(lang, "small")
    if model not in _whisper:
        _whisper[model] = WhisperModel(model, device="cpu", compute_type="int8")
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    if lang == "hi":  # Carry may be quiet while English game dialogue plays: let Whisper decide
        _, info = _whisper[model].transcribe(audio[:16000 * 30], language=None)
        lang = "hi" if info.language in ("hi", "ur") else "en"
    segs, _ = _whisper[model].transcribe(audio, language=lang, word_timestamps=True, vad_filter=True,
                                  condition_on_previous_text=False)
    words = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if (w.probability or 0) < 0.45:  # unsure words become garbage subtitles: skip them
                continue
            if lang == "hi":
                t = to_hinglish(t)
            t = censor(t).replace("\ufffd", "")
            if t:
                words.append((w.start, w.end, t))
    return words


# ------------------------------------------------------------------ layout
def even(v):
    return int(v) // 2 * 2


def plan_layout(layout, src_w, src_h, face, W, H):
    """Crop boxes (x, y, w, h) in source pixels + panel heights in output px."""
    band = even(H * 0.20) if layout == "panel" else 0
    main_h = H - band
    gw = even(src_h * W / main_h)  # gameplay crop width for the full source height
    center_x = (src_w - gw) // 2
    small_face = face is not None and face[2] < src_w * 0.16

    if layout == "inline" or not small_face:
        # gameplay: centre crop - in GTA the player / car is always mid-screen
        gw = even(src_h * W / H)
        lay = {"kind": "inline", "band": 0, "game": (even((src_w - gw) // 2), 0, gw, src_h)}
        if small_face:
            # cut the streamer's own box out and pin it to the bottom-left corner
            fx, fy, fw, fh = face
            bx = even(max(0, fx - fw * 1.7))
            by = even(max(0, fy - fh * 0.8))
            bw = even(min(src_w - bx, fw * 4.4))
            bh = even(min(src_h - by, fh * 3.6))
            lay["cam"] = (bx, by, bw, bh)
            lay["face_w"] = int(fw)

        return lay

    # panel: webcam box at the bottom
    fx, fy, fw, fh = face
    cam_aspect = W / band
    ch = even(min(src_h, fh * 2.2))
    cw = even(min(src_w, ch * cam_aspect))
    # stay inside the webcam box (it is ~4-5 face-widths wide): never show game in the panel
    box_right = fx + fw * 3.4 if fx < src_w / 2 else src_w
    box_left = fx - fw * 2.4 if fx >= src_w / 2 else 0
    cw = even(min(cw, box_right - max(0, box_left)))
    ch = even(cw / cam_aspect)
    cx = even(min(max(max(0, box_left), fx + fw / 2 - cw / 2), min(src_w, box_right) - cw))
    cy = even(min(max(0, fy + fh * 0.45 - ch / 2), src_h - ch))
    # gameplay crop: as central as possible but away from the webcam box
    cam_left, cam_right = fx - fw * 1.5, fx + fw * 2.5
    x = center_x
    if x < cam_right and x + gw > cam_left and fy < src_h * 0.5:
        x = int(cam_right) if fx < src_w / 2 else int(cam_left - gw)
    x = even(min(max(0, x), src_w - gw))
    return {"kind": "panel", "band": band, "game": (x, 0, gw, src_h), "cam": (cx, cy, cw, ch)}


def video_chain(lay, W, H, src, label, out, zoom="1", shake="0", mask=None):
    """filter_complex chain turning [src] into a WxH 9:16 frame [out].
    zoom / shake are zoompan expressions (in_time = seconds) for effects."""
    gx, gy, gw, gh = lay["game"]
    band = lay["band"]
    gh_out = H - band
    # effects run at half size (cheap), then lanczos-upscale to the final size
    zw, zh = even(W / 2), even(gh_out / 2)
    game = (f"crop={gw}:{gh}:{gx}:{gy},scale={zw}:{zh}:flags=lanczos,fps=30,"
            f"zoompan=z='{zoom}':d=1:s={zw}x{zh}:fps=30"
            f":x='iw/2-(iw/zoom/2)+({shake})':y='ih/2-(ih/zoom/2)+({shake})*0.6',"
            f"scale={W}:{gh_out}:flags=lanczos,unsharp=5:5:0.7")
    if lay["kind"] == "inline":
        if "cam" not in lay:
            return f"[{src}]{game},setsar=1[{out}]"
        bx, by, bw, bh = lay["cam"]
        # same on-screen size in every stream: the streamer's face ~14% of the width (~20% of the screen)
        k = (W * 0.14 / lay["face_w"]) if lay.get("face_w") else W / gw * 0.45
        ow, oh = even(bw * k), even(bh * k)
        if mask:  # pre-made RGBA cut-out of just the streamer + chair (no box)
            cam = f"[{mask}]fps=30,format=rgba,scale={ow}:{oh}:flags=lanczos[{label}c];"
            return (f"[{src}]{game}[{label}g];" + cam +
                    f"[{label}g][{label}c]overlay=0:{H - oh}:format=auto,setsar=1[{out}]")
        else:
            cam = (f"[{label}b]fps=30,crop={bw}:{bh}:{bx}:{by},scale={ow}:{oh}:flags=lanczos,"
                   f"unsharp=5:5:0.7[{label}c];")
        return (f"[{src}]split[{label}a][{label}b];"
                f"[{label}a]{game}[{label}g];" + cam +
                f"[{label}g][{label}c]overlay=0:{H - oh}:format=auto,setsar=1[{out}]")
    cx, cy, cw, ch = lay["cam"]
    return (f"[{src}]split[{label}a][{label}b];"
            f"[{label}a]{game}[{label}g];"
            f"[{label}b]fps=30,crop={cw}:{ch}:{cx}:{cy},scale={W}:{band}:flags=lanczos,unsharp=5:5:0.7[{label}c];"
            f"[{label}g][{label}c]vstack,setsar=1[{out}]")


# ------------------------------------------------------------------ text
def ass_time(t):
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build_ass(path, W, H, lay, words, hook_text, hook_len, offset, peak=None, total=None,
              stamp="", btn_xy=None):
    band = lay["band"]
    s = W / 1080
    # upper third of the gameplay: sky / background, away from the streamer
    # (bottom) and the game character (centre)
    hook_y, sub_y = int(H * 0.11), int(H * 0.30)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Sub,{FONT},{int(112 * s)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,"
        f"{int(8 * s)},{int(4 * s)},5,{int(60 * s)},{int(60 * s)},0,1",
        f"Style: Hook,{FONT},{int(132 * s)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,"
        f"{int(11 * s)},{int(5 * s)},8,{int(60 * s)},{int(60 * s)},0,1",
        f"Style: Stamp,{FONT},{int(150 * s)},&H002A2AE8,&H002A2AE8,&H00FFFFFF,&H00000000,0,0,0,0,100,100,6,0,1,"
        f"{int(7 * s)},0,5,0,0,0,1",
        f"Style: Btn,{FONT},{int(64 * s)},&H00FFFFFF,&H00FFFFFF,&H00F69500,&H00000000,0,0,0,0,100,100,3,0,3,"
        f"{int(22 * s)},0,5,0,0,0,1",
        f"Style: BtnOn,{FONT},{int(64 * s)},&H00FFFFFF,&H00FFFFFF,&H00505050,&H00000000,0,0,0,0,100,100,3,0,3,"
        f"{int(22 * s)},0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    # hook title: big during the intro, then stays for 2.5s
    pop = r"{\fscx70\fscy70\t(0,180,\fscx108\fscy108)\t(180,300,\fscx100\fscy100)}"
    lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(hook_len + 2.0)},Hook,,0,0,0,,"
                 f"{{\\pos({W // 2},{hook_y})}}{pop}{hook_text}")
    # word-by-word subtitles, 3 words per chunk, current word highlighted
    chunk = []
    chunks = []
    for w in words:
        chunk.append(w)
        if len(chunk) == 3 or w[2].endswith((".", "?", "!", ",")):
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunks.append(chunk)
    for ch in chunks:
        for i, (ws, we, _) in enumerate(ch):
            end = ch[i + 1][0] if i + 1 < len(ch) else max(we, ws + 0.25)
            parts = []
            for j, (_, _, t) in enumerate(ch):
                t = t.upper().replace("{", "").replace("}", "")
                parts.append(r"{\fscx118\fscy118\bord" + str(int(11 * s)) + "}" + t +
                             r"{\fscx100\fscy100\bord" + str(int(8 * s)) + "}" if j == i else t)
            lines.append(f"Dialogue: 0,{ass_time(ws + offset)},{ass_time(end + offset)},Sub,,0,0,0,,"
                         f"{{\\an5\\pos({W // 2},{sub_y})}}" + " ".join(parts))
    # stamp slam on the loudest moment (skipped if it would clash with the hook title)
    if stamp and peak is not None and peak + offset > hook_len + 2.1:
        t0 = peak + offset - 0.15
        slam = (r"{\an5\pos(%d,%d)\frz-9\fscx320\fscy320\alpha&HFF&"
                r"\t(0,140,\fscx100\fscy100\alpha&H00&)\t(140,220,\fscx112\fscy112)\t(220,300,\fscx100\fscy100)"
                r"\fad(0,220)}" % (W // 2, int(H * 0.20)))
        lines.append(f"Dialogue: 2,{ass_time(t0)},{ass_time(t0 + 1.3)},Stamp,,0,0,0,,{slam}{stamp}")
    # follow button at the end: appears, gets "tapped", flips to Following
    if total and btn_xy:
        bx, by = btn_xy
        a0, tap = total - 3.6, total - 2.4
        pop = r"{\an5\pos(%d,%d)\fscx40\fscy40\t(0,200,\fscx108\fscy108)\t(200,300,\fscx100\fscy100)}" % (bx, by)
        press = r"{\an5\pos(%d,%d)\fscx86\fscy86\t(0,160,\fscx106\fscy106)\t(160,260,\fscx100\fscy100)}" % (bx, by)
        lines.append(f"Dialogue: 3,{ass_time(a0)},{ass_time(tap)},Btn,,0,0,0,,{pop}+ FOLLOW")
        lines.append(f"Dialogue: 3,{ass_time(tap)},{ass_time(total)},BtnOn,,0,0,0,,{press}FOLLOWING")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


STAMPS = {"carryminati": ["PAGAL", "NO WAY", "BHAI WTF", "INSANE", "GG", "OMG"],
          "_": ["NO WAY", "INSANE", "BRUH", "GG", "OMG", "CRAZY"]}


def pick_stamp(creator, seed):
    pool = STAMPS.get(creator.lower(), STAMPS["_"])
    return pool[int(hashlib.md5((seed + "s").encode()).hexdigest(), 16) % len(pool)]


def pick_hook(words, peak, creator, seed):
    pool = HOOKS.get(creator.lower(), HOOKS["_"])
    return pool[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(pool)]


# ------------------------------------------------------------------ render
def render_short(src, dst, layout="inline", creator="", W=2160, H=3840, hook_len=2.5,
                 hook_text=None, subtitles=True, log=print):
    src, dst = Path(src), Path(dst)
    sw, sh, dur = probe(src)
    face = find_streamer_face(src)
    lay = plan_layout(layout, sw, sh, face, W, H)
    peak = loudest_second(src)
    lang = "hi" if creator.lower() in HINGLISH else "en"
    words = transcribe(src, lang=lang) if subtitles else []
    hook = hook_text or pick_hook(words, peak, creator, src.name)
    h0 = max(0.0, min(peak - hook_len * 0.6, dur - hook_len))
    log(f"   face={face} layout={lay['kind']} peak={peak:.1f}s hook={hook!r} words={len(words)}")

    xd = 0.45  # transition length
    trans = TRANSITIONS[int(hashlib.md5(src.name.encode()).hexdigest(), 16) % len(TRANSITIONS)]
    hook_frames = int(hook_len * 30)
    # hook: slow push-in; main: zoom punch + shake on the loudest moment
    bump = f"exp(-pow((in_time-{peak:.2f})/0.30,2))"
    with tempfile.TemporaryDirectory() as td:
        ass = Path(td) / "subs.ass"
        total = hook_len - xd + dur
        if lay["kind"] == "panel":
            btn = (W // 2, H - lay["band"] - int(H * 0.045))
        elif "cam" in lay:
            kk = (W * 0.14 / lay["face_w"]) if lay.get("face_w") else W / lay["game"][2] * 0.45
            bh = even(lay["cam"][3] * kk)
            bw = even(lay["cam"][2] * kk)
            btn = (max(bw // 2, int(W * 0.2)), H - bh - int(H * 0.035))
        else:
            btn = (W // 2, int(H * 0.82))
        build_ass(ass, W, H, lay, words, hook, hook_len, offset=hook_len - xd, peak=peak, total=total,
                  stamp=pick_stamp(creator, src.name), btn_xy=btn)
        masked = lay["kind"] == "inline" and "cam" in lay
        extra_in = []
        if masked:
            matte = Path(td) / "cutout.mov"
            left, right = cam_mask_video(src, lay["cam"], matte)
            # keep the original streamer out of the game crop (no "two Carrys"),
            # moving the crop only as far as his real outline needs
            bx, gw_, gx = lay["cam"][0], lay["game"][2], lay["game"][0]
            if bx < sw / 2 and gx < bx + right:
                gx = even(min(sw - gw_, bx + right + 6))
            elif bx >= sw / 2 and gx + gw_ > bx + left:
                gx = even(max(0, bx + left - 6 - gw_))
            lay["game"] = (gx, 0, gw_, lay["game"][3])
            extra_in = ["-i", str(matte), "-ss", f"{h0:.2f}", "-t", f"{hook_len:.2f}", "-i", str(matte)]
        fc = ";".join([
            video_chain(lay, W, H, "1:v", "h", "hookv",
                        zoom=f"1.0+0.22*min(on/{hook_frames},1)", mask="3:v" if masked else None),
            video_chain(lay, W, H, "0:v", "m", "mainv",
                        zoom=f"1+0.14*{bump}", shake=f"9*sin(on*2.3)*{bump}", mask="2:v" if masked else None),
            f"[hookv][mainv]xfade=transition={trans}:duration={xd}:offset={hook_len - xd:.2f}[cv]",
            f"[0:a]apad=whole_dur={dur:.2f}[a0];[1:a][a0]acrossfade=d={xd}[ca]",  # pad short audio to clip length
            f"[cv]ass={ass}:fontsdir={FONT_DIR}[v]",
            "[ca]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",
        ])
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(src),
               "-ss", f"{h0:.2f}", "-t", f"{hook_len:.2f}", "-i", str(src), *extra_in,
               "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-profile:v", "high",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            # rare ffmpeg failure with padded audio on long clips: retry with plain crossfade
            log("   retrying without audio padding")
            cmd = [c.replace(f"[0:a]apad=whole_dur={dur:.2f}[a0];[1:a][a0]acrossfade", "[1:a][0:a]acrossfade")
                   for c in cmd]
            subprocess.run(cmd, check=True)
    return {"face": face, "layout": lay["kind"], "hook": hook, "peak": peak, "transition": trans}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="source clips (16:9)")
    p.add_argument("--layout", choices=["inline", "panel"], default="inline")
    p.add_argument("--creator", default="")
    p.add_argument("--out", default="output/shorts")
    p.add_argument("--hd", action="store_true", help="1080x1920 instead of 4K 2160x3840")
    p.add_argument("--no-subs", action="store_true")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    W, H = (1080, 1920) if a.hd else (2160, 3840)
    for src in a.inputs:
        dst = out / Path(src).name
        print(dst.name)
        render_short(src, dst, a.layout, a.creator, W, H, subtitles=not a.no_subs)


if __name__ == "__main__":
    main()
