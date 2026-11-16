#!/usr/bin/env python3
"""「枠をくぐる」無限ズームの絵を作る（spec に "frame": true のとき。zoom_chain.py の改良版）。

zoom_chain.py との違い:
- 各場面の中央の長方形は、窓・戸・写真・鏡などの「入口」の内側そのものにする。入口の枠を長方形のすぐ外側に描かせ、
  ズームすると枠をくぐって次の場面に入るようにする（spec の openings[j] がその入口の名前）。
- Codex は描き足すときに中央の絵を少しずらしたり大きさを変えたりする。そのままだと、まわりの絵と貼り戻した中央の絵がずれる。
  そこで、Codex の絵の中で中央の絵がどこに来たかを特徴点で探し、Codex の絵全体を動かして中央がぴったり合うようにしてから貼り戻す。
- 合わせきれない（ずれが大きい・中央を描き変えた）ときは描き直してもらう。

使い方: zoom_frame.py art/zoom121.json
結果は zoom_chain.py と同じ（assets/art/<id>/layer_NN.jpg と loop_inner.jpg）。描画は zoom_render.py がそのまま使う。
"""
import json, pathlib, sys
import numpy as np
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import ROOT, codex, find, gen_image, feather_mask, load_spec

try:
    import cv2
except ImportError:  # 手元で試すとき用
    cv2 = None


