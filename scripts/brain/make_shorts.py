#!/usr/bin/env python3
"""長い動画の台本（brain/episodes）から、1問ずつのショートの台本（brain/shorts）を作る。
使い方: make_shorts.py <episode_id>:<問題番号>[,<問題番号>...] ...
例:     make_shorts.py brain_kanji_odd_001:4,9 brain_color_word_001:3"""
import json, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
EP, OUT = ROOT / "brain" / "episodes", ROOT / "brain" / "shorts"


def questions(ep):
    """問題番号 → (問題の場面, 答えの場面)"""
    qs = {}
    for sc in ep["scenes"]:
        t = sc.get("text", "")
        if not t.startswith("第") or "問" not in t:
            continue
        n = int(t[1:t.index("問")])
        if sc.get("reveal") or (sc.get("chime") and sc["type"] == "grid"):
            qs.setdefault(n, [None, None])[1] = qs.get(n, [None, None])[1] or sc
        elif not sc.get("think") and "由来" not in t:
            qs.setdefault(n, [None, None])[0] = qs.get(n, [None, None])[0] or sc
    return qs


def make(ep, n):
    q, a = questions(ep)[n]
    sid = f"{ep['id']}_q{n:02d}"
    base = {"id": sid, "series": ep.get("series", "頭の体操"), "style": ep["style"], "think": 6}
    if q["type"] == "grid" and "base" in q:
        rnd = random.Random(sid)
        base.update(kind="grid", base=q["base"], odd=q["odd"], rows=8, cols=6, pos=[rnd.randrange(1, 7), rnd.randrange(1, 5)],
                    q="1つだけちがう漢字は？", voice_q="1つだけちがう漢字、見つけられる？", voice_a="正解は、ここ！",
                    answer_note=a.get("caption", "ここ！"), think=7)
        return base
    if q["type"] != "choice":
        return None
    opts, c = q["options"], q["correct"]
    base.update(kind="choice", options=opts, correct=c)
    for k in ("big", "emoji", "big_color", "big_answer"):
        if q.get(k):
            base[k] = q[k]
    st = ep["style"]
    ans = opts[c]
    if st == "color":
        base.update(q="文字の「色」を答えて！", voice_q="文字の色は？読んじゃだめ！", voice_a=f"正解は、{ans}！", answer_note=f"正解は「{ans}」", think=4)
    elif q.get("emoji"):
        base.update(q="このかげ、なんだ？", voice_q="このかげ、なんだかわかる？", voice_a=f"正解は、{ans}！", answer_note=f"正解は「{ans}」", think=5)
    elif st in ("fish", "veg"):
        base.update(q="この漢字、読める？", voice_q="この漢字、読めるかな？", voice_a=f"正解は、{ans}！", answer_note=f"正解は「{ans}」")
    elif st in ("yoji", "proverb"):
        word = "漢字" if st == "yoji" else "言葉"
        base.update(q=f"□に入る{word}は？", voice_q=f"四角に入る{word}は、どれ？", voice_a=f"正解は、{q.get('ruby', ans)}！",
                    answer_note=f"正解：{q.get('big_answer', ans)}")
    else:
        base.update(q=q.get("q", "答えはどれ？"), voice_q=q.get("q", "答えはどれ？").replace("□", "四角"), voice_a=f"正解は、{ans}！",
                    answer_note=f"正解は「{ans}」")
    return base


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        eid, nums = arg.split(":")
        ep = json.loads((EP / f"{eid}.json").read_text(encoding="utf-8"))
        for n in map(int, nums.split(",")):
            s = make(ep, n)
            if s:
                (OUT / f"{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
                print("made", s["id"])
