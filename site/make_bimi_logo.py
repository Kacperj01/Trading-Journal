"""Build docs/bimi-logo.svg: the ELEV8 mark as an SVG Tiny PS logo for BIMI (sender logos in inboxes).

Traces the mark's outline from site/brand/elev8-mark.png (needs: pip install potracer numpy pillow),
fills it with the brand gradient on navy, centred in a square with room for the circular crop.
Published at https://elev8tradingjournal.com/bimi-logo.svg and referenced by the BIMI DNS record.
"""
from pathlib import Path
import numpy as np
import potrace
from PIL import Image

root = Path(__file__).resolve().parent.parent
im = Image.open(root / "site" / "brand" / "elev8-mark.png").convert("RGBA")
S = 4  # trace at 4x for smooth curves
alpha = np.array(im.getchannel("A").resize((im.width * S, im.height * S), Image.LANCZOS))
path = potrace.Bitmap(alpha <= 128).trace(turdsize=20, alphamax=1.0, opticurve=True, opttolerance=0.25)  # potracer fills False pixels
W, H = im.width * S, im.height * S
side = 1000.0
scale = side * 0.74 / W
ox, oy = (side - W * scale) / 2, (side - H * scale) / 2 + 10
pt = lambda p: f"{p.x * scale + ox:.1f} {p.y * scale + oy:.1f}"
d = []
for curve in path:
    d.append("M" + pt(curve.start_point))
    for seg in curve.segments:
        d.append(("L" + pt(seg.c) + "L" + pt(seg.end_point)) if seg.is_corner else ("C" + pt(seg.c1) + " " + pt(seg.c2) + " " + pt(seg.end_point)))
    d.append("Z")
svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg version="1.2" baseProfile="tiny-ps" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
<title>ELEV8</title>
<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="{ox:.0f}" y1="{oy + H * scale:.0f}" x2="{ox + W * scale:.0f}" y2="{oy:.0f}"><stop offset="0" stop-color="#2a7fd9"/><stop offset="0.55" stop-color="#1f9fcf"/><stop offset="1" stop-color="#2fd0c8"/></linearGradient></defs>
<rect width="1000" height="1000" fill="#06111f"/>
<path fill="url(#g)" fill-rule="evenodd" d="{"".join(d)}"/>
</svg>
'''
(root / "docs" / "bimi-logo.svg").write_text(svg, encoding="utf-8")
print("wrote docs/bimi-logo.svg,", len(svg), "bytes")
