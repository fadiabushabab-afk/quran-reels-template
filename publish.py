#!/usr/bin/env python3
"""
Publish out/reel.mp4 with out/caption.txt to Instagram Reels (and, when allowed, the Facebook Page).

Environment (GitHub secrets / variables):
  META_PAGE_TOKEN   System-user (or Page) token
  IG_USER_ID        Instagram professional account id (instagram_business_account.id)
  FB_PAGE_ID        Facebook Page id (optional; Facebook posting needs pages_manage_posts)
  PLATFORMS         comma list: instagram,facebook,tiktok (default instagram,facebook)
  TIKTOK_*          TikTok app keys and refresh token: see tiktok.py. TikTok gets the reel only, no
                    story, and only when "tiktok" is in PLATFORMS and the TikTok secrets are set.
  GRAPH_VERSION     Graph API version (default v26.0)
  MEDIA_REPO        optional public repo "owner/name" used to host the video for Instagram
  MEDIA_TOKEN       token with Contents read/write on MEDIA_REPO
  HISTORY           history file to append to (default history.json)
  FORCE             "true" to post even if this slot's reel is already out (normally one reel per slot:
                    morning 08:00 and evening 18:00 local time, Saturday-Thursday; one on Friday);
                    manual runs can also add "force" to the platforms box, e.g. instagram,facebook,force
  RETRY_PREV        set by automatic retries: the published.json of the failed run. Platforms that
                    already have the reel are not posted again (same video, reused), and the
                    history entry for that reel is completed instead of a new one being added.
  STORIES           "true" (default) to also share the same video to the Instagram and Facebook Page
                    Story (never on Fridays or for the morning reel) right after each reel goes out; "false" to post reels only. Manual runs can
                    also add "nostory" to the platforms box.

Facebook: up to 90 s the video goes out as a Reel; longer (the Friday Al-Kahf reels) as a regular
Page video, since Facebook Reels stop at 90 s.

Stories: none on Fridays. Otherwise a story is only posted on a platform whose reel just went out, so the reel and the story
always match. Stories carry no caption (the APIs do not take one) and last 24 hours. A failed
story never blocks the reel or the history entry; it shows as an error annotation on the run.

Instagram: when MEDIA_REPO is set, the full-quality file is hosted briefly as a GitHub release
asset and Instagram fetches it (video_url); the direct (resumable) upload is the fallback.
(Since 2 Nov the direct upload has been refused every time while the hosted URL works.)
Only if both fail is a lighter re-encode tried.

Writes out/published.json. When at least one platform posted, appends the passage
to history.json, so a partly failed run never re-posts it to the platform that worked.
"""
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import tiktok

V = os.environ.get("GRAPH_VERSION", "v26.0")
GRAPH = f"https://graph.facebook.com/{V}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"


def call(method, url, params=None, data=None, headers=None, timeout=120):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {body[:600]}")


