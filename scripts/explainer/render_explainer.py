#!/usr/bin/env python3
"""AI解説動画（画像がテンポよく切り替わり、ゆっくり動くスタイル）を作る。横長も縦長ショートも作れる。

explainer/<id>.json の形
  id, title, size（[1920,1080] か [1080,1920]）, chapters（{"1": "写真で質問", ...}）, chapter_label（"STEP" など）
  bgm_track（assets/bgm/<名前>.mp3 の曲。あればこちらを使う）, bgm_track_volume（既定0.22）, bgm_style（自作曲 match / riddle / spot）, bgm_volume, transition（fade / slide）, caption_style（outline / box）
  voice（既定の声、nova）, voice_instructions（読み方の指示）
  cast（掛け合い用 {"key": {"name","voice","color":[r,g,b],"side":"left|right","instructions"}}）
  scenes: [{image（assets/generated/<依頼id> か画像のパス）, voice（読み上げ文）か lines（[{who,text}]、掛け合い）,
            telop（大きな見出し。\\n で改行）, chapter（"1" など）, rank（ランキングの順位）, move（動き）}]
声は explainer/voice/<id>/<hash>.m4a（scripts/explainer/voices.py が Actions で作る）。無ければ無音で長さだけ見積もる。
使い方: render_explainer.py explainer/<id>.json 出力フォルダー [--fast]（--fast は半分の大きさで確認用）
"""
import json, math, os, pathlib, re, subprocess, sys, tempfile, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
sys.path.insert(0, str(ROOT / "scripts" / "explainer"))
import bgm as BGM  # noqa: E402
import voices as V  # noqa: E402

FPS, SR = 30, 48000
LEAD, PAD, GAP, XFADE = 0.35, 0.55, 0.25, 0.30  # 声の前の間、後の間、掛け合いの間、切り替えの長さ（秒）

ACCENT = (255, 196, 0)
ACCENT2 = (0, 170, 255)
INK = (18, 22, 32)
WHITE = (255, 255, 255)
MEDAL = {1: (236, 180, 20), 2: (170, 182, 196), 3: (200, 120, 60)}


def _find_font(names):
    dirs = [os.environ.get("FONT_DIR", ""), "/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto", "/usr/share/fonts"]
    for n in names:
        for d in dirs:
            if d and os.path.isdir(d):
                for p in pathlib.Path(d).rglob(n):
                    return str(p)
    raise SystemExit(f"日本語フォントが見つかりません: {names}")


FONT_BLACK = _find_font(["NotoSansCJK-Black.ttc", "NotoSansJP_900Black.ttf", "NotoSansCJK-Bold.ttc"])
FONT_BOLD = _find_font(["NotoSansCJK-Bold.ttc", "NotoSansJP_700Bold.ttf"])


def font(size, heavy=False):
    return ImageFont.truetype(FONT_BLACK if heavy else FONT_BOLD, int(size))


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def back_out(x, s=1.9):  # 少し行き過ぎて戻る（弾む）
    x = min(1.0, max(0.0, x)) - 1
    return x * x * ((s + 1) * x + s) + 1


class Layout:
    """横長と縦長で、文字の大きさと置き場所を変える。"""

    def __init__(self, size):
        self.W, self.H = size
        self.vertical = self.H > self.W
        u = self.W / (1080 if self.vertical else 1920)
        self.u = u
        if self.vertical:
            self.telop_size, self.telop_y, self.cap_size, self.cap_max = 92 * u, 360 * u, 60 * u, 15
            self.cap_bottom, self.chap_y, self.prog_y = self.H - 420 * u, 170 * u, 120 * u
            self.rank_xy = (self.W / 2, 620 * u)
        else:
            self.telop_size, self.telop_y, self.cap_size, self.cap_max = 104 * u, 150 * u, 58 * u, 22
            self.cap_bottom, self.chap_y, self.prog_y = self.H - 40 * u, 40 * u, self.H - 22 * u
            self.rank_xy = (230 * u, 400 * u)


L = Layout((1920, 1080))


