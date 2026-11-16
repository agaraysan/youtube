#!/usr/bin/env python3
"""著作権の心配がない自作BGMを、その場で合成する（numpy だけ使う）。

使い方: bgm.py out.wav 秒数 [style]
style: match（明るい・やや速い）/ riddle（やさしい）/ spot（軽快）
エレピのアルペジオ、やわらかいパッド、ベース、小さなシェイカーでできた、ループする曲。
"""
import sys, wave
import numpy as np

SR = 48000
STYLES = {
    # bpm, 主音(MIDI), 和音進行(主音からの半音と種類)
    "match": (104, 60, [(0, "maj7"), (9, "m7"), (5, "maj7"), (7, "dom7")]),
    "riddle": (88, 62, [(0, "maj7"), (4, "m7"), (9, "m7"), (5, "maj7"), (2, "m7"), (7, "dom7"), (0, "maj7"), (7, "dom7")]),
    "spot": (112, 65, [(0, "maj7"), (5, "maj7"), (9, "m7"), (7, "dom7")]),
}
CHORD = {"maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "dom7": [0, 4, 7, 10]}


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def note(freq, dur, kind):
    t = np.arange(int(dur * SR)) / SR
    if kind == "ep":  # エレピ風：倍音を少し足した正弦波、減衰
        w = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-6 * t) + 0.08 * np.sin(2 * np.pi * 3 * freq * t)
        env = np.exp(-3.2 * t) * np.minimum(1, t * 400)
    elif kind == "pad":
        w = sum(np.sin(2 * np.pi * freq * (1 + d) * t) for d in (-0.003, 0, 0.003)) / 3
        env = np.minimum(1, t / 0.6) * np.minimum(1, (dur - t) / 0.6).clip(0)
    elif kind == "bass":
        w = np.sin(2 * np.pi * freq * t) + 0.2 * np.sin(2 * np.pi * 2 * freq * t)
        env = np.exp(-2.5 * t) * np.minimum(1, t * 300)
    return w * env


def shaker(dur, rng):
    n = int(dur * SR)
    x = rng.standard_normal(n)
    x = np.diff(x, prepend=0)  # 高い音だけ残す
    t = np.arange(n) / SR
    return x * np.exp(-60 * t) * 0.5


def place(buf, sig, start, gain, pan=0.0):
    i = int(start * SR)
    j = min(len(buf), i + len(sig))
    if i >= len(buf):
        return
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:j, 0] += sig[: j - i] * gain * l
    buf[i:j, 1] += sig[: j - i] * gain * r


def make(seconds, style="match", seed=1):
    bpm, root, prog = STYLES.get(style, STYLES["match"])
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bar = beat * 4
    total = seconds + 2
    buf = np.zeros((int(total * SR), 2))
    k, t0 = 0, 0.0
    arp = [0, 1, 2, 3, 2, 1, 2, 3]
    while t0 < total:
        off, q = prog[k % len(prog)]
        tones = [root + off + i for i in CHORD[q]]
        for m in tones[:3]:
            place(buf, note(hz(m), bar, "pad"), t0, 0.05, pan=rng.uniform(-0.4, 0.4))
        for s in range(8):  # 8分音符のアルペジオ
            m = tones[arp[s]] + 12
            if rng.random() < 0.85:
                place(buf, note(hz(m), beat * 1.5, "ep"), t0 + s * beat / 2, 0.11, pan=0.35 if s % 2 else -0.35)
        for b in range(4):
            place(buf, note(hz(root + off - 24 + (7 if b == 2 else 0)), beat, "bass"), t0 + b * beat, 0.22)
            for h in (0.5,):
                place(buf, shaker(0.08, rng), t0 + (b + h) * beat, 0.05, pan=0.5)
        k += 1
        t0 += bar
    # 簡単な残響
    out = buf.copy()
    for d, g in ((0.031, 0.35), (0.047, 0.28), (0.071, 0.2), (0.113, 0.14)):
        n = int(d * SR)
        out[n:] += buf[:-n] * g
    out = out[: int(seconds * SR)]
    fade = int(min(2.0, seconds / 4) * SR)
    out[:int(0.3 * SR)] *= np.linspace(0, 1, int(0.3 * SR))[:, None]
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    out /= max(1e-9, np.abs(out).max()) / 0.8
    return out


def save(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((data * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    save(sys.argv[1], make(float(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "match"))
