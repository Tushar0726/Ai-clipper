#!/bin/bash
# Split one rendered clip into 18 MB parts (+ a thumbnail) so it can be uploaded to a
# claude.ai download page (asset limit 20 MiB per file, 1 GB per page).
#
# usage: RUN=<run folder> [CLIPDIR=clips_4k] [OUT=<parts dir>] web/prep.sh <clip number>
# prints the clip length/size and the part files; parts land in $OUT/c<NN>/
set -euo pipefail
N=$(printf "%02d" "$1")
RUN=${RUN:?set RUN to the run folder, e.g. ~/GTA6-Clips/2026-11-23-streamer-master}
CD=${CLIPDIR:-clips_4k}
OUT=${OUT:-$HOME/clip-parts}
F=$(ls "$RUN/$CD"/clip_${N}_*.mp4)
D=$OUT/c$N
rm -rf "$D"; mkdir -p "$D"
split -b 18000000 -d -a 2 "$F" "$D/part"
for p in "$D"/part??; do mv "$p" "$p.mp4"; done
d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$F")
ffmpeg -v error -y -ss "$(python3 -c "print(min(20,$d/2))")" -i "$F" -frames:v 1 -vf scale=540:-2 -q:v 4 "$D/thumb.jpg"
echo "len=$(python3 -c "print(round($d))") sizeMB=$(( $(stat -c%s "$F") / 1000000 )) dir=$D"
ls "$D" | tr '\n' ' '; echo
