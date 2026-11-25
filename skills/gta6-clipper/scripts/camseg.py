"""Per-frame person mask of the streamer's facecam region -> grayscale mask video (same fps/length as src).
usage: camseg.py src.mp4 cx cy cw ch out_mask.mp4"""
import sys, subprocess, numpy as np, mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
src, cx, cy, cw, ch, out = sys.argv[1], *map(int, sys.argv[2:6]), sys.argv[6]
fps = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", src]).decode().strip()
rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"crop={cw}:{ch}:{cx}:{cy}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{cw}x{ch}", "-r", fps, "-i", "-",
                       "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
    base_options=mpt.BaseOptions(model_asset_path="/root/.claude/skills/effects/models/selfie_segmenter.tflite"), output_confidence_masks=True))
n = cw * ch * 3; prev = None
while True:
    b = rd.stdout.read(n)
    if len(b) < n: break
    f = np.frombuffer(b, np.uint8).reshape(ch, cw, 3)
    m = np.squeeze(seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(f))).confidence_masks[0].numpy_view())
    m = np.clip((m - 0.3) / 0.4, 0, 1)
    prev = m if prev is None else 0.6 * m + 0.4 * prev   # light temporal smoothing against flicker
    wr.stdin.write((prev * 255).astype(np.uint8).tobytes())
wr.stdin.close(); wr.wait(); print("mask done", out)
