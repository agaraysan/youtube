#!/usr/bin/env python3
# 動画は previews 枝に最新分だけ置く。投稿して公開を確かめた動画は消し、台本と設定だけを残す。
"""設計JSON（episodes/<id>.json）から動画を作る。

エピソードの共通項目
  id, series（画面左上の番組名）, style（match / riddle / spot：色とBGMが変わる）, bg（背景画像）
  puzzle（マッチ棒）, spot（間違い探し：a, b, list）, bgm（false で無音）, bgm_volume
scene の種類
  title   : 番組の表紙（text, sub）
  match   : マッチ棒の式（state: question / move / move2 / answer）
  riddle  : なぞなぞの問題カード（riddle）。answer があれば答えカード
  think   : 考える時間（seconds）。images があれば間違い探しの2枚を出したまま
  circles : 間違い探しの2枚＋答えの丸（upto）
  zoom    : 違い1か所を左右とも切り抜いて拡大（index）
共通: text（左上の見出し）, caption（下の字幕カード）, voice（nova の読み上げ）, chime, seconds, pad
使い方: render.py episodes/<id>.json out_dir [--no-voice]
"""
import json, os, pathlib, subprocess, sys, tempfile, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import matchstick as M
import spotcheck
import bgm as BGM

ROOT = pathlib.Path(__file__).resolve().parents[2]
FPS = 30
SR = 48000


def _first(paths):
    return next((p for p in paths if p and os.path.exists(p)), None)


