#!/usr/bin/env python3
"""AI映像の試作を1本作る。素材の生成（Codex など）→ 動画の書き出し。

使い方: run.py art/<id>.json out_dir [--render-only]
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import load_spec


def main(spec_path, out_dir, *flags):
    spec = load_spec(spec_path)
    out = pathlib.Path(out_dir) / f"{spec['id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    t = spec["type"]
    if t == "zoom":
        import zoom_chain, zoom_render
        if "--render-only" not in flags and zoom_chain.main(spec_path):
            return 1
        zoom_render.main(spec_path, str(out))
    else:
        mod = __import__({"morph": "morph", "slides": "slides", "parallax": "parallax"}[t])
        if "--render-only" not in flags and mod.generate(spec):
            return 1
        mod.render(spec, str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
