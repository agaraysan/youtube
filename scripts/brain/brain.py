#!/usr/bin/env python3
"""頭の体操シリーズ（漢字・ことわざ・雑学・記憶力・計算など）の動画を作る。1本につき1ジャンル。

scripts/render/render.py の仕組み（声・BGM・効果音・書き出し）をそのまま使い、場面の種類だけ足す。
render.py は変更しない。

足した場面の種類
  grid    : 同じ漢字の中に1つだけ違う漢字（base, odd, rows, cols）。think: true で考える時間（seconds）、reveal: true で答えに丸
  cross   : 漢字穴埋め。真ん中の□に入る漢字（top, left, right, bottom, answer）。think / reveal は grid と同じ
  fact    : 雑学クイズ。左に絵（image）、右に問題（q）。think で考える時間、answer で答え（caption に解説）
  choice  : 3択クイズ。big（大きな文字。□は色つき）か image（絵）と q（問題文）、options, correct（0から）。reveal で正解に色
            big_answer（答えで差し替える文字）, hl（答えで色をつける文字）, ruby（答えで出す読み）
            big_color（大きな文字の色。色の名前クイズ用）, emoji（シルエットクイズ。答えまで黒い影）
  count   : 数えてクイズ。target（絵文字）が n 個、others [[絵文字, 個数]] にまぜる。key で配置を固定
  grid に cells（文字のリスト）を渡すと自由な並び（数字さがし）
  memo    : 記憶力。items（絵文字）を並べる。hide で1つを「？」に。options/correct で下に3択
共通: text（左上の見出し）, caption, voice, chime, seconds, pad（render.py と同じ）
使い方: brain.py brain/episodes/<id>.json out_dir [--no-voice]
"""
import math, os, pathlib, random, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
import render as R  # noqa: E402

# シリーズの色とBGM（render.py の表に、この実行の間だけ足す）
R.ACCENT.update({"kanji": (196, 52, 52), "trivia": (44, 120, 200), "proverb": (120, 84, 170), "showa": (176, 104, 40),
                 "memory": (0, 150, 136), "calc": (230, 110, 30), "fish": (30, 110, 170),
                 "yoji": (150, 60, 90), "veg": (60, 140, 60), "pref": (40, 100, 180), "color": (90, 90, 110), "shadow": (70, 70, 150),
                 "number": (210, 90, 40), "antonym": (70, 120, 160), "mushikui": (200, 80, 60), "count": (40, 150, 90)})
for _k in ("proverb", "showa", "fish", "yoji", "veg", "pref"):
    R.BGM.STYLES.setdefault(_k, R.BGM.STYLES["riddle"])
for _k in ("memory", "calc", "color", "shadow", "number", "mushikui", "count"):
    R.BGM.STYLES.setdefault(_k, R.BGM.STYLES["spot"])
for _k in ("antonym",):
    R.BGM.STYLES.setdefault(_k, R.BGM.STYLES["riddle"])
R.BGM.STYLES.setdefault("kanji", R.BGM.STYLES["riddle"])
R.BGM.STYLES.setdefault("trivia", (96, 60, [(0, "maj7"), (5, "maj7"), (2, "m7"), (7, "dom7")]))

# ---- BGM：YouTube オーディオライブラリの曲（assets/bgm/）。シリーズごとに最初の曲を決め、同じ組の曲を順につなぐ ----
BGM_DIR = ROOT / "assets" / "bgm"
CALM = ["valley_drive", "you_are_the_only", "cruise"]
LIVELY = ["little_fish", "estela", "wager_with_angels"]
BGM_FIRST = {"kanji": "valley_drive", "proverb": "you_are_the_only", "yoji": "cruise", "fish": "valley_drive",
             "veg": "you_are_the_only", "antonym": "cruise", "pref": "cruise", "showa": "valley_drive", "trivia": "you_are_the_only",
             "calc": "little_fish", "mushikui": "estela", "count": "little_fish", "memory": "estela", "shadow": "wager_with_angels",
             "color": "wager_with_angels", "number": "estela"}
LOUDNESS = -18  # 動画全体の大きさ（LUFS）。render.py の -16 より少し控えめ
BGM_VOLUME = 0.22  # 曲は -20 LUFS にそろえてから、この倍率で小さめに入れる（声の間はさらに下がる）
_make, _save = R.BGM.make, R.BGM.save


