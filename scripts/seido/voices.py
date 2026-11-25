#!/usr/bin/env python3
"""seido/<id>.json の読み上げを OpenAI Speech API で作り、seido/voice/<id>/<hash>.m4a に保存する。
1文ごとに1つの音声を作る（字幕とぴったり合わせるため）。同じ文・同じ声はもう作らない（ハッシュで判断）。
GitHub Actions の seido-voice で動かす。"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_INSTR = ("落ち着いたニュース解説のアナウンサーのように、はっきり聞き取りやすい自然な日本語で話してください。"
                 "あおらず、やさしく、数字はゆっくり正確に読んでください。")


def key(text, voice, instr):
    return hashlib.sha1(f"{voice}|0.5|1.05|{instr}|{text}".encode()).hexdigest()[:12]


def clips(ep):
    """この動画で読む (文章, 声, 指示) をすべて返す。render_seido.py と同じ規則。"""
    voice = ep.get("voice", "nova")
    instr = ep.get("voice_instructions", DEFAULT_INSTR)
    for sc in ep["scenes"]:
        for s in sc.get("say", []):
            yield spoken(s), voice, instr


def spoken(s):
    """字幕と読みが違うときは「字幕|読み」と書く。読みの方を返す。"""
    return s.split("|", 1)[1] if "|" in s else s


def shown(s):
    return s.split("|", 1)[0]


def speak(text, voice, instr, dst):
    body = json.dumps({"model": os.environ.get("TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text,
                       "instructions": instr, "response_format": "wav"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", body,
                                 {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
    with tempfile.TemporaryDirectory() as t:
        raw = f"{t}/raw.wav"
        for i in range(4):
            try:
                open(raw, "wb").write(urllib.request.urlopen(req, timeout=300).read())
                break
            except Exception as e:  # 一時的な失敗はやり直す
                print("retry", i, e)
                if i == 3:
                    raise
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,volume=0.5,atempo=1.05",
                        "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(dst)], check=True)
    print("made", dst.name, text[:24])


def main():
    jobs = []
    for spec in sorted((ROOT / "seido").glob("*.json")):
        ep = json.loads(spec.read_text(encoding="utf-8"))
        out = ROOT / "seido" / "voice" / ep["id"]
        out.mkdir(parents=True, exist_ok=True)
        for text, voice, instr in clips(ep):
            dst = out / f"{key(text, voice, instr)}.m4a"
            if not dst.exists() and dst not in [j[3] for j in jobs]:
                jobs.append((text, voice, instr, dst))
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda j: speak(*j), jobs))
    print("made", len(jobs))


if __name__ == "__main__":
    main()
