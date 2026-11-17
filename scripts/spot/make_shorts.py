#!/usr/bin/env python3
"""本編の台本（spot/episodes/<id>.json）から、1問ずつのショート台本 spot/shorts/<id>_sNN.json を作る。
本編の "names"（各問の場面の短い名前）をタイトルに使う。
使い方: make_shorts.py <本編のid> [...]"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for eid in sys.argv[1:]:
    ep = json.loads((ROOT / "spot" / "episodes" / f"{eid}.json").read_text(encoding="utf-8"))
    names = ep.get("names") or [""] * len(ep["pictures"])
    for k, (pic, name) in enumerate(zip(ep["pictures"], names), 1):
        sid = f"{eid}_s{k:02d}"
        season = ep["title"].replace("の間違い探し", "")
        sh = {"id": sid, "picture": pic, "think": 15, "bgm": ep.get("bgm", "little_fish"),
              "upload": {"title": f"【間違い探し】{name}｜違いは5つ、15秒でわかる？ #shorts",
                         "description": f"上と下の絵の違いを5つ見つけてください。（{name}）\n"
                                        f"本編「{ep['title']}」は全{len(ep['pictures'])}問。チャンネルからどうぞ。\n\n"
                                        "絵と声はAIで作っています。BGM：YouTube オーディオライブラリ\n\n"
                                        f"#間違い探し #脳トレ #頭の体操 #{season} #shorts",
                         "tags": ["間違い探し", "脳トレ", "頭の体操", season, "shorts"]}}
        (ROOT / "spot" / "shorts" / f"{sid}.json").write_text(json.dumps(sh, ensure_ascii=False, indent=1), encoding="utf-8")
        print(sid)
