#!/usr/bin/env python3
"""「日本と世界 制度くらべ」の動画を作る。ニュース番組のような図表（国旗・数字・グラフ）が中心。

seido/<id>.json の形（くわしくは seido/README.md）
  id, size（[1920,1080] か [1080,1920]）, topic（右上の話題名）, short_title（縦長の上に出し続ける見出し）
  bgm_track（assets/bgm/<名前>.mp3）, bgm_volume（既定0.2）, voice, voice_instructions
  sources: {"key": {"label": "財務省「…」", "url": "https://…"}}
  meta: {title, description, tags}, thumb: {lines: [...], flags: [...]}
  scenes: [{type, say: [文, ...], source: "key" か ["key", ...], ...}]
    type: title / chapter / compare / bars / list / big / table / flow / outro
  文の中の {…} は赤く強調（見出し・字幕・大きな文字）。「字幕|読み」と書くと読みだけ変えられる。
声は seido/voice/<id>/<hash>.m4a（scripts/seido/voices.py が Actions で作る）。無ければ無音で長さを見積もる。
使い方: render_seido.py seido/<id>.json 出力フォルダー [--stills 秒,秒,...] [--thumb]
"""
import json, math, os, pathlib, re, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "seido"))
import voices as V  # noqa: E402

FPS, SR = 30, 48000
LEAD, GAP, PAD = 0.45, 0.32, 0.7  # 最初の文の前、文と文の間、最後の文の後（秒）
FADE_OUT = 0.25

PAPER = (244, 242, 237)
INK = (22, 34, 60)
SUB = (104, 112, 128)
LINE = (218, 213, 204)
RED = (196, 22, 48)
BLUE = (44, 92, 140)
GRAY = (150, 156, 166)
WHITE = (255, 255, 255)
PALE_RED = (252, 234, 236)
CHANNEL = "日本と世界 制度くらべ"


def _find_font(names):
    dirs = [os.environ.get("FONT_DIR", ""), "/usr/share/fonts"]
    for n in names:
        for d in dirs:
            if d and os.path.isdir(d):
                for p in pathlib.Path(d).rglob(n):
                    return str(p)
    raise SystemExit(f"日本語フォントが見つかりません: {names}（FONT_DIR に Noto Sans JP を置いてください）")


FONTS = {
    "black": _find_font(["NotoSansJP_900Black.ttf", "NotoSansCJK-Black.ttc"]),
    "heavy": _find_font(["NotoSansJP_800ExtraBold.ttf", "NotoSansJP_900Black.ttf", "NotoSansCJK-Black.ttc"]),
    "bold": _find_font(["NotoSansJP_700Bold.ttf", "NotoSansCJK-Bold.ttc"]),
    "medium": _find_font(["NotoSansJP_500Medium.ttf", "NotoSansCJK-Medium.ttc"]),
}
EMOJI = _find_font(["NotoColorEmoji.ttf"])
FLAG_CODES = {"eu": "EU", "uk": "GB"}


@lru_cache(None)
def font(size, w="bold"):
    return ImageFont.truetype(FONTS[w], int(size))


def ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def parse_rich(s, base, acc=RED):
    """「{強調}」を赤くする。[(文字, 色), ...] を返す。"""
    out = []
    for i, part in enumerate(re.split(r"[{}]", s)):
        if part:
            out.append((part, acc if i % 2 else base))
    return out


def plain(s):
    return s.replace("{", "").replace("}", "")


NO_HEAD = set("、。，．・：；！？」』）】〉ー～ぁぃぅぇぉっゃゅょァィゥェォッャュョ%％")


def wrap(s, size, w, maxw):
    """文字の幅で折り返す（行頭に句読点が来ないようにする）。{} の強調は行をまたいでも保つ。"""
    lines = []
    for para in s.split("\n"):
        cur, acc_open = "", False
        f = font(size, w)
        for ch in para:
            trial = cur + ch
            if ch not in "{}" and cur and f.getlength(plain(trial)) > maxw and ch not in NO_HEAD:
                lines.append(cur + ("}" if acc_open else ""))
                cur = ("{" if acc_open else "") + ch
            else:
                cur = trial
            if ch == "{":
                acc_open = True
            elif ch == "}":
                acc_open = False
        lines.append(cur)
    return lines


def wrap_bal(s, size, w, maxw):
    """折り返しの行数はそのままで、各行の長さをそろえる（最後の行に1〜2文字だけ残らないように）。"""
    if "\n" in s:
        return [l for para in s.split("\n") for l in wrap_bal(para, size, w, maxw)]
    ls = wrap(s, size, w, maxw)
    if len(ls) < 2:
        return ls
    n = len(ls)
    total = font(size, w).getlength(plain(s))
    lo = total / n
    for k in range(40):
        trial = wrap(s, size, w, lo * (1 + 0.025 * k))
        if len(trial) <= n:
            return trial
    return ls


def fit(s, size, w, maxw, minsize=24):
    """1行に収まる大きさに縮める。"""
    while size > minsize and font(size, w).getlength(plain(s)) > maxw:
        size -= 2
    return size


