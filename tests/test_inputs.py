"""Input cleaning, offline."""

from __future__ import annotations

import pytest

from instagram_profile.inputs import POST, PROFILE, collect_targets, normalize


@pytest.mark.parametrize(
    ("raw", "kind", "url"),
    [
        ("nasa", PROFILE, "https://www.instagram.com/nasa/"),
        ("@nasa", PROFILE, "https://www.instagram.com/nasa/"),
        ("  @NASA ", PROFILE, "https://www.instagram.com/NASA/"),
        ("nat.geo_1", PROFILE, "https://www.instagram.com/nat.geo_1/"),
        ("https://www.instagram.com/nasa/", PROFILE, "https://www.instagram.com/nasa/"),
        ("https://instagram.com/nasa?hl=en", PROFILE, "https://www.instagram.com/nasa/"),
        ("instagram.com/nasa", PROFILE, "https://www.instagram.com/nasa/"),
        ("www.instagram.com/nasa/reels/", PROFILE, "https://www.instagram.com/nasa/"),
        ("https://m.instagram.com/nasa/tagged/", PROFILE, "https://www.instagram.com/nasa/"),
        ("https://www.instagram.com/p/DfahZrMjAqq/", POST, "https://www.instagram.com/p/DfahZrMjAqq/"),
        ("https://www.instagram.com/p/DfahZrMjAqq/?img_index=2", POST, "https://www.instagram.com/p/DfahZrMjAqq/"),
        ("https://www.instagram.com/reel/Dfc1mYxFevS/", POST, "https://www.instagram.com/p/Dfc1mYxFevS/"),
        ("https://www.instagram.com/reels/Dfc1mYxFevS/", POST, "https://www.instagram.com/p/Dfc1mYxFevS/"),
        ("https://www.instagram.com/tv/Dfc1mYxFevS", POST, "https://www.instagram.com/p/Dfc1mYxFevS/"),
        ("https://www.instagram.com/nasa/reel/Dfc1mYxFevS/", POST, "https://www.instagram.com/p/Dfc1mYxFevS/"),
        ("https://www.instagram.com/nasa/p/Df-xWMD_LEa/", POST, "https://www.instagram.com/p/Df-xWMD_LEa/"),
    ],
)
def test_accepted(raw, kind, url):
    target, problem = normalize(raw)
    assert problem is None
    assert target.kind == kind
    assert target.url == url
    assert target.input == raw


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.facebook.com/nasa",
        "https://www.instagram.com/",
        "https://www.instagram.com/explore/tags/space/",
        "https://www.instagram.com/stories/nasa/123/",
        "https://www.instagram.com/accounts/login/",
        "https://www.instagram.com/share/p/abc123/",
        "https://www.instagram.com/p/",
        "https://www.instagram.com/p/a!b/",
        "https://www.instagram.com/nasa/something/",
        "explore",
        "has space",
        "a" * 31,
        ".nasa",
        "na..sa",
        "nasa!",
        "@",
    ],
)
def test_rejected(raw):
    target, problem = normalize(raw)
    assert target is None and problem


def test_collect_targets_dedup_mixed_lists_and_order():
    targets, problems = collect_targets(
        ["nasa", "@NASA", "https://www.instagram.com/nasa/", "https://www.instagram.com/p/DfahZrMjAqq/", "", "bad name", {"url": "nike"}],
        ["https://www.instagram.com/reel/DfahZrMjAqq/", "https://www.instagram.com/natgeo/", "https://x.com/a", None],
    )
    assert [(t.kind, t.value) for t in targets] == [
        (PROFILE, "nasa"),
        (PROFILE, "nike"),
        (PROFILE, "natgeo"),
        (POST, "DfahZrMjAqq"),
    ]
    assert [(raw, kind) for raw, kind, _ in problems] == [("bad name", PROFILE), ("https://x.com/a", POST)]


def test_collect_targets_empty():
    assert collect_targets(None, None) == ([], [])
    assert collect_targets(["", "  "], []) == ([], [])


def test_a_single_string_instead_of_a_list_is_not_split_into_characters():
    targets, problems = collect_targets("nasa\n@nike", "https://www.instagram.com/p/DfahZrMjAqq/")
    assert [(t.kind, t.value) for t in targets] == [("profile", "nasa"), ("profile", "nike"), ("post", "DfahZrMjAqq")]
    assert problems == []
