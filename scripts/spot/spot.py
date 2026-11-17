#!/usr/bin/env python3
"""間違い探し（新デザイン）の本編を作る。横長 1920x1080、30コマ/秒で1コマずつ描く。

台本 spot/episodes/<id>.json
  id       : 回のid（出力のファイル名）
  title    : 表紙の大きな題（例「冬の間違い探し」）
  sub      : 表紙の小さな説明（省略可。省略すると「全6問・違いは各5つ」）
  pictures : 絵のid の並び。assets/generated/<絵のid>/ に a.png・b.png・differences.json がある組
  think    : 1問の考える時間（秒、省略すると 30）
  bgm      : 最初の曲（assets/bgm/<名前>.mp3）。同じ組の曲を順につなぐ
  upload   : 投稿用の文（title, description, tags）。<id>.txt に書き出す

流れ：表紙 → 第1問（2枚を左右に並べて考える時間）→ 答え（違いの場所に丸、すぐ左右そろって拡大）
      → 5つ全部の丸 → 第2問 … → 終わりの画面（終了画面の要素を置く場所つき）
spotcheck（画素の比較）に通らない絵は使わない。違いの枠は画素の比較で出た正確な位置を使う。
使い方: spot.py spot/episodes/<id>.json 出力フォルダ [--no-voice]
"""
import hashlib, json, math, os, pathlib, random, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
import render as R  # noqa: E402  （字体・影つきカード・声・効果音を使う）
import spotcheck  # noqa: E402

W, H = 1920, 1080
FPS = 30
FADE = 9
ACC = (206, 58, 66)          # 間違い探しの色（落ち着いた赤）
INK = (28, 28, 34)
SUBINK = (96, 96, 106)
PAPER, PAPER2 = (248, 243, 232), (238, 230, 212)
SERIF = R._first(["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc", R.FONT_BOLD])
TOP, GAP = 150, 36
SIDE = 900                    # 1枚の大きさ（白い縁を含む）
X0 = (W - SIDE * 2 - GAP) // 2
BORDER = 6
INNER = SIDE - BORDER * 2
NUM = "1つめ 2つめ 3つめ 4つめ 5つめ 6つめ 7つめ".split()
LOUDNESS = -18
BGM_DIR = ROOT / "assets" / "bgm"
CALM = ["valley_drive", "you_are_the_only", "cruise"]
LIVELY = ["little_fish", "estela", "wager_with_angels"]
BGM_VOLUME = 0.22


def serif(size):
    return R.ImageFont.truetype(SERIF, max(8, int(size)))


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


# ---------------- 土台 ----------------
def paper():
    g = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(g)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(PAPER[i] * (1 - k) + PAPER2[i] * k) for i in range(3)) + (255,))
    rnd = random.Random(7)
    for _ in range(1400):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        L = rnd.uniform(4, 22)
        c = rnd.randint(205, 228)
        d.line([(x, y), (x + L, y + rnd.uniform(-3, 3))], fill=(c, c - 6, c - 18, 70), width=1)
    return g


def chip(img, text, x, y, h, fill, color=(255, 255, 255), w="heavy", size=None):
    return R.chip(img, text, x, y, h, fill, color=color, w=w) if size is None else _chip(img, text, x, y, h, fill, color, w, size)


def _chip(img, text, x, y, h, fill, color, w, size):
    d = ImageDraw.Draw(img)
    f = R.font(size, w)
    tw = d.textlength(text, font=f)
    pad = h * 0.42
    R.shadow_box(img, (x, y, x + tw + pad * 2, y + h), int(h * 0.22), fill, blur=10, offset=4, alpha=70)
    ImageDraw.Draw(img).text((x + pad, y + h / 2), text, font=f, fill=color, anchor="lm")
    return x + tw + pad * 2


