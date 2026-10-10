"""Cut the ELEV8 logo out of its dark background into transparent PNGs.

Estimates the background behind the logo (by filling the logo area from its surroundings),
then derives each pixel's opacity from how far it rises above that background.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

here = Path(__file__).resolve().parent
src = np.asarray(Image.open(here / "elev8-logo-source.jpg").convert("RGB")).astype(np.float32)
H, W, _ = src.shape
r, g, b = src[..., 0], src[..., 1], src[..., 2]

# Logo pixels: clearly blue/teal and brighter than the navy backdrop.
logo = (b > 95) & (b - r > 45)
mask_img = Image.fromarray((logo * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
valid = 1.0 - np.asarray(mask_img, dtype=np.float32) / 255.0

# Fill the background under the logo by normalised blurring of the surrounding pixels.
def box(a, r, axis):
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)

def blur(a, radius):
    # Three box passes per axis approximate a Gaussian.
    r = max(1, int(radius / 1.7))
    for axis in (0, 1):
        for _ in range(3):
            a = box(a, r, axis)
    return a
bg = np.zeros_like(src)
w = blur(valid, 40) + 1e-6
for c in range(3):
    bg[..., c] = blur(src[..., c] * valid, 40) / w

# Opacity from the rise above background, measured on the blue channel (the logo's strongest).
FG_B = 205.0
alpha = np.clip((b - bg[..., 2]) / np.maximum(FG_B - bg[..., 2], 1.0), 0, 1)
alpha = np.where(alpha < 0.14, 0, alpha)
# Un-mix the background to recover the logo's own colour at soft edges.
a3 = np.maximum(alpha[..., None], 1e-3)
fg = np.clip((src - (1 - a3) * bg) / a3, 0, 255)
# Brighten slightly so the mark holds up on the page's darker navy.
fg = np.clip(fg * 1.12, 0, 255)
rgba = np.dstack([fg, alpha * 255]).astype(np.uint8)
img = Image.fromarray(rgba, "RGBA")

def crop(box, pad, name, height):
    x0, y0, x1, y1 = box
    c = img.crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    scale = height / c.height
    c = c.resize((round(c.width * scale), height), Image.LANCZOS)
    c.save(here / name, optimize=True)
    print(name, c.size)

crop((501, 158, 907, 426), 6, "elev8-mark.png", 240)        # wings, bars and arrow
crop((471, 158, 936, 611), 8, "elev8-lockup.png", 460)      # mark with ELEV8 TRADING
