#!/usr/bin/env python3
"""
TikTok posting through the Content Posting API (Direct Post), used by publish.py.

Environment (GitHub secrets / variables):
  TIKTOK_CLIENT_KEY      app client key   (secret)
  TIKTOK_CLIENT_SECRET   app client secret (secret)
  TIKTOK_REFRESH_TOKEN   the account's refresh token (secret; written by the "TikTok connect" workflow)
  GH_ADMIN_TOKEN         fine-grained GitHub token for this repo with Secrets: read and write. TikTok may
                         hand back a NEW refresh token on every refresh; this token is how the new one
                         is saved over TIKTOK_REFRESH_TOKEN. Without it, posting stops when the old one lapses.
  TIKTOK_PRIVACY         variable: PUBLIC_TO_EVERYONE (default), FOLLOWER_OF_CREATOR, MUTUAL_FOLLOW_FRIENDS
                         or SELF_ONLY. Until TikTok audits the app, every post is private whatever this says.
  TIKTOK_REDIRECT_URI    variable: the redirect URI registered under Login Kit (used only when connecting)

Command line (run by the "TikTok connect" workflow):
  python tiktok.py url              print the link that asks the account to allow posting
  python tiktok.py connect CODE     exchange the code (or the whole address it landed on) for tokens
"""
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish"
MB = 1024 * 1024


def _req(method, url, token=None, body=None, form=None, data=None, headers=None, timeout=120):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"TikTok {method} {url.split('?')[0]} -> {e.code}: "
                           f"{e.read().decode('utf-8', 'replace')[:600]}")


def _ok(resp, what):
    err = resp.get("error") or {}
    if err.get("code", "ok") != "ok":
        raise RuntimeError(f"TikTok {what}: {err.get('code')}: {err.get('message')}")
    return resp.get("data") or {}


def _mask(value):
    if value and os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}")


def save_secret(name, value):
    """Store a value as a repository secret with GH_ADMIN_TOKEN. Returns True on success."""
    admin, repo = os.environ.get("GH_ADMIN_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not admin or not repo:
        return False
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                       env={**os.environ, "GH_TOKEN": admin}, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"::warning title=Could not save {name}::{r.stderr.strip()[:300]}")
    return r.returncode == 0


