#!/usr/bin/env python3
"""投稿用の文（<id>.txt）だけを書き直す（動画は作り直さない）。使い方: write_text.py 台本.json 出力フォルダ"""
import json, pathlib, sys
d = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
up = d.get("upload")
if up:
    short = "picture" in d
    extra = "形式：ショート（縦）\n" if short else f"形式：通常の動画（横長）\nサムネイル：{d['id']}_thumb.jpg\n"
    (pathlib.Path(sys.argv[2]) / f"{d['id']}.txt").write_text(
        f"タイトル：\n{up['title']}\n\n説明文：\n{up['description']}\n\nタグ：\n{', '.join(up['tags'])}\n\n{extra}"
        "アップロード時の設定：「改変または合成されたコンテンツ」は「はい」\n", encoding="utf-8")
