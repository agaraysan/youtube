#!/usr/bin/env python3
"""頭の体操のショート（縦 1080x1920、1問だけ、10秒前後）を作る。

方針（運営の数字から）：8割が最初の1〜2秒でスワイプするので、
  - 1コマ目から問題そのもの（大きな字・絵）と短い問いかけを出す。表紙・前置き・フェードインはなし
  - すぐタイマーが動き、数秒で答え。答えは上の問いかけの場所に一言で
  - 大事なものは画面のまん中（右の縦のボタン列と、下の説明文の重なりをさける）

ショートの項目（brain/shorts/<id>.json）
  id, style, kind: "grid"（漢字の仲間はずれ）| "choice"（3択。big か emoji）
  q（短い問いかけ）, think（秒）, voice_q, voice_a, answer_note（答えのあとに出す一言）
  grid: base, odd, rows, cols ／ choice: big, emoji, big_color, options, correct
使い方: shorts.py brain/shorts/<id>.json out_dir [--no-voice]
"""
import json, math, pathlib, subprocess, sys, tempfile
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
sys.path.insert(0, str(ROOT / "scripts" / "brain"))
import render as R  # noqa: E402
import brain as B  # noqa: E402

W, H = 1080, 1920
FPS = 30
SAFE_L, SAFE_R = 60, 930   # 右側は YouTube のボタン列があるので空ける


def big_text_card(im, ep, text, color, top, bottom):
    d = ImageDraw.Draw(im)
    maxw = SAFE_R - SAFE_L - 100
    fs = 240
    lines = [text]
    while True:
        f = B.serif(fs)
        lines = B.wrap(d, text, f, maxw) if d.textlength(text, font=f) > maxw else [text]
        if len(lines) <= 2 and all(d.textlength(l, font=f) <= maxw for l in lines):
            break
        fs *= 0.9
    lh = fs * 1.25
    ch = lh * len(lines) + 120
    y0 = (top + bottom) / 2 - ch / 2
    R.shadow_box(im, (SAFE_L, y0, SAFE_R, y0 + ch), 36, (255, 255, 255, 250))
    d = ImageDraw.Draw(im)
    acc = R.accent(ep)
    for k, ln in enumerate(lines):
        # □ は色つき
        tw = d.textlength(ln, font=f)
        x = (SAFE_L + SAFE_R) / 2 - tw / 2
        y = y0 + 60 + lh * (k + 0.5)
        for c in ln:
            col = color or (acc if c == "□" else B.INK)
            d.text((x, y), c, font=f, fill=col, anchor="lm")
            x += d.textlength(c, font=f)


def options_col(im, ep, opts, correct, reveal, top):
    """3択を縦に並べる。"""
    acc = R.accent(ep)
    h, gap = 118, 26
    for i, o in enumerate(opts):
        y0 = top + i * (h + gap)
        ok = reveal and i == correct
        dim = reveal and i != correct
        fill = acc + (255,) if ok else ((255, 255, 255, 150) if dim else (255, 255, 255, 250))
        R.shadow_box(im, (SAFE_L, y0, SAFE_R, y0 + h), 26, fill, blur=12, offset=6)
        d = ImageDraw.Draw(im)
        r = 34
        cx0 = SAFE_L + 40
        d.ellipse([cx0, y0 + h / 2 - r, cx0 + 2 * r, y0 + h / 2 + r], fill=(255, 255, 255) if ok else acc)
        d.text((cx0 + r, y0 + h / 2), "ABC"[i], font=R.font(40, "heavy"), fill=acc if ok else (255, 255, 255), anchor="mm")
        col = (255, 255, 255) if ok else ((150, 150, 160) if dim else B.INK)
        if B.is_emoji(o):
            e = B.emoji(o, 84)
            B.paste_center(im, e, (SAFE_L + SAFE_R) / 2 + 30, y0 + h / 2)
        else:
            fs = min(64, (SAFE_R - SAFE_L - 220) / max(1, len(o)))
            d.text(((SAFE_L + SAFE_R) / 2 + 30, y0 + h / 2), o, font=R.font(fs, "heavy"), fill=col, anchor="mm")


