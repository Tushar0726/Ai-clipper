#!/usr/bin/env bash
# Periodic health check for the shorts queue: status, disk, failures, short clips,
# a frame strip of not-yet-reviewed clips, and a FINAL/ refresh.
cd "$(dirname "$0")/.." || exit 1
REVIEWED="${REVIEWED:-/tmp/claude-0/-home-user-Ai-clipper/ee5890a5-bfaf-5952-be6d-2f62d7ecb2ff/scratchpad/sent2.txt}"
STRIP="${STRIP:-/tmp/claude-0/-home-user-Ai-clipper/ee5890a5-bfaf-5952-be6d-2f62d7ecb2ff/scratchpad/check.png}"
touch "$REVIEWED"
if pgrep -f batch/make_all.py >/dev/null; then echo "queue: RUNNING"; else echo "queue: STOPPED"; fi
tail -1 output/make_all.log | grep -q DONE && echo "queue: DONE"
df -h / | tail -1 | awk '{print "disk avail: " $4}'
echo "fails: $(grep -c '^FAIL' output/make_all.log)  last: $(grep '^FAIL' output/make_all.log | tail -1 | cut -c1-80)"
n=0; short=""; new=""
for f in output/n3on_shorts/*.mp4 output/carry_shorts/*.mp4; do
  [ -f "$f" ] || continue
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null) || continue
  [ -n "$d" ] || continue
  n=$((n+1))
  awk "BEGIN{exit !($d < 8)}" && short="$short $(basename "$f"):$d"
  grep -qxF "$(basename "$f")" "$REVIEWED" || new="$new $f"
done
echo "finished: $n  carry: $(ls output/carry_shorts/*.mp4 2>/dev/null | wc -l)  n3on: $(ls output/n3on_shorts/*.mp4 2>/dev/null | wc -l)"
[ -n "$short" ] && echo "SHORT:$short"
echo "NEW:$new"
tmp=$(mktemp -d); i=0
for f in $new; do for t in 4 12 22; do i=$((i+1)); ffmpeg -nostdin -y -loglevel error -ss $t -i "$f" -frames:v 1 -vf scale=160:-2 "$tmp/$(printf %03d $i).png" 2>/dev/null; done; done
k=$(ls "$tmp"/*.png 2>/dev/null | wc -l)
if [ "$k" -gt 0 ]; then ffmpeg -y -loglevel error $(for p in $(ls "$tmp"/*.png | sort); do echo -n "-i $p "; done) -filter_complex hstack=$k "$STRIP" && echo "strip: $STRIP ($k frames)"; fi
rm -rf "$tmp"
python3 batch/package.py 2>/dev/null | grep FINAL
