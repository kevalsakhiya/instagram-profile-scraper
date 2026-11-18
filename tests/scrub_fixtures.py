"""Turn a saved Instagram page into a small, privacy-safe test fixture.

A logged-out Instagram page is ~800 KB and carries people's data the actor never outputs: up to a dozen
preview comments (commenter names, handles, photos, text) under a post, the owner's other posts with their
captions, @-mentions of people in captions, tagged users and collaborators. A fixture keeps only what the
parser reads, exactly as Instagram served it, and scrubs the people out of that:

* ``<title>`` and the ``og:*`` / ``description`` meta tags;
* the route excerpt from ``"rootView":`` to ``"polarisRouteConfig":{"pageID":"..."}`` (page type, profile id,
  age gating), wrapped in braces so it is valid JSON;
* the Relay preloads the parser reads (profile root, profile posts tab, post root), in their original
  ``ScheduledServerJS`` / ``RelayPrefetchedStreamCache`` wrapper. Inside the post root, the owner's timeline is
  dropped and the comments are replaced by one placeholder comment.

Scrubbing (also applied to the meta tags): every account that is not a brand or organisation on ``ALLOWED``
becomes ``redacted.person.N`` with name ``Redacted Person N``, id ``0`` and a placeholder photo; every
``@handle`` not on ``ALLOWED`` becomes ``@redacted.person.N``; names on ``NAMES`` become ``Redacted Person``.

People's names written out in kept caption text are listed one per line in ``raw/scrub_names.txt``, which is
git-ignored like the raw captures: the names to remove must never be committed themselves.

The reduction is idempotent: reducing a fixture gives the same bytes, which ``test_fixtures_privacy`` checks.

Usage: .venv/bin/python tests/scrub_fixtures.py raw/<name>.html.gz [...]   (writes tests/fixtures/<name>.html.gz)
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

ALLOWED = {
    # Brand and organisation accounts that may stay in fixtures.
    "nasa", "nike", "natgeo", "natgeotv", "nsw", "empirestatebldg", "nasahubble", "iss", "nasachandraxray",
    "explorecanada", "budweiser", "jackdaniels_us", "spaceneedle", "nasajpl", "rolex", "disneyplus", "hulu",
}
NAMES_FILE = Path(__file__).resolve().parent.parent / "raw" / "scrub_names.txt"


def load_names(path: Path = NAMES_FILE) -> tuple[str, ...]:
    """People named in kept caption text (git-ignored file, one name per line)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    return tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))


NAMES = load_names()
REDACTED = "redacted.person"
REDACTED_PIC = "https://scontent.cdninstagram.com/v/redacted-profile-picture.jpg"
REDACTED_COMMENT = "Redacted comment text."
KEPT_QUERIES = (
    "PolarisLoggedOutDesktopWWWProfileRootContentQuery",
    "PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery",
    "PolarisLoggedOutDesktopWWWPostRootContentQuery",
)
META_RE = re.compile(r'<meta (?:property="og:(?:title|description|url|type)"|content="[^"]*" name="description")[^>]*>')
TITLE_RE = re.compile(r"<title>[^<]*</title>")
SCRIPT_RE = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)
ROUTE_END_RE = re.compile(r'"polarisRouteConfig":\{[^{}]*"pageID":"\w+"[^{}]*\}')
MENTION_RE = re.compile(r"(?:@|&#064;)([A-Za-z0-9_.]{1,30})")
PERSON_KEYS = ("username", "full_name", "profile_pic_url", "profile_image_uri", "id", "pk")


