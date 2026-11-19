# Contributing

Jazakum Allahu khayran for helping. Code changes follow normal open-source practice. **Changes to Quranic content follow stricter rules**, because an error there is published automatically, every day, to a public audience.

## Quranic content rules (passages.py, captions, rendering)

1. **No generated or retyped Quran text.** The text is always fetched from a verified edition. Never paste verses into code, and never use an AI model to produce, complete or "fix" a verse.
2. **Complete meaning only.** A passage must start and end where the meaning is complete. Long passages are split only at *ruku'* boundaries. In the pull request, explain why the boundaries are sound, citing a tafsir if it isn't obvious.
3. **Virtues need evidence.** Every virtue line gives its source (book and number) and a grade code (`h`, `a`, `q`, `s`; see the header of `passages.py`). Weak or fabricated narrations are not accepted, even if they are popular. Items that are disputed among scholars carry no virtue line.
4. **Promises in the Quran are not attributed to the Prophet ﷺ**, and statements of companions or scholars are attributed to them by name.
5. **Two reviewers** for any content change, at least one of them able to verify the Arabic and the hadith reference.

## Daily actions (actions.py)

An action is a simple good deed or an established Sunnah practice, worded as an invitation. Don't add rewards, numbers or virtues that aren't already cited in `passages.py`, and don't attach an action to a disputed practice.

## Reciters

Add a reciter only if all of these are true:
- the recording is Hafs murattal,
- it is 128 kbps or higher on everyayah.com,
- the files are complete for the whole Quran,
- there is no audible noise, clipping or crowd sound.

Test at least three passages, including one with a long final verse, so the end-of-audio trim can be checked.

## Code

- Python 3.9+, standard library plus Pillow and numpy only. Please don't add heavy dependencies without discussion.
- Run `python generate.py --verses 112:1-4` and `python generate.py --verses 2:255` and look at both videos before opening a pull request.
- Keep secrets out of code, logs and artifacts. All credentials come from environment variables.
- Describe what you changed and how you tested it. A smaller pull request that you fully understand is better than a large one you don't.

## Reporting a content error

If you find a wrong verse, a wrong verse number, a cut in the middle of the meaning, or a weak virtue, open an issue labelled **content-error** with the surah and verse. These are handled before anything else.