def header(img, label, found=None, total=5, note=None):
    """上の帯：番組名・第何問（見つけた数の丸）・答えの説明。"""
    h, y = 76, 37
    x = chip(img, "間違い探し", 42, y, h, ACC + (255,))
    # 第何問 ＋ 見つけた数
    d = ImageDraw.Draw(img)
    f = R.font(40, "heavy")
    tw = d.textlength(label, font=f)
    dots = total if found is not None else 0
    w = tw + 32 * 2 + (dots * 34 + 14 if dots else 0)
    x0 = x + 14
    R.shadow_box(img, (x0, y, x0 + w, y + h), 17, (255, 255, 255, 248), blur=10, offset=4, alpha=60)
    d = ImageDraw.Draw(img)
    d.text((x0 + 32, y + h / 2), label, font=f, fill=INK, anchor="lm")
    for k in range(dots):
        cx, cy, r = x0 + 32 + tw + 26 + k * 34, y + h / 2, 12
        if k < found:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACC)
        else:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(190, 184, 172), width=4)
    x = x0 + w
    if note:
        fs = 40
        while d.textlength(note, font=R.font(fs, "bold")) > W - x - 120 and fs > 26:
            fs -= 2
        _chip(img, note, x + 14, y, h, (255, 255, 255, 248), INK, "bold", fs)


def stage(label, found=None, note=None):
    """2枚を並べる場面の土台（紙・白い縁の影・上の帯）。"""
    im = paper()
    for j in range(2):
        ox = X0 + j * (SIDE + GAP)
        R.shadow_box(im, (ox, TOP, ox + SIDE, TOP + SIDE), 16, (255, 255, 255, 255), blur=18, offset=8, alpha=80)
    header(im, label, found, note=note)
    return im.convert("RGB")


def ring(d, cx, cy, r, alpha=1.0):
    """白い縁どりの赤い丸（太め）。"""
    for rr, wdt, col in ((r + 5, 14, (255, 255, 255)), (r, 8, ACC)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=wdt)


def compose(base, A, B, crop, rings=(), timer=None, prog=None):
    """1コマを作る。crop = (左, 上, 一辺) を絵の座標で。rings = [(box, 大きさ倍率)]。"""
    l, t, cs = crop
    im = base.copy()
    s = INNER / cs
    for j, src in enumerate((A, B)):
        ox = X0 + j * (SIDE + GAP) + BORDER
        if cs >= src.width - 0.5:
            pic = src.resize((INNER, INNER), Image.LANCZOS) if not hasattr(src, "_full") else src._full
        else:
            pic = src.resize((INNER, INNER), Image.BILINEAR, box=(l, t, l + cs, t + cs))
        pic = pic.copy()
        d = ImageDraw.Draw(pic)
        for (bx, by, bw, bh), k in rings:
            r = (max(bw, bh) / 2 * s + 18) * k
            ring(d, (bx + bw / 2 - l) * s, (by + bh / 2 - t) * s, r)
        mask = Image.new("L", pic.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, INNER, INNER], radius=11, fill=255)
        im.paste(pic, (ox, TOP + BORDER), mask)
    if timer is not None:
        draw_timer(im, *timer)
    if prog is not None:
        d = ImageDraw.Draw(im)
        d.rectangle([0, H - 8, W, H], fill=(40, 36, 32))
        d.rectangle([0, H - 8, W * prog, H], fill=ACC)
    return im


_TIMER = None


def draw_timer(im, remain, n):
    global _TIMER
    Rr, cx, cy = 58, W - 58 - 42, 75
    if _TIMER is None:
        layer = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
        R.shadow_box(layer, (cx - Rr, cy - Rr, cx + Rr, cy + Rr), Rr, R.NAVY + (255,), blur=12, offset=5)
        _TIMER = layer
    im.paste(_TIMER, (0, 0), _TIMER)
    d = ImageDraw.Draw(im)
    w = 8
    bb = [cx - Rr + w, cy - Rr + w, cx + Rr - w, cy + Rr - w]
    d.ellipse(bb, outline=(60, 78, 105), width=w)
    if remain > 0:
        d.arc(bb, -90, -90 + 360 * remain / n, fill=ACC, width=w)
    d.text((cx, cy), str(max(0, math.ceil(remain - 1e-6))), font=R.font(Rr * 0.9, "heavy"), fill=(255, 255, 255), anchor="mm")


