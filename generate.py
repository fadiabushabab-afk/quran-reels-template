#!/usr/bin/env python3
"""
Quran Reels generator.

Each run picks a complete, well-known passage from passages.py (short surahs
in full, and famous verses of great virtue), a random reciter, and an Islamic
geometric background, then renders a 1080x1920 vertical video.

Audio: everyayah.com (one MP3 per verse).  Text: api.alquran.cloud (Uthmani).

Outputs (in --out, default ./out):
  reel.mp4      the video
  caption.txt   ready-to-post caption
  meta.json     what was chosen

Usage:
  python generate.py                                   # next passage, random reciter
  python generate.py --surah 112 --start 1 --end 4 --reciter alafasy
"""
import argparse, datetime, json, math, os, random, re, shutil, subprocess, sys, tempfile, time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from passages import PASSAGES, FRIDAY, COMFORT
from zoneinfo import ZoneInfo
import actions, audio_trim, bgstyles, motion

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
FPS = 30

# everyayah.com folder names -> Arabic display name
RECITERS = {
    "alafasy":    ("Alafasy_128kbps", "مشاري راشد العفاسي"),
    "husary":     ("Husary_128kbps", "محمود خليل الحصري"),
    "minshawy":   ("Minshawy_Murattal_128kbps", "محمد صديق المنشاوي"),
    "abdulbasit": ("Abdul_Basit_Murattal_192kbps", "عبد الباسط عبد الصمد"),
    "maher":      ("MaherAlMuaiqly128kbps", "ماهر المعيقلي"),
    "sudais":     ("Abdurrahmaan_As-Sudais_192kbps", "عبد الرحمن السديس"),
    "shuraym":    ("Saood_ash-Shuraym_128kbps", "سعود الشريم"),
    "dussary":    ("Yasser_Ad-Dussary_128kbps", "ياسر الدوسري"),
    # added Nov 2026: high-quality (128/192 kbps) Hafs murattal recitations on everyayah.com
    "juhany":     ("Abdullaah_3awwaad_Al-Juhaynee_128kbps", "عبد الله عواد الجهني"),
    "basfar":     ("Abdullah_Basfar_192kbps", "عبد الله بصفر"),
    "shaatree":   ("Abu_Bakr_Ash-Shaatree_128kbps", "أبو بكر الشاطري"),
    "ajamy":      ("Ahmed_ibn_Ali_al-Ajamy_128kbps_ketaballah.net", "أحمد بن علي العجمي"),
    "rifai":      ("Hani_Rifai_192kbps", "هاني الرفاعي"),
    "hudhaify":   ("Hudhaify_128kbps", "علي الحذيفي"),
    "qahtani":    ("Khaalid_Abdullaah_al-Qahtaanee_192kbps", "خالد القحطاني"),
    "ayyoub":     ("Muhammad_Ayyoub_128kbps", "محمد أيوب"),
    "qasim":      ("Muhsin_Al_Qasim_192kbps", "عبد المحسن القاسم"),
    "qatami":     ("Nasser_Alqatami_128kbps", "ناصر القطامي"),
    "bukhatir":   ("Salaah_AbdulRahman_Bukhatir_128kbps", "صلاح بو خاطر"),
    "budair":     ("Salah_Al_Budair_128kbps", "صلاح البدير"),
}

# number of verses per surah (Hafs)
AYAH_COUNTS = [7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,
112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,
18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,
40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,
4,5,6]
assert len(AYAH_COUNTS) == 114

UA = {"User-Agent": "quran-reels/1.0"}
WAQF_SPACE = re.compile(r"\s+([ۖ-ۜ])")     # space(s) before a Quranic pause mark
CHUNK_CHARS = 170      # long verses are shown in parts of about this many characters


# ---------------------------------------------------------------- network

def http_get(url, binary=False, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else data.decode("utf-8")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


EN_EDITION = "en.sahih"          # Saheeh International
TAFSIR_EDITION = "ar.muyassar"   # التفسير الميسر (King Fahd Complex) - the sourced reflection line


def fetch_verse(surah, ayah):
    j = json.loads(http_get(f"https://api.alquran.cloud/v1/ayah/{surah}:{ayah}/editions/"
                            f"quran-uthmani,{EN_EDITION},{TAFSIR_EDITION}"))
    eds = {e["edition"]["identifier"]: e for e in j["data"]}
    d = eds["quran-uthmani"]
    en = eds.get(EN_EDITION, {}).get("text", "").strip()
    tafsir = eds.get(TAFSIR_EDITION, {}).get("text", "").strip()
    text = d["text"].strip()
    # alquran.cloud prefixes verse 1 of each surah (except 1 and 9) with the basmala
    if ayah == 1 and surah not in (1, 9) and text.startswith("بِسْمِ"):
        text = " ".join(text.split(" ")[4:]).strip()
    # pause (waqf) marks come after a space; attach them to the word before, as in the mushaf,
    # so they sit over its last letter and line wrapping never separates them
    text = WAQF_SPACE.sub(r"\1", text)
    return {"surah": surah, "ayah": ayah, "text": text, "en": en, "tafsir": tafsir,
            "surah_name_ar": d["surah"]["name"], "surah_name_en": d["surah"]["englishName"]}


def fetch_audio(folder, surah, ayah, dest):
    url = f"https://everyayah.com/data/{folder}/{surah:03d}{ayah:03d}.mp3"
    with open(dest, "wb") as f:
        f.write(http_get(url, binary=True))
    return dest


def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path]).decode().strip()
    return float(out)


