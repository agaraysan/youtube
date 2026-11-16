#!/usr/bin/env python3
"""ループ動画（無限ズーム）の音を、YouTube オーディオライブラリの曲（assets/bgm）に差し替える。

曲の一部を動画の長さで切り出し、曲の続き（尾）を頭に重ねてつなぐので、
ショートで繰り返し再生されても音が途切れない。音量は小さめ（既定 -20 LUFS）にそろえる。

使い方: loop_bgm.py 入力.mp4 出力.mp4 曲名 [開始秒] [LUFS]
"""
import json, subprocess, sys, tempfile, pathlib
import numpy as np

SR = 48000
ROOT = pathlib.Path(__file__).resolve().parents[2]


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(p)]).decode())


def decode(p, start, length):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{start}", "-t", f"{length}", "-i", str(p),
                                   "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"])
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def main(src, dst, song, start=20.0, lufs=-20.0):
    T = dur(src)
    X = 3.0  # 重ねる長さ
    mp3 = ROOT / "assets" / "bgm" / f"{song}.mp3"
    a = decode(mp3, start, T + X)
    n, x = int(round(T * SR)), int(X * SR)
    if len(a) < n + x:
        raise SystemExit("曲が短すぎます。開始秒を前にしてください")
    out = a[:n].copy()
    fade = np.linspace(0, 1, x, dtype=np.float32)[:, None]
    out[:x] = a[n:n + x] * (1 - fade) ** 0.5 + a[:x] * fade ** 0.5  # 等パワーで重ねる
    with tempfile.TemporaryDirectory() as td:
        wav = pathlib.Path(td) / "a.f32"
        out.astype(np.float32).tofile(wav)
        # 音量を測ってから一定のゲインで合わせる（loudnorm の動的処理で頭と尾の音量がずれないように）
        meas = subprocess.run(["ffmpeg", "-hide_banner", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(wav),
                               "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True).stderr
        I = float(meas.rsplit("I:", 1)[1].split("LUFS")[0])
        gain = lufs - I
        subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-f", "f32le", "-ar", str(SR), "-ac", "2",
                               "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                               "-af", f"volume={gain:.2f}dB,alimiter=limit=0.7:level=0", "-c:a", "aac", "-b:a", "160k",
                               "-shortest", "-movflags", "+faststart", str(dst)])
    print(json.dumps({"out": str(dst), "seconds": round(T, 1), "song": song, "lufs": lufs, "measured": I}))


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], args[1], args[2], *(float(v) for v in args[3:5]))
