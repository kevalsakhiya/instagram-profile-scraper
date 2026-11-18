"""Response classification and retry rules, offline."""

from __future__ import annotations

import pytest
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

from instagram_profile.fetch import (
    BLOCKED,
    LOGIN_REQUIRED,
    MAX_RETRIES,
    NOT_FOUND,
    PAGE,
    POST_PAGE,
    PROFILE_PAGE,
    RATE_LIMITED,
    REDIRECT,
    TEMPORARY,
    Fetcher,
    classify_response,
)

from .helpers import html, index

URL = "https://www.instagram.com/nasa/"

# -- the real captured responses ---------------------------------------------------------------

EXPECTED = {
    "nasa": (PROFILE_PAGE, PAGE),
    "nike": (PROFILE_PAGE, PAGE),
    "budweiser": (PROFILE_PAGE, PAGE),  # gated: the parser makes it a 'restricted' row
    "nouser": (PROFILE_PAGE, NOT_FOUND),
    "post_nasa_reel": (POST_PAGE, PAGE),
    "post_nasa_image": (POST_PAGE, PAGE),
    "post_nasa_collab": (POST_PAGE, PAGE),
    "post_natgeo_carousel": (POST_PAGE, PAGE),
    "post_missing": (POST_PAGE, NOT_FOUND),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_captured_pages(name):
    meta = index()[name]
    expect, kind = EXPECTED[name]
    assert meta["status"] == 200 and meta["location"] is None
    assert classify_response(meta["requestedUrl"], meta["status"], meta["location"], html(name), expect).kind == kind


def test_profile_page_when_a_post_was_expected_is_temporary():
    assert classify_response(URL, 200, None, html("nasa"), POST_PAGE).kind == TEMPORARY


def test_page_without_data_is_temporary():
    body = html("nasa").replace('"xig_user_by_username":{"pk":', '"xig_user_by_username":null,"x":{"k":')
    assert classify_response(URL, 200, None, body, PROFILE_PAGE).kind == TEMPORARY


@pytest.mark.parametrize(
    ("status", "location", "body", "kind"),
    [
        (302, "https://www.instagram.com/accounts/login/?next=%2Fnasa%2F", "", LOGIN_REQUIRED),
        (302, "/accounts/login/", "", LOGIN_REQUIRED),
        (302, "https://www.instagram.com/challenge/?next=/nasa/", "", LOGIN_REQUIRED),
        (302, "https://www.instagram.com/", "", NOT_FOUND),
        (302, "https://about.instagram.com/", "", NOT_FOUND),
        (301, "https://www.instagram.com/nasa/", "", REDIRECT),
        (302, None, "", TEMPORARY),
        (404, None, "", NOT_FOUND),
        (429, None, "", RATE_LIMITED),
        (500, None, "", TEMPORARY),
        (403, None, "", TEMPORARY),
        (200, None, "", TEMPORARY),
        # Synthetic bodies (no live capture of these states):
        (200, None, "<html><title>Instagram</title><body>shell</body></html>", TEMPORARY),
        (200, None, '{"polarisRouteConfig":{"pageID":"loginPage"}}', LOGIN_REQUIRED),
    ],
)
def test_classify(status, location, body, kind):
    assert classify_response(URL, status, location, body, PROFILE_PAGE).kind == kind


# -- retries ---------------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, body="", location=None):
        self.status_code = status
        self.text = body
        self.content = body.encode()
        self.headers = {"location": location} if location else {}


class FakeSession:
    """Answers from a shared script of responses (one per request)."""

    def __init__(self, script, proxy_url):
        self.script = script
        self.proxy_url = proxy_url
        self.closed = False

    async def get(self, url, headers=None, allow_redirects=False):
        self.script["calls"].append((self.proxy_url, url))
        answer = self.script["answers"].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        self.closed = True


def make_fetcher(answers):
    script = {"answers": list(answers), "calls": []}
    counter = {"n": 0}

    async def new_proxy_url(session_id):
        counter["n"] += 1
        return f"http://proxy-{counter['n']}"

    fetcher = Fetcher(
        new_proxy_url,
        session_factory=lambda proxy: FakeSession(script, proxy),
        pace=(0, 0),
        backoff=(0, 0),
        rate_limit_backoff=(0, 0),
    )
    return fetcher, script


async def test_page_on_first_try():
    fetcher, script = make_fetcher([FakeResponse(200, html("nasa"))])
    result = await fetcher.fetch(0, URL, PROFILE_PAGE)
    assert result.kind == PAGE and result.attempts == 1
    assert len(script["calls"]) == 1


async def test_temporary_problems_retry_on_fresh_sessions_then_block():
    fetcher, script = make_fetcher([FakeResponse(429), CurlConnectionError("x"), FakeResponse(200, "<html></html>")])
    result = await fetcher.fetch(0, URL, PROFILE_PAGE)
    assert result.kind == BLOCKED and result.attempts == MAX_RETRIES + 1
    assert [proxy for proxy, _ in script["calls"]] == ["http://proxy-1", "http://proxy-2", "http://proxy-3"]


async def test_retry_succeeds():
    fetcher, script = make_fetcher([FakeResponse(500), FakeResponse(200, html("post_nasa_reel"))])
    result = await fetcher.fetch(0, "https://www.instagram.com/p/Dfc1mYxFevS/", POST_PAGE)
    assert result.kind == PAGE and result.attempts == 2


async def test_login_wall_is_retried_once_then_final():
    login = FakeResponse(302, location="https://www.instagram.com/accounts/login/")
    fetcher, script = make_fetcher([login, login, FakeResponse(200, html("nasa"))])
    result = await fetcher.fetch(0, URL, PROFILE_PAGE)
    assert result.kind == LOGIN_REQUIRED and result.attempts == 2
    assert len(script["calls"]) == 2


async def test_login_wall_then_page():
    login = FakeResponse(302, location="https://www.instagram.com/accounts/login/")
    fetcher, _ = make_fetcher([login, FakeResponse(200, html("nasa"))])
    assert (await fetcher.fetch(0, URL, PROFILE_PAGE)).kind == PAGE


async def test_not_found_is_final():
    fetcher, script = make_fetcher([FakeResponse(200, html("nouser"))])
    result = await fetcher.fetch(0, URL, PROFILE_PAGE)
    assert result.kind == NOT_FOUND and len(script["calls"]) == 1


async def test_redirect_is_followed_and_loop_detected():
    fetcher, script = make_fetcher(
        [FakeResponse(301, location="https://www.instagram.com/nasa/"), FakeResponse(200, html("nasa"))]
    )
    result = await fetcher.fetch(0, "https://www.instagram.com/NASA/", PROFILE_PAGE)
    assert result.kind == PAGE and result.url == URL
    loop = FakeResponse(302, location=URL)
    fetcher, script = make_fetcher([loop] * 3)
    result = await fetcher.fetch(0, URL, PROFILE_PAGE)
    assert result.kind == BLOCKED and "redirect loop" in result.reason


async def test_session_reused_within_a_worker_and_rotated():
    from instagram_profile import fetch as fetch_module

    pages = [FakeResponse(200, html("nasa")) for _ in range(fetch_module.PAGES_PER_SESSION + 1)]
    fetcher, script = make_fetcher(pages)
    for _ in range(fetch_module.PAGES_PER_SESSION + 1):
        await fetcher.fetch(0, URL, PROFILE_PAGE)
    proxies = [proxy for proxy, _ in script["calls"]]
    assert set(proxies[: fetch_module.PAGES_PER_SESSION]) == {"http://proxy-1"}
    assert proxies[-1] == "http://proxy-2"
    await fetcher.close()
    assert fetcher.slots == {}
