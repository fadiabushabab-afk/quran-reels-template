"""«عمل اليوم»: one small, concrete action for the day, matched to the passage.

Idea from the Itqan community (community.itqan.dev/d/960): instead of only asking for a
comment, give the viewer a practical task tied to the verse's meaning, to apply that day.

Rules for writing actions:
  - a simple good deed or an established Sunnah practice, worded as an invitation;
  - no promised reward, number or virtue that is not already cited in passages.py;
  - nothing disputed (e.g. Friday + Al-Kahf carries no action of its own, see passages.py);
  - Arabic first, then a plain English line.

action_for(passage) returns (arabic, english).
"""

# specific passages first: (surah, first, last) -> action
BY_PASSAGE = {
    (2, 255, 255): ("اقرأ آية الكرسي الليلة قبل نومك",
                    "Recite Ayat al-Kursi tonight before you sleep"),
    (2, 285, 286): ("اقرأ آخر آيتين من سورة البقرة الليلة",
                    "Recite the last two verses of Al-Baqarah tonight"),
    (112, 1, 4): ("اقرأ الإخلاص والمعوذتين الليلة قبل نومك",
                  "Recite Al-Ikhlas, Al-Falaq and An-Nas tonight before you sleep"),
    (113, 1, 5): ("اقرأ الإخلاص والمعوذتين الليلة قبل نومك",
                  "Recite Al-Ikhlas, Al-Falaq and An-Nas tonight before you sleep"),
    (114, 1, 6): ("اقرأ الإخلاص والمعوذتين الليلة قبل نومك",
                  "Recite Al-Ikhlas, Al-Falaq and An-Nas tonight before you sleep"),
    (1, 1, 7): ("في صلاتك القادمة اقرأ الفاتحة متأنيًا، آيةً آية",
                "In your next prayer, recite Al-Fatiha slowly, verse by verse"),
    (67, 1, 30): ("اقرأ سورة الملك الليلة", "Recite Surat Al-Mulk tonight"),
    (67, 1, 5): ("اقرأ سورة الملك الليلة", "Recite Surat Al-Mulk tonight"),
    (67, 26, 30): ("اقرأ سورة الملك الليلة", "Recite Surat Al-Mulk tonight"),
    (13, 28, 29): ("اذكر الله خمس دقائق اليوم بعيدًا عن هاتفك",          # «ألا بذكر الله تطمئن القلوب»
                   "Spend five minutes in dhikr today, away from your phone"),
}

FRIDAY = ("أكثِر من الصلاة على النبي ﷺ في يوم الجمعة",
          "Send abundant blessings on the Prophet ﷺ this Friday")

