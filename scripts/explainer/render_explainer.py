#!/usr/bin/env python3
"""AI解説動画（画像がテンポよく切り替わり、ゆっくり動くスタイル）を作る。

explainer/<id>.json の形
  id, title, chapters（{"1": "写真で質問", ...}）, bgm_volume（省略可）
  scenes: [{image（assets/generated/<依頼id> か画像のパス）, voice（読み上げ文）, telop（大きな見出し）, chapter（"1" など）}]
声は explainer/voice/<id>/<hash>.m4a（scripts/explainer/voices.py が Actions で作る）。無ければ無音で長さだけ見積もる。
動き: 場面ごとに寄る／引く／左右に流すを順番に使い、切り替えは短いクロスフェード＋軽いズームの押し込み。
見出しは弾むように出し、字幕は句読点で区切って声に合わせて切り替える。BGMは scripts/render/bgm.py の自作曲。
使い方: render_explainer.py explainer/<id>.json 出力フォルダー [--fast]（--fast は低画質の確認用）
"""
import hashlib, json, math, os, pathlib, re, subprocess, sys, tempfile, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
import bgm as BGM  # noqa: E402

W, H, FPS, SR = 1920, 1080, 30, 48000
LEAD, PAD, XFADE = 0.35, 0.55, 0.30  # 声の前の間、声の後の間、切り替えの長さ（秒）

ACCENT = (255, 196, 0)      # 見出しの縁・番号の色
ACCENT2 = (0, 170, 255)
INK = (18, 22, 32)
WHITE = (255, 255, 255)


def _find_font(names):
    dirs = [os.environ.get("FONT_DIR", ""), "/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto", "/usr/share/fonts"]
    for n in names:
        for d in dirs:
            if not d:
                continue
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


# ---------- 素材 ----------
def load_image(ref, n):
    p = ROOT / ref
    if p.is_dir():
        cands = sorted(f for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        p = cands[0] if cands else None
    if p and p.exists():
        im = Image.open(p).convert("RGB")
    else:  # まだ画像がないときの仮の絵
        im = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(im)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(40 + 60 * t + 20 * n % 60), int(70 + 40 * t), int(140 - 40 * t)))
        d.text((W / 2, H / 2), f"（画像 {n + 1} を準備中）", font=font(64), fill=WHITE, anchor="mm")
    # 1.2倍の余白を持たせて、16:9に切り抜く
    target = (int(W * 1.2), int(H * 1.2))
    s = max(target[0] / im.width, target[1] / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    x, y = (im.width - target[0]) // 2, (im.height - target[1]) // 2
    return im.crop((x, y, x + target[0], y + target[1]))


def voice_key(text):
    return hashlib.sha1(("nova|0.5|1.05|" + text).encode()).hexdigest()[:12]


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "2", str(dst)], check=True)