def zoom_crop(box, size=1024):
    x, y, w, h = box
    cs = min(max(max(w, h) * 2.8, 300), size)
    cx, cy = x + w / 2, y + h / 2
    l = min(max(cx - cs / 2, 0), size - cs)
    t = min(max(cy - cs / 2, 0), size - cs)
    return (l, t, cs)


def lerp_crop(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


# ---------------- 表紙と終わり ----------------
def title_card(ep, bgpic):
    im = bgpic.convert("RGB").resize((W, W), Image.LANCZOS).crop((0, (W - H) // 2, W, (W - H) // 2 + H))
    im = im.filter(ImageFilter.GaussianBlur(10))
    im = Image.blend(im, Image.new("RGB", (W, H), (250, 247, 240)), 0.35).convert("RGBA")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 34, H], fill=ACC)
    d.rectangle([34, 0, 40, H], fill=(255, 255, 255))
    cx0, cy0, cx1, cy1 = 170, 190, W - 170, H - 190
    R.shadow_box(im, (cx0, cy0, cx1, cy1), 30, (255, 255, 255, 250), blur=26, offset=12, alpha=70)
    d = ImageDraw.Draw(im)
    f = R.font(42, "heavy")
    tw = d.textlength("間違い探し", font=f)
    d.rounded_rectangle([W / 2 - tw / 2 - 34, cy0 - 36, W / 2 + tw / 2 + 34, cy0 + 36], radius=36, fill=ACC)
    d.text((W / 2, cy0), "間違い探し", font=f, fill=(255, 255, 255), anchor="mm")
    fs = 132
    while d.textlength(ep["title"], font=serif(fs)) > (cx1 - cx0) - 140:
        fs *= 0.92
    my = (cy0 + cy1) / 2 - 40
    d.text((W / 2, my), ep["title"], font=serif(fs), fill=INK, anchor="mm")
    d.rounded_rectangle([W / 2 - 90, my + fs * 0.78, W / 2 + 90, my + fs * 0.78 + 10], radius=5, fill=ACC)
    d.text((W / 2, my + fs * 0.78 + 85), ep["sub"], font=R.font(50, "bold"), fill=SUBINK, anchor="mm")
    return im.convert("RGB")


def end_card():
    im = paper()
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 34, H], fill=ACC)
    d.text((140, 250), "全部見つけられましたか？", font=serif(80), fill=INK, anchor="lm")
    d.text((140, 360), "コメントで教えてください", font=R.font(46, "bold"), fill=SUBINK, anchor="lm")
    R.shadow_box(im, (140, 470, 860, 640), 24, ACC + (255,), blur=16, offset=8)
    d = ImageDraw.Draw(im)
    d.text((500, 525), "チャンネル登録", font=R.font(64, "heavy"), fill=(255, 255, 255), anchor="mm")
    d.text((500, 600), "毎日の頭の体操をお届けします", font=R.font(36, "bold"), fill=(255, 255, 255), anchor="mm")
    d.text((140, 760), "▶ 次の間違い探しもどうぞ", font=R.font(46, "heavy"), fill=ACC, anchor="lm")

    def dashed(box):
        x0, y0, x1, y1 = box
        for x in range(int(x0), int(x1), 22):
            d.line([(x, y0), (min(x + 11, x1), y0)], fill=(200, 195, 185), width=4)
            d.line([(x, y1), (min(x + 11, x1), y1)], fill=(200, 195, 185), width=4)
        for y in range(int(y0), int(y1), 22):
            d.line([(x0, y), (x0, min(y + 11, y1))], fill=(200, 195, 185), width=4)
            d.line([(x1, y), (x1, min(y + 11, y1))], fill=(200, 195, 185), width=4)
    dashed((1000, 200, 1780, 640))
    d.ellipse([1290, 700, 1490, 900], outline=(200, 195, 185), width=4)
    return im.convert("RGB")


