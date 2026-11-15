#!/usr/bin/env python3
"""YouTube Data API で投稿・公開設定をする。認証は環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN。

queue/upload/<id>.json  … 新しく動画を上げる
  {"id","video_url" or "video_path","title","description","tags":[],"category_id":"27",
   "privacy":"private|unlisted|public","publish_at":"2026-11-17T21:00:00+09:00"(任意),
   "thumbnail_url"/"thumbnail_path"(任意),"made_for_kids":false,"language":"ja"}
queue/publish/<id>.json … すでにある動画の公開設定を変える
  {"youtube_id","privacy":"public|private|unlisted","publish_at"(任意)}

処理が終わった依頼は logs/youtube/<id>.json に結果を書き、二度実行しない。
"""
import json, os, pathlib, sys, datetime, urllib.request, tempfile
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "youtube"


def client():
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"])
    return build("youtube", "v3", credentials=c, cache_discovery=False)


def fetch(url_or_path, suffix):
    if not url_or_path:
        return None
    if url_or_path.startswith("http"):
        t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        req = urllib.request.Request(url_or_path, headers={"Accept": "application/vnd.github.raw"})
        tok = os.environ.get("GH_TOKEN")
        if tok and "api.github.com" in url_or_path:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=1800) as r:
            while chunk := r.read(1 << 20):
                t.write(chunk)
        t.close()
        return t.name
    return str(ROOT / url_or_path)


def status_body(j):
    s = {"privacyStatus": j.get("privacy", "private"), "selfDeclaredMadeForKids": bool(j.get("made_for_kids", False))}
    if j.get("publish_at"):
        s["privacyStatus"] = "private"
        s["publishAt"] = datetime.datetime.fromisoformat(j["publish_at"]).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return s


def upload(yt, j):
    video = fetch(j.get("video_url") or j.get("video_path"), ".mp4")
    body = {"snippet": {"title": j["title"][:100], "description": j.get("description", "")[:5000], "tags": j.get("tags", []),
                        "categoryId": str(j.get("category_id", "27")), "defaultLanguage": j.get("language", "ja"),
                        "defaultAudioLanguage": j.get("language", "ja")},
            "status": status_body(j)}
    req = yt.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(video, chunksize=8 << 20, resumable=True))
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            print(f"  {int(st.progress() * 100)}%", flush=True)
    vid = resp["id"]
    thumb = fetch(j.get("thumbnail_url") or j.get("thumbnail_path"), ".png")
    thumb_ok = None
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb)).execute()
            thumb_ok = True
        except Exception as e:  # サムネイルは電話番号の確認が済んだチャンネルだけ使える
            thumb_ok = f"failed: {e}"[:300]
    return {"youtube_id": vid, "status_returned": resp.get("status"), "thumbnail": thumb_ok}


def publish(yt, j):
    cur = yt.videos().list(part="status", id=j["youtube_id"]).execute()["items"][0]["status"]
    new = status_body(j)
    cur.update(new)
    if "publishAt" not in new:
        cur.pop("publishAt", None)
    resp = yt.videos().update(part="status", body={"id": j["youtube_id"], "status": cur}).execute()
    return {"youtube_id": j["youtube_id"], "status_returned": resp.get("status")}


def main():
    LOG.mkdir(parents=True, exist_ok=True)
    yt = client()
    n = 0
    for kind, fn in (("upload", upload), ("publish", publish)):
        for p in sorted((ROOT / "queue" / kind).glob("*.json")):
            out = LOG / f"{kind}_{p.stem}.json"
            if out.exists():
                continue
            j = json.loads(p.read_text(encoding="utf-8"))
            print(kind, p.stem, flush=True)
            try:
                res = {"ok": True, **fn(yt, j)}
            except Exception as e:
                res = {"ok": False, "error": str(e)[:2000]}
            res.update({"request": p.name, "at_utc": datetime.datetime.utcnow().isoformat() + "Z"})
            out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps(res, ensure_ascii=False), flush=True)
            n += 1
    print("processed", n)


if __name__ == "__main__":
    sys.exit(main())
