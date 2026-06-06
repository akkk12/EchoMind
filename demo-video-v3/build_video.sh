#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$ROOT/frames"
AUDIO="$ROOT/audio"
WORK="$ROOT/work"
OUTPUT="$ROOT/EchoMind_Founder_Demo_1080p.mp4"

mkdir -p "$WORK"

for number in 01 02 03 04 05 06 07; do
  frame="$(find "$FRAMES" -name "${number}-*.png" -print -quit)"
  narration="$AUDIO/${number}.aiff"
  duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration")"
  video_duration="$(awk -v duration="$duration" 'BEGIN { printf "%.3f", duration + 0.65 }')"
  fade_out="$(awk -v duration="$video_duration" 'BEGIN { printf "%.3f", duration - 0.25 }')"

  ffmpeg -y -hide_banner -loglevel error \
    -loop 1 -framerate 30 -i "$frame" \
    -i "$narration" \
    -filter_complex \
    "[0:v]scale=1920:1080:flags=lanczos,fade=t=in:st=0:d=0.25,fade=t=out:st=${fade_out}:d=0.25,format=yuv420p[video]; \
     [1:a]highpass=f=80,lowpass=f=11500,acompressor=threshold=-20dB:ratio=1.8:attack=20:release=220,loudnorm=I=-16:TP=-1.5:LRA=7,afade=t=in:st=0:d=0.1,apad=pad_dur=0.65[audio]" \
    -map "[video]" -map "[audio]" \
    -t "$video_duration" \
    -c:v libx264 -preset slow -crf 16 \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$WORK/${number}.mp4"
done

: > "$WORK/concat.txt"
for number in 01 02 03 04 05 06 07; do
  printf "file '%s/%s.mp4'\n" "$WORK" "$number" >> "$WORK/concat.txt"
done

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$WORK/concat.txt" \
  -c copy -movflags +faststart "$OUTPUT"

echo "$OUTPUT"
