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
    db, harm, _, sib = frame_features(x)
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
            end = min(dur, (t * HOP + 320) / SR + grace)   # t = start of the frame after the voice
            return end if end >= dur * 0.5 else None
    return dur if stop == n else None                  # voice runs to the very end: nothing to cut


def duration_of(path):
    return len(_decode(path)) / SR


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
