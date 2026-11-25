"""Add effects-skill effects (stamp, follow button, pause-point...) to short windows of a finished clip.

usage: postfx.py in.mp4 out.mp4 plan.json
plan.json: [{"fx": "reject-stamp", "start": 28.0, "end": 30.0, "text": "SOLD!", "y": 0.35}, ...]  (clip seconds)

The effects script works at 30 fps and re-renders every frame in Python, so instead of passing the whole
4K/60 clip through it we cut out only each effect window, run the effect on that piece, and overlay the
result back onto the original at the same time (one final encode, original audio kept).
"""
import json, subprocess, sys, os
from pathlib import Path

FX = Path(os.path.expanduser("~/.claude/skills/effects"))
src, out, planp = sys.argv[1:4]
plan = json.loads(Path(planp).read_text())
work = Path(out).with_suffix(".fxwork"); work.mkdir(exist_ok=True)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])


segs = []
for i, e in enumerate(plan):
    s, d = float(e["start"]), float(e["end"]) - float(e["start"])
    piece = work / f"p{i}.mp4"
    sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", src, "-t", f"{d:.3f}", "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "12", str(piece)])
    pe = dict(e); pe["start"], pe["end"] = 0.0, d
    (work / f"p{i}.json").write_text(json.dumps({"effects": [pe]}))
    fxo = work / f"p{i}_fx.mp4"
    r = subprocess.run([str(FX / ".venv/bin/python"), str(FX / "scripts/fx.py"), "--plan", str(work / f"p{i}.json"),
                        str(piece), str(fxo), "--width", "2160"], capture_output=True, text=True)
    if not fxo.exists():
        raise SystemExit("effect failed: " + r.stderr[-1500:])
    segs.append((s, d, fxo))

inputs, filt, last = ["-i", src], [], "[0:v]"
for i, (s, d, f) in enumerate(segs):
    inputs += ["-i", str(f)]
    filt.append(f"[{i+1}:v]fps=60,setpts=PTS-STARTPTS+{s:.3f}/TB[f{i}]")
    filt.append(f"{last}[f{i}]overlay=0:0:enable='between(t,{s:.3f},{s+d-0.02:.3f})':eof_action=pass[v{i}]")
    last = f"[v{i}]"
graph = ";".join(filt)
sh(["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", last, "-map", "0:a",
    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high", "-level", "5.2", "-pix_fmt", "yuv420p",
    "-r", "60", "-c:a", "copy", "-movflags", "+faststart", out])
print("done", out)
