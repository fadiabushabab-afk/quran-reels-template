# Setup guide

All settings live in your repository under **Settings → Secrets and variables → Actions**. Put credentials under **Secrets** and plain settings under **Variables**. Nothing secret is ever stored in the code.

## 1. Meta (Instagram + Facebook Page)

**You need:**
- an Instagram **professional** account (Business or Creator),
- a Facebook Page linked to that Instagram account,
- a Meta developer app (type *Business*).

**Steps:**

1. In Meta Business Settings, create a **System User**, give it access to the Page and the Instagram account, and generate a **long-lived token** with these permissions: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, and `instagram_manage_insights` (for `trends.py`).
2. Find the Instagram account id: `GET /{page-id}?fields=instagram_business_account`.

| Name | Kind | Value |
|---|---|---|
| `META_PAGE_TOKEN` | secret | the System User token (a Page token also works) |
| `IG_USER_ID` | secret | `instagram_business_account.id` |
| `FB_PAGE_ID` | secret | the Facebook Page id (leave it out to post to Instagram only) |

### Recommended: hosting the video for Instagram

Instagram's direct (resumable) upload is sometimes refused, while a public video URL keeps working. If you set the two names below, the video is put on a public repo as a temporary GitHub release asset, Instagram fetches it from there, and the asset is then deleted.

| Name | Kind | Value |
|---|---|---|
| `MEDIA_REPO` | variable | `owner/name` of a **public** repo used only for this |
| `MEDIA_TOKEN` | secret | fine-grained token on that repo only, with **Contents: Read and write** |

## 2. TikTok (optional)

1. Create an app at developers.tiktok.com and add **Login Kit** and **Content Posting API** with **Direct Post**. The scopes are `user.info.basic` and `video.publish`.
2. Register a redirect URI. Any page you control will do, for example your GitHub Pages site.
3. Add the settings below.
4. Run **Actions → TikTok connect** once with the box empty, open the link it prints and allow access. Then run it again with the whole address you were sent to pasted into the box. This saves `TIKTOK_REFRESH_TOKEN` for you.
5. Add `tiktok` to the `PLATFORMS` variable.

| Name | Kind | Value |
|---|---|---|
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | secrets | from the TikTok app |
| `TIKTOK_REDIRECT_URI` | variable | exactly as registered |
| `GH_ADMIN_TOKEN` | secret | fine-grained token on **this repo only**, with **Secrets: Read and write**. TikTok rotates refresh tokens, and this token saves the new one. |
| `TIKTOK_PRIVACY` | variable | optional, default `PUBLIC_TO_EVERYONE` |

Until TikTok audits your app, posts are private and the account must be set to private.

## 3. General settings

| Name | Kind | Default | What |
|---|---|---|---|
| `HANDLE` | variable | *(empty)* | e.g. `@your_account` |
| `TIMEZONE` | variable | `Asia/Baghdad` | any IANA zone, e.g. `Africa/Cairo`, `Europe/London` |
| `PLATFORMS` | variable | `instagram,facebook` | add `tiktok` when it is connected |
| `STORIES` | variable | `true` | `false` turns off sharing to the Stories |
| `MAX_RETRIES` | variable | `2` | automatic retries after a failure |
| `RETRY_DELAY_SEC` | variable | `2700` | wait before a retry (45 min) |
| `TREND_TAGS` | variable | built-in | comma-separated hashtags for `trends.py` (Instagram allows 30 unique hashtags per 7 days) |

## 4. Schedule and time zone

GitHub `cron` lines are in **UTC**. The workflow ships set for **UTC+3**:

- 18:07 every day except Friday,
- 09:07 on Friday (Al-Kahf),
- watchdog runs later in the day, which post only if nothing went out.

If you change `TIMEZONE`, shift the cron lines in `.github/workflows/daily-reel.yml` **and the same strings in the `case` lines of the `guard` job**, which match runs by their cron text. You may also change the posting windows (`from` / `until`) there.

**Second reel each day:** uncomment the two morning cron lines.

## 5. On-time posting (recommended)

GitHub's scheduler can start runs hours late, or skip them. The guard then refuses to post outside the slot's window, so a late run never posts at the wrong time. For reliable timing, trigger the workflow from an outside scheduler such as cron-job.org (free):

1. Create a fine-grained GitHub token on this repo only, with **Actions: Read and write**.
2. Add one job per reel, in your time zone:
   - URL: `https://api.github.com/repos/OWNER/REPO/actions/workflows/daily-reel.yml/dispatches`, method **POST**
   - Headers: `Authorization: Bearer <token>` and `Accept: application/vnd.github+json`
   - Body: `{"ref":"main","inputs":{"auto":"true","slot":"evening"}}` (use `"morning"` for a morning reel)

A run with `auto=true` behaves like a scheduled one: it posts only inside its window, never twice per slot, and is retried after a failure. GitHub's own crons stay in place as a backup.

## 6. First test

1. Go to **Actions → Daily Quran reel → Run workflow**.
2. Leave **Post this video?** unticked.
3. Optionally set `verses` (e.g. `112:1-4`) or `background`.
4. Download the `reel-N` artifact and check the text, audio cut, caption and cover.
5. Run it once more with **Post** ticked. After that, the schedule takes over.
