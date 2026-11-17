#!/usr/bin/env python3
"""間違い探しのショート（縦 1080x1920、1問だけ、20秒前後）を作る。

  - 1コマ目から2枚の絵（上下）と問いかけを出す。表紙・前置き・フェードインはなし
  - すぐタイマーが動き、終わったら違いの場所に丸が順にポンと出る
  - 大事なものは右のボタン列と下の説明文にかからない位置へ
台本 spot/shorts/<id>.json
  id, picture（絵のid）, think（秒、省略すると 15）, title（上の問いかけ、省略すると「違いを5つ探せ」）, bgm, upload
使い方: short.py spot/shorts/<id>.json 出力フォルダ [--no-voice]
"""
import json, math, pathlib, subprocess, sys, tempfile
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "spot"))
import spot as S  # noqa: E402
R = S.R

W, H = 1080, 1920
FPS = 30
SIDE = 760
X0 = (60 + 930) // 2 - SIDE // 2      # 右のボタン列をさけて、少し左寄せ
YA, YB = 250, 250 + SIDE + 22
LOUDNESS = -19


def base_frame(title, label):
    im = _paper()
    for y in (YA, YB):
        R.shadow_box(im, (X0 - 6, y - 6, X0 + SIDE + 6, y + SIDE + 6), 14, (255, 255, 255, 255), blur=16, offset=6, alpha=80)
    d = ImageDraw.Draw(im)
    # 上の帯：番組名と問いかけ
    S.chip(im, "間違い探し", 60, 62, 64, S.ACC + (255,))
    d = ImageDraw.Draw(im)
    f = S.serif(78)
    while d.textlength(title, font=f) > 700:
        f = S.serif(f.size * 0.92)
    d.text((60, 186), title, font=f, fill=S.INK, anchor="lm")
    if label:
        S._chip(im, label, 330, 62, 64, (255, 255, 255, 248), S.INK, "heavy", 34)
    return im


def _paper():
    import random
    g = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(g)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(S.PAPER[i] * (1 - k) + S.PAPER2[i] * k) for i in range(3)) + (255,))
    rnd = random.Random(9)
    for _ in range(1500):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        L = rnd.uniform(4, 22)
        c = rnd.randint(205, 228)
        d.line([(x, y), (x + L, y + rnd.uniform(-3, 3))], fill=(c, c - 6, c - 18, 70), width=1)
    return g


def frame(base, A, B, rings, remain=None, n=None):
    im = base.copy()
    s = SIDE / A.width
    for y, src in ((YA, A), (YB, B)):
        pic = src.copy()
        d = ImageDraw.Draw(pic)
        for (bx, by, bw, bh), k in rings:
            r = (max(bw, bh) / 2 + 22 / s) * k
            _ring(d, bx + bw / 2, by + bh / 2, r, 1 / s)
        pic = pic.resize((SIDE, SIDE), Image.LANCZOS)
        mask = Image.new("L", pic.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIDE, SIDE], radius=10, fill=255)
        im.paste(pic, (X0, y), mask)
    if remain is not None:
        cx, cy, Rr = 870, 186, 54
        R.shadow_box(im, (cx - Rr, cy - Rr, cx + Rr, cy + Rr), Rr, R.NAVY + (255,), blur=10, offset=4)
        d = ImageDraw.Draw(im)
        w = 8
        bb = [cx - Rr + w, cy - Rr + w, cx + Rr - w, cy + Rr - w]
        d.ellipse(bb, outline=(60, 78, 105), width=w)
        if remain > 0:
            d.arc(bb, -90, -90 + 360 * remain / n, fill=S.ACC, width=w)
        d.text((cx, cy), str(max(0, math.ceil(remain - 1e-6))), font=R.font(Rr * 0.9, "heavy"), fill=(255, 255, 255), anchor="mm")
        d.rectangle([X0, YB + SIDE + 24, X0 + SIDE, YB + SIDE + 34], fill=(220, 212, 196))
        d.rectangle([X0, YB + SIDE + 24, X0 + SIDE * remain / n, YB + SIDE + 34], fill=S.ACC)
    return im.convert("RGB")


def _ring(d, cx, cy, r, px):
    """絵の座標で描く丸（縮めたあとに白い縁 7px・赤 5px ほどになる太さ）。"""
    for rr, wdt, col in ((r + 4 * px, int(11 * px), (255, 255, 255)), (r, int(6 * px), S.ACC)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=max(1, wdt))


