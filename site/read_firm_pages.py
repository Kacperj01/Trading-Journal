"""Print the text of prop firm rules pages into the Action log, so new firms' rules can be read and
checked when they're added (some firm sites can't be reached from where the journal is edited).

Reads the page list from site/firm-pages.txt (one URL per line, # for comments). For each page it
prints the readable text and any help-centre article and section links found on it. Changes nothing.
"""
import html, re, sys, urllib.request
from pathlib import Path

LIST = Path(__file__).resolve().parent / "firm-pages.txt"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ELEV8 Trading Journal rules reader)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", "replace")


def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|td|th|section|article)>", "\n", page)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in page.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def main():
    urls = [ln.strip() for ln in LIST.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    for url in urls:
        print("=" * 100, "\nPAGE", url, flush=True)
        try:
            page = fetch(url)
        except Exception as exc:  # keep going: one bad page shouldn't hide the others
            print("FAILED", exc)
            continue
        links = sorted(set(re.findall(r'href="(https?://[^"]*/(?:articles|collections)/[^"]+|/[^"]*/(?:articles|collections)/[^"]+)"', page)))
        print(text_of(page)[:30000])
        if links:
            print("\nHELP-CENTRE LINKS\n" + "\n".join(links))
    return 0


if __name__ == "__main__":
    sys.exit(main())
