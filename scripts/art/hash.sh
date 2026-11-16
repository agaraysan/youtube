#!/bin/bash
# 試作1本の「作り直しが要るか」の目印。仕様と、その種類で使うスクリプトだけから作る。
f="$1"; d=$(dirname "$0")
t=$(jq -r .type "$f")
case "$t" in zoom) m="zoom_chain.py zoom_render.py";; *) m="$t.py";; esac
(cd "$d" && cat common.py ambient.py run.py $m) | cat "$f" - | sha1sum | cut -c1-12
