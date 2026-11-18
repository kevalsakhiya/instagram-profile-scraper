"""Reading profile and post data from the HTML Instagram serves to logged-out visitors.

Pages are ~800 KB, so nothing here builds a DOM. Instagram embeds the data in
``<script type="application/json" data-sjs>`` blocks as Relay preloads:
``["RelayPrefetchedStreamCache", "next", [], ["adp_<QueryName>RelayPreloader_<id>", {"__bbox": {"result": {"data": ...}}}]]``.
Only script blocks containing ``RelayPrefetchedStreamCache`` are JSON-decoded.

Keys used (verified on live pages, 2026-11-18):

Route (regex on the raw HTML)
  ``"polarisRouteConfig":{...,"pageID":"profilePage|postPage|httpErrorPage"}`` -> what page this is.
  ``"rootView":{..."props":{"id": <profile pk>, "gating": null | {"title","description"}}`` -> age/country
  gating of a profile (then the profile data is null).

Profile page, query ``PolarisLoggedOutDesktopWWWProfileRootContentQuery`` -> ``data.xig_user_by_username``:
  ``pk`` (user id), ``username``, ``full_name``, ``biography``, ``is_verified``, ``is_private``,
  ``follower_count``, ``following_count`` (exact), ``profile_pic_url``,
  ``bio_links[].url`` / ``.title`` / ``.lynx_url`` (the ``u=`` parameter when ``url`` is empty).
  The post count is not in the JSON (``all_media_count`` is null): it is read from
  ``<meta property="og:description" content="268M Followers, 196 Following, 32K Posts - ...">``, which
  Instagram rounds above 9,999 (``32K``).
  Not shown to logged-out visitors: category, business/professional flags, contact buttons.

Profile page, query ``PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery`` ->
  ``data.xig_user_by_username.polaris_ordered_timeline_connection.edges[].node``: ``code`` (shortcode),
  ``pk``, ``media_type``, ``product_type``, ``user.username``. Twelve posts, pinned posts first, no counts.

Post page, query ``PolarisLoggedOutDesktopWWWPostRootContentQuery`` -> ``data.xig_polaris_media``:
  ``if_not_gated_logged_out`` holds the post (null when the post is gated, see ``gating_ruling``):
  ``code``, ``pk``, ``taken_at`` (unix), ``media_type`` (1 photo, 2 video, 8 carousel), ``product_type``
  (``clips`` = reel), ``caption.text``, ``like_count``, ``like_and_view_counts_disabled``, ``comment_count``,
  ``display_uri`` / ``image_versions2.candidates[0].url``, ``video_versions[0].url``, ``carousel_media[]``,
  ``user.pk`` / ``user.username`` (owner), ``coauthor_producers`` (collab), ``location.name``.
  Up to a dozen preview comments sit in ``comments_connection``; they are deliberately never read.
  View and play counts are not shown to logged-out visitors.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

PROFILE_ROOT_QUERY = "PolarisLoggedOutDesktopWWWProfileRootContentQuery"
PROFILE_POSTS_QUERY = "PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery"
POST_ROOT_QUERY = "PolarisLoggedOutDesktopWWWPostRootContentQuery"

SCRIPT_RE = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)
PAGE_ID_RE = re.compile(r'"polarisRouteConfig":\{[^{}]*"pageID":"(\w+)"')
ROOT_PROPS_RE = re.compile(r'"rootView":\{"allResources":\[[^\]]*\],"resource":\{[^{}]*\},"props":')
OG_DESCRIPTION_RE = re.compile(r'<meta property="og:description" content="([^"]*)"')
COUNT_RE = re.compile(r"([\d.,]+)\s*([KMB])?\s+(Followers|Following|Posts)\b", re.I)
HASHTAG_RE = re.compile(r"(?<![\w&])#(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{1,30})")

MEDIA_TYPES = {1: "photo", 2: "video", 8: "carousel"}


@dataclass
class ParsedProfile:
    kind: str  # "profile", "private", "restricted", "notFound", "missing"
    fields: dict[str, Any] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)  # timeline nodes: shortcode, mediaId, type, owner
    message: str | None = None


@dataclass
class ParsedPost:
    kind: str  # "post", "restricted", "notFound", "missing"
    fields: dict[str, Any] = field(default_factory=dict)
    message: str | None = None


# -- generic extraction ------------------------------------------------------------


def page_id(page: str) -> str | None:
    match = PAGE_ID_RE.search(page)
    return match.group(1) if match else None


def root_props(page: str) -> dict:
    """The route's ``rootView.props`` object (profile id, gating, media id)."""
    match = ROOT_PROPS_RE.search(page)
    if not match:
        return {}
    try:
        value, _end = json.JSONDecoder().raw_decode(page, match.end())
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def relay_data(page: str) -> dict[str, Any]:
    """{query name: result.data} for every Relay preload in the page."""
    found: dict[str, Any] = {}

    def walk(node) -> None:
        if isinstance(node, list):
            if len(node) >= 4 and node[0] == "RelayPrefetchedStreamCache" and node[1] == "next":
                try:
                    key, payload = node[3][0], node[3][1]
                    data = payload["__bbox"]["result"]["data"]
                except (IndexError, KeyError, TypeError):
                    return
                name = key.split("RelayPreloader")[0].removeprefix("adp_")
                found.setdefault(name, data)
                return
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    for match in SCRIPT_RE.finditer(page):
        body = match.group(1)
        if "RelayPrefetchedStreamCache" not in body:
            continue
        try:
            walk(json.loads(body))
        except ValueError:
            continue
    return found


