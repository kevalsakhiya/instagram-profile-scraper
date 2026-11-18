"""Row layout and the engagement figures."""

from __future__ import annotations

from instagram_profile import output
from instagram_profile.output import (
    FIELDS,
    build_error_row,
    build_post_row,
    build_profile_row,
    engagement_rate,
    profile_metrics,
    regular_posts,
)


def stat(likes, comments, taken):
    return {"likeCount": likes, "commentCount": comments, "takenAt": taken}


def test_engagement_rate():
    assert engagement_rate(900, 100, 100_000) == 1.0
    assert engagement_rate(13005, 50, 268103035) == 0.0049
    assert engagement_rate(None, 10, 100) is None
    assert engagement_rate(10, None, 100) == 10.0
    assert engagement_rate(10, 1, 0) is None
    assert engagement_rate(10, 1, None) is None


def test_pinned_posts_are_left_out_of_the_frequency():
    # Grid order: two pinned (old) posts first, then newest-first.
    stats = [
        stat(10, 1, "2026-01-01T00:00:00+00:00"),
        stat(10, 1, "2026-03-01T00:00:00+00:00"),
        stat(10, 1, "2026-11-15T00:00:00+00:00"),
        stat(10, 1, "2026-11-08T00:00:00+00:00"),
        stat(10, 1, "2026-11-01T00:00:00+00:00"),
    ]
    assert [s["takenAt"][:10] for s in regular_posts(stats)] == ["2026-11-15", "2026-11-08", "2026-11-01"]
    metrics = profile_metrics(stats, 1000)
    assert metrics["postingFrequencyPerWeek"] == 1.0  # 2 gaps over 2 weeks
    assert metrics["lastPostAt"] == "2026-11-15T00:00:00+00:00"
    assert metrics["recentPostsAnalysed"] == 5
    assert metrics["avgLikes"] == 10.0 and metrics["avgComments"] == 1.0
    assert metrics["engagementRatePct"] == 1.1


def test_only_the_top_three_can_be_pinned():
    stats = [stat(1, 1, f"2026-11-{d:02d}T00:00:00+00:00") for d in (20, 19, 18, 10, 17)]
    # The 4th post is out of order but can't be pinned; it stays.
    assert len(regular_posts(stats)) == 5


def test_metrics_edge_cases():
    empty = profile_metrics([], 1000)
    assert empty == {
        "recentPostsAnalysed": 0,
        "avgLikes": None,
        "avgComments": None,
        "engagementRatePct": None,
        "postingFrequencyPerWeek": None,
        "lastPostAt": None,
    }
    hidden = profile_metrics([stat(None, 5, "2026-11-01T00:00:00+00:00")], 1000)
    assert hidden["avgLikes"] is None and hidden["avgComments"] == 5.0 and hidden["engagementRatePct"] is None
    assert hidden["postingFrequencyPerWeek"] is None  # one post: no frequency
    same_time = profile_metrics([stat(1, 1, "2026-11-01T00:00:00+00:00")] * 2, 1000)
    assert same_time["postingFrequencyPerWeek"] is None


def test_rows_have_every_key_in_order():
    profile = build_profile_row("nasa", {"username": "nasa", "followersCount": 10}, stats=None, recent_urls=[])
    post = build_post_row("nasa", {"shortcode": "abc", "likeCount": 5, "commentCount": 1}, followers=100)
    error = build_error_row(output.POST, "x", output.NOT_FOUND, "gone", url="https://www.instagram.com/p/x/")
    for row in (profile, post, error):
        assert list(row) == list(FIELDS)
    assert profile["recordType"] == "profile" and profile["recentPostsAnalysed"] == 0 and profile["avgLikes"] is None
    assert post["recordType"] == "post" and post["engagementRatePct"] == 6.0
    assert post["hashtags"] == [] and post["imageUrls"] == []
    assert {k for k, v in error.items() if v is not None} == {"recordType", "inputUrl", "url", "error", "errorMessage", "scrapedAt"}


def test_error_row_with_public_fields():
    row = build_error_row(output.PROFILE, "x", output.PRIVATE_PROFILE, "private", url="u", fields={"username": "x", "url": "https://www.instagram.com/x/", "followersCount": 5})
    assert row["followersCount"] == 5 and row["url"] == "https://www.instagram.com/x/"
    assert row["recordType"] == "profile" and row["inputUrl"] == "x"
