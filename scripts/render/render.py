#!/usr/bin/env python3
"""設計JSON（episodes/<id>.json）から動画を作る。

scene の種類
  title   : 背景＋大きな文字（＋読み上げ）
  match   : マッチ棒の式（状態 question / think / move / answer）＋文字＋読み上げ
  think   : 考える時間（残り秒数のカウントダウンと時計音）
  image   : 画像1枚（または2枚を左右/上下）＋文字＋読み上げ
  circles : 2枚の画像＋答えの丸（differences.json の座標）
共通: "voice" があれば nova で読み上げ、長さは声＋余白で決まる。"seconds" で長さを固定できる。
使い方: render.py episodes/<id>.json out_dir [--no-voice]
"""
import json, os, pathlib, subprocess, sys, tempfile, math, wave, struct
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import matchstick as M
import spotcheck

ROOT = pathlib.Path(__file__).resolve().parents[2]
FONT_CANDIDATES = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
                   "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
FONT = next(p for p in FONT_CANDIDATES if os.path.exists(p))
FPS = 30


def font(size):
    return ImageFont.truetype(FONT, size)


def bg(path, size, dim=0.0, blur=0):
    im = Image.open(ROOT / path).convert("RGB")
    W, H = size
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim:
        im = Image.blend(im, Image.new("RGB", size, (0, 0, 0)), dim)
    return im.convert("RGBA")


def text_box(img, text, y, size=72, fill=(255, 255, 255), band=True, max_w=None):
    d = ImageDraw.Draw(img)
    f = font(size)
    W = img.width
    max_w = max_w or W * 0.9
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if d.textlength(cur + ch, font=f) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    lh = int(size * 1.35)
    h = lh * len(lines)
    if band:
        pad = int(size * 0.45)
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle([W * 0.04, y - pad, W * 0.96, y + h + pad * 0.6], radius=pad, fill=(20, 40, 30, 190))
        img.alpha_composite(ov)
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y + i * lh), ln, font=f, fill=fill, stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0))
    return y + h


