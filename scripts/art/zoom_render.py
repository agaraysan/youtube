#!/usr/bin/env python3
"""無限ズームの絵の列から、縦長ショート動画（1080x1920）を作る。

使い方: zoom_render.py art/zoom001.json out.mp4 [layer_dir]
direction が "in"（既定）なら外側から内側へ、"out" なら内側から外側へ一定の速さで進む。
最後は最初の絵へ溶かしてループさせる。caption があれば最初に字幕を出す。
"""
import math, pathlib, sys
import numpy as np
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ambient
from common import ROOT, OW, OH, FPS, feather_mask, caption_layer, over, Writer, load_spec


def place(frame, img, mask, k):
    """img を画面中央に k 倍で置いたときの見える部分を frame に重ねる。"""
    W, H = img.size
    rw, rh = W * k, H * k
    left, top = OW / 2 - rw / 2, OH / 2 - rh / 2
    ax0, ay0, ax1, ay1 = max(0, left), max(0, top), min(OW, left + rw), min(OH, top + rh)
    if ax1 - ax0 < 2 or ay1 - ay0 < 2:
        return
    box = ((ax0 - left) / k, (ay0 - top) / k, (ax1 - left) / k, (ay1 - top) / k)
    dx0, dy0, dx1, dy1 = int(round(ax0)), int(round(ay0)), int(round(ax1)), int(round(ay1))
    size = (dx1 - dx0, dy1 - dy0)
    part = np.asarray(img.resize(size, Image.BICUBIC, box=box), dtype=np.float32)
    if mask is None:
        frame[dy0:dy1, dx0:dx1] = part
        return
    a = np.asarray(mask.resize(size, Image.BILINEAR, box=box), dtype=np.float32)[..., None] / 255
    frame[dy0:dy1, dx0:dx1] = frame[dy0:dy1, dx0:dx1] * (1 - a) + part * a


def render_at(layers, mask, L, base_k, r):
    n = len(layers)
    j0 = min(n - 1, int(math.floor(L)))
    frame = np.zeros((OH, OW, 3), np.float32)
    for j in range(j0, min(n, j0 + 4)):
        place(frame, layers[j], None if j == j0 else mask, base_k * r ** (L - j))
    return frame


def main(spec_path, out_mp4, layer_dir=None):
    spec = load_spec(spec_path)
    r = spec.get("ratio", 3)
    d = pathlib.Path(layer_dir) if layer_dir else ROOT / "assets" / "art" / spec["id"]
    layers = [Image.open(p).convert("RGB") for p in sorted(d.glob("layer_*.jpg"))]
    n = len(layers)
    W, H = layers[0].size
    base_k = max(OW / W, OH / H)
    mask = feather_mask(W, H, max(8, (W // r) // 14))
    step = spec.get("seconds_per_step", 2.4)
    zin = spec.get("direction", "in") == "in"
    hold, loop = spec.get("hold", 0.8), 0.8
    zoom_s = step * (n - 1)
    total = hold + zoom_s + loop
    cap = caption_layer(spec["caption"], spec.get("caption_sub")) if spec.get("caption") else None
    wav = pathlib.Path(out_mp4).with_suffix(".wav")
    ambient.save(str(wav), ambient.make(total, spec.get("mood", "dream"), seed=7))
    w = Writer(out_mp4, wav)
    start = render_at(layers, mask, 0.0 if zin else n - 1.0, base_k, r)
    for i in range(int(total * FPS)):
        t = i / FPS
        u = min(1.0, max(0.0, (t - hold) / zoom_s))
        if not zin:  # 外へ向かうときは、見かけの速さが一定になるよう段を逆にたどる
            u = 1 - u
        frame = render_at(layers, mask, u * (n - 1), base_k, r)
        if t > hold + zoom_s:
            a = min(1.0, (t - hold - zoom_s) / loop)
            frame = frame * (1 - a) + start * a
        if cap is not None and t < 3.2:
            frame = over(frame, cap, min(1.0, t / 0.3, (3.2 - t) / 0.5))
        w.write(frame)
    w.close()
    wav.unlink(missing_ok=True)
    print("wrote", out_mp4, f"{total:.1f}s")


if __name__ == "__main__":
    main(*sys.argv[1:])