def render(sh, out_dir, no_voice=False):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    pics = S.load_pictures([sh["picture"]])
    if not pics:
        raise SystemExit("絵が使えない")
    _, A, B, diffs = pics[0]
    m = len(diffs)
    n = int(sh.get("think", 15))
    title = sh.get("title", f"違いを{m}つ探せ")
    voice = S.Voice(tmp, no_voice)
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    R.tone(tick, "tick"); R.tone(chime, "chime")
    audio = []
    frames = []  # (画像, コマ数)

    base = base_frame(title, None)
    v, vl = voice(f"違いは{m}つ。{n}秒で見つけられるかな？")
    audio.append((0.15, v))
    nf = n * FPS
    for i in range(nf):
        frames.append((frame(base, A, B, [], n * (1 - i / nf), n), 1))
    for k in range(n):
        if n - k <= 5:
            audio.append((k, tick))
    t = float(n)
    base = base_frame("答えはここ！", None)
    v, vl = voice("答えはここ！")
    audio.append((t + 0.05, v))
    shown = []
    for j, df in enumerate(diffs):
        audio.append((t, chime))
        for i in range(int(0.3 * FPS)):
            k = 1.5 - 0.5 * S.ease_out(i / (0.3 * FPS - 1))
            frames.append((frame(base, A, B, [(b, 1.0) for b in shown] + [(df["box"], k)]), 1))
        shown.append(df["box"])
        frames.append((frame(base, A, B, [(b, 1.0) for b in shown]), int(0.12 * FPS)))
        t += 0.3 + 0.12
    last = frame(base, A, B, [(b, 1.0) for b in shown])
    frames.append((last, int(3.0 * FPS)))
    t += 3.0

    video = tmp / "video.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-c:v", "libx264", "-crf", "21", "-preset", "slow", "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p", str(video)],
                          stdin=subprocess.PIPE)
    total = 0
    for im, c in frames:
        b = im.tobytes()
        for _ in range(c):
            ff.stdin.write(b)
        total += c
    ff.stdin.close(); ff.wait()
    dur = total / FPS

    def mix(parts, out):
        ins, filt = [], []
        for k, (st, p) in enumerate(parts):
            ins += ["-i", p]
            ms = int(st * 1000)
            filt.append(f"[{k}:a]aresample={R.SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
        filt.append("".join(f"[a{k}]" for k in range(len(parts))) + f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{dur:.3f}[o]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(R.SR), out], check=True)

    vw, sw, mw = str(tmp / "voice.wav"), str(tmp / "sfx.wav"), str(tmp / "bgm.wav")
    mix([(a, p) for a, p in audio if pathlib.Path(p).name.startswith("v")], vw)
    mix([(a, p) for a, p in audio if not pathlib.Path(p).name.startswith("v")], sw)
    S.bgm_track(sh.get("bgm", "little_fish"), dur, mw)
    fc = (f"[1:a]volume={S.BGM_VOLUME}[m];[2:a]volume=0.5[s];[0:a]asplit=2[v1][v2];"
          f"[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=450[md];[v1][md][s]amix=inputs=3:normalize=0[o]")
    aw = tmp / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", vw, "-i", mw, "-i", sw, "-filter_complex", fc, "-map", "[o]", "-ar", str(R.SR), str(aw)], check=True)
    out = out_dir / f"{sh['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(aw), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-af", f"loudnorm=I={LOUDNESS}:TP=-2:LRA=11", "-ar", str(R.SR), "-movflags", "+faststart", "-shortest", str(out)], check=True)
    frames[0][0].resize((360, 640)).save(out_dir / f"{sh['id']}_first.jpg", quality=85)
    up = sh.get("upload")
    if up:
        (out_dir / f"{sh['id']}.txt").write_text(
            f"タイトル：\n{up['title']}\n\n説明文：\n{up['description']}\n\nタグ：\n{', '.join(up['tags'])}\n\n"
            "形式：ショート（縦）\nアップロード時の設定：「改変または合成されたコンテンツ」は「はい」\n", encoding="utf-8")
    print(out, f"{dur:.1f}s")


if __name__ == "__main__":
    sh = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    render(sh, sys.argv[2], "--no-voice" in sys.argv)
