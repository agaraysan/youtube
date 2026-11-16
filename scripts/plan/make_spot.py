#!/usr/bin/env python3
"""間違い探し（1本に複数問）の台本 episodes/<id>.json を作る。

使い方: make_spot.py <id> <タイトルの副題> <絵のid> [<絵のid> ...]
絵のid は assets/generated/<絵のid>/（a.png, b.png, differences.json, result.json が ok のもの）。
自動チェック（spotcheck）に通らない絵は飛ばす。
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "render"))
import spotcheck

ROOT = pathlib.Path(__file__).resolve().parents[2]
NUM = "1つめ 2つめ 3つめ 4つめ 5つめ 6つめ 7つめ".split()


def short(desc, n=16):
    d = desc.rstrip("。")
    return d if len(d) <= n else d[: n - 1] + "…"


def main(eid, sub, ids, think=30):
    scenes, used = [], []
    for gid in ids:
        g = ROOT / "assets" / "generated" / gid
        res = json.loads((g / "result.json").read_text()) if (g / "result.json").exists() else {}
        if res.get("status") != "ok":
            print("skip", gid, res.get("status")); continue
        ok, msg, diffs = spotcheck.check(g / "a.png", g / "b.png", g / "differences.json")
        if not ok:
            print("skip", gid, msg); continue
        used.append((gid, diffs))
    if not used:
        raise SystemExit("使える絵がない")
    n = len(used)
    first = used[0][0]
    scenes.append({"type": "title", "text": "間違い探し", "sub": sub, "bg": f"assets/generated/{first}/a.png",
                   "voice": f"間違い探し、全{n}問です。左と右の絵の違いを見つけてください。"})
    for k, (gid, diffs) in enumerate(used, 1):
        A, B = f"assets/generated/{gid}/a.png", f"assets/generated/{gid}/b.png"
        m = len(diffs)
        scenes.append({"type": "think", "images": [A, B], "text": f"第{k}問  違いは{m}つ", "seconds": think,
                       "spot": gid, "voice": f"第{k}問。違いは{m}つです。", "voice_delay": 0.2})
        for j, d in enumerate(diffs):
            scenes.append({"type": "reveal", "images": [A, B], "index": j, "spot": gid,
                           "text": f"{NUM[j]}  {short(d['note'])}", "voice": f"{NUM[j]}。{d['note'].rstrip('。')}。",
                           "voice_delay": 0.15, "pad": 0.4, "hold_full": 0.5, "chime": True})
    scenes.append({"type": "title", "text": "全部見つけられた？", "sub": "コメントで教えてください", "bg": f"assets/generated/{used[-1][0]}/a.png",
                   "voice": "全部見つけられましたか？コメントで教えてください。チャンネル登録もよろしくお願いします。"})
    ep = {"id": eid, "series": "間違い探し", "style": "spot", "bg": f"assets/generated/{first}/a.png",
          "spots": {gid: {"a": f"assets/generated/{gid}/a.png", "b": f"assets/generated/{gid}/b.png",
                          "list": f"assets/generated/{gid}/differences.json"} for gid, _ in used},
          "scenes": scenes, "meta": {"genre": "spot", "pictures": [g for g, _ in used]}}
    (ROOT / "episodes" / f"{eid}.json").write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(eid, n, "問")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