# ---------- 素材 ----------
def load_image(ref, n):
    W, H = L.W, L.H
    p = ROOT / ref
    if p.is_dir():
        cands = sorted(f for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        p = cands[0] if cands else None
    elif not p.exists():
        p = None
    if p:
        im = Image.open(p).convert("RGB")
    else:  # まだ画像がないときの仮の絵
        im = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(im)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(40 + 60 * t + (37 * n) % 60), int(70 + 40 * t), int(140 - 40 * t)))
        d.text((W / 2, H / 2), f"（画像 {n + 1} を準備中）", font=font(56 * L.u), fill=WHITE, anchor="mm")
    target = (int(W * 1.2), int(H * 1.2))  # 1.2倍の余白を持たせて切り抜く（動かすため）
    s = max(target[0] / im.width, target[1] / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    x, y = (im.width - target[0]) // 2, (im.height - target[1]) // 2
    return im.crop((x, y, x + target[0], y + target[1]))


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "2", str(dst)], check=True)


def write_wav(p, data):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())


def read_wav(p):
    with wave.open(str(p)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767
    return a.reshape(-1, 2)


def sfx_pop():
    t = np.arange(int(0.12 * SR)) / SR
    f = 900 * np.exp(-18 * t) + 500
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-30 * t) * 0.5
    return np.stack([s, s], 1)


def sfx_whoosh(rng):
    n = int(0.35 * SR)
    x = rng.standard_normal(n)
    out, a = np.zeros(n), 0.0
    for i in range(n):
        a += (0.02 + 0.25 * (i / n)) * (x[i] - a)
        out[i] = a
    s = out * np.sin(np.pi * np.arange(n) / n) ** 2 * 0.6
    return np.stack([s * 0.8, s], 1)


def sfx_drum(seconds=1.0):  # ランキング発表のドラムロール＋シンバル
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    roll = rng.standard_normal(n) * (0.5 + 0.5 * np.sin(2 * np.pi * 28 * t) ** 2) * np.linspace(0.15, 0.5, n)
    cn = int(0.8 * SR)
    cym = rng.standard_normal(cn) * np.exp(-4 * np.arange(cn) / SR) * 0.4
    cym = np.diff(cym, prepend=0)
    s = np.concatenate([roll, cym])
    return np.stack([s, s], 1)


# ---------- 文字 ----------
def stroke_text(img, xy, text, f, fill, stroke, sw, anchor="mm"):
    ImageDraw.Draw(img).multiline_text(xy, text, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor,
                                       align="center", spacing=int(f.size * 0.15))


PARTICLES = "をはがにでも"


def _cut(c, maxlen, strict=False, chars="、？！"):
    """chars のどれかの後ろで、真ん中に近いところで2つに分ける（どちらも maxlen 字以内）。"""
    cands = [i for i, ch in enumerate(c[:-1]) if ch in chars and max(i + 1, len(c) - i - 1) <= maxlen]
    cut = min(cands, key=lambda i: abs(i + 1 - len(c) / 2), default=None)
    if cut is None:
        if strict:
            return None
        cut = len(c) // 2 - 1
    return c[:cut + 1], c[cut + 1:]


def split_caption(text, maxlen):
    """文ごとに1枚。1枚は2行・1行 maxlen 字まで。
    分け方の優先順：読点で2行 → 読点で別の1枚 → 助詞の後ろで2行 → 真ん中。"""
    todo = [p.strip().rstrip("。") for p in re.split(r"(?<=[。？！])", text.replace("　", "")) if p.strip()]
    out = []
    while todo:
        c = todo.pop(0)
        if len(c) <= maxlen:
            out.append([c]); continue
        two = _cut(c, maxlen, True) if len(c) <= maxlen * 2 else None
        if two:
            out.append(list(two)); continue
        halves = _cut(c, max(maxlen * 2, len(c) - 1), True)
        if halves and min(len(halves[0]), len(halves[1])) >= 3:
            todo[:0] = list(halves); continue
        two = _cut(c, maxlen, True, PARTICLES + "、") if len(c) <= maxlen * 2 else None
        out.append(list(two or _cut(c, maxlen)))
    return out


