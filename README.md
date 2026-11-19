# Quran Reels — automated daily Quran reels

**An open-source template that makes a vertical Quran recitation video (1080×1920) every day and posts it automatically to Instagram, a Facebook Page and TikTok. It runs entirely on GitHub Actions, with no server and no paid service.**

 قالب مفتوح المصدر يُنتج يوميًا مقطعًا قرآنيًا عموديًا (ريل) بتلاوة متقنة ونص عثماني وترجمة، وينشره تلقائيًا على إنستغرام وصفحة فيسبوك وتيك توك عبر GitHub Actions، بلا خادم ولا تكلفة. المقاطع تُختار من قائمة مراجَعة من المقاطع **التامّة المعنى** (قصار السور، وآيات الفضائل الثابتة، ومقاطع موضوعية)، ولا يُقطع النص في منتصف المعنى أبدًا. النص والصوت يُجلبان من مصادر موثوقة ولا يُولَّد شيء منهما بالذكاء الاصطناعي.

---

## What it does

| Step | What happens |
|---|---|
| **1. Choose** | A passage from `passages.py`: short surahs in full, well-known verses of great virtue (with the hadith source and grade), and thematic passages. **Every passage is complete in meaning.** Groups rotate daily; Fridays use the first or last ten verses of Al-Kahf. Each passage is used once before any repeats. |
| **2. Fetch** | Uthmani text, Saheeh International English and التفسير الميسر from [api.alquran.cloud](https://alquran.cloud/api); verse-by-verse audio from [everyayah.com](https://everyayah.com) (20 reciters, all 128–192 kbps). |
| **3. Clean audio** | `audio_trim.py` joins the verse files without the dead gap left where a reverberant reciter's echo is cut off, and ends the reel exactly at the end of the last verse, keeping a held «ن / م» but not the reciter's next breath. |
| **4. Render** | Verse-synchronised Arabic (Amiri Quran) and English over a background, with soft looping motion (light rays, dust, slow drift) from `motion.py`. Text colour adapts to light or dark images. Default length is up to 30 s; a longer passage is posted one complete *ruku'* section at a time. |
| **5. Caption** | A hook line, the virtue and its source, a short reflection from التفسير الميسر, the verses in Arabic and English, the reciter, **«عمل اليوم»** (one small practical action for the day, matched to the passage, from `actions.py`), and 5 hashtags. Kept within Instagram's limit. |
| **6. Publish** | Instagram Reel, Facebook Page Reel and TikTok, plus optional Instagram and Facebook Stories. Records what was posted in `history.json`. |
| **7. Recover** | If generating or posting fails, the run waits 45 minutes and retries, reposting only where it failed, so nothing goes out twice. Watchdog runs cover days when GitHub skips a schedule. |
| **8. Learn** *(optional)* | `trends.py` reads your own reels' saves, shares and reach (and, if the Meta app is allowed, top posts on Quran hashtags), and puts the best-performing passages first. |

## Quick start (local test)

```bash
# Python 3.9+, ffmpeg on PATH, Pillow with libraqm (Arabic shaping)
sudo apt-get install -y ffmpeg libraqm0        # Debian/Ubuntu
pip install -r requirements.txt

python generate.py                              # next passage, random reciter
python generate.py --verses 112:1-4 --reciter husary --handle @your_account
python generate.py --verses 2:255               # Ayat al-Kursi
```

The output goes to `out/`: `reel.mp4`, `caption.txt` and `meta.json`. Nothing is posted when you run it locally.

## Run it every day on GitHub

1. **Use this template** (or fork it), and keep your copy **private** if you will store a posting history you don't want public.
2. Add the secrets and variables listed in **[docs/SETUP.md](docs/SETUP.md)** (Meta token, Instagram user id, Facebook Page id, and optionally TikTok).
3. Set the `HANDLE` variable (e.g. `@your_account`) and, if you are not in UTC+3, the `TIMEZONE` variable. Then shift the cron lines (see SETUP).
4. Test: **Actions → Daily Quran reel → Run workflow**, with "Post this video?" left **unticked**. Download the video from the run's artifacts and review it.
5. When you are happy, tick "Post" for one manual run, then let the schedule take over.

## Backgrounds

Put your own photos (jpg/png) or short vertical clips in `backgrounds/`, or prepare a folder with:

```bash
python sync_backgrounds.py "/path/to/your/folder"
```

This resizes images, turns clips into seamless 1080×1920 loops with no audio, and skips anything listed in `background_exclude.txt`. Backgrounds rotate in full cycles: none is reused until every one has been used once. If the folder is empty, a drawn Islamic geometric style from `bgstyles.py` is used, so the template works out of the box.

**Use only images you have the right to use, and keep them in keeping with the Quran:** no people, no music imagery, nothing distracting. Pixabay and Pexels licences allow this kind of use, but check each file.

## Configuration at a glance

| Where | Name | Default | What |
|---|---|---|---|
| variable | `HANDLE` | *(empty)* | Shown on the video and in "Follow … for daily verses" |
| variable | `TIMEZONE` | `Asia/Baghdad` | Decides "today", Fridays and the posting windows |
| variable | `PLATFORMS` | `instagram,facebook` | Add `tiktok` once it is connected |
| variable | `STORIES` | `true` | Also share each reel to the Stories |
| variable | `MAX_RETRIES` / `RETRY_DELAY_SEC` | `2` / `2700` | Automatic retry after a failure |
| variable | `TREND_TAGS` | built-in list | Hashtags read by `trends.py` |
| code | `passages.py` | curated list | **Edit with care:** see CONTRIBUTING |
| code | `RECITERS` in `generate.py` | 20 reciters | Folder names on everyayah.com |
| CLI | `--max-sec` | 30 | Longest weekday reel |

To post a second (morning) reel each day, uncomment the two morning `cron` lines in `.github/workflows/daily-reel.yml`.

## Project layout

```
generate.py          choose passage → fetch text/audio → render reel.mp4 + caption
passages.py          curated, complete-in-meaning passages (+ virtue source and grade)
audio_trim.py        smooth verse joins; cut the audio at the true end of the last verse
actions.py           «عمل اليوم»: a small daily action matched to each passage
motion.py            soft looping motion for still backgrounds
bgstyles.py          drawn Islamic geometric fallback backgrounds
sync_backgrounds.py  prepare a folder of images/clips as backgrounds
publish.py           Instagram / Facebook (reels + stories) + TikTok, history.json
tiktok.py            TikTok Content Posting API (Direct Post) + OAuth helper
trends.py            reads your reels' results and Quran hashtags → trends.json
.github/workflows/   daily-reel.yml, trends.yml, tiktok-connect.yml
```

## Principles

- **The Quranic text is never generated or retyped.** It always comes from a verified source (the `quran-uthmani` edition on alquran.cloud), verse by verse.
- **No passage is cut mid-meaning.** Long passages are split only at traditional *ruku'* boundaries.
- **Virtues are cited with their source and grade.** Weak narrations are not presented as established.
- **Reciters are vetted for audio quality** (128 kbps or more, clean murattal Hafs recitations).

## Contributing

Corrections to `passages.py`, new vetted reciters, more platforms, a translation switch and better motion are all welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first; Quranic content has stricter review rules than code.

## Licence and credits

The code is released under the [MIT Licence](LICENSE). The Quran text, translations, tafsir, recitations and fonts belong to their owners and keep their own terms. See [NOTICE.md](NOTICE.md).

May Allah accept it from everyone who builds on it. **تقبّل الله منا ومنكم.**