class Scrubber:
    def __init__(self, names: tuple[str, ...] = ()) -> None:
        self.handles: dict[str, str] = {}
        self.names = names

    def handle(self, name: str) -> str:
        key = name.lower().rstrip(".")
        if key in ALLOWED or key.startswith(REDACTED):
            return name
        self.handles.setdefault(key, f"{REDACTED}.{len(self.handles) + 1}")
        return self.handles[key]

    def text(self, value: str) -> str:
        for name in self.names:
            for form in (name, "".join(c if ord(c) < 128 else f"&#x{ord(c):x};" for c in name)):
                value = value.replace(form, "Redacted Person")

        def mention(match: re.Match) -> str:
            raw = match.group(1)
            trailing = raw[len(raw.rstrip(".")):]
            return match.group(0)[: -len(raw)] + self.handle(raw.rstrip(".")) + trailing

        return MENTION_RE.sub(mention, value)

    def data(self, node, path: tuple[str, ...] = ()):
        if isinstance(node, list):
            return [self.data(item, path) for item in node]
        if isinstance(node, str):
            return self.text(node)
        if not isinstance(node, dict):
            return node
        node = dict(node)
        if "comments_connection" in node and isinstance(node["comments_connection"], dict):
            node["comments_connection"] = {**node["comments_connection"], "edges": [placeholder_comment()]}
        if path[-1:] == ("if_not_gated_logged_out",) and isinstance(node.get("user"), dict):
            # The owner's other posts on a post page: not read by the parser, full of other captions.
            node["user"] = {k: v for k, v in node["user"].items() if k != "polaris_ordered_timeline_connection"}
        username = node.get("username")
        if isinstance(username, str) and username != self.handle(username):
            alias = self.handle(username)
            number = alias.rsplit(".", 1)[-1]
            for key in PERSON_KEYS:
                if key in node:
                    node[key] = {
                        "username": alias,
                        "full_name": f"Redacted Person {number}",
                        "profile_pic_url": REDACTED_PIC,
                        "profile_image_uri": REDACTED_PIC,
                    }.get(key, "0")
        return {key: (value if key == "comments_connection" else self.data(value, (*path, key))) for key, value in node.items()}


def placeholder_comment() -> dict:
    return {
        "node": {
            "pk": "0",
            "created_at": 0,
            "user": {"username": f"{REDACTED}.commenter", "id": "0", "pk": "0", "profile_pic_url": REDACTED_PIC, "is_verified": False},
            "text": REDACTED_COMMENT,
            "comment_like_count": 0,
            "id": "0",
            "__typename": "XIGComment",
        },
        "cursor": None,
    }


def _relay_entries(page: str) -> list[tuple[str, dict]]:
    found = []
    for match in SCRIPT_RE.finditer(page):
        body = match.group(1)
        if "RelayPrefetchedStreamCache" not in body:
            continue
        try:
            doc = json.loads(body)
        except ValueError:
            continue

        def walk(node):
            if isinstance(node, list):
                if len(node) >= 4 and node[0] == "RelayPrefetchedStreamCache" and node[1] == "next":
                    key, value = node[3][0], node[3][1]
                    if any(q in key for q in KEPT_QUERIES):
                        found.append((key, value))
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                for item in node.values():
                    walk(item)

        walk(doc)
    return found


def _route_excerpt(page: str) -> str | None:
    end = ROUTE_END_RE.search(page)
    if not end:
        return None
    start = page.rfind('"rootView":', 0, end.start())
    return page[start : end.end()] if start >= 0 else None


def _script(content: str) -> str:
    return f'<script type="application/json" data-sjs>{content.replace("</", "<\\/")}</script>'


def reduce_page(page: str, names: tuple[str, ...] | None = None) -> str:
    scrub = Scrubber(NAMES if names is None else names)
    head = [TITLE_RE.search(page).group(0)] if TITLE_RE.search(page) else []
    head += [scrub.text(tag) for tag in META_RE.findall(page)]
    parts = ["<!DOCTYPE html>", "<html><head>", *head, "</head><body>"]
    route = _route_excerpt(page)
    if route:
        parts.append(_script("{" + scrub.text(route) + "}"))
    for key, value in _relay_entries(page):
        clean = scrub.data(value)
        wrapper = {"require": [["ScheduledServerJS", "handle", None, [{"__bbox": {"require": [
            ["RelayPrefetchedStreamCache", "next", [], [key, clean]]]}}]]]}
        parts.append(_script(json.dumps(wrapper, ensure_ascii=False, separators=(",", ":"))))
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def write_fixture(source: Path, target_dir: Path) -> Path:
    raw = gzip.decompress(source.read_bytes()).decode("utf-8")
    target = target_dir / source.name
    target.write_bytes(gzip.compress(reduce_page(raw).encode("utf-8"), mtime=0))
    return target


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "fixtures"
    for arg in sys.argv[1:]:
        print(write_fixture(Path(arg), out))
