#!/usr/bin/env python3
"""explainer/<id>.json から、手動アップロード用のタイトル・説明文・タグのテキストを作る。
使い方: metadata.py explainer/<id>.json 出力.txt"""
import json, sys

ep = json.load(open(sys.argv[1], encoding="utf-8"))
m = ep.get("meta", {})
title = m.get("title", ep["title"])
vertical = ep.get("size", [1920, 1080])[1] > ep.get("size", [1920, 1080])[0]
first = ep["scenes"][0].get("voice") or " ".join(l["text"] for l in ep["scenes"][0].get("lines", []))
points = [s["telop"].replace("\n", "") for s in ep["scenes"][1:-1] if s.get("telop") and "正解" not in s["telop"] and not s.get("choices")]
tags = m.get("tags", [])
desc = [first, ""]
if points and not vertical:
    desc += ["【この動画の内容】"] + [f"・{p}" for p in points] + [""]
if any(s.get("rank") for s in ep["scenes"]):
    desc += ["※ランキングは編集部の独断です。", ""]
if "心理テスト" in title:
    desc += ["※お遊びの心理テストです。", ""]
desc += ["画像はAIで作成しています。BGM：YouTube オーディオライブラリ", ""]
desc += [" ".join("#" + t for t in tags[:5])]
out = [f"タイトル：\n{title}\n", "説明文：\n" + "\n".join(desc) + "\n", "タグ：\n" + ", ".join(tags) + "\n",
       "形式：" + ("ショート（縦長）" if vertical else "通常の動画（横長）"),
       "アップロード時の設定：「改変または合成されたコンテンツ」は「はい」（写実的なAI画像を使っているため）"]
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(out) + "\n")
