#!/usr/bin/env python3
"""explainer/<id>.json の声を OpenAI Speech API で作り、explainer/voice/<id>/<hash>.m4a に保存する。
設定は scripts/tts.py と同じ（gpt-4o-mini-tts、音量0.5、1.05倍速）。声の種類は場面ごと・話し手ごとに変えられる。
同じ文章・同じ声はもう作らない（ハッシュで判断）。GitHub Actions の explainer-voice で動かす。"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_INSTR = "明るく親しみやすい、聞き取りやすい自然な日本語で、YouTubeの解説動画のように話してください。"


def key(text, voice="nova", instr=None):
    return hashlib.sha1((f"{voice}|0.5|1.05|" + (instr + "|" if instr else "") + text).encode()).hexdigest()[:12]


def clips(ep):
    """この動画で読む (文章, 声, 指示) をすべて返す。render_explainer.py と同じ規則。"""
    cast = ep.get("cast", {})
    base_instr = ep.get("voice_instructions")
    for sc in ep["scenes"]:
        for ln in sc.get("lines") or ([{"text": sc["voice"]}] if sc.get("voice") else []):
            who = cast.get(ln.get("who"), {})
            yield ln["text"], who.get("voice", ep.get("voice", "nova")), who.get("instructions", base_instr)


def speak(text, voice, instr, dst):
    body = json.dumps({"model": os.environ.get("TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text,
                       "instructions": instr or DEFAULT_INSTR, "response_format": "wav"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", body,
                                 {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
    with tempfile.TemporaryDirectory() as t:
        raw = f"{t}/raw.wav"
        open(raw, "wb").write(urllib.request.urlopen(req, timeout=300).read())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af", "volume=0.5,atempo=1.05", "-ar", "48000", "-ac", "2",
                        "-c:a", "aac", "-b:a", "192k", str(dst)], check=True)
    print("made", dst.name, voice, text[:20])


def main():
    jobs = []
    for spec in sorted((ROOT / "explainer").glob("*.json")):
        ep = json.loads(spec.read_text(encoding="utf-8"))
        out = ROOT / "explainer" / "voice" / ep["id"]
        out.mkdir(parents=True, exist_ok=True)
        for text, voice, instr in clips(ep):
            dst = out / f"{key(text, voice, instr)}.m4a"
            if not dst.exists():
                jobs.append((text, voice, instr, dst))
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda j: speak(*j), jobs))
    print("made", len(jobs))


if __name__ == "__main__":
    main()
