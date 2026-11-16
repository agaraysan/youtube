#!/bin/bash
# 1本ぶんを描画する。台本・描画コード・使う絵が変わったときだけ作り直す（声のAPI代の節約）。
f="$1"; id=$(basename "$f" .json)
imgs=$(python3 scripts/brain/assets_of.py "$f")
h=$( (cat "$f" scripts/brain/*.py scripts/render/*.py; echo "$imgs") | sha1sum | cut -c1-12)
if [ -f "pv/out/$id.hash" ] && [ "$(cat pv/out/$id.hash)" = "$h" ]; then echo "skip $id"; exit 0; fi
if python3 scripts/brain/brain.py "$f" pv/out > "pv/log_$id.txt" 2>&1; then echo "$h" > "pv/out/$id.hash"; echo "done $id"; else echo "FAILED $id: $(tail -1 pv/log_$id.txt)"; fi
