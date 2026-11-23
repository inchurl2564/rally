"""
IndexNow: tell Bing (and the engines that share IndexNow: Yandex, Seznam, Naver...) which pages the
nightly edition added or changed, so they're indexed in hours instead of weeks. Free; no account.
The key is public by design: it's the file site/aeeb3c4722e288d25b4ec2350b972e25.txt, which proves we own the site.

  python tools/indexnow.py [git range]     (default HEAD~1..HEAD: the edition just committed)
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

HOST = "therallyback.com"
KEY = "aeeb3c4722e288d25b4ec2350b972e25"
ENDPOINT = "https://api.indexnow.org/indexnow"


def changed_urls(rng: str) -> list[str]:
    files = subprocess.run(["git", "diff", "--name-only", rng, "--", "site/w", "site/week", "site/index.html"],
                           capture_output=True, text=True).stdout.split()
    urls = set()
    for f in files:
        if f == "site/index.html":
            urls.add(f"https://{HOST}/")
        elif f.startswith("site/w/") and f.endswith(".html"):
            urls.add(f"https://{HOST}/w/{f[7:-5]}")            # Cloudflare serves pages without .html
        elif f.startswith("site/week/") and f.endswith(".html"):
            name = f[10:-5]
            urls.add(f"https://{HOST}/week/" if name == "index" else f"https://{HOST}/week/{name}")
    return sorted(urls)


def main() -> None:
    urls = changed_urls(sys.argv[1] if len(sys.argv) > 1 else "HEAD~1..HEAD")
    if not urls:
        print("IndexNow: nothing changed")
        return
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt",
                       "urlList": urls[:10000]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow: sent {len(urls)} pages, HTTP {r.status}")
    except Exception as e:                       # never fail the nightly run over this
        print(f"IndexNow: not sent ({e})")


if __name__ == "__main__":
    main()
