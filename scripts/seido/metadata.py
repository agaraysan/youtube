#!/usr/bin/env python3
"""seido/<id>.json から、投稿用のタイトル・説明文・タグ（.txt）とサムネ（_thumb.png）を作る。
使い方: metadata.py seido/<id>.json 出力フォルダー
章の時刻は render_seido.py が出す <id>.chapters.json（同じ出力フォルダー）を使う。"""
import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render_seido as R  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

YELLOW = (255, 210, 63)


def ts(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def description(ep, chapters):
    lines = []
    first = ep["scenes"][0].get("say", [])
    if first:
        lines.append("".join(R.V.shown(s) for s in first[:3]))
        lines.append("")
    if len(chapters) >= 2:
        lines.append("▼目次")
        lines.append("0:00 はじめに")
        for t, title in chapters:
            lines.append(f"{ts(t)} {title}")
        lines.append("")
    lines.append("▼出典（数字はすべて公的な資料などで確認しています）")
    for s in ep["sources"].values():
        lines.append(f"・{s['label']}")
        lines.append(f"  {s['url']}")
    lines.append("")
    lines.append("このチャンネルでは、AIで世界中の制度を調べてくらべ、日本の制度の穴を指摘していきます。")
    lines.append("特定の人や国を責めるのではなく、制度の作りそのものを問うチャンネルです。")
    lines.append("内容のまちがいに気づいたら、コメントで教えてください。確認して訂正します。")
    lines.append("")
    tags = ep["meta"].get("tags", [])
    lines.append(" ".join("#" + t for t in tags[:3] if t != "shorts"))
    return "\n".join(lines)


def thumb(ep, out):
    W, H = 1280, 720
    im = Image.new("RGBA", (W, H), R.INK + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle((0, H - 16, W, H), fill=R.RED)
    ctx = R.Ctx(im, 99)
    d.ellipse((48, 44, 72, 68), fill=R.RED)
    ctx.text(86, 56, R.CHANNEL, 30, (220, 226, 236), "bold", "lm")
    lines = ep["thumb"]["lines"]
    y = 130
    for i, ln in enumerate(lines):
        size = R.fit(ln, 150 if i == 0 else 128, "black", W - 100, 60)
        sp = R.text_sprite(ln, size, R.WHITE, "black", YELLOW)
        ctx.paste(sp, 50, y)
        y += sp.height + 34
    flags = ep["thumb"].get("flags", [])
    x = W - 50
    for c in reversed(flags):
        x -= R.flag_sprite(c, 72).width
        ctx.flag(c, x, H - 60, 72, "lb")
        x -= 18
    im.convert("RGB").save(out, quality=92)


def main():
    spec = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    ep = json.loads(spec.read_text(encoding="utf-8"))
    chf = outdir / f"{ep['id']}.chapters.json"
    chapters = json.loads(chf.read_text()) if chf.exists() else []
    txt = f"タイトル:\n{ep['meta']['title']}\n\n説明:\n{description(ep, chapters)}\n\nタグ:\n{', '.join(ep['meta'].get('tags', []))}\n"
    (outdir / f"{ep['id']}.txt").write_text(txt, encoding="utf-8")
    if ep.get("thumb"):
        thumb(ep, outdir / f"{ep['id']}_thumb.jpg")
    print("wrote", ep["id"])


if __name__ == "__main__":
    main()