def parse_count(text: str) -> int | None:
    """'1,676' -> 1676, '32K' -> 32000, '1.2M' -> 1200000."""
    match = re.fullmatch(r"\s*([\d.,]+)\s*([KMB])?\s*", text or "", re.I)
    if not match:
        return None
    number, suffix = match.groups()
    if suffix:
        try:
            return int(round(float(number.replace(",", "")) * {"K": 1e3, "M": 1e6, "B": 1e9}[suffix.upper()]))
        except ValueError:
            return None
    digits = number.replace(",", "").replace(".", "")
    return int(digits) if digits.isdigit() else None


def meta_counts(page: str) -> dict[str, int | None]:
    """Followers/Following/Posts from the og:description meta tag (rounded by Instagram above 9,999)."""
    match = OG_DESCRIPTION_RE.search(page)
    counts: dict[str, int | None] = {"followers": None, "following": None, "posts": None}
    if not match:
        return counts
    text = htmllib.unescape(match.group(1)).split(" - ", 1)[0]
    for number, suffix, label in COUNT_RE.findall(text):
        counts[label.lower()] = parse_count(number + (suffix or ""))
    return counts


def iso(timestamp) -> str | None:
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return None
    return datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat()


def hashtags(text: str | None) -> list[str]:
    return _unique(HASHTAG_RE.findall(text or ""))


def mentions(text: str | None) -> list[str]:
    return _unique(m.rstrip(".") for m in MENTION_RE.findall(text or "") if m.rstrip("."))


def _unique(items) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.lower(), item)
    return list(seen.values())


def media_type(media_type_code, product_type: str | None) -> str | None:
    kind = MEDIA_TYPES.get(media_type_code)
    if kind == "video" and product_type == "clips":
        return "reel"
    return kind


def _first_url(node: dict | None) -> str | None:
    if not isinstance(node, dict):
        return None
    if node.get("display_uri"):
        return node["display_uri"]
    candidates = (node.get("image_versions2") or {}).get("candidates") or []
    return candidates[0].get("url") if candidates and isinstance(candidates[0], dict) else None


def _video_url(node: dict | None) -> str | None:
    versions = (node or {}).get("video_versions") or []
    return versions[0].get("url") if versions and isinstance(versions[0], dict) else None


def _link_url(link: dict) -> str | None:
    if link.get("url"):
        return link["url"]
    lynx = link.get("lynx_url") or ""
    target = parse_qs(urlparse(lynx).query).get("u")
    return target[0] if target else None


def _str(value) -> str | None:
    return str(value) if value not in (None, "") else None


# -- profile -------------------------------------------------------------------------


