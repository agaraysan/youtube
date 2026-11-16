"""マッチ棒（7セグメント）の数字の定義・パズル探索・描画。"""
from PIL import Image, ImageDraw, ImageFilter
import itertools

SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
       "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}
DIGIT_OF = {frozenset(v): k for k, v in SEG.items()}


def evaluate(expr):
    l, r = expr.split("=")
    try:
        return eval(l) == int(r)
    except Exception:
        return False


def one_move_solutions(expr):
    """数字の棒を1本だけ動かして正しい式になる答えを全部返す（記号は動かさない）。"""
    chars = list(expr)
    pos = [i for i, c in enumerate(chars) if c.isdigit()]
    sols = set()
    for i in pos:
        for s in SEG[chars[i]]:
            src = frozenset(set(SEG[chars[i]]) - {s})
            for j in pos:
                base = src if j == i else frozenset(SEG[chars[j]])
                for t in "abcdefg":
                    if t in base:
                        continue
                    dst = frozenset(set(base) | {t})
                    if j != i and src not in DIGIT_OF:
                        continue
                    if dst not in DIGIT_OF:
                        continue
                    new = chars[:]
                    if j != i:
                        new[i] = DIGIT_OF[src]
                    new[j] = DIGIT_OF[dst]
                    e = "".join(new)
                    if e != expr and evaluate(e):
                        sols.add((e, i, s, j, t))
    return sols


# ---- 描画 ----
WOOD = (236, 214, 170)
HEAD = (196, 40, 30)


def _stick(img, p0, p1, w, head=True, alpha=255):
    """p0→p1 の向きにマッチ棒を1本描く（p1側に頭）。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    off = max(2, w // 3)
    ds.line([(p0[0] + off, p0[1] + off), (p1[0] + off, p1[1] + off)], fill=(0, 0, 0, int(110 * alpha / 255)), width=w)
    sh = sh.filter(ImageFilter.GaussianBlur(w / 2))
    img.alpha_composite(sh)
    d.line([p0, p1], fill=WOOD + (alpha,), width=w)
    d.line([p0, p1], fill=(255, 240, 205, int(alpha * .5)), width=max(1, w // 4))
    if head:
        r = int(w * 0.9)
        d.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=HEAD + (alpha,))
    img.alpha_composite(layer)


def seg_coords(s, x, y, W, H):
    g = W * 0.08
    pts = {"a": ((x + g, y), (x + W - g, y)), "d": ((x + g, y + H), (x + W - g, y + H)),
           "g": ((x + g, y + H / 2), (x + W - g, y + H / 2)),
           "f": ((x, y + H / 2 - g), (x, y + g)), "b": ((x + W, y + H / 2 - g), (x + W, y + g)),
           "e": ((x, y + H - g), (x, y + H / 2 + g)), "c": ((x + W, y + H - g), (x + W, y + H / 2 + g))}
    return pts[s]


def draw_expr(img, expr, cx, cy, H=300, hide=None, ghost=None, highlight=None):
    """式を中央 (cx,cy) に描く。hide=(位置,棒) は描かない棒、ghost=(位置,棒) は薄く描く棒。"""
    def layout(H):
        W = H * 0.55
        gap = H * 0.28
        widths = [W if c.isdigit() else W * 0.8 for c in expr]
        gaps = [gap * (0.55 if expr[k].isdigit() and expr[k + 1].isdigit() else 1) for k in range(len(expr) - 1)]
        return W, gap, widths, gaps, sum(widths) + sum(gaps)
    W, gap, widths, gaps, total = layout(H)
    max_total = img.width * 0.86
    if total > max_total:  # 長い式は画面に収まるよう小さくする
        H = H * max_total / total
        W, gap, widths, gaps, total = layout(H)
    w = max(6, int(H * 0.05))
    x = cx - total / 2
    y = cy - H / 2
    for i, c in enumerate(expr):
        cw = widths[i]
        if c.isdigit():
            for s in SEG[c]:
                if hide and (i, s) == hide:
                    continue
                a = 90 if ghost and (i, s) == ghost else 255
                p0, p1 = seg_coords(s, x, y, W, H)
                _stick(img, p0, p1, w, alpha=a)
            if ghost and ghost[0] == i and ghost[1] not in SEG[c]:
                p0, p1 = seg_coords(ghost[1], x, y, W, H)
                _stick(img, p0, p1, w, alpha=90)
            if highlight and highlight[0] == i:
                p0, p1 = seg_coords(highlight[1], x, y, W, H)
                d = ImageDraw.Draw(img)
                mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                R = H * 0.28
                d.ellipse([mx - R, my - R, mx + R, my + R], outline=(255, 210, 0, 255), width=max(6, w // 1))
        else:
            m = cy
            L = cw * 0.9
            if c in "+-":
                _stick(img, (x + cw / 2 - L / 2, m), (x + cw / 2 + L / 2, m), w)
                if c == "+":
                    _stick(img, (x + cw / 2, m + L / 2), (x + cw / 2, m - L / 2), w)
            elif c == "=":
                _stick(img, (x + cw / 2 - L / 2, m - H * 0.12), (x + cw / 2 + L / 2, m - H * 0.12), w)
                _stick(img, (x + cw / 2 - L / 2, m + H * 0.12), (x + cw / 2 + L / 2, m + H * 0.12), w)
        x += cw + (gaps[i] if i < len(gaps) else 0)


if __name__ == "__main__":
    good = []
    for a, op, b in itertools.product("0123456789", "+-", "0123456789"):
        for c in "0123456789":
            e = f"{a}{op}{b}={c}"
            if evaluate(e):
                continue
            s = one_move_solutions(e)
            if len(s) == 1:
                good.append((e, s))
    print(len(good))
    for g in good[:40]:
        print(g)