def thumbnail(ep, A, B, out):
    """サムネイル 1280x720：2枚を並べ、上に大きな題、下に問いかけ。"""
    TW, TH = 1280, 720
    im = Image.new("RGBA", (TW, TH), PAPER + (255,))
    side, gap, top = 600, 24, 150
    x0 = (TW - side * 2 - gap) // 2
    for j, src in enumerate((A, B)):
        p = src.resize((side, side), Image.LANCZOS).crop((0, 30, side, 30 + TH - top - 20))
        im.paste(p, (x0 + j * (side + gap), top))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, TW, top - 12], fill=(255, 255, 255))
    d.rectangle([0, top - 12, TW, top - 4], fill=ACC)
    f = serif(84)
    t = ep["title"]
    while d.textlength(t, font=f) > TW - 380:
        f = serif(f.size * 0.92)
    d.text((40, (top - 12) / 2), t, font=f, fill=INK, anchor="lm")
    badge = ep.get("badge", f"全{ep['n']}問")
    fb = R.font(56, "heavy")
    bw = d.textlength(badge, font=fb) + 60
    d.rounded_rectangle([TW - bw - 30, 26, TW - 30, top - 38], radius=18, fill=ACC)
    d.text((TW - 30 - bw / 2, (top - 12) / 2), badge, font=fb, fill=(255, 255, 255), anchor="mm")
    # 下の帯：問いかけ
    tag = ep.get("tagline", "違いは5つ　全部わかる？")
    ft = R.font(60, "heavy")
    tw = d.textlength(tag, font=ft) + 80
    R.shadow_box(im, ((TW - tw) / 2, TH - 118, (TW + tw) / 2, TH - 26), 20, (255, 214, 64, 255), blur=12, offset=6, alpha=90)
    ImageDraw.Draw(im).text((TW / 2, TH - 72), tag, font=ft, fill=INK, anchor="mm")
    im.convert("RGB").save(out, quality=92)


# ---------------- 音 ----------------
def bgm_track(first, seconds, out):
    first = first if (BGM_DIR / f"{first}.mp3").exists() else "little_fish"
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


class Voice:
    def __init__(self, tmp, no_voice):
        self.tmp, self.no_voice, self.n = tmp, no_voice, 0

    def __call__(self, text):
        self.n += 1
        p = str(self.tmp / f"v{self.n:03d}.wav")
        if self.no_voice:
            R.silence(max(1.2, len(text) * 0.13), p)
        else:
            R.tts(text, p)
        return p, R.dur(p)


# ---------------- 本体 ----------------
def load_pictures(ids):
    used = []
    for gid in ids:
        g = ROOT / "assets" / "generated" / gid
        res = json.loads((g / "result.json").read_text()) if (g / "result.json").exists() else {}
        if res.get("status") != "ok":
            print("skip", gid, res.get("status") or "まだ届いていない"); continue
        ok, msg, diffs = spotcheck.check(g / "a.png", g / "b.png", g / "differences.json")
        print("spotcheck", gid, msg)
        if not ok:
            continue
        A = Image.open(g / "a.png").convert("RGB")
        B = Image.open(g / "b.png").convert("RGB")
        if A.size != (1024, 1024):
            A, B = A.resize((1024, 1024), Image.LANCZOS), B.resize((1024, 1024), Image.LANCZOS)
        A._full = A.resize((INNER, INNER), Image.LANCZOS)
        B._full = B.resize((INNER, INNER), Image.LANCZOS)
        # 左上から右下の順に答える（目で追いやすい）
        diffs.sort(key=lambda d: (round((d["box"][1] + d["box"][3] / 2) / 256), d["box"][0]))
        used.append((gid, A, B, diffs))
    return used


