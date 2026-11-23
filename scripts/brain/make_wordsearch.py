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
        if len(words) > 1 and not (1 <= nh <= len(words) - 1):
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
        ("台所の道具", "だいどころの、どうぐ", ["なべ", "やかん", "おたま", "まないた", "ざる"], "おたまは、おたまじゃくしを、みじかくした、よびかたです。カエルのこどもの、おたまじゃくしは、このどうぐに、かたちがにているので、そうよばれるようになったと、いわれています。"),
        ("野菜", "やさい", ["だいこん", "にんじん", "ごぼう", "かぶ", "ねぎ", "なす"], "ごぼうを、やさいとして、たべるくには、せかいでも、めずらしいと、いわれています。"),
        ("山の動物", "やまの、どうぶつ", ["きつね", "たぬき", "うさぎ", "くま", "いのしし", "さる"], "いのししの、ししは、むかしのことばで、けもののにくのことだと、いわれています。"),
        ("お正月", "おしょうがつ", ["かどまつ", "おせち", "たこあげ", "こま", "かるた"], "かどまつは、としがみさまが、まよわずに、こられるための、めじるしだと、いわれています。"),
    ],
}

# かんたん編（本人の希望 11/23：かんたんは4×4）：言葉は3つ、3文字まで、1問20秒
THEMES_EASY = {
    1: [("冬のもの", "ふゆの、もの", ["ゆき", "こたつ", "みかん"]), ("台所の道具", "だいどころの、どうぐ", ["なべ", "ざる", "おたま"]),
        ("動物", "どうぶつ", ["いぬ", "ねこ", "うさぎ"]), ("野菜", "やさい", ["なす", "ねぎ", "かぶ"]),
        ("くだもの", "くだもの", ["なし", "もも", "ぶどう"]), ("体", "からだ", ["あし", "くび", "ひざ"]),
        ("天気", "てんき", ["あめ", "くも", "かぜ"]), ("色", "いろ", ["あか", "しろ", "みどり"]),
        ("文房具", "ぶんぼうぐ", ["のり", "ふで", "はさみ"]), ("海", "うみ", ["なみ", "かい", "かに"])],
}


def paths_of(rows, w):
    """表の中で、たて・よこにとなり合うマスをたどって w が読める道すじの数（曲がってもよい、同じマスは2回使わない）。"""
    R, C = len(rows), len(rows[0])
    cnt = 0

    def go(r, c, k, seen):
        nonlocal cnt
        if rows[r][c] != w[k]:
            return
        if k == len(w) - 1:
            cnt += 1
            return
        for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            a, b = r + dr, c + dc
            if 0 <= a < R and 0 <= b < C and (a, b) not in seen:
                go(a, b, k + 1, seen | {(a, b)})
    for r in range(R):
        for c in range(C):
            go(r, c, 0, {(r, c)})
    return cnt


COMMON = set(w for line in (pathlib.Path(__file__).with_name("common_words.txt")).read_text(encoding="utf-8").splitlines()
             if not line.startswith("#") for w in line.split())


def stray_words(rows, place):
    """答えの道すじ以外で、右か下にたどって読める「よく使う言葉」を返す（たまたま別の言葉ができていないかの確認）。"""
    R, C = len(rows), len(rows[0])
    answer = {tuple(map(tuple, p["path"])) for p in place}
    inside = set()
    for p in place:  # 答えの一部（例：さくらんぼ の中の さくら）は数えない
        pts = list(map(tuple, p["path"]))
        for a in range(len(pts)):
            for b in range(a + 2, len(pts) + 1):
                inside.add(tuple(pts[a:b]))
    found = []

    def go(path, text):
        if len(text) >= 2 and text in COMMON and tuple(path) not in answer and tuple(path) not in inside:
            found.append(text)
        if len(text) >= 4:
            return
        r, c = path[-1]
        for a, b in ((r, c + 1), (r + 1, c)):
            if a < R and b < C:
                go(path + [(a, b)], text + rows[a][b])
    for r in range(R):
        for c in range(C):
            go([(r, c)], rows[r][c])
    return found


