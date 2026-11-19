"""Copy images and video clips from a folder into backgrounds/ (skips ones already there or too small).

Images  -> backgrounds/<name>.jpg   (min 600 px wide, max 2400 px tall)
Videos  -> backgrounds/<name>.mp4   (1080x1920 vertical, 30 fps, no audio, at most MAX_SEC long,
                                     made into a seamless loop by cross-fading the end into the start)

Names listed in background_exclude.txt are never copied.

Usage: python sync_backgrounds.py "<folder>"   """
import hashlib, os, re, subprocess, sys
from PIL import Image

MIN_W = 600
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
VID_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
W, H, FPS = 1080, 1920, 30
MAX_SEC = 30.0          # longest clip kept (it is looped for longer recitations)
XFADE = 1.0             # seconds of cross-fade that hides the loop point
MIN_SEC = 4.0


def safe_stem(stem):
    """File names without spaces or brackets, e.g. 'WhatsApp Video 2026-11-10 at 9.02.43 AM' -> 'WhatsApp_Video_2026-11-10_at_9.02.43_AM'."""
    return re.sub(r"[^\w.-]+", "_", stem).strip("_")


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def prepare_video(src, dest):
    """Vertical 1080x1920 seamless loop, no audio."""
    d = min(duration(src), MAX_SEC)
    if d < MIN_SEC:
        raise ValueError(f"only {d:.1f} s long")
    x = XFADE
    filt = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"fps={FPS},setsar=1,format=yuv420p,split[a][b];"
            f"[a]trim=start={x}:end={d:.3f},setpts=PTS-STARTPTS[a1];"
            f"[b]trim=start=0:end={x},setpts=PTS-STARTPTS[b1];"
            f"[a1][b1]xfade=transition=fade:duration={x}:offset={d - 2 * x:.3f}[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-t", f"{d:.3f}", "-i", src,
                    "-filter_complex", filt, "-map", "[v]", "-an",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-maxrate", "8M", "-bufsize", "16M",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", dest], check=True)


def main():
    src = sys.argv[1]
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backgrounds")
    os.makedirs(dst, exist_ok=True)
    added, skipped = [], []
    excl = set()
    ex_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "background_exclude.txt")
    if os.path.exists(ex_file):
        for ln in open(ex_file, encoding="utf-8"):
            ln = ln.split("#")[0].strip()
            if ln:
                excl.add(os.path.splitext(ln)[0])
    seen = {}
    # shorter names first, so "x.jpg" is kept and its copy "x (1).jpg" is recognised as a duplicate
    for f in sorted(os.listdir(src), key=lambda n: (len(n), n)):
        low = f.lower()
        stem = os.path.splitext(f)[0]
        if stem in excl or safe_stem(stem) in excl:
            continue
        path = os.path.join(src, f)
        if not low.endswith(IMG_EXT + VID_EXT) or not os.path.isfile(path):
            continue
        hsh = file_hash(path)
        if hsh in seen:
            skipped.append(f"{f} (duplicate of {seen[hsh]})"); continue
        seen[hsh] = f
        stem = safe_stem(stem)
        if low.endswith(IMG_EXT):
            name = stem + ".jpg"
            if os.path.exists(os.path.join(dst, name)):
                continue
            im = Image.open(path).convert("RGB")
            if im.width < MIN_W:
                skipped.append(f"{f} ({im.width}x{im.height}, too small)"); continue
            if im.height > 2400:
                im = im.resize((round(im.width * 2400 / im.height), 2400), Image.LANCZOS)
            im.save(os.path.join(dst, name), quality=92)
            added.append(name)
        elif low.endswith(VID_EXT):
            name = stem + ".mp4"
            if os.path.exists(os.path.join(dst, name)):
                continue
            try:
                prepare_video(path, os.path.join(dst, name))
                added.append(name)
            except (ValueError, subprocess.CalledProcessError) as e:
                skipped.append(f"{f} ({e})")
    print(f"added {len(added)}")
    for a in added:
        print("  +", a)
    for s in skipped:
        print("  skipped", s)


if __name__ == "__main__":
    main()
