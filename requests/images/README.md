# 画像・GIFの依頼書

Claude がここに `<id>.json` を置くと、GitHub Actions の `codex-image` が Codex に画像生成を依頼します。
結果は `assets/generated/<id>/` に保存され、`result.json` が書かれます。

```json
{
  "id": "match011_bg",
  "kind": "image",          // image か gif
  "prompt": "温かい木の机の上に、マッチ棒が並ぶ…",
  "size": "1920x1080",
  "count": 1,               // image の枚数
  "seconds": 3,             // gif の長さの目安
  "notes": "文字は入れない"
}
```

`assets/generated/<id>/result.json` がある依頼は、もう一度実行されません。作り直したいときは、新しい id で依頼します。
