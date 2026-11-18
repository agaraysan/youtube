#!/usr/bin/env python3
"""Codex（ChatGPT ログイン）の鍵を、Actions の全ジョブで1つだけ共有して使い回すための道具。

Codex のログインの refresh_token は「1回使うと新しいものに変わる」。Actions は更新後の鍵を Secret に
書き戻せないので、どれか1つのジョブが更新すると、残りは使用済みの古い鍵ではじかれていた。
そこで、更新後の鍵を暗号化して専用ブランチ（codex-auth）に置き、次のジョブはそこから読む。

  python3 scripts/codex_auth.py load      # 共有の鍵か Secret の新しいほうを ~/.codex/auth.json に置く
  python3 scripts/codex_auth.py refresh   # 期限が近ければ更新して、すぐ共有に書き戻す
  python3 scripts/codex_auth.py save      # Codex が自分で更新していたら共有に書き戻す
  python3 scripts/codex_auth.py status    # 期限だけ表示（鍵の中身は出さない）

必要な環境変数：CODEX_AUTH_JSON（Secret）、CODEX_AUTH_KEY（暗号化の鍵。Secret の OPENAI_API_KEY を流用してよい）。
git は actions/checkout 済みのリポジトリ（GITHUB_TOKEN で push できる）で動かす。鍵の中身はログに出さない。"""
import base64, hashlib, json, os, pathlib, subprocess, sys, tempfile, time, urllib.error, urllib.request

BRANCH = "codex-auth"
FILE = "auth.enc"
AUTH = pathlib.Path.home() / ".codex" / "auth.json"
MARK = pathlib.Path.home() / ".codex" / "auth.loaded.sha"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REFRESH_BEFORE = int(os.environ.get("CODEX_REFRESH_BEFORE", 6 * 3600))  # 期限まで残りこれ以下なら更新


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


def key():
    k = os.environ.get("CODEX_AUTH_KEY", "")
    if not k:
        sys.exit("CODEX_AUTH_KEY がありません")
    return hashlib.sha256(("codex-auth|" + k).encode()).hexdigest()


def crypt(data: bytes, decrypt=False) -> bytes:
    args = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-pass", "env:_K"]
    if decrypt:
        args.append("-d")
    r = subprocess.run(args, input=data, capture_output=True, env={**os.environ, "_K": key()})
    if r.returncode:
        raise RuntimeError("openssl に失敗")
    return r.stdout


def jwt(tok):
    try:
        p = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}


def tokens(a):
    return (a or {}).get("tokens") or {}


def expires(a):
    return jwt(tokens(a).get("access_token", "")).get("exp", 0)


def stamp(a):
    """どちらが新しいか比べる目安：最後に更新した時刻（無ければ access_token の発行時刻）。"""
    t = (a or {}).get("last_refresh") or ""
    iat = jwt(tokens(a).get("access_token", "")).get("iat", 0)
    return (t, iat)


def fetch_shared():
    r = sh("git", "fetch", "-q", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    if r.returncode:
        return None
    r = subprocess.run(["git", "show", f"origin/{BRANCH}:{FILE}"], capture_output=True)
    if r.returncode:
        return None
    try:
        return json.loads(crypt(base64.b64decode(r.stdout), decrypt=True))
    except Exception:
        print("共有の鍵を開けませんでした（暗号化の鍵が変わった？）。Secret を使います。")
        return None


def write_local(a):
    AUTH.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(a, indent=2)
    AUTH.write_text(raw)
    AUTH.chmod(0o600)
    MARK.write_text(hashlib.sha256(raw.encode()).hexdigest())


def push_shared(a):
    """共有ブランチに書き戻す。先に誰かが新しい鍵を置いていたら上書きしない。"""
    blob = base64.b64encode(crypt(json.dumps(a).encode())).decode()
    for i in range(6):
        cur = fetch_shared()
        if cur and stamp(cur) > stamp(a):
            print("共有の鍵のほうが新しいので、書き戻しません。")
            return
        with tempfile.TemporaryDirectory() as t:
            wt = pathlib.Path(t) / "wt"
            if sh("git", "rev-parse", "--verify", "-q", f"origin/{BRANCH}").returncode == 0:
                sh("git", "worktree", "add", "-q", "--detach", str(wt), f"origin/{BRANCH}")
            else:
                sh("git", "worktree", "add", "-q", "--detach", str(wt))
                sh("git", "checkout", "-q", "--orphan", "tmp-codex-auth", cwd=wt)
                sh("git", "rm", "-rqf", ".", cwd=wt)
            (wt / FILE).write_text(blob)
            (wt / "README.md").write_text("Codex のログインの鍵（暗号化済み）。Actions が自動で書き換えます。手で触らないでください。\n")
            sh("git", "add", FILE, "README.md", cwd=wt)
            sh("git", "-c", "user.name=github-actions[bot]", "-c",
               "user.email=41898282+github-actions[bot]@users.noreply.github.com",
               "commit", "-qm", "codex-auth: 鍵を更新", cwd=wt)
            ok = sh("git", "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=wt).returncode == 0
            sh("git", "worktree", "remove", "--force", str(wt))
        if ok:
            print("共有の鍵を書き戻しました。")
            return
        time.sleep(3 * (i + 1))
    print("共有の鍵の書き戻しに失敗しました。")


def load():
    secret = json.loads(os.environ.get("CODEX_AUTH_JSON") or "null")
    shared = fetch_shared()
    best = max([x for x in (secret, shared) if x], key=stamp, default=None)
    if not best:
        sys.exit("Codex の鍵がありません（Secret CODEX_AUTH_JSON を入れてください）")
    write_local(best)
    print("鍵を読みました：", "共有" if best is shared else "Secret", "／期限まで", int((expires(best) - time.time()) / 3600), "時間")


def refresh(force=False):
    a = json.loads(AUTH.read_text())
    left = expires(a) - time.time()
    if not force and left > REFRESH_BEFORE:
        print("更新は不要（期限まで", int(left / 3600), "時間）")
        return
    t = tokens(a)
    aud = jwt(t.get("id_token", "")).get("aud")
    client = aud[0] if isinstance(aud, list) else aud
    body = json.dumps({"client_id": client, "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                       "scope": "openid profile email"}).encode()
    req = urllib.request.Request(TOKEN_URL, body, {"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        # ほかのジョブが同時に更新した場合は、共有に新しい鍵が置かれるので、それを待って使う
        for _ in range(6):
            time.sleep(10)
            cur = fetch_shared()
            if cur and stamp(cur) > stamp(a) and expires(cur) > time.time():
                write_local(cur)
                print("ほかのジョブが更新した鍵を使います。")
                return
        sys.exit(f"鍵の更新に失敗しました（HTTP {e.code}）。ログインし直して Secret を入れ直してください。")
    for k in ("id_token", "access_token", "refresh_token"):
        if r.get(k):
            t[k] = r[k]
    a["tokens"] = t
    a["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())
    write_local(a)
    print("鍵を更新しました（期限まで", int((expires(a) - time.time()) / 3600), "時間）")
    push_shared(a)


def save():
    if not AUTH.exists():
        return
    raw = AUTH.read_text()
    if MARK.exists() and hashlib.sha256(raw.encode()).hexdigest() == MARK.read_text():
        print("鍵は変わっていません。")
        return
    push_shared(json.loads(raw))


def status():
    a = json.loads(AUTH.read_text())
    print("期限まで", int((expires(a) - time.time()) / 3600), "時間／最後の更新", a.get("last_refresh"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"load": load, "refresh": refresh, "force": lambda: refresh(True), "save": save, "status": status}[cmd]()
