"""Capture logged-out Instagram pages for exploration and fixtures.

Usage: .venv/bin/python tools/capture.py name=url [name=url ...]

Raw responses go to raw/ (git-ignored, may hold personal data). One fresh session per request,
3-6 s apart. Redirects are NOT followed: the status and location are recorded in raw/index.json.
Scrub with tests/scrub_fixtures.py before anything is copied into tests/fixtures/.
"""

from __future__ import annotations

import gzip
import json
import random
import sys
import time
from pathlib import Path

from curl_cffi import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from instagram_profile.fetch import NAV_HEADERS  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "raw"


def main(pairs: list[str]) -> None:
    RAW.mkdir(exist_ok=True)
    index_path = RAW / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for i, pair in enumerate(pairs):
        name, url = pair.split("=", 1)
        if i:
            time.sleep(random.uniform(3, 6))
        resp = requests.get(url, headers=NAV_HEADERS, impersonate="chrome", allow_redirects=False, timeout=30)
        body = resp.text or ""
        (RAW / f"{name}.html.gz").write_bytes(gzip.compress(body.encode("utf-8"), mtime=0))
        index[name] = {
            "requestedUrl": url,
            "status": resp.status_code,
            "location": resp.headers.get("location"),
            "bytes": len(body),
        }
        print(name, resp.status_code, resp.headers.get("location"), len(body))
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