def base_frame(ep, reveal):
    im = B.paper((W, H))
    acc = R.accent(ep)
    d = ImageDraw.Draw(im)
    # 上：番組名と、問いかけ（答えでは一言の答え）
    d.rounded_rectangle([SAFE_L, 150, SAFE_L + 230, 214], radius=32, fill=acc)
    d.text((SAFE_L + 115, 182), ep.get("series", "頭の体操"), font=R.font(36, "heavy"), fill=(255, 255, 255), anchor="mm")
    text = ep["answer_note"] if reveal else ep["q"]
    f = R.font(66, "heavy")
    lines = B.wrap(d, text, f, SAFE_R - SAFE_L - 150)
    for k, ln in enumerate(lines[:2]):
        d.text((SAFE_L, 290 + k * 86), ln, font=f, fill=acc if reveal else B.INK, anchor="lm")
    kind = ep["kind"]
    if kind == "words":  # かくれた言葉あて（5×5か4×4、右か下にたどる。答えは色の帯）
        rows = ep["cells"]
        n = len(rows)
        top = 470
        cell = (SAFE_R - SAFE_L - 40) / n
        x0, y0 = SAFE_L + 20, top
        R.shadow_box(im, (x0 - 20, y0 - 20, x0 + cell * n + 20, y0 + cell * n + 20), 30, (255, 255, 255, 250))
        if reveal:
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            for k, wd in enumerate(ep["words"]):
                col = B.WS_COLORS[k % len(B.WS_COLORS)]
                pts = [(x0 + cell * (c + 0.5), y0 + cell * (r + 0.5)) for r, c in wd["path"]]
                wdt = int(cell * 0.78)
                od.line(pts, fill=col + (110,), width=wdt, joint="curve")
                for px, py in pts:
                    od.ellipse([px - wdt / 2, py - wdt / 2, px + wdt / 2, py + wdt / 2], fill=col + (110,))
            im.alpha_composite(ov)
        d = ImageDraw.Draw(im)
        f = R.font(cell * 0.6, "bold")
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                d.text((x0 + cell * (c + 0.5), y0 + cell * (r + 0.5)), ch, font=f, fill=B.INK, anchor="mm")
        # 下：テーマと文字数の枠
        yb = y0 + cell * n + 70
        d.rounded_rectangle([SAFE_L, yb, SAFE_R, yb + 90], radius=45, fill=acc)
        d.text(((SAFE_L + SAFE_R) / 2, yb + 45), "テーマ：" + ep["theme"], font=R.font(52, "heavy"), fill=(255, 255, 255), anchor="mm")
        for k, wd in enumerate(ep["words"]):
            w0, m = wd["w"], len(wd["w"])
            col = B.WS_COLORS[k % len(B.WS_COLORS)]
            bs, gp = 96, 14
            cy = yb + 170 + k * 120
            bx0 = (SAFE_L + SAFE_R) / 2 - (bs * m + gp * (m - 1)) / 2
            for i in range(m):
                x = bx0 + i * (bs + gp)
                d.rounded_rectangle([x, cy - bs / 2, x + bs, cy + bs / 2], radius=12, outline=col if reveal else (150, 150, 160), width=4, fill=col if reveal else (255, 255, 255))
                if reveal:
                    d.text((x + bs / 2, cy), w0[i], font=R.font(60, "heavy"), fill=(255, 255, 255), anchor="mm")
        return im
    if kind == "grid":
        rows, cols = ep["rows"], ep["cols"]
        top, bottom = 480, 1500
        cell = min((SAFE_R - SAFE_L - 40) / cols, (bottom - top) / rows)
        x0 = (SAFE_L + SAFE_R) / 2 - cell * cols / 2
        y0 = top + (bottom - top - cell * rows) / 2
        R.shadow_box(im, (x0 - 20, y0 - 20, x0 + cell * cols + 20, y0 + cell * rows + 20), 30, (255, 255, 255, 250))
        d = ImageDraw.Draw(im)
        f = B.serif(cell * 0.8)
        r0, c0 = ep["pos"]
        for r in range(rows):
            for c in range(cols):
                ch = ep["odd"] if (r, c) == (r0, c0) else ep["base"]
                d.text((x0 + cell * (c + 0.5), y0 + cell * (r + 0.5)), ch, font=f, fill=B.INK, anchor="mm")
        if reveal:
            R.ring(im, x0 + cell * (c0 + 0.5), y0 + cell * (r0 + 0.5), cell * 0.62, acc, 1.6)
    else:
        if ep.get("emoji"):
            R.shadow_box(im, (SAFE_L + 120, 480, SAFE_R - 120, 1060), 40, (255, 255, 255, 250))
            e = B.emoji(ep["emoji"], 470)
            if not reveal:
                sil = Image.new("RGBA", e.size, (40, 40, 52, 255))
                sil.putalpha(e.getchannel("A").point(lambda a: 255 if a > 90 else 0))
                e = sil
            B.paste_center(im, e, (SAFE_L + SAFE_R) / 2, 770)
        else:
            text = ep.get("big_answer") if reveal and ep.get("big_answer") else ep["big"]
            big_text_card(im, ep, text, tuple(ep["big_color"]) if ep.get("big_color") else None, 480, 1060)
        options_col(im, ep, ep["options"], ep["correct"], reveal, 1120)
    return im


