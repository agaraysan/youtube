#!/usr/bin/env python3
"""ことば探しの台本を作る。言葉を表にたて・よこ（左→右、上→下だけ）で置き、残りをひらがなでうめる。
どの言葉も表の中にちょうど1回だけ出るように確かめる（たまたま同じ言葉ができたら作り直す）。
使い方: make_wordsearch.py <id> <型の番号> （中の THEMES を使う）"""
import json, random, sys, pathlib

KANA = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわん" \
       "がぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽ"


def count(rows, w):
    n = 0
    R, C = len(rows), len(rows[0])
    for r in range(R):
        n += "".join(rows[r]).count(w)
    for c in range(C):
        n += "".join(rows[r][c] for r in range(R)).count(w)
    return n


def build(words, size, seed):
    rnd = random.Random(seed)
    for _ in range(4000):
        g = [[None] * size for _ in range(size)]
        place, ok = [], True
        for k, w in enumerate(sorted(words, key=len, reverse=True)):
            for _ in range(300):
                d = rnd.choice("hv")
                r = rnd.randrange(size - (len(w) if d == "v" else 1) + 1)
                c = rnd.randrange(size - (len(w) if d == "h" else 1) + 1)
                cells = [(r + (i if d == "v" else 0), c + (i if d == "h" else 0)) for i in range(len(w))]
                if all(g[a][b] in (None, w[i]) for i, (a, b) in enumerate(cells)) and sum(g[a][b] is not None for a, b in cells) <= 1:
                    for i, (a, b) in enumerate(cells):
                        g[a][b] = w[i]
                    place.append({"w": w, "r": r, "c": c, "d": d})
                    break
            else:
                ok = False
                break
        if not ok:
            continue
        # たて・よこ半々くらいに
        nh = sum(p["d"] == "h" for p in place)
        if not (1 <= nh <= len(words) - 1):
            continue
        for r in range(size):
            for c in range(size):
                if g[r][c] is None:
                    g[r][c] = rnd.choice(KANA)
        if all(count(g, w) == 1 for w in words):
            order = {w: i for i, w in enumerate(words)}
            place.sort(key=lambda p: order[p["w"]])
            return ["".join(row) for row in g], place
    raise SystemExit(f"置けませんでした: {words}")


THEMES = {
    1: [  # (テーマ, 声で読むテーマ, 言葉, 答えのあとの一言)
        ("冬の食べもの", "ふゆの、たべもの", ["みかん", "おでん", "おもち", "やきいも", "ぞうに"], "やきいもは、えどじだいの、おわりごろから、ふゆのまちで、うられるようになったそうです。"),
        ("春の花", "はるの、はな", ["さくら", "うめ", "つばき", "なのはな", "たんぽぽ"], "うめは、さくらよりさきにさいて、はるをしらせる、はなとして、したしまれてきました。"),
        ("台所の道具", "だいどころの、どうぐ", ["なべ", "やかん", "おたま", "まないた", "ほうちょう"], "おたまは、おたまじゃくしを、みじかくした、よびかたです。カエルのこどもの、おたまじゃくしは、このどうぐに、かたちがにているので、そうよばれるようになったと、いわれています。"),
        ("野菜", "やさい", ["だいこん", "にんじん", "ごぼう", "かぶ", "ねぎ", "なす"], "ごぼうを、やさいとして、たべるくには、せかいでも、めずらしいと、いわれています。"),
        ("山の動物", "やまの、どうぶつ", ["きつね", "たぬき", "うさぎ", "くま", "いのしし", "さる"], "いのししの、ししは、むかしのことばで、けもののにくのことだと、いわれています。"),
        ("お正月", "おしょうがつ", ["かどまつ", "おせち", "たこあげ", "こま", "かるた", "おとしだま"], "かどまつは、としがみさまが、まよわずに、こられるための、めじるしだと、いわれています。"),
    ],
}


def main():
    epid, n = sys.argv[1], int(sys.argv[2])
    themes = THEMES[n]
    sc = [{"type": "title", "text": "ことば探し", "size": 130, "sub": "ひらがなの中にかくれた言葉をさがそう",
           "voice": f"頭の体操、ことば探しです。ひらがなの表の中に、テーマにそった言葉が、たてか、よこに、かくれています。右に書いてある言葉を、全部さがしてみてください。全部で{len(themes)}問です。"}]
    for i, (theme, theme_kana, words, note) in enumerate(themes, 1):
        rows, place = build(words, 6 if max(map(len, words)) >= 5 else 5, f"{epid}:{i}")
        base = {"type": "words", "cells": rows, "words": place, "theme": theme, "text": f"第{i}問"}
        sec = 30 + 5 * (len(words) - 5)
        sc.append({**base, "voice": f"第{i}問。テーマは、{theme_kana}。{len(words)}つの言葉が、かくれています。"})
        sc.append({**base, "think": True, "seconds": sec})
        sc.append({**base, "text": f"第{i}問 答え", "reveal": True, "chime": True,
                   "voice": "答えです。" + "、".join(words) + "。", "pad": 1.2})
    sc.append({"type": "title", "text": "何問見つけられましたか？", "size": 100, "sub": "コメントで教えてください",
               "voice": "何問、全部見つけられましたか？コメントで教えてください。"})
    ep = {"id": epid, "series": "頭の体操", "style": "wordsearch", "scenes": sc}
    out = pathlib.Path("brain/episodes") / f"{epid}.json"
    out.write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
