"""
Slow, calm, seamlessly looping motion for a still background image:
  - very slow camera drift on a soft elliptical path with a gentle breathing zoom
  - soft rays of warm light from above that slowly swell and fade
  - dust motes floating almost still, visible only in bright areas and in the rays
  - light that softly brightens and dims
Every motion has period LOOP seconds, so the clip loops without a jump.

Usage as a module:  make_motion_video(image_path, seconds, out_mp4)
Command line:       python motion.py image.jpg out.mp4 [seconds]
"""
import math, random, subprocess, sys

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

W, H, FPS = 1080, 1920, 30
LOOP = 30.0                 # seconds; all motion repeats exactly every LOOP seconds
OVERSCAN = 1.08             # image is prepared slightly larger than the frame for drift
WARM = (255, 226, 170)      # colour of the light rays and glow


def _prepare(path):
    im = Image.open(path).convert("RGB")
    tw, th = int(W * OVERSCAN), int(H * OVERSCAN)
    s = max(tw / im.width, th / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((l, t, l + tw, t + th))


def _sprite(r):
    """Soft round dust mote."""
    size = r * 6
    sp = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sp).ellipse([size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r], fill=255)
    return sp.filter(ImageFilter.GaussianBlur(r * 0.9))


def _rays(rng, bw, bh, n, strength):
    """Soft light rays fanning down from above the frame, fading towards the bottom."""
    sx, sy = bw * rng.uniform(0.45, 0.7), -bh * 0.25
    m = Image.new("L", (bw, bh), 0)
    d = ImageDraw.Draw(m)
    for _ in range(n):
        ang = math.radians(rng.uniform(-28, 28) + 90)          # 90 deg = straight down
        half = math.radians(rng.uniform(1.2, 3.5))
        far = bh * 1.6
        pts = [(sx, sy),
               (sx + far * math.cos(ang - half), sy + far * math.sin(ang - half)),
               (sx + far * math.cos(ang + half), sy + far * math.sin(ang + half))]
        d.polygon(pts, fill=int(255 * rng.uniform(0.5, 1.0)))
    # soft glow at the top where the light comes in
    d.ellipse([sx - bw * 0.45, -bh * 0.30, sx + bw * 0.45, bh * 0.22], fill=170)
    m = m.filter(ImageFilter.GaussianBlur(45))
    fade = Image.linear_gradient("L").resize((bw, bh)).point(lambda v: 255 - int(v * 0.85))   # strong at top
    return ImageChops.multiply(m, fade).point(lambda v: int(v * strength))


def make_motion_video(image_path, seconds, out_mp4, seed=1, n_motes=140, crf=20):
    rng = random.Random(seed)
    base = _prepare(image_path)
    bw, bh = base.size
    # light rays: two sets that slowly cross-fade, so the light seems to shift and swell
    rays_a, rays_b = _rays(rng, bw, bh, 5, 0.22), _rays(rng, bw, bh, 5, 0.22)
    warm = Image.new("RGB", base.size, WARM)
    # brightness map decides where dust is visible (bright areas and inside the rays)
    lum = base.convert("L").filter(ImageFilter.GaussianBlur(12))
    lum = lum.point(lambda v: max(0, min(255, int((v - 60) * 3.0))))
    lum = ImageChops.lighter(lum, ImageChops.lighter(rays_a, rays_b).point(lambda v: min(255, v * 5)))
    # a slightly brighter, warmer version for the "breathing light"
    bright = ImageEnhance.Brightness(base).enhance(1.10)
    bright = Image.blend(bright, warm, 0.06)
    light_mask = base.convert("L").point(lambda v: int(max(0, v - 90) * 1.6)).filter(ImageFilter.GaussianBlur(20))

    sprites = {r: _sprite(r) for r in (2, 3, 4, 5)}
    motes = []
    for _ in range(n_motes):
        r = rng.choice([2, 2, 2, 3, 3, 4, 5])
        motes.append({
            "x": rng.uniform(0, bw), "y": rng.uniform(0, bh), "r": r,
            # each mote floats on its own small, slow loop (a few pixels per second)
            "ax": rng.uniform(15, 45), "ay": rng.uniform(25, 75),
            "px": rng.uniform(0, 2 * math.pi), "py": rng.uniform(0, 2 * math.pi),
            "tw": rng.choice([1, 1, 2]), "tph": rng.uniform(0, 2 * math.pi),
            "a": rng.uniform(0.3, 0.85),
        })

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4],
        stdin=subprocess.PIPE)
    n = int(round(seconds * FPS))
    for f in range(n):
        t = f / FPS
        ph = 2 * math.pi * (t % LOOP) / LOOP
        # breathing light
        k = 0.5 + 0.5 * math.sin(ph)
        frame = Image.composite(bright, base, light_mask.point(lambda v, k=k: int(v * k * 0.45)))
        # light rays swell and fade, one set into the other
        rays = Image.blend(rays_a, rays_b, 0.5 + 0.5 * math.sin(ph + 1.0))
        frame = Image.composite(warm, frame, rays)
        # dust motes (positions are periodic in LOOP)
        dust = Image.new("L", (bw, bh), 0)
        for m in motes:
            x = (m["x"] + m["ax"] * math.sin(ph + m["px"])) % bw
            y = (m["y"] + m["ay"] * math.sin(ph + m["py"])) % bh
            a = m["a"] * (0.6 + 0.4 * math.sin(m["tw"] * ph + m["tph"]))
            sp = sprites[m["r"]]
            dust.paste(int(255 * a), (int(x - sp.width / 2), int(y - sp.height / 2)), sp)
        dust = ImageChops.multiply(dust, lum)
        frame = Image.composite(Image.new("RGB", frame.size, (255, 240, 210)), frame, dust)
        # very slow drift on an ellipse with a gentle breathing zoom
        z = 1.0 + 0.03 * (0.5 - 0.5 * math.cos(ph))
        cw, ch = (bw / OVERSCAN) / z, (bh / OVERSCAN) / z
        cx = bw / 2 + (bw - cw) * 0.18 * math.sin(ph)
        cy = bh / 2 + (bh - ch) * 0.12 * math.cos(ph)
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        frame = frame.resize((W, H), Image.BILINEAR, box=box)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while writing motion background")
    return out_mp4


if __name__ == "__main__":
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else LOOP
    make_motion_video(sys.argv[1], secs, sys.argv[2])
