#!/usr/bin/env python3
"""なぞなぞ（1本10問）の台本 episodes/<id>.json を data/riddles.json から作る。

使い方: make_riddle.py <id> [問題数=10]
出した問題は data/used_riddles.json に記録し、別の回で使わない。
"""
import json, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANK = ROOT / "data" / "riddles.json"
USED = ROOT / "data" / "used_riddles.json"
BG = "assets/generated/t003_bg_riddle_library/image.png"


def main(eid, n=10):
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    used = set(json.loads(USED.read_text())) if USED.exists() else set()
    pool = [r for r in bank if r["q"] not in used]
    if len(pool) < n:
        raise SystemExit(f"なぞなぞの在庫が足りない（残り {len(pool)}）")
    random.Random(eid).shuffle(pool)
    picks = pool[:n]
    scenes = [{"type": "title", "text": "なぞなぞ", "sub": f"全{n}問　ひらめきで答えよう",
               "voice": f"なぞなぞ、全{n}問です。ひらめきで答えてください。"}]
    for k, r in enumerate(picks, 1):
        q = r["q"]
        shown = q.replace("、", "、\n") if len(q) > 18 else q  # 読点で改行して読みやすく
        scenes += [
            {"type": "riddle", "text": f"第{k}問", "riddle": shown, "voice": f"第{k}問。{q}", "pad": 0.5},
            {"type": "think", "text": f"第{k}問", "riddle": shown, "seconds": 7},
            {"type": "riddle", "text": f"第{k}問", "answer": r["a"], "caption": r.get("why") or None, "chime": True,
             "voice": f"答えは、{r['a']}。" + (f"{r['why']}。" if r.get("why") else ""), "voice_delay": 0.3, "pad": 0.7},
        ]
    scenes.append({"type": "title", "text": "何問わかった？", "sub": "コメントで教えてください",
                   "voice": "何問わかりましたか？コメントで教えてください。チャンネル登録もよろしくお願いします。"})
    for s in scenes:
        if s.get("caption") is None:
            s.pop("caption", None)
    ep = {"id": eid, "series": "なぞなぞ", "style": "riddle", "bg": BG, "scenes": scenes,
          "meta": {"genre": "riddle", "questions": [r["q"] for r in picks]}}
    (ROOT / "episodes" / f"{eid}.json").write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
    USED.write_text(json.dumps(sorted(used | {r["q"] for r in picks}), ensure_ascii=False))
    print(eid, [r["a"] for r in picks])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10)