# ---------------------------------------------------------------- selection

def load_history(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def passage_key(h):
    """History entry -> the passage it came from (a section of a long surah counts as that surah)."""
    if h.get("part_of"):
        return tuple(h["part_of"])
    return (h.get("surah"), h.get("start"), h.get("end"))


def order_candidates(rng, history, pool=None):
    """Passages never used first (shuffled), then the least recently used."""
    pool = PASSAGES if pool is None else pool
    last_used = {}
    for i, h in enumerate(history):
        last_used[passage_key(h)] = i
    unused = [p for p in pool if (p[0], p[1], p[2]) not in last_used]
    used = [p for p in pool if (p[0], p[1], p[2]) in last_used]
    rng.shuffle(unused)
    used.sort(key=lambda p: last_used[(p[0], p[1], p[2])])
    return unused + used


def group_of(entry):
    for p in PASSAGES:
        if p[:3] == passage_key(entry):
            return p[5]
    return None


def daily_candidates(rng, history, today):
    """Fridays: first/last ten verses of Al-Kahf (alternating).
    Other days: rotate groups 1 (virtue) -> 2 (short surah) -> 3 (thematic)."""
    if today.weekday() == 4:                       # Friday
        return order_candidates(rng, history, FRIDAY), "friday"
    last = None
    for h in reversed(history):                    # last non-Friday group used
        if h.get("friday"):
            continue
        last = h.get("group") or group_of(h)
        if last:
            break
    nxt = 1 if last in (None, 3) else last + 1
    weekday = [p for p in PASSAGES if p not in FRIDAY]      # Al-Kahf ten verses are kept for Fridays
    first = order_candidates(rng, history, [p for p in weekday if p[5] == nxt])
    rest = [p for p in order_candidates(rng, history, weekday) if p[5] != nxt]
    # passages found too long on an earlier day go last (still tried, e.g. with a faster reciter)
    too = {tuple(x) for h in history for x in h.get("too_long", [])}
    return prefer_short(first, history, too) + prefer_short(rest, history, too), nxt


_HOT = None


def trending():
    """Passages in the top quarter of trends.json scores (written daily by trends.py from our own
    reels' saves/shares and popular Quran hashtags). Missing or broken file -> no effect."""
    global _HOT
    if _HOT is None:
        _HOT = set()
        try:
            with open(os.path.join(HERE, "trends.json"), encoding="utf-8") as f:
                scores = json.load(f).get("scores", {})
            ranked = [k for k, v in sorted(scores.items(), key=lambda x: -x[1]) if v > 0]
            for k in ranked[:max(1, len(PASSAGES) // 4)]:
                s, rng_ = k.split(":"); a, b = rng_.split("-")
                _HOT.add((int(s), int(a), int(b)))
        except Exception:
            pass
    return _HOT


def prefer_short(lst, history, too=()):
    """Passages found too long on an earlier day last; within the same freshness (never used before / already used), comforting passages first,
    then short ones (6 verses or fewer, likely to fit the 30-second format), then the rest.
    Python's sort is stable, so the random / least-recently-used order is kept inside each band."""
    used = {passage_key(h) for h in history}
    hot = trending()
    return sorted(lst, key=lambda p: (p[:3] in too,
                                      p[:3] in used,
                                      p[:3] not in hot,      # trending (trends.json) first
                                      p[:3] not in COMFORT,
                                      p[2] - p[1] + 1 > 6))


def build_passage(surah, start, end, reciter_key, tmp, max_sec):
    """Download text + audio. Returns (verses, total_sec) or None if too long."""
    folder = RECITERS[reciter_key][0]
    verses, total = [], 0.0
    full_surah = start == 1 and surah not in (1, 9)
    if full_surah:   # open with the basmala (text and audio of 1:1)
        b = fetch_verse(1, 1)
        mp3 = fetch_audio(folder, 1, 1, os.path.join(tmp, f"{reciter_key}_basmala.mp3"))
        b.update(audio=mp3, dur=duration(mp3), marker=False)
        verses.append(b); total += b["dur"]
    for a in range(start, end + 1):
        v = fetch_verse(surah, a)
        mp3 = fetch_audio(folder, surah, a, os.path.join(tmp, f"{reciter_key}_{surah:03d}{a:03d}.mp3"))
        v.update(audio=mp3, dur=duration(mp3), marker=True)
        verses.append(v); total += v["dur"]
        if total > max_sec:
            return None
    return verses, total


def sections_of(surah, start, end):
    """Whole ruku' sections (the traditional thematic divisions of the mushaf) inside start..end.
    Only sections that are complete ruku's are returned, so a section never stops mid-theme."""
    try:
        j = json.loads(http_get(f"https://api.alquran.cloud/v1/surah/{surah}"))
        ruku = {a["numberInSurah"]: a.get("ruku") for a in j["data"]["ayahs"]}
    except Exception as e:
        print(f"  could not read sections of surah {surah}: {e}", file=sys.stderr)
        return []
    if any(ruku.get(a) is None for a in range(start, end + 1)):
        return []
    secs = []
    for a in range(start, end + 1):
        if secs and secs[-1][2] == ruku[a]:
            secs[-1][1] = a
        else:
            secs.append([a, a, ruku[a]])
    whole = [(a, b) for a, b, r in secs if ruku.get(a - 1) != r and ruku.get(b + 1) != r]
    return whole if len(secs) > 1 else []


TOO_LONG = []          # passages tried in this run that did not fit (saved in history via meta.json)


BAD_RECITERS = set()   # reciters whose audio could not be downloaded in this run


def try_build(surah, start, end, rk, tmp, max_sec):
    """build_passage, but a reciter whose audio is missing or unreachable is skipped (and not
    tried again this run) instead of failing the whole reel. Returns (audio_ok, result)."""
    if rk in BAD_RECITERS:
        return False, None
    try:
        return True, build_passage(surah, start, end, rk, tmp, max_sec)
    except RuntimeError as e:
        if "everyayah.com" not in str(e):
            raise                                      # text API failures still fail the run
        BAD_RECITERS.add(rk)
        print(f"::warning title=Reciter audio missing::{rk}: {e}; using another reciter")
        return False, None


def choose(rng, history, reciter_arg, tmp, max_sec, fixed=None, today=None):
    """Pick passage + reciter. If the recitation is longer than max_sec, try another reciter;
    then the passage's complete ruku' sections (next unused section first); then the next passage.
    Returns (passage, title, reciter, verses, seconds, section or None)."""
    keys = list(RECITERS)
    candidates = [fixed] if fixed else daily_candidates(rng, history, today)[0]
    for p in candidates[:60]:
        surah, start, end = p[0], p[1], p[2]
        title = p[3] if len(p) > 3 else ""
        if reciter_arg != "random":
            order = [reciter_arg]
        else:
            order = [k for k in keys if k not in BAD_RECITERS]; rng.shuffle(order)
        tried = []                                     # reciters whose audio downloaded
        for rk in order:
            if reciter_arg == "random" and not fixed and len(tried) >= 2:
                break                                  # long passages: one retry, then move on
            ok, res = try_build(surah, start, end, rk, tmp, max_sec)
            if not ok:
                continue
            tried.append(rk)
            if res:
                return p, title, rk, res[0], res[1], None
            print(f"  {surah}:{start}-{end} too long with {rk}, trying another", file=sys.stderr)
        order = tried
        secs = sections_of(surah, start, end)
        if not secs:
            TOO_LONG.append(list(p[:3]))
            continue
        prev = [(h["start"], h["end"]) for h in history
                if h.get("part_of") and tuple(h["part_of"]) == tuple(p[:3])]
        k = (secs.index(prev[-1]) + 1) % len(secs) if prev and prev[-1] in secs else 0
        for a, b in secs[k:] + secs[:k]:               # continue where the last section left off
            for rk in order:
                ok, res = try_build(surah, a, b, rk, tmp, max_sec)
                if res:
                    return p, title, rk, res[0], res[1], (a, b)
                print(f"  section {surah}:{a}-{b} too long with {rk}", file=sys.stderr)
        TOO_LONG.append(list(p[:3]))
    raise RuntimeError("no passage fits within the time limit")


# ---------------------------------------------------------------- drawing

def font(name, size):
    return ImageFont.truetype(os.path.join(HERE, "fonts", name), size)


def text_w(draw, s, f):
    b = draw.textbbox((0, 0), s, font=f, direction="rtl", language="ar")
    return b[2] - b[0]


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(draw, t, f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text, fname, box_w, box_h, start=92, minimum=46, spacing=1.8):
    size = start
    while size >= minimum:
        f = font(fname, size)
        lines = wrap(draw, text, f, box_w)
        lh = int(size * spacing)
        if len(lines) * lh <= box_h:
            return f, lines, lh
        size -= 4
    f = font(fname, minimum)
    return f, wrap(draw, text, f, box_w), int(minimum * spacing)


def draw_centered(draw, y, s, f, fill, rtl=True, shadow=True):
    kw = {"direction": "rtl", "language": "ar"} if rtl else {}
    b = draw.textbbox((0, 0), s, font=f, **kw)
    x = (W - (b[2] - b[0])) // 2 - b[0]
    if shadow:
        draw.text((x + 3, y + 3), s, font=f, fill=(0, 0, 0, 170), **kw)
    draw.text((x, y), s, font=f, fill=fill, **kw)



IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
VID_EXT = (".mp4", ".mov", ".m4v", ".webm")


def is_video(path):
    return path.lower().endswith(VID_EXT)


def pick_photo(photos, history, today=None):
    """Full-cycle rotation: no background (image or video clip) is used a second time until every
    background in the library has been used once; then the cycle starts again in the same
    least-recently-used order. Backgrounds added mid-cycle join the current cycle; removed ones
    are ignored."""
    names = {os.path.basename(p) for p in photos}
    last, cycle = {}, set()
    for i, h in enumerate(history):
        bg = h.get("background", "")
        if not bg.startswith(("photo: ", "video: ")):
            continue
        name = bg[7:]
        last[name] = i
        if name not in names:
            continue
        if not (names - cycle):                     # every background used: a new cycle starts
            cycle = set()
        cycle.add(name)
    pool = [p for p in photos if os.path.basename(p) not in cycle] or photos
    return min(pool, key=lambda p: (last.get(os.path.basename(p), -1), os.path.basename(p)))


def theme_for(path):
    """White text on dark images, dark text on light ones (judged on the verse area)."""
    im = Image.open(path).convert("L")
    w, h = im.size
    centre = im.crop((int(w * 0.1), int(h * 0.25), int(w * 0.9), int(h * 0.85)))
    mean = sum(i * c for i, c in enumerate(centre.histogram())) / (centre.width * centre.height)
    theme = dict(bgstyles.DARK_TEXT if mean > 165 else bgstyles.LIGHT_TEXT)
    theme["light_bg"] = mean > 165
    return theme

def video_still(path, dest):
    """Average of three frames of a clip (¼, ½, ¾ through), used to judge text colour."""
    d = duration(path)
    frames = []
    for k, frac in enumerate((0.25, 0.5, 0.75)):
        fp = f"{dest}.{k}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{d * frac:.2f}", "-i", path,
                        "-frames:v", "1", fp], check=True)
        frames.append(Image.open(fp).convert("RGB"))
    im = frames[0]
    for k, f in enumerate(frames[1:], start=2):
        im = Image.blend(im, f.resize(im.size), 1 / k)
    im.save(dest)
    return dest


def make_photo_background(path, dest):
    im = Image.open(path).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    Image.alpha_composite(im.convert("RGBA"), shade).convert("RGB").save(dest, quality=95)
    return dest


def to_ar_digits(n):
    return str(n).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def split_long(text, limit=CHUNK_CHARS):
    """Split a long verse into parts of roughly `limit` characters at word breaks."""
    if len(text) <= limit * 1.3:
        return [text]
    words, parts, cur = text.split(), [], ""
    n_parts = math.ceil(len(text) / limit)
    target = len(text) / n_parts
    for w in words:
        if cur and len(cur) + 1 + len(w) > target and len(parts) < n_parts - 1:
            parts.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        parts.append(cur)
    return parts


def split_words(text, n):
    """Split text into n parts of about equal length at word breaks (English shown under a long
    verse that is displayed in n parts); prefers to break after punctuation."""
    if n <= 1 or not text:
        return [text] + [""] * (n - 1) if n > 1 else [text]
    words = text.split()
    target = len(text) / n
    parts, cur = [], ""
    for i, w in enumerate(words):
        cur = (cur + " " + w).strip()
        left = len(words) - i - 1
        if len(parts) < n - 1 and left >= (n - 1 - len(parts)):
            if len(cur) >= target or (len(cur) >= target * 0.7 and cur[-1] in ",;:.!?"):
                parts.append(cur); cur = ""
    parts.append(cur)
    while len(parts) < n:
        parts.append("")
    return parts


def segments_from(verses):
    """One screen per verse; long verses split into parts timed by length.
    Each screen carries its share of the English translation."""
    segs, t = [], 0.0
    for v in verses:
        parts = split_long(v["text"])
        en_parts = split_words(v.get("en", ""), len(parts))
        total_chars = sum(len(p) for p in parts)
        for i, p in enumerate(parts):
            d = v["dur"] * len(p) / total_chars
            last = i == len(parts) - 1
            label = p
            if v["marker"] and last:
                label = f"{p} ﴿{to_ar_digits(v['ayah'])}﴾"
            en = en_parts[i]
            if en and v["marker"] and last:
                en = f"{en} ({v['ayah']})"
            segs.append({"text": label, "en": en, "start": t, "end": t + d, "verse": v})
            t += d
    return segs


def _soft_shadow(layer, color, radius=10, strength=170):
    a = layer.split()[3].filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, v * strength // 100))
    sh = Image.new("RGBA", layer.size, color + (0,))
    sh.putalpha(a)
    return Image.alpha_composite(sh, layer)


def make_static_overlay(header, title, reciter_ar, handle, theme, dest):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gold = (238, 206, 128, 255)
    hf = font("Amiri-Bold.ttf", 54)
    hw = text_w(d, header, hf) + 90
    d.rounded_rectangle([(W - hw) // 2, 120, (W + hw) // 2, 218], radius=49, fill=(0, 0, 0, 140))
    draw_centered(d, 127, header, hf, gold, shadow=False)
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t = ImageDraw.Draw(txt)
    draw_centered(t, 232, "بصوت القارئ " + reciter_ar, font("Amiri-Regular.ttf", 40), theme["sub"] + (255,), shadow=False)
    if title:
        draw_centered(t, 1700, title, font("Amiri-Bold.ttf", 44), theme["title"] + (255,), shadow=False)
    if handle:
        draw_centered(t, H - 130, handle, font("Amiri-Regular.ttf", 34), theme["sub"] + (230,), rtl=False, shadow=False)
    txt = _soft_shadow(txt, theme["shadow"], 6, 150)
    Image.alpha_composite(img, txt).save(dest)
    return dest


def wrap_ltr(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        b = draw.textbbox((0, 0), t, font=f)
        if b[2] - b[0] <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_english(draw, text, box_w, box_h, start=42, minimum=28, spacing=1.32):
    size = start
    while True:
        f = font("Amiri-Regular.ttf", size)
        lines = wrap_ltr(draw, text, f, box_w)
        lh = int(size * spacing)
        if len(lines) * lh <= box_h or size <= minimum:
            return f, lines, lh
        size -= 2


VERSE_TOP, VERSE_BOTTOM = 480, 1650     # the verse area (inside the soft glow behind the text)
EN_GAP = 46                             # space between the Arabic and the English


def make_text_overlay(text, theme, dest, en=""):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    area = VERSE_BOTTOM - VERSE_TOP
    en_lines, en_lh, ef = [], 0, None
    if en:
        # English: at most ~30% of the area, smaller and softer than the verse
        ef, en_lines, en_lh = fit_english(d, en, W - 220, int(area * 0.30))
    en_h = len(en_lines) * en_lh
    ar_box = area - (en_h + EN_GAP if en_lines else 0)
    # Amiri Quran draws pause marks (ۖ ۗ ۚ ...) about one line-height above the word, so lines need
    # extra spacing or each mark lands under the line above it
    f, lines, lh = fit_text(d, text, "AmiriQuran.ttf", W - 260, ar_box, spacing=2.3)
    ar_h = len(lines) * lh
    block = ar_h + (EN_GAP + en_h if en_lines else 0)
    top = VERSE_TOP + (area - block) // 2
    for i, ln in enumerate(lines):
        draw_centered(d, top + i * lh, ln, f, theme["verse"] + (255,), shadow=False)
    y = top + ar_h + EN_GAP
    for i, ln in enumerate(en_lines):
        draw_centered(d, y + i * en_lh, ln, ef, theme["sub"] + (240,), rtl=False, shadow=False)
    _soft_shadow(img, theme["shadow"], 14, 230).save(dest)
    return dest


# ---------------------------------------------------------------- render

def render(verses, title, bg, theme, reciter_ar, handle, out_mp4, tmp, animate=False, video=False):
    real = [v for v in verses if v["marker"]]
    a1, a2 = real[0]["ayah"], real[-1]["ayah"]
    rng_txt = to_ar_digits(a1) if a1 == a2 else f"{to_ar_digits(a1)}–{to_ar_digits(a2)}"
    header = f"{real[0]['surah_name_ar']} · {rng_txt}"

    # everyayah's verse files often run on into the reciter's in-breath for the next verse;
    # at the end of a reel that breath is heard on its own, so finish exactly on the last word
    last_v = verses[-1]
    clean = os.path.join(tmp, "last_verse_clean.mp3")
    if os.environ.get("TRIM_DEBUG"):
        print("TRIM PROFILE (t dB harm tilt sib)\n" + audio_trim.profile(last_v["audio"], 3.0))
    try:
        cut = audio_trim.trim_end(last_v["audio"], clean)
    except Exception as e:                      # never lose a reel over this: keep the original
        print(f"::warning title=End trim skipped::{e}")
        cut = None
    if cut:
        print(f"Last verse trimmed {last_v['dur']:.2f}s -> {cut:.2f}s (reciter's breath removed)")
        last_v.update(audio=clean, dur=cut)

    # join the verse files without the dead gap left where a reverberant reciter's echo is cut
    # off at the end of each file; the on-screen text follows the joined timing
    joined = os.path.join(tmp, "joined.wav")
    try:
        spans = audio_trim.join_verses([v["audio"] for v in verses], joined)
        for v, d in zip(verses, spans):
            v["dur"] = d
        src = ["-i", joined]
    except Exception as e:                      # never lose a reel over this: plain concat
        print(f"::warning title=Smooth verse join skipped::{e}")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for v in verses:
                f.write(f"file '{v['audio']}'\n")
        src = ["-f", "concat", "-safe", "0", "-i", lst]
    audio = os.path.join(tmp, "audio.m4a")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *src,
                    "-af", "apad=pad_dur=1.2", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", audio],
                   check=True)
    total = duration(audio)
    segs = segments_from(verses)

    if animate or video:
        if video:
            # real video clip (already a seamless vertical loop from sync_backgrounds.py), repeated
            bgvid = bg
        else:
            # photo/AI image -> gentle looping motion (dust in the light, breathing light, slow drift)
            # render one seamless loop and repeat it (much faster than rendering every second)
            bgvid = motion.make_motion_video(bg, motion.LOOP, os.path.join(tmp, "bg.mp4"))
        # soft dark glow behind the verse area so text stays readable on busy images
        scrim = Image.new("L", (W, H), 0)
        ImageDraw.Draw(scrim).rounded_rectangle([40, 470, W - 40, 1660], radius=200, fill=150)
        scrim = scrim.filter(ImageFilter.GaussianBlur(90))
        scrim_rgb = (250, 244, 232) if theme.get("light_bg") else (0, 0, 0)
        sc = Image.new("RGBA", (W, H), scrim_rgb + (0,)); sc.putalpha(scrim)
        scrim_png = os.path.join(tmp, "scrim.png"); sc.save(scrim_png)
        inputs = ["-stream_loop", "-1", "-i", bgvid, "-loop", "1", "-framerate", str(FPS), "-i", scrim_png]
        grade = ("eq=saturation=1.03" if theme.get("light_bg")
                 else "eq=brightness=-0.04:saturation=1.05,vignette=angle=PI/4.5")
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
               if video else "")
        filt = [f"[0:v]{fit}{grade},setsar=1[bg0]",
                "[bg0][1:v]overlay=0:0[bg]"]
    else:
        inputs = ["-loop", "1", "-framerate", str(FPS), "-i", bg]
        filt = [f"[0:v]scale={int(W*1.08)}:-2,"
                f"crop={W}:{H}:'(in_w-{W})/2+sin(t/10)*18':'(in_h-{H})/2+cos(t/12)*12',setsar=1[bg]"]
    last = "bg"
    base = 2 if (animate or video) else 1          # index of the first verse overlay input
    for i, s in enumerate(segs):
        ov = make_text_overlay(s["text"], theme, os.path.join(tmp, f"ov{i}.png"), s.get("en", ""))
        st = s["start"]
        en = total if i == len(segs) - 1 else s["end"]
        dur = max(en - st, 0.1)
        fade = min(0.35, dur / 4)
        # each verse screen exists only for its own few seconds (fast even for long passages)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", ov]
        fade_in = "" if i == 0 else f"fade=in:st=0:d={fade:.2f}:alpha=1,"   # frame 1 already shows text
        filt.append(f"[{i+base}:v]format=rgba,{fade_in}"
                    f"fade=out:st={dur-fade:.3f}:d={fade:.2f}:alpha=1,"
                    f"setpts=PTS-STARTPTS+{st:.3f}/TB[o{i}]")
        filt.append(f"[{last}][o{i}]overlay=0:0:eof_action=pass[v{i}]")
        last = f"v{i}"
    static = make_static_overlay(header, title, reciter_ar, handle, theme, os.path.join(tmp, "static.png"))
    inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.3f}", "-i", static]
    filt.append(f"[{last}][{len(segs)+base}:v]overlay=0:0,"
                f"fade=out:st={total-0.8:.3f}:d=0.8,format=yuv420p[vout]")   # no fade-in: first frame = cover
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-i", audio,
           "-filter_complex", ";".join(filt),
           "-map", "[vout]", "-map", f"{len(segs)+base+1}:a",
           "-t", f"{total:.3f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high", "-level", "4.1",
           "-maxrate", "10M", "-bufsize", "20M", "-g", str(FPS * 2),      # Instagram: capped bitrate, keyframe every 2 s
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True)
    return total, cover_ms(segs)