def caption_layer(lines, style="outline", color=None, name=None):
    """字幕1枚分（下端に字幕を寄せた透明な層）。"""
    W, u = L.W, L.u
    hgt = int(320 * u)
    im = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
    f = font(L.cap_size)
    lh = L.cap_size * 1.35
    y0 = hgt - 20 * u - lh * len(lines)
    d = ImageDraw.Draw(im)
    if style == "box":
        tw = max(d.textlength(ln, font=f) for ln in lines)
        bw = tw + 90 * u
        x0 = W / 2 - bw / 2
        d.rounded_rectangle([x0 + 6 * u, y0 - 14 * u, x0 + bw + 6 * u, hgt + 6 * u - 2 * u], 28 * u, fill=(0, 0, 0, 70))
        d.rounded_rectangle([x0, y0 - 22 * u, x0 + bw, hgt - 2 * u], 28 * u, fill=(255, 250, 240, 238),
                            outline=tuple(color) if color else None, width=int(7 * u) if color else 0)
        if name:
            nf = font(34 * u, heavy=True)
            nw = d.textlength(name, font=nf) + 44 * u
            d.rounded_rectangle([x0 + 30 * u, y0 - 56 * u, x0 + 30 * u + nw, y0 - 2 * u], 22 * u, fill=tuple(color or ACCENT2))
            d.text((x0 + 30 * u + nw / 2, y0 - 29 * u), name, font=nf, fill=WHITE, anchor="mm")
        for k, ln in enumerate(lines):
            d.text((W / 2, y0 + lh * k + lh / 2 - 10 * u), ln, font=f, fill=INK, anchor="mm")
    elif style == "news":  # ニュース風：画面下の帯の中に字幕
        top = hgt - 40 * u - lh * 2 - 30 * u
        d.rectangle([0, top, W, hgt], fill=(12, 30, 70, 235))
        d.rectangle([0, top, W, top + 8 * u], fill=(230, 50, 60, 255))
        lab = font(36 * u, heavy=True)
        d.rectangle([40 * u, top - 56 * u, 40 * u + d.textlength(name or "解説", font=lab) + 40 * u, top], fill=(230, 50, 60, 255))
        d.text((60 * u, top - 28 * u), name or "解説", font=lab, fill=WHITE, anchor="lm")
        mid = (top + 8 * u + hgt) / 2
        for k, ln in enumerate(lines):
            d.text((W / 2, mid + (k - (len(lines) - 1) / 2) * lh), ln, font=f, fill=WHITE, anchor="mm")
    else:
        for k, ln in enumerate(lines):
            stroke_text(im, (W / 2, y0 + lh * k + lh / 2), ln, f, WHITE, INK, int(9 * u))
    return im


