#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
AUDIO="/Users/aakarshita/Downloads/ElevenLabs_2026-06-06T19_08_44_Elise – Warm, Natural and Engaging_pvc_sp100_s50_sb75_se88_b_m2.mp3"
OUTPUT="$ROOT/EchoMind_Moving_Demo_ElevenLabs_1080p.mp4"

ffmpeg -y -hide_banner -loglevel error \
  -framerate 8 \
  -i "$ROOT/frames/%05d.jpg" \
  -i "$AUDIO" \
  -filter_complex \
  "[0:v]fps=30,scale=1920:1080:flags=lanczos,format=yuv420p[v]; \
   [1:a]highpass=f=80,lowpass=f=14000,acompressor=threshold=-18dB:ratio=1.6:attack=15:release=180,loudnorm=I=-16:TP=-1.5:LRA=8[a]" \
  -map "[v]" -map "[a]" \
  -shortest \
  -c:v libx264 -preset slow -crf 17 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$OUTPUT"

echo "$OUTPUT"
