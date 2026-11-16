#!/usr/bin/env python3
"""頭の体操シリーズを「動きのある」動画にする（30コマ/秒で1コマずつ描く）。

render.py の書き出し（止まった画像を秒数どおりにつなぐ）との違い
  - 場面の切り替えは 0.3 秒のクロスフェード（パッと変わらない）
  - 考える時間のタイマーと残り時間のバーは、なめらかに減る
  - 表紙はゆっくり寄っていく
  - 答えの場面は、少しだけ拡大してから戻る（ポンと出る感じ）
音（声・効果音・BGM）の作り方は render.py と同じ。
"""
import math, pathlib, subprocess, sys, tempfile
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "render"))
sys.path.insert(0, str(ROOT / "scripts" / "brain"))
import render as R  # noqa: E402
import brain as B  # noqa: E402

FPS = 30
FADE = 9  # クロスフェードのコマ数（0.3秒）


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def zoomed(im, scale):
    """中央を基準に scale 倍に拡大した画像（同じ大きさ）。"""
    if abs(scale - 1) < 1e-3:
        return im
    W, H = im.size
    cw, ch = W / scale, H / scale
    return im.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2))


def scene_frames(kind, r, length, ep):
    """1場面ぶんのコマを順に返す（ジェネレーター）。"""
    nf = max(1, int(round(length * FPS)))
    if isinstance(r, B.ThinkFrames):
        base = B.timer_shadow(r.base.copy())
        n = r.n
        for i in range(nf):
            remain = n * (1 - i / nf)
            yield B.draw_timer(base.copy(), ep, remain, n, shadow=False).convert("RGB")
        return
    im = r if r.mode == "RGB" else r.convert("RGB")
    if kind == "title":  # ゆっくり寄る
        for i in range(nf):
            yield zoomed(im, 1.0 + 0.035 * i / nf)
        return
    if kind == "reveal":  # 答え：少し大きく出て、すっと戻る
        for i in range(nf):
            t = i / FPS
            s = 1.0 + 0.025 * max(0.0, 1 - t / 0.35) if t < 0.35 else 1.0
            yield zoomed(im, s) if s > 1.0005 else im
        return
    for _ in range(nf):
        yield im


def render(ep, out_dir, no_voice=False):
    size = tuple(ep.get("size", [1920, 1080]))
    W, H = size
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp())
    tick, chime = str(tmp / "tick.wav"), str(tmp / "chime.wav")
    R.tone(tick, "tick"); R.tone(chime, "chime")

    # 1) 声と長さを先に決める
    plan, voice_parts, sfx_parts, t = [], [], [], 0.0
    for n, sc in enumerate(ep["scenes"]):
        voice_len = 0
        if sc.get("voice"):
            vp = str(tmp / f"v{n:02d}.wav")
            if no_voice:
                R.silence(max(1.5, len(sc["voice"]) * 0.14), vp)
            else:
                R.tts(sc["voice"], vp)
            voice_len = R.dur(vp)
            voice_parts.append((t + sc.get("voice_delay", 0.4), vp))
        r = R.render_scene(sc, ep, size)
        if isinstance(r, B.ThinkFrames):
            length = float(r.n)
            for k in range(r.n):
                sfx_parts.append((t + k, tick))
        elif isinstance(r, list):  # render.py の古い形（1秒ごとの画像）
            length = float(len(r))
            r = r[0]
        else:
            length = sc.get("seconds", voice_len + sc.get("voice_delay", 0.4) + sc.get("pad", 0.8))
            length = max(length, sc.get("min_seconds", 0))
        if sc.get("chime"):
            sfx_parts.append((t, chime))
        kind = "title" if sc["type"] == "title" and not sc.get("end") else ("reveal" if sc.get("reveal") or sc.get("chime") else "plain")
        plan.append((kind, r, length))
        t += length

    # 2) 映像：1コマずつ ffmpeg に流しこむ。場面の頭は前の場面の最後のコマから溶けるように変わる
    video = tmp / "video.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", str(video)],
                          stdin=subprocess.PIPE)
    prev, sheet = None, []
    total_frames = int(round(t * FPS))
    written = 0
    for idx, (kind, r, length) in enumerate(plan):
        nf = max(1, int(round(length * FPS)))
        if idx == len(plan) - 1:
            nf = max(1, total_frames - written)
        for i, fr in enumerate(scene_frames(kind, r, nf / FPS, ep)):
            if i == 0:
                sheet.append(fr)
            if prev is not None and i < FADE:
                fr = Image.blend(prev, fr, ease((i + 1) / (FADE + 1)))
            ff.stdin.write(fr.tobytes())
            written += 1
            last = fr
        prev = last
    if idx >= 0 and kind != "title":  # 最後は少し暗くして終わる
        pass
    ff.stdin.close()
    ff.wait()

    # 3) 音：render.py と同じ（声＋効果音＋BGM、声の間はBGMを下げる）
    def mixdown(parts, out):
        inputs, filt = [], []
        for k, (start, path) in enumerate(parts):
            inputs += ["-i", path]
            ms = int(start * 1000)
            filt.append(f"[{k}:a]aresample={R.SR},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
        mix = "".join(f"[a{k}]" for k in range(len(parts)))
        filt.append(f"{mix}amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{t:.3f}[o]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[o]", "-ar", str(R.SR), out], check=True)

    voice, sfx = str(tmp / "voice.wav"), str(tmp / "sfx.wav")
    mixdown(voice_parts, voice) if voice_parts else R.silence(t, voice)
    mixdown(sfx_parts, sfx) if sfx_parts else R.silence(t, sfx)
    audio = tmp / "audio.wav"
    music = str(tmp / "bgm.wav")
    R.BGM.save(music, R.BGM.make(t, ep.get("style", "match"), seed=sum(map(ord, ep["id"]))))
    vol = ep.get("bgm_volume", 0.16)
    fc = (f"[1:a]volume={vol}[m];[0:a]asplit=2[v1][v2];"
          f"[m][v2]sidechaincompress=threshold=0.02:ratio=5:attack=20:release=450[md];"
          f"[v1][md][2:a]amix=inputs=3:normalize=0[o]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-i", music, "-i", sfx, "-filter_complex", fc,
                    "-map", "[o]", "-ar", str(R.SR), str(audio)], check=True)
    out = out_dir / f"{ep['id']}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", f"loudnorm=I={B.LOUDNESS}:TP=-2:LRA=11", "-ar", str(R.SR), "-movflags", "+faststart", "-shortest", str(out)], check=True)
    # 確認用の一覧画像（場面ごとの最初のコマ、12枚まで）
    th = [s.resize((480, int(480 * H / W))) for s in sheet[:12]]
    S = Image.new("RGB", (480 * 3, th[0].height * math.ceil(len(th) / 3)))
    for k, s in enumerate(th):
        S.paste(s, ((k % 3) * 480, (k // 3) * s.height))
    S.save(out_dir / f"{ep['id']}_sheet.jpg", quality=85)
    print(out, f"{t:.1f}s")