def timer(f, ep, remain, n):
    """右上の小さなタイマーと、上の細い残り時間のバー。"""
    acc = R.accent(ep)
    d = ImageDraw.Draw(f)
    cx, cy, r = SAFE_R - 50, 300, 62
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=R.NAVY)
    w = 10
    bb = [cx - r + w, cy - r + w, cx + r - w, cy + r - w]
    d.ellipse(bb, outline=(60, 78, 105), width=w)
    if remain > 0:
        d.arc(bb, -90, -90 + 360 * remain / n, fill=acc, width=w)
    d.text((cx, cy), str(max(0, math.ceil(remain - 1e-6))), font=R.font(56, "heavy"), fill=(255, 255, 255), anchor="mm")
    d.rectangle([0, 0, W, 12], fill=(220, 214, 200))
    d.rectangle([0, 0, W * max(0, remain / n), 12], fill=acc)
    return f


def main(spec, out_dir, no_voice=False):
    ep = json.loads(pathlib.Path(spec).read_text(encoding="utf-8"))
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    n = int(ep.get("think", 6))
    vq, va = str(tmp / "q.wav"), str(tmp / "a.wav")
    for text, path in ((ep["voice_q"], vq), (ep["voice_a"], va)):
        if no_voice:
            R.silence(max(1.0, len(text) * 0.13), path)
        else:
            R.tts(text, path)
    hold = max(3.0, R.dur(va) + 1.0)
    total = n + hold
    q_img = base_frame(ep, False).convert("RGB")
    a_img = base_frame(ep, True).convert("RGB")
    video = tmp / "video.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", str(video)],
                          stdin=subprocess.PIPE)
    for i in range(int(round(total * FPS))):
        t = i / FPS
        if t < n:
            fr = timer(q_img.copy(), ep, n - t, n)
        else:
            k = t - n
            s = 1.0 + 0.03 * max(0.0, 1 - k / 0.3)  # 答えがポンと出る
            fr = a_img if s < 1.0005 else a_img.resize((W, H), Image.BILINEAR, box=((W - W / s) / 2, (H - H / s) / 2, (W + W / s) / 2, (H + H / s) / 2))
        ff.stdin.write(fr.tobytes())
    ff.stdin.close()
    ff.wait()
    # 音：問いかけはすぐ（0.1秒）、時計の音、答えの合図と声、BGM は小さく
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    R.tone(tick, "tick"); R.tone(chime, "chime")
    parts = [(0.1, vq)] + [(k, tick) for k in range(1, n)] + [(n, chime), (n + 0.25, va)]
    ins, filt = [], []
    for k, (st, p) in enumerate(parts):
        ins += ["-i", p]
        ms = int(st * 1000)
        filt.append(f"[{k}:a]aresample={R.SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
    filt.append("".join(f"[a{k}]" for k in range(len(parts))) + f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.3f}[o]")
    fg = str(tmp / "fg.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(R.SR), fg], check=True)
    music = str(tmp / "bgm.wav")
    R.BGM.save(music, R.BGM.make(total, ep.get("style", "match"), seed=sum(map(ord, ep["id"]))))
    vol = ep.get("bgm_volume", B.BGM_VOLUME)
    audio = tmp / "audio.wav"
    fc = (f"[1:a]volume={vol}[m];[0:a]asplit=2[v1][v2];[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=400[md];"
          f"[v1][md]amix=inputs=2:normalize=0[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", fg, "-i", music, "-filter_complex", fc, "-map", "[o]", "-ar", str(R.SR), str(audio)], check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", f"loudnorm=I={B.LOUDNESS}:TP=-2:LRA=11", "-ar", str(R.SR), "-movflags", "+faststart", "-shortest", str(out)], check=True)
    S = Image.new("RGB", (540 * 2, 960))
    S.paste(q_img.resize((540, 960)), (0, 0)); S.paste(a_img.resize((540, 960)), (540, 0))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{total:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
