"""Find where the recitation of a verse really ends, so a reel does not finish on the reciter's
breath.

everyayah.com cuts each verse file a little after the verse, and with many reciters that tail
holds the in-breath they take before the next verse. At the end of a reel that breath is heard
alone, so the last verse is trimmed to the end of the voice, given a short natural fade, and the
reel then ends in silence.

Voice and breath look different in a recording: the voice is loud and its energy sits low
(roughly 80-1000 Hz, the pitch and first formants), while a breath is quieter, noise-like hiss
with its energy spread up into the high frequencies.  We scan 20 ms frames and keep the last
stretch that is clearly voice.
"""
import subprocess

import numpy as np

SR = 16000
FRAME = 320          # 20 ms
HOP = 160            # 10 ms


def _decode(path):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
                                   "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype=np.float32)


def frame_features(x):
    """Per 10 ms step:
    db   - level in dB
    harm - harmonicity 0..1 (how periodic the sound is, measured above the mains hum)
    tilt - dB of energy in 100-1500 Hz over 2-6 kHz.  A sung vowel is strongly tilted to the
           low band; a breath is a hiss spread evenly up into the high frequencies."""
    win = 640                                          # 40 ms analysis window
    n = max(0, (len(x) - win) // HOP + 1)
    if n == 0:
        z = np.zeros(0)
        return z, z, z, z
    idx = np.arange(win)[None, :] + HOP * np.arange(n)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(1, keepdims=True)
    db = 10 * np.log10((fr ** 2).mean(1) + 1e-12)
    spec = np.fft.rfft(fr * np.hanning(win)[None, :], n=2 * win, axis=1)
    pw = np.abs(spec) ** 2
    f = np.fft.rfftfreq(2 * win, 1 / SR)
    lowb = pw[:, (f >= 100) & (f <= 1500)].sum(1)
    highb = pw[:, (f >= 2000) & (f <= 6000)].sum(1)
    tilt = 10 * np.log10((lowb + 1e-12) / (highb + 1e-12))
    sibb = pw[:, (f >= 4000) & (f <= 7800)].sum(1)
    midb = pw[:, (f >= 1000) & (f <= 3500)].sum(1)
    sib = 10 * np.log10((sibb + 1e-12) / (midb + 1e-12))   # > 0: hiss sits in the sibilant band
    pb = pw * ((f >= 150) & (f <= 3000))[None, :]      # ignore hum when judging periodicity
    ac = np.fft.irfft(pb, axis=1)[:, :win]
    lo, hi = SR // 450, SR // 65                       # pitch 65-450 Hz
    harm = np.clip(ac[:, lo:hi].max(1) / (ac[:, 0] + 1e-12), 0, 1)
    return db, harm, tilt, sib


def speech_end(path, drop_db=8.0, grace=0.13):
    """Seconds into the file where the recitation of the verse ends.

    Tuned on real everyayah files from every reciter in the rotation.  The end of the voice
    is the last moment where
      - the 150 ms before it is clearly the reciter's voice: largely pitched (at least 40%
        of its frames with harmonicity >= 0.65, so a short final syllable still counts) and
        not far below the recitation's loudness, and
      - everything after it stays at least 8 dB quieter than that voice.
    What follows (room echo, hum, the in-breath for the next verse) never comes back up to the
    voice's level, while a pause inside the verse always does.  A breath itself is not pitched,
    so it can never count as the voice.  A final hissing letter attached to the last vowel is
    kept, and a short grace keeps the final consonant's bounce (qalqala, a short nasal) and the
    very start of the decay.

    Returns None when the analysis finds nothing sensible (the file is then left untouched)."""
    x = _decode(path)
    dur = len(x) / SR
    db, harm, tilt, sib = frame_features(x)
    n = len(db)
    if n < 40:
        return None
    k = 2                                              # 50 ms median: ignore single clicks
    pad = np.pad(db, k, mode="edge")
    sm = np.median(np.stack([pad[i:i + n] for i in range(2 * k + 1)]), axis=0)
    level = np.percentile(sm, 90)                      # loudness of the recitation itself
    # A short sound at the very end of the file that comes after a pause (the in-breath, or
    # the first instant of the next verse) is not part of this verse: leave it out of the
    # "everything after" test.  Inside a verse the last word never follows such a pause.
    quiet = sm < level - 12
    stop, run = n, 0
    for i in range(n - 1, max(n - 50, 0) - 1, -1):     # last 0.5 s
        run = run + 1 if quiet[i] else 0
        if run >= 12 and n - (i + run) <= 35:          # >= 120 ms pause, then <= 350 ms to the end
            stop = i + run
    w = 15                                             # 150 ms before the candidate end
    c_db = np.concatenate([[0], np.cumsum(sm)])
    c_h = np.concatenate([[0], np.cumsum(harm >= 0.65)])   # pitched frames
    after = np.maximum.accumulate(sm[:stop][::-1])[::-1]   # loudest frame from here to `stop`
    gap = 5                                            # look from 50 ms after the end
    for t in range(stop - gap - 1, w - 1, -1):
        pre = (c_db[t] - c_db[t - w]) / w
        if pre < level - 20 or (c_h[t] - c_h[t - w]) / w < 0.4:
            continue
        if after[t + gap] <= pre - drop_db:
            # a verse can end on a hissing letter (س ش ص ز, e.g. "والناس"): it is not pitched,
            # but it is attached to the last vowel and its energy sits in the 4-8 kHz band, well
            # above a breath (measured: the letter +4..+16 dB, breaths -4 dB or lower).  Keep it.
            j, miss = t, 0
            while j < stop and (j - t) < 35 and miss <= 2:
                fric = sm[j] > level - 25 and sib[j] > 2      # a breath measured -4 dB or lower
                miss = 0 if fric else miss + 1
                j += 1
            if j - miss > t:
                t = j - miss
            # a verse can also end on a held nasal (ن / م after a long vowel, e.g. "الصابرين",
            # "العالمين"): at the stop it is quieter than the vowel, but it is still the voice -
            # pitched, with its energy low in the spectrum - while a breath is unpitched hiss.
            # Keep every such frame that follows (a few short dips allowed).
            j, miss, last = t, 0, t
            while j < stop and miss <= 4:
                nasal = sm[j] > level - 32 and harm[j] >= 0.5 and tilt[j] > 8 and sib[j] < 2
                if nasal:
                    last, miss = j + 1, 0
                else:
                    miss += 1
                j += 1
            t = max(t, last)
            end = min(dur, (t * HOP + 320) / SR + grace)   # t = start of the frame after the voice
            return end if end >= dur * 0.5 else None
    return dur if stop == n else None                  # voice runs to the very end: nothing to cut


def duration_of(path):
    return len(_decode(path)) / SR


def profile(src, last_sec=2.0):
    """Diagnostics: the last seconds of a file as 50 ms rows (time, dB, harmonicity, tilt, sibilance)."""
    x = _decode(src)
    db, harm, tilt, sib = frame_features(x)
    n = len(db)
    rows = []
    for i in range(max(0, n - int(last_sec * 100)), n, 5):
        rows.append(f"{i * HOP / SR:6.2f} {db[i]:6.1f} {harm[i]:.2f} {tilt[i]:5.1f} {sib[i]:5.1f}")
    return "\n".join(rows)


def trim_end(src, dst, fade=0.10):
    """Write dst = src cut at the end of the voice with a short fade-out. Returns the new
    duration, or None if src was left as it is."""
    end = speech_end(src)
    if end is None or end >= duration_of(src) - 0.05:   # nothing after the voice to remove
        return None
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-t", f"{end:.3f}",
                    "-af", f"afade=t=out:st={max(0.0, end - fade):.3f}:d={fade:.3f}",
                    "-c:a", "libmp3lame", "-q:a", "2", dst], check=True)
    return end


