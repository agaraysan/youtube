#!/bin/bash
# 1本ぶんを描画する。台本・使う絵・RENDER_VERSION が変わったときだけ作り直す（声のAPI代と時間の節約）。
# 見た目を全部の動画で変えたいときだけ scripts/brain/RENDER_VERSION の数字を上げる。
# 新しい場面の型を足すだけなら上げない（既存の動画は作り直さない）。
# brain/episodes/*.json は横長の本編（brain.py）、brain/shorts/*.json は縦のショート（shorts.py → pv/out/shorts/）。
f="$1"; id=$(basename "$f" .json)
case "$f" in
  brain/shorts/*) prog=scripts/brain/shorts.py; out=pv/out/shorts ;;
  *) prog=scripts/brain/brain.py; out=pv/out ;;
esac
mkdir -p "$out"
imgs=$(python3 scripts/brain/assets_of.py "$f" 2>/dev/null)
h=$( (cat "$f" scripts/brain/RENDER_VERSION scripts/render/*.py; echo "$imgs") | sha1sum | cut -c1-12)
old=$(cat "$out/$id.hash" 2>/dev/null)
if [ "$old" = "$h" ]; then echo "skip $id"; exit 0; fi
if python3 "$prog" "$f" "$out" > "pv/log_$id.txt" 2>&1; then echo "$h" > "$out/$id.hash"; echo "done $id"; else echo "FAILED $id: $(tail -1 pv/log_$id.txt)"; fi
