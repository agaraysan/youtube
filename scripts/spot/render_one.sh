#!/bin/bash
# 間違い探し1本ぶんを描画する。台本・描画コード・使う絵が変わったときだけ作り直す。
# spot/episodes/*.json は横長の本編（spot.py → pv/out）、spot/shorts/*.json は縦のショート（short.py → pv/out/shorts）。
f="$1"; id=$(basename "$f" .json)
case "$f" in
  spot/shorts/*) prog=scripts/spot/short.py; out=pv/out/shorts; code="scripts/spot/spot.py scripts/spot/short.py" ;;
  *) prog=scripts/spot/spot.py; out=pv/out; code="scripts/spot/spot.py" ;;
esac
mkdir -p "$out"
pics=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(' '.join(d.get('pictures') or [d['picture']]))" "$f")
# 本編の hash は投稿用の文と names を除いて取る（文を直しても作り直さない。文は下で毎回書き直す）
h=$( (python3 -c "import json,sys;d=json.load(open(sys.argv[1]));[d.pop(k,None) for k in ('upload','names')];print(json.dumps(d,sort_keys=True))" "$f"; cat $code scripts/render/render.py scripts/render/spotcheck.py; for p in $pics; do cat assets/generated/$p/a.png assets/generated/$p/b.png assets/generated/$p/differences.json 2>/dev/null; done) | sha1sum | cut -c1-12)
if [ -f "$out/$id.hash" ] && [ "$(cat $out/$id.hash)" = "$h" ]; then
  python3 scripts/spot/write_text.py "$f" "$out"; echo "skip $id"; exit 0
fi
if python3 "$prog" "$f" "$out" > "pv/log_$id.txt" 2>&1; then echo "$h" > "$out/$id.hash"; echo "done $id"; tail -1 "pv/log_$id.txt"; else echo "FAILED $id"; tail -5 "pv/log_$id.txt"; fi