def post_instagram(token, ig_id, video, caption, video_url=None, cover_ms=2500, story=False):
    # 1. container: resumable (we upload the bytes) or video_url (Instagram fetches it)
    if story:   # stories take no caption, feed flag or cover
        params = {"media_type": "STORIES", "access_token": token}
    else:
        params = {"media_type": "REELS", "caption": caption, "share_to_feed": "true",
                  "thumb_offset": str(int(cover_ms)), "access_token": token}   # cover = first verse on screen
    params.update({"video_url": video_url} if video_url else {"upload_type": "resumable"})
    cid = call("POST", f"{GRAPH}/{ig_id}/media", params)["id"]
    # 2. upload the bytes
    if not video_url:
        size = os.path.getsize(video)
        with open(video, "rb") as f:
            up = call("POST", f"https://rupload.facebook.com/ig-api-upload/{V}/{cid}", data=f.read(),
                      headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
                               "Content-Type": "application/octet-stream"},
                      timeout=600)
        if not up.get("success", True):
            raise RuntimeError(f"Instagram upload failed: {up}")
    # 3. wait for processing
    for _ in range(60):
        st = call("GET", f"{GRAPH}/{cid}", {"fields": "status_code,status", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing {code}: {st.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram processing timed out")
    # 4. publish
    pub = call("POST", f"{GRAPH}/{ig_id}/media_publish", {"creation_id": cid, "access_token": token})
    media_id = pub["id"]
    try:
        link = call("GET", f"{GRAPH}/{media_id}", {"fields": "permalink", "access_token": token}).get("permalink")
    except Exception:
        link = None
    if not link and story:
        handle = os.environ.get("IG_HANDLE", "").lstrip("@")
        link = f"https://www.instagram.com/stories/{handle}/{media_id}/" if handle else f"instagram story {media_id}"
    return {"id": media_id, "permalink": link}


def safe_copy(video):
    """Lighter, conservative encode (Main profile, 5 Mbps cap, 48 kHz stereo) for a second attempt."""
    dest = os.path.join(OUT, "reel_ig.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-profile:v", "main", "-level", "4.0",
                    "-maxrate", "5M", "-bufsize", "10M", "-pix_fmt", "yuv420p", "-r", "30", "-g", "60",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", dest], check=True)
    return dest


def gh(method, url, token, data=None, ctype="application/json"):
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    return call(method, url, data=body, timeout=600,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "Content-Type": ctype})


def host_on_github(repo, token, video):
    """Upload the video as a release asset of a public repo; returns (url, cleanup)."""
    tag = f"reel-{int(time.time())}"
    rel = gh("POST", f"https://api.github.com/repos/{repo}/releases", token,
             {"tag_name": tag, "name": tag, "body": "Temporary file for Instagram; deleted after posting."})
    def cleanup():
        for url in (f"https://api.github.com/repos/{repo}/releases/{rel['id']}",
                    f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}"):
            try:
                gh("DELETE", url, token)
            except Exception as e:
                print(f"::warning title=Media cleanup failed::{str(e)[:200]}")
    try:
        with open(video, "rb") as f:
            asset = gh("POST", f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets?name=reel.mp4",
                       token, f.read(), "video/mp4")
    except Exception:
        cleanup()
        raise
    return asset["browser_download_url"], cleanup


def instagram(token, ig_id, video, caption, cover_ms=2500, story=False):
    repo, gh_token = os.environ.get("MEDIA_REPO"), os.environ.get("MEDIA_TOKEN")
    what = "story" if story else "reel"

    def post(path, url=None):
        return post_instagram(token, ig_id, path, caption, video_url=url, cover_ms=cover_ms, story=story)

    def hosted(path):
        url, cleanup = host_on_github(repo, gh_token, path)
        try:
            return post(path, url)
        finally:
            cleanup()

    attempts = [("direct upload", lambda: post(video))]
    if repo and gh_token:
        attempts.insert(0, ("hosted URL", lambda: hosted(video)))
        attempts.append(("lighter encode, hosted URL", lambda: hosted(safe_copy(video))))
    else:
        attempts.append(("lighter encode", lambda: post(safe_copy(video))))
    for i, (name, attempt) in enumerate(attempts):
        try:
            return attempt()
        except Exception as e:
            if i == len(attempts) - 1:
                raise
            print(f"::warning title=Instagram {what} {name} refused, trying {attempts[i + 1][0]}::{str(e)[:200]}")


def post_facebook(token, page_id, video, caption):
    s = call("POST", f"{GRAPH}/{page_id}/video_reels", {"upload_phase": "start", "access_token": token})
    vid = s["video_id"]
    size = os.path.getsize(video)
    with open(video, "rb") as f:
        call("POST", f"https://rupload.facebook.com/video-upload/{V}/{vid}", data=f.read(),
             headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
                      "Content-Type": "application/octet-stream"},
             timeout=600)
    call("POST", f"{GRAPH}/{page_id}/video_reels", {
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption, "access_token": token})
    return {"id": vid, "permalink": f"https://www.facebook.com/reel/{vid}"}


def post_facebook_video(token, page_id, video, caption):
    """Regular Page video, for videos longer than Facebook Reels allow (the Friday Al-Kahf reels).
    One multipart upload; Page videos may run far longer than 3 min."""
    boundary = f"----quranreels{int(time.time() * 1000)}"
    parts = []
    for name, value in (("description", caption), ("published", "true"), ("access_token", token)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    with open(video, "rb") as f:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="reel.mp4"\r\n'
                     f'Content-Type: video/mp4\r\n\r\n'.encode() + f.read() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    r = call("POST", f"https://graph-video.facebook.com/{V}/{page_id}/videos", data=b"".join(parts),
             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=900)
    vid = r["id"]
    return {"id": vid, "permalink": f"https://www.facebook.com/{page_id}/videos/{vid}"}


def post_facebook_story(token, page_id, video):
    """Page video story: start -> upload bytes -> finish (same upload host as Reels)."""
    s = call("POST", f"{GRAPH}/{page_id}/video_stories", {"upload_phase": "start", "access_token": token})
    vid = s["video_id"]
    size = os.path.getsize(video)
    with open(video, "rb") as f:
        call("POST", s.get("upload_url") or f"https://rupload.facebook.com/video-upload/{V}/{vid}",
             data=f.read(),
             headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
                      "Content-Type": "application/octet-stream"},
             timeout=600)
    fin = call("POST", f"{GRAPH}/{page_id}/video_stories", {
        "upload_phase": "finish", "video_id": vid, "access_token": token})
    if fin.get("success") is False:
        raise RuntimeError(f"Facebook story not published: {fin}")
    return {"id": fin.get("post_id") or vid, "permalink": f"https://www.facebook.com/stories/{page_id}"}


def page_token_from(token, page_id):
    """Accept a Page token or a (system-)user token: if the Page hands out its own token, use it."""
    if not page_id:
        return token
    try:
        t = call("GET", f"{GRAPH}/{page_id}", {"fields": "access_token", "access_token": token}).get("access_token")
        return t or token
    except Exception:
        return token


def same_reel(a, b):
    return all(a.get(k) == b.get(k) for k in ("date", "surah", "start", "end"))


def merged(history, entry):
    """history with entry added, replacing an earlier record of the same reel (a retry completing it)."""
    return [h for h in history if not same_reel(h, entry)] + [entry]


def record(meta, results, path, stories=None):
    """Append the passage to history once anything was posted (never for --surah test runs).
    Returns False only if it should have been saved and could not be."""
    posted = {k: v["permalink"] for k, v in results.items() if "permalink" in v}
    if not posted or meta.get("fixed"):
        return True
    entry = {k: v for k, v in meta.items() if k != "fixed"}
    entry["posted"] = posted
    failed = [k for k, v in results.items() if "error" in v]
    if failed:
        entry["failed"] = failed
    story_links = {k: v["permalink"] for k, v in (stories or {}).items() if "permalink" in v}
    if story_links:
        entry["stories"] = story_links
    with open(os.path.join(OUT, "history_entry.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_ACTIONS"):
        return save_history_to_github(entry, path)
    history = load_history(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged(history, entry), f, ensure_ascii=False, indent=1)
    return True


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


BRANCH = os.environ.get("GITHUB_REF_NAME") or "main"


def save_history_to_github(entry, path):
    """Merge the entry into the LATEST history.json on GitHub and push, retrying if another run
    pushed in between. (The old commit-then-rebase step crashed on 2 Nov when two runs overlapped,
    which is how Al-Fatiha went unrecorded.) Returns False if every attempt failed."""
    git("config", "user.name", "quran-reels-bot")
    git("config", "user.email", "actions@users.noreply.github.com")
    for i in range(5):
        try:
            git("fetch", "-q", "origin", BRANCH)
            git("reset", "-q", "--hard", f"origin/{BRANCH}")
            history = load_history(path)
            if entry in history:
                return True
            with open(path, "w", encoding="utf-8") as f:
                json.dump(merged(history, entry), f, ensure_ascii=False, indent=1)
            git("add", path)
            git("commit", "-q", "-m", "history: " + json.dumps(entry, ensure_ascii=False))
            git("push", "-q", "origin", f"HEAD:{BRANCH}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"history save attempt {i + 1} failed: {(e.stderr or '')[:300]}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    print("::error title=history.json not saved::the post went out but could not be recorded; add this "
          "entry by hand: " + json.dumps(entry, ensure_ascii=False))
    return False


def load_history(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def already_posted(meta, path):
    """Today's reel is already out (any earlier run, scheduled or manual), judged on the
    latest history.json on GitHub, not the copy this run started with."""
    history = load_history(path)
    if os.environ.get("GITHUB_ACTIONS"):
        try:
            git("fetch", "-q", "origin", BRANCH)
            history = json.loads(git("show", f"origin/{BRANCH}:{path}"))
        except Exception as e:
            print(f"could not read the latest history: {e}", file=sys.stderr)
    slot = meta.get("slot") or "evening"          # entries before the morning slot have no slot
    return [h for h in history if h.get("date") == meta.get("date") and h.get("posted")
            and (h.get("slot") or "evening") == slot]


def main():
    token = os.environ.get("META_PAGE_TOKEN")
    ig_id = os.environ.get("IG_USER_ID")
    if not token or not ig_id:
        print("::warning title=Publishing skipped::META_PAGE_TOKEN / IG_USER_ID secrets are not set")
        return 0
    user_token = token                                   # system-user / user token (best for Instagram)
    token = page_token_from(token, os.environ.get("FB_PAGE_ID"))   # Page token (needed for Facebook)
    video = os.path.join(OUT, "reel.mp4")
    with open(os.path.join(OUT, "caption.txt"), encoding="utf-8") as f:
        caption = f.read().strip()[:2150]          # Instagram caption limit is 2,200 characters
    with open(os.path.join(OUT, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    seconds = float(meta.get("seconds", 0))
    hist_path = os.environ.get("HISTORY", "history.json")
    done = already_posted(meta, hist_path)
    platforms = {x.strip().lower() for x in os.environ.get("PLATFORMS", "instagram,facebook").split(",")}
    force = os.environ.get("FORCE", "").lower() == "true" or "force" in platforms
    want_story = os.environ.get("STORIES", "true").lower() != "false" and "nostory" not in platforms
    before, stories_before = {}, {}
    if os.environ.get("RETRY_PREV"):
        with open(os.environ["RETRY_PREV"], encoding="utf-8") as f:
            prev = json.load(f)
        before = {k: v for k, v in prev.items() if k in ("instagram", "facebook", "tiktok") and "permalink" in v}
        stories_before = {k: v for k, v in prev.get("stories", {}).items() if "error" not in v}
        platforms -= set(before)
        force = True        # today's record is this same reel; we are completing it
        print("::notice title=Retry of a failed run::already out on " + (", ".join(before) or "nothing")
              + "; posting to " + (", ".join(sorted(platforms & {"instagram", "facebook", "tiktok"})) or "nothing (saving history only)"))
    if done and not force:
        print(f"::notice title=Not posted::this slot's reel ({done[-1].get('title')}) is already out today; "
              "one reel per slot (add force to the platforms box to post anyway)")
        return 0

    results, stories = {}, {}

    def share_story(name, fn):
        """Same video to the Story, only after that platform's reel went out. Never fails the run."""
        if not want_story or "permalink" not in results.get(name, {}):
            return
        if meta.get("slot") == "morning":
            stories[name] = {"skipped": "morning reel: stories only with the evening reel"}
            print(f"::notice title={name.title()} story skipped::stories go with the evening reel only")
            return
        if meta.get("friday"):
            stories[name] = {"skipped": "Friday: no story"}
            print(f"::notice title={name.title()} story skipped::no stories on Fridays")
            return
        if seconds > 60:
            stories[name] = {"skipped": f"video is {seconds:.0f} s; Stories take 60 s"}
            print(f"::notice title={name.title()} story skipped::video is {seconds:.0f} s (Stories take 60 s)")
            return
        try:
            stories[name] = fn()
            print(f"::notice title=Shared to {name.title()} story::" + str(stories[name]["permalink"]))
        except Exception as e:
            stories[name] = {"error": str(e)}
            print(f"::error title={name.title()} story failed (reel is up)::" + str(e).replace("\n", " "))

    if "instagram" in platforms:
        try:
            results["instagram"] = instagram(user_token, ig_id, video, caption, meta.get("cover_ms", 2500))
            print("::notice title=Posted to Instagram::" + str(results["instagram"]["permalink"]))
        except Exception as e:
            results["instagram"] = {"error": str(e)}
            print("::error title=Instagram post failed::" + str(e).replace("\n", " "))
        share_story("instagram", lambda: instagram(user_token, ig_id, video, caption, story=True))

    page_id = os.environ.get("FB_PAGE_ID")
    if page_id and "facebook" in platforms:
        try:
            if seconds > 90:    # Friday Al-Kahf: too long for a Facebook Reel, so a regular Page video
                print(f"video is {seconds:.0f} s (Facebook Reels allow 90 s): posting as a Page video")
                results["facebook"] = post_facebook_video(token, page_id, video, caption)
            else:
                results["facebook"] = post_facebook(token, page_id, video, caption)
            print("::notice title=Posted to Facebook::" + str(results["facebook"]["permalink"]))
        except Exception as e:
            results["facebook"] = {"error": str(e)}
            print("::error title=Facebook post failed::" + str(e).replace("\n", " "))
        share_story("facebook", lambda: post_facebook_story(token, page_id, video))

    if "tiktok" in platforms:
        missing = [k for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
                   if not os.environ.get(k)]
        if missing:
            print("::warning title=TikTok skipped::not connected yet (missing " + ", ".join(missing) + ")")
        else:
            try:
                results["tiktok"] = tiktok.post(video, caption, meta.get("cover_ms", 1000), seconds)
                note = "" if results["tiktok"]["privacy"] == "PUBLIC_TO_EVERYONE" else \
                    f" (visible as {results['tiktok']['privacy']})"
                print("::notice title=Posted to TikTok" + note + "::" + results["tiktok"]["permalink"])
            except Exception as e:
                results["tiktok"] = {"error": str(e)}
                print("::error title=TikTok post failed::" + str(e).replace("\n", " "))

    new_failed = any("error" in r for r in results.values())
    results, stories = {**before, **results}, {**stories_before, **stories}
    with open(os.path.join(OUT, "published.json"), "w", encoding="utf-8") as f:
        json.dump({**results, "stories": stories}, f, ensure_ascii=False, indent=2)
    saved = record(meta, results, hist_path, stories)
    failed = new_failed or not saved
    return 1 if failed else 0    # red run -> GitHub emails you


if __name__ == "__main__":
    sys.exit(main())