def build_bent(words, size, seed):
    """言葉を、右か下にだけ進み、とちゅうで1回以上曲がる道すじで、重ならないように置く。
    残りをうめたあと、どの言葉もほかの道すじで読めない（ちょうど1通り）ことを確かめる。"""
    rnd = random.Random(seed)
    for _ in range(20000):
        used, place, ok = set(), [], True
        for w in sorted(words, key=len, reverse=True):
            for _ in range(200):
                r, c = rnd.randrange(size), rnd.randrange(size)
                path = [(r, c)]
                while len(path) < len(w):
                    opts = [(path[-1][0] + dr, path[-1][1] + dc) for dr, dc in ((0, 1), (1, 0))]
                    opts = [p for p in opts if p[0] < size and p[1] < size]
                    if not opts:
                        break
                    path.append(rnd.choice(opts))
                if len(path) < len(w) or used & set(path):
                    continue
                turns = sum(1 for i in range(1, len(path) - 1)
                            if (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]) != (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1]))
                if len(w) >= 3 and turns < 1:
                    continue
                used |= set(path)
                place.append({"w": w, "path": [list(p) for p in path]})
                break
            else:
                ok = False
                break
        if not ok:
            continue
        # まわりのマスには、答えの言葉と同じ文字をなるべく使わない
        filler = [k for k in KANA if k not in "".join(words)]
        g = [[rnd.choice(filler) for _ in range(size)] for _ in range(size)]
        for pl in place:
            for i, (a, b) in enumerate(pl["path"]):
                g[a][b] = pl["w"][i]
        rows = ["".join(x) for x in g]
        if all(paths_of(rows, w) == 1 for w in words) and not stray_words(rows, place):
            order = {w: i for i, w in enumerate(words)}
            place.sort(key=lambda p: order[p["w"]])
            return rows, place
    raise SystemExit(f"置けませんでした: {words}")


# 隠れた言葉あて：一覧を見せず、テーマと文字数だけをヒントに言葉を当てる。
# 本人の希望（11/23）：かんたん編は4×4（言葉2つ、1問20秒）、むずかしい編は5×5（言葉3つ、1問30秒）。1本の中では大きさをそろえる。
HIDDEN = {  # (テーマ, 声で読むテーマ, 言葉)。短い順に並べる
    "easy": {
        1: [("冬の食べもの", "ふゆの、たべもの", ["みかん", "やきいも"]), ("春の花", "はるの、はな", ["うめ", "たんぽぽ"]),
            ("台所の道具", "だいどころの、どうぐ", ["なべ", "やかん"]), ("野菜", "やさい", ["ねぎ", "だいこん"]),
            ("山の動物", "やまの、どうぶつ", ["くま", "たぬき"]), ("秋の味覚", "あきの、みかく", ["くり", "まつたけ"]),
            ("文房具", "ぶんぼうぐ", ["のり", "えんぴつ"]), ("海の生きもの", "うみの、いきもの", ["たこ", "くじら"]),
            ("空と天気", "そらと、てんき", ["くも", "かみなり"]), ("和菓子", "わがし", ["だんご", "もなか"])],
    },
    "hard": {
        1: [("お正月", "おしょうがつ", ["こま", "おせち", "かどまつ"]), ("くだもの", "くだもの", ["かき", "りんご", "さくらんぼ"]),
            ("魚", "さかな", ["さけ", "さんま", "かつお"]), ("乗りもの", "のりもの", ["ふね", "でんしゃ", "ひこうき"]),
            ("昭和の茶の間", "しょうわの、ちゃのま", ["こたつ", "てれび", "ちゃぶだい"]), ("鳥", "とり", ["はと", "すずめ", "うぐいす"]),
            ("夏の花", "なつの、はな", ["ゆり", "あさがお", "ひまわり"]), ("和楽器", "わがっき", ["こと", "たいこ", "しゃみせん"]),
            ("虫", "むし", ["せみ", "とんぼ", "かぶとむし"]), ("お祭り", "おまつり", ["みこし", "わたあめ", "ちょうちん"])],
    },
}
LEVEL = {"easy": ("かんたん編", 4, 20, 10), "hard": ("むずかしい編", 5, 30, 15)}  # 名前, 表の大きさ, 考える秒数, ショートの秒数


