#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$ROOT/frames"
AUDIO="$ROOT/audio"
WORK="$ROOT/work"
OUTPUT="$ROOT/EchoMind_Demo.mp4"

mkdir -p "$WORK"

for number in 01 02 03 04 05 06 07 08; do
  frame="$(find "$FRAMES" -name "${number}-*.png" -print -quit)"
  narration="$AUDIO/${number}.aiff"
  duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration")"
  video_duration="$(awk -v duration="$duration" 'BEGIN { printf "%.3f", duration + 1.0 }')"

  ffmpeg -y -hide_banner -loglevel error \
    -loop 1 -framerate 30 -i "$frame" \
    -i "$narration" \
    -filter_complex \
    "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=20:3[background]; \
     [0:v]scale=1280:720:force_original_aspect_ratio=decrease[foreground]; \
     [background][foreground]overlay=(W-w)/2:(H-h)/2,fade=t=in:st=0:d=0.35,fade=t=out:st=$(awk -v d="$video_duration" 'BEGIN { printf "%.3f", d - 0.35 }'):d=0.35,format=yuv420p[video]; \
     [1:a]afade=t=in:st=0:d=0.2,apad=pad_dur=1[audio]" \
    -map "[video]" -map "[audio]" \
    -t "$video_duration" \
    -c:v libx264 -preset medium -crf 20 \
    -c:a aac -b:a 160k \
    -movflags +faststart \
    "$WORK/${number}.mp4"
done

: > "$WORK/concat.txt"
for number in 01 02 03 04 05 06 07 08; do
  printf "file '%s/%s.mp4'\n" "$WORK" "$number" >> "$WORK/concat.txt"
done

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$WORK/concat.txt" \
  -c copy -movflags +faststart "$OUTPUT"

echo "$OUTPUT"