def _tokens(form):
    t = _req("POST", f"{API}/oauth/token/", form={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"], **form})
    if "access_token" not in t:
        raise RuntimeError(f"TikTok token request refused: {t.get('error')}: {t.get('error_description')}")
    _mask(t["access_token"])
    _mask(t.get("refresh_token"))
    return t


def access_token():
    """Fresh access token (they last 24 h) from the stored refresh token; saves a rotated refresh token."""
    old = os.environ["TIKTOK_REFRESH_TOKEN"]
    t = _tokens({"grant_type": "refresh_token", "refresh_token": old})
    new = t.get("refresh_token")
    if new and new != old:
        if save_secret("TIKTOK_REFRESH_TOKEN", new):
            print("TikTok gave a new refresh token; saved it over TIKTOK_REFRESH_TOKEN")
        else:
            print("::warning title=TikTok refresh token changed but was not saved::add the GH_ADMIN_TOKEN "
                  "secret, or run the TikTok connect workflow again, or TikTok posting will stop")
    days = int(t.get("refresh_expires_in", 0)) // 86400
    if 0 < days <= 14:
        print(f"::warning title=TikTok connection ends in {days} days::run the TikTok connect workflow again")
    return t["access_token"]


def _chunks(size):
    """(chunk_size, count) per the Media Transfer Guide: whole file up to 64 MB, else 10 MB chunks
    with the remainder joined to the last one (count = size // chunk_size)."""
    if size <= 64 * MB:
        return size, 1
    chunk = 10 * MB
    return chunk, size // chunk


def post(video, caption, cover_ms=1000, seconds=0):
    """Direct-post the video. Returns {"publish_id", "permalink", "privacy"}; raises on failure."""
    token = access_token()
    info = _ok(_req("POST", f"{API}/post/publish/creator_info/query/", token, body={}), "creator info")
    user = info.get("creator_username", "")
    options = info.get("privacy_level_options") or []
    longest = int(info.get("max_video_post_duration_sec") or 0)
    if longest and seconds > longest:
        raise RuntimeError(f"video is {seconds:.0f} s; this TikTok account can post up to {longest} s")
    want = os.environ.get("TIKTOK_PRIVACY") or "PUBLIC_TO_EVERYONE"
    privacy = want if want in options else ("SELF_ONLY" if "SELF_ONLY" in options else (options or [want])[0])
    if privacy != want:
        print(f"::warning title=TikTok privacy {want} not offered::posting as {privacy} (offered: {', '.join(options)})")

    size = os.path.getsize(video)
    chunk, count = _chunks(size)
    init = _ok(_req("POST", f"{API}/post/publish/video/init/", token, body={
        "post_info": {"title": caption[:2200], "privacy_level": privacy,
                      "disable_duet": False, "disable_stitch": False, "disable_comment": False,
                      "video_cover_timestamp_ms": int(cover_ms),
                      "brand_content_toggle": False, "brand_organic_toggle": False, "is_aigc": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count}}), "init")
    pid, url = init["publish_id"], init["upload_url"]

    with open(video, "rb") as f:
        for i in range(count):
            first = i * chunk
            last = size - 1 if i == count - 1 else first + chunk - 1
            f.seek(first)
            part = f.read(last - first + 1)
            _req("PUT", url, data=part, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                "Content-Range": f"bytes {first}-{last}/{size}"})

    for _ in range(60):          # up to ~10 minutes
        time.sleep(10)
        st = _ok(_req("POST", f"{API}/post/publish/status/fetch/", token, body={"publish_id": pid}), "status")
        status = st.get("status")
        if status == "FAILED":
            raise RuntimeError(f"TikTok processing failed: {st.get('fail_reason')}")
        if status == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
            profile = f"https://www.tiktok.com/@{user}" if user else "https://www.tiktok.com/"
            link = f"{profile}/video/{ids[0]}" if ids and user else profile
            return {"publish_id": pid, "permalink": link, "privacy": privacy}
    raise RuntimeError(f"TikTok still processing after 10 minutes (publish_id {pid})")


def auth_url():
    q = urllib.parse.urlencode({"client_key": os.environ["TIKTOK_CLIENT_KEY"], "scope": SCOPES,
                                "response_type": "code", "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
                                "state": "quran-reels"})
    return f"https://www.tiktok.com/v2/auth/authorize/?{q}"


def connect(code_or_url):
    text = code_or_url.strip()
    if "code=" in text:
        text = urllib.parse.parse_qs(urllib.parse.urlparse(text).query).get("code", [""])[0]
    code = urllib.parse.unquote(text)
    t = _tokens({"grant_type": "authorization_code", "code": code,
                 "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"]})
    granted = set((t.get("scope") or "").replace(" ", "").split(","))
    if "video.publish" not in granted:
        raise RuntimeError(f"the account did not allow posting (granted: {t.get('scope')}); "
                           "tick every permission on the TikTok screen and try again")
    if not save_secret("TIKTOK_REFRESH_TOKEN", t["refresh_token"]):
        raise RuntimeError("tokens received but TIKTOK_REFRESH_TOKEN could not be saved: check GH_ADMIN_TOKEN")
    days = int(t.get("refresh_expires_in", 0)) // 86400
    print(f"::notice title=TikTok connected::saved TIKTOK_REFRESH_TOKEN (scopes: {t.get('scope')}; "
          f"valid {days} days, renewed on each post)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "url":
        print(auth_url())
    elif cmd == "connect" and len(sys.argv) > 2:
        connect(sys.argv[2])
    else:
        sys.exit(__doc__)