FONT_HEAVY = _first(["/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                     "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"])
FONT_BOLD = _first(["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"])

# ---- デザイン（色） ----
NAVY = (14, 27, 46)
NAVY2 = (28, 48, 78)
WHITE = (255, 255, 255)
INK = (20, 30, 45)
MUTED = (195, 205, 220)
ACCENT = {"match": (255, 138, 31), "riddle": (24, 182, 160), "spot": (255, 77, 94)}


def font(size, w="bold"):
    return ImageFont.truetype(FONT_HEAVY if w == "heavy" else FONT_BOLD, max(8, int(size)))


def accent(ep):
    return ACCENT.get(ep.get("style", "match"), ACCENT["match"])


def shadow_box(img, box, radius, fill, blur=18, offset=8, alpha=110):
    """影つきの角丸カード。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + offset, x1, y1 + offset], radius=radius, fill=(0, 0, 0, alpha))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    img.alpha_composite(ov)


def wrap(d, text, f, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if d.textlength(cur + ch, font=f) > max_w and cur:
                lines.append(cur); cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def chip(img, text, x, y, h, fill, color=WHITE, w="heavy"):
    """角丸のラベル。右端の x を返す。"""
    d = ImageDraw.Draw(img)
    f = font(h * 0.56, w)
    tw = d.textlength(text, font=f)
    pad = h * 0.42
    shadow_box(img, (x, y, x + tw + pad * 2, y + h), int(h * 0.22), fill, blur=10, offset=4, alpha=90)
    ImageDraw.Draw(img).text((x + pad, y + h / 2), text, font=f, fill=color, anchor="lm")
    return x + tw + pad * 2


def header(img, ep, sc, H):
    """左上：番組名のラベル＋見出し。"""
    u = H / 1080
    x = chip(img, ep["series"], 48 * u, 32 * u, 76 * u, accent(ep)) if ep.get("series") else 48 * u
    if sc.get("text"):
        chip(img, sc["text"], x + 14 * u, 32 * u, 76 * u, (255, 255, 255, 242), color=INK)


def caption(img, ep, text, H):
    """下の字幕カード（白地・左に色の線）。"""
    W = img.width
    u = H / 1080
    d = ImageDraw.Draw(img)
    f = font(56 * u, "bold")
    lines = wrap(d, text, f, W * 0.78)
    lh = 56 * u * 1.45
    h = lh * len(lines) + 40 * u
    w = max(d.textlength(l, font=f) for l in lines) + 130 * u
    x0 = (W - w) / 2
    y0 = H - h - 60 * u
    shadow_box(img, (x0, y0, x0 + w, y0 + h), int(16 * u), (255, 255, 255, 246))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + 14 * u, y0 + h], radius=int(7 * u), fill=accent(ep))
    for i, ln in enumerate(lines):
        d.text((W / 2 + 7 * u, y0 + 20 * u + lh * (i + 0.5)), ln, font=f, fill=INK, anchor="mm")


def bg(path, size, dim=0.0, blur=0, tint=NAVY):
    im = Image.open(ROOT / path).convert("RGB")
    W, H = size
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim:
        im = Image.blend(im, Image.new("RGB", size, tint), dim)
    return im.convert("RGBA")


def panel_bg(size):
    """間違い探しの土台：紺のグラデーション。"""
    W, H = size
    g = Image.new("RGBA", size)
    d = ImageDraw.Draw(g)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(NAVY[i] * (1 - k) + NAVY2[i] * k) for i in range(3)) + (255,))
    return g


def timer(img, ep, k, n, cx, cy, R):
    """タイマー：紺の円＋残りを色の輪で＋数字。"""
    shadow_box(img, (cx - R, cy - R, cx + R, cy + R), R, NAVY + (255,), blur=12, offset=5)
    d = ImageDraw.Draw(img)
    w = max(6, int(R * 0.14))
    bb = [cx - R + w, cy - R + w, cx + R - w, cy + R - w]
    d.ellipse(bb, outline=(60, 78, 105), width=w)
    d.arc(bb, -90, -90 + 360 * k / n, fill=accent(ep), width=w)
    d.text((cx, cy), str(k), font=font(R * 0.9, "heavy"), fill=WHITE, anchor="mm")


def progress_bar(img, ep, frac, H):
    W = img.width
    u = H / 1080
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 10 * u, W, H], fill=(0, 0, 0, 255))
    d.rectangle([0, H - 10 * u, W * frac, H], fill=accent(ep))


def framed(img, src, box, radius):
    """白い縁と影のついた写真。"""
    x, y, w, h = [int(v) for v in box]
    shadow_box(img, (x, y, x + w, y + h), radius, (255, 255, 255, 255), blur=16, offset=8)
    s = src.resize((w - 12, h - 12), Image.LANCZOS)
    mask = Image.new("L", s.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s.width, s.height], radius=max(1, radius - 6), fill=255)
    img.paste(s, (x + 6, y + 6), mask)


def ring(img, cx, cy, r, color, u):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r - 6 * u, cy - r - 6 * u, cx + r + 6 * u, cy + r + 6 * u], outline=WHITE, width=int(16 * u))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=int(10 * u))


# ---- 音 ----
def tts(text, out):
    subprocess.run([sys.executable, str(ROOT / "scripts/tts.py"), out, text], check=True)


def silence(sec, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{sec:.3f}", out], check=True)


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode())


def tone(out, kind):
    """時計の音（tick）と、答えの合図（chime）を合成する。"""
    if kind == "tick":
        expr, d = "0.22*sin(2*PI*1800*t)*exp(-60*t)", 0.08
    else:
        expr, d = "0.16*(sin(2*PI*1046.5*t)+0.5*sin(2*PI*1568*t)+0.3*sin(2*PI*2093*t))*exp(-3.5*t)", 1.4
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc={expr}:s={SR}:d={d}", "-ac", "2", out], check=True)



def reveal_frames(sc, ep, size):
    """間違い探しの答え：丸を出してすぐ、その場所へ左右そろってズームする（声と同時に進む）。
    (画像, 秒) のリストを返す。最後の画像の秒は None（声の長さに合わせて main が決める）。"""
    W, H = size
    u = H / 1080
    a = Image.open(ROOT / sc["images"][0]).convert("RGB")
    b = Image.open(ROOT / sc["images"][1]).convert("RGB")
    x, y, ww, hh = diffs_of(ep, sc)[sc["index"]]["box"]
    top, gap = 140 * u, 36 * u
    side = int(min(H - top - 40 * u, (W - gap * 3) / 2))
    x0 = (W - (side * 2 + gap)) / 2
    cx, cy = x + ww / 2, y + hh / 2
    zs = min(max(max(ww, hh) * 2.6, a.width * 0.3), a.width)  # ズーム後に見せる範囲（正方形）
    base = panel_bg(size)
    header(base, ep, sc, H)
    if sc.get("caption"):
        caption(base, ep, sc["caption"], H)
    out = []
    steps = [0.0] * 1 + [((k + 1) / 14) for k in range(14)]  # 0 = 全体、1 = ズーム
    for n, k in enumerate(steps):
        e = 1 - (1 - k) ** 3  # だんだんゆっくり
        cs = a.width + (zs - a.width) * e
        l = min(max(cx - cs / 2, 0), a.width - cs) * e if e > 0 else 0
        t = min(max(cy - cs / 2, 0), a.height - cs) * e if e > 0 else 0
        im = base.copy()
        for j, src in enumerate((a, b)):
            ox = x0 + j * (side + gap)
            framed(im, src.crop((int(l), int(t), int(l + cs), int(t + cs))), (ox, top, side, side), int(18 * u))
            s = (side - 12) / cs
            ring(im, int(ox) + 6 + (cx - l) * s, int(top) + 6 + (cy - t) * s, max(ww, hh) * s / 2 + (16 + 8 * e) * u, accent(ep), u)
            if e >= 1:
                chip(im, ("左", "右")[j], ox + 22 * u, top + 22 * u, 62 * u, NAVY + (230,))
        out.append((im.convert("RGB"), sc.get("hold_full", 0.6) if n == 0 else 1 / FPS))
    out[-1] = (out[-1][0], None)
    return out

def diffs_of(ep, sc):
    """その場面の絵の違い一覧（1本に絵が何枚もある回は scene の "spot" で選ぶ）。"""
    if sc.get("spot"):
        return ep["diffs_by"][sc["spot"]]
    return ep["differences"]


# ---- 場面 ----
def render_scene(sc, ep, size):
    """1場面の静止画（think の場合は1秒ごとの画像のリスト）を返す。"""
    kind = sc["type"]
    if kind == "reveal":
        return reveal_frames(sc, ep, size)
    W, H = size
    u = H / 1080
    pair = kind in ("image", "circles", "zoom") or (kind == "think" and "images" in sc)
    if pair:
        im = panel_bg(size)
    elif kind == "title":
        im = bg(sc.get("bg", ep["bg"]), size, dim=0.62, blur=14)
    else:
        im = bg(sc.get("bg", ep["bg"]), size, dim=sc.get("dim", 0.12))

    if kind == "title":
        d = ImageDraw.Draw(im)
        if ep.get("series") and sc.get("text") != ep.get("series"):
            d.text((W / 2, H * 0.30), ep["series"], font=font(46 * u, "bold"), fill=accent(ep), anchor="mm")
        d.text((W / 2, H * 0.44), sc["text"], font=font(sc.get("size", 132) * u, "heavy"), fill=WHITE, anchor="mm")
        d.rounded_rectangle([W / 2 - 70 * u, H * 0.44 + 122 * u, W / 2 + 70 * u, H * 0.44 + 134 * u], radius=int(6 * u), fill=accent(ep))
        if sc.get("sub"):
            d.text((W / 2, H * 0.44 + 210 * u), sc["sub"], font=font(54 * u, "bold"), fill=MUTED, anchor="mm")

    has_puzzle = "puzzle" in sc or "puzzle" in ep
    if kind == "match" or (kind == "think" and not pair and has_puzzle):
        st = sc.get("state", "question")
        p = sc.get("puzzle") or ep["puzzle"]
        expr = p["answer"] if st == "answer" else p["question"]
        _, i, s, j, t = p["move"]
        kw = {}
        if st == "move":
            kw = dict(hide=(i, s), highlight=(i, s))
        if st == "move2":
            expr = p["answer"]
            kw = dict(highlight=(j, t))
        M.draw_expr(im, expr, W / 2, H * 0.47, H=int(H * 0.36), **kw)

    if kind == "riddle" or (kind == "think" and not pair and not has_puzzle):
        d = ImageDraw.Draw(im)
        if sc.get("answer"):
            f = font(150 * u, "heavy")
            tw = d.textlength(sc["answer"], font=f)
            w, h = max(tw + 240 * u, 760 * u), 330 * u
            x0, y0 = (W - w) / 2, H * 0.26
            shadow_box(im, (x0, y0, x0 + w, y0 + h), int(28 * u), (255, 255, 255, 248))
            chip(im, "答え", x0 + 40 * u, y0 - 38 * u, 76 * u, accent(ep))
            ImageDraw.Draw(im).text((W / 2, y0 + h / 2 + 10 * u), sc["answer"], font=f, fill=INK, anchor="mm")
        else:
            text = sc.get("riddle", "")
            fs = sc.get("size", 76) * u
            f = font(fs, "bold")
            lines = wrap(d, text, f, W * 0.66)
            lh = fs * 1.5
            h = lh * len(lines) + 110 * u
            w = W * 0.74
            x0, y0 = (W - w) / 2, max(150 * u, (H - h) / 2 - 20 * u)
            shadow_box(im, (x0, y0, x0 + w, y0 + h), int(28 * u), (255, 255, 255, 245))
            d = ImageDraw.Draw(im)
            for k, ln in enumerate(lines):
                d.text((W / 2, y0 + 55 * u + lh * (k + 0.5)), ln, font=f, fill=INK, anchor="mm")

    if kind in ("circles", "image") or (kind == "think" and pair):
        top, gap = 140 * u, 36 * u
        side = min(H - top - 40 * u, (W - gap * 3) / 2)
        x0 = (W - (side * 2 + gap)) / 2
        a = Image.open(ROOT / sc["images"][0]).convert("RGB")
        b = Image.open(ROOT / sc["images"][1]).convert("RGB")
        for k, src in enumerate((a, b)):
            framed(im, src, (x0 + k * (side + gap), top, side, side), int(18 * u))
        if kind == "circles":
            s = (int(side) - 12) / a.width
            for df in diffs_of(ep, sc)[: sc.get("upto", 99)]:
                x, y, ww, hh = df["box"]
                for k in range(2):
                    ox = int(x0 + k * (side + gap)) + 6
                    ring(im, ox + (x + ww / 2) * s, int(top) + 6 + (y + hh / 2) * s, max(ww, hh) * s / 2 + 16 * u, accent(ep), u)

    if kind == "zoom":
        a = Image.open(ROOT / sc["images"][0]).convert("RGB")
        b = Image.open(ROOT / sc["images"][1]).convert("RGB")
        x, y, ww, hh = diffs_of(ep, sc)[sc["index"]]["box"]
        cw = min(max(max(ww, hh * 4 / 3) * 2.4, a.width * 0.28), a.width)
        ch = min(cw * 3 / 4, a.height)
        cx, cy = x + ww / 2, y + hh / 2
        l = min(max(cx - cw / 2, 0), a.width - cw)
        t = min(max(cy - ch / 2, 0), a.height - ch)
        gap = 36 * u
        w = (W - gap * 3) / 2
        h = w * 3 / 4
        if 140 * u + h > H - 40 * u:
            h = H - 180 * u
            w = h * 4 / 3
        x0 = (W - (w * 2 + gap)) / 2
        top = 140 * u + (H - 180 * u - h) / 2
        for k, src in enumerate((a, b)):
            ox = x0 + k * (w + gap)
            framed(im, src.crop((int(l), int(t), int(l + cw), int(t + ch))), (ox, top, w, h), int(18 * u))
            sc_ = (int(w) - 12) / cw
            ring(im, int(ox) + 6 + (cx - l) * sc_, int(top) + 6 + (cy - t) * sc_, max(ww, hh) * sc_ / 2 + 22 * u, accent(ep), u)
            chip(im, ("左", "右")[k], ox + 22 * u, top + 22 * u, 62 * u, NAVY + (230,))

    if kind != "title":
        header(im, ep, sc, H)
    if sc.get("caption"):
        caption(im, ep, sc["caption"], H)

    if kind == "think":
        frames = []
        n = int(sc["seconds"])
        R = int((58 if pair else 84) * u)
        cx, cy = (W - R - 40 * u, R + 12 * u) if pair else (W - R - 48 * u, R + 32 * u)
        for k in range(n, 0, -1):
            f = im.copy()
            timer(f, ep, k, n, cx, cy, R)
            progress_bar(f, ep, k / n, H)
            frames.append(f.convert("RGB"))
        return frames
    return im.convert("RGB")


def main(spec_path, out_dir, no_voice=False):
    ep = json.loads(pathlib.Path(spec_path).read_text(encoding="utf-8"))
    size = tuple(ep.get("size", [1920, 1080]))
    if "spot" in ep:  # 間違い探し: 画素の比較で違いを確かめ、正確な枠を使う
        sp = ep["spot"]
        ok, msg, res = spotcheck.check(ROOT / sp["a"], ROOT / sp["b"], ROOT / sp["list"])
        print("spotcheck", ep["id"], msg)
        if not ok:
            raise SystemExit(f"間違い探しの確認に失敗: {msg}")
        ep["differences"] = res
    if "spots" in ep:  # 絵が何枚もある回
        ep["diffs_by"] = {}
        for gid, sp in ep["spots"].items():
            ok, msg, res = spotcheck.check(ROOT / sp["a"], ROOT / sp["b"], ROOT / sp["list"])
            print("spotcheck", gid, msg)
            if not ok:
                raise SystemExit(f"間違い探しの確認に失敗: {gid} {msg}")
            ep["diffs_by"][gid] = res
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    tone(tick, "tick"); tone(chime, "chime")
    concat, voice_parts, sfx_parts, t = [], [], [], 0.0
    for n, sc in enumerate(ep["scenes"]):
        voice_len = 0
        if sc.get("voice"):
            vp = str(tmp / f"v{n:02d}.wav")
            if no_voice:
                silence(max(1.5, len(sc["voice"]) * 0.14), vp)
            else:
                tts(sc["voice"], vp)
            voice_len = dur(vp)
            voice_parts.append((t + sc.get("voice_delay", 0.4), vp))
        length = sc.get("seconds", voice_len + sc.get("voice_delay", 0.4) + sc.get("pad", 0.8))
        if sc.get("chime"):
            sfx_parts.append((t, chime))
        r = render_scene(sc, ep, size)
        if isinstance(r, list) and r and isinstance(r[0], tuple):  # (画像, 秒) の列
            fixed = sum(d for _, d in r if d)
            rest = max(0.8, length - fixed)
            for k, (fr, d) in enumerate(r):
                p = tmp / f"s{n:02d}_{k:03d}.png"
                fr.save(p)
                concat.append((p, d if d else rest))
            length = fixed + rest
        elif isinstance(r, list):
            for k, fr in enumerate(r):
                p = tmp / f"s{n:02d}_{k:03d}.png"
                fr.save(p)
                concat.append((p, 1.0))
                sfx_parts.append((t + k, tick))
            length = len(r)
        else:
            p = tmp / f"s{n:02d}.png"
            r.save(p)
            concat.append((p, length))
        t += length
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\nduration {d:.3f}\n" for p, d in concat) + f"file '{concat[-1][0]}'\n")
    video = tmp / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},format=yuv420p",
                    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-t", f"{t:.3f}", str(video)], check=True)

    # 音：声と効果音をそれぞれ1本に。BGMは声が出ている間だけ自動で下げる（ダッキング）。
    def mixdown(parts, out):
        inputs, filt = [], []
        for k, (start, path) in enumerate(parts):
            inputs += ["-i", path]
            ms = int(start * 1000)
            filt.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
        mix = "".join(f"[a{k}]" for k in range(len(parts)))
        filt.append(f"{mix}amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{t:.3f}[o]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(SR), out], check=True)

    voice = str(tmp / "voice.wav")
    if voice_parts:
        mixdown(voice_parts, voice)
    else:
        silence(t, voice)
    sfx = str(tmp / "sfx.wav")
    if sfx_parts:
        mixdown(sfx_parts, sfx)
    else:
        silence(t, sfx)
    audio = tmp / "audio.wav"
    if ep.get("bgm", True):
        music = str(tmp / "bgm.wav")
        BGM.save(music, BGM.make(t, ep.get("style", "match"), seed=sum(map(ord, ep["id"]))))
        vol = ep.get("bgm_volume", 0.16)
        fc = (f"[1:a]volume={vol}[m];[0:a]asplit=2[v1][v2];"
              f"[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=450[md];"
              f"[v1][md][2:a]amix=inputs=3:normalize=0[o]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", music, "-i", sfx, "-filter_complex", fc,
                        "-map", "[o]", "-ar", str(SR), str(audio)], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", sfx, "-filter_complex", "amix=inputs=2:normalize=0",
                        "-ar", str(SR), str(audio)], check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-movflags", "+faststart", "-shortest", str(out)], check=True)
    # 確認用の一覧画像（場面ごとの最初のコマ）
    firsts, seen = [], set()
    for p, _ in concat:
        key = p.stem.split("_")[0]
        if key not in seen:
            seen.add(key); firsts.append(p)
    sheet = [Image.open(p).resize((480, int(480 * size[1] / size[0]))) for p in firsts][:12]
    cols = 3
    S = Image.new("RGB", (480 * cols, sheet[0].height * math.ceil(len(sheet) / cols)))
    for k, s in enumerate(sheet):
        S.paste(s, ((k % cols) * 480, (k // cols) * s.height))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{t:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
