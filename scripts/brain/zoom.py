#!/usr/bin/env python3
"""無限ズームのショート動画（縦 1080x1920）を作る。

絵を何枚か用意し、1枚目の中央に2枚目、2枚目の中央に3枚目…と入れ子にして、
中央へ向かってズームし続ける。入れ子の境目は楕円のぼかしでなじませる。
最後の絵を1枚目と同じにすると、ぐるっと一周してループする。

エピソードの項目
  id, kind: "zoom", size（既定 [1080, 1920]）, zoom（1段で何倍に寄るか。既定 3）
  layers: [{image（絵かフォルダー）, voice（その段の語り）, caption（字幕）}]
  seconds（1段の秒数。既定 5）, hold（最初と最後の止め。既定 1.2）, style（BGM）
使い方: zoom.py brain/episodes/<id>.json out_dir [--no-voice]
"""
import json, math, os, pathlib, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
sys.path.insert(0, str(ROOT / "scripts" / "brain"))
import render as R  # noqa: E402
import brain as B  # noqa: E402

R.ACCENT.setdefault("zoom", (120, 90, 200))
R.BGM.STYLES.setdefault("zoom", (72, 57, [(0, "m7"), (8, "maj7"), (3, "maj7"), (10, "dom7")]))
FPS = 30


def load(path, size):
    """絵を画面の比率に合わせて切り抜き、少し大きめ（ズーム用）に読み込む。"""
    im = Image.open(ROOT / path).convert("RGB")
    W, H = size
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((l, t, l + W, t + H))


def oval_mask(size, feather):
    w, h = size
    m = Image.new("L", size, 0)
    f = int(min(w, h) * feather)
    ImageDraw.Draw(m).ellipse([f * 0.6 - w * 0.08, f * 0.6 - h * 0.05, w - f * 0.6 + w * 0.08, h - f * 0.6 + h * 0.05], fill=255)
    return m.filter(ImageFilter.GaussianBlur(max(1, f / 2)))


def frame(imgs, z, size, Z, masks):
    """z = 何段目まで寄ったか（小数）。外側から3段ぶん重ねる。"""
    W, H = size
    k = int(z)
    s = Z ** (z - k)                     # いまの段の拡大率（1〜Z）
    out = None
    for j in range(3):
        idx = k + j
        if idx >= len(imgs):
            break
        scale = s / (Z ** j)             # この絵の拡大率（画面に対して）
        w, h = W * scale, H * scale
        if w < 8:
            break
        src = imgs[idx]
        if scale >= 1:                   # 画面より大きい：中央を切り抜く
            cw, ch = W / scale, H / scale
            box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
            layer = src.resize(size, Image.BICUBIC, box=box)
            if out is None:
                out = layer
                continue
            mask = masks[(W, H)].resize(size, Image.BILINEAR, box=box)
            out.paste(layer, (0, 0), mask)
        else:                            # 画面より小さい：中央に置く
            iw, ih = max(2, int(round(w))), max(2, int(round(h)))
            layer = src.resize((iw, ih), Image.BICUBIC)
            mask = masks[(W, H)].resize((iw, ih), Image.BILINEAR)
            if out is None:
                out = Image.new("RGB", size, (0, 0, 0))
            out.paste(layer, ((W - iw) // 2, (H - ih) // 2), mask)
    return out


def main(spec, out_dir, no_voice=False):
    ep = json.loads(pathlib.Path(spec).read_text(encoding="utf-8"))
    size = tuple(ep.get("size", [1080, 1920]))
    W, H = size
    Z = ep.get("zoom", 3.0)
    sec = ep.get("seconds", 5.0)
    hold = ep.get("hold", 1.2)
    layers = ep["layers"]
    imgs = []
    for L in layers:
        p = B.pick(L["image"])
        if not p:
            raise SystemExit(f"絵がまだありません: {L['image']}")
        imgs.append(load(p, size))
    masks = {(W, H): oval_mask(size, 0.22)}
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    n = len(imgs) - 1                     # ズームの段数
    total = hold + n * sec + hold
    # 映像：フレームを ffmpeg に流しこむ
    video = tmp / "video.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", str(video)],
                          stdin=subprocess.PIPE)
    nf = int(total * FPS)
    for i in range(nf):
        t = i / FPS
        u = min(max((t - hold) / sec, 0), n)
        z = u  # 一定の速さで寄り続ける（最初と最後は hold で止める）
        im = frame(imgs, z, size, Z, masks) if z < n else imgs[-1].copy()
        k = min(int(u + 0.15), n)
        cap = layers[k].get("caption")
        if cap:
            im = im.convert("RGBA")
            B.caption(im, ep, cap, H)
            im = im.convert("RGB")
        ff.stdin.write(im.tobytes())
    ff.stdin.close()
    ff.wait()
    # 音：段ごとの語り＋BGM
    parts = []
    for k, L in enumerate(layers):
        if not L.get("voice"):
            continue
        vp = str(tmp / f"v{k:02d}.wav")
        if no_voice:
            R.silence(max(1.2, len(L["voice"]) * 0.13), vp)
        else:
            R.tts(L["voice"], vp)
        start = 0.3 if k == 0 else hold + (k - 0.15) * sec
        parts.append((start, vp))
    voice = str(tmp / "voice.wav")
    inputs, filt = [], []
    for k, (st, p) in enumerate(parts):
        inputs += ["-i", p]
        ms = int(st * 1000)
        filt.append(f"[{k}:a]aresample={R.SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
    filt.append("".join(f"[a{k}]" for k in range(len(parts))) + f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.3f}[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(R.SR), voice], check=True)
    music = str(tmp / "bgm.wav")
    R.BGM.save(music, R.BGM.make(total, ep.get("style", "zoom"), seed=sum(map(ord, ep["id"]))))
    vol = ep.get("bgm_volume", 0.22)
    audio = tmp / "audio.wav"
    fc = (f"[1:a]volume={vol},afade=t=out:st={total - 1.5:.2f}:d=1.5[m];[0:a]asplit=2[v1][v2];"
          f"[m][v2]sidechaincompress=threshold=0.02:ratio=4:attack=20:release=450[md];[v1][md]amix=inputs=2:normalize=0[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", music, "-filter_complex", fc, "-map", "[o]", "-ar", str(R.SR), str(audio)],
                   check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", "-movflags", "+faststart", "-shortest", str(out)], check=True)
    # 確認用の一覧（等間隔に6コマ）
    shots = [frame(imgs, min(x, n - 1e-6), size, Z, masks).resize((270, 480)) for x in [0, n * 0.2, n * 0.4, n * 0.6, n * 0.8, n * 0.97]]
    S = Image.new("RGB", (270 * 6, 480))
    for i, s in enumerate(shots):
        S.paste(s, (i * 270, 0))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{total:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--no-voice" in sys.argv)