def bgm_playlist(style, seconds):
    first = BGM_FIRST.get(style)
    if not first or not (BGM_DIR / f"{first}.mp3").exists():
        return None
    group = CALM if first in CALM else LIVELY
    k = group.index(first)
    order = [g for g in group[k:] + group[:k] if (BGM_DIR / f"{g}.mp3").exists()]
    lst, total = [], 0.0
    while total < seconds + 6:
        for g in order:
            p = BGM_DIR / f"{g}.mp3"
            lst.append(p)
            total += R.dur(str(p)) - 3
            if total >= seconds + 6:
                break
    return lst


def _bgm_make(seconds, style="match", seed=1):
    lst = bgm_playlist(style, seconds)
    return ("files", lst, seconds) if lst else _make(seconds, style, seed)


def _bgm_save(out, data):
    if not (isinstance(data, tuple) and data and data[0] == "files"):
        return _save(out, data)
    _, lst, seconds = data
    ins, filt = [], []
    for i, p in enumerate(lst):
        ins += ["-i", str(p)]
        filt.append(f"[{i}:a]aresample={R.SR},aformat=channel_layouts=stereo[a{i}]")
    cur = "[a0]"
    for i in range(1, len(lst)):
        filt.append(f"{cur}[a{i}]acrossfade=d=3[x{i}]")
        cur = f"[x{i}]"
    filt.append(f"{cur}loudnorm=I=-20:TP=-2,atrim=0:{seconds:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0, seconds - 3):.3f}:d=3,aresample={R.SR}[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(R.SR), "-ac", "2", out],
                   check=True)


R.BGM.make, R.BGM.save = _bgm_make, _bgm_save

PAPER = (248, 243, 232)
PAPER2 = (238, 230, 212)
INK = (28, 28, 34)
SERIF = R._first(["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc",
                  R.FONT_BOLD])
MINE = {"grid", "cross", "fact", "choice", "memo"}


def serif(size):
    return R.ImageFont.truetype(SERIF, max(8, int(size)))


def paper(size):
    """和紙のような明るい土台（字がはっきり見えるように）。"""
    W, H = size
    g = Image.new("RGBA", size)
    d = ImageDraw.Draw(g)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(PAPER[i] * (1 - k) + PAPER2[i] * k) for i in range(3)) + (255,))
    rnd = random.Random(7)
    for _ in range(1400):  # 細かい繊維
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        L = rnd.uniform(4, 22)
        c = rnd.randint(205, 228)
        d.line([(x, y), (x + L, y + rnd.uniform(-3, 3))], fill=(c, c - 6, c - 18, 70), width=1)
    return g


HEAD_NG = set("、。，．！？!?）」』】・ーぁぃぅぇぉっゃゅょァィゥェォッャュョ")


def wrap(d, text, f, max_w):
    """折り返し。行の長さをそろえ、句読点やかっこ閉じが行の先頭に来ないようにする。"""
    out = []
    for para in text.split("\n"):
        total = d.textlength(para, font=f)
        n = max(1, -(-int(total) // int(max_w)))
        target = min(max_w, total / n * 1.08 + 1)
        cur = ""
        for ch in para:
            if cur and d.textlength(cur + ch, font=f) > target and ch not in HEAD_NG:
                if cur[-1] in "（「『【" and len(cur) > 1:  # 開きかっこは行末に残さない
                    out.append(cur[:-1]); cur = cur[-1] + ch
                else:
                    out.append(cur); cur = ch
            else:
                cur += ch
        out.append(cur)
    return out


def caption(img, ep, text, H):
    """下の字幕カード（render.py と同じ見た目で、折り返しだけ整える）。"""
    W = img.width
    u = H / 1080
    d = ImageDraw.Draw(img)
    f = R.font(52 * u, "bold")
    lines = wrap(d, text, f, W * 0.80)
    lh = 52 * u * 1.45
    h = lh * len(lines) + 40 * u
    w = max(d.textlength(l, font=f) for l in lines) + 130 * u
    x0, y0 = (W - w) / 2, H - h - 40 * u
    R.shadow_box(img, (x0, y0, x0 + w, y0 + h), int(16 * u), (255, 255, 255, 246))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + 14 * u, y0 + h], radius=int(7 * u), fill=R.accent(ep))
    for i, ln in enumerate(lines):
        d.text((W / 2 + 7 * u, y0 + 20 * u + lh * (i + 0.5)), ln, font=f, fill=INK, anchor="mm")


