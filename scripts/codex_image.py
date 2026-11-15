#!/usr/bin/env python3
"""未処理の依頼書を、Codex CLI に1件ずつ渡す。画像はCodexだけで作る（OpenAIのAPIキーは音声専用）。"""
import json, pathlib, subprocess, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQ = ROOT / "requests" / "images"
OUT = ROOT / "assets" / "generated"
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def pending():
    for p in sorted(REQ.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if not (OUT / r["id"] / "result.json").exists():
            yield r


def run_codex(r, out):
    task = (
        f"次の依頼どおりに{'動くGIF' if r.get('kind') == 'gif' else '画像'}を作成し、"
        f"ファイルを {out} に保存してください。ほかのファイルは変更しないでください。\n"
        f"依頼: {json.dumps(r, ensure_ascii=False)}"
    )
    cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", task]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    (out / "codex.log").write_text(p.stdout[-20000:] + "\n--- stderr ---\n" + p.stderr[-20000:], encoding="utf-8")
    return p.returncode


def main():
    done = 0
    for r in pending():
        out = OUT / r["id"]
        out.mkdir(parents=True, exist_ok=True)
        rc = run_codex(r, out)
        files = [f.name for f in out.iterdir() if f.suffix.lower() in MEDIA]
        via = "codex"
        status = "ok" if files else "failed"
        (out / "result.json").write_text(json.dumps({
            "id": r["id"], "status": status, "via": via, "codex_returncode": rc, "files": sorted(files),
            "at_utc": datetime.datetime.utcnow().isoformat() + "Z"}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(r["id"], status, via, files)
        done += 1
    print("processed", done)


if __name__ == "__main__":
    sys.exit(main())
