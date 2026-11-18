"""Parsing the real (reduced, scrubbed) pages captured on 2026-11-18."""

from __future__ import annotations

import pytest

from instagram_profile.parser import (
    hashtags,
    media_type,
    mentions,
    meta_counts,
    page_id,
    parse_count,
    parse_post,
    parse_profile,
    root_props,
)

from .helpers import html


def test_nasa_profile():
    parsed = parse_profile(html("nasa"))
    assert parsed.kind == "profile"
    f = parsed.fields
    assert f["username"] == "nasa"
    assert f["fullName"] == "NASA"
    assert f["userId"] == "528817151"
    assert f["url"] == "https://www.instagram.com/nasa/"
    assert f["biography"] == "Making the seemingly impossible, possible. ✨"
    assert f["isVerified"] is True and f["isPrivate"] is False
    # Exact counts come from the JSON; the post count only from og:description.
    assert f["followersCount"] == 104325922
    assert f["followingCount"] == 91
    assert f["postsCount"] == 5014
    assert f["externalUrl"] == "https://www.nasa.gov"
    assert f["externalUrls"][0] == {"title": "NASA.gov Homepage", "url": "https://www.nasa.gov"}
    assert len(f["externalUrls"]) == 5
    assert f["profilePicUrl"].startswith("https://scontent")
    assert len(parsed.recent) == 12
    assert parsed.recent[0] == {
        "shortcode": "Dfc1mYxFevS",
        "mediaId": "4025327901360909266",
        "type": "reel",
        "ownerUsername": "nasa",
        "url": "https://www.instagram.com/p/Dfc1mYxFevS/",
    }
    assert [p["type"] for p in parsed.recent[:3]] == ["reel", "photo", "carousel"]
    # A collab post the account was invited to sits in its grid under the other owner.
    assert parsed.recent[3]["ownerUsername"] == "empirestatebldg"


def test_nike_profile_rounded_meta_and_link_without_title():
    parsed = parse_profile(html("nike"))
    f = parsed.fields
    assert f["followersCount"] == 290772652
    assert f["postsCount"] == 1676
    assert f["externalUrls"] == [{"title": None, "url": "http://empli.fi/nike"}]
    assert len(parsed.recent) == 12
    assert parsed.recent[0]["shortcode"] == "Df0U_JQP8Y3"


def test_age_restricted_profile():
    parsed = parse_profile(html("budweiser"))
    assert parsed.kind == "restricted"
    assert parsed.message == (
        "Instagram hides this profile from logged-out visitors: Restricted profile. "
        "You must be 21 years old or over to see this profile."
    )
    assert parsed.fields == {"userId": "611930682", "followersCount": 735000, "followingCount": 287, "postsCount": 1621}


def test_missing_profile_and_post():
    assert parse_profile(html("nouser")).kind == "notFound"
    assert parse_post(html("post_missing")).kind == "notFound"


def test_wrong_page_type():
    assert parse_profile(html("post_nasa_image")).kind == "missing"
    assert parse_post(html("nasa")).kind == "missing"
    assert parse_profile("<html>shell</html>").kind == "missing"


def test_profile_page_without_data_is_missing():
    page = html("nasa").replace('"xig_user_by_username":{"pk"', '"xig_user_by_username":null,"x":{"pk"', 1)
    assert parse_profile(page).kind == "missing"


def test_private_profile_gives_no_posts():
    page = html("nasa").replace('"is_private":false', '"is_private":true', 1)
    parsed = parse_profile(page)
    assert parsed.kind == "private"
    assert parsed.recent == []
    assert parsed.fields["isPrivate"] is True and parsed.fields["followersCount"] == 104325922