class ThinkFrames(list):
    """考える時間の画像（1秒ごと）。base（タイマーなしの土台）と n（秒数）も持つ。なめらかな描画で使う。"""


def think_frames(im, ep, sc, H):
    """考える時間：右上のタイマーと下の進み具合。1秒ごとの画像を返す（動きのある描画では base を使う）。"""
    n = int(sc["seconds"])
    out = ThinkFrames()
    out.base, out.n = im.copy(), n
    out.append(draw_timer(im.copy(), ep, n, n).convert("RGB"))  # 確認用に最初の1枚だけ作る
    return out


def timer_shadow(f):
    """タイマーの土台（影つきの紺の円）。重い処理なので1回だけ描く。"""
    W, H = f.size
    u = H / 1080
    Rr = int(62 * u)
    cx, cy = W - Rr - 40 * u, Rr + 22 * u
    R.shadow_box(f, (cx - Rr, cy - Rr, cx + Rr, cy + Rr), Rr, R.NAVY + (255,), blur=12, offset=5)
    return f


def draw_timer(f, ep, remain, n, shadow=True):
    """タイマー（残り remain 秒、小数可）と下の進み具合のバーを描く。"""
    W, H = f.size
    u = H / 1080
    Rr = int(62 * u)
    cx, cy = W - Rr - 40 * u, Rr + 22 * u
    if shadow:
        timer_shadow(f)
    d = ImageDraw.Draw(f)
    w = max(6, int(Rr * 0.14))
    bb = [cx - Rr + w, cy - Rr + w, cx + Rr - w, cy + Rr - w]
    d.ellipse(bb, outline=(60, 78, 105), width=w)
    if remain > 0:
        d.arc(bb, -90, -90 + 360 * remain / n, fill=R.accent(ep), width=w)
    d.text((cx, cy), str(max(0, math.ceil(remain - 1e-6))), font=R.font(Rr * 0.9, "heavy"), fill=(255, 255, 255), anchor="mm")
    R.progress_bar(f, ep, max(0.0, remain / n), H)
    return f


def grid_pos(ep, sc):
    if "pos" in sc:
        return tuple(sc["pos"])
    rnd = random.Random(f"{ep['id']}:{sc['base']}{sc['odd']}:{sc['rows']}x{sc['cols']}")
    # 端すぎない場所に置く
    return rnd.randrange(1, sc["rows"] - 1), rnd.randrange(1, sc["cols"] - 1)


def scene_grid(sc, ep, size):
    W, H = size
    u = H / 1080
    im = paper(size)
    rows, cols = sc["rows"], sc["cols"]
    top, bottom, side = 140 * u, 185 * u, 70 * u
    cell = min((W - side * 2) / cols, (H - top - bottom) / rows)
    x0 = (W - cell * cols) / 2
    y0 = top + (H - top - bottom - cell * rows) / 2
    # 白いカード
    R.shadow_box(im, (x0 - 24 * u, y0 - 20 * u, x0 + cell * cols + 24 * u, y0 + cell * rows + 20 * u), int(24 * u), (255, 255, 255, 250))
    d = ImageDraw.Draw(im)
    if sc.get("cells"):  # 自由な並び（例：1〜50の数字）
        cells = sc["cells"]
        longest = max(len(str(x)) for x in cells)
        f = R.font(cell * (0.62 if longest <= 2 else 0.45), "heavy")
        for i, ch in enumerate(cells):
            r, c = divmod(i, cols)
            d.text((x0 + cell * (c + 0.5), y0 + cell * (r + 0.5)), str(ch), font=f, fill=INK, anchor="mm")
        R.header(im, ep, sc, H)
        if sc.get("caption"):
            caption(im, ep, sc["caption"], H)
        return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")
    f = serif(cell * 0.78)
    r0, c0 = grid_pos(ep, sc)
    for r in range(rows):
        for c in range(cols):
            ch = sc["odd"] if (r, c) == (r0, c0) else sc["base"]
            d.text((x0 + cell * (c + 0.5), y0 + cell * (r + 0.5)), ch, font=f, fill=INK, anchor="mm")
    if sc.get("reveal"):
        cx, cy = x0 + cell * (c0 + 0.5), y0 + cell * (r0 + 0.5)
        R.ring(im, cx, cy, cell * 0.62, R.accent(ep), u)
    R.header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