def cover_ms(segs):
    """Cover frame (Instagram thumb_offset): the first real verse fully on screen, not the basmala."""
    for s in segs:
        v = s["verse"]
        if not v["marker"] or (v["surah"] == 1 and v["ayah"] == 1 and len(segs) > 1):
            continue
        return int(1000 * (s["start"] + min(1.5, (s["end"] - s["start"]) / 2)))
    return 2500


GRADE_ICON = {"h": "📜", "a": "📜", "q": "🌿", "s": "🖋️"}   # see passages.py


CAPTION_MAX = 2100     # Instagram allows 2,200 characters; keep a margin
HANDLE = os.environ.get("REEL_HANDLE", "")    # e.g. @your_account (set the HANDLE repository variable)
REEL_TZ = os.environ.get("REEL_TZ", "Asia/Baghdad")   # IANA time zone that decides "today" (Fridays, slots)

# opening line (the first line is all most people read before "more")
HOOKS = {
    "comfort": ["🤍 رسالة من الله لقلبك اليوم | A message for your heart today",
                "🤍 إن ضاق صدرك… فاسمع هذه الآيات | If your heart feels heavy, listen to this",
                "🤍 توقّف لحظة… واستمع بقلبك | Pause for a moment and listen with your heart",
                "🤍 آياتٌ تطمئن بها القلوب | Verses that bring peace to the heart",
                "🤍 لا تمرّ عليها سريعًا | Don't scroll past this one"],
    "dua": ["🤲 دعاءٌ من القرآن… ردّده معنا | A du'a from the Quran, say it with us",
            "🤲 أجمل الدعاء ما علّمنا الله إياه | The best du'a is the one Allah taught us"],
    "friday": ["🕌 جمعة مباركة | Jumu'ah Mubarak"],
    "morning": ["🌅 آيةٌ تبدأ بها يومك | A verse to start your day",
                "🌅 صباحك نورٌ بكلام الله | Begin your morning with the words of Allah",
                "🌅 قبل أن يبدأ يومك… استمع | Before your day begins, listen"],
}