def badge(img, text, xy, size=48, fill=(255, 210, 0)):
    d = ImageDraw.Draw(img)
    f = font(size)
    tw = d.textlength(text, font=f)
    x, y = xy
    d.rounded_rectangle([x, y, x + tw + size, y + size * 1.5], radius=size // 2, fill=fill)
    d.text((x + size / 2, y + size * 0.2), text, font=f, fill=(30, 30, 30))


# ---- 音 ----
SR = 48000


def tts(text, out):
    subprocess.run([sys.executable, str(ROOT / "scripts/tts.py"), out, text], check=True)


def silence(sec, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", f"{sec:.3f}", out], check=True)


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode())


def tone(out, kind):
    """時計の音（tick）と、答えの合図（chime）を合成する。"""
    if kind == "tick":
        expr = "0.25*sin(2*PI*1800*t)*exp(-60*t)"
        d = 0.08
    else:
        expr = "0.18*(sin(2*PI*880*t)+0.6*sin(2*PI*1320*t))*exp(-4*t)"
        d = 1.2
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc={expr}:s={SR}:d={d}", "-ac", "2", out], check=True)


# ---- 場面 ----
def render_scene(sc, ep, size):
    """1場面の静止画（または think の場合は1秒ごとの画像のリスト）を返す。"""
    kind = sc["type"]
    W, H = size
    pair = kind in ("image", "circles") or (kind == "think" and "images" in sc)
    if kind in ("title", "match", "think", "riddle") and not pair:
        im = bg(sc.get("bg", ep["bg"]), size, dim=sc.get("dim", 0.4 if kind == "title" else 0.15), blur=6 if kind == "title" else 0)
    else:  # image / circles / zoom / 絵つきの think
        im = Image.new("RGBA", size, (24, 52, 40, 255))
    if kind == "title":
        text_box(im, sc["text"], H * 0.33, size=sc.get("size", 96))
        if sc.get("sub"):
            text_box(im, sc["sub"], H * 0.62, size=60, fill=(255, 235, 170))
    if kind == "zoom":
        a = Image.open(ROOT / sc["images"][0]).convert("RGBA")
        b = Image.open(ROOT / sc["images"][1]).convert("RGBA")
        x, y, ww, hh = ep["differences"][sc["index"]]["box"]
        cw = max(ww, hh * 4 / 3) * 2.6
        cw = min(max(cw, 320), a.width)
        ch = cw * 3 / 4
        cx, cy = x + ww / 2, y + hh / 2
        l = min(max(cx - cw / 2, 0), a.width - cw)
        t = min(max(cy - ch / 2, 0), a.height - ch)
        gap = 40
        w = (W - gap * 3) // 2
        h = int(w * 3 / 4)
        top = int(H * 0.17) + (H - int(H * 0.17) - h) // 2 - 10
        x0 = (W - (w * 2 + gap)) // 2
        d = ImageDraw.Draw(im)
        sc_ = w / cw
        for k, src in enumerate((a, b)):
            ox = x0 + k * (w + gap)
            crop = src.crop((int(l), int(t), int(l + cw), int(t + ch))).resize((w, h), Image.LANCZOS)
            im.alpha_composite(crop, (ox, top))
            d.rectangle([ox - 4, top - 4, ox + w + 4, top + h + 4], outline=(255, 255, 255), width=6)
            ex, ey = ox + (cx - l) * sc_, top + (cy - t) * sc_
            r = max(ww, hh) * sc_ / 2 + 24
            d.ellipse([ex - r, ey - r, ex + r, ey + r], outline=(255, 40, 40), width=10)
            label = ("前", "後")[k] if sc.get("labels") else ("左", "右")[k]
            badge(im, label, (ox + 16, top + 16), size=44)
        if sc.get("text"):
            text_box(im, sc["text"], int(H * 0.04), size=60)
    if kind == "think" and not pair and "puzzle" not in ep:
        text_box(im, sc.get("text", "考えてね"), H * 0.25, size=sc.get("size", 84))
    if kind == "match" or (kind == "think" and not pair and "puzzle" in ep):
        st = sc.get("state", "question")
        p = ep["puzzle"]
        expr = p["answer"] if st == "answer" else p["question"]
        _, i, s, j, t = p["move"]
        kw = {}
        if st == "move":
            kw = dict(hide=(i, s), highlight=(i, s))
        if st == "move2":
            expr = p["answer"]
            kw = dict(highlight=(j, t))
        M.draw_expr(im, expr, W / 2, H * 0.47, H=int(H * 0.36), **kw)
        if sc.get("text"):
            text_box(im, sc["text"], H * 0.08, size=64)
        if sc.get("caption"):
            text_box(im, sc["caption"], H * 0.78, size=60)
    if kind == "riddle":
        text_box(im, sc["text"], H * 0.25, size=sc.get("size", 84))
        if sc.get("caption"):
            text_box(im, sc["caption"], H * 0.70, size=64, fill=(255, 230, 120))
    if pair:
        a = Image.open(ROOT / sc["images"][0]).convert("RGBA")
        b = Image.open(ROOT / sc["images"][1]).convert("RGBA")
        gap = 24
        top = int(H * 0.16)
        w = (W - gap * 3) // 2
        h = int(w * a.height / a.width)
        if top + h > H - 20:
            h = H - 20 - top
            w = int(h * a.width / a.height)
        x0 = (W - (w * 2 + gap)) // 2
        top = max(top, (H - h) // 2 + int(H * 0.04))
        a2, b2 = a.resize((w, h), Image.LANCZOS), b.resize((w, h), Image.LANCZOS)
        im.alpha_composite(a2, (x0, top))
        im.alpha_composite(b2, (x0 + w + gap, top))
        if kind == "circles":
            d = ImageDraw.Draw(im)
            sx = w / a.width
            for k, df in enumerate(ep["differences"][: sc.get("upto", 99)]):
                x, y, ww, hh = df["box"]
                for ox in (x0, x0 + w + gap):
                    cx, cy = ox + (x + ww / 2) * sx, top + (y + hh / 2) * sx
                    r = max(ww, hh) * sx / 2 + 14
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 40, 40), width=8)
        if sc.get("text"):
            text_box(im, sc["text"], 24, size=56, band=False)
    if kind == "think":
        frames = []
        n = int(sc["seconds"])
        for k in range(n, 0, -1):
            f = im.copy()
            d = ImageDraw.Draw(f)
            R = int(H * 0.09)
            cx, cy = W - R - 50, R + 50
            d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(255, 255, 255, 235), outline=(30, 90, 60), width=8)
            d.pieslice([cx - R + 14, cy - R + 14, cx + R - 14, cy + R - 14], -90, -90 + 360 * k / n, fill=(70, 170, 110))
            ft = font(int(R * 0.9))
            tw = d.textlength(str(k), font=ft)
            d.text((cx - tw / 2, cy - R * 0.58), str(k), font=ft, fill=(20, 20, 20), stroke_width=4, stroke_fill=(255, 255, 255))
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
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    tone(tick, "tick"); tone(chime, "chime")
    concat, audio_parts, t = [], [], 0.0
    for n, sc in enumerate(ep["scenes"]):
        voice_len = 0
        if sc.get("voice"):
            vp = str(tmp / f"v{n:02d}.wav")
            if no_voice:
                silence(max(1.5, len(sc["voice"]) * 0.14), vp)
            else:
                tts(sc["voice"], vp)
            voice_len = dur(vp)
            audio_parts.append((t + sc.get("voice_delay", 0.4), vp))
        length = sc.get("seconds", voice_len + sc.get("voice_delay", 0.4) + sc.get("pad", 0.8))
        if sc.get("chime"):
            audio_parts.append((t, chime))
        r = render_scene(sc, ep, size)
        if isinstance(r, list):
            for k, fr in enumerate(r):
                p = tmp / f"s{n:02d}_{k:03d}.png"
                fr.save(p)
                concat.append((p, 1.0))
                audio_parts.append((t + k, tick))
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
    inputs, filt = [], []
    for k, (start, path) in enumerate(audio_parts):
        inputs += ["-i", path]
        ms = int(start * 1000)
        filt.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
    mix = "".join(f"[a{k}]" for k in range(len(audio_parts)))
    filt.append(f"{mix}amix=inputs={len(audio_parts)}:normalize=0,apad,atrim=0:{t:.3f}[aout]")
    audio = tmp / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[aout]", "-ar", str(SR), str(audio)], check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-movflags", "+faststart", "-shortest", str(out)], check=True)
    # 確認用の静止画（各場面の最初のコマ）
    sheet = [Image.open(p).resize((480, int(480 * size[1] / size[0]))) for p, _ in concat[:: max(1, len(concat) // 9)]][:9]
    cols = 3
    S = Image.new("RGB", (480 * cols, sheet[0].height * math.ceil(len(sheet) / cols)))
    for k, s in enumerate(sheet):
        S.paste(s, ((k % cols) * 480, (k // cols) * s.height))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{t:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
