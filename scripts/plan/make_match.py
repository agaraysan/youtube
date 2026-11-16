#!/usr/bin/env python3
"""マッチ棒クイズ（1本10問）の台本 episodes/<id>.json を作る。

使い方: make_match.py <id> [問題数=10] [seed]
- 1本動かす答えが1通りしかない式だけを使う。前半はやさしく（1けた）、後半は2けたを混ぜる。
- 出した問題は data/used_match.json に記録し、別の回で同じ式を使わない。
"""
import json, pathlib, random, sys, itertools
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "render"))
import matchstick as M

ROOT = pathlib.Path(__file__).resolve().parents[2]
USED = ROOT / "data" / "used_match.json"
READ = {"+": "たす", "-": "ひく", "=": "は"}
BGS = ["assets/generated/t002_bg_match_desk/background.png"] + sorted(
    str(p.relative_to(ROOT)) for p in ROOT.glob("assets/generated/bg_match_*/image.png"))


def say(expr):
    return "".join(READ.get(c, c) for c in expr)


def candidates():
    out = []
    for a, b in itertools.product(range(10), range(10)):
        for op in "+-":
            for c in list(range(10)) + list(range(10, 20)):
                e = f"{a}{op}{b}={c}"
                if M.evaluate(e):
                    continue
                sols = M.one_move_solutions(e)
                answers = {s[0] for s in sols}
                if len(answers) == 1:
                    sol = sorted(sols)[0]
                    out.append((e, sol, len(e)))
    return out


def explain(q, sol):
    new, i, s, j, t = sol
    if i == j:
        return f"「{q[i]}」の1本を動かして「{new[i]}」にする"
    return f"「{q[i]}」から1本とって「{new[i]}」、「{q[j]}」に足して「{new[j]}」"


def main(eid, n=10, seed=None):
    rng = random.Random(seed if seed is not None else eid)
    used = set(json.loads(USED.read_text())) if USED.exists() else set()
    cand = [c for c in candidates() if c[0] not in used]
    easy = [c for c in cand if c[2] == 5]
    hard = [c for c in cand if c[2] == 6]
    rng.shuffle(easy); rng.shuffle(hard)
    picks = easy[: n - n * 3 // 10] + hard[: n * 3 // 10]
    scenes = [{"type": "title", "text": "マッチ棒クイズ", "sub": f"全{n}問　1本だけ動かして正しい式に",
               "voice": f"マッチ棒クイズ、全{n}問です。マッチ棒を1本だけ動かして、正しい式にしてください。後半ほど難しくなります。"}]
    for k, (q, sol, _) in enumerate(picks, 1):
        new = sol[0]
        pz = {"question": q, "answer": new, "move": list(sol)}
        scenes += [
            {"type": "match", "puzzle": pz, "state": "question", "text": f"第{k}問", "voice": f"第{k}問。", "pad": 0.4},
            {"type": "think", "puzzle": pz, "text": f"第{k}問", "seconds": 10 if k <= 7 else 12},
            {"type": "match", "puzzle": pz, "state": "move", "text": "正解", "caption": explain(q, sol), "chime": True,
             "voice": "正解は、こちら。", "voice_delay": 0.2, "pad": 0.6},
            {"type": "match", "puzzle": pz, "state": "move2", "text": "正解", "caption": f"{new.replace('-', '−')}",
             "voice": f"{say(new)}。", "voice_delay": 0.1, "pad": 0.8},
        ]
    scenes.append({"type": "title", "text": "何問解けた？", "sub": "コメントで教えてください",
                   "voice": "何問解けましたか？コメントで教えてください。チャンネル登録もよろしくお願いします。"})
    ep = {"id": eid, "series": "マッチ棒クイズ", "style": "match", "bg": rng.choice(BGS), "scenes": scenes,
          "meta": {"genre": "match", "questions": [p[0] for p in picks]}}
    (ROOT / "episodes" / f"{eid}.json").write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
    USED.parent.mkdir(exist_ok=True)
    USED.write_text(json.dumps(sorted(used | {p[0] for p in picks}), ensure_ascii=False))
    print(eid, [p[0] + "→" + p[1][0] for p in picks])


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10, int(sys.argv[3]) if len(sys.argv) > 3 else None)
