# Codex へのお願い（このリポジトリでの役割）

このリポジトリの運営は Claude が行います。Codex の担当は **画像と動くGIFの作成だけ** です。

- 依頼は `requests/images/<id>.json` にあります。Issue やタスクで id を指定されたら、その依頼書を読んでください。
- **画像は Codex 自身の画像生成機能で作ってください。** `scripts/codex_image.py` は GitHub Actions 用なので、実行しないでください（Codex の中から Codex CLI を呼ぶ必要はありません）。
- 出来上がったファイルは `assets/generated/<id>/` に保存してください。画像は PNG、動くGIFは GIF で保存します。
  - あわせて `result.json` を書いてください（`{"id","status":"ok","via":"codex-cloud","files":[...]}`）。
- **保存が終わったら、必ず GitHub に送ってください。** 送り先は `codex-inbox` 枝です。
  ```bash
  # origin がなければ、環境変数 GH_PUSH_TOKEN を使って自分で追加する
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://x-access-token:${GH_PUSH_TOKEN}@github.com/agaraysan/youtube.git"
  git fetch origin codex-inbox && git rebase origin/codex-inbox   # 失敗したら git pull --rebase origin codex-inbox
  git push origin HEAD:codex-inbox
  ```
  push できなかったら、`GH_PUSH_TOKEN` が空かどうか（値は表示しない）と、、その理由を最後の報告に書いてください。
- 音声（OpenAI Speech API）や投稿は Claude と GitHub Actions が担当します。OpenAI の APIキーは不要です。
- 依頼された id のフォルダー以外は変更しないでください。
- 画像の中に、依頼にない文字やロゴを入れないでください。
