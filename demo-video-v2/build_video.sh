#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FRAMES="$ROOT/frames"
AUDIO="$ROOT/audio"
WORK="$ROOT/work"
OUTPUT="$ROOT/EchoMind_Founder_Demo.mp4"

mkdir -p "$WORK"

for number in 01 02 03 04 05 06 07; do
  frame="$(find "$FRAMES" -name "${number}-*.png" -print -quit)"
  narration="$AUDIO/${number}.aiff"
  duration="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$narration")"
  video_duration="$(awk -v duration="$duration" 'BEGIN { printf "%.3f", duration + 0.8 }')"
  frames="$(awk -v duration="$video_duration" 'BEGIN { printf "%d", duration * 30 }')"
  fade_out="$(awk -v duration="$video_duration" 'BEGIN { printf "%.3f", duration - 0.3 }')"

  if (( 10#$number % 2 == 0 )); then
    zoom="if(lte(zoom,1.0),1.06,max(1.0,zoom-0.00022))"
  else
    zoom="min(zoom+0.00022,1.06)"
  fi

  ffmpeg -y -hide_banner -loglevel error \
    -loop 1 -framerate 30 -i "$frame" \
    -i "$narration" \
    -filter_complex \
    "[0:v]scale=1344:756:force_original_aspect_ratio=increase,crop=1344:756,zoompan=z='${zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=1280x720:fps=30,fade=t=in:st=0:d=0.3,fade=t=out:st=${fade_out}:d=0.3,format=yuv420p[video]; \
     [1:a]highpass=f=80,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2.2:attack=15:release=180,loudnorm=I=-16:TP=-1.5:LRA=8,afade=t=in:st=0:d=0.12,apad=pad_dur=0.8[audio]" \
    -map "[video]" -map "[audio]" \
    -t "$video_duration" \
    -c:v libx264 -preset medium -crf 18 \
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