def wav_len(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


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
    # だんだん高く、だんだん小さく（簡単な帯域の移動）
    out = np.zeros(n)
    a = 0.0
    for i in range(n):
        k = 0.02 + 0.25 * (i / n)
        a += k * (x[i] - a)
        out[i] = a
    env = np.sin(np.pi * np.arange(n) / n) ** 2
    s = out * env * 0.6
    return np.stack([s * 0.8, s], 1)


# ---------- 文字 ----------
def stroke_text(img, xy, text, f, fill, stroke, sw, anchor="mm"):
    d = ImageDraw.Draw(img)
    d.text(xy, text, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def _cut(c, maxlen):
    """読点のうち真ん中に近いところで2つに分ける。"""
    cands = [i for i, ch in enumerate(c[:-1]) if ch in "、？！"]
    cut = min(cands, key=lambda i: abs(i - len(c) / 2), default=None)
    if cut is None or max(cut + 1, len(c) - cut - 1) > maxlen:
        cut = len(c) // 2 - 1
    return c[:cut + 1], c[cut + 1:]


def split_caption(text, maxlen=22):
    """文ごとに1枚。長い文は読点で2枚に分け、1枚は2行・1行 maxlen 字まで。"""
    sents = [p for p in re.split(r"(?<=[。？！])", text.replace("　", "")) if p.strip()]
    chunks = []
    for c in sents:
        c = c.rstrip("。")
        chunks += list(_cut(c, maxlen * 2)) if len(c) > maxlen * 2 - 2 else [c]
    return [[c] if len(c) <= maxlen else list(_cut(c, maxlen)) for c in chunks]


def caption_layer(lines):
    im = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    f = font(58)
    y0 = 260 - 40 - 78 * len(lines)
    for k, ln in enumerate(lines):
        stroke_text(im, (W / 2, y0 + 78 * k + 39), ln, f, WHITE, INK, 9)
    return im


def telop_layer(text):
    f = font(104, heavy=True)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    x0, y0, x1, y1 = tmp.textbbox((0, 0), text, font=f, stroke_width=14)
    w, h = x1 - x0 + 60, y1 - y0 + 50
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # 影→黄色い太縁→白文字
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    stroke_text(sh, (w / 2 + 6, h / 2 + 8), text, f, (0, 0, 0, 150), (0, 0, 0, 150), 16)
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    stroke_text(im, (w / 2, h / 2), text, f, INK, ACCENT, 16)
    stroke_text(im, (w / 2, h / 2), text, f, WHITE, INK, 7)
    return im


def chapter_layer(num, name):
    f, fn = font(44), font(46, heavy=True)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = tmp.textlength(name, font=f)
    w, h = int(tw + 150), 84
    im = Image.new("RGBA", (w + 12, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([6, 10, w + 6, h + 10], 42, fill=(0, 0, 0, 90))
    d.rounded_rectangle([0, 0, w, h], 42, fill=(255, 255, 255, 240))
    d.ellipse([8, 8, 76, 76], fill=ACCENT2)
    d.text((42, 41), num, font=fn, fill=WHITE, anchor="mm")
    d.text((96, h / 2), name, font=f, fill=INK, anchor="lm")
    return im


def progress_layer(ep, current):
    """画面いちばん下の章の進み具合（1・2・3）。"""
    im = Image.new("RGBA", (W, 14), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    n = len(ep.get("chapters", {})) or 1
    seg = (W - 80) / n
    for k in range(n):
        x0 = 40 + seg * k + 6
        on = current is not None and k + 1 <= current
        d.rounded_rectangle([x0, 2, x0 + seg - 12, 12], 5, fill=ACCENT2 + (235,) if on else (255, 255, 255, 110))
    return im


# ---------- 動き ----------
MOVES = ["in", "pan_r", "out", "pan_l", "in_up", "pan_r", "out", "in"]


def kenburns(src, move, p):
    """src は 1.2倍の絵。p=0→1 で表示範囲を動かす（小数の位置で滑らかに）。"""
    sw, sh = src.size
    e = ease(p)
    if move == "in":
        z0, z1, c0, c1 = 1.0, 1.15, (0.5, 0.5), (0.5, 0.48)
    elif move == "in_up":
        z0, z1, c0, c1 = 1.02, 1.16, (0.5, 0.58), (0.5, 0.42)
    elif move == "out":
        z0, z1, c0, c1 = 1.16, 1.0, (0.5, 0.47), (0.5, 0.5)
    elif move == "pan_r":
        z0, z1, c0, c1 = 1.08, 1.10, (0.38, 0.5), (0.62, 0.5)
    else:  # pan_l
        z0, z1, c0, c1 = 1.10, 1.08, (0.62, 0.5), (0.38, 0.5)
    z = z0 + (z1 - z0) * e
    cx, cy = c0[0] + (c1[0] - c0[0]) * e, c0[1] + (c1[1] - c0[1]) * e
    vw, vh = sw / 1.2 / z, sh / 1.2 / z  # 表示する範囲（z=1で出力と同じ大きさ）
    # 余白（1.2倍）の分だけ動ける
    x = cx * (sw - vw)
    y = cy * (sh - vh)
    return src.resize((W, H), Image.BILINEAR, box=(x, y, x + vw, y + vh))


# ---------- 本体 ----------
def main(spec, out_dir, fast=False):
    ep = json.loads(pathlib.Path(spec).read_text(encoding="utf-8"))
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    rng = np.random.default_rng(7)
    vdir = ROOT / "explainer" / "voice" / ep["id"]

    # 1) 場面の長さを声から決める
    scenes, t = [], 0.0
    missing = 0
    for n, sc in enumerate(ep["scenes"]):
        src = vdir / f"{voice_key(sc['voice'])}.m4a"
        if src.exists():
            wv = tmp / f"v{n:02d}.wav"; to_wav(src, wv); vlen = wav_len(wv)
        else:
            wv, vlen = None, max(1.5, len(sc["voice"]) * 0.135); missing += 1
        length = LEAD + vlen + PAD
        scenes.append({**sc, "n": n, "start": t, "len": length, "vlen": vlen, "wav": wv})
        t += length
    total = t
    if missing:
        print(f"声がまだない場面: {missing}（無音で長さを見積もり）")

    # 2) 場面ごとの部品を先に作る
    for s in scenes:
        s["img"] = load_image(s["image"], s["n"])
        s["move"] = MOVES[s["n"] % len(MOVES)]
        s["telop"] = telop_layer(s["telop"]) if s.get("telop") else None
        ch = s.get("chapter")
        s["chap"] = chapter_layer(ch, ep["chapters"][ch]) if ch else None
        s["prog"] = progress_layer(ep, int(ch) if ch else (len(ep.get("chapters", {})) if s["n"] >= len(scenes) - 3 else None))
        caps = split_caption(s["voice"])
        weights = [sum(len(l) for l in c) for c in caps]
        acc, s["caps"] = LEAD, []
        for c, wgt in zip(caps, weights):
            d = s["vlen"] * wgt / sum(weights)
            s["caps"].append((acc, acc + d, caption_layer(c)))
            acc += d

    # 3) 1コマずつ描いて ffmpeg に流す
    video = tmp / "video.mp4"
    nframes = int(round(total * FPS))
    scale = 0.5 if fast else 1.0
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-vf", f"scale={int(W*scale)}:{int(H*scale)}" if fast else "null", "-c:v", "libx264", "-preset", "veryfast" if fast else "medium",
                           "-crf", "28" if fast else "19", "-pix_fmt", "yuv420p", str(video)], stdin=subprocess.PIPE)
    shots = {}
    k = 0
    for f in range(nframes):
        tt = f / FPS
        while k + 1 < len(scenes) and tt >= scenes[k + 1]["start"]:
            k += 1
        s = scenes[k]
        lt = tt - s["start"]
        frame = draw_scene(s, lt, total)
        # 次の場面への切り替え（最後の XFADE 秒で重ねる）
        if k + 1 < len(scenes) and lt > s["len"] - XFADE:
            a = ease((lt - (s["len"] - XFADE)) / XFADE)
            nxt = draw_scene(scenes[k + 1], 0.0, total, base_only=True)
            frame = Image.blend(frame, nxt, a)
        ff.stdin.write(frame.tobytes())
        if abs(lt - min(2.2, s["len"] / 2)) < 0.5 / FPS:
            shots[s["n"]] = frame.copy()
    ff.stdin.close(); ff.wait()

    # 4) 音：声＋効果音、BGMは声の間だけ下げる
    voice = np.zeros((int(total * SR) + SR, 2), np.float32)
    sfx = np.zeros_like(voice)
    pop, wh = sfx_pop(), sfx_whoosh(rng)

    def put(buf, sig, at, g=1.0):
        i = int(at * SR); j = min(len(buf), i + len(sig)); buf[i:j] += sig[: j - i] * g

    for s in scenes:
        if s["wav"]:
            put(voice, read_wav(s["wav"]), s["start"] + LEAD)
        if s["telop"] is not None:
            put(sfx, pop, s["start"] + 0.05, 0.35)
        if s["n"] > 0:
            put(sfx, wh, s["start"] - XFADE, 0.25)
    vw, sw_ = tmp / "voice.wav", tmp / "sfx.wav"
    write_wav(vw, voice[: int(total * SR)]); write_wav(sw_, sfx[: int(total * SR)])
    music = tmp / "bgm.wav"
    BGM.save(str(music), BGM.make(total, ep.get("bgm_style", "spot"), seed=3))
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
    ims = [shots[i].resize((480, 270)) for i in sorted(shots)]
    cols = 4
    sheet = Image.new("RGB", (480 * cols, 270 * math.ceil(len(ims) / cols)))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * 480, (i // cols) * 270))
    sheet.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{total:.1f}s", "missing voices:", missing)


def draw_scene(s, lt, total, base_only=False):
    p = lt / (s["len"] + XFADE)
    frame = kenburns(s["img"], s["move"], p)
    # 入りの軽い押し込み（最初の0.25秒だけ少し大きい）
    if lt < 0.25 and s["n"] > 0:
        z = 1 + 0.04 * (1 - ease(lt / 0.25))
        frame = frame.resize((int(W * z), int(H * z)), Image.BILINEAR).crop(
            (int((W * z - W) / 2), int((H * z - H) / 2), int((W * z - W) / 2) + W, int((H * z - H) / 2) + H))
    if base_only:
        return frame
    im = frame.convert("RGBA")
    # 下を少し暗くして字幕を読みやすく
    im.alpha_composite(GRAD)
    if s["chap"] is not None:
        a = ease(lt / 0.35)
        x = int(-s["chap"].width + (48 + s["chap"].width) * a)
        im.alpha_composite(s["chap"], (x, 40))
    if s["telop"] is not None and lt > 0.05:
        a = back_out((lt - 0.05) / 0.4)
        tl = s["telop"]
        sc = 0.6 + 0.4 * a
        bob = math.sin(lt * 2.2) * 4  # ゆっくり上下にゆれる
        t2 = tl.resize((max(1, int(tl.width * sc)), max(1, int(tl.height * sc))), Image.BILINEAR)
        if a < 1:
            al = t2.getchannel("A").point(lambda v: int(v * min(1, a * 1.5)))
            t2.putalpha(al)
        y = (210 if s["chap"] is not None else 150) + bob
        im.alpha_composite(t2, (int(W / 2 - t2.width / 2), int(y - t2.height / 2)))
    for a0, a1, layer in s["caps"]:
        if a0 - 0.05 <= lt < a1 + 0.35:
            im.alpha_composite(layer, (0, H - 260 - 20))
            break
    im.alpha_composite(s["prog"], (0, H - 22))
    return im.convert("RGB")


def _grad():
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for y in range(H - 360, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * ((y - (H - 360)) / 360) ** 1.6)))
    for y in range(0, 300):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(70 * (1 - y / 300) ** 2)))
    return g


GRAD = _grad()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--fast" in sys.argv)
