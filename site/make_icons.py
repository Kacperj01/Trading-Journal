"""App icons: the ELEV8 mark centred on the logo's navy, with its soft blue glow."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
mark = Image.open(Path(__file__).resolve().parent / "brand" / "elev8-mark.png").convert("RGBA")
S = 1024

def icon(scale):
    img = Image.new("RGBA", (S, S), (5, 17, 33, 255))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([S * 0.12, S * 0.05, S * 0.88, S * 0.8], fill=(14, 60, 100, 255))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))
    w = int(S * scale)
    m = mark.resize((w, round(mark.height * w / mark.width)), Image.LANCZOS)
    img.alpha_composite(m, ((S - m.width) // 2, (S - m.height) // 2))
    return img.convert("RGB")

base, maskable = icon(0.74), icon(0.56)  # maskable keeps the mark inside the platform's safe zone
for name, img, size in [("apple-touch-icon.png", base, 180), ("icon-192.png", base, 192), ("icon-512.png", base, 512),
                        ("icon-maskable-512.png", maskable, 512), ("favicon-32.png", base, 32)]:
    img.resize((size, size), Image.LANCZOS).save(out / name, optimize=True)
print("icons written to", out)

# Notification badge (Android's status bar): the mark as a white silhouette on transparent; the system
# colours it in.
badge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
w = int(S * 0.86)
m = mark.resize((w, round(mark.height * w / mark.width)), Image.LANCZOS)
white = Image.new("RGBA", m.size, (255, 255, 255, 255))
white.putalpha(m.getchannel("A").point(lambda a: 255 if a > 110 else 0))
badge.alpha_composite(white, ((S - m.width) // 2, (S - m.height) // 2))
badge.resize((96, 96), Image.LANCZOS).save(out / "badge-96.png", optimize=True)
print("badge written")
