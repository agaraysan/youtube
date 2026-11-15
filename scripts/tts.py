#!/usr/bin/env python3
"""OpenAI Speech API でナレーションを作る。旧運営の設定に合わせる：gpt-4o-mini-tts、声 nova、音量0.5を1回だけ、1.05倍速（音程はそのまま）。
使い方: tts.py 出力.wav "読み上げる文章" [指示]"""
import json, os, subprocess, sys, tempfile, urllib.request


def main(out, text, instructions="落ち着いた、聞き取りやすい自然な日本語で話してください。"):
    body = json.dumps({"model": os.environ.get("TTS_MODEL", "gpt-4o-mini-tts"), "voice": "nova",
                       "input": text, "instructions": instructions, "response_format": "wav"}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", body,
                                 {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                  "Content-Type": "application/json"})
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
        t.write(urllib.request.urlopen(req, timeout=300).read())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", t.name,
                    "-af", "volume=0.5,atempo=1.05", "-ar", "48000", "-ac", "2", out], check=True)
    os.unlink(t.name)


if __name__ == "__main__":
    main(*sys.argv[1:])
