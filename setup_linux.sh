#!/usr/bin/env bash
# One-time setup of the clipper on a Linux cloud session (Claude Code on the web).
# Installs the gta6-clipper skills + our editing scripts into ~/.claude/skills and everything they need:
# ffmpeg, deno, a Python venv (yt-dlp, OpenCV, Pillow, numpy), whisper.cpp (built from source),
# Whisper models (English + multilingual), the YuNet face detector and a heavy caption font.
# Safe to re-run. Takes ~10-15 min the first time (mostly the whisper build + model download).
set -uo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
SK="$HOME/.claude/skills"
S="$SK/gta6-clipper"
BUILD="${TMPDIR:-/tmp}/clipper-build"
ok()   { printf "  [ok]   %s\n" "$1"; }
fail() { printf "  [FAIL] %s\n" "$1"; FAILED=1; }
FAILED=0
echo "Clipper setup (Linux)"

# 1. skills + scripts
mkdir -p "$SK"
cp -R "$REPO/skills/gta6-clipper" "$REPO/skills/gta6-live-clipper" "$SK/" && ok "skills copied to $SK"
mkdir -p "$S/models" "$BUILD"

# 2. ffmpeg
if command -v ffmpeg >/dev/null; then ok "ffmpeg"; else
  (apt-get update -qq && apt-get install -y -qq ffmpeg) >/dev/null 2>&1 && ok "ffmpeg installed" || fail "ffmpeg"; fi

# 3. deno (yt-dlp needs a JS runtime for YouTube)
if command -v deno >/dev/null; then ok "deno"; else
  (curl -fsSL https://deno.land/install.sh | sh -s -- -y >/dev/null 2>&1 && ln -sf "$HOME/.deno/bin/deno" /usr/local/bin/deno) \
    && ok "deno installed" || fail "deno"; fi

# 4. Python venv
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; UV="$HOME/.local/bin/uv"; fi
[ -x "$S/.venv/bin/python" ] || "$UV" venv --python 3.12 "$S/.venv" -q
"$UV" pip install --python "$S/.venv/bin/python" -q -U "yt-dlp[default]" opencv-python-headless pillow numpy \
  && ok "python packages" || fail "python packages"

# 5. whisper.cpp (speech to text)
if command -v whisper-cli >/dev/null; then ok "whisper-cli"; else
  (cd "$BUILD" && rm -rf whisper.cpp && git clone -q --depth 1 https://github.com/ggml-org/whisper.cpp && cd whisper.cpp \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release >/dev/null && cmake --build build -j"$(nproc)" --target whisper-cli >/dev/null 2>&1 \
    && ln -sf "$PWD/build/bin/whisper-cli" /usr/local/bin/whisper-cli) && ok "whisper-cli built" || fail "whisper-cli"; fi

# 6. models
dl() { [ -s "$2" ] || curl -fsSL -o "$2" "$1"; [ -s "$2" ] && ok "$(basename "$2")" || fail "$(basename "$2")"; }
dl https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin "$S/models/ggml-small.en.bin"
dl https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin "$S/models/ggml-small.bin"
dl https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
   "$S/models/face_detection_yunet_2023mar.onnx"

# 7. caption font: the skill looks for Arial Black (macOS path); link a heavy free font there
F=$(ls /usr/share/fonts/opentype/inter/Inter-Black.otf /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf 2>/dev/null | head -1)
mkdir -p "/System/Library/Fonts/Supplemental" && ln -sf "$F" "/System/Library/Fonts/Supplemental/Arial Black.ttf" && ok "caption font ($F)"

# 8. config + ready flag (English model by default; switch whisper_model to ggml-small.bin for Hindi/other languages)
echo "{\"whisper_model\": \"$S/models/ggml-small.en.bin\", \"yunet_model\": \"$S/models/face_detection_yunet_2023mar.onnx\"}" > "$S/config.json"
if [ $FAILED -eq 0 ]; then date > "$S/.ready"; echo; echo "READY"; else echo; echo "NOT READY: fix the [FAIL] lines and re-run"; exit 1; fi