def render(ep, out_dir, no_voice=False):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    pics = load_pictures(ep["pictures"])
    if not pics:
        raise SystemExit("使える絵がない")
    n = len(pics)
    ep["n"] = n
    ep.setdefault("sub", f"全{n}問・違いは各{len(pics[0][3])}つ")
    think = int(ep.get("think", 30))
    voice = Voice(tmp, no_voice)
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    R.tone(tick, "tick"); R.tone(chime, "chime")

    ff_out = tmp / "video.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-maxrate", "6M", "-bufsize", "12M",
                           "-pix_fmt", "yuv420p", str(ff_out)], stdin=subprocess.PIPE)
    state = {"frames": 0, "last": None, "fade": 0}
    audio, sheet = [], []

    def now():
        return state["frames"] / FPS

    def put(im, fade=False):
        if fade:
            state["fade"] = FADE
        if state["fade"] and state["last"] is not None:
            k = FADE - state["fade"] + 1
            im = Image.blend(state["last_im"], im, ease(k / (FADE + 1)))
            state["fade"] -= 1
        b = im.tobytes()
        ff.stdin.write(b)
        state["frames"] += 1
        state["last"], state["last_im"] = b, im

    def hold(sec):
        for _ in range(int(round(sec * FPS))):
            if state["fade"]:
                put(state["last_im"])
            else:
                ff.stdin.write(state["last"])
                state["frames"] += 1

    # 表紙（ゆっくり寄る）
    tc = title_card(ep, pics[0][1])
    sheet.append(tc)
    v, vl = voice(f"{ep['title']}。全{n}問です。左と右の絵で、違うところを5つずつ探してください。")
    audio.append((now() + 0.4, v))
    L = max(3.5, vl + 0.9)
    nf = int(L * FPS)
    for i in range(nf):
        s = 1.0 + 0.035 * i / nf
        cw, ch = W / s, H / s
        put(tc.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)))

    full = (0, 0, 1024)
    for q, (gid, A, B, diffs) in enumerate(pics, 1):
        m = len(diffs)
        label = f"第{q}問"
        # 考える時間
        base = stage(label, 0)
        v, vl = voice(f"第{q}問。違いは{m}つです。")
        audio.append((now() + 0.3, v))
        first = compose(base, A, B, full)
        sheet.append(first)
        nf = think * FPS
        tstart = now()
        for i in range(nf):
            remain = think * (1 - i / nf)
            im = compose(base, A, B, full, timer=(remain, think), prog=remain / think)
            put(im, fade=(i == 0))
        for k in range(think):
            if think - k <= 10:
                audio.append((tstart + k, tick))
        # 答え
        cur = full
        found = []
        for j, df in enumerate(diffs):
            box = df["box"]
            note = df["note"].rstrip("。")
            txt = (f"答えです。{NUM[j]}。" if j == 0 else f"{NUM[j]}。") + f"{note}。"
            v, vl = voice(txt)
            base = stage(label, j + 1, note=note)
            # ① 前の拡大から全体へ戻る
            if cur != full:
                for i in range(int(0.35 * FPS)):
                    k = ease(i / (0.35 * FPS - 1))
                    put(compose(base, A, B, lerp_crop(cur, full, k), [(b, 1.0) for b in found]))
            t0 = now()
            audio.append((t0, chime))
            audio.append((t0 + 0.12, v))
            # ② 丸がポンと出る
            for i in range(int(0.3 * FPS)):
                k = 1.45 - 0.45 * ease_out(i / (0.3 * FPS - 1))
                put(compose(base, A, B, full, [(b, 1.0) for b in found] + [(box, k)]), fade=(j == 0 and i == 0))
            found.append(box)
            # ③ 左右そろって拡大
            target = zoom_crop(box)
            for i in range(int(0.5 * FPS)):
                k = ease(i / (0.5 * FPS - 1))
                put(compose(base, A, B, lerp_crop(full, target, k), [(b, 1.0) for b in found]))
            if j == 0:
                sheet.append(compose(base, A, B, target, [(b, 1.0) for b in found]))
            cur = target
            hold(max(0.6, t0 + 0.12 + vl + 0.35 - now()))
        # 全部の丸を見せる
        base = stage(label, m, note=f"違いは この{m}つ")
        for i in range(int(0.45 * FPS)):
            k = ease(i / (0.45 * FPS - 1))
            put(compose(base, A, B, lerp_crop(cur, full, k), [(b, 1.0) for b in found]))
        hold(1.4)

    # 終わり
    ec = end_card()
    sheet.append(ec)
    v, vl = voice("全部見つけられましたか？何問できたか、コメントで教えてください。毎日の頭の体操に、ぜひチャンネル登録をお願いします。また次の間違い探しで、お会いしましょう。")
    audio.append((now() + 0.5, v))
    put(ec, fade=True)
    hold(max(16, vl + 1.5))
    ff.stdin.close()
    ff.wait()
    total = now()

    # 音：声と効果音、BGM（声の間は下げる）
    def mixdown(parts, out):
        inputs, filt = [], []
        for k, (start, path) in enumerate(parts):
            inputs += ["-i", path]
            ms = int(start * 1000)
            filt.append(f"[{k}:a]aresample={R.SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
        mix = "".join(f"[a{k}]" for k in range(len(parts)))
        filt.append(f"{mix}amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.3f}[o]")
        script = tmp / f"{pathlib.Path(out).stem}.filter"
        script.write_text(";".join(filt))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", str(script), "-map", "[o]", "-ar", str(R.SR), out],
                       check=True)

    vparts = [(s, p) for s, p in audio if pathlib.Path(p).name.startswith("v")]
    sparts = [(s, p) for s, p in audio if not pathlib.Path(p).name.startswith("v")]
    vw, sw, mw = str(tmp / "voice.wav"), str(tmp / "sfx.wav"), str(tmp / "bgm.wav")
    mixdown(vparts, vw)
    mixdown(sparts, sw)
    bgm_track(ep.get("bgm", "little_fish"), total, mw)
    fc = (f"[1:a]volume={ep.get('bgm_volume', BGM_VOLUME)}[m];[2:a]volume=0.55[s];[0:a]asplit=2[v1][v2];"
          f"[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=450[md];"
          f"[v1][md][s]amix=inputs=3:normalize=0[o]")
    aw = tmp / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vw, "-i", mw, "-i", sw, "-filter_complex", fc, "-map", "[o]", "-ar", str(R.SR), str(aw)],
                   check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ff_out), "-i", str(aw), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-af", f"loudnorm=I={LOUDNESS}:TP=-2:LRA=11", "-ar", str(R.SR), "-movflags", "+faststart", "-shortest", str(out)], check=True)
    # 確認用の一覧、サムネイル、投稿用の文
    th = [s.resize((480, 270)) for s in sheet[:15]]
    S = Image.new("RGB", (480 * 3, 270 * math.ceil(len(th) / 3)))
    for k, s in enumerate(th):
        S.paste(s, ((k % 3) * 480, (k // 3) * 270))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    gid, A, B, diffs = pics[0]
    thumbnail(ep, A, B, out_dir / f"{ep['id']}_thumb.jpg")
    up = ep.get("upload")
    if up:
        txt = (f"タイトル：\n{up['title']}\n\n説明文：\n{up['description']}\n\nタグ：\n{', '.join(up['tags'])}\n\n"
               f"形式：通常の動画（横長）\nサムネイル：{ep['id']}_thumb.jpg\n"
               "アップロード時の設定：「改変または合成されたコンテンツ」は「はい」\n")
        (out_dir / f"{ep['id']}.txt").write_text(txt, encoding="utf-8")
    print(out, f"{total:.1f}s", f"{n}問")


if __name__ == "__main__":
    ep = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    render(ep, sys.argv[2], "--no-voice" in sys.argv)
