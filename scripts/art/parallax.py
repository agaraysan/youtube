#!/usr/bin/env python3
"""名画（パブリックドメイン）に奥行きをつけて、絵の中をカメラが進むように見せる動画（type: parallax）。

spec: {"id","type":"parallax","caption",
       "items": [{"commons": ファイル名, "title": 作品名, "sub": "作者・年"}], "seconds_each": 5.5}
奥行きは Depth Anything V2（小）で推定する。近いものほど大きく動くので、立体的に見える。
"""
import pathlib, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ambient
from common import ROOT, OW, OH, FPS, fetch, commons, caption_layer, over, Writer, font


def generate(spec):
    out = ROOT / "assets" / "art" / spec["id"]
    out.mkdir(parents=True, exist_ok=True)
    pipe = None
    for i, it in enumerate(spec["items"]):
        img_p, dep_p = out / f"img_{i:02d}.jpg", out / f"depth_{i:02d}.png"
        if not img_p.exists():
            try:
                fetch(commons(it["commons"], 2400), str(img_p) + ".tmp")
                Image.open(str(img_p) + ".tmp").convert("RGB").save(img_p, quality=93)
                pathlib.Path(str(img_p) + ".tmp").unlink()
            except Exception as e:
                print("fetch failed", it["commons"], e); continue
        if not dep_p.exists():
            if pipe is None:
                from transformers import pipeline
                pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf")
            img = Image.open(img_p).convert("RGB")
            dm = np.asarray(pipe(img)["depth"].resize(img.size, Image.BICUBIC), dtype=np.float32)
            dm = (dm - dm.min()) / (dm.max() - dm.min() + 1e-6)
            Image.fromarray((dm * 65535).astype(np.uint16)).save(dep_p)
        print(spec["id"], "item", i, "ok", flush=True)
    return 0


def title_layer(title, sub):
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f, fs = font(66), font(40)
    y = OH - 420
    d.rectangle((0, y - 40, OW, y + 170), fill=(0, 0, 0, 120))
    d.text(((OW - d.textlength(title, font=f)) / 2, y), title, font=f, fill=(255, 255, 255, 255))
    d.text(((OW - d.textlength(sub, font=fs)) / 2, y + 95), sub, font=fs, fill=(230, 220, 200, 255))
    return np.asarray(im, dtype=np.float32)


class Scene:
    """絵を縦長の画面に合わせ、横にパンしながら奥へ進む。"""

    def __init__(self, img, depth, move):
        import cv2
        self.cv2 = cv2
        s = OH * 1.18 / img.height
        if img.width * s < OW * 1.18:
            s = OW * 1.18 / img.width
        size = (round(img.width * s), round(img.height * s))
        self.img = np.asarray(img.resize(size, Image.LANCZOS), dtype=np.float32)
        d = np.asarray(depth.resize(size, Image.BILINEAR), dtype=np.float32) / 65535
        self.d = cv2.GaussianBlur(d, (0, 0), 6)
        self.h, self.w = self.d.shape
        self.move = move
        gx, gy = np.meshgrid(np.arange(OW, dtype=np.float32), np.arange(OH, dtype=np.float32))
        self.gx, self.gy = gx - OW / 2, gy - OH / 2

    def frame(self, u):
        cv2 = self.cv2
        x0, x1, zoom, amp = self.move
        span = max(0.0, self.w - OW * 1.05)
        cx = self.w / 2 + (x0 + (x1 - x0) * u) * span / 2
        cy = self.h / 2
        z = 1.0 + zoom * u
        # まず奥行きなしの位置で、その場所の深さを読む
        mx, my = cx + self.gx / z, cy + self.gy / z
        dep = cv2.remap(self.d, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        zz = z * (1 + 0.10 * zoom * u * 4 * (dep - 0.5))  # 近いものほど大きく寄る
        shift = amp * (u - 0.5) * (dep - 0.5) * OW  # 近いものほど横に大きく動く
        mx = cx + (self.gx - shift) / zz
        my = cy + self.gy / zz
        return cv2.remap(self.img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


MOVES = [(-0.8, 0.8, 0.18, 0.10), (0.8, -0.6, 0.22, 0.09), (0.0, 0.0, 0.35, 0.06), (-0.5, 0.6, 0.20, 0.10)]


def render(spec, out_mp4):
    d = ROOT / "assets" / "art" / spec["id"]
    scenes, titles = [], []
    for i, it in enumerate(spec["items"]):
        if (d / f"img_{i:02d}.jpg").exists() and (d / f"depth_{i:02d}.png").exists():
            scenes.append(Scene(Image.open(d / f"img_{i:02d}.jpg").convert("RGB"), Image.open(d / f"depth_{i:02d}.png"),
                                it.get("move", MOVES[len(scenes) % len(MOVES)])))
            titles.append(title_layer(it.get("title", ""), it.get("sub", "")))
    each, fade = spec.get("seconds_each", 5.5), 0.7
    n = len(scenes)
    total = each * n
    cap = caption_layer(spec["caption"], spec.get("caption_sub")) if spec.get("caption") else None
    wav = pathlib.Path(out_mp4).with_suffix(".wav")
    ambient.save(str(wav), ambient.make(total, spec.get("mood", "epic"), seed=11))
    w = Writer(out_mp4, wav)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        i = min(n - 1, int(t // each))
        local = t - i * each
        frame = scenes[i].frame((local + fade) / (each + fade))
        frame = over(frame, titles[i], min(1.0, (local - 0.4) / 0.4, (each - 0.5 - local) / 0.4) if local > 0.4 else 0)
        if i + 1 < n and local > each - fade:
            a = (local - (each - fade)) / fade
            frame = frame * (1 - a) + scenes[i + 1].frame((local - each + fade) / (each + fade)) * a
        if cap is not None and t < 3.0:
            frame = over(frame, cap, min(1.0, t / 0.3, (3.0 - t) / 0.5))
        w.write(frame)
    w.close()
    wav.unlink(missing_ok=True)
    print("wrote", out_mp4, f"{total:.1f}s")
