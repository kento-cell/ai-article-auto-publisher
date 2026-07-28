"""#夏の1コマ contest entry: generative fireworks artwork.

Original generative art drawn entirely in code (PIL) — no stock
photos, no third-party material, no AI image models. Summer night
fireworks over water with reflection.

Output: data/images/contest/natsu_hitokoma_2026.png (1280x1280)
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

random.seed(20260728)  # reproducible artwork

W = H = 1280
HORIZON = int(H * 0.72)

img = Image.new("RGB", (W, H))
px = img.load()

# --- 1. Summer night sky gradient (deep indigo -> warm horizon) ---
for y in range(H):
    if y < HORIZON:
        t = y / HORIZON
        r = int(8 + 30 * t)
        g = int(10 + 24 * t)
        b = int(38 + 52 * t)
    else:
        t = (y - HORIZON) / (H - HORIZON)
        r = int(10 + 6 * t)
        g = int(14 + 8 * t)
        b = int(40 + 14 * t)
    for x in range(W):
        px[x, y] = (r, g, b)

draw = ImageDraw.Draw(img, "RGBA")

# --- 2. Stars ---
for _ in range(220):
    x = random.randint(0, W - 1)
    y = random.randint(0, HORIZON - 60)
    b = random.randint(90, 200)
    draw.point((x, y), fill=(b, b, min(255, b + 30), 255))

# --- 3. Fireworks ---
PALETTES = [
    [(255, 120, 80), (255, 190, 90), (255, 240, 180)],   # warm orange
    [(120, 200, 255), (170, 230, 255), (230, 250, 255)],  # ice blue
    [(255, 130, 200), (255, 180, 230), (255, 230, 250)],  # pink
    [(170, 255, 150), (220, 255, 190), (250, 255, 230)],  # green-gold
]

glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gdraw = ImageDraw.Draw(glow)


def firework(cx: int, cy: int, radius: int, palette, rays: int, seed: int):
    rnd = random.Random(seed)
    for i in range(rays):
        ang = (2 * math.pi / rays) * i + rnd.uniform(-0.05, 0.05)
        length = radius * rnd.uniform(0.55, 1.0)
        # trail of fading dots along each ray, drooping slightly (gravity)
        steps = int(length / 4)
        for s in range(steps):
            t = s / max(1, steps - 1)
            droop = 18 * (t ** 2)
            x = cx + math.cos(ang) * length * t
            y = cy + math.sin(ang) * length * t + droop
            if not (0 <= x < W and 0 <= y < H):
                continue
            c = palette[min(2, int(t * 3))]
            alpha = int(235 * (1 - t) ** 1.3) + 20
            size = max(1, int(3.4 * (1 - t)) + (1 if s % 7 == 0 else 0))
            gdraw.ellipse(
                (x - size, y - size, x + size, y + size),
                fill=(c[0], c[1], c[2], alpha),
            )
        # bright tip sparkle
        tx = cx + math.cos(ang) * length
        ty = cy + math.sin(ang) * length + 18
        gdraw.ellipse((tx - 2, ty - 2, tx + 2, ty + 2),
                      fill=(255, 255, 240, 220))
    # core flash
    gdraw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7),
                  fill=(255, 255, 230, 255))


firework(int(W * 0.32), int(H * 0.30), 300, PALETTES[0], 46, 1)
firework(int(W * 0.68), int(H * 0.22), 240, PALETTES[1], 40, 2)
firework(int(W * 0.55), int(H * 0.45), 150, PALETTES[2], 32, 3)
firework(int(W * 0.16), int(H * 0.52), 110, PALETTES[3], 28, 4)
firework(int(W * 0.86), int(H * 0.48), 95, PALETTES[0], 26, 5)

# soft glow pass + sharp pass
blurred = glow.filter(ImageFilter.GaussianBlur(6))
img.paste(blurred, (0, 0), blurred)
img.paste(glow, (0, 0), glow)

# --- 4. Water reflection (flip fireworks band, ripple, darken) ---
band = img.crop((0, 0, W, HORIZON)).transpose(Image.FLIP_TOP_BOTTOM)
band = band.resize((W, H - HORIZON))
band = band.filter(ImageFilter.GaussianBlur(3))
ripple = band.load()
refl = Image.new("RGB", (W, H - HORIZON))
rp = refl.load()
for y in range(H - HORIZON):
    shift = int(6 * math.sin(y / 7.0))
    dim = 0.38 + 0.1 * (y / (H - HORIZON))
    for x in range(W):
        sx = min(W - 1, max(0, x + shift))
        r, g, b = ripple[sx, y]
        rp[x, y] = (int(r * dim), int(g * dim), int(b * dim + 8))
img.paste(refl, (0, HORIZON))

# horizon line shimmer
d2 = ImageDraw.Draw(img, "RGBA")
d2.line((0, HORIZON, W, HORIZON), fill=(120, 140, 190, 90), width=2)

# --- 5. Distant town silhouette on horizon ---
rnd = random.Random(99)
x = 0
while x < W:
    w = rnd.randint(18, 60)
    h = rnd.randint(6, 26)
    d2.rectangle((x, HORIZON - h, x + w, HORIZON), fill=(4, 6, 16, 255))
    if rnd.random() < 0.5:
        wx = x + rnd.randint(3, max(4, w - 4))
        d2.point((wx, HORIZON - rnd.randint(2, max(3, h - 2))),
                 fill=(255, 220, 140, 255))
    x += w + rnd.randint(4, 22)

out = Path("data/images/contest")
out.mkdir(parents=True, exist_ok=True)
dest = out / "natsu_hitokoma_2026.png"
img.save(dest, "PNG")
print(f"saved: {dest} ({dest.stat().st_size} bytes)")
