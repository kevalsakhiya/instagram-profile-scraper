"""Input cleaning. No Apify or network imports, so it is easy to test.

Accepted forms:
- profiles: ``nasa``, ``@nasa``, ``https://www.instagram.com/nasa/`` (also ``/nasa/reels/``, ``/nasa/tagged/``,
  ``instagram.com/nasa?hl=en``, ``m.instagram.com/nasa``)
- posts: ``https://www.instagram.com/p/<shortcode>/``, ``/reel/<shortcode>/``, ``/reels/<shortcode>/``,
  ``/tv/<shortcode>/``, ``/<username>/p/<shortcode>/``, ``/<username>/reel/<shortcode>/``

A post link in the profile list is scraped as a post and a profile link in the post list as a profile, so a
mixed list just works. Bad entries never fail the run: each becomes one free 'invalidInput' row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

PROFILE = "profile"
POST = "post"

INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,64}$")
POST_PATHS = {"p", "reel", "reels", "tv"}
PROFILE_SUBPAGES = {"reels", "tagged", "saved", "feed", "guides", "channel", "followers", "following"}

# First path parts that are Instagram features, not usernames.
NOT_PROFILES = {
    "explore": "Explore, hashtag and location links are not supported. Use a profile or post link.",
    "stories": "Stories need a login and are not supported. Use a profile or post link.",
    "highlights": "Highlights need a login and are not supported. Use a profile or post link.",
    "direct": "Direct messages are not supported.",
    "accounts": "Account pages are not supported. Use a profile or post link.",
    "share": "Share links are not supported. Open the link in a browser and paste the post or profile link it leads to.",
    "s": "Share links are not supported. Open the link in a browser and paste the post or profile link it leads to.",
}
NOT_PROFILES_GENERIC = {
    "about", "legal", "privacy", "terms", "developer", "developers", "web", "challenge", "login", "signup",
    "emails", "session", "press", "api", "graphql", "static", "ajax", "oauth", "help", "lite", "popular",
    "locations", "topics", "your_activity", "notifications", "meta", "threads", "invites", "music",
}


@dataclass(frozen=True)
class Target:
    """One profile or post to scrape. ``key`` drops duplicate inputs."""

    kind: str  # PROFILE or POST
    input: str
    url: str
    key: str
    value: str  # username or shortcode


def _profile(raw: str, username: str) -> Target:
    return Target(PROFILE, raw, f"https://www.instagram.com/{username}/", f"user:{username.lower()}", username)


def _post(raw: str, shortcode: str) -> Target:
    return Target(POST, raw, f"https://www.instagram.com/p/{shortcode}/", f"post:{shortcode}", shortcode)


def _check_username(name: str) -> str | None:
    if not USERNAME_RE.match(name) or name.startswith(".") or name.endswith(".") or ".." in name:
        return "not a valid Instagram username"
    if name.lower() in NOT_PROFILES or name.lower() in NOT_PROFILES_GENERIC or name.lower() in POST_PATHS:
        return f"'{name}' is an Instagram page, not a username"
    return None


def normalize(raw: str) -> tuple[Target | None, str | None]:
    """Return (target, None) or (None, why it can't be used)."""
    text = (raw or "").strip().strip("\"'").strip()
    if not text:
        return None, "empty input"

    looks_like_url = re.match(r"^[a-z][a-z0-9+.\-]*://", text, re.I) or "/" in text or re.match(
        r"^(?:www\.|m\.)?(?:instagram\.com|instagr\.am)\b", text, re.I
    )
    if not looks_like_url:
        name = text.removeprefix("@").strip()
        problem = _check_username(name)
        return (None, problem) if problem else (_profile(raw, name), None)

    url = text if re.match(r"^https?://", text, re.I) else "https://" + text.lstrip("/")
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if host not in INSTAGRAM_HOSTS:
        return None, "not an Instagram link"
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None, "the link has no profile or post in it"

    first = parts[0].lower()
    if first in POST_PATHS:
        if len(parts) >= 2 and SHORTCODE_RE.match(parts[1]):
            return _post(raw, parts[1]), None
        return None, "post link without a valid post code"
    if first in NOT_PROFILES:
        return None, NOT_PROFILES[first]
    if len(parts) >= 3 and parts[1].lower() in POST_PATHS:
        # /<username>/p/<shortcode>/ and /<username>/reel/<shortcode>/
        if SHORTCODE_RE.match(parts[2]):
            return _post(raw, parts[2]), None
        return None, "post link without a valid post code"
    if first in NOT_PROFILES_GENERIC:
        return None, "not an Instagram profile or post link"
    if len(parts) >= 2 and parts[1].lower() not in PROFILE_SUBPAGES:
        return None, "not an Instagram profile or post link"
    problem = _check_username(parts[0])
    return (None, problem) if problem else (_profile(raw, parts[0]), None)


def _strings(items) -> list[str]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(str(item.get("url") or item.get("username") or ""))
        elif item is not None:
            out.append(str(item))
    return out


def collect_targets(usernames, post_urls) -> tuple[list[Target], list[tuple[str, str, str]]]:
    """Turn the two input lists into (unique targets in input order, [(input, kind, problem)]).

    Profiles come first, then posts. ``kind`` of a problem is the list it came from.
    """
    targets: list[Target] = []
    problems: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for kind, entries in ((PROFILE, _strings(usernames)), (POST, _strings(post_urls))):
        for entry in entries:
            target, problem = normalize(entry)
            if target is None:
                if problem != "empty input":
                    problems.append((entry.strip(), kind, problem or "invalid input"))
                continue
            if target.key in seen:
                continue
            seen.add(target.key)
            targets.append(target)
    targets.sort(key=lambda t: 0 if t.kind == PROFILE else 1)
    return targets, problems
