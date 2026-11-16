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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
