"""
Which verses are doing well: our own reels' results + what is popular on Instagram hashtags.
Writes trends.json, which generate.py reads to put "trending" passages first (within the usual
group rotation, freshness and full-cycle background rotation; nothing else changes).

  1. Own performance: every reel on our Instagram account, matched to history.json by its link,
     with views / reach / saves / shares / likes / comments (Instagram insights).
  2. Hashtag trends: the top posts of a fixed set of Quran hashtags (Instagram Hashtag Search).
     Captions are read for surah names, verse references ("البقرة 255", "2:255") and well-known
     verse names ("آية الكرسي"). Instagram allows 30 unique hashtags per 7 days; we use 8.
     Needs the "Instagram Public Content Access" feature on the Meta app; without it this part is
     skipped with a warning and only our own results are used.

Each part fails on its own: a missing permission never stops the reel.

Env: META_PAGE_TOKEN, IG_USER_ID, FB_PAGE_ID (same secrets as publish.py), TREND_TAGS (optional).
TikTok is not included: it has no official API for reading other accounts' public posts.
"""
import datetime, json, math, os, re, sys

from passages import PASSAGES
from publish import GRAPH, call, page_token_from

TAGS = [t.strip().lstrip("#") for t in os.environ.get("TREND_TAGS", "").split(",") if t.strip()] or [
    "قرآن", "القرآن_الكريم", "تلاوة", "تلاوات", "quran", "quranrecitation", "تلاوة_خاشعة", "ايات_قرآنية"]

SURAHS = """الفاتحة البقرة آل_عمران النساء المائدة الأنعام الأعراف الأنفال التوبة يونس هود يوسف الرعد
إبراهيم الحجر النحل الإسراء الكهف مريم طه الأنبياء الحج المؤمنون النور الفرقان الشعراء النمل القصص
العنكبوت الروم لقمان السجدة الأحزاب سبأ فاطر يس الصافات ص الزمر غافر فصلت الشورى الزخرف الدخان
الجاثية الأحقاف محمد الفتح الحجرات ق الذاريات الطور النجم القمر الرحمن الواقعة الحديد المجادلة
الحشر الممتحنة الصف الجمعة المنافقون التغابن الطلاق التحريم الملك القلم الحاقة المعارج نوح الجن
المزمل المدثر القيامة الإنسان المرسلات النبأ النازعات عبس التكوير الانفطار المطففين الانشقاق
البروج الطارق الأعلى الغاشية الفجر البلد الشمس الليل الضحى الشرح التين العلق القدر البينة الزلزلة
العاديات القارعة التكاثر العصر الهمزة الفيل قريش الماعون الكوثر الكافرون النصر المسد الإخلاص
الفلق الناس""".split()
assert len(SURAHS) == 114

# well-known names of single verses / passages -> (surah, first, last)
NAMED = {"اية الكرسي": (2, 255, 255), "خواتيم البقره": (2, 285, 286), "اخر البقره": (2, 285, 286),
         "المعوذتين": (113, 1, 5), "المعوذات": (112, 1, 4)}

TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def norm(s):
    s = TASHKEEL.sub("", s or "").replace("_", " ").replace("#", " ")
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
SURAH_NORM = [norm(n) for n in SURAHS]
# a surah is only counted when written as "سورة X" or "X <verse number>", so that ordinary
# words that are also surah names (النور، الفجر، الليل ...) are not miscounted
SURAH_RE = re.compile(r"(سوره ?)?(" + "|".join(sorted(map(re.escape, SURAH_NORM), key=len, reverse=True))
                      + r")(?![ء-ي])(?:\s*[:(\-–]?\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?)?")
NUM_RE = re.compile(r"(?<!\d)(\d{1,3})\s*:\s*(\d{1,3})(?!\d)")


def refs_in(caption):
    """Caption -> list of (surah, verse or None)."""
    t = norm(caption).translate(AR_DIGITS)
    out = []
    for m in SURAH_RE.finditer(t):
        has_word, name, verse, last = m.group(1), m.group(2), m.group(3), m.group(4)
        if not has_word and not verse:
            continue
        s = SURAH_NORM.index(name) + 1
        if verse and last and 0 <= int(last) - int(verse) < 50:
            out += [(s, v) for v in range(int(verse), int(last) + 1)]
        else:
            out.append((s, int(verse) if verse else None))
    for m in NUM_RE.finditer(t):
        s, v = int(m.group(1)), int(m.group(2))
        if 1 <= s <= 114 and v >= 1:
            out.append((s, v))
    for name, (s, a, b) in NAMED.items():
        if norm(name) in t:
            out += [(s, v) for v in range(a, b + 1)]
    return list(dict.fromkeys(out))


def key(p):
    return f"{p[0]}:{p[1]}-{p[2]}"


# ---------------------------------------------------------------- own reels

