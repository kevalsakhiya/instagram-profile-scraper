"""Dataset rows. Every row has every key, in the same order, with null for missing values, so CSV
and Excel exports always get the same columns. ``recordType`` says whether a row is a profile or a
post; error rows keep the record type of what was attempted."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Error codes. Error rows are never charged.
INVALID_INPUT = "invalidInput"
NOT_FOUND = "notFound"
PRIVATE_PROFILE = "privateProfile"
RESTRICTED = "restricted"
LOGIN_REQUIRED = "loginRequired"
BLOCKED = "blocked"
FAILED = "failed"

PROFILE = "profile"
POST = "post"

PROFILE_FIELDS: tuple[str, ...] = (
    "username",
    "fullName",
    "userId",
    "biography",
    "externalUrl",
    "externalUrls",
    "isVerified",
    "isPrivate",
    "followersCount",
    "followingCount",
    "postsCount",
    "profilePicUrl",
    "recentPostsAnalysed",
    "avgLikes",
    "avgComments",
    "postingFrequencyPerWeek",
    "lastPostAt",
    "recentPostUrls",
)
POST_FIELDS: tuple[str, ...] = (
    "shortcode",
    "mediaId",
    "type",
    "takenAt",
    "caption",
    "hashtags",
    "mentions",
    "likeCount",
    "commentCount",
    "displayUrl",
    "imageUrls",
    "videoUrl",
    "carouselMediaCount",
    "ownerUsername",
    "ownerId",
    "isCollab",
    "locationName",
)
FIELDS: tuple[str, ...] = (
    "recordType",
    "inputUrl",
    "url",
    *PROFILE_FIELDS,
    "engagementRatePct",
    *POST_FIELDS,
    "scrapedAt",
    "error",
    "errorMessage",
)

MAX_PINNED = 3  # Instagram lets an account pin up to 3 posts to the top of its grid


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty(record_type: str, input_url: str) -> dict[str, Any]:
    row = dict.fromkeys(FIELDS)
    row["recordType"] = record_type
    row["inputUrl"] = input_url
    return row


def _fill(row: dict, fields: dict) -> None:
    for key, value in fields.items():
        if key in row and key not in ("recordType", "inputUrl"):
            row[key] = value


def engagement_rate(likes: float | None, comments: float | None, followers: int | None) -> float | None:
    """(likes + comments) / followers * 100, or None without likes or followers."""
    if likes is None or not followers:
        return None
    return round((likes + (comments or 0)) / followers * 100, 4)


def build_post_row(input_url: str, fields: dict, *, followers: int | None = None, scraped_at: str | None = None) -> dict:
    row = _empty(POST, input_url)
    _fill(row, fields)
    row["hashtags"] = list(fields.get("hashtags") or [])
    row["mentions"] = list(fields.get("mentions") or [])
    row["imageUrls"] = list(fields.get("imageUrls") or [])
    row["engagementRatePct"] = engagement_rate(row["likeCount"], row["commentCount"], followers)
    row["scrapedAt"] = scraped_at or now_iso()
    return row


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def regular_posts(stats: list[dict]) -> list[dict]:
    """Drop pinned posts from the head of the grid (in grid order) for the posting frequency.

    The grid is newest first, except up to 3 pinned posts at the top. A post near the top that is
    older than a post after it can only be there because it is pinned. A pinned post that is also the
    newest can't be told apart, and doesn't change the result much.
    """
    times = [_parse_time(s.get("takenAt")) for s in stats]
    keep = []
    for i, (stat, taken) in enumerate(zip(stats, times)):
        later = [t for t in times[i + 1 :] if t]
        if i < MAX_PINNED and taken and later and taken < max(later):
            continue
        keep.append(stat)
    return keep


def profile_metrics(stats: list[dict], followers: int | None) -> dict[str, Any]:
    """Aggregates over the recent posts fetched (``stats`` in grid order: likeCount, commentCount, takenAt)."""
    likes = [s["likeCount"] for s in stats if isinstance(s.get("likeCount"), int)]
    comments = [s["commentCount"] for s in stats if isinstance(s.get("commentCount"), int)]
    avg_likes = round(sum(likes) / len(likes), 1) if likes else None
    avg_comments = round(sum(comments) / len(comments), 1) if comments else None

    times = [t for t in (_parse_time(s.get("takenAt")) for s in stats) if t]
    regular = [t for t in (_parse_time(s.get("takenAt")) for s in regular_posts(stats)) if t]
    frequency = None
    if len(regular) >= 2:
        span = max(regular) - min(regular)
        if span > timedelta(0):
            frequency = round((len(regular) - 1) / (span / timedelta(weeks=1)), 2)
    return {
        "recentPostsAnalysed": len(stats),
        "avgLikes": avg_likes,
        "avgComments": avg_comments,
        "engagementRatePct": engagement_rate(avg_likes, avg_comments, followers),
        "postingFrequencyPerWeek": frequency,
        "lastPostAt": max(times).isoformat() if times else None,
    }


def build_profile_row(
    input_url: str,
    fields: dict,
    *,
    stats: list[dict] | None,
    recent_urls: list[str],
    scraped_at: str | None = None,
) -> dict:
    """A profile row. ``stats`` is None when recent posts were not fetched."""
    row = _empty(PROFILE, input_url)
    _fill(row, fields)
    row["externalUrls"] = list(fields.get("externalUrls") or [])
    row["recentPostUrls"] = list(recent_urls)
    if stats is None:
        row["recentPostsAnalysed"] = 0
    else:
        row.update(profile_metrics(stats, fields.get("followersCount")))
    row["scrapedAt"] = scraped_at or now_iso()
    return row


def build_error_row(
    record_type: str,
    input_url: str,
    error: str,
    message: str,
    *,
    url: str | None = None,
    fields: dict | None = None,
    scraped_at: str | None = None,
) -> dict:
    """A free error row. ``fields`` adds what is public (for private and restricted profiles)."""
    row = _empty(record_type, input_url)
    if fields:
        _fill(row, fields)
        if "externalUrls" in fields:
            row["externalUrls"] = list(fields.get("externalUrls") or [])
    if url and not row["url"]:
        row["url"] = url
    row["error"] = error
    row["errorMessage"] = message
    row["scrapedAt"] = scraped_at or now_iso()
    return row