def test_reel_post():
    parsed = parse_post(html("post_nasa_reel"))
    assert parsed.kind == "post"
    f = parsed.fields
    assert f["shortcode"] == "Dfc1mYxFevS"
    assert f["url"] == "https://www.instagram.com/p/Dfc1mYxFevS/"
    assert f["mediaId"] == "4025327901360909266"
    assert f["type"] == "reel"
    assert f["takenAt"] == "2026-11-07T18:35:41+00:00"
    assert f["likeCount"] == 99696
    assert f["commentCount"] == 1420
    assert f["hashtags"] == ["NASA", "Astronaut", "JobSearch"]
    assert f["caption"].startswith("Apply to become an astronaut!")
    assert f["videoUrl"].startswith("https://scontent")
    assert f["displayUrl"] == f["imageUrls"][0]
    assert f["ownerUsername"] == "nasa" and f["ownerId"] == "528817151"
    assert f["isCollab"] is False and f["locationName"] is None
    assert f["carouselMediaCount"] is None


def test_photo_post():
    f = parse_post(html("post_nasa_image")).fields
    assert f["type"] == "photo"
    assert (f["likeCount"], f["commentCount"]) == (257507, 873)
    assert f["videoUrl"] is None
    assert len(f["imageUrls"]) == 1


def test_collab_post_with_location():
    f = parse_post(html("post_nasa_collab")).fields
    assert f["ownerUsername"] == "empirestatebldg"
    assert f["isCollab"] is True
    assert f["locationName"] == "Empire State Building"
    assert f["type"] == "reel"
    assert f["takenAt"] == "2026-11-18T01:00:50+00:00"


def test_carousel_post():
    f = parse_post(html("post_natgeo_carousel")).fields
    assert f["type"] == "carousel"
    assert f["carouselMediaCount"] == 3
    assert len(f["imageUrls"]) == 3
    assert (f["likeCount"], f["commentCount"]) == (13005, 50)
    assert f["mentions"][-1] == "ExploreCanada"
    assert f["ownerUsername"] == "natgeo"


def test_comments_are_never_read():
    # The page carries a preview comment (placeholder in the fixture); no field holds it.
    page = html("post_nasa_image")
    assert "Redacted comment text." in page
    assert "Redacted comment text." not in repr(parse_post(page).fields)


def test_hidden_likes_are_null():
    page = html("post_nasa_image").replace('"like_and_view_counts_disabled":false', '"like_and_view_counts_disabled":true', 1)
    f = parse_post(page).fields
    assert f["likeCount"] is None and f["commentCount"] == 873


def test_gated_post_is_restricted():
    page = html("post_nasa_image").replace('"if_not_gated_logged_out":{', '"if_not_gated_logged_out":null,"was":{', 1)
    page = page.replace('"gating_ruling":null', '"gating_ruling":{"title":"Sensitive content"}', 1)
    assert parse_post(page).kind == "restricted"


def test_route_helpers():
    assert page_id(html("nasa")) == "profilePage"
    assert page_id(html("post_nasa_reel")) == "postPage"
    assert page_id(html("nouser")) == "httpErrorPage"
    assert root_props(html("nasa"))["id"] == "528817151"
    assert root_props(html("budweiser"))["gating"]["title"] == "Restricted profile"
    assert root_props("nothing") == {}


@pytest.mark.parametrize(
    ("text", "value"),
    [("1,676", 1676), ("32K", 32000), ("268M", 268000000), ("1.2M", 1200000), ("2B", 2000000000), ("95", 95), ("x", None), ("", None)],
)
def test_parse_count(text, value):
    assert parse_count(text) == value


def test_meta_counts():
    assert meta_counts('<meta property="og:description" content="268M Followers, 196 Following, 32K Posts - x" />') == {
        "followers": 268000000,
        "following": 196,
        "posts": 32000,
    }
    assert meta_counts("") == {"followers": None, "following": None, "posts": None}


def test_hashtags_and_mentions():
    text = "Hi @NASA and @nasa. #Space #space #Mars! email me@x.com &#123; (@ISS) by @jane.doe."
    assert hashtags(text) == ["Space", "Mars"]
    assert mentions(text) == ["NASA", "ISS", "jane.doe"]
    assert hashtags(None) == [] and mentions(None) == []


@pytest.mark.parametrize(
    ("code", "product", "kind"),
    [(1, "feed", "photo"), (2, "clips", "reel"), (2, "feed", "video"), (2, "igtv", "video"), (8, "carousel_container", "carousel"), (9, None, None)],
)
def test_media_type(code, product, kind):
    assert media_type(code, product) == kind
