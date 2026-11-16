#!/usr/bin/env python3
"""頭の体操シリーズ（漢字の仲間はずれ探し・漢字穴埋め・雑学クイズ）の動画を作る。

scripts/render/render.py の仕組み（声・BGM・効果音・書き出し）をそのまま使い、場面の種類だけ足す。
render.py は変更しない。

足した場面の種類
  grid    : 同じ漢字の中に1つだけ違う漢字（base, odd, rows, cols）。think: true で考える時間（seconds）、reveal: true で答えに丸
  cross   : 漢字穴埋め。真ん中の□に入る漢字（top, left, right, bottom, answer）。think / reveal は grid と同じ
  fact    : 雑学クイズ。左に絵（image）、右に問題（q）。think で考える時間、answer で答え（caption に解説）
共通: text（左上の見出し）, caption, voice, chime, seconds, pad（render.py と同じ）
使い方: brain.py brain/episodes/<id>.json out_dir [--no-voice]
"""
import os, pathlib, random, sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
import render as R  # noqa: E402

# シリーズの色とBGM（render.py の表に、この実行の間だけ足す）
R.ACCENT.update({"kanji": (196, 52, 52), "trivia": (44, 120, 200)})
R.BGM.STYLES.setdefault("kanji", R.BGM.STYLES["riddle"])
R.BGM.STYLES.setdefault("trivia", (96, 60, [(0, "maj7"), (5, "maj7"), (2, "m7"), (7, "dom7")]))

PAPER = (248, 243, 232)
PAPER2 = (238, 230, 212)
INK = (28, 28, 34)
SERIF = R._first(["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc",
                  R.FONT_BOLD])
MINE = {"grid", "cross", "fact"}


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


def think_frames(im, ep, sc, H):
    """考える時間：右上のタイマーと下の進み具合。1秒ごとの画像を返す。"""
    W = im.width
    u = H / 1080
    n = int(sc["seconds"])
    Rr = int(62 * u)
    cx, cy = W - Rr - 40 * u, Rr + 22 * u
    out = []
    for k in range(n, 0, -1):
        f = im.copy()
        R.timer(f, ep, k, n, cx, cy, Rr)
        R.progress_bar(f, ep, k / n, H)
        out.append(f.convert("RGB"))
    return out


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
    top, bottom, side = 140 * u, 150 * u, 70 * u
    cell = min((W - side * 2) / cols, (H - top - bottom) / rows)
    x0 = (W - cell * cols) / 2
    y0 = top + (H - top - bottom - cell * rows) / 2
    # 白いカード
    R.shadow_box(im, (x0 - 24 * u, y0 - 20 * u, x0 + cell * cols + 24 * u, y0 + cell * rows + 20 * u), int(24 * u), (255, 255, 255, 250))
    d = ImageDraw.Draw(im)
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


_orig = R.render_scene


def render_scene(sc, ep, size):
    t = sc["type"]
    if t == "grid":
        return scene_grid(sc, ep, size)
    if t == "cross":
        return scene_cross(sc, ep, size)
    if t == "fact":
        return scene_fact(sc, ep, size)
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
    p = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "brain_paper.png"
    paper((1920, 1080)).convert("RGB").filter(ImageFilter.GaussianBlur(1)).save(p)
    ep["bg"] = str(p)
    return ep


def main(spec, out_dir, no_voice=False):
    import json
    ep = ensure_bg(json.loads(pathlib.Path(spec).read_text(encoding="utf-8")))
    for sc in ep["scenes"]:  # 絵がまだ届いていない場面は背景で代用
        if sc.get("image"):
            got = pick(sc["image"])
            if not got:
                print("まだない絵:", sc["image"])
            sc["image"] = got or ep["bg"]
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / f"{ep['id']}.resolved.json"
    tmp.write_text(json.dumps(ep, ensure_ascii=False), encoding="utf-8")
    R.main(str(tmp), out_dir, no_voice)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
