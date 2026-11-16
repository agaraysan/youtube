#!/usr/bin/env python3
"""explainer/<id>.json の各場面の voice を nova で読み上げ、explainer/voice/<id>/<hash>.m4a に保存する。
同じ文章はもう作らない（文章のハッシュで判断）。GitHub Actions の explainer-voice で動かす。"""
import hashlib, json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import tts  # noqa: E402


def key(text):
    return hashlib.sha1(("nova|0.5|1.05|" + text).encode()).hexdigest()[:12]


def main():
    made = 0
    for spec in sorted((ROOT / "explainer").glob("*.json")):
        ep = json.loads(spec.read_text(encoding="utf-8"))
        out = ROOT / "explainer" / "voice" / ep["id"]
        out.mkdir(parents=True, exist_ok=True)
        for sc in ep["scenes"]:
            if not sc.get("voice"):
                continue
            dst = out / f"{key(sc['voice'])}.m4a"
            if dst.exists():
                continue
            with tempfile.TemporaryDirectory() as t:
                wav = f"{t}/v.wav"
                tts.main(wav, sc["voice"], ep.get("voice_instructions", "明るく親しみやすい、聞き取りやすい自然な日本語で、YouTubeの解説動画のように話してください。"))
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "aac", "-b:a", "192k", str(dst)], check=True)
            print("made", dst.name, sc["voice"][:20])
            made += 1
    print("made", made)


if __name__ == "__main__":
    main()