def arrow(d, a, b, color, w, head):
    d.line([a, b], fill=color, width=int(w))
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    p1 = (b[0] - head * math.cos(ang - 0.5), b[1] - head * math.sin(ang - 0.5))
    p2 = (b[0] - head * math.cos(ang + 0.5), b[1] - head * math.sin(ang + 0.5))
    d.polygon([b, p1, p2], fill=color)


def scene_cross(sc, ep, size):
    """上→□、左→□、□→右、□→下 の4つの熟語ができる漢字を当てる。"""
    W, H = size
    u = H / 1080
    im = paper(size)
    s = 200 * u          # マスの大きさ
    gap = 120 * u        # マスの間（矢印）
    cx, cy = W * 0.40, H * 0.56
    boxes = {"center": (cx, cy), "top": (cx, cy - s - gap), "bottom": (cx, cy + s + gap),
             "left": (cx - s - gap, cy), "right": (cx + s + gap, cy)}
    acc = R.accent(ep)
    for k, (bx, by) in boxes.items():
        fill = (255, 255, 255, 255) if k != "center" or sc.get("reveal") else (255, 246, 220, 255)
        R.shadow_box(im, (bx - s / 2, by - s / 2, bx + s / 2, by + s / 2), int(18 * u), fill, blur=12, offset=6)
    d = ImageDraw.Draw(im)
    f = serif(s * 0.72)
    for k in ("top", "bottom", "left", "right"):
        bx, by = boxes[k]
        d.text((bx, by), sc[k], font=f, fill=INK, anchor="mm")
    if sc.get("reveal"):
        d.text((cx, cy), sc["answer"], font=f, fill=acc, anchor="mm")
        d.rounded_rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], radius=int(18 * u), outline=acc, width=int(8 * u))
    else:
        d.rounded_rectangle([cx - s / 2 + 10 * u, cy - s / 2 + 10 * u, cx + s / 2 - 10 * u, cy + s / 2 - 10 * u], radius=int(12 * u),
                            outline=acc, width=int(6 * u))
        d.text((cx, cy), "？", font=R.font(s * 0.55, "heavy"), fill=acc, anchor="mm")
    col, lw, hd, m = (120, 110, 100), 9 * u, 30 * u, 18 * u
    arrow(d, (cx, cy - s / 2 - gap + m), (cx, cy - s / 2 - m), col, lw, hd)          # 上 → □
    arrow(d, (cx - s / 2 - gap + m, cy), (cx - s / 2 - m, cy), col, lw, hd)          # 左 → □
    arrow(d, (cx + s / 2 + m, cy), (cx + s / 2 + gap - m, cy), col, lw, hd)          # □ → 右
    arrow(d, (cx, cy + s / 2 + m), (cx, cy + s / 2 + gap - m), col, lw, hd)          # □ → 下
    # 右側：説明か、できる熟語の一覧
    px0, px1 = W * 0.64, W - 70 * u
    py0, py1 = H * 0.24, H * 0.88
    R.shadow_box(im, (px0, py0, px1, py1), int(24 * u), (255, 255, 255, 245))
    d = ImageDraw.Draw(im)
    pcx = (px0 + px1) / 2
    if sc.get("reveal"):
        a = sc["answer"]
        words = [sc["top"] + a, sc["left"] + a, a + sc["right"], a + sc["bottom"]]
        readings = sc.get("readings", [""] * 4)
        d.text((pcx, py0 + 64 * u), "できる熟語", font=R.font(44 * u), fill=acc, anchor="mm")
        for i, w in enumerate(words):
            y = py0 + 150 * u + i * 138 * u
            d.text((pcx - 120 * u, y), w, font=serif(80 * u), fill=INK, anchor="mm")
            if readings[i]:
                d.text((pcx + 60 * u, y + 4 * u), readings[i], font=R.font(40 * u), fill=(95, 95, 110), anchor="lm")
    else:
        lines = ["矢印の向きに読むと", "4つの熟語ができる", "漢字はなに？"]
        for i, ln in enumerate(lines):
            d.text((pcx, py0 + (py1 - py0) * (0.30 + i * 0.2)), ln, font=R.font(54 * u), fill=INK, anchor="mm")
    R.header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