# ------------------------------------------------------------------ joining verse files
# everyayah.com serves one file per verse. With reciters recorded in a reverberant hall
# (As-Sudais, Ash-Shuraym ...) each file's echo is cut off abruptly and followed by up to
# ~0.3 s of digital silence, so played back to back the recitation "drops out" at every
# verse boundary (see community.itqan.dev/d/881). join_verses() removes that dead silence
# and overlaps the end of each verse with the quiet start of the next using a short
# equal-power crossfade, so the echo dies away naturally into the next verse.

JOIN_SR = 48000


def _decode_stereo(path, sr=JOIN_SR):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-ac", "2", "-ar", str(sr),
                                   "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)


def sound_bounds(x, sr=JOIN_SR, floor=50.0):
    """(first, last) sample that holds any sound at all: voice, echo or breath. Anything more
    than `floor` dB below the recitation's loudness (and below -70 dBFS) counts as silence."""
    hop = sr // 100                                    # 10 ms
    n = len(x) // hop
    if n < 5:
        return 0, len(x)
    m = x[:n * hop].mean(1).reshape(n, hop)
    db = 10 * np.log10((m ** 2).mean(1) + 1e-12)
    level = np.percentile(db, 90)
    on = np.nonzero(db > max(level - floor, -70))[0]
    if len(on) == 0:
        return 0, len(x)
    return int(on[0] * hop), int(min(len(x), (on[-1] + 1) * hop))


def join_verses(paths, dst, xfade=0.08, keep_lead=0.15, keep_tail=0.04, sr=JOIN_SR):
    """Join verse files into one WAV without dead gaps between them.

    - trailing silence after the last sound of a verse (the cut-off echo) is removed,
      keeping `keep_tail` s;
    - leading silence before the next verse is cut down to at most `keep_lead` s;
    - the two are overlapped by up to `xfade` s with equal-power curves (never more than the
      next verse's remaining lead-in, so two voices never overlap).

    The first verse keeps its start and the last verse its end (that is trimmed separately by
    trim_end). Returns the time each verse occupies in the joined audio, in seconds, for
    timing the on-screen text."""
    xs = [_decode_stereo(p, sr) for p in paths]
    pieces, leads = [], []
    for i, x in enumerate(xs):
        first, last = sound_bounds(x, sr)
        start = 0 if i == 0 else max(0, first - int(keep_lead * sr))
        end = len(x) if i == len(xs) - 1 else min(len(x), last + int(keep_tail * sr))
        if end - start < sr // 10:                     # analysis failed: keep the file as it is
            start, end = 0, len(x)
        pieces.append(x[start:end])
        leads.append(max(0, first - start))            # silence left at the head of this piece

    out = [pieces[0]]
    spans = []
    for i in range(1, len(pieces)):
        nxt = pieces[i]
        k = int(min(xfade * sr, leads[i], len(out[-1]) // 2, len(nxt) // 2))
        if k > 0:
            t = np.linspace(0, np.pi / 2, k, dtype=np.float32)[:, None]
            prev = out[-1]
            blend = prev[-k:] * np.cos(t) + nxt[:k] * np.sin(t)
            out[-1] = prev[:-k]
            nxt = np.concatenate([blend, nxt[k:]])
        spans.append(len(pieces[i - 1]) - k)           # samples verse i-1 holds before the next takes over
        out.append(nxt)
    spans.append(len(pieces[-1]))
    y = np.concatenate(out).astype(np.float32)
    peak = float(np.abs(y).max()) if len(y) else 0.0
    if peak > 1.0:
        y /= peak
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2",
                    "-i", "-", "-c:a", "pcm_s16le", dst], input=y.tobytes(), check=True)
    return [s / sr for s in spans]
