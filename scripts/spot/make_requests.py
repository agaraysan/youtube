#!/usr/bin/env python3
"""間違い探しの絵の依頼書（requests/images/<id>.json）を作る。

使い方: make_requests.py <回のid> <場面の表 .json>
場面の表: [{"style": "anime|photo", "scene": "場面の説明"}, ...]
各場面について、正方形の2枚（a.png / b.png）と differences.json（違い5か所）を Codex に頼む。
出来上がりは Actions の codex-image が spotcheck（画素の比較）で確かめる。
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
STYLE = {
    "anime": ("日本の雑誌やテレビの間違い探しに載るような、プロのイラストレーターが描いた丁寧なアニメ調のイラスト。"
              "線はきれいで、色はやわらかく上品。人物の顔・手・指は自然な形にする"),
    "photo": ("プロのカメラマンが撮ったような、本物の写真にしか見えないフォトリアルな画像（自然な光と影、高精細）。"
              "人物の顔・手・指・服のしわが自然で、CGっぽさや作り物っぽさがないこと。実在の人物や商標は使わない"),
}
TYPES = ("違いの種類は混ぜる：①ある物が消えている ②物の数が変わっている ③物の形が変わっている ④別の物に入れ替わっている "
         "⑤大きさが変わっている ⑥向きや位置が少し変わっている ⑦服や物の模様が変わっている。色だけを変える違いは多くても1か所まで。"
         "ちょうちんや照明の形を変えるだけの違いはなるべく使わず、使っても1か所まで。5か所はなるべく違う種類にする。")


def request(rid, style, scene, n=5):
    return {
        "id": rid, "kind": "image", "pair": True, "size": "1024x1024", "count": 1,
        "prompt": (
            f"間違い探し用の絵を2枚作ってください。1枚目 a.png：正方形（1024x1024）。{STYLE[style]}。場面：{scene}。"
            "人物や小物をたくさん（30個以上の物が見えるように）入れて、見るところが多いにぎやかな絵にする。"
            "絵の中に文字・数字・ロゴ・看板の字は入れない（字がにじんだ看板も入れない）。"
            f"2枚目 b.png：a.png をコピーして、違いを{n}か所だけ描き変える。違いの部分だけを描き変えて元の絵に貼り合わせ、"
            "違い以外は a.png と画素単位で完全に同じにする（構図・色・人物・位置・明るさ・画質を変えない。全体を描き直さない）。"
            f"{TYPES}簡単すぎないように、すぐ目に入る大きな物ばかりにはせず、中くらいの物や細かい所も混ぜる。"
            "ただしスマホの画面で見て気づける大きさにする（どの違いも幅か高さが50画素以上）。"
            "描き変えた部分は周りになじませ、継ぎ目や四角い跡が見えないようにする。"
            f"{n}か所は絵の中で離れた場所に散らし（おたがい200画素以上はなす）、絵の端ぎりぎりには置かない。"
        ),
        "notes": ("出力は a.png と b.png（どちらも 1024x1024）。あわせて differences.json に "
                  "{\"differences\": [{\"description\": 日本語の短い説明（例：『女の子の帽子のぽんぽんが消えている』）, \"type\": 種類, \"x\", \"y\", \"width\", \"height\"}]} の形で、"
                  f"{n}か所の位置（1024x1024の座標）を書いてください。説明は、b.png（右の絵）で何がどう変わったかを書く。"),
    }


if __name__ == "__main__":
    eid, table = sys.argv[1], json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
    for k, row in enumerate(table, 1):
        rid = f"{eid}_{k:02d}"
        p = ROOT / "requests" / "images" / f"{rid}.json"
        p.write_text(json.dumps(request(rid, row["style"], row["scene"]), ensure_ascii=False, indent=1), encoding="utf-8")
        print(p.relative_to(ROOT))