def scene_fact(sc, ep, size):
    """雑学クイズ：左に絵、右に問題か答え。"""
    W, H = size
    u = H / 1080
    img_path = sc.get("image", ep["bg"])
    im = R.bg(img_path, size, dim=0.55, blur=18)
    src = Image.open(ROOT / img_path).convert("RGB")
    iw = W * 0.50
    ih = iw * 9 / 16
    ix, iy = 60 * u, 130 * u + (H - 340 * u - ih) / 2
    R.framed(im, src, (ix, iy, iw, ih), int(20 * u))
    px0, px1 = ix + iw + 40 * u, W - 60 * u
    py0, py1 = iy, iy + ih
    R.shadow_box(im, (px0, py0, px1, py1), int(24 * u), (255, 255, 255, 246))
    d = ImageDraw.Draw(im)
    pw = px1 - px0 - 80 * u
    acc = R.accent(ep)
    if sc.get("answer"):
        R.chip(im, "答え", px0 + 36 * u, py0 - 36 * u, 72 * u, acc)
        fs = sc.get("size", 76) * u
        f = R.font(fs, "heavy")
        lines = wrap(d, sc["answer"], f, pw)
        lh = fs * 1.35
        y = (py0 + py1) / 2 - lh * len(lines) / 2
        for i, ln in enumerate(lines):
            d.text(((px0 + px1) / 2, y + lh * (i + 0.5)), ln, font=f, fill=acc, anchor="mm")
    else:
        fs = sc.get("size", 60) * u
        f = R.font(fs, "bold")
        lines = wrap(d, sc["q"], f, pw)
        lh = fs * 1.5
        y = (py0 + py1) / 2 - lh * len(lines) / 2
        for i, ln in enumerate(lines):
            d.text(((px0 + px1) / 2, y + lh * (i + 0.5)), ln, font=f, fill=INK, anchor="mm")
    R.header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


EMOJI_FONT = R._first(["/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"])
_emoji_cache = {}


def emoji(ch, size):
    """絵文字を指定の大きさの画像で返す（カラー絵文字は109pxで描いてから縮める）。"""
    key = (ch, int(size))
    if key not in _emoji_cache:
        f = R.ImageFont.truetype(EMOJI_FONT, 109)
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((80, 80), ch, font=f, embedded_color=True, anchor="mm")
        im = im.crop(im.getbbox() or (0, 0, 160, 160))
        k = size / max(im.size)
        _emoji_cache[key] = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    return _emoji_cache[key]


def paste_center(im, small, cx, cy):
    im.alpha_composite(small, (int(cx - small.width / 2), int(cy - small.height / 2)))


def is_emoji(t):
    return bool(t) and all(ord(c) > 0x2000 for c in t) and not any("　" <= c <= "鿿" for c in t)


def options_row(im, ep, sc, x0, x1, y0, h):
    """3択（または4択）のボタン。reveal で正解を色付き、ほかを薄く。"""
    u = im.height / 1080
    opts = sc["options"]
    n = len(opts)
    gap = 36 * u
    w = (x1 - x0 - gap * (n - 1)) / n
    acc = R.accent(ep)
    for i, o in enumerate(opts):
        bx = x0 + i * (w + gap)
        ok = sc.get("reveal") and i == sc["correct"]
        dim = sc.get("reveal") and i != sc["correct"]
        fill = acc + (255,) if ok else ((255, 255, 255, 150) if dim else (255, 255, 255, 250))
        R.shadow_box(im, (bx, y0, bx + w, y0 + h), int(20 * u), fill, blur=12, offset=6)
        d = ImageDraw.Draw(im)
        lab = "ABCD"[i]
        r = h * 0.26
        d.ellipse([bx + 26 * u, y0 + h / 2 - r, bx + 26 * u + 2 * r, y0 + h / 2 + r], fill=(255, 255, 255) if ok else acc)
        d.text((bx + 26 * u + r, y0 + h / 2), lab, font=R.font(r * 1.2, "heavy"), fill=acc if ok else (255, 255, 255), anchor="mm")
        cx = bx + 26 * u + 2 * r + (w - 26 * u - 2 * r) / 2
        col = (255, 255, 255) if ok else ((150, 150, 160) if dim else INK)
        if is_emoji(o):
            e = emoji(o, h * 0.66)
            if dim:
                e = e.copy(); e.putalpha(e.getchannel("A").point(lambda a: a * 0.35))
            paste_center(im, e, cx, y0 + h / 2)
        else:
            fs = min(h * 0.42, (w - 2 * r - 70 * u) / max(1, len(o)) * 1.0)
            ImageDraw.Draw(im).text((cx, y0 + h / 2), o, font=R.font(fs, "heavy"), fill=col, anchor="mm")


