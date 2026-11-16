"""AI映像の試作で共通に使う道具（Codex への画像依頼、字幕、動画の書き出し、画像の取得）。"""
import json, pathlib, subprocess, urllib.request, urllib.parse
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
OW, OH, FPS = 1080, 1920, 30
FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]


def font(size):
    for f in FONTS:
        if pathlib.Path(f).exists():
            return ImageFont.truetype(f, int(size))
    return ImageFont.load_default()


def codex(task, log):
    cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", task]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1500)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "timeout", -1
    with open(log, "a", encoding="utf-8") as f:
        f.write(out[-6000:] + "\n--- stderr ---\n" + err[-3000:] + "\n=====\n")
    return rc


def find(stem):
    stem = pathlib.Path(stem)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if stem.with_suffix(ext).exists():
            return stem.with_suffix(ext)
    return None


def gen_image(prompt, stem, size, log, style="", tries=2):
    """新しく1枚描いてもらう。stem.png に保存。"""
    W, H = size
    task = (f"内蔵の画像生成機能で、{'縦長' if H > W else '横長' if W > H else '正方形'} {W}x{H} の画像を1枚作ってください。"
            f"内容: {prompt}\n画風: {style}\n画像の中に文字・ロゴ・透かしは入れないでください。\n"
            f"できた画像を {stem}.png に保存してください。ほかのファイルは変更しないでください。")
    for _ in range(tries):
        codex(task, log)
        if find(stem):
            return find(stem)
    return None


def edit_image(src, instruction, stem, size, log, style="", tries=2):
    """src の絵を元に、構図を保ったまま描き変えてもらう。"""
    W, H = size
    task = (f"画像 {src} を開いて見てください。内蔵の画像生成機能でこの画像を編集してください。\n"
            f"変更内容: {instruction}\n構図・カメラの位置・建物や地形の配置は元の画像と同じに保ってください。画風: {style}\n"
            f"画像の中に文字・ロゴ・透かしは入れないでください。{W}x{H} で {stem}.png に保存してください。ほかのファイルは変更しないでください。")
    for _ in range(tries):
        codex(task, log)
        if find(stem):
            return find(stem)
    return None


def fetch(url, dst):
    """パブリックドメインの名画などを取得する（GitHub Actions 上で使う）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "art-prototype/0.1 (video research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        pathlib.Path(dst).write_bytes(r.read())
    return dst


def commons(file_name, width=2000):
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(file_name) + f"?width={width}"


def cover(img, w, h):
    """img を w x h いっぱいに切り抜いて合わせる。"""
    s = max(w / img.width, h / img.height)
    im = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def feather_mask(w, h, f):
    m = Image.new("L", (w, h), 0)
    m.paste(255, (f, f, w - f, h - f))
    return m.filter(ImageFilter.GaussianBlur(f / 2))


def caption_layer(text, sub=None, y=260):
    """上部に出す字幕（RGBA、画面サイズ）。白い太字に影。"""
    im = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lines = text.split("\n")
    f = font(78 if max(len(l) for l in lines) <= 11 else 64)
    yy = y
    for line in lines:
        w = d.textlength(line, font=f)
        for dx, dy in ((0, 5), (3, 3)):
            d.text(((OW - w) / 2 + dx, yy + dy), line, font=f, fill=(0, 0, 0, 160))
        d.text(((OW - w) / 2, yy), line, font=f, fill=(255, 255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0, 200))
        yy += f.size * 1.3
    if sub:
        fs = font(44)
        w = d.textlength(sub, font=fs)
        d.text(((OW - w) / 2, yy + 10), sub, font=fs, fill=(255, 255, 255, 235), stroke_width=3, stroke_fill=(0, 0, 0, 200))
    im = im.filter(ImageFilter.GaussianBlur(0.4))
    return np.asarray(im, dtype=np.float32)


def over(frame, layer, alpha=1.0):
    if layer is None or alpha <= 0:
        return frame
    a = layer[..., 3:4] / 255 * alpha
    return frame * (1 - a) + layer[..., :3] * a


class Grade:
    """プロの映像らしい仕上げ。色を少し抑えてそろえ、明るすぎる所をなだらかにし、
    四隅をわずかに暗くし、細かいフィルムの粒子を足す（AIっぽいギラつきを抑える）。"""

    def __init__(self, sat=0.86, warm=0.03, vignette=0.22, grain=2.0, seed=0):
        yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
        r = np.sqrt(((xx - OW / 2) / (OW / 2)) ** 2 * 0.8 + ((yy - OH / 2) / (OH / 2)) ** 2 * 0.6)
        self.vig = (1 - vignette * np.clip(r - 0.35, 0, None) ** 1.6)[..., None].astype(np.float32)
        self.sat, self.warm, self.grain = sat, warm, grain
        self.rng = np.random.default_rng(seed)
        self.noise = [np.repeat(np.repeat(self.rng.standard_normal((OH // 2, OW // 2, 1)).astype(np.float32), 2, 0), 2, 1)
                      for _ in range(8)]

    def __call__(self, frame, i=0):
        x = frame / 255.0
        lum = x @ np.array([0.299, 0.587, 0.114], np.float32)
        x = lum[..., None] + (x - lum[..., None]) * self.sat
        x = x / (1 + 0.35 * np.clip(x - 0.7, 0, None))  # 明るい所をなだらかに（光りすぎを抑える）
        x = x * 0.97 + 0.015  # 黒を少しだけ持ち上げる（フィルムらしいやわらかさ）
        x[..., 0] *= 1 + self.warm
        x[..., 2] *= 1 - self.warm
        x = x * self.vig
        x = x * 255 + self.noise[i % len(self.noise)] * self.grain
        return x


class Writer:
    def __init__(self, out_mp4, audio_wav, grade=True):
        self.grade = Grade() if grade else None
        self.i = 0
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
                                   "-r", str(FPS), "-i", "-", "-i", str(audio_wav), "-c:v", "libx264", "-preset", "medium",
                                   "-crf", "20", "-maxrate", "9M", "-bufsize", "18M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
                                   "-movflags", "+faststart", str(out_mp4)], stdin=subprocess.PIPE)

    def write(self, frame):
        if self.grade is not None:
            frame = self.grade(frame, self.i)
        self.i += 1
        self.p.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def load_spec(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
