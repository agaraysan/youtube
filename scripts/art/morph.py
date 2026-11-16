#!/usr/bin/env python3
"""同じ場所・同じ構図の絵が、季節や時代で移り変わる動画（type: morph）。

spec: {"id","type":"morph","size":[1024,1536],"style","caption",
       "base": 元の絵の内容 か "seed": {"commons": 名画のファイル名},
       "base_label": 最初の絵の見出し,
       "variants": [{"edit": 変える内容, "label": 見出し}], "seconds_each": 3.2}
生成: 元の絵 → 各 variant を「元の絵から」描き変える（構図がそろう）。
描画: ずっとゆっくり寄りながら、光る線が横切るワイプで次の絵へ移る。
"""
import pathlib, sys
import numpy as np
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ambient
from common import (ROOT, OW, OH, FPS, gen_image, edit_image, fetch, commons, find, cover, caption_layer, over,
                    Writer, load_spec, font)
from PIL import ImageDraw


def generate(spec):
    W, H = spec["size"]
    out = ROOT / "assets" / "art" / spec["id"]
    work = ROOT / "tmp_art" / spec["id"]
    out.mkdir(parents=True, exist_ok=True); work.mkdir(parents=True, exist_ok=True)
    log = out / "codex.log"
    style = spec.get("style", "")
    base = out / "img_00.jpg"
    if not base.exists():
        if spec.get("seed"):
            fetch(commons(spec["seed"]["commons"]), str(work / "seed.jpg"))
            img = Image.open(work / "seed.jpg").convert("RGB")
            img = cover(img, W, H) if spec.get("crop", True) else img.resize((W, H), Image.LANCZOS)
        else:
            got = gen_image(spec["base"], work / "base", (W, H), log, style)
            if not got:
                return 1
            img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
        img.save(base, quality=93)
    src = work / "base_src.png"
    Image.open(base).save(src)
    for i, v in enumerate(spec["variants"], 1):
        dst = out / f"img_{i:02d}.jpg"
        if dst.exists():
            continue
        got = edit_image(src, v["edit"], work / f"var_{i:02d}", (W, H), log, style)
        if not got:
            print("failed variant", i); return 1
        Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS).save(dst, quality=93)
        print(spec["id"], "variant", i, "ok", flush=True)
    return 0


def label_layer(text):
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(96)
    w = d.textlength(text, font=f)
    x, y = (OW - w) / 2, OH - 430
    d.rounded_rectangle((x - 50, y - 20, x + w + 50, y + 130), 36, fill=(0, 0, 0, 120))
    d.text((x, y), text, font=f, fill=(255, 255, 255, 255))
    return np.asarray(im, dtype=np.float32)


def view(img, k, ox=0.0):
    """画面いっぱい × k 倍に寄った絵（中心から ox だけ横にずらす）。"""
    W, H = img.size
    s = max(OW / W, OH / H) * k
    cw, ch = OW / s, OH / s
    cx = W / 2 + ox * (W - cw) / 2
    box = (cx - cw / 2, H / 2 - ch / 2, cx + cw / 2, H / 2 + ch / 2)
    return np.asarray(img.resize((OW, OH), Image.BICUBIC, box=box), dtype=np.float32)


def render(spec, out_mp4):
    d = ROOT / "assets" / "art" / spec["id"]
    imgs = [Image.open(p).convert("RGB") for p in sorted(d.glob("img_*.jpg"))]
    labels = [spec.get("base_label", "")] + [v.get("label", "") for v in spec["variants"]]
    labs = [label_layer(t) if t else None for t in labels]
    each, tr = spec.get("seconds_each", 3.2), 1.1
    n = len(imgs)
    total = 1.0 + each * n + 0.8
    cap = caption_layer(spec["caption"], spec.get("caption_sub")) if spec.get("caption") else None
    wav = pathlib.Path(out_mp4).with_suffix(".wav")
    ambient.save(str(wav), ambient.make(total, spec.get("mood", "calm"), seed=3))
    w = Writer(out_mp4, wav)
    xs = np.arange(OW, dtype=np.float32)[None, :, None]
    ys = np.arange(OH, dtype=np.float32)[:, None, None]
    for fi in range(int(total * FPS)):
        t = fi / FPS
        k = 1.0 + 0.12 * t / total
        p = max(0.0, t - 1.0)
        i = min(n - 1, int(p // each))
        frame = view(imgs[i], k)
        local = p - i * each
        lab_a = 1.0
        if i + 1 < n and local > each - tr:  # 斜めのワイプで次の絵へ
            q = (local - (each - tr)) / tr
            q = q * q * (3 - 2 * q)
            nxt = view(imgs[i + 1], k)
            edge = (xs * 0.35 + ys) / (OH + OW * 0.35)  # 0〜1（左上→右下）
            pos = q * 1.25 - 0.12
            a = np.clip((pos - edge) / 0.06 + 0.5, 0, 1)
            glow = np.exp(-((edge - pos) / 0.012) ** 2) * 180 * np.sin(np.pi * q)
            frame = frame * (1 - a) + nxt * a + glow
            lab_a = 1 - q
        if labs[i] is not None:
            frame = over(frame, labs[i], lab_a * min(1.0, local / 0.4) if t > 1.0 else 0)
        if i + 1 < n and local > each - tr * 0.4 and labs[i + 1] is not None:
            frame = over(frame, labs[i + 1], (local - (each - tr * 0.4)) / (tr * 0.4))
        if cap is not None and t < 3.0:
            frame = over(frame, cap, min(1.0, t / 0.3, (3.0 - t) / 0.5))
        if t > total - 0.8:  # 最初の絵へ戻してループ
            a = (t - (total - 0.8)) / 0.8
            frame = frame * (1 - a) + view(imgs[0], 1.0) * a
        w.write(frame)
    w.close()
    wav.unlink(missing_ok=True)
    print("wrote", out_mp4, f"{total:.1f}s")