def scene_choice(sc, ep, size):
    """3択クイズ。big（大きな文字）か image（絵）で問題を見せ、下に選択肢。"""
    W, H = size
    u = H / 1080
    acc = R.accent(ep)
    if sc.get("image"):
        im = R.bg(sc["image"], size, dim=0.55, blur=18)
        src = Image.open(ROOT / sc["image"]).convert("RGB")
        ih = 560 * u
        iw = ih * src.width / src.height
        R.framed(im, src, ((W - iw) / 2 if not sc.get("q") else 60 * u, 120 * u, iw, ih), int(20 * u))
        if sc.get("q"):
            px0 = 60 * u + iw + 40 * u
            R.shadow_box(im, (px0, 120 * u, W - 60 * u, 120 * u + ih), int(24 * u), (255, 255, 255, 246))
            d = ImageDraw.Draw(im)
            f = R.font(62 * u, "bold")
            lines = wrap(d, sc["q"], f, W - 60 * u - px0 - 80 * u)
            lh = 62 * u * 1.5
            y = 120 * u + ih / 2 - lh * len(lines) / 2
            for i, ln in enumerate(lines):
                d.text(((px0 + W - 60 * u) / 2, y + lh * (i + 0.5)), ln, font=f, fill=INK, anchor="mm")
        oy = 120 * u + ih + 50 * u
    else:
        im = paper(size)
        d = ImageDraw.Draw(im)
        if sc.get("reveal") and sc.get("ruby"):  # 答えでは問題文の代わりに読みを出す
            d.text((W / 2, 175 * u), sc["ruby"], font=R.font(60 * u, "bold"), fill=R.accent(ep), anchor="mm")
        elif sc.get("q"):
            d.text((W / 2, 175 * u), sc["q"], font=R.font(60 * u, "bold"), fill=INK, anchor="mm")
        if sc.get("emoji"):  # シルエット：答えまでは黒い影
            e = emoji(sc["emoji"], 420 * u)
            if not sc.get("reveal"):
                sil = Image.new("RGBA", e.size, (40, 40, 52, 255))
                sil.putalpha(e.getchannel("A").point(lambda a: 255 if a > 90 else 0))
                e = sil
            R.shadow_box(im, (W / 2 - 300 * u, 120 * u, W / 2 + 300 * u, 640 * u), int(28 * u), (255, 255, 255, 250))
            paste_center(im, e, W / 2, 380 * u)
            options_row(im, ep, sc, 90 * u, W - 90 * u, 700 * u, 170 * u)
            R.header(im, ep, sc, H)
            if sc.get("caption"):
                caption(im, ep, sc["caption"], H)
            return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")
        big = sc.get("big", "")
        if sc.get("reveal") and sc.get("big_answer"):
            big = sc["big_answer"]
        fs = sc.get("size", 190) * u
        f = serif(fs)
        tw = d.textlength(big, font=f)
        while tw > W * 0.82:
            fs *= 0.9; f = serif(fs); tw = d.textlength(big, font=f)
        cw, ch = max(tw + 200 * u, 700 * u), fs + 150 * u
        cx0, cy0 = (W - cw) / 2, 240 * u
        R.shadow_box(im, (cx0, cy0, cx0 + cw, cy0 + ch), int(28 * u), (255, 255, 255, 250))
        d = ImageDraw.Draw(im)
        # □ は色をつけて目立たせる
        x = W / 2 - tw / 2
        for c in big:
            cwid = d.textlength(c, font=f)
            col = tuple(sc["big_color"]) if sc.get("big_color") else (acc if c == "□" or (sc.get("reveal") and c in sc.get("hl", "")) else INK)
            d.text((x, cy0 + ch / 2), c, font=f, fill=col, anchor="lm")
            x += cwid
        oy = cy0 + ch + 70 * u
    oh = 170 * u
    options_row(im, ep, sc, 90 * u, W - 90 * u, oy, oh)
    R.header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


