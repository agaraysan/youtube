#!/usr/bin/env python3
"""間違い探しの2枚を画素で比べ、違いの場所を確かめる。

使い方: spotcheck.py 元の絵.png 違いの絵.png differences.json [出力.json]
- 2枚の差を取り、変わった場所のかたまりを数える。
- Codex の一覧（differences.json）と数・位置が合うかを確かめる。
- 合えば、画素の比較で出た正確な枠を書き出して 0 で終わる。合わなければ 1 で終わる。
"""
import json, sys
from PIL import Image, ImageChops, ImageFilter


def clusters(a, b, thr=40, grow=25, min_px=150):
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").point(lambda v: 255 if v > thr else 0)
    m = d.filter(ImageFilter.MaxFilter(9))
    W, H = m.size
    px = m.load()
    raw = d.load()
    seen = bytearray(W * H)
    boxes = []
    for y in range(0, H, 3):
        for x in range(0, W, 3):
            if px[x, y] and not seen[y * W + x]:
                st = [(x, y)]; seen[y * W + x] = 1
                x0 = x1 = x; y0 = y1 = y; n = 0
                while st:
                    cx, cy = st.pop()
                    if raw[cx, cy]:
                        n += 1
                    x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < W and 0 <= ny < H and px[nx, ny] and not seen[ny * W + nx]:
                            seen[ny * W + nx] = 1; st.append((nx, ny))
                if n >= min_px:
                    boxes.append([x0, y0, x1 - x0 + 1, y1 - y0 + 1, n])
    # 近いかたまりはまとめる
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a_, b_ = boxes[i], boxes[j]
                if (a_[0] - grow < b_[0] + b_[2] and b_[0] - grow < a_[0] + a_[2] and
                        a_[1] - grow < b_[1] + b_[3] and b_[1] - grow < a_[1] + a_[3]):
                    x0, y0 = min(a_[0], b_[0]), min(a_[1], b_[1])
                    x1, y1 = max(a_[0] + a_[2], b_[0] + b_[2]), max(a_[1] + a_[3], b_[1] + b_[3])
                    boxes[i] = [x0, y0, x1 - x0, y1 - y0, a_[4] + b_[4]]
                    del boxes[j]; merged = True; break
            if merged:
                break
    return boxes


def check(a_path, b_path, diff_path):
    a, b = Image.open(a_path), Image.open(b_path)
    if a.size != b.size:
        return False, f"大きさが違う {a.size} {b.size}", []
    listed = json.load(open(diff_path, encoding="utf-8"))["differences"]
    found = clusters(a, b)
    out, used = [], set()
    for L in listed:
        lx, ly = L["x"] + L["width"] / 2, L["y"] + L["height"] / 2
        best = None
        for k, f in enumerate(found):
            if k in used:
                continue
            fx, fy = f[0] + f[2] / 2, f[1] + f[3] / 2
            dist = ((fx - lx) ** 2 + (fy - ly) ** 2) ** 0.5
            if dist < max(150, L["width"], L["height"]) and (best is None or dist < best[0]):
                best = (dist, k)
        if best is None:
            return False, f"一覧の違いが絵に見つからない: {L.get('description')}", found
        used.add(best[1])
        f = found[best[1]]
        out.append({"box": f[:4], "note": L.get("description", "")})
    extra = [f for k, f in enumerate(found) if k not in used]
    if extra:
        return False, f"一覧にない変化が {len(extra)} か所ある: {[e[:4] for e in extra]}", found
    return True, f"OK {len(out)} か所", out


if __name__ == "__main__":
    ok, msg, res = check(*sys.argv[1:4])
    print(msg)
    if ok and len(sys.argv) > 4:
        json.dump({"differences": res}, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(0 if ok else 1)
