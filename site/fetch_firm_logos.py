"""Fetch each supported prop firm's official site icon into site/firm-logos/ (run by hand via
the "Fetch prop firm logos" Action). The app embeds them, so they show offline and in every copy.

Tries the firm's own <link rel="apple-touch-icon"> / <link rel="icon"> first, then /favicon.ico,
then Google's favicon service for that domain.
"""
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

FIRMS = {"ftmo": "https://ftmo.com/en/", "fundingpips": "https://fundingpips.com/", "alpha": "https://alphacapitalgroup.uk/"}
OUT = Path(__file__).resolve().parent / "firm-logos"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as res:
        return res.read(), res.headers.get("Content-Type", "")


def candidates(home):
    try:
        page = get(home)[0].decode("utf-8", "replace")
    except Exception as exc:
        print("  homepage failed:", exc)
        page = ""
    links = []
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = (re.search(r'rel=["\']([^"\']+)', tag, re.I) or [None, ""])[1].lower()
        href = (re.search(r'href=["\']([^"\']+)', tag, re.I) or [None, ""])[1]
        if "icon" in rel and href:
            size = re.search(r'sizes=["\'](\d+)', tag)
            score = (2 if "apple" in rel else 1) * 1000 + (int(size.group(1)) if size else 32)
            links.append((score, urllib.parse.urljoin(home, href)))
    urls = [u for _, u in sorted(links, reverse=True)]
    host = urllib.parse.urlparse(home).netloc
    return urls + [urllib.parse.urljoin(home, "/favicon.ico"), f"https://www.google.com/s2/favicons?domain={host}&sz=128"]


def main():
    OUT.mkdir(exist_ok=True)
    ok = 0
    for firm, home in FIRMS.items():
        print(firm)
        for url in candidates(home):
            try:
                data, ctype = get(url)
            except Exception as exc:
                print("  skip", url, exc)
                continue
            ext = "svg" if "svg" in ctype or url.endswith(".svg") else "ico" if "icon" in ctype or url.endswith(".ico") else "png" if "png" in ctype else "jpg" if "jp" in ctype else "webp" if "webp" in ctype else ""
            if not ext or len(data) < 100:
                print("  skip", url, ctype, len(data))
                continue
            for old in OUT.glob(firm + ".*"):
                old.unlink()
            (OUT / f"{firm}.{ext}").write_bytes(data)
            print("  saved", url, ctype, len(data))
            ok += 1
            break
    print(ok, "of", len(FIRMS), "logos saved")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