def scene_memo(sc, ep, size):
    """記憶力：絵文字を並べて見せる。hide にした場所は「？」のマス。"""
    W, H = size
    u = H / 1080
    im = paper(size)
    items = sc["items"]
    n = len(items)
    cols = sc.get("cols", 3 if n <= 6 else 4)
    rows = -(-n // cols)
    top, bottom = 150 * u, (290 * u if sc.get("options") else 60 * u)
    cell = min((W - 300 * u) / cols, (H - top - bottom) / rows)
    x0 = (W - cell * cols) / 2
    y0 = top + (H - top - bottom - cell * rows) / 2
    acc = R.accent(ep)
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        bx, by = x0 + c * cell + 14 * u, y0 + r * cell + 14 * u
        bw = cell - 28 * u
        hidden = i == sc.get("hide")
        R.shadow_box(im, (bx, by, bx + bw, by + bw), int(22 * u), (255, 246, 220, 255) if hidden else (255, 255, 255, 252), blur=10, offset=5)
        if hidden:
            ImageDraw.Draw(im).text((bx + bw / 2, by + bw / 2), "？", font=R.font(bw * 0.55, "heavy"), fill=acc, anchor="mm")
        else:
            paste_center(im, emoji(it, bw * 0.66), bx + bw / 2, by + bw / 2)
    if sc.get("options"):
        options_row(im, ep, sc, 300 * u, W - 300 * u, H - 250 * u, 190 * u)
    R.header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


def scene_count(sc, ep, size):
    """数えてクイズ：絵文字をばらばらに置き、target がいくつあるか。reveal で target に丸。"""
    W, H = size
    u = H / 1080
    im = paper(size)
    x0, y0, x1, y1 = 120 * u, 140 * u, W - 120 * u, H - (300 * u if sc.get("options") else 60 * u)
    R.shadow_box(im, (x0, y0, x1, y1), int(24 * u), (255, 255, 255, 250))
    rnd = random.Random(f"{ep['id']}:{sc['key']}")
    items = [sc["target"]] * sc["n"] + [e for e, k in sc["others"] for _ in range(k)]
    rnd.shuffle(items)
    cols = math.ceil(math.sqrt(len(items) * (x1 - x0) / (y1 - y0)))
    rows = math.ceil(len(items) / cols)
    cw, ch = (x1 - x0 - 40 * u) / cols, (y1 - y0 - 40 * u) / rows
    slots = [(r, c) for r in range(rows) for c in range(cols)]
    rnd.shuffle(slots)
    sz = min(cw, ch) * 0.70
    marks = []
    for e, (r, c) in zip(items, slots):
        cx = x0 + 20 * u + cw * (c + 0.5) + rnd.uniform(-0.12, 0.12) * cw
        cy = y0 + 20 * u + ch * (r + 0.5) + rnd.uniform(-0.12, 0.12) * ch
        paste_center(im, emoji(e, sz), cx, cy)
        if e == sc["target"]:
            marks.append((cx, cy))
    if sc.get("reveal"):
        for cx, cy in marks:
            R.ring(im, cx, cy, sz * 0.62, R.accent(ep), u)
    if sc.get("options"):
        options_row(im, ep, sc, 300 * u, W - 300 * u, H - 250 * u, 190 * u)
    R.header(im, ep, sc, H)
    return think_frames(im, ep, sc, H) if sc.get("think") else im.convert("RGB")


def scene_title(sc, ep, size):
    """和紙の表紙：左に色の帯、番組名の札、大きな題、下線、小さな説明。"""
    W, H = size
    u = H / 1080
    if ep.get("_paper"):
        im = paper(size)
    else:  # 絵の背景は、明るくぼかして使う
        im = R.bg(sc.get("bg", ep["bg"]), size, dim=0.35, blur=10, tint=(250, 247, 240))
    acc = R.accent(ep)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 34 * u, H], fill=acc)
    d.rectangle([34 * u, 0, 40 * u, H], fill=(255, 255, 255))
    # 大きな白いカード
    cx0, cy0, cx1, cy1 = 170 * u, 190 * u, W - 170 * u, H - 190 * u
    R.shadow_box(im, (cx0, cy0, cx1, cy1), int(30 * u), (255, 255, 255, 250), blur=26, offset=12, alpha=70)
    d = ImageDraw.Draw(im)
    if ep.get("series"):
        f = R.font(42 * u, "heavy")
        tw = d.textlength(ep["series"], font=f)
        bx = W / 2 - tw / 2 - 34 * u
        d.rounded_rectangle([bx, cy0 - 36 * u, W / 2 + tw / 2 + 34 * u, cy0 + 36 * u], radius=int(36 * u), fill=acc)
        d.text((W / 2, cy0), ep["series"], font=f, fill=(255, 255, 255), anchor="mm")
    fs = sc.get("size", 120) * u * 1.05
    f = serif(fs)
    while d.textlength(sc["text"], font=f) > (cx1 - cx0) - 140 * u:
        fs *= 0.92; f = serif(fs)
    my = (cy0 + cy1) / 2 - (40 * u if sc.get("sub") else 0)
    d.text((W / 2, my), sc["text"], font=f, fill=INK, anchor="mm")
    d.rounded_rectangle([W / 2 - 90 * u, my + fs * 0.78, W / 2 + 90 * u, my + fs * 0.78 + 10 * u], radius=int(5 * u), fill=acc)
    if sc.get("sub"):
        d.text((W / 2, my + fs * 0.78 + 85 * u), sc["sub"], font=R.font(50 * u, "bold"), fill=(90, 90, 100), anchor="mm")
    return im.convert("RGB")


