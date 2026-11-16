#!/usr/bin/env python3
"""エピソードが使う絵の一覧（ファイル名と大きさ）を出す。絵が届いたら作り直すための目印。"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ep = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
paths = {ep.get("bg")} | {sc.get(k) for sc in ep["scenes"] for k in ("image", "bg")}
for p in sorted(x for x in paths if x):
    q = ROOT / p
    files = sorted(q.iterdir()) if q.is_dir() else [q]
    for f in files:
        if f.exists() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            print(f.relative_to(ROOT), f.stat().st_size)
