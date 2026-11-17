#!/bin/bash
# 間違い探し1本ぶんを描画する。台本・描画コード・使う絵が変わったときだけ作り直す。
f="$1"; id=$(basename "$f" .json); out=pv/out
mkdir -p "$out"
pics=$(python3 -c "import json,sys;print(' '.join(json.load(open(sys.argv[1]))['pictures']))" "$f")
h=$( (cat "$f" scripts/spot/*.py scripts/render/render.py scripts/render/spotcheck.py; for p in $pics; do cat assets/generated/$p/a.png assets/generated/$p/b.png assets/generated/$p/differences.json 2>/dev/null; done) | sha1sum | cut -c1-12)
if [ -f "$out/$id.hash" ] && [ "$(cat $out/$id.hash)" = "$h" ]; then echo "skip $id"; exit 0; fi
if python3 scripts/spot/spot.py "$f" "$out" > "pv/log_$id.txt" 2>&1; then echo "$h" > "$out/$id.hash"; echo "done $id"; tail -1 "pv/log_$id.txt"; else echo "FAILED $id"; tail -5 "pv/log_$id.txt"; fi