def hidden(epid, level, n):
    items = HIDDEN[level][n]
    name, size, sec, _ = LEVEL[level]
    sc = [{"type": "title", "text": "かくれた言葉あて", "size": 120, "sub": f"{name}　ヒントをたよりに、表の中の言葉をさがそう",
           "voice": f"頭の体操、かくれた言葉あて、{name}です。ひらがなの表の中に、テーマの言葉が、かくれています。ひだりから右、上から下へ、となりのマスをたどって読みます。とちゅうで、まがります。見つけた言葉の、文字の数が、そのまま点数。長い言葉ほど、高い点です。全部で{len(items)}問です。"}]
    for i, (theme, theme_kana, ws) in enumerate(items, 1):
        assert max(map(len, ws)) <= size + 1, ws
        rows, place = build_bent(ws, size, f"{epid}:{i}")
        base = {"type": "words", "hide": True, "cells": rows, "words": place, "theme": theme, "text": f"第{i}問"}
        lens = "と、".join(f"{len(w)}文字" for w in ws)
        sc.append({**base, "voice": f"第{i}問。テーマは、{theme_kana}。{lens}の、{len(ws)}つの言葉が、かくれています。"})
        sc.append({**base, "think": True, "seconds": sec})
        sc.append({**base, "text": f"第{i}問 答え", "reveal": True, "chime": True,
                   "voice": "答えは、" + "、".join(ws) + "。", "pad": 1.0})
    total = sum(len(w) for _, _, ws in items for w in ws)
    sc.append({"type": "title", "text": f"{total}点満点で何点？", "size": 100, "sub": "コメントで教えてください",
               "voice": f"全部で、{total}点満点です。何点、とれましたか？コメントで教えてください。"})
    return {"id": epid, "series": "頭の体操", "style": "kotoba_ate", "scenes": sc}


def main():
    epid, n = sys.argv[1], int(sys.argv[2])
    level = sys.argv[sys.argv.index("--hidden") + 1] if "--hidden" in sys.argv else None
    if "--short" in sys.argv:  # make_wordsearch.py <id> <型> --hidden easy|hard --short <問題番号>：1問だけの縦ショート
        k = int(sys.argv[sys.argv.index("--short") + 1])
        theme, theme_kana, ws = HIDDEN[level][n][k - 1]
        _, size, _, think = LEVEL[level]
        rows, place = build_bent(ws, size, f"{epid}:short")
        ep = {"id": epid, "series": "頭の体操", "style": "kotoba_ate", "kind": "words", "cells": rows, "words": place,
              "theme": theme, "think": think, "q": "かくれている言葉は？",
              "voice_q": f"かくれている言葉は、なんでしょう？テーマは、{theme_kana}。",
              "voice_a": "正解は、" + "、".join(ws) + "！", "answer_note": "正解は「" + "」「".join(ws) + "」"}
        out = pathlib.Path("brain/shorts") / f"{epid}.json"
        out.write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(out)
        return
    if level:
        ep = hidden(epid, level, n)
        out = pathlib.Path("brain/episodes") / f"{epid}.json"
        out.write_text(json.dumps(ep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(out)
        return
    easy = "--easy" in sys.argv
    themes = [t + ("",) for t in THEMES_EASY[n]] if easy else THEMES[n]
    sc = [{"type": "title", "text": "ことば探し", "size": 130, "sub": ("かんたん編　" if easy else "") + "ひらがなの中にかくれた言葉をさがそう",
           "voice": f"頭の体操、ことば探しです。ひらがなの表の中に、テーマにそった言葉が、たてか、よこに、かくれています。右に書いてある言葉を、全部さがしてみてください。全部で{len(themes)}問です。"}]
    for i, (theme, theme_kana, words, note) in enumerate(themes, 1):
        # 表は全部の問題で同じ大きさ（5×5）。言葉は4文字まで（本人の希望で小さい表にそろえる）
        size = 4 if easy else 5
        assert max(map(len, words)) <= size - 1, words
        rows, place = build(words, size, f"{epid}:{i}")
        base = {"type": "words", "cells": rows, "words": place, "theme": theme, "text": f"第{i}問"}
        sec = 20 if easy else 30 + 5 * (len(words) - 5)
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