THEME_TAG = {1: "#islamicreminders", 2: "#quranrecitation", 3: "#تدبر"}


def surah_tag(surah, name_en, start, end):
    """English surah hashtag, e.g. #surahmulk, #ayatulkursi."""
    if (surah, start, end) == (2, 255, 255):
        return "#ayatulkursi"
    n = name_en.lower()
    n = re.sub(r"^(aal-i-|al-|an-|ar-|as-|ash-|at-|az-|ad-|adh-)", "", n)
    n = re.sub(r"[^a-z]", "", n)
    n = re.sub(r"aa+", "a", n).replace("ee", "i").replace("oo", "u")
    return f"#surah{n}"


def hashtags_for(verses, group, friday, is_dua):
    """Instagram allows 5 hashtags: broad, Arabic broad, surah, theme, #explore."""
    real = [v for v in verses if v["marker"]]
    v0 = real[0]
    theme = ("#jumuah" if friday else "#dua" if is_dua else THEME_TAG.get(group, "#islamicreminders"))
    return " ".join(["#quran", "#القرآن_الكريم",
                     surah_tag(v0["surah"], v0["surah_name_en"], v0["ayah"], real[-1]["ayah"]),
                     theme, "#explore"])


def tafsir_excerpt(verses, limit=280):
    """First sentence(s) of التفسير الميسر for the passage, never cut mid-word."""
    for v in verses:
        t = (v.get("tafsir") or "").strip() if v["marker"] else ""
        if not t:
            continue
        sents = re.split(r"(?<=[.!؟])\s+", t)
        out = ""
        for s in sents:
            if out and len(out) + 1 + len(s) > limit:
                break
            out = (out + " " + s).strip()
        if len(out) > limit + 60:                    # one very long sentence
            cut = out[:limit]
            k = max(cut.rfind("،"), cut.rfind(" "))
            out = cut[:k].rstrip("،, ") + " …"
        return out
    return ""


