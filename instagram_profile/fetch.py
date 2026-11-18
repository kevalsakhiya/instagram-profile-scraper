"""Fetching profile and post pages the way a logged-out Chrome visitor does, and deciding what a
response means.

Rules (kept on purpose, see README):
- No login, no account cookies, no tokens, no private API. Each proxy IP gets its own curl_cffi session
  with Chrome impersonation; the only cookies are the anonymous ones Instagram itself sets
  (csrftoken, datr, ig_did).
- A redirect to the login page (or a login page instead of the content) is retried once on a fresh
  proxy session, because Instagram sends throttled IPs there; the second time it is final
  ("loginRequired"). It is never worked around.
- Instagram's "page isn't available" page and a 404 are final ("notFound").
- Only temporary problems (network errors, timeouts, 429/5xx, an empty shell page without data) are
  retried, on a fresh proxy session, at most ``MAX_RETRIES`` more times.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

MAX_RETRIES = 2  # a temporary block is retried at most 2 more times
MAX_LOGIN_RETRIES = 1  # a login wall is retried once on a fresh IP, then final
MAX_REDIRECTS = 4
REQUEST_TIMEOUT_SECS = 30
PAGES_PER_SESSION = 15  # move to a fresh IP now and then, so no single IP does much
PACE_SECS = (2.0, 5.0)  # pause between requests on the same session
RETRY_BACKOFF_SECS = (3.0, 6.0)
RATE_LIMIT_BACKOFF_SECS = (8.0, 15.0)  # after a 429
IMPERSONATE = "chrome"

NAV_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

INSTAGRAM_WEB_HOSTS = {"www.instagram.com", "instagram.com", "m.instagram.com"}
PAGE_ID_RE = re.compile(r'"polarisRouteConfig":\{[^{}]*"pageID":"(\w+)"')
LOGIN_PATHS = ("/accounts/login", "/challenge", "/accounts/suspended", "/accounts/signup")
LOGIN_PAGE_IDS = {"loginPage", "LoginAndSignupPage", "challengePage"}

# What the caller expects on the page.
PROFILE_PAGE = "profilePage"
POST_PAGE = "postPage"

# Outcome kinds
PAGE = "page"
REDIRECT = "redirect"
NOT_FOUND = "notFound"
LOGIN_REQUIRED = "loginRequired"
TEMPORARY = "temporary"
RATE_LIMITED = "rateLimited"  # a temporary problem with a longer pause
BLOCKED = "blocked"


@dataclass
class Outcome:
    kind: str
    reason: str
    location: str | None = None


def has_data(body: str, expect: str) -> bool:
    """Cheap check (no JSON parsing) that the page carries the data the parser needs."""
    if expect == PROFILE_PAGE:
        return '"xig_user_by_username":{"pk":' in body or '"gating":{"title"' in body
    return '"xig_polaris_media":{' in body


def classify_response(url: str, status: int, location: str | None, body: str, expect: str = PROFILE_PAGE) -> Outcome:
    """Decide what one HTTP response means. Pure function, no network."""
    if status in (301, 302, 303, 307, 308):
        if not location:
            return Outcome(TEMPORARY, f"HTTP {status} without a location")
        target = urljoin(url, location)
        parsed = urlparse(target)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if host not in INSTAGRAM_WEB_HOSTS:
            return Outcome(NOT_FOUND, f"Instagram redirected away from the page ({host})")
        if path.startswith(LOGIN_PATHS):
            return Outcome(LOGIN_REQUIRED, "Instagram sent the visitor to its login page.")
        if path.rstrip("/") == "":
            return Outcome(NOT_FOUND, "Instagram redirected to its home page: the page does not exist.")
        return Outcome(REDIRECT, "redirect", location=target)

    if status in (404, 410):
        return Outcome(NOT_FOUND, f"Instagram returned HTTP {status}: the page does not exist.")
    if status == 429:
        return Outcome(RATE_LIMITED, "HTTP 429 (too many requests)")
    if status != 200:
        return Outcome(TEMPORARY, f"HTTP {status}")
    if not body:
        return Outcome(TEMPORARY, "empty response")

    match = PAGE_ID_RE.search(body)
    page = match.group(1) if match else None
    if page == "httpErrorPage":
        return Outcome(NOT_FOUND, "Instagram says this page isn't available.")
    if page in LOGIN_PAGE_IDS:
        return Outcome(LOGIN_REQUIRED, "Instagram showed its login page instead of the content.")
    if page is None:
        return Outcome(TEMPORARY, "the response was an empty page shell without data")
    if page != expect:
        return Outcome(TEMPORARY, f"Instagram answered with a different page ({page})")
    if not has_data(body, expect):
        return Outcome(TEMPORARY, "the page had no profile or post data")
    return Outcome(PAGE, "ok")


@dataclass
class FetchResult:
    kind: str  # PAGE, NOT_FOUND, LOGIN_REQUIRED or BLOCKED
    reason: str
    url: str  # last URL requested
    html: str | None = None
    attempts: int = 1


class ProxySession:
    """One curl_cffi session bound to one proxy IP (one Apify proxy session id)."""

    def __init__(self, session: AsyncSession, proxy_url: str | None, session_id: str) -> None:
        self.session = session
        self.proxy_url = proxy_url
        self.session_id = session_id
        self.pages = 0
        self.last_request = 0.0

    async def close(self) -> None:
        try:
            await self.session.close()
        except Exception:  # noqa: BLE001 - closing must never fail a page
            pass


NewProxyUrl = Callable[[str], Awaitable[str | None]]


async def _no_proxy(_session_id: str) -> str | None:
    return None


class Fetcher:
    """Fetches pages with one session per worker, each on its own proxy IP."""

    def __init__(
        self,
        new_proxy_url: NewProxyUrl = _no_proxy,
        *,
        session_factory: Callable[[str | None], AsyncSession] | None = None,
        pace: tuple[float, float] = PACE_SECS,
        backoff: tuple[float, float] = RETRY_BACKOFF_SECS,
        rate_limit_backoff: tuple[float, float] = RATE_LIMIT_BACKOFF_SECS,
        log=None,
    ) -> None:
        self.new_proxy_url = new_proxy_url
        self.session_factory = session_factory or self._default_session
        self.pace = pace
        self.backoff = backoff
        self.rate_limit_backoff = rate_limit_backoff
        self.log = log
        self.slots: dict[int, ProxySession] = {}
        self.requests = 0
        self.bytes = 0

    @staticmethod
    def _default_session(proxy_url: str | None) -> AsyncSession:
        return AsyncSession(
            impersonate=IMPERSONATE,
            proxy=proxy_url,
            timeout=REQUEST_TIMEOUT_SECS,
            allow_redirects=False,
        )

    async def _slot(self, worker: int, fresh: bool = False) -> ProxySession:
        slot = self.slots.get(worker)
        if slot and (fresh or slot.pages >= PAGES_PER_SESSION):
            await slot.close()
            slot = None
        if slot is None:
            session_id = f"igp{worker}_{uuid.uuid4().hex[:10]}"
            proxy_url = await self.new_proxy_url(session_id)
            slot = ProxySession(self.session_factory(proxy_url), proxy_url, session_id)
            self.slots[worker] = slot
        return slot

    async def _wait_turn(self, slot: ProxySession) -> None:
        if slot.last_request:
            pause = random.uniform(*self.pace) - (time.monotonic() - slot.last_request)
            if pause > 0:
                await asyncio.sleep(pause)
        slot.last_request = time.monotonic()

    async def _get(self, slot: ProxySession, url: str, expect: str) -> tuple[Outcome, str]:
        await self._wait_turn(slot)
        self.requests += 1
        try:
            resp = await slot.session.get(url, headers=NAV_HEADERS, allow_redirects=False)
        except (RequestException, asyncio.TimeoutError, OSError) as exc:
            return Outcome(TEMPORARY, f"network error ({exc.__class__.__name__})"), ""
        body = resp.text if resp.status_code == 200 else ""
        # Bytes on the wire (compressed), which is what proxy traffic is billed on.
        self.bytes += getattr(resp, "download_size", None) or len(resp.content or b"")
        return classify_response(url, resp.status_code, resp.headers.get("location"), body, expect), body

    async def fetch(self, worker: int, url: str, expect: str) -> FetchResult:
        """Fetch one page, following same-site redirects, retrying temporary problems."""
        last_reason = "unknown"
        current = url
        logins = 0
        for attempt in range(1, MAX_RETRIES + 2):
            slot = await self._slot(worker, fresh=attempt > 1)
            slot.pages += 1
            current = url
            seen = {url}
            outcome, body = Outcome(TEMPORARY, "no response"), ""
            for _hop in range(MAX_REDIRECTS + 1):
                outcome, body = await self._get(slot, current, expect)
                if outcome.kind != REDIRECT:
                    break
                current = outcome.location or current
                if current in seen:
                    outcome = Outcome(TEMPORARY, "redirect loop")
                    break
                seen.add(current)
            else:
                outcome = Outcome(TEMPORARY, "too many redirects")

            if outcome.kind == PAGE:
                return FetchResult(PAGE, "ok", current, html=body, attempts=attempt)
            if outcome.kind == NOT_FOUND:
                return FetchResult(NOT_FOUND, outcome.reason, current, attempts=attempt)
            if outcome.kind == LOGIN_REQUIRED:
                logins += 1
                if logins > MAX_LOGIN_RETRIES:
                    return FetchResult(LOGIN_REQUIRED, outcome.reason, current, attempts=attempt)
            last_reason = outcome.reason
            if attempt <= MAX_RETRIES:
                if self.log:
                    self.log.info(f"{url}: {outcome.reason}; retrying on a fresh proxy session ({attempt}/{MAX_RETRIES})")
                pause = self.rate_limit_backoff if outcome.kind == RATE_LIMITED else self.backoff
                await asyncio.sleep(random.uniform(*pause))
        return FetchResult(BLOCKED, last_reason, current, attempts=MAX_RETRIES + 1)

    async def close(self) -> None:
        for slot in self.slots.values():
            await slot.close()
        self.slots.clear()
