"""Check the prop firm rules pages for changes and open a GitHub issue when one changes.

The rules themselves live in index.html (<script id="propRules">) and are checked by hand;
this only says when a source page's wording has changed so the numbers get reviewed.
Page text (scripts, styles and tags stripped) is hashed and stored in site/prop-rules-hashes.json.
"""
import hashlib
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
HASHES = root / "site" / "prop-rules-hashes.json"


def sources():
    page = (root / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="propRules">\s*(.*?)\s*</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    out = {}
    for firm in data["firms"]:
        for prog in firm["programs"]:
            for url in prog.get("sources", []):
                out.setdefault(url, []).append(f'{firm["name"]} · {prog["name"]}')
    return out


def page_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ELEV8 Trading Journal rules watcher)"})
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read().decode("utf-8", "replace")
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()


def open_issue(changed):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token; not opening an issue")
        return
    body = "These prop firm rules pages changed since the last check. Review the numbers in `index.html` (`propRules`) and update `checked`.\n\n"
    body += "\n".join(f"- [{url}]({url}) ({', '.join(sorted(set(progs)))})" for url, progs in changed.items())
    api = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "elev8-rules-watcher"}
    # Add to an open review issue if there is one, instead of opening another.
    req = urllib.request.Request(api + "?state=open&labels=prop-rules", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        open_issues = json.load(res)
    if open_issues:
        url, payload = open_issues[0]["comments_url"], {"body": body}
    else:
        url, payload = api, {"title": "Prop firm rules pages changed: review needed", "body": body, "labels": ["prop-rules"]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=30).close()
    print("Reported", len(changed), "changed page(s)")


def main():
    old = json.loads(HASHES.read_text(encoding="utf-8")) if HASHES.exists() else {}
    new, changed, failed = {}, {}, []
    for url, progs in sources().items():
        try:
            digest = hashlib.sha256(page_text(url).encode()).hexdigest()
        except Exception as exc:  # blocked or down: keep the old hash, try again tomorrow
            failed.append(f"{url}: {exc}")
            if url in old:
                new[url] = old[url]
            continue
        new[url] = digest
        if url in old and old[url] != digest:
            changed[url] = progs
    HASHES.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for f in failed:
        print("could not fetch", f, file=sys.stderr)
    print(f"{len(new) - len(failed)} pages checked, {len(changed)} changed, {len(failed)} failed")
    if changed:
        open_issue(changed)


if __name__ == "__main__":
    main()
