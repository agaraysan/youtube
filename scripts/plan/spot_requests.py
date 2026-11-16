#!/usr/bin/env python3
"""間違い探しの依頼書（requests/images/<id>.json）をまとめて作る。

使い方: spot_requests.py <シリーズid> <絵柄 anime|photo> <場面1> <場面2> ...
各場面について、正方形の2枚組（a.png / b.png）と differences.json（違い5か所）を Codex に頼む。
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STYLE = {
    "anime": "やわらかく明るいアニメ調のイラスト（細部まで描きこむ）",
    "photo": "本物の写真のようなフォトリアルな画像（自然な光、高精細、実在の人物や商標は使わない）",
}
TYPES = ("違いの種類は混ぜる：①ある物が消えている ②物の数が変わっている ③物の形が変わっている ④別の物に入れ替わっている "
         "⑤大きさが変わっている ⑥向きや位置が少し変わっている ⑦服や物の模様が変わっている。色だけを変える違いは多くても1か所まで。")


def request(rid, style, scene, n=5):
    return {
        "id": rid, "kind": "image", "pair": True, "size": "1024x1024", "count": 1,
        "prompt": (
            f"間違い探し用の絵を2枚作ってください。1枚目 a.png：正方形（1024x1024）。{STYLE[style]}。場面：{scene}。"
            "人物や小物をたくさん（30個以上の物が見えるように）入れて、見るところが多いにぎやかな絵にする。文字やロゴは入れない。"
            f"2枚目 b.png：a.png をそのまま元にして、違いを{n}か所だけ入れる。違い以外は a.png と完全に同じにする（構図・色・人物・位置・明るさを変えない）。"
            f"{TYPES}簡単すぎないように、すぐ目に入る大きな物ばかりにはせず、中くらいの物や細かい所も混ぜる。ただしスマホで見て気づける大きさにする。"
            f"{n}か所は絵の中で離れた場所に散らす。"
        ),
        "notes": ("出力は a.png と b.png（どちらも 1024x1024）。あわせて differences.json に "
                  "{\"differences\": [{\"description\": 日本語の短い説明, \"type\": 種類, \"x\", \"y\", \"width\", \"height\"}]} の形で、"
                  f"{n}か所の位置（1024x1024の座標）を書いてください。"),
    }


if __name__ == "__main__":
    sid, style, scenes = sys.argv[1], sys.argv[2], sys.argv[3:]
    for k, sc in enumerate(scenes, 1):
        rid = f"{sid}_{k:02d}"
        p = ROOT / "requests" / "images" / f"{rid}.json"
        p.write_text(json.dumps(request(rid, style, sc), ensure_ascii=False, indent=1), encoding="utf-8")
        print(p.relative_to(ROOT))
