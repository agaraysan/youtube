#!/usr/bin/env python3
"""映像作品用の、ゆったりした自作アンビエントBGM（numpy だけで合成）。著作権の心配がない。
使い方: ambient.py out.wav 秒数 [mood]   mood: dream（幻想）/ calm（落ち着き）/ epic（壮大）
"""
import sys, wave
import numpy as np

SR = 48000
MOODS = {
    "dream": (50, [(0, [0, 7, 11, 14]), (-4, [0, 7, 10, 14]), (-7, [0, 7, 11, 16]), (-2, [0, 5, 9, 14])]),
    "calm": (55, [(0, [0, 4, 7, 11]), (5, [0, 4, 7, 14]), (-3, [0, 3, 7, 10]), (2, [0, 3, 7, 10])]),
    "epic": (45, [(0, [0, 7, 12, 15]), (-4, [0, 7, 12, 16]), (3, [0, 7, 12, 16]), (-2, [0, 7, 12, 14])]),
}


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def pad(freq, dur, rng):
    t = np.arange(int(dur * SR)) / SR
    w = np.zeros_like(t)
    for dt in (-0.004, -0.0015, 0.0015, 0.004):
        ph = rng.uniform(0, 6.28)
        w += np.sin(2 * np.pi * freq * (1 + dt) * t + ph) + 0.3 * np.sin(2 * np.pi * 2 * freq * (1 + dt) * t + ph)
    att = min(2.5, dur / 3)
    env = np.minimum(1, t / att) * np.clip((dur - t) / att, 0, 1)
    return w * env / 4


def bell(freq, dur):
    t = np.arange(int(dur * SR)) / SR
    return (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-3 * t)) * np.exp(-1.6 * t) * np.minimum(1, t * 200)


def add(buf, sig, start, gain, pan=0.0):
    i = int(start * SR); j = min(len(buf), i + len(sig))
    if i >= len(buf): return
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:j, 0] += sig[: j - i] * gain * l
    buf[i:j, 1] += sig[: j - i] * gain * r


def make(seconds, mood="dream", seed=1):
    root, prog = MOODS.get(mood, MOODS["dream"])
    rng = np.random.default_rng(seed)
    chord = 6.0
    buf = np.zeros((int((seconds + chord) * SR), 2))
    t0, k = 0.0, 0
    while t0 < seconds:
        off, iv = prog[k % len(prog)]
        for m in iv:
            add(buf, pad(hz(root + off + m), chord + 2.5, rng), t0, 0.12, rng.uniform(-0.5, 0.5))
        add(buf, pad(hz(root + off - 12), chord + 2.5, rng), t0, 0.16)
        for b in range(4):  # きらきらした高い音
            if rng.random() < 0.8:
                m = root + off + 24 + int(rng.choice(iv))
                add(buf, bell(hz(m), 3.0), t0 + b * chord / 4 + rng.uniform(0, 0.3), 0.05, rng.uniform(-0.7, 0.7))
        t0 += chord; k += 1
    out = buf.copy()
    for d, g in ((0.043, 0.5), (0.089, 0.4), (0.137, 0.3), (0.211, 0.25), (0.331, 0.18), (0.479, 0.12)):
        n = int(d * SR); out[n:] += buf[:-n] * g
    out = out[: int(seconds * SR)]
    f = int(min(1.5, seconds / 5) * SR)
    out[: int(0.8 * SR)] *= np.linspace(0, 1, int(0.8 * SR))[:, None]
    out[-f:] *= np.linspace(1, 0, f)[:, None]
    return out / (np.abs(out).max() + 1e-9) * 0.3  # 小さめ（ショートは音が大きいと飛ばされる）。約 -22 LUFS


def make_loop(seconds, mood="dream", seed=1, xf=3.0):
    """最後と最初がつながるBGM。少し長めに作り、はみ出した終わりを頭に重ねる。"""
    a = make(seconds + xf + 1.0, mood, seed)
    n, k = int(seconds * SR), int(xf * SR)
    body = a[:n].copy()
    tail = a[n:n + k]
    ramp = np.linspace(0, 1, k)[:, None]
    body[:k] = body[:k] * ramp + tail * (1 - ramp)
    return body / (np.abs(body).max() + 1e-9) * 0.3  # 小さめ（ショートは音が大きいと飛ばされる）。約 -22 LUFS


def save(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((data * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    save(sys.argv[1], make(float(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "dream"))