@lru_cache(4096)
def text_sprite(s, size, color, w="bold", acc=RED):
    """1行の文字の絵（RGBA）。{} の中は acc 色。"""
    segs = parse_rich(s, color, acc)
    f = font(size, w)
    total = sum(f.getlength(t) for t, _ in segs)
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (max(1, int(math.ceil(total)) + 4), asc + desc + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 2
    for t, c in segs:
        d.text((x, 2), t, font=f, fill=c)
        x += f.getlength(t)
    # 見た目の上下（字の高さ）で置けるよう、上下の余白を切る
    box = im.getbbox() or (0, 0, 1, 1)
    top, bot = int(asc * 0.12), asc + int(desc * 0.55)
    return im.crop((0, min(top, box[1]), im.width, max(bot, box[3])))


@lru_cache(64)
def flag_sprite(code, h):
    code = FLAG_CODES.get(code, code.upper())
    ch = "".join(chr(0x1F1E6 + ord(c) - 65) for c in code)
    f = ImageFont.truetype(EMOJI, 109)
    im = Image.new("RGBA", (160, 140), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4, 4), ch, font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    return im.resize((int(im.width * h / im.height), int(h)), Image.LANCZOS)


@lru_cache(256)
def rrect_sprite(w, h, r, fill, outline=None, width=0, shadow=0):
    pad = shadow * 2
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((pad, pad + shadow // 2, pad + w, pad + h + shadow // 2), r, fill=(20, 30, 50, 46))
        im = sh.filter(ImageFilter.GaussianBlur(shadow / 2))
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w - 1, pad + h - 1), r, fill=fill, outline=outline, width=width)
    return im


def with_alpha(sp, a):
    if a >= 0.999:
        return sp
    sp = sp.copy()
    sp.putalpha(sp.getchannel("A").point(lambda v: int(v * a)))
    return sp


class Ctx:
    """1コマを描く道具。collect=True のときは描かずに、動きのある時間だけを集める（止まっている場面はコマを使い回すため）。"""

    def __init__(self, canvas, t, collect=False, instant=False):
        self.c, self.t, self.collect, self.instant = canvas, t, collect, instant
        self.windows = []
        self.fade = 1.0

    def ap(self, t0, dur=0.45):
        if self.collect:
            self.windows.append((t0, dur))
            return 1.0
        if self.instant and t0 <= 1.5:
            return 1.0
        return ease((self.t - t0) / dur)

    def paste(self, sp, x, y, a=1.0):
        a *= self.fade
        if self.collect or a <= 0.003:
            return
        x, y = int(round(x)), int(round(y))
        W, H = self.c.size
        if x >= W or y >= H or x + sp.width <= 0 or y + sp.height <= 0:
            return
        cx, cy = max(0, -x), max(0, -y)
        sp = sp.crop((cx, cy, min(sp.width, W - x), min(sp.height, H - y)))
        self.c.alpha_composite(with_alpha(sp, a), (x + cx, y + cy))

    def text(self, x, y, s, size, color=INK, w="bold", anchor="lt", a=1.0, acc=RED):
        sp = text_sprite(s, int(size), color, w, acc)
        self.paste(sp, *anchored(sp, x, y, anchor), a)
        return sp.width, sp.height

    def lines(self, x, y, s, size, color=INK, w="bold", maxw=1000, lh=1.35, anchor="lt", a=1.0, acc=RED):
        """折り返して複数行を書く。y は1行目の上（anchor の縦が m なら全体の中央）。高さを返す。"""
        ls = wrap_bal(s, size, w, maxw)
        step = size * lh
        total = step * (len(ls) - 1) + size
        if anchor[1] == "m":
            y -= total / 2
        for i, ln in enumerate(ls):
            self.text(x, y + i * step, ln, size, color, w, anchor[0] + "t", a, acc)
        return total

    def rrect(self, x, y, w, h, r=18, fill=WHITE, outline=None, width=0, shadow=0, a=1.0):
        sp = rrect_sprite(int(w), int(h), int(r), fill, outline, width, shadow)
        self.paste(sp, x - shadow * 2, y - shadow * 2, a)

    def flag(self, code, x, y, h, anchor="lt", a=1.0):
        sp = flag_sprite(code, int(h))
        self.paste(sp, *anchored(sp, x, y, anchor), a)
        return sp.width


def anchored(sp, x, y, anchor):
    ax, ay = anchor[0], anchor[1]
    if ax == "m":
        x -= sp.width / 2
    elif ax == "r":
        x -= sp.width
    if ay == "m":
        y -= sp.height / 2
    elif ay == "b":
        y -= sp.height
    return x, y


def fmt_num(v, dec=0):
    return f"{v:,.{dec}f}"


# ---------- 画面の型 ----------
class Look:
    def __init__(self, size):
        self.W, self.H = size
        self.v = self.H > self.W
        if self.v:
            self.top, self.bottom, self.left, self.right = 470, 1240, 70, 1010
            self.cap_y, self.cap_size, self.cap_maxw = 1318, 52, 900
            self.src_y = 1262
        else:
            self.top, self.bottom, self.left, self.right = 150, 850, 110, 1810
            self.cap_y, self.cap_size, self.cap_maxw = 968, 50, 1500
            self.src_y = 1056


def background(look, ep):
    W, H = look.W, look.H
    im = Image.new("RGBA", (W, H), PAPER + (255,))
    d = ImageDraw.Draw(im)
    # うっすらした点の格子（新聞の紙面のような質感）
    step = 36
    for y in range(step // 2, H, step):
        for x in range(step // 2, W, step):
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(228, 225, 218))
    ctx = Ctx(im, 99)
    if look.v:
        ctx.rrect(W / 2 - 300, 96, 600, 64, 32, fill=WHITE, shadow=6)
        d.ellipse((W / 2 - 262, 115, W / 2 - 236, 141), fill=RED)
        ctx.text(W / 2 + 14, 128, CHANNEL, 32, INK, "bold", "mm")
        if ep.get("short_title"):
            ctx.lines(W / 2, 290, ep["short_title"], 76, INK, "black", maxw=960, lh=1.22, anchor="mm")
    else:
        d.ellipse((64, 52, 92, 80), fill=RED)
        ctx.text(106, 66, CHANNEL, 32, INK, "bold", "lm")
        if ep.get("topic"):
            ctx.text(W - 64, 66, ep["topic"], 30, SUB, "bold", "rm")
        d.line((64, 112, W - 64, 112), fill=LINE, width=2)
    return im


def heading(ctx, look, s, t0=0.0):
    p = ctx.ap(t0, 0.4)
    if look.v:
        return ctx.lines(look.W / 2, look.top - 10 + 20 * (1 - p), s, 60, INK, "black", maxw=940, lh=1.25, anchor="mt", a=p)
    ctx.rrect(look.left, look.top + 6 + 20 * (1 - p), 10, 58, 4, fill=RED, a=p)
    ctx.text(look.left + 34, look.top + 35 + 20 * (1 - p), s, 58, INK, "black", "lm", a=p)
    return 70


def item_times(sc, n, times, start=0.35, step=0.18):
    """各項目が出る時刻。項目に at（何文目で出すか）があればそれに合わせる。"""
    out = []
    for i in range(n):
        at = (sc.get("items") or [{}] * n)[i].get("at") if isinstance((sc.get("items") or [None])[0], dict) else None
        if at is None and sc.get("at"):
            at = sc["at"][i] if i < len(sc["at"]) else None
        out.append(times[at] if at is not None and at < len(times) else start + i * step)
    return out


def value_text(it, p):
    if "text" in it:
        return it["text"]
    v = it["value"] * (ease(p) if it.get("count", True) else 1)
    return it.get("prefix", "") + fmt_num(v, it.get("dec", 0))


def color_of(it, sc):
    if it.get("color"):
        return tuple(it["color"])
    hl = sc.get("highlight", "jp")
    return RED if it.get("flag") == hl else (GRAY if it.get("dim") else BLUE)


def draw_title(ctx, look, sc, T, times):
    W = look.W
    cy = (look.top + look.bottom) / 2 - (40 if not look.v else 60)
    p0, p1 = ctx.ap(0.05), ctx.ap(0.25, 0.5)
    if sc.get("kicker"):
        sp = text_sprite(sc["kicker"], 44 if not look.v else 50, WHITE, "bold")
        kw, kh = sp.width + 60, sp.height + 26
        ky = cy - (230 if not look.v else 330)
        ctx.rrect(W / 2 - kw / 2, ky, kw, kh, kh // 2, fill=RED, a=p0)
        ctx.paste(sp, W / 2 - sp.width / 2, ky + 13, p0)
    size = sc.get("size", 104 if not look.v else 96)
    ctx.lines(W / 2, cy + 18 * (1 - p1), sc["title"], size, INK, "black", maxw=W - 200, lh=1.22, anchor="mm", a=p1)
    flags = sc.get("flags", [])
    if flags:
        fh = 96 if not look.v else 110
        gapx = 34
        if look.v and len(flags) > 4:
            rows = [flags[: (len(flags) + 1) // 2], flags[(len(flags) + 1) // 2:]]
        else:
            rows = [flags]
        fy = cy + (220 if not look.v else 330)
        k = 0
        for r, row in enumerate(rows):
            ws = [flag_sprite(c, fh).width for c in row]
            x = W / 2 - (sum(ws) + gapx * (len(row) - 1)) / 2
            for c, w in zip(row, ws):
                p = ctx.ap(0.55 + 0.1 * k, 0.4)
                ctx.flag(c, x, fy + r * (fh + 40) + 16 * (1 - p), fh, "lt", p)
                x += w + gapx
                k += 1


def draw_chapter(ctx, look, sc, T, times):
    W = look.W
    cy = (look.top + look.bottom) / 2
    p, p2 = ctx.ap(0.05, 0.5), ctx.ap(0.3, 0.5)
    ctx.text(W / 2, cy - 110 - 20 * (1 - p), f"{int(sc['num']):02d}", 150, RED, "black", "mm", a=p)
    lw = 160 * p
    ctx.rrect(W / 2 - lw / 2, cy - 18, max(2, lw), 6, 3, fill=INK, a=p)
    ctx.lines(W / 2, cy + 80 + 16 * (1 - p2), sc["title"], 84 if not look.v else 78, INK, "black", maxw=W - 160, lh=1.2, anchor="mt", a=p2)


def draw_compare(ctx, look, sc, T, times):
    heading(ctx, look, sc["heading"])
    items = sc["items"]
    n = len(items)
    ts = item_times(sc, n, times, 0.45, 0.22)
    if look.v:  # 縦長は1国1行のカード
        top = look.top + (150 if len(wrap(sc["heading"], 60, "black", 940)) < 2 else 220)
        ch = min(220, (look.bottom - top - 30 * (n - 1)) / n)
        for i, it in enumerate(items):
            p = ctx.ap(ts[i], 0.45)
            y = top + i * (ch + 30) + 30 * (1 - p)
            hl = it.get("hl", it.get("flag") == sc.get("highlight", "jp"))
            ctx.rrect(look.left, y, look.right - look.left, ch, 22, fill=WHITE, outline=RED if hl else None, width=5 if hl else 0, shadow=8, a=p)
            ctx.flag(it["flag"], look.left + 36, y + ch / 2 - 30, 66, "lm", p)
            ctx.text(look.left + 36, y + ch / 2 + 44, it["name"], 38, INK, "bold", "lm", a=p)
            pv = ctx.ap(ts[i] + 0.15, 0.9)
            col = color_of(it, sc)
            uw = ctx.text(look.right - 36, y + ch / 2 + 20, it.get("unit", ""), 52, col, "black", "rb", a=p)[0] if it.get("unit") else 0
            ctx.text(look.right - 40 - uw, y + ch / 2 + 26, value_text(it, pv), 104 if "text" not in it else 72, col, "black", "rb", a=p)
            if it.get("note"):
                ctx.text(look.right - 36, y + ch / 2 + 50, it["note"], 28, SUB, "medium", "rt", a=p)
        return
    gap = 40
    top = look.top + 110
    cw = (look.right - look.left - gap * (n - 1)) / n
    chh = min(520, look.bottom - top - 40)
    for i, it in enumerate(items):
        p = ctx.ap(ts[i], 0.45)
        x = look.left + i * (cw + gap)
        y = top + 30 * (1 - p)
        hl = it.get("hl", it.get("flag") == sc.get("highlight", "jp"))
        ctx.rrect(x, y, cw, chh, 24, fill=WHITE, outline=RED if hl else None, width=5 if hl else 0, shadow=10, a=p)
        cx = x + cw / 2
        ctx.flag(it["flag"], cx, y + 60, 100, "mt", p)
        ctx.text(cx, y + 196, it["name"], 46, INK, "bold", "mt", a=p)
        pv = ctx.ap(ts[i] + 0.15, 0.9)
        col = color_of(it, sc)
        vs = value_text(it, pv)
        vsize = 136 if "text" not in it else (96 if len(it["text"]) <= 4 else 72)
        vsp = text_sprite(vs, vsize, col, "black")
        usp = text_sprite(it["unit"], 56, col, "black") if it.get("unit") else None
        tw = vsp.width + (usp.width + 6 if usp else 0)
        vy = y + 360
        ctx.paste(vsp, cx - tw / 2, vy - vsp.height / 2, p)
        if usp:
            ctx.paste(usp, cx - tw / 2 + vsp.width + 6, vy + vsp.height / 2 - usp.height - 8, p)
        if it.get("note"):
            ctx.lines(cx, y + 470, it["note"], 30, SUB, "medium", maxw=cw - 50, lh=1.35, anchor="mt", a=p)


def draw_bars(ctx, look, sc, T, times):
    hh = heading(ctx, look, sc["heading"])
    items = sc["items"]
    n = len(items)
    ts = item_times(sc, n, times, 0.45, 0.16)
    vmax = sc.get("max") or max(it.get("value", 0) for it in items) * 1.08
    if look.v:
        top = look.top + hh + 50
        rh = min(150, (look.bottom - top) / n)
        bh = min(58, rh * 0.5)
        bx0, bx1 = 410, 860
        for i, it in enumerate(items):
            p = ctx.ap(ts[i], 0.4)
            cy = top + i * rh + rh / 2
            if it.get("flag"):
                ctx.flag(it["flag"], look.left, cy, 50, "lm", p)
            nm = it["name"]
            ctx.text(look.left + (78 if it.get("flag") else 0), cy, nm, fit(nm, 38, "bold", 250), INK, "bold", "lm", a=p)
            pb = ctx.ap(ts[i] + 0.1, 0.8)
            col = color_of(it, sc)
            bw = max(0.0, (bx1 - bx0) * it.get("value", 0) / vmax * pb)
            if bw > 2:
                ctx.rrect(bx0, cy - bh / 2, bw, bh, 10, fill=col, a=p)
            lab = it.get("label") or value_text(it, pb) + it.get("unit", "")
            ctx.text(bx0 + bw + 14, cy, lab, 46, col, "black", "lm", a=p)
        return
    top = look.top + 120
    rh = min(112, (look.bottom - top) / n)
    bh = min(64, rh * 0.62)
    bx0, bx1 = look.left + 430, look.right - 230
    for i, it in enumerate(items):
        p = ctx.ap(ts[i], 0.4)
        cy = top + i * rh + rh / 2
        if it.get("flag"):
            ctx.flag(it["flag"], look.left + 10, cy, min(64, rh * 0.62), "lm", p)
        nx = look.left + (120 if it.get("flag") else 10)
        ctx.text(nx, cy, it["name"], fit(it["name"], 42, "bold", bx0 - nx - 24), INK, "bold", "lm", a=p)
        pb = ctx.ap(ts[i] + 0.1, 0.8)
        col = color_of(it, sc)
        bw = max(0.0, (bx1 - bx0) * it.get("value", 0) / vmax * pb)
        if bw > 2:
            ctx.rrect(bx0, cy - bh / 2, bw, bh, 10, fill=col, a=p)
        lab = it.get("label") or value_text(it, pb) + it.get("unit", "")
        ctx.text(bx0 + bw + 20, cy, lab, 48, col, "black", "lm", a=p)
        if it.get("note"):
            ctx.text(bx0 + bw + 24 + text_sprite(lab, 48, col, "black").width, cy + 4, it["note"], 28, SUB, "medium", "lm", a=p)


def draw_list(ctx, look, sc, T, times, numbered=None):
    if numbered is None:
        numbered = sc.get("numbered", True)
    hh = heading(ctx, look, sc["heading"])
    items = [it if isinstance(it, dict) else {"text": it} for it in sc["items"]]
    n = len(items)
    ts = []
    for i, it in enumerate(items):
        at = it.get("at", i if sc.get("by_line", True) else None)
        ts.append(times[at] if at is not None and at < len(times) else 0.45 + 0.25 * i)
    size = sc.get("size", 50 if not look.v else 50)
    top = look.top + hh + (70 if not look.v else 60)
    maxw = (look.right - look.left - 150)
    heights = [size * 1.32 * len(wrap_bal(it["text"], size, "bold", maxw)) for it in items]
    gap = min(48, (look.bottom - top - sum(heights)) / max(1, n - 1)) if n > 1 else 0
    y = top
    for i, it in enumerate(items):
        p = ctx.ap(ts[i], 0.4)
        x0 = look.left + 30 * (1 - p)
        if numbered:
            ctx.rrect(x0, y + size * 0.62 - 34, 68, 68, 34, fill=RED if it.get("hl") else INK, a=p)
            ctx.text(x0 + 34, y + size * 0.62, str(i + 1), 40, WHITE, "black", "mm", a=p)
        else:
            ctx.rrect(x0 + 18, y + size * 0.62 - 12, 24, 24, 12, fill=RED, a=p)
        ctx.lines(x0 + 110, y, it["text"], size, INK, "bold", maxw=maxw, lh=1.32, a=p)
        y += heights[i] + gap


def draw_big(ctx, look, sc, T, times):
    W = look.W
    cy = (look.top + look.bottom) / 2
    p0 = ctx.ap(0.1)
    if sc.get("pre"):
        ctx.lines(W / 2, cy - (190 if not look.v else 260), sc["pre"], 52, SUB, "bold", maxw=W - 200, anchor="mm", a=p0)
    at = sc.get("at")
    t1 = times[at] if at is not None and at < len(times) else 0.35
    p1 = ctx.ap(t1, 0.5)
    pv = ctx.ap(t1, 1.0)
    col = RED if sc.get("red", True) else INK
    if "value" in sc:
        s = sc.get("prefix", "") + fmt_num(sc["value"] * pv, sc.get("dec", 0))
        vsp = text_sprite(s, sc.get("size", 200), col, "black")
        usp = text_sprite(sc.get("unit", ""), 90, col, "black") if sc.get("unit") else None
        tw = vsp.width + (usp.width + 8 if usp else 0)
        sc_ = 0.92 + 0.08 * p1
        ctx.paste(vsp, W / 2 - tw / 2, cy - vsp.height / 2 + 10 * (1 - p1), p1)
        if usp:
            ctx.paste(usp, W / 2 - tw / 2 + vsp.width + 8, cy + vsp.height / 2 - usp.height - 14, p1)
    else:
        ctx.lines(W / 2, cy + 14 * (1 - p1), sc["text"], sc.get("size", 120 if not look.v else 104), col, "black", maxw=W - 160, lh=1.18, anchor="mm", a=p1)
    if sc.get("sub"):
        at2 = sc.get("sub_at")
        t2 = times[at2] if at2 is not None and at2 < len(times) else t1 + 0.4
        p2 = ctx.ap(t2)
        ctx.lines(W / 2, cy + (170 if not look.v else 230), sc["sub"], 48, INK, "bold", maxw=W - 200, anchor="mt", a=p2)


def draw_table(ctx, look, sc, T, times):
    hh = heading(ctx, look, sc["heading"])
    cols = sc["cols"]
    rows = sc["rows"]
    widths = sc.get("widths") or [1] * len(cols)
    tw = look.right - look.left
    xs = [look.left]
    for w in widths:
        xs.append(xs[-1] + tw * w / sum(widths))
    top = look.top + hh + 50
    rh = min(96, (look.bottom - top - 80) / len(rows))
    p = ctx.ap(0.3)
    ctx.rrect(look.left, top, tw, 74, 14, fill=INK, a=p)
    for j, c in enumerate(cols):
        ctx.text((xs[j] + xs[j + 1]) / 2 if j else xs[j] + 30, top + 37, c, 36, WHITE, "bold", "mm" if j else "lm", a=p)
    ts = item_times({"at": sc.get("at")}, len(rows), times, 0.6, 0.22)
    for i, r in enumerate(rows):
        pr = ctx.ap(ts[i], 0.4)
        y = top + 84 + i * rh
        code = r[0]
        hl = code == sc.get("highlight", "jp")
        ctx.rrect(look.left, y, tw, rh - 10, 12, fill=PALE_RED if hl else WHITE, outline=RED if hl else None, width=3 if hl else 0, a=pr)
        cy = y + (rh - 10) / 2
        ctx.flag(code, xs[0] + 26, cy, min(54, rh * 0.55), "lm", pr)
        ctx.text(xs[0] + 112, cy, r[1], 40, INK, "bold", "lm", a=pr)
        for j, cell in enumerate(r[2:], start=1):
            ctx.text((xs[j] + xs[j + 1]) / 2, cy, cell, 42, RED if hl else INK, "black" if j == 1 else "bold", "mm", a=pr)


def draw_flow(ctx, look, sc, T, times):
    hh = heading(ctx, look, sc["heading"])
    items = sc["items"]
    n = len(items)
    ts = item_times(sc, n, times, 0.45, 0.35)
    if look.v:
        top = look.top + hh + 50
        bh = min(190, (look.bottom - top - 70 * (n - 1)) / n)
        for i, it in enumerate(items):
            p = ctx.ap(ts[i], 0.45)
            y = top + i * (bh + 70)
            hl = it.get("hl")
            ctx.rrect(look.left, y + 20 * (1 - p), look.right - look.left, bh, 22, fill=RED if hl else WHITE, shadow=8, a=p)
            ctx.text(look.W / 2, y + bh * 0.33 + 20 * (1 - p), it["label"], 40, WHITE if hl else SUB, "bold", "mm", a=p)
            ctx.text(look.W / 2, y + bh * 0.68 + 20 * (1 - p), it["value"], 70, WHITE if hl else INK, "black", "mm", a=p)
            if i < n - 1:
                ctx.text(look.W / 2, y + bh + 35, "▼", 40, GRAY, "black", "mm", a=ctx.ap(ts[i + 1] - 0.1))
        return
    gap = 90
    bw = (look.right - look.left - gap * (n - 1)) / n
    y = look.top + 200
    bh = 360
    for i, it in enumerate(items):
        p = ctx.ap(ts[i], 0.45)
        x = look.left + i * (bw + gap)
        hl = it.get("hl")
        ctx.rrect(x, y + 24 * (1 - p), bw, bh, 26, fill=RED if hl else WHITE, shadow=10, a=p)
        ls_ = it["label"]
        ctx.text(x + bw / 2, y + 80 + 24 * (1 - p), ls_, fit(ls_, 40, "bold", bw - 40), WHITE if hl else SUB, "bold", "mt", a=p)
        vls = it["value"].split("\n")
        vs_ = min(fit(v, 76, "black", bw - 44) for v in vls)
        ctx.lines(x + bw / 2, y + 230 + 24 * (1 - p), it["value"], vs_, WHITE if hl else INK, "black", maxw=bw, lh=1.15, anchor="mm", a=p)
        if it.get("note"):
            ctx.lines(x + bw / 2, y + bh + 40, it["note"], 30, SUB, "medium", maxw=bw, anchor="mt", a=p)
        if i < n - 1:
            ctx.text(x + bw + gap / 2, y + bh / 2, "▶", 46, GRAY, "black", "mm", a=ctx.ap(ts[i + 1] - 0.1))


def draw_outro(ctx, look, sc, T, times):
    draw_list(ctx, look, dict(sc, by_line=sc.get("by_line", True)), T, times, numbered=False)
    if sc.get("cta"):
        at = sc.get("cta_at", len(times) - 1)
        p = ctx.ap(times[at] if at < len(times) else T - 2, 0.5)
        y = look.bottom - (130 if not look.v else 40)
        sp = text_sprite(sc["cta"], 46, WHITE, "bold")
        ctx.rrect(look.W / 2 - sp.width / 2 - 40, y - 46, sp.width + 80, 92, 46, fill=RED, a=p)
        ctx.paste(sp, look.W / 2 - sp.width / 2, y - sp.height / 2, p)


@lru_cache(16)
def stamp_sprite(s, size):
    sp = text_sprite(s, size, RED, "black")
    pad = 26
    im = Image.new("RGBA", (sp.width + pad * 2, sp.height + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((4, 4, im.width - 5, im.height - 5), 16, fill=(255, 255, 255, 235), outline=RED, width=7)
    im.alpha_composite(sp, (pad, pad))
    return im.rotate(-6, resample=Image.BICUBIC, expand=True)


def draw_point(ctx, look, sc, T, times):
    """ツッコミどころ：赤い札＋大きな一文＋（あれば）2国の比べ＋「おかしくない？」の判子。全体を上下の中央に置く。"""
    W = look.W
    size = sc.get("size", 80 if not look.v else 66)
    maxw = W - (300 if not look.v else 120)
    text_h = size * 1.25 * (len(wrap_bal(sc["text"], size, "black", maxw)) - 1) + size
    pair = sc.get("pair")
    n = len(pair) if pair else 0
    pbh = (180 if look.v else 230)
    pair_h = (n * (pbh + 30) - 30 if look.v else pbh) if pair else 0
    stamp_h = 0 if (pair and not look.v) else 150
    total = 70 + 50 + text_h + (60 + pair_h if pair else 0) + stamp_h
    y0 = (look.top + look.bottom) / 2 - total / 2 - (10 if not look.v else 0)
    p0 = ctx.ap(0.05)
    lab = sc.get("label", "ツッコミどころ")
    sp = text_sprite(lab, 42, WHITE, "black")
    ctx.rrect(W / 2 - sp.width / 2 - 34, y0, sp.width + 68, sp.height + 28, (sp.height + 28) // 2, fill=RED, a=p0)
    ctx.paste(sp, W / 2 - sp.width / 2, y0 + 14, p0)
    p1 = ctx.ap(0.25, 0.5)
    y = y0 + 120
    ctx.lines(W / 2, y + 14 * (1 - p1), sc["text"], size, INK, "black", maxw=maxw, lh=1.25, anchor="mt", a=p1)
    y += text_h + 60
    stamp_xy = (W / 2, y + 60)
    if pair:
        ts = item_times(dict(sc, items=pair), n, times, 0.6, 0.3)
        if look.v:
            for i, it in enumerate(pair):
                p = ctx.ap(ts[i], 0.45)
                yy = y + i * (pbh + 30) + 20 * (1 - p)
                hl = it.get("flag") == "jp"
                ctx.rrect(look.left, yy, look.right - look.left, pbh, 22, fill=PALE_RED if hl else WHITE, outline=RED if hl else None, width=4 if hl else 0, shadow=8, a=p)
                ctx.flag(it["flag"], look.left + 30, yy + 50, 52, "lm", p)
                ctx.text(look.left + 102, yy + 50, it["name"], 36, INK, "bold", "lm", a=p)
                ctx.text(look.left + 30, yy + 124, it["text"], fit(it["text"], 50, "black", look.right - look.left - 60, 30), RED if hl else INK, "black", "lm", a=p)
            stamp_xy = (W / 2, y + pair_h + 85)
        else:
            gap = 50
            bw = (look.right - look.left - 200 - gap * (n - 1)) / n
            for i, it in enumerate(pair):
                p = ctx.ap(ts[i], 0.45)
                x = look.left + 100 + i * (bw + gap)
                yy = y + 20 * (1 - p)
                hl = it.get("flag") == "jp"
                ctx.rrect(x, yy, bw, pbh, 24, fill=PALE_RED if hl else WHITE, outline=RED if hl else None, width=4 if hl else 0, shadow=10, a=p)
                fw = flag_sprite(it["flag"], 62).width
                nm = text_sprite(it["name"], 40, INK, "bold")
                gx = x + bw / 2 - (fw + 16 + nm.width) / 2
                ctx.flag(it["flag"], gx, yy + 62, 62, "lm", p)
                ctx.paste(nm, gx + fw + 16, yy + 62 - nm.height / 2, p)
                ctx.text(x + bw / 2, yy + 158, it["text"], fit(it["text"], 56, "black", bw - 50, 34), RED if hl else INK, "black", "mm", a=p)
                if hl:
                    stamp_xy = (x + bw - 60, yy - 10)
    st = sc.get("stamp")
    if st:
        at = sc.get("stamp_at", len(times) - 1)
        t = times[at] if at < len(times) else T - 1.5
        p = ctx.ap(t, 0.25)
        im = stamp_sprite(st, 60 if (pair and not look.v) else 66)
        k = 1.35 - 0.35 * p  # 少し大きく出て、押したように縮む
        if not ctx.collect and p > 0:
            im = im.resize((int(im.width * k), int(im.height * k)), Image.BICUBIC)
        ctx.paste(im, stamp_xy[0] - im.width / 2, stamp_xy[1] - im.height / 2, p)


DRAW = {"point": draw_point, "title": draw_title, "chapter": draw_chapter, "compare": draw_compare, "bars": draw_bars, "list": draw_list,
        "big": draw_big, "table": draw_table, "flow": draw_flow, "outro": draw_outro}


def draw_caption(ctx, look, s):
    if not s:
        return
    ls = wrap_bal(s, look.cap_size, "bold", look.cap_maxw)[:3]
    sps = [text_sprite(l, look.cap_size, INK, "bold") for l in ls]
    lh = look.cap_size * 1.42
    w = max(sp.width for sp in sps) + 80
    h = lh * len(ls) + 34
    y0 = look.cap_y if look.v else look.cap_y + 40 - h  # 縦長は上を、横長は下をそろえる
    ctx.rrect(look.W / 2 - w / 2, y0, w, h, 18, fill=WHITE, shadow=8)
    for i, sp in enumerate(sps):
        ctx.paste(sp, look.W / 2 - sp.width / 2, y0 + 17 + i * lh + (lh - sp.height) / 2)


def draw_source(ctx, look, ep, sc):
    keys = sc.get("source")
    if not keys:
        return
    keys = [keys] if isinstance(keys, str) else keys
    label = "出典：" + "／".join(ep["sources"][k]["label"] for k in keys)
    if look.v:
        ctx.lines(look.W / 2, look.src_y, label, 24, SUB, "medium", maxw=960, lh=1.3, anchor="mt")
    else:
        ctx.text(look.W - 40, 1056, label, 22, SUB, "medium", "rm")


# ---------- 時間割 ----------
def voice_path(ep, s):
    instr = ep.get("voice_instructions", V.DEFAULT_INSTR)
    return ROOT / "seido" / "voice" / ep["id"] / f"{V.key(V.spoken(s), ep.get('voice', 'nova'), instr)}.m4a"


@lru_cache(None)
def duration(path, text):
    p = pathlib.Path(path)
    if p.exists():
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True).stdout.strip()
        return float(out)
    return max(1.2, len(text) / 7.2)  # 声がまだ無いときの見積もり


def plan(ep):
    """場面ごとに、長さ（コマ数）と各文の始まり・終わりを決める。"""
    out, frame = [], 0
    for sc in ep["scenes"]:
        says = sc.get("say", [])
        t = sc.get("lead", LEAD if says else 0)
        clips = []
        for s in says:
            d = duration(str(voice_path(ep, s)), V.spoken(s))
            clips.append((t, t + d, s))
            t += d + sc.get("gap", GAP)
        T = (t - sc.get("gap", GAP) + sc.get("pad", PAD)) if says else sc.get("dur", 2.5)
        T = max(T, sc.get("min", 0))
        n = int(round(T * FPS))
        out.append({"scene": sc, "start": frame, "frames": n, "clips": clips})
        frame += n
    return out, frame


def caption_at(clips, t):
    for i, (a, b, s) in enumerate(clips):
        nxt = clips[i + 1][0] if i + 1 < len(clips) else b + 0.25
        if a - 0.05 <= t < max(b + 0.2, nxt - 0.02 if nxt - b < 0.6 else b + 0.2):
            return i, plain(V.shown(s))
    return -1, ""


def render_scene(args):
    spec_path, idx, out_path = args
    ep = json.loads(pathlib.Path(spec_path).read_text(encoding="utf-8"))
    look = Look(tuple(ep["size"]))
    plans, _ = plan(ep)
    pl = plans[idx]
    sc = pl["scene"]
    T = pl["frames"] / FPS
    times = [c[0] for c in pl["clips"]]
    bg = background(look, ep)
    draw = DRAW[sc["type"]]
    instant = bool(sc.get("instant"))
    col = Ctx(None, 0, collect=True)
    draw(col, look, sc, T, times)
    windows = col.windows
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{look.W}x{look.H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
                           "-g", "60", str(out_path)], stdin=subprocess.PIPE)
    last_key, last = None, None
    for f in range(pl["frames"]):
        t = f / FPS
        fade = 1 - ease((t - (T - FADE_OUT)) / FADE_OUT) if not sc.get("hold") else 1.0
        ci, cap = caption_at(pl["clips"], t)
        key = (ci, round(fade, 3)) + tuple(round(min(1, max(0, (t - a) / d)), 3) if not (instant and a <= 1.5) else 1 for a, d in windows)
        if key != last_key:
            im = bg.copy()
            ctx = Ctx(im, t, instant=instant)
            ctx.fade = fade
            draw(ctx, look, sc, T, times)
            draw_source(ctx, look, ep, sc)
            ctx.fade = 1.0
            draw_caption(ctx, look, cap)
            last = im.convert("RGB").tobytes()
            last_key = key
        ff.stdin.write(last)
    ff.stdin.close()
    ff.wait()
    return out_path


def still(ep, look, t_global, plans):
    for pl in plans:
        if pl["start"] <= t_global * FPS < pl["start"] + pl["frames"]:
            t = t_global - pl["start"] / FPS
            sc = pl["scene"]
            im = background(look, ep)
            ctx = Ctx(im, t, instant=bool(sc.get("instant")))
            DRAW[sc["type"]](ctx, look, sc, pl["frames"] / FPS, [c[0] for c in pl["clips"]])
            draw_source(ctx, look, ep, sc)
            draw_caption(ctx, look, caption_at(pl["clips"], t)[1])
            return im.convert("RGB")


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def build_audio(ep, plans, total_frames, tmp):
    n = int(total_frames / FPS * SR) + SR
    mix = np.zeros((n, 2), np.float32)
    missing = 0
    for pl in plans:
        base = pl["start"] / FPS
        for a, b, s in pl["clips"]:
            p = voice_path(ep, s)
            if not p.exists():
                missing += 1
                continue
            x = decode(p)
            i = int((base + a) * SR)
            mix[i:i + len(x)] += x[: n - i]
    total = total_frames / FPS
    track = ROOT / "assets" / "bgm" / f"{ep.get('bgm_track', 'cruise')}.mp3"
    if track.exists():
        bgm_wav = pathlib.Path(tmp) / "bgm.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(track), "-af",
                        f"loudnorm=I=-20:TP=-2,atrim=0:{total:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0, total - 3):.3f}:d=3",
                        "-ar", str(SR), "-ac", "2", str(bgm_wav)], check=True)
        bg = decode(bgm_wav) * ep.get("bgm_volume", 0.2)
        mix[: len(bg)] += bg[:n]
    out = pathlib.Path(tmp) / "mix.f32"
    mix[: int(total * SR)].tofile(out)
    return out, missing


def main():
    spec_path = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    ep = json.loads(spec_path.read_text(encoding="utf-8"))
    look = Look(tuple(ep["size"]))
    plans, total = plan(ep)
    print(f"{ep['id']}: {len(plans)} 場面, {total / FPS:.1f} 秒")
    if "--stills" in sys.argv:
        ts = [float(x) for x in sys.argv[sys.argv.index("--stills") + 1].split(",")]
        for t in ts:
            still(ep, look, t, plans).save(outdir / f"{ep['id']}_{t:06.1f}.png")
        return
    if "--plan" in sys.argv:
        for pl in plans:
            print(f"{pl['start'] / FPS:7.1f}s  {pl['frames'] / FPS:5.1f}s  {pl['scene']['type']}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        jobs = [(str(spec_path), i, f"{tmp}/s{i:03d}.mp4") for i in range(len(plans))]
        with ProcessPoolExecutor(int(os.environ.get("JOBS", "4"))) as ex:
            segs = list(ex.map(render_scene, jobs))
        lst = pathlib.Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs))
        video = pathlib.Path(tmp) / "video.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)], check=True)
        audio, missing = build_audio(ep, plans, total, tmp)
        if missing:
            print(f"注意: 声がまだ無い文が {missing} 個（無音で作りました）")
        out = outdir / f"{ep['id']}.mp4"
        loud = ep.get("loudness", -18 if look.v else -16)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(audio),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-af", f"loudnorm=I={loud}:TP=-2:LRA=11", "-ar", str(SR), "-movflags", "+faststart", "-shortest", str(out)], check=True)
    chapters = [(pl["start"] / FPS, pl["scene"]["title"]) for pl in plans if pl["scene"]["type"] == "chapter"]
    (outdir / f"{ep['id']}.chapters.json").write_text(json.dumps(chapters, ensure_ascii=False))
    print("done", out)


if __name__ == "__main__":
    main()
