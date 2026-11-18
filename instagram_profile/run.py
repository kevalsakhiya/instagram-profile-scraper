"""One scraping run: profiles (with their recent posts) and single posts, one row each.

Talks to Apify only through ``Platform`` (billing.py) and to Instagram only through ``Fetcher``
(fetch.py), so tests can replace both.

Order inside a profile: the profile page is fetched, then each recent post page on the same worker
(same proxy IP, paced), each post row is pushed as soon as it is read, and the profile row with the
engagement figures is pushed last.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import MutableMapping

from . import output
from .billing import POST_EVENT, PROFILE_EVENT, Platform
from .fetch import LOGIN_REQUIRED, NOT_FOUND, PAGE, POST_PAGE, PROFILE_PAGE
from .inputs import POST, PROFILE, Target
from .parser import parse_post, parse_profile

LIMIT_RECHECK_SECS = 0.2  # how often a worker re-checks the spending limit while pages are in flight
DEFAULT_MAX_POSTS = 12

ERROR_LABELS = {
    output.NOT_FOUND: "not found",
    output.PRIVATE_PROFILE: "private",
    output.RESTRICTED: "restricted",
    output.LOGIN_REQUIRED: "login required",
    output.BLOCKED: "blocked",
    output.INVALID_INPUT: "invalid input",
    output.FAILED: "failed",
}
STAT_KEYS = ("likeCount", "commentCount", "takenAt")
PUSHED_BY = "pushedBy"  # RUN_STATE: the input key whose row delivered a post


class ScrapeRun:
    def __init__(
        self,
        platform: Platform,
        fetcher,
        *,
        include_recent_posts: bool = True,
        max_posts_per_profile: int = DEFAULT_MAX_POSTS,
        concurrency: int = 3,
        log=None,
        state: MutableMapping | None = None,
    ) -> None:
        self.platform = platform
        self.fetcher = fetcher
        self.include_recent_posts = include_recent_posts
        self.max_posts = max(0, max_posts_per_profile)
        self.concurrency = max(1, concurrency)
        self.log = log
        # Survives migrations (Actor.use_state): inputs and posts already pushed are not redone,
        # so nothing is pushed or charged twice, and a profile's figures still count its posts.
        self.state = state if state is not None else {}
        self.state.setdefault("done", [])
        self.state.setdefault("profiles", {})
        self.state.setdefault("posts", {})
        self.done: set[str] = set(self.state["done"])
        self.counts: Counter = Counter(self.state.get("counts") or {})
        self.post_locks: dict[str, asyncio.Lock] = {}
        self.profiles_in_flight: dict[str, str] = {}
        self.total = 0
        self.stopped_at_limit = False
        self.posts_skipped_at_limit = 0
        self.not_processed = 0

    # -- bookkeeping ---------------------------------------------------------------

    def _mark_done(self, key: str, outcome: str | None) -> None:
        self.done.add(key)
        self.state["done"].append(key)
        if outcome:
            self.counts[outcome] += 1
            self.state["counts"] = dict(self.counts)

    def _info(self, message: str) -> None:
        if self.log:
            self.log.info(message)

    # -- invalid inputs ------------------------------------------------------------

    async def push_invalid(self, problems: list[tuple[str, str, str]]) -> None:
        for raw, kind, problem in problems:
            key = f"invalid:{kind}:{raw}"
            if key in self.done:
                continue
            await self.platform.push_free(output.build_error_row(kind, raw, output.INVALID_INPUT, problem))
            self._mark_done(key, output.INVALID_INPUT)
            if self.log:
                self.log.warning(f"Skipping '{raw}': {problem}")

    # -- the queue -----------------------------------------------------------------

    async def run(self, targets: list[Target]) -> None:
        todo = deque(t for t in targets if t.key not in self.done)
        self.total = len(targets)
        workers = [asyncio.create_task(self._worker(i, todo)) for i in range(min(self.concurrency, len(todo)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                task.cancel()
        self.not_processed = len(todo)

    async def _reserve(self, event: str) -> bool:
        """Wait for room in the spending limit while other rows in flight hold it; False when there is none."""
        while not self.stopped_at_limit:
            if self.platform.reserve(event):
                return True
            if self.platform.reserved > 0:
                # Pages in flight hold the room. Some may turn out free (error rows) and give it
                # back, so wait for them before deciding the limit is hit.
                await asyncio.sleep(LIMIT_RECHECK_SECS)
                continue
            self.stopped_at_limit = True
        return False

    async def _worker(self, worker: int, todo: deque) -> None:
        while todo and not self.stopped_at_limit:
            target = todo.popleft()
            event = PROFILE_EVENT if target.kind == PROFILE else POST_EVENT
            if not await self._reserve(event):
                todo.appendleft(target)
                break
            try:
                if target.kind == PROFILE:
                    await self._profile(worker, target)
                else:
                    await self._single_post(worker, target)
            finally:
                self.platform.release(event)

    # -- profiles --------------------------------------------------------------------

    async def _profile(self, worker: int, target: Target) -> None:
        try:
            result = await self.fetcher.fetch(worker, target.url, PROFILE_PAGE)
        except Exception as exc:  # noqa: BLE001 - one input must never stop the run
            await self._error(PROFILE, target, output.FAILED, f"Unexpected error while loading the profile ({exc.__class__.__name__}).")
            return
        if result.kind != PAGE:
            await self._fetch_error(PROFILE, target, result)
            return
        try:
            parsed = parse_profile(result.html or "")
        except Exception as exc:  # noqa: BLE001
            await self._error(PROFILE, target, output.FAILED, f"Could not read the profile ({exc.__class__.__name__}).")
            return

        if parsed.kind == "notFound":
            await self._error(PROFILE, target, output.NOT_FOUND, parsed.message or "Profile not found.")
            return
        if parsed.kind == "restricted":
            fields = {**parsed.fields, "username": target.value, "url": target.url}
            await self._error(PROFILE, target, output.RESTRICTED, parsed.message or "Restricted profile.", fields=fields)
            return
        if parsed.kind == "private":
            await self._error(PROFILE, target, output.PRIVATE_PROFILE, parsed.message or "Private account.", fields=parsed.fields)
            return
        if parsed.kind != "profile":
            await self._error(PROFILE, target, output.BLOCKED, f"Instagram did not return the profile data ({parsed.message}). Try again later.")
            return

        user_id = parsed.fields.get("userId")
        if user_id and self.state["profiles"].get(user_id) == target.input:
            # This very input's row was pushed just before a restart (RUN_STATE was saved during the push).
            self._mark_done(target.key, PROFILE)
            return
        first_input = self.state["profiles"].get(user_id) or self.profiles_in_flight.get(user_id)
        if user_id and first_input:
            self._info(f"'{target.input}' is the same profile as '{first_input}'; skipped (not charged).")
            self._mark_done(target.key, "duplicate")
            return
        if user_id:
            # In memory only: after a migration this profile must still be finished, not skipped.
            self.profiles_in_flight[user_id] = target.input

        recent = parsed.recent[: self.max_posts]
        stats = None
        if self.include_recent_posts and self.max_posts:
            stats = []
            for post in recent:
                stat = await self._recent_post(worker, target, post, parsed.fields.get("followersCount"))
                if stat is not None:
                    stats.append(stat)

        row = output.build_profile_row(
            target.input, parsed.fields, stats=stats, recent_urls=[p["url"] for p in parsed.recent]
        )
        if user_id:
            # Recorded before the push: if RUN_STATE is saved while the push is in flight, a restart
            # skips this profile instead of charging it twice.
            self.state["profiles"][user_id] = target.input
        try:
            await self.platform.push_charged(row, PROFILE_EVENT)
        except Exception:
            self.state["profiles"].pop(user_id, None)
            raise
        self._mark_done(target.key, PROFILE)

    async def _recent_post(self, worker: int, profile: Target, post: dict, followers: int | None) -> dict | None:
        """Fetch and push one post of a profile; return its stats for the profile figures, or None."""
        code = post["shortcode"]
        done_key = f"{profile.key}>{code}"
        if code in self.state["posts"]:
            self._mark_pushed_before_restart(code, done_key)
            return self.state["posts"][code]
        if done_key in self.done:  # an error row was already pushed for it before a restart
            return None
        # No waiting here: this worker holds the profile's own reservation, so "rows in flight"
        # would never drop to zero. Without room the remaining posts are skipped.
        if self.stopped_at_limit or not self.platform.reserve(POST_EVENT):
            self.stopped_at_limit = True
            self.posts_skipped_at_limit += 1
            return None
        try:
            return await self._post(worker, code, post["url"], profile.input, done_key, followers)
        finally:
            self.platform.release(POST_EVENT)

    # -- posts -----------------------------------------------------------------------

    def _mark_pushed_before_restart(self, code: str, done_key: str) -> bool:
        """True when this input's own post row was pushed just before a restart; it is then counted, not redone."""
        stat = self.state["posts"].get(code)
        if stat is None or done_key in self.done or stat.get(PUSHED_BY) != done_key:
            return False
        self._mark_done(done_key, POST)
        return True

    async def _single_post(self, worker: int, target: Target) -> None:
        if self._mark_pushed_before_restart(target.value, target.key):
            return
        if target.value in self.state["posts"]:
            self._info(f"'{target.input}' was already scraped in this run; skipped (not charged).")
            self._mark_done(target.key, "duplicate")
            return
        await self._post(worker, target.value, target.url, target.input, target.key, None)

    async def _post(self, worker: int, code: str, url: str, input_url: str, done_key: str, followers: int | None) -> dict | None:
        lock = self.post_locks.setdefault(code, asyncio.Lock())
        async with lock:
            if code in self.state["posts"]:  # pushed meanwhile through another input
                if not self._mark_pushed_before_restart(code, done_key) and done_key not in self.done:
                    self._mark_done(done_key, "duplicate" if done_key.startswith("post:") else None)
                return self.state["posts"][code]
            target = Target(POST, input_url, url, done_key, code)
            try:
                result = await self.fetcher.fetch(worker, url, POST_PAGE)
            except Exception as exc:  # noqa: BLE001
                await self._error(POST, target, output.FAILED, f"Unexpected error while loading the post ({exc.__class__.__name__}).")
                return None
            if result.kind != PAGE:
                await self._fetch_error(POST, target, result)
                return None
            try:
                parsed = parse_post(result.html or "")
            except Exception as exc:  # noqa: BLE001
                await self._error(POST, target, output.FAILED, f"Could not read the post ({exc.__class__.__name__}).")
                return None
            if parsed.kind == "notFound":
                await self._error(POST, target, output.NOT_FOUND, parsed.message or "Post not found.")
                return None
            if parsed.kind == "restricted":
                await self._error(POST, target, output.RESTRICTED, parsed.message or "Restricted post.")
                return None
            if parsed.kind != "post":
                await self._error(POST, target, output.BLOCKED, f"Instagram did not return the post data ({parsed.message}). Try again later.")
                return None

            row = output.build_post_row(input_url, parsed.fields, followers=followers)
            stat = {key: row[key] for key in STAT_KEYS}
            # Recorded before the push: if RUN_STATE is saved while the push is in flight, a restart
            # reuses this post instead of pushing and charging it twice.
            self.state["posts"][code] = {**stat, PUSHED_BY: done_key}
            try:
                await self.platform.push_charged(row, POST_EVENT)
            except Exception:
                del self.state["posts"][code]
                raise
            self._mark_done(done_key, POST)
            return stat

    # -- errors ----------------------------------------------------------------------

    async def _fetch_error(self, kind: str, target: Target, result) -> None:
        what = "profile" if kind == PROFILE else "post"
        if result.kind == NOT_FOUND:
            hint = (
                "The username does not exist, was changed, or the account was removed."
                if kind == PROFILE
                else "The post was deleted, or the link is wrong."
            )
            await self._error(kind, target, output.NOT_FOUND, f"{result.reason} {hint}")
        elif result.kind == LOGIN_REQUIRED:
            await self._error(
                kind,
                target,
                output.LOGIN_REQUIRED,
                f"Instagram asked to log in to see this {what}, twice on two proxy IPs. "
                "This actor never logs in. Try again later, or with residential proxies.",
            )
        else:
            await self._error(
                kind,
                target,
                output.BLOCKED,
                f"Instagram did not return the {what} after {result.attempts} tries on fresh proxy IPs "
                f"(last problem: {result.reason}). Try again later or with residential proxies.",
            )

    async def _error(self, kind: str, target: Target, error: str, message: str, *, fields: dict | None = None) -> None:
        url = target.url
        await self.platform.push_free(output.build_error_row(kind, target.input, error, message, url=url, fields=fields))
        self._mark_done(target.key, error)
        label = ERROR_LABELS.get(error, error)
        where = target.input if target.input == url else f"{target.input} ({url})"
        self._info(f"{where}: {label}. {message}")

    # -- status ----------------------------------------------------------------------

    def progress(self) -> str:
        errors = sum(v for k, v in self.counts.items() if k in ERROR_LABELS)
        return (
            f"Scraped {self.counts[PROFILE]} profiles and {self.counts[POST]} posts "
            f"({errors} error rows, free)"
        )

    def summary(self) -> str:
        profiles, posts = self.counts[PROFILE], self.counts[POST]
        parts = [f"{profiles} profile{'s' if profiles != 1 else ''} and {posts} post{'s' if posts != 1 else ''} scraped"]
        for code, label in ERROR_LABELS.items():
            if self.counts[code]:
                parts.append(f"{self.counts[code]} {label}")
        if self.counts["duplicate"]:
            parts.append(f"{self.counts['duplicate']} duplicate")
        text = "Done: " + ", ".join(parts) + "."
        if self.stopped_at_limit:
            left = []
            if self.not_processed:
                left.append(f"{self.not_processed} input{'s' if self.not_processed != 1 else ''} not processed")
            if self.posts_skipped_at_limit:
                left.append(f"{self.posts_skipped_at_limit} recent post{'s' if self.posts_skipped_at_limit != 1 else ''} not fetched")
            text = (
                f"Stopped at your spending limit: {', '.join(parts)}. "
                + (", ".join(left) + " " if left else "")
                + "(raise the limit and run again for the rest)."
            )
        elif any(self.counts[c] for c in ERROR_LABELS):
            text += " Error rows are free."
        return text