def choice_card(text, state):
    """選択肢カード。state: normal / right / dim"""
    u = L.u
    f = font((56 if L.vertical else 54) * u, heavy=True)
    w = int((900 if L.vertical else 1000) * u)
    h = int(118 * u)
    im = Image.new("RGBA", (w + 16, h + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fill = {"normal": (255, 255, 255, 240), "right": (255, 214, 60, 255), "dim": (255, 255, 255, 120)}[state]
    d.rounded_rectangle([8, 14, w + 8, h + 14], h // 2, fill=(0, 0, 0, 90 if state != "dim" else 40))
    d.rounded_rectangle([0, 0, w, h], h // 2, fill=fill, outline=(230, 50, 60) if state == "right" else None, width=int(8 * u))
    head, _, body = text.partition(" ")
    d.ellipse([12 * u, 12 * u, h - 12 * u, h - 12 * u], fill=ACCENT2 if state != "right" else (230, 50, 60))
    d.text(((h) / 2, h / 2), head, font=f, fill=WHITE, anchor="mm")
    d.text((h + 20 * u, h / 2), body, font=f, fill=INK if state != "dim" else (90, 90, 100), anchor="lm")
    return im


def timer_layer(k, frac):
    """考える時間の丸い時計（残り k 秒）。"""
    u = L.u
    R = int(90 * u)
    im = Image.new("RGBA", (2 * R + 20, 2 * R + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([10, 10, 10 + 2 * R, 10 + 2 * R], fill=(255, 255, 255, 235))
    d.pieslice([10 + 10 * u, 10 + 10 * u, 10 + 2 * R - 10 * u, 10 + 2 * R - 10 * u], -90, -90 + 360 * frac, fill=(230, 50, 60, 200))
    d.ellipse([10 + 26 * u, 10 + 26 * u, 10 + 2 * R - 26 * u, 10 + 2 * R - 26 * u], fill=(255, 255, 255, 255))
    d.text((10 + R, 10 + R), str(k), font=font(84 * u, heavy=True), fill=INK, anchor="mm")
    return im


def telop_layer(text):
    u = L.u
    f = font(L.telop_size, heavy=True)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    x0, y0, x1, y1 = tmp.multiline_textbbox((0, 0), text, font=f, stroke_width=int(16 * u), spacing=int(f.size * 0.15), align="center")
    w, h = int(x1 - x0 + 60 * u), int(y1 - y0 + 50 * u)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    stroke_text(sh, (w / 2 + 6 * u, h / 2 + 8 * u), text, f, (0, 0, 0, 150), (0, 0, 0, 150), int(16 * u))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6 * u)))
    stroke_text(im, (w / 2, h / 2), text, f, INK, ACCENT, int(16 * u))
    stroke_text(im, (w / 2, h / 2), text, f, WHITE, INK, int(7 * u))
    return im


def chapter_layer(num, name, label=""):
    u = L.u
    f, fn = font(44 * u), font((40 if label else 46) * u, heavy=True)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    badge = f"{label}{num}"
    bw = max(68 * u, tmp.textlength(badge, font=fn) + 36 * u)
    tw = tmp.textlength(name, font=f)
    w, h = int(tw + bw + 60 * u), int(84 * u)
    im = Image.new("RGBA", (w + 12, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6, 10, w + 6, h + 10], h // 2, fill=(0, 0, 0, 90))
    d.rounded_rectangle([0, 0, w, h], h // 2, fill=(255, 255, 255, 240))
    d.rounded_rectangle([8 * u, 8 * u, 8 * u + bw, h - 8 * u], (h - 16 * u) // 2, fill=ACCENT2)
    d.text((8 * u + bw / 2, h / 2), badge, font=fn, fill=WHITE, anchor="mm")
    d.text((bw + 28 * u, h / 2), name, font=f, fill=INK, anchor="lm")
    return im


def rank_layer(rank):
    u = L.u
    R = int(130 * u)
    im = Image.new("RGBA", (2 * R + 24, 2 * R + 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = MEDAL.get(rank, (226, 60, 80))
    pts = []
    for k in range(48):  # ぎざぎざの縁（メダル風）
        a = 2 * math.pi * k / 48
        r = R if k % 2 == 0 else R * 0.9
        pts.append((R + 12 + r * math.cos(a), R + 12 + r * math.sin(a)))
    d.polygon([(x + 6, y + 10) for x, y in pts], fill=(0, 0, 0, 90))
    d.polygon(pts, fill=col)
    d.ellipse([12 + R * 0.2, 12 + R * 0.2, 12 + R * 1.8, 12 + R * 1.8], fill=WHITE)
    d.ellipse([12 + R * 0.28, 12 + R * 0.28, 12 + R * 1.72, 12 + R * 1.72], fill=col)
    d.text((R + 12 - 14 * u, R + 12), str(rank), font=font(140 * u, heavy=True), fill=WHITE, anchor="mm", stroke_width=int(5 * u), stroke_fill=INK)
    d.text((R + 12 + 58 * u, R + 12 + 40 * u), "位", font=font(48 * u, heavy=True), fill=WHITE, anchor="mm", stroke_width=int(4 * u), stroke_fill=INK)
    return im


def progress_layer(n, current):
    W, u = L.W, L.u
    im = Image.new("RGBA", (W, int(14 * u)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    seg = (W - 80 * u) / n
    for k in range(n):
        x0 = 40 * u + seg * k + 6 * u
        on = current is not None and k + 1 <= current
        d.rounded_rectangle([x0, 2 * u, x0 + seg - 12 * u, 12 * u], 5 * u, fill=ACCENT2 + (235,) if on else (255, 255, 255, 110))
    return im


def avatar(color, mouth, blink, active):
    """掛け合いの話し手（丸い顔のキャラクター）。mouth=0→1 で口が開く。"""
    u = L.u
    R = int(120 * u)
    im = Image.new("RGBA", (2 * R + 20, 2 * R + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = tuple(color) if active else tuple(int(v * 0.55 + 90) for v in color)
    d.ellipse([16, 22, 16 + 2 * R, 22 + 2 * R], fill=(0, 0, 0, 80))
    d.ellipse([10, 10, 10 + 2 * R, 10 + 2 * R], fill=c, outline=WHITE, width=int(8 * u))
    cx, cy = 10 + R, 10 + R
    ey = cy - 18 * u
    for sx in (-1, 1):
        x = cx + sx * 40 * u
        if blink:
            d.line([x - 16 * u, ey, x + 16 * u, ey], fill=INK, width=int(7 * u))
        else:
            d.ellipse([x - 15 * u, ey - 19 * u, x + 15 * u, ey + 19 * u], fill=WHITE)
            d.ellipse([x - 8 * u, ey - 8 * u, x + 8 * u, ey + 10 * u], fill=INK)
    d.ellipse([cx - 78 * u, cy + 6 * u, cx - 50 * u, cy + 24 * u], fill=(255, 150, 160, 160))
    d.ellipse([cx + 50 * u, cy + 6 * u, cx + 78 * u, cy + 24 * u], fill=(255, 150, 160, 160))
    mh = 6 * u + 34 * u * mouth
    d.rounded_rectangle([cx - 26 * u, cy + 32 * u, cx + 26 * u, cy + 32 * u + mh], int(min(mh, 52 * u) / 2), fill=(120, 30, 40))
    return im


# ---------- 動き ----------
MOVES = ["in", "pan_r", "out", "pan_l", "in_up", "pan_r", "out", "in"]


def kenburns(src, move, p):
    """src は 1.2倍の絵。p=0→1 で表示範囲を動かす（小数の位置で滑らかに）。"""
    sw, sh = src.size
    e = ease(p)
    vert = L.vertical
    table = {
        "in": (1.0, 1.15, (0.5, 0.5), (0.5, 0.48)),
        "in_up": (1.02, 1.16, (0.5, 0.58), (0.5, 0.42)),
        "out": (1.16, 1.0, (0.5, 0.47), (0.5, 0.5)),
        "pan_r": (1.08, 1.10, (0.5, 0.38), (0.5, 0.62)) if vert else (1.08, 1.10, (0.38, 0.5), (0.62, 0.5)),
        "pan_l": (1.10, 1.08, (0.5, 0.62), (0.5, 0.38)) if vert else (1.10, 1.08, (0.62, 0.5), (0.38, 0.5)),
        "still": (1.04, 1.06, (0.5, 0.5), (0.5, 0.5)),
    }
    z0, z1, c0, c1 = table.get(move, table["in"])
    z = z0 + (z1 - z0) * e
    cx, cy = c0[0] + (c1[0] - c0[0]) * e, c0[1] + (c1[1] - c0[1]) * e
    vw, vh = sw / 1.2 / z, sh / 1.2 / z  # 表示する範囲（z=1で出力と同じ大きさ）
    x, y = cx * (sw - vw), cy * (sh - vh)
    return src.resize((L.W, L.H), Image.BILINEAR, box=(x, y, x + vw, y + vh))


# ---------- 本体 ----------
def main(spec, out_dir, fast=False):
    global L, GRAD
    ep = json.loads(pathlib.Path(spec).read_text(encoding="utf-8"))
    L = Layout(tuple(ep.get("size", [1920, 1080])))
    GRAD = _grad()
    W, H = L.W, L.H
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    rng = np.random.default_rng(7)
    vdir = ROOT / "explainer" / "voice" / ep["id"]
    cast = ep.get("cast", {})
    cap_style = ep.get("caption_style", "box" if cast else "outline")
    nch = len(ep.get("chapters", {}))
    if cap_style == "news":
        L.cap_bottom = L.H
    if cast and not L.vertical:
        L.cap_max = 20  # 左右のキャラクターに字幕がかからないように

    # 1) 場面の長さを声から決める
    scenes, t, missing = [], 0.0, 0
    for n, sc in enumerate(ep["scenes"]):
        lines = sc.get("lines") or [{"text": sc["voice"]}]
        acc, parts = LEAD + (1.0 if sc.get("rank") else 0), []  # 順位発表はドラムロールの分だけ遅らせる
        for j, ln in enumerate(lines):
            who = cast.get(ln.get("who"), {})
            voice = who.get("voice", ep.get("voice", "nova"))
            src = vdir / f"{V.key(ln['text'], voice, who.get('instructions', ep.get('voice_instructions')))}.m4a"
            if src.exists():
                wv = tmp / f"v{n:02d}_{j}.wav"; to_wav(src, wv); data = read_wav(wv)
            else:
                data = np.zeros((int(max(1.2, len(ln["text"]) * 0.135) * SR), 2), np.float32); missing += 1
            win = SR // 25
            env = np.sqrt(np.convolve(data[:, 0] ** 2, np.ones(win) / win, "same"))  # 口の動き用
            parts.append({"start": acc, "len": len(data) / SR, "data": data, "env": env / (env.max() + 1e-6),
                          "who": ln.get("who"), "text": ln["text"]})
            acc += len(data) / SR + GAP
        length = acc - GAP + PAD + sc.get("extra", 0) + sc.get("countdown", 0)
        scenes.append({**sc, "n": n, "start": t, "len": length, "parts": parts})
        t += length
    total = t
    if missing:
        print(f"声がまだない部分: {missing}（無音で長さを見積もり）")

    # 2) 場面ごとの部品を先に作る
    last_ch = None
    for s in scenes:
        s["img"] = load_image(s["image"], s["n"])
        s["move"] = s.get("move") or MOVES[s["n"] % len(MOVES)]
        s["telop_l"] = telop_layer(s["telop"]) if s.get("telop") else None
        ch = s.get("chapter")
        s["chap"] = chapter_layer(ch, ep["chapters"][ch], ep.get("chapter_label", "")) if ch else None
        if ch:
            last_ch = int(ch)
        elif last_ch and s["n"] >= len(scenes) - 3:
            last_ch = nch
        s["prog"] = progress_layer(nch, last_ch) if nch else None
        s["rank_l"] = rank_layer(s["rank"]) if s.get("rank") else None
        if s.get("choices"):
            rv = s.get("reveal")
            s["cards"] = [choice_card(c, "normal" if rv is None else ("right" if i == rv else "dim")) for i, c in enumerate(s["choices"])]
        s["voice_end"] = max((p["start"] + p["len"] for p in s["parts"]), default=LEAD)
        s["caps"] = []
        for p in s["parts"]:
            who = cast.get(p["who"], {})
            caps = split_caption(p["text"], L.cap_max)
            weights = [sum(len(x) for x in c) for c in caps]
            acc = p["start"]
            for c, wgt in zip(caps, weights):
                d = p["len"] * wgt / sum(weights)
                s["caps"].append((acc, acc + d, caption_layer(c, cap_style, who.get("color"), who.get("name") or ep.get("news_label"))))
                acc += d

    # 3) 1コマずつ描いて ffmpeg に流す
    video = tmp / "video.mp4"
    nframes = int(round(total * FPS))
    vf = f"scale={W // 2}:{H // 2}" if fast else "null"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast" if fast else "medium",
                           "-crf", "28" if fast else "19", "-pix_fmt", "yuv420p", str(video)], stdin=subprocess.PIPE)
    shots, k = {}, 0
    trans = ep.get("transition", "fade")
    for f in range(nframes):
        tt = f / FPS
        while k + 1 < len(scenes) and tt >= scenes[k + 1]["start"]:
            k += 1
        s = scenes[k]
        lt = tt - s["start"]
        frame = draw_scene(s, lt, ep, cast)
        if k + 1 < len(scenes) and lt > s["len"] - XFADE:
            a = ease((lt - (s["len"] - XFADE)) / XFADE)
            nxt = draw_scene(scenes[k + 1], 0.0, ep, cast, base_only=True)
            if trans == "slide":  # ページをめくるように右から入る
                off = int(W * (1 - a))
                canvas = Image.new("RGB", (W, H))
                canvas.paste(frame, (off - W, 0))
                canvas.paste(nxt, (off, 0))
                frame = canvas
            else:
                frame = Image.blend(frame, nxt, a)
        ff.stdin.write(frame.tobytes())
        if abs(lt - min(2.4, s["len"] / 2)) < 0.5 / FPS:
            shots[s["n"]] = frame.copy()
    ff.stdin.close(); ff.wait()

    # 4) 音：声＋効果音、BGMは声の間だけ下げる
    voice = np.zeros((int(total * SR) + 3 * SR, 2), np.float32)
    sfx = np.zeros_like(voice)
    pop, wh, drum = sfx_pop(), sfx_whoosh(rng), sfx_drum()

    def put(buf, sig, at, g=1.0):
        i = max(0, int(at * SR)); j = min(len(buf), i + len(sig)); buf[i:j] += sig[: j - i] * g

    for s in scenes:
        for p in s["parts"]:
            put(voice, p["data"], s["start"] + p["start"])
        if s.get("countdown"):
            for i in range(int(s["countdown"])):
                put(sfx, sfx_pop(), s["start"] + s["voice_end"] + 0.3 + i, 0.5)
        if s.get("reveal") is not None:
            put(sfx, drum[-int(0.8 * SR):], s["start"] + 0.05, 0.4)
        if s.get("rank"):
            put(sfx, drum, s["start"] + 0.05, 0.35)
        elif s["telop_l"] is not None:
            put(sfx, pop, s["start"] + 0.05, 0.35)
        if s["n"] > 0:
            put(sfx, wh, s["start"] - XFADE, 0.22 if trans == "fade" else 0.3)
    n_s = int(total * SR)
    vw, sw_ = tmp / "voice.wav", tmp / "sfx.wav"
    write_wav(vw, voice[:n_s]); write_wav(sw_, sfx[:n_s])
    music = tmp / "bgm.wav"
    track = ROOT / "assets" / "bgm" / f"{ep.get('bgm_track', '')}.mp3"
    if ep.get("bgm_track") and track.exists():  # YouTube オーディオライブラリの曲（あがさん提供）。-20 LUFS にそろえて小さめに入れる
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(track), "-af",
                        f"loudnorm=I=-20:TP=-2,atrim=0:{total:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0, total - 3):.3f}:d=3",
                        "-ar", str(SR), "-ac", "2", str(music)], check=True)
        vol = ep.get("bgm_track_volume", 0.22)
    else:
        BGM.save(str(music), BGM.make(total, ep.get("bgm_style", "spot"), seed=sum(map(ord, ep["id"]))))
        vol = ep.get("bgm_volume", 0.14)
    audio = tmp / "audio.wav"
    fc = (f"[1:a]volume={vol}[m];[0:a]asplit=2[v1][v2];[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=450[md];"
          f"[v1][md][2:a]amix=inputs=3:normalize=0[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vw), "-i", str(music), "-i", str(sw_), "-filter_complex", fc,
                    "-map", "[o]", "-ar", str(SR), str(audio)], check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-movflags", "+faststart", "-shortest", str(out)], check=True)

    # 5) 確認用の一覧画像
    tw = 270 if L.vertical else 480
    th = int(tw * H / W)
    ims = [shots[i].resize((tw, th)) for i in sorted(shots)]
    cols = 6 if L.vertical else 4
    sheet = Image.new("RGB", (tw * cols, th * math.ceil(len(ims) / cols)))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{total:.1f}s", "missing voices:", missing)


def draw_scene(s, lt, ep, cast, base_only=False):
    W, H, u = L.W, L.H, L.u
    frame = kenburns(s["img"], s["move"], lt / (s["len"] + XFADE))
    if lt < 0.25 and s["n"] > 0 and ep.get("transition", "fade") == "fade":  # 入りの軽い押し込み
        z = 1 + 0.04 * (1 - ease(lt / 0.25))
        big = frame.resize((int(W * z), int(H * z)), Image.BILINEAR)
        ox, oy = (big.width - W) // 2, (big.height - H) // 2
        frame = big.crop((ox, oy, ox + W, oy + H))
    if base_only:
        return frame
    im = frame.convert("RGBA")
    im.alpha_composite(GRAD)
    if s["chap"] is not None:
        a = ease(lt / 0.35)
        x = int(-s["chap"].width + (48 * u + s["chap"].width) * a)
        im.alpha_composite(s["chap"], (x, int(L.chap_y)))
    if s["rank_l"] is not None and lt > 0.9:
        a = back_out((lt - 0.9) / 0.45)
        rl = s["rank_l"]
        sc = max(0.05, a)
        r2 = rl.resize((max(1, int(rl.width * sc)), max(1, int(rl.height * sc))), Image.BILINEAR)
        r2 = r2.rotate((1 - min(a, 1)) * 90 + math.sin(lt * 2) * 3, expand=True, resample=Image.BILINEAR)
        cx, cy = L.rank_xy
        im.alpha_composite(r2, (int(cx - r2.width / 2), int(cy - r2.height / 2)))
    t0 = 1.0 if s.get("rank") else 0.05
    if s["telop_l"] is not None and lt > t0:
        a = back_out((lt - t0) / 0.4)
        tl = s["telop_l"]
        sc = 0.6 + 0.4 * a
        bob = math.sin(lt * 2.2) * 4 * u  # ゆっくり上下にゆれる
        t2 = tl.resize((max(1, int(tl.width * sc)), max(1, int(tl.height * sc))), Image.BILINEAR)
        if a < 1:
            t2.putalpha(t2.getchannel("A").point(lambda v: int(v * min(1, a * 1.5))))
        y = max(L.telop_y + (60 * u if s["chap"] is not None and not L.vertical else 0), tl.height / 2 + 20 * u)
        if s["chap"] is not None and L.vertical:  # 章の札と重ならないように
            y = max(y, L.chap_y + 110 * u + tl.height / 2)
        y += bob
        x = W / 2 + (130 * u if s.get("rank") and not L.vertical else 0)
        im.alpha_composite(t2, (int(x - t2.width / 2), int(y - t2.height / 2)))
    if cast:  # 掛け合いの話し手：話している方が口を動かして弾む
        active = next((p for p in s["parts"] if p["start"] <= lt < p["start"] + p["len"]), None)
        for key, who in cast.items():
            talking = active is not None and active["who"] == key
            mouth = 0.0
            if talking:
                i = int((lt - active["start"]) * SR)
                mouth = float(active["env"][min(i, len(active["env"]) - 1)]) ** 0.7
            blink = (int((lt + (0.7 if who.get("side") == "left" else 0)) * 10) % 37) == 0
            av = avatar(who.get("color", ACCENT2), mouth, blink, talking or active is None)
            hop = abs(math.sin(lt * 9)) * 10 * u if talking else 0
            if L.vertical:
                x = int(W * (0.2 if who.get("side") == "left" else 0.8) - av.width / 2)
                y = int(L.cap_bottom - 330 * u - av.height - hop)
            else:
                x = int(40 * u if who.get("side") == "left" else W - av.width - 40 * u)
                y = int(H - av.height - 30 * u - hop)
            im.alpha_composite(av, (x, y))
    if s.get("cards"):
        n = len(s["cards"])
        ch = s["cards"][0].height
        gap = 20 * u
        cy0 = (H * 0.47 if L.vertical else H * 0.5) - (n * ch + (n - 1) * gap) / 2
        for i, card in enumerate(s["cards"]):
            t_in = 0.3 + 0.3 * i if s.get("reveal") is None else 0
            if lt < t_in:
                continue
            a = back_out((lt - t_in) / 0.35) if s.get("reveal") is None else 1
            sc = 0.7 + 0.3 * a
            if s.get("reveal") == i:
                sc *= 1 + 0.05 * math.sin(lt * 6)
            c2 = card.resize((max(1, int(card.width * sc)), max(1, int(card.height * sc))), Image.BILINEAR)
            im.alpha_composite(c2, (int(W / 2 - c2.width / 2), int(cy0 + i * (ch + gap) + (ch - c2.height) / 2)))
    if s.get("countdown"):
        t_cd = lt - s["voice_end"] - 0.3
        n_cd = int(s["countdown"])
        if 0 <= t_cd < n_cd:
            tl_ = timer_layer(n_cd - int(t_cd), 1 - (t_cd / n_cd))
            x = W - tl_.width - 50 * u
            y = (L.chap_y + 120 * u) if not L.vertical else (L.cap_bottom - tl_.height - 40 * u)
            im.alpha_composite(tl_, (int(x), int(y)))
    sticky = ep.get("caption_style") == "news"  # ニュース風は帯を出しっぱなしにする
    shown = None
    for a0, a1, layer in s["caps"]:
        if a0 - 0.05 <= lt < a1 + 0.35 or (sticky and a0 - 0.05 <= lt):
            shown = layer
            if not sticky:
                break
    if sticky and shown is None and s["caps"]:
        shown = s["caps"][0][2]
    if shown is not None:
        im.alpha_composite(shown, (0, int(L.cap_bottom - shown.height)))
    if s["prog"] is not None:
        im.alpha_composite(s["prog"], (0, int(L.prog_y)))
    return im.convert("RGB")


def _grad():
    W, H = L.W, L.H
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    b0 = int(H * 0.64)
    for y in range(b0, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * ((y - b0) / (H - b0)) ** 1.6)))
    top = int(H * (0.3 if L.vertical else 0.28))
    for y in range(0, top):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(80 * (1 - y / top) ** 2)))
    return g


GRAD = None

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--fast" in sys.argv)
