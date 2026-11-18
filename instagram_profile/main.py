"""Apify Actor entry point: read the input, scrape the profiles and posts, report the result."""

from __future__ import annotations

import asyncio
import contextlib

from apify import Actor

from .billing import Platform
from .fetch import Fetcher
from .inputs import collect_targets
from .run import DEFAULT_MAX_POSTS, ScrapeRun

# US residential Apify Proxy. On 2026-11-18 an Apify run on datacenter IPs got login walls for 4 of 5
# profiles; the same run on residential US IPs got all 5 profiles and 60 posts with no block.
DEFAULT_PROXY = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"], "apifyProxyCountry": "US"}
DEFAULT_CONCURRENCY = 3
MAX_CONCURRENCY = 10
MAX_POSTS_PER_PROFILE = 12  # logged-out profiles show the 12 newest posts
STATUS_INTERVAL_SECS = 15
STATE_KEY = "RUN_STATE"


def read_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def read_concurrency(value) -> int:
    return read_int(value, DEFAULT_CONCURRENCY, 1, MAX_CONCURRENCY)


def read_max_posts(value) -> int:
    return read_int(value, DEFAULT_MAX_POSTS, 0, MAX_POSTS_PER_PROFILE)


async def report_status(run: ScrapeRun) -> None:
    while True:
        await asyncio.sleep(STATUS_INTERVAL_SECS)
        with contextlib.suppress(Exception):
            await Actor.set_status_message(run.progress())


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}

        targets, problems = collect_targets(actor_input.get("usernames") or [], actor_input.get("postUrls") or [])
        if not targets and not problems:
            message = (
                "Nothing to scrape. Add Instagram usernames or profile links (such as nasa or "
                "https://www.instagram.com/nasa/) or post links (https://www.instagram.com/p/...)."
            )
            Actor.log.error(message)
            await Actor.fail(status_message=message)
            return

        proxy_input = actor_input.get("proxyConfiguration") or DEFAULT_PROXY
        try:
            proxy = await Actor.create_proxy_configuration(actor_proxy_input=proxy_input)
        except Exception as exc:  # noqa: BLE001 - explain instead of a stack trace
            message = f"The proxy could not be set up ({exc}). Check the proxy settings in the input."
            Actor.log.error(message)
            await Actor.fail(status_message=message)
            return

        async def new_proxy_url(session_id: str) -> str | None:
            return await proxy.new_url(session_id=session_id) if proxy else None

        if proxy is None:
            Actor.log.warning("Running without a proxy. Instagram limits each IP; use Apify Proxy for more than a few profiles.")

        state = await Actor.use_state({"done": [], "profiles": {}, "posts": {}}, key=STATE_KEY)
        fetcher = Fetcher(new_proxy_url, log=Actor.log)
        include_posts = bool(actor_input.get("includeRecentPosts", True))
        max_posts = read_max_posts(actor_input.get("maxPostsPerProfile", DEFAULT_MAX_POSTS))
        run = ScrapeRun(
            Platform(Actor, log=Actor.log),
            fetcher,
            include_recent_posts=include_posts,
            max_posts_per_profile=max_posts,
            concurrency=read_concurrency(actor_input.get("maxConcurrency")),
            log=Actor.log,
            state=state,
        )

        profiles = sum(1 for t in targets if t.kind == "profile")
        posts = len(targets) - profiles
        Actor.log.info(
            f"Scraping {profiles} profile(s) and {posts} post link(s); {len(problems)} input(s) could not be used. "
            + (f"Up to {max_posts} recent posts per profile." if include_posts and max_posts else "Recent posts off.")
        )
        await Actor.set_status_message(f"Starting: {profiles} profile(s), {posts} post link(s)")

        status_task = asyncio.create_task(report_status(run))
        try:
            await run.push_invalid(problems)
            await run.run(targets)
        finally:
            status_task.cancel()
            await fetcher.close()

        summary = run.summary()
        Actor.log.info(summary)
        Actor.log.info(f"{fetcher.requests} requests, {fetcher.bytes / 1_000_000:.1f} MB transferred.")
        await Actor.set_status_message(summary, is_terminal=True)
