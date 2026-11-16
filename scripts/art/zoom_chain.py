#!/usr/bin/env python3
"""無限ズーム用の絵を、内側から外側へ1枚ずつ Codex に描き足してもらう（アウトペイント）。

使い方: zoom_chain.py art/zoom001.json
結果: assets/art/<id>/layer_00.jpg（いちばん外側）… layer_NN.jpg（いちばん内側）
各絵の中央 1/ratio には、1つ内側の絵を縮小したものを画素ごと貼り戻すので、つなぎ目がずれない。
spec に "seed": {"commons": "ファイル名"} があれば、いちばん内側はその名画（パブリックドメイン）にする。
"""
import pathlib, sys
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import ROOT, codex, find, gen_image, fetch, commons, cover, feather_mask, load_spec


def main(spec_path):
    spec = load_spec(spec_path)
    W, H = spec["size"]
    r = spec.get("ratio", 3)
    layers = spec["layers"]
    n = len(layers)
    out = ROOT / "assets" / "art" / spec["id"]
    work = ROOT / "tmp_art" / spec["id"]
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    log = out / "codex.log"
    style = spec.get("style", "")
    iw, ih = W // r, H // r
    x0, y0 = (W - iw) // 2, (H - ih) // 2
    for j in range(n - 1, -1, -1):  # 内側から
        dst = out / f"layer_{j:02d}.jpg"
        if dst.exists():
            continue
        raw = work / f"raw_{j:02d}"
        if j == n - 1:
            if spec.get("seed"):
                fetch(commons(spec["seed"]["commons"]), str(raw) + ".jpg")
                img = cover(Image.open(find(raw)).convert("RGB"), W, H)
            else:
                got = gen_image(layers[j], raw, (W, H), log, style)
                if not got:
                    print("failed layer", j); return 1
                img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
        else:
            inner = Image.open(out / f"layer_{j + 1:02d}.jpg").convert("RGB")
            small = inner.resize((iw, ih), Image.LANCZOS)
            canvas = Image.new("RGB", (W, H), (128, 128, 128))
            canvas.paste(small, (x0, y0))
            cpath = work / f"canvas_{j:02d}.png"
            canvas.save(cpath)
            task = (f"画像 {cpath} を開いて見てください。中央の長方形（x {x0}〜{x0 + iw}、y {y0}〜{y0 + ih}）にはすでに絵があり、"
                    f"まわりの灰色の部分は空白です。内蔵の画像生成機能でこの画像を編集し、灰色の部分を描き足して、"
                    f"画像全体が次の1枚の絵になるようにしてください: {layers[j]}\n"
                    f"中央の長方形の中身は、位置も大きさも変えずにそのまま残し、まわりと自然につながるように描いてください。"
                    f"中央の絵は、全体の絵の一部（{layers[j + 1]}）に見えるようにします。中央の絵とまわりは同じ視点・同じ光の向きで描き、"
                    f"中央の長方形の形の枠や境目が見えないようにしてください。画風: {style}\n"
                    f"画像の中に文字・ロゴ・透かし・額縁の外の余白は入れないでください。"
                    f"縦長 {W}x{H} で、{raw}.png に保存してください。ほかのファイルは変更しないでください。")
            for _ in range(2):
                codex(task, log)
                if find(raw):
                    break
            got = find(raw)
            if not got:
                print("failed layer", j); return 1
            img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
            img.paste(small, (x0, y0), feather_mask(iw, ih, max(8, iw // 14)))  # 中央は内側の絵の画素で貼り戻す
        img.save(dst, quality=93)
        print(spec["id"], "layer", j, "ok", flush=True)
    if spec.get("loop"):
        return close_loop(spec, out, work, log, W, H, iw, ih, x0, y0)
    return 0


def close_loop(spec, out, work, log, W, H, iw, ih, x0, y0):
    """いちばん内側の絵の中央に、いちばん外側の絵を埋め込む。こうすると最後のズームが最初の場面にぴったり戻る。
    中央のまわりの細い帯だけを Codex に描き直してもらい、帯の外側は元の画素のまま残す。"""
    n = len(spec["layers"])
    dst = out / "loop_inner.jpg"
    if dst.exists():
        return 0
    inner = Image.open(out / f"layer_{n - 1:02d}.jpg").convert("RGB")
    first = Image.open(out / "layer_00.jpg").convert("RGB").resize((iw, ih), Image.LANCZOS)
    bw, bh = int(iw * 1.5), int(ih * 1.5)  # 描き直す帯の外枠
    bx, by = (W - bw) // 2, (H - bh) // 2
    canvas = inner.copy()
    canvas.paste((128, 128, 128), (bx, by, bx + bw, by + bh))
    canvas.paste(first, (x0, y0))
    cpath = work / "loop_canvas.png"
    canvas.save(cpath)
    raw = work / "loop_raw"
    task = (f"画像 {cpath} を開いて見てください。中央の長方形（x {x0}〜{x0 + iw}、y {y0}〜{y0 + ih}）の絵と、"
            f"いちばん外側の絵は、どちらもそのまま残します。そのあいだの灰色の帯だけを、内蔵の画像生成機能で描き足してください。"
            f"全体は次の1枚の絵になります: {spec['layers'][-1]}\n中央の絵（{spec['layers'][0]}）が、その入口の向こうに見えるように、"
            f"帯の部分で自然につなげてください。境目や枠の線が見えないようにします。画風: {spec.get('style', '')}\n"
            f"画像の中に文字・ロゴ・透かしは入れないでください。縦長 {W}x{H} で {raw}.png に保存してください。ほかのファイルは変更しないでください。")
    for _ in range(2):
        codex(task, log)
        if find(raw):
            break
    if not find(raw):
        print("loop closure failed"); return 1
    got = Image.open(find(raw)).convert("RGB").resize((W, H), Image.LANCZOS)
    res = inner.copy()
    band = got.crop((bx, by, bx + bw, by + bh))
    res.paste(band, (bx, by), feather_mask(bw, bh, max(10, bw // 16)))
    res.paste(first, (x0, y0), feather_mask(iw, ih, max(8, iw // 14)))
    res.save(dst, quality=93)
    print(spec["id"], "loop closed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
