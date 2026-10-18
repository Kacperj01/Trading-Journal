"""Download the site's fonts (Outfit and JetBrains Mono) from Google Fonts into site/fonts/,
so pages load them from elev8tradingjournal.com instead of Google's servers (no visitor IPs sent
to Google). Both fonts are under the SIL Open Font License. Run: python3 site/fetch_fonts.py
"""
import re, urllib.request
from pathlib import Path

out = Path(__file__).resolve().parent / "fonts"
out.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FAMILIES = {"Outfit": "Outfit:wght@300..900", "JetBrains Mono": "JetBrains+Mono:wght@400..700"}
KEEP = ("latin", "latin-ext")  # English, Irish, Polish and other European names


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()


css_out = ["/* Self-hosted fonts (SIL Open Font License). Made by site/fetch_fonts.py. */"]
for name, q in FAMILIES.items():
    css = get(f"https://fonts.googleapis.com/css2?family={q}&display=swap").decode()
    for subset, block in re.findall(r"/\* ([a-z-]+) \*/\s*(@font-face \{.*?\})", css, re.S):
        if subset not in KEEP:
            continue
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        fname = f"{name.lower().replace(' ', '-')}-{subset}.woff2"
        (out / fname).write_bytes(get(url))
        css_out.append(f"/* {name} {subset} */\n" + block.replace(url, fname))
        print("saved", fname)
(out / "fonts.css").write_text("\n".join(css_out) + "\n")
print("wrote fonts.css")
