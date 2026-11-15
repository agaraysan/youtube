#!/usr/bin/env bash
# 動くGIFを、動画の1場面として使える MP4 にする。使い方: gif_to_mp4.sh in.gif out.mp4 [秒数] [幅x高さ]
set -euo pipefail
in=$1; out=$2; sec=${3:-0}; size=${4:-1920x1080}
w=${size%x*}; h=${size#*x}
loop=(); [ "$sec" != 0 ] && loop=(-stream_loop -1 -t "$sec")
ffmpeg -y -loglevel error "${loop[@]}" -i "$in" \
  -vf "scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p" \
  -c:v libx264 -crf 18 -movflags +faststart -an "$out"