_orig = R.render_scene


def render_scene(sc, ep, size):
    t = sc["type"]
    if t == "title":
        return scene_title(sc, ep, size)
    if t == "grid":
        return scene_grid(sc, ep, size)
    if t == "cross":
        return scene_cross(sc, ep, size)
    if t == "fact":
        return scene_fact(sc, ep, size)
    if t == "choice":
        return scene_choice(sc, ep, size)
    if t == "memo":
        return scene_memo(sc, ep, size)
    if t == "count":
        return scene_count(sc, ep, size)
    return _orig(sc, ep, size)


R.render_scene = render_scene


def pick(path):
    """フォルダーを指定されたら、その中の最初の絵を使う（Codex の保存名は毎回ちがうため）。なければ None。"""
    if not path:
        return None
    p = ROOT / path
    if p.is_dir():
        imgs = sorted(x for x in p.iterdir() if x.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        return str(imgs[0].relative_to(ROOT)) if imgs else None
    return path if p.exists() else None


def ensure_bg(ep):
    """背景画像がまだなければ、和紙の土台を一時ファイルで使う。"""
    if pick(ep.get("bg")):
        ep["bg"] = pick(ep["bg"])
        return ep
    p = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / f"brain_paper_{ep.get('id', 'x')}.png"
    paper((1920, 1080)).convert("RGB").filter(ImageFilter.GaussianBlur(1)).save(p)
    ep["bg"] = str(p)
    ep["_paper"] = True
    return ep


def main(spec, out_dir, no_voice=False):
    import json
    ep = ensure_bg(json.loads(pathlib.Path(spec).read_text(encoding="utf-8")))
    for sc in ep["scenes"]:  # 絵がまだ届いていない場面は背景で代用
        if sc.get("image"):
            got = pick(sc["image"])
            if not got:
                raise SystemExit(f"絵がまだ届いていないので、今回は作りません: {sc['image']}")
            sc["image"] = got
    if bgm_playlist(ep.get("style"), 60) and "bgm_volume" not in ep:
        ep["bgm_volume"] = BGM_VOLUME
    import motion  # 1コマずつ描く書き出し（場面のつなぎ・なめらかなタイマー・表紙の動き）
    motion.render(ep, out_dir, no_voice)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