def parse_profile(page: str) -> ParsedProfile:
    kind = page_id(page)
    if kind == "httpErrorPage":
        return ParsedProfile("notFound", message="Instagram says this page isn't available: the username does not exist or was changed.")
    if kind != "profilePage":
        return ParsedProfile("missing", message="The response was not a profile page.")

    props = root_props(page)
    data = relay_data(page)
    user = (data.get(PROFILE_ROOT_QUERY) or {}).get("xig_user_by_username")
    counts = meta_counts(page)

    if not isinstance(user, dict):
        gating = props.get("gating")
        if isinstance(gating, dict):
            fields = {
                "userId": _str(props.get("id")),
                "followersCount": counts["followers"],
                "followingCount": counts["following"],
                "postsCount": counts["posts"],
            }
            reason = ". ".join(x.strip().rstrip(".") for x in (gating.get("title"), gating.get("description")) if x) or "Restricted profile"
            return ParsedProfile("restricted", fields, message=f"Instagram hides this profile from logged-out visitors: {reason}.")
        return ParsedProfile("missing", message="The profile page had no profile data.")

    links = [
        {"title": link.get("title") or None, "url": _link_url(link)}
        for link in user.get("bio_links") or []
        if isinstance(link, dict) and _link_url(link)
    ]
    username = user.get("username")
    fields = {
        "username": username,
        "fullName": user.get("full_name") or None,
        "userId": _str(user.get("pk") or props.get("id")),
        "url": f"https://www.instagram.com/{username}/" if username else None,
        "biography": user.get("biography") or None,
        "externalUrls": links,
        "externalUrl": links[0]["url"] if links else None,
        "isVerified": bool(user.get("is_verified")),
        "isPrivate": bool(user.get("is_private")),
        "followersCount": user.get("follower_count") if isinstance(user.get("follower_count"), int) else counts["followers"],
        "followingCount": user.get("following_count") if isinstance(user.get("following_count"), int) else counts["following"],
        "postsCount": user.get("media_count") if isinstance(user.get("media_count"), int) else counts["posts"],
        "profilePicUrl": user.get("profile_pic_url") or None,
    }

    timeline = ((data.get(PROFILE_POSTS_QUERY) or {}).get("xig_user_by_username") or {}).get(
        "polaris_ordered_timeline_connection"
    ) or {}
    recent = []
    for edge in timeline.get("edges") or []:
        node = (edge or {}).get("node") or {}
        code = node.get("code")
        if not code:
            continue
        recent.append(
            {
                "shortcode": code,
                "mediaId": _str(node.get("pk")),
                "type": media_type(node.get("media_type"), node.get("product_type")),
                "ownerUsername": (node.get("user") or {}).get("username"),
                "url": f"https://www.instagram.com/p/{code}/",
            }
        )
    if fields["isPrivate"]:
        return ParsedProfile("private", fields, [], message="This account is private: only its profile details are public.")
    return ParsedProfile("profile", fields, recent)


# -- post ----------------------------------------------------------------------------


def parse_post(page: str) -> ParsedPost:
    kind = page_id(page)
    if kind == "httpErrorPage":
        return ParsedPost("notFound", message="Instagram says this post isn't available: it was deleted, or the link is wrong.")
    if kind != "postPage":
        return ParsedPost("missing", message="The response was not a post page.")

    media = (relay_data(page).get(POST_ROOT_QUERY) or {}).get("xig_polaris_media")
    if not isinstance(media, dict):
        return ParsedPost("missing", message="The post page had no post data.")
    node = media.get("if_not_gated_logged_out")
    if not isinstance(node, dict):
        if media.get("gating_ruling"):
            return ParsedPost("restricted", message="Instagram hides this post from logged-out visitors (sensitive or age-restricted content).")
        return ParsedPost("missing", message="The post page had no post data.")

    code = node.get("code") or media.get("code")
    kind_name = media_type(node.get("media_type"), node.get("product_type"))
    caption = ((node.get("caption") or {}).get("text")) or None
    hidden = bool(node.get("like_and_view_counts_disabled"))
    owner = node.get("user") or {}
    children = [c for c in node.get("carousel_media") or [] if isinstance(c, dict)]
    display = _first_url(node) or (_first_url(children[0]) if children else None)
    image_urls = [u for u in (_first_url(c) for c in children) if u] if children else ([display] if display else [])
    video = _video_url(node)
    if video is None and children:
        video = next((u for u in (_video_url(c) for c in children) if u), None)

    fields = {
        "shortcode": code,
        "url": f"https://www.instagram.com/p/{code}/" if code else None,
        "mediaId": _str(node.get("pk") or media.get("pk")),
        "type": kind_name,
        "takenAt": iso(node.get("taken_at")),
        "caption": caption,
        "hashtags": hashtags(caption),
        "mentions": mentions(caption),
        "likeCount": None if hidden or not isinstance(node.get("like_count"), int) else node["like_count"],
        "commentCount": node.get("comment_count") if isinstance(node.get("comment_count"), int) else None,
        "displayUrl": display,
        "imageUrls": image_urls,
        "videoUrl": video,
        "carouselMediaCount": len(children) if children else None,
        "ownerUsername": owner.get("username"),
        "ownerId": _str(owner.get("pk")),
        "isCollab": bool(node.get("coauthor_producers")),
        "locationName": (node.get("location") or {}).get("name") or None,
    }
    return ParsedPost("post", fields)