def caption(verses, title, reciter_ar, hashtags, virtue=None, grade=None,
            hook="", handle=HANDLE, action=None):
    real = [v for v in verses if v["marker"]]
    v0, v1 = real[0], real[-1]
    rng_txt = f"{v0['ayah']}" if v0["ayah"] == v1["ayah"] else f"{v0['ayah']}-{v1['ayah']}"
    ar = " ".join(f"{v['text']} ﴿{to_ar_digits(v['ayah'])}﴾" for v in real)
    en = " ".join(f"{v['en']} ({v['ayah']})" for v in real if v.get("en"))
    reflection = tafsir_excerpt(verses)

    def build(ar, en, reflection):
        top = f"{hook}\n\n" if hook else ""
        if title:
            top += f"✨ {title}\n"
        if virtue:
            top += f"{GRADE_ICON.get(grade, '📜')} {virtue}\n"
        if reflection:
            top += f"💭 {reflection}\n— التفسير الميسر (مجمع الملك فهد)\n"
        text = f"{top}\n{ar}\n"
        if en:
            text += f"\n🌍 {en}\n— Saheeh International\n"
        text += (f"\n📖 {v0['surah_name_ar']} ({v0['surah_name_en']}) — الآيات {rng_txt}\n"
                 f"🎙️ بصوت القارئ {reciter_ar}\n\n"
                 + (f"✅ عمل اليوم: {action[0]}\nToday: {action[1]}\n\n" if action else "")
                 + f"🤲 اكتب «آمين» في التعليقات، وشاركها لتكون صدقة جارية لك\n"
                 f"Comment \"Ameen\" and share it as sadaqah jariyah 🤍\n"
                 + (f"➕ Follow {handle} for daily verses\n" if handle else "")
                 + f"\n{hashtags}\n")
        return text

    # keep within Instagram's limit: drop the English first, then shorten the Arabic, then the reflection
    text = build(ar, en, reflection)
    if len(text) > CAPTION_MAX:
        text = build(ar, "", reflection)
    while len(text) > CAPTION_MAX and len(ar) > 200:
        ar = ar[:int(len(ar) * 0.8)].rsplit(" ", 1)[0] + " …"
        text = build(ar, "", reflection)
    if len(text) > CAPTION_MAX:
        text = build(ar, "", "")
    return text


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--reciter", default="random", help="key from RECITERS, or 'random'")
    ap.add_argument("--surah", type=int); ap.add_argument("--start", type=int); ap.add_argument("--end", type=int)
    ap.add_argument("--max-sec", type=float, default=30,
                    help="longest video; longer passages are posted one complete section at a time")
    ap.add_argument("--friday-max-sec", type=float, default=175,
                    help="Fridays: the ten verses of Al-Kahf are kept whole (Instagram only if > 90 s)")
    ap.add_argument("--verses", default="", help="a specific passage as SURAH:START-END, e.g. 73:1-20")
    ap.add_argument("--date", default=None, help="pretend today is YYYY-MM-DD (testing)")
    ap.add_argument("--slot", default="evening", choices=["morning", "evening"],
                    help="which of the day's reels this is (morning 08:00 / evening 18:00 local time)")
    ap.add_argument("--handle", default="", help="text shown at the bottom, e.g. @myaccount")
    ap.add_argument("--hashtags", default="",
                    help="override the 5 automatic hashtags (Instagram allows at most 5)")
    ap.add_argument("--history", default=os.path.join(HERE, "history.json"))
    ap.add_argument("--seed", default=None)
    ap.add_argument("--bg-style", default="", help="force a drawn style instead of photos: " + ", ".join(bgstyles.ALL_STYLES))
    ap.add_argument("--bg-file", default="", help="force one file from backgrounds/ (testing)")
    args = ap.parse_args()

    rng = random.Random(args.seed or time.time_ns())
    if args.reciter != "random" and args.reciter not in RECITERS:
        sys.exit(f"unknown reciter {args.reciter}; choose from {', '.join(RECITERS)}")

    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="qr_")
    try:
        history = load_history(args.history)
        fixed = None
        if args.verses:
            sv, _, rg = args.verses.partition(":")
            args.surah = int(sv)
            if rg:
                a, _, b = rg.partition("-")
                args.start, args.end = int(a), int(b or a)
        if args.surah:
            st = args.start or 1
            en = args.end or (st if args.start else AYAH_COUNTS[args.surah - 1])
            match = [p for p in PASSAGES if p[:3] == (args.surah, st, en)]
            fixed = match[0] if match else (args.surah, st, en, "", None, None, None)
        today = (datetime.date.fromisoformat(args.date) if args.date
                 else datetime.datetime.now(ZoneInfo(REEL_TZ)).date())
        friday = today.weekday() == 4 and not args.surah
        max_sec = args.friday_max_sec if friday else args.max_sec
        p, title, rk, verses, _, section = choose(rng, history, args.reciter, tmp, max_sec, fixed, today)
        reciter_ar = RECITERS[rk][1]
        virtue = p[4] if len(p) > 4 else None
        grade = p[6] if len(p) > 6 else None
        if section:
            # only part of the passage: say so, and drop the virtue (it is cited for the whole passage)
            title, virtue = (f"من {title}" if title else ""), None

        bg_dir = os.path.join(HERE, "backgrounds")
        photos = [os.path.join(bg_dir, f) for f in sorted(os.listdir(bg_dir))
                  if f.lower().endswith(IMG_EXT + VID_EXT)] if os.path.isdir(bg_dir) else []
        if args.bg_file:
            photos = [os.path.join(bg_dir, args.bg_file)]
        animate, video, bg_style = False, False, None
        if photos and not args.bg_style:
            bgfile = pick_photo(photos, history, today)
            if is_video(bgfile):
                theme = theme_for(video_still(bgfile, os.path.join(tmp, "still.png")))
                bg_style, video = "video: " + os.path.basename(bgfile), True
            else:
                theme = theme_for(bgfile)
                bg_style, animate = "photo: " + os.path.basename(bgfile), True
        else:
            bgfile = os.path.join(tmp, "bg.jpg")
            bg_style, theme = bgstyles.make_themed(rng, bgfile, args.bg_style or None)

        mp4 = os.path.join(args.out, "reel.mp4")
        total, cover = render(verses, title, bgfile, theme, reciter_ar, args.handle, mp4, tmp, animate, video)
        group = p[5] if len(p) > 5 else None
        is_dua = "دعاء" in (p[3] if len(p) > 3 else "")
        kind = ("friday" if friday else "dua" if is_dua
                else "morning" if args.slot == "morning" and rng.random() < 0.5 else "comfort")
        hook = rng.choice(HOOKS[kind])
        tags = args.hashtags or hashtags_for(verses, group, friday, is_dua)
        with open(os.path.join(args.out, "caption.txt"), "w", encoding="utf-8") as f:
            act = actions.action_for(p, friday)
            f.write(caption(verses, title, reciter_ar, tags, virtue, grade, hook=hook,
                            handle=args.handle or HANDLE, action=act))
        start, end = section or (p[1], p[2])
        meta = {"date": today.isoformat(), "surah": p[0], "start": start, "end": end,
                "group": p[5] if len(p) > 5 else None, "friday": friday,
                "title": title, "reciter": rk, "background": bg_style, "seconds": round(total, 2),
                "cover_ms": cover, "fixed": bool(args.surah), "action": act[0],
                "slot": "evening" if friday else args.slot}
        if section:
            meta["part_of"] = list(p[:3])
        if TOO_LONG and not args.surah:
            meta["too_long"] = TOO_LONG
        # history.json is written by publish.py, only after something was actually posted
        with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(json.dumps(meta, ensure_ascii=False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
