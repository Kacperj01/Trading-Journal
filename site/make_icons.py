"""Draw the app icon (a rising equity line on the journal's navy) at the sizes iOS and browsers need."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
S = 1024

def icon(maskable=False):
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    top, bottom = (16, 24, 48), (8, 11, 22)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    # Soft blue and green glows.
    glow = Image.new("RGB", (S, S), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([-200, -260, 560, 500], fill=(30, 70, 150))
    g.ellipse([520, 520, 1240, 1240], fill=(20, 110, 80))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(160)), 0.35)
    d = ImageDraw.Draw(img)
    pad = 230 if maskable else 170  # keep the mark inside the safe zone for maskable icons
    x0, x1, y0, y1 = pad, S - pad, pad + 40, S - pad - 20
    for i in range(4):
        y = y0 + (y1 - y0) * i / 3
        d.line([(x0, y), (x1, y)], fill=(40, 52, 82), width=6)
    pts = [(0.00, 0.70), (0.16, 0.58), (0.30, 0.66), (0.46, 0.42), (0.60, 0.50), (0.78, 0.24), (1.00, 0.08)]
    xy = [(x0 + (x1 - x0) * px, y0 + (y1 - y0) * py) for px, py in pts]
    # Area under the line.
    area = Image.new("L", (S, S), 0)
    ImageDraw.Draw(area).polygon(xy + [(x1, y1), (x0, y1)], fill=90)
    img.paste((46, 229, 157), mask=area.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(img)
    d.line(xy, fill=(46, 229, 157), width=34, joint="curve")
    for i, (x, y) in enumerate(xy):
        r = 30 if i == len(xy) - 1 else 20
        d.ellipse([x - r, y - r, x + r, y + r], fill=(247, 198, 74) if i == len(xy) - 1 else (46, 229, 157), outline=(10, 14, 26), width=8)
    return img

base, mask = icon(), icon(maskable=True)
for name, img, size in [("apple-touch-icon.png", base, 180), ("icon-192.png", base, 192), ("icon-512.png", base, 512),
                        ("icon-maskable-512.png", mask, 512), ("favicon-32.png", base, 32)]:
    img.resize((size, size), Image.LANCZOS).save(out / name, optimize=True)
print("icons written to", out)