def align(raw, small, x0, y0):
    """raw（Codex の絵）の中で small（中央に置いた絵）がどこにあるかを探し、raw を動かして中央を (x0, y0) にそろえる。
    戻り値: (そろえた絵, 合わせたあとの中央の平均の色の差 0〜255, 動かした量の説明)"""
    W, H = raw.size
    iw, ih = small.size
    if cv2 is None:
        return raw, center_diff(raw, small, x0, y0), "no-cv2"
    g_raw = cv2.cvtColor(np.asarray(raw), cv2.COLOR_RGB2GRAY)
    g_small = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(4000)
    # 探す範囲は中央の長方形を少し広げたところだけ（まわりの似た模様に引っぱられないように）
    m = np.zeros_like(g_raw)
    px, py = iw // 3, ih // 3
    m[max(0, y0 - py):y0 + ih + py, max(0, x0 - px):x0 + iw + px] = 255
    k1, d1 = sift.detectAndCompute(g_raw, m)
    k2, d2 = sift.detectAndCompute(g_small, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return raw, center_diff(raw, small, x0, y0), "few-features"
    pairs = cv2.BFMatcher().knnMatch(d2, d1, k=2)
    good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 12:
        return raw, center_diff(raw, small, x0, y0), f"few-matches {len(good)}"
    src = np.float32([k1[g.trainIdx].pt for g in good])                       # raw の中の位置
    dst = np.float32([(k2[g.queryIdx].pt[0] + x0, k2[g.queryIdx].pt[1] + y0) for g in good])  # 本来の位置
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=5000)
    if M is None or inl is None or inl.sum() < 10:
        return raw, center_diff(raw, small, x0, y0), "no-transform"
    s = float(np.hypot(M[0, 0], M[1, 0]))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    if not (0.75 < s < 1.33) or abs(rot) > 4:
        return raw, center_diff(raw, small, x0, y0), f"odd-transform s={s:.2f} rot={rot:.1f}"
    out = cv2.warpAffine(np.asarray(raw), M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    out = Image.fromarray(out)
    info = f"shift=({M[0, 2]:.1f},{M[1, 2]:.1f}) s={s:.3f} rot={rot:.2f} inliers={int(inl.sum())}"
    return out, center_diff(out, small, x0, y0), info


def center_diff(img, small, x0, y0):
    iw, ih = small.size
    a = np.asarray(img.crop((x0, y0, x0 + iw, y0 + ih)).convert("L").resize((iw // 4, ih // 4)), np.float32)
    b = np.asarray(small.convert("L").resize((iw // 4, ih // 4)), np.float32)
    return float(np.abs(a - b).mean())


def align_outer(img, ref, box):
    """img（Codex の絵）を、ref（元の絵）の帯 box より外側の部分にぴったり重なるよう動かす。
    帯の外側がずれたまま貼ると、帯のふちで2枚の絵が二重に透けて、ぼやけた帯のような跡が出るため。"""
    if cv2 is None:
        return img, "no-cv2"
    W, H = img.size
    bx0, by0, bx1, by1 = box
    m = np.full((H, W), 255, np.uint8)
    m[by0 + 40:by1 - 40, bx0 + 40:bx1 - 40] = 0  # 帯の内側は描き直されているので使わない（ふち付近は使う）
    g_img = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    g_ref = cv2.cvtColor(np.asarray(ref), cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create(5000)
    k1, d1 = sift.detectAndCompute(g_img, m)
    k2, d2 = sift.detectAndCompute(g_ref, m)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return img, "few-features"
    pairs = cv2.BFMatcher().knnMatch(d1, d2, k=2)
    good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 12:
        return img, f"few-matches {len(good)}"
    src = np.float32([k1[g.queryIdx].pt for g in good])
    dst = np.float32([k2[g.trainIdx].pt for g in good])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=5000)
    if M is None or inl is None or inl.sum() < 10:
        return img, "no-transform"
    s = float(np.hypot(M[0, 0], M[1, 0]))
    if not (0.85 < s < 1.18):
        return img, f"odd-scale {s:.2f}"
    out = cv2.warpAffine(np.asarray(img), M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return Image.fromarray(out), f"outer shift=({M[0, 2]:.1f},{M[1, 2]:.1f}) s={s:.3f} inliers={int(inl.sum())}"


def ring_diff(a, b, box, w=40):
    """帯のふち（貼り合わせる幅）での2枚の色の差。大きいとふちに二重の跡が出る。"""
    bx0, by0, bx1, by1 = box
    A, B = np.asarray(a, np.float32), np.asarray(b, np.float32)
    m = np.zeros(A.shape[:2], bool)
    m[by0:by1, bx0:bx1] = True
    m[by0 + w:by1 - w, bx0 + w:bx1 - w] = False
    return float(np.abs(A[m] - B[m]).mean())


def leftover_gray(img, box, x0, y0, iw, ih):
    """描き足すはずだった灰色が残っている割合（中央の長方形は除く）。残っていると帯のような跡になる。"""
    a = np.asarray(img, np.int16)
    g = (np.abs(a - 128) < 7).all(-1)
    bx0, by0, bx1, by1 = box
    m = np.zeros(g.shape, bool)
    m[by0:by1, bx0:bx1] = True
    m[y0:y0 + ih, x0:x0 + iw] = False
    return float(g[m].mean()) if m.any() else 0.0


FRAME_RULES = ("中央の長方形のふちに、入口の枠（ふち）の内側がちょうど重なるように、枠を長方形のすぐ外側に描いてください。"
               "枠が長方形の中にはみ出したり、長方形と枠のあいだにすき間ができたりしないようにします。"
               "入口は真正面から見た形（四辺が画面とまっすぐ平行）にし、斜めや遠近でゆがめないでください。"
               "中央の絵は、その入口の向こう（奥）に見える場面です。")


def outpaint(spec, j, small, work, log, W, H, x0, y0):
    layers, openings, style = spec["layers"], spec["openings"], spec.get("style", "")
    iw, ih = small.size
    canvas = Image.new("RGB", (W, H), (128, 128, 128))
    canvas.paste(small, (x0, y0))
    cpath = work / f"canvas_{j:02d}.png"
    canvas.save(cpath)
    best = None
    for attempt in range(3):
        raw = work / f"raw_{j:02d}_{attempt}"
        task = (f"画像 {cpath} を開いて見てください。中央の長方形（x {x0}〜{x0 + iw}、y {y0}〜{y0 + ih}）にはすでに絵があり、"
                f"まわりの灰色の部分は空白です。内蔵の画像生成機能でこの画像を編集し、灰色の部分を描き足して、"
                f"画像全体が次の1枚の絵になるようにしてください: {layers[j]}\n"
                f"中央の長方形は「{openings[j]}」の内側です。{FRAME_RULES}\n"
                f"中央の長方形の中身（{layers[j + 1]}）は、位置も大きさも変えず、描き直さずにそのまま残してください。"
                f"中央の絵とまわりは同じ光の向きで描きます。画風: {style}\n"
                f"画像の中に文字・ロゴ・透かしは入れないでください。縦長 {W}x{H} で、{raw}.png に保存してください。ほかのファイルは変更しないでください。")
        codex(task, log)
        got = find(raw)
        if not got:
            continue
        img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
        fixed, diff, info = align(img, small, x0, y0)
        gray = leftover_gray(img, (0, 0, W, H), x0, y0, iw, ih)
        if gray > 0.01:
            diff += 100  # 灰色が残った絵は使わない（ほかに無いときだけ使う）
            info += f" gray={gray:.3f}"
        print(spec["id"], "layer", j, "try", attempt, "diff", round(diff, 1), info, flush=True)
        if best is None or diff < best[1]:
            best = (fixed, diff)
        if diff < 16:  # 中央がほぼ元のまま＝まわりとずれずにつながる
            break
    return best


def main(spec_path):
    spec = load_spec(spec_path)
    W, H = spec["size"]
    r = spec.get("ratio", 3)
    layers = spec["layers"]
    n = len(layers)
    assert len(spec["openings"]) == n, "openings は layers と同じ数（最後は最初の場面への入口）"
    out = ROOT / "assets" / "art" / spec["id"]
    work = ROOT / "tmp_art" / spec["id"]
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    log = out / "codex.log"
    style = spec.get("style", "")
    iw, ih = W // r, H // r
    x0, y0 = (W - iw) // 2, (H - ih) // 2
    report = {}
    for j in range(n - 1, -1, -1):  # 内側から
        dst = out / f"layer_{j:02d}.jpg"
        if dst.exists():
            continue
        if j == n - 1:
            got = gen_image(f"{layers[j]} 画面のちょうど中央に、縦長の「{spec['openings'][j]}」が真正面に見える。",
                            work / f"raw_{j:02d}", (W, H), log, style)
            if not got:
                print("failed layer", j); return 1
            img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
        else:
            inner = Image.open(out / f"layer_{j + 1:02d}.jpg").convert("RGB")
            small = inner.resize((iw, ih), Image.LANCZOS)
            best = outpaint(spec, j, small, work, log, W, H, x0, y0)
            if not best:
                print("failed layer", j); return 1
            img, report[j] = best
            img.paste(small, (x0, y0), feather_mask(iw, ih, max(6, iw // 24)))  # 中央は内側の絵の画素で貼り戻す
        img.save(dst, quality=93)
        print(spec["id"], "layer", j, "ok", flush=True)
    if report:
        (out / "align.json").write_text(json.dumps({str(k): round(v, 1) for k, v in sorted(report.items())}))
    return close_loop(spec, out, work, log, W, H, iw, ih, x0, y0)


def close_loop(spec, out, work, log, W, H, iw, ih, x0, y0):
    """いちばん内側の絵の入口の中に、いちばん外側の絵を入れる。入口のまわりの帯だけ描き直してもらい、外は元の画素のまま。"""
    n = len(spec["layers"])
    dst = out / "loop_inner.jpg"
    if dst.exists():
        return 0
    inner = Image.open(out / f"layer_{n - 1:02d}.jpg").convert("RGB")
    first = Image.open(out / "layer_00.jpg").convert("RGB").resize((iw, ih), Image.LANCZOS)
    bw, bh = int(iw * 1.8), int(ih * 1.8)  # 描き直す帯の外枠（入口の枠を描き直せる広さ）
    bx, by = (W - bw) // 2, (H - bh) // 2
    canvas = inner.copy()
    canvas.paste((128, 128, 128), (bx, by, bx + bw, by + bh))
    canvas.paste(first, (x0, y0))
    cpath = work / "loop_canvas.png"
    canvas.save(cpath)
    best = None
    for attempt in range(3):
        raw = work / f"loop_raw_{attempt}"
        task = (f"画像 {cpath} を開いて見てください。中央の長方形（x {x0}〜{x0 + iw}、y {y0}〜{y0 + ih}）の絵と、"
                f"灰色の帯より外側の絵は、どちらもそのまま残します。そのあいだの灰色の帯だけを、内蔵の画像生成機能で描き足してください。"
                f"全体は次の1枚の絵になります: {spec['layers'][-1]}\n"
                f"中央の長方形は「{spec['openings'][-1]}」の内側です。{FRAME_RULES}"
                f"帯の外側の絵とも自然につなげ、境目が見えないようにします。画風: {spec.get('style', '')}\n"
                f"画像の中に文字・ロゴ・透かしは入れないでください。縦長 {W}x{H} で {raw}.png に保存してください。ほかのファイルは変更しないでください。")
        codex(task, log)
        got = find(raw)
        if not got:
            continue
        img = Image.open(got).convert("RGB").resize((W, H), Image.LANCZOS)
        box = (bx, by, bx + bw, by + bh)
        fixed, info = align_outer(img, inner, box)  # 帯のふちで外側とぴったり重なるように
        cdiff = center_diff(fixed, first, x0, y0)
        rdiff = ring_diff(fixed, inner, box)
        diff = cdiff + rdiff
        gray = leftover_gray(img, box, x0, y0, iw, ih)
        if gray > 0.01:
            diff += 100
            info += f" gray={gray:.3f}"
        print(spec["id"], "loop try", attempt, "center", round(cdiff, 1), "ring", round(rdiff, 1), info, flush=True)
        if best is None or diff < best[1]:
            best = (fixed, diff)
        if cdiff < 16 and rdiff < 12:
            break
    if not best:
        print("loop closure failed"); return 1
    got = best[0]
    res = inner.copy()
    band = got.crop((bx, by, bx + bw, by + bh))
    res.paste(band, (bx, by), feather_mask(bw, bh, 40))  # ふち40画素で外側へ溶かす（align_outer で重ねてあるので二重にならない）
    res.paste(first, (x0, y0), feather_mask(iw, ih, max(6, iw // 24)))
    res.save(dst, quality=93)
    print(spec["id"], "loop closed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