# (keywords found in the title, action); the first matching rule wins
RULES = [
    (("الغضب",), ("إذا غضبت اليوم فقل: أعوذ بالله من الشيطان الرجيم",
                  "If you feel angry today, say: «I seek refuge in Allah from Satan, the accursed»")),
    (("الوالدين", "ووالديه"), ("اتصل بوالديك أو زُرهما اليوم، أو ادعُ لهما إن كانا قد رحلا",
                              "Call or visit your parents today, or pray for them if they have passed away")),
    (("الصلاة على النبي",), ("صلِّ على النبي ﷺ عشر مرات اليوم",
                             "Send blessings on the Prophet ﷺ ten times today")),
    (("الإنفاق", "الصدقة", "تنفقوا", "أنفقتم", "القرض", "الإيثار"),
     ("تصدّق اليوم ولو بشيء يسير، وأخفِها إن استطعت",
      "Give something in charity today, even a little, and quietly if you can")),
    (("العفو", "الصفح"), ("سامِح اليوم من أساء إليك، ولو في نفسك",
                          "Forgive someone who wronged you today, even if only in your heart")),
    (("استغفر", "الاستغفار", "التوبة", "توبوا", "المغفرة", "الحسنات", "سيئاتهم"),
     ("خصّص دقائق اليوم للاستغفار بقلبٍ حاضر",
      "Take a few minutes today to ask Allah's forgiveness with a present heart")),
    (("الذرية", "ذريتهم", "الأهل", "أبوهما", "لقمان", "زكريا", "مريم", "الصالحين", "حافظ"),
     ("ادعُ لأهلك وأولادك اليوم بأسمائهم", "Pray for your family and children by name today")),
    (("دعاء", "ادعوني", "يجيب", "الدعاء"),
     ("اجعل هذا الدعاء من دعائك اليوم، وردّده في سجودك",
      "Make this du'a your own today and repeat it in your sujood")),
    (("صفات",), ("اختر صفةً واحدة من صفات هذه الآيات، واعمل بها اليوم",
                  "Pick one quality described in these verses and practise it today")),
    (("الشكر", "شكر", "النعمة", "نعم الله", "ما شاء الله"),
     ("اكتب ثلاث نِعَم أنعم الله بها عليك، واحمده عليها",
      "Write down three blessings Allah has given you, and thank Him for them")),
    (("الصبر", "المصيبة", "العسر", "الحزن", "الابتلاء", "أيوب", "نصر الله", "فترضى"),
     ("إن أهمّك شيء اليوم فتذكّر هذه الآيات، وقل: إنا لله وإنا إليه راجعون",
      "If something worries you today, remember these verses and say: «To Allah we belong and to Him we return»")),
    (("التوكل", "حسبنا", "حسبي", "أفوض", "مخرجًا", "معكما"),
     ("سلّم أمرًا يُقلقك إلى الله اليوم، وقل: حسبي الله ونعم الوكيل",
      "Hand one worry over to Allah today and say: «Allah is sufficient for me, and He is the best disposer of affairs»")),
    (("الرزق", "رزق", "يرزق", "نرزقك", "البركات", "يغنهم", "الجمعة والسعي", "الحياة الطيبة"),
     ("ابدأ عملك اليوم بـ«بسم الله، توكلت على الله» وأتقِنه",
      "Begin your work today with «Bismillah, I put my trust in Allah», and do it well")),
    (("الأخوة", "آداب", "القول", "قولًا", "الكلمة الطيبة", "حسن الخلق", "التواضع", "العدل", "الوصايا", "أجمع آية"),
     ("قل اليوم كلمة طيبة لمن يحتاجها، واجتنب الغيبة",
      "Say a kind word today to someone who needs it, and avoid backbiting")),
    (("ذكر", "الذاكرون", "التسبيح", "تنزيه"),
     ("اذكر الله خمس دقائق اليوم بعيدًا عن هاتفك",
      "Spend five minutes in dhikr today, away from your phone")),
    (("التفكر", "الخلق", "دلائل", "القدرة"),
     ("تأمّل السماء دقيقةً الليلة، وسبّح الله", "Look up at the sky for a minute tonight and glorify Allah")),
    (("السكينة", "سكينته", "شفاء", "يشفين", "السحر", "الساحر", "سيبطله", "العين", "الاستعاذة", "الإعاذة"),
     ("حافظ اليوم على أذكار الصباح والمساء", "Keep your morning and evening adhkar today")),
    (("الآخرة", "القيامة", "الاحتضار", "الأعمال", "الميزان", "الدنيا", "المتقين", "نعيم", "البر", "عقبى"),
     ("اسأل نفسك الليلة: ماذا قدّمتُ اليوم لآخرتي؟",
      "Ask yourself tonight: what did I do today for my hereafter?")),
]

SHORT_SURAH = ("احفظ هذه السورة أو راجِعها اليوم، واقرأ بها في صلاتك",
               "Memorise or review this surah today, and recite it in your prayer")
DEFAULT = ("أعِد قراءة هذه الآيات بتدبّر، واختر منها كلمةً تعيش بها يومك",
           "Read these verses again slowly, and carry one phrase from them through your day")


def action_for(p, friday=False):
    """p = a passages.py entry (surah, first, last, title, virtue, group, grade)."""
    if friday:
        return FRIDAY
    key = tuple(p[:3])
    if key in BY_PASSAGE:
        return BY_PASSAGE[key]
    title = p[3] if len(p) > 3 else ""
    for words, action in RULES:
        if any(w in title for w in words):
            return action
    group = p[5] if len(p) > 5 else None
    return SHORT_SURAH if group == 2 else DEFAULT