def own_results(token, ig_id, history):
    by_link = {}
    for h in history:
        link = (h.get("posted") or {}).get("instagram")
        if link:
            pk = tuple(h["part_of"]) if h.get("part_of") else (h["surah"], h["start"], h["end"])
            by_link[link.rstrip("/").split("/")[-1]] = pk
    res, url = {}, f"{GRAPH}/{ig_id}/media"
    params = {"fields": "id,permalink,like_count,comments_count,media_product_type", "limit": 50,
              "access_token": token}
    pages = 0
    while url and pages < 6:
        j = call("GET", url, params); params = None; pages += 1
        for m in j.get("data", []):
            code = (m.get("permalink") or "").rstrip("/").split("/")[-1]
            pk = by_link.get(code)
            if not pk:
                continue
            stats = {"likes": m.get("like_count", 0), "comments": m.get("comments_count", 0)}
            for metrics in ("views,reach,saved,shares", "reach,saved,shares"):
                try:
                    ins = call("GET", f"{GRAPH}/{m['id']}/insights", {"metric": metrics, "access_token": token})
                    for d in ins.get("data", []):
                        stats[d["name"]] = (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value", 0))
                    break
                except RuntimeError as e:
                    err = str(e)
            else:
                print(f"::warning title=Reel insights unavailable::{err[:200]}")
            r = res.setdefault(f"{pk[0]}:{pk[1]}-{pk[2]}", {"posts": 0})
            r["posts"] += 1
            for k, v in stats.items():
                r[k] = r.get(k, 0) + (v or 0)
        url = (j.get("paging") or {}).get("next")
    return res


def own_score(r):
    """Saves and shares mean people want the verse again or for others: they weigh most."""
    reach = r.get("reach") or r.get("views") or 0
    act = 4 * r.get("saved", 0) + 4 * r.get("shares", 0) + r.get("likes", 0) + 2 * r.get("comments", 0)
    if not reach:      # no insights permission: likes and comments per post only
        return act / max(r.get("posts", 1), 1)
    return (act / reach) if reach >= 50 else 0.0      # too few viewers to judge


# ---------------------------------------------------------------- hashtags

def hashtag_trends(token, ig_id):
    surahs, verses, read, used = {}, {}, 0, []
    for tag in TAGS:
        try:
            hid = call("GET", f"{GRAPH}/ig_hashtag_search", {"user_id": ig_id, "q": tag, "access_token": token})["data"][0]["id"]
            j = call("GET", f"{GRAPH}/{hid}/top_media", {"user_id": ig_id, "limit": 50, "access_token": token,
                                                        "fields": "caption,like_count,comments_count,media_type"})
        except Exception as e:
            print(f"::warning title=Hashtag #{tag} skipped::{str(e)[:300]}")
            if "permission" in str(e).lower() or "(#10)" in str(e) or "OAuth" in str(e):
                break                                  # no access at all: don't spend the rest
            continue
        used.append(tag)
        for m in j.get("data", []):
            read += 1
            # log scale: one viral post must not outweigh many popular ones
            w = 1 + math.log1p((m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0))
            for s, v in refs_in(m.get("caption")):
                if v:                                  # a named verse counts for that verse only
                    verses[f"{s}:{v}"] = verses.get(f"{s}:{v}", 0) + w
                else:                                  # "سورة X" counts for the surah
                    surahs[s] = surahs.get(s, 0) + w
    return {"tags": used, "posts_read": read, "surahs": surahs, "verses": verses}


def tag_score(p, tags):
    s, a, b = p[0], p[1], p[2]
    sw = tags["surahs"].get(s, 0) + tags["surahs"].get(str(s), 0)
    vw = sum(tags["verses"].get(f"{s}:{v}", 0) for v in range(a, b + 1))
    whole = a == 1 and str(p[3]).startswith("سورة")      # a surah in full gets the surah's weight
    return vw + (sw if whole else 0.3 * sw)


# ---------------------------------------------------------------- main

def main():
    token, ig_id = os.environ.get("META_PAGE_TOKEN"), os.environ.get("IG_USER_ID")
    if not token or not ig_id:
        print("::warning title=Trends skipped::META_PAGE_TOKEN / IG_USER_ID secrets are not set")
        return 0
    token = page_token_from(token, os.environ.get("FB_PAGE_ID"))
    with open("history.json", encoding="utf-8") as f:
        history = json.load(f)

    try:
        own = own_results(token, ig_id, history)
    except Exception as e:
        print(f"::warning title=Own reel results skipped::{str(e)[:300]}"); own = {}
    try:
        tags = hashtag_trends(token, ig_id)
    except Exception as e:
        print(f"::warning title=Hashtag trends skipped::{str(e)[:300]}"); tags = {"tags": [], "posts_read": 0, "surahs": {}, "verses": {}}

    raw_tag = {key(p): tag_score(p, tags) for p in PASSAGES}
    raw_own = {k: own_score(r) for k, r in own.items()}
    mt, mo = max(raw_tag.values(), default=0) or 1, max(raw_own.values(), default=0) or 1
    scores = {}
    for p in PASSAGES:
        k = key(p)
        s = 0.6 * raw_tag[k] / mt + 0.4 * raw_own.get(k, 0) / mo
        if s > 0:
            scores[k] = round(s, 4)

    out = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
           "scores": dict(sorted(scores.items(), key=lambda x: -x[1])),
           "own": own,
           "hashtags": {"tags": tags["tags"], "posts_read": tags["posts_read"],
                        "top_surahs": dict(sorted(((str(k), v) for k, v in tags["surahs"].items()), key=lambda x: -x[1])[:20]),
                        "top_verses": dict(sorted(tags["verses"].items(), key=lambda x: -x[1])[:30])}}
    with open("trends.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    top = list(out["scores"].items())[:10]
    print(f"own reels matched: {sum(r['posts'] for r in own.values())}; hashtag posts read: {tags['posts_read']} "
          f"from {len(tags['tags'])} tags")
    print("top passages:", ", ".join(f"{k} ({v})" for k, v in top) or "none yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
