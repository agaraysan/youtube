#!/usr/bin/env python3
"""テーマに沿ったAIの絵を、ゆっくり動かしながら見せる動画（type: slides）。「もしも〇〇だったら」など。

spec: {"id","type":"slides","size":[1024,1536],"style","caption",
       "items": [{"prompt": 絵の内容, "label": 見出し}], "seconds_each": 3.0}
"""
import pathlib, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ambient
from common import ROOT, OW, OH, FPS, gen_image, caption_layer, over, Writer, font


def generate(spec):
    W, H = spec["size"]
    out = ROOT / "assets" / "art" / spec["id"]
    work = ROOT / "tmp_art" / spec["id"]
    out.mkdir(parents=True, exist_ok=True); work.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(spec["items"]):
        dst = out / f"img_{i:02d}.jpg"
        if dst.exists():
            continue
        got = gen_image(it["prompt"], work / f"img_{i:02d}", (W, H), out / "codex.log", spec.get("style", ""))
        if not got:
            print("failed item", i); continue  # 1枚失敗しても残りで作る
        Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS).save(dst, quality=93)
        print(spec["id"], "item", i, "ok", flush=True)
    return 0


def label_layer(text, num):
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f, fn = font(70), font(40)
    w = d.textlength(text, font=f)
    y = OH - 470
    d.rectangle((0, y - 40, OW, y + 150), fill=(0, 0, 0, 110))
    nt = f"{num:02d}"
    d.text(((OW - d.textlength(nt, font=fn)) / 2, y - 20), nt, font=fn, fill=(255, 210, 120, 255))
    d.text(((OW - w) / 2, y + 35), text, font=f, fill=(255, 255, 255, 255))
    return np.asarray(im, dtype=np.float32)


MOVES = [(1.0, 1.15, -0.3, 0.3), (1.15, 1.0, 0.3, -0.2), (1.05, 1.2, 0.0, 0.0), (1.2, 1.05, -0.2, 0.3)]


def view(img, k, ox):
    W, H = img.size
    s = max(OW / W, OH / H) * k
    cw, ch = OW / s, OH / s
    cx = W / 2 + ox * (W - cw) / 2
    box = (cx - cw / 2, H / 2 - ch / 2, cx + cw / 2, H / 2 + ch / 2)
    return np.asarray(img.resize((OW, OH), Image.BICUBIC, box=box), dtype=np.float32)


def render(spec, out_mp4):
    d = ROOT / "assets" / "art" / spec["id"]
    pairs = [(Image.open(d / f"img_{i:02d}.jpg").convert("RGB"), it.get("label", ""))
             for i, it in enumerate(spec["items"]) if (d / f"img_{i:02d}.jpg").exists()]
    each, fade = spec.get("seconds_each", 3.0), 0.5
    n = len(pairs)
    total = 0.6 + each * n
    labs = [label_layer(t, i + 1) if t else None for i, (_, t) in enumerate(pairs)]
    cap = caption_layer(spec["caption"], spec.get("caption_sub")) if spec.get("caption") else None
    wav = pathlib.Path(out_mp4).with_suffix(".wav")
    ambient.save(str(wav), ambient.make(total, spec.get("mood", "calm"), seed=5))
    w = Writer(out_mp4, wav)

    def shot(i, local):
        k0, k1, x0, x1 = MOVES[i % len(MOVES)]
        u = min(1.0, max(0.0, local / (each + fade)))
        return view(pairs[i][0], k0 + (k1 - k0) * u, x0 + (x1 - x0) * u)

    for fi in range(int(total * FPS)):
        t = fi / FPS
        p = max(0.0, t - 0.6)
        i = min(n - 1, int(p // each))
        local = p - i * each
        frame = shot(i, local + fade)
        if labs[i] is not None:
            frame = over(frame, labs[i], min(1.0, local / 0.3, (each - local) / 0.3))
        if i + 1 < n and local > each - fade:
            a = (local - (each - fade)) / fade
            frame = frame * (1 - a) + shot(i + 1, local - each + fade) * a
        if cap is not None and t < 2.6:
            frame = over(frame, cap, min(1.0, t / 0.3, (2.6 - t) / 0.4))
        w.write(frame)
    w.close()
    wav.unlink(missing_ok=True)
    print("wrote", out_mp4, f"{total:.1f}s")
