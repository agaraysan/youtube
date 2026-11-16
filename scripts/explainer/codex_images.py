#!/usr/bin/env python3
"""AI解説動画の試作用の画像依頼（requests/explainer_images/*.json）を Codex で描く。
共通の scripts/codex_image.py の仕組みをそのまま使い、依頼の置き場所だけ分ける（他の動画の依頼と順番待ちを取り合わないため）。
2件ずつ並べて描き、1件終わるごとにコミットして push する（途中で止まっても描いた分は残る）。"""
import json, pathlib, subprocess, sys, datetime
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import codex_image as C  # noqa: E402

C.REQ = ROOT / "requests" / "explainer_images"
LOCK = __import__("threading").Lock()


def save(msg):
    with LOCK:
        subprocess.run(["git", "add", "assets/generated"], cwd=ROOT)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
            return
        subprocess.run(["git", "commit", "-qm", msg], cwd=ROOT, check=True)
        for _ in range(5):
            if subprocess.run(["git", "pull", "--rebase", "-q"], cwd=ROOT).returncode == 0 and \
               subprocess.run(["git", "push", "-q"], cwd=ROOT).returncode == 0:
                return
        print("push に失敗", msg)


def one(r):
    out = C.OUT / r["id"]
    out.mkdir(parents=True, exist_ok=True)
    rc = C.run_codex(r, out)
    files = sorted(f.name for f in out.iterdir() if f.suffix.lower() in C.MEDIA)
    status = "ok" if files else "failed"
    (out / "result.json").write_text(json.dumps({"id": r["id"], "status": status, "via": "codex", "codex_returncode": rc, "files": files,
                                                 "at_utc": datetime.datetime.utcnow().isoformat() + "Z"}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(r["id"], status, files, flush=True)
    save(f"explainer: image {r['id']} ({status})")


def main():
    todo = list(C.pending())
    print("pending", len(todo), flush=True)
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, todo))


if __name__ == "__main__":
    main()
