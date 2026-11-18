"""Push and charge rules, restarts and error rows, with a fake Actor and fake fetcher (no network)."""

from __future__ import annotations

import asyncio
import copy
import math
from dataclasses import dataclass
from decimal import Decimal

from instagram_profile import output
from instagram_profile.billing import POST_EVENT, PROFILE_EVENT, Platform
from instagram_profile.fetch import BLOCKED, LOGIN_REQUIRED, NOT_FOUND, PAGE, POST_PAGE, PROFILE_PAGE, FetchResult
from instagram_profile.inputs import collect_targets
from instagram_profile.run import ScrapeRun

from .helpers import html

PRICES = {PROFILE_EVENT: Decimal("0.004"), POST_EVENT: Decimal("0.002")}


@dataclass
class Pricing:
    is_pay_per_event: bool
    per_event_prices: dict
    max_total_charge_usd: Decimal


@dataclass
class ChargeResult:
    event_charge_limit_reached: bool
    charged_count: int
    chargeable_within_limit: dict


class FakeChargingManager:
    """Same maths as the Apify SDK's charging manager for explicit events."""

    def __init__(self, ppe: bool, limit: str | None = None) -> None:
        self.ppe = ppe
        self.limit = Decimal(limit) if limit is not None else Decimal("inf")
        self.counts = {PROFILE_EVENT: 0, POST_EVENT: 0}

    def get_pricing_info(self):
        return Pricing(self.ppe, dict(PRICES) if self.ppe else {}, self.limit)

    def calculate_total_charged_amount(self) -> Decimal:
        return sum((PRICES[e] * n for e, n in self.counts.items()), start=Decimal())

    def calculate_max_event_charge_count_within_limit(self, event_name):
        result = (self.limit - self.calculate_total_charged_amount()) / PRICES[event_name]
        return max(0, math.floor(result)) if result.is_finite() else None


class FakeActor:
    def __init__(self, ppe: bool = True, limit: str | None = None) -> None:
        self.manager = FakeChargingManager(ppe, limit)
        self.pushed: list[tuple[dict, str | None]] = []

    def get_charging_manager(self):
        return self.manager

    async def push_data(self, data, charged_event_name=None):
        await asyncio.sleep(0)
        charged = 0
        if charged_event_name and self.manager.ppe:
            room = self.manager.calculate_max_event_charge_count_within_limit(charged_event_name)
            # The SDK would still push (overcharge-by-one); the actor must never get here without room.
            assert room is None or room >= 1, "pushed a charged row without room in the limit"
            charged = 1
            self.manager.counts[charged_event_name] += 1
        self.pushed.append((data, charged_event_name))
        return ChargeResult(False, charged, {})


def page(name: str) -> FetchResult:
    return FetchResult(PAGE, "ok", "u", html=html(name))


P = "https://www.instagram.com/p/"
ANSWERS = {
    "https://www.instagram.com/nasa/": page("nasa"),
    "https://www.instagram.com/nasa_old_name/": page("nasa"),  # e.g. a renamed account
    "https://www.instagram.com/nike/": page("nike"),
    "https://www.instagram.com/budweiser/": page("budweiser"),
    "https://www.instagram.com/nosuchuser/": FetchResult(NOT_FOUND, "Instagram says this page isn't available.", "u"),
    "https://www.instagram.com/walled/": FetchResult(LOGIN_REQUIRED, "login", "u", attempts=2),
    "https://www.instagram.com/blockeduser/": FetchResult(BLOCKED, "HTTP 429 (too many requests)", "u", attempts=3),
    P + "Dfc1mYxFevS/": page("post_nasa_reel"),
    P + "DfahZrMjAqq/": page("post_nasa_image"),
    P + "DfSi56IFwZK/": page("post_nasa_carousel"),
    P + "Df3Rp0bKNdr/": page("post_nasa_collab"),
    P + "Df147tCiAyB/": page("post_natgeo_carousel"),
    P + "DzzzzzzzzzA/": FetchResult(NOT_FOUND, "Instagram says this page isn't available.", "u"),
    P + "Df0U_JQP8Y3/": FetchResult(BLOCKED, "the response was an empty page shell without data", "u", attempts=3),
}


class FakeFetcher:
    def __init__(self, answers=ANSWERS) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, worker, url, expect):
        self.calls.append((url, expect))
        await asyncio.sleep(0.005)
        return self.answers[url]


async def run_actor(usernames=(), posts=(), *, ppe=True, limit=None, concurrency=3, state=None, include=True, max_posts=4, fetcher=None):
    actor = FakeActor(ppe, limit)
    fetcher = fetcher or FakeFetcher()
    run = ScrapeRun(
        Platform(actor), fetcher, include_recent_posts=include, max_posts_per_profile=max_posts, concurrency=concurrency, state=state
    )
    targets, problems = collect_targets(list(usernames), list(posts))
    await run.push_invalid(problems)
    await run.run(targets)
    return actor, fetcher, run


def rows(actor, record_type=None):
    return [(row, event) for row, event in actor.pushed if record_type is None or row["recordType"] == record_type]


async def test_profile_with_recent_posts():
    actor, fetcher, run = await run_actor(["nasa"])
    posts = rows(actor, "post")
    assert [r["shortcode"] for r, _ in posts] == ["Dfc1mYxFevS", "DfahZrMjAqq", "DfSi56IFwZK", "Df3Rp0bKNdr"]
    assert all(event == POST_EVENT for _, event in posts)
    assert all(r["inputUrl"] == "nasa" for r, _ in posts)
    profile, event = actor.pushed[-1]
    assert event == PROFILE_EVENT and profile["recordType"] == "profile"
    assert profile["recentPostsAnalysed"] == 4
    likes = [99696, 257507, 388937, 3893]
    comments = [1420, 873, 973, 41]
    assert profile["avgLikes"] == round(sum(likes) / 4, 1)
    assert profile["avgComments"] == round(sum(comments) / 4, 1)
    assert profile["engagementRatePct"] == round((sum(likes) / 4 + sum(comments) / 4) / 104325922 * 100, 4)
    assert profile["lastPostAt"] == "2026-11-18T01:00:50+00:00"
    # NASA's first three grid posts are older than the fourth: they are pinned, which leaves one
    # regular post, too few for a posting frequency.
    assert profile["postingFrequencyPerWeek"] is None
    assert len(profile["recentPostUrls"]) == 12
    # Per-post engagement against the profile's followers
    assert posts[1][0]["engagementRatePct"] == round((257507 + 873) / 104325922 * 100, 4)
    assert [expect for _, expect in fetcher.calls] == [PROFILE_PAGE] + [POST_PAGE] * 4
    assert actor.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 4}
    assert run.summary() == "Done: 1 profile and 4 posts scraped."


async def test_recent_posts_off():
    actor, fetcher, _ = await run_actor(["nasa"], include=False)
    assert len(actor.pushed) == 1
    profile = actor.pushed[0][0]
    assert profile["recentPostsAnalysed"] == 0 and profile["avgLikes"] is None and profile["engagementRatePct"] is None
    assert len(profile["recentPostUrls"]) == 12
    assert len(fetcher.calls) == 1


async def test_error_rows_are_free_and_have_every_key():
    actor, _, run = await run_actor(
        ["nosuchuser", "walled", "blockeduser", "budweiser", "bad name!"],
        [P + "DzzzzzzzzzA/", "https://example.com/x"],
    )
    by_input = {row["inputUrl"]: (row, event) for row, event in actor.pushed}
    assert by_input["nosuchuser"][0]["error"] == output.NOT_FOUND
    assert by_input["nosuchuser"][0]["errorMessage"].endswith("The username does not exist, was changed, or the account was removed.")
    assert by_input[P + "DzzzzzzzzzA/"][0]["errorMessage"].endswith("The post was deleted, or the link is wrong.")
    assert by_input["walled"][0]["error"] == output.LOGIN_REQUIRED
    assert by_input["blockeduser"][0]["error"] == output.BLOCKED
    restricted = by_input["budweiser"][0]
    assert restricted["error"] == output.RESTRICTED and restricted["followersCount"] == 735000
    assert restricted["username"] == "budweiser" and restricted["userId"] == "611930682"
    assert by_input["bad name!"][0]["error"] == output.INVALID_INPUT
    assert by_input["bad name!"][0]["recordType"] == "profile"
    assert by_input[P + "DzzzzzzzzzA/"][0]["error"] == output.NOT_FOUND
    assert by_input[P + "DzzzzzzzzzA/"][0]["recordType"] == "post"
    assert by_input["https://example.com/x"][0]["recordType"] == "post"
    for row, event in actor.pushed:
        assert event is None
        assert list(row) == list(output.FIELDS)
        assert row["error"] and row["errorMessage"]
    assert actor.manager.counts == {PROFILE_EVENT: 0, POST_EVENT: 0}
    assert run.summary() == (
        "Done: 0 profiles and 0 posts scraped, 2 not found, 1 restricted, 1 login required, 1 blocked, "
        "2 invalid input. Error rows are free."
    )


async def test_private_profile_is_a_free_row_without_posts():
    private = FetchResult(PAGE, "ok", "u", html=html("nasa").replace('"is_private":false', '"is_private":true', 1))
    fetcher = FakeFetcher({**ANSWERS, "https://www.instagram.com/nasa/": private})
    actor, fetcher, _ = await run_actor(["nasa"], fetcher=fetcher)
    assert len(actor.pushed) == 1
    row, event = actor.pushed[0]
    assert event is None and row["error"] == output.PRIVATE_PROFILE
    assert row["isPrivate"] is True and row["followersCount"] == 104325922 and row["username"] == "nasa"
    assert len(fetcher.calls) == 1


async def test_failed_recent_post_is_a_free_post_row():
    actor, _, run = await run_actor(["nike"], max_posts=1)
    (post_row, post_event), (profile, profile_event) = actor.pushed
    assert post_row["recordType"] == "post" and post_row["error"] == output.BLOCKED and post_event is None
    assert post_row["url"] == P + "Df0U_JQP8Y3/" and post_row["inputUrl"] == "nike"
    assert profile_event == PROFILE_EVENT and profile["recentPostsAnalysed"] == 0 and profile["avgLikes"] is None
    assert run.counts["profile"] == 1 and run.counts[output.BLOCKED] == 1


async def test_post_links_and_dedup_with_profile_posts():
    actor, fetcher, run = await run_actor(["nasa"], [P + "DfahZrMjAqq/", "https://www.instagram.com/reel/Df147tCiAyB/"], concurrency=1)
    shortcodes = [r["shortcode"] for r, _ in rows(actor, "post")]
    assert shortcodes.count("DfahZrMjAqq") == 1
    assert "Df147tCiAyB" in shortcodes
    single = next(r for r, _ in rows(actor, "post") if r["shortcode"] == "Df147tCiAyB")
    assert single["inputUrl"] == "https://www.instagram.com/reel/Df147tCiAyB/" and single["engagementRatePct"] is None
    assert actor.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 5}
    assert [url for url, _ in fetcher.calls].count(P + "DfahZrMjAqq/") == 1
    assert run.counts["duplicate"] == 1


async def test_concurrent_post_link_and_profile_post_push_once():
    actor, fetcher, _ = await run_actor(["nasa"], [P + "Dfc1mYxFevS/"], concurrency=2)
    assert [r["shortcode"] for r, _ in rows(actor, "post")].count("Dfc1mYxFevS") == 1
    assert actor.manager.counts[POST_EVENT] == 4


async def test_same_profile_twice_is_charged_once():
    actor, _, run = await run_actor(["nasa", "NASA", "nasa_old_name"], include=False, concurrency=1)
    assert len(actor.pushed) == 1 and run.counts["duplicate"] == 1
    assert actor.manager.counts[PROFILE_EVENT] == 1


async def test_same_profile_twice_in_parallel_is_charged_once():
    actor, _, run = await run_actor(["nasa", "nasa_old_name"], concurrency=2, max_posts=2)
    assert len(rows(actor, "profile")) == 1 and run.counts["duplicate"] == 1
    assert actor.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 2}


async def test_not_pay_per_event_pushes_plainly():
    actor, _, run = await run_actor(["nasa", "nosuchuser"], ppe=False)
    assert {event for _, event in actor.pushed} == {None}
    assert run.counts["profile"] == 1 and run.counts["post"] == 4


async def test_spending_limit_stops_posts_but_delivers_the_profile():
    # Room for 1 profile ($0.004) and 2 posts ($0.002 each).
    actor, fetcher, run = await run_actor(["nasa", "nike"], limit="0.0085", concurrency=1)
    assert actor.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 2}
    assert actor.pushed[-1][0]["recordType"] == "profile" and actor.pushed[-1][0]["recentPostsAnalysed"] == 2
    assert run.stopped_at_limit and run.not_processed == 1
    assert len(fetcher.calls) == 3  # pages the user can't pay for are not fetched
    assert run.summary() == (
        "Stopped at your spending limit: 1 profile and 2 posts scraped. 1 input not processed, "
        "2 recent posts not fetched (raise the limit and run again for the rest)."
    )


async def test_spending_limit_with_parallel_workers_never_overcharges():
    actor, _, run = await run_actor(["nasa", "nike", "budweiser", "nosuchuser"], limit="0.009", concurrency=4)
    total = actor.manager.calculate_total_charged_amount()
    assert total <= Decimal("0.009")
    assert run.stopped_at_limit


async def test_free_rows_in_flight_do_not_stop_the_run_early():
    # Room for one profile only; the first workers pick inputs that turn out free.
    actor, _, run = await run_actor(["nosuchuser", "walled", "nasa"], limit="0.004", concurrency=3, include=False)
    assert actor.manager.counts[PROFILE_EVENT] == 1
    assert [r["error"] for r, _ in actor.pushed].count(None) == 1
    assert not run.stopped_at_limit


async def test_resume_after_migration_skips_done_work():
    state: dict = {}
    actor1, _, _ = await run_actor(["nasa", "nosuchuser"], state=state)
    assert len(actor1.pushed) == 6
    # The platform restarts the run with the saved state: nothing is pushed or charged twice.
    actor2, fetcher2, run2 = await run_actor(["nasa", "nosuchuser", "nike"], state=state, max_posts=1)
    assert [r["inputUrl"] for r, _ in actor2.pushed] == ["nike", "nike"]
    assert [url for url, _ in fetcher2.calls] == ["https://www.instagram.com/nike/", P + "Df0U_JQP8Y3/"]
    assert run2.counts["profile"] == 2


async def test_resume_mid_profile_reuses_pushed_posts():
    # Simulate a migration after 2 of nasa's posts were pushed but before its profile row.
    state: dict = {}
    first = FakeActor()
    run1 = ScrapeRun(Platform(first), FakeFetcher(), max_posts_per_profile=2, state=state)
    targets, _ = collect_targets(["nasa"], [])
    await run1.run(targets)
    state["done"].remove("user:nasa")
    state["profiles"].clear()
    pushed_posts = set(state["posts"])
    actor2, fetcher2, _ = await run_actor(["nasa"], state=state, max_posts=4)
    new_posts = [r["shortcode"] for r, _ in rows(actor2, "post")]
    assert not pushed_posts & set(new_posts)
    assert new_posts == ["DfSi56IFwZK", "Df3Rp0bKNdr"]
    profile = rows(actor2, "profile")[0][0]
    assert profile["recentPostsAnalysed"] == 4  # the two earlier posts still count


async def test_crash_in_fetcher_is_a_failed_row():
    class Broken(FakeFetcher):
        async def fetch(self, worker, url, expect):
            raise RuntimeError("boom")

    actor, _, run = await run_actor(["nasa"], fetcher=Broken())
    row, event = actor.pushed[0]
    assert row["error"] == output.FAILED and event is None
    assert run.counts[output.FAILED] == 1


async def test_platform_reservations():
    platform = Platform(FakeActor(ppe=False))
    assert all(platform.reserve(PROFILE_EVENT) for _ in range(1000))
    platform = Platform(FakeActor(ppe=True, limit="0.008"))
    assert platform.reserve(PROFILE_EVENT) and platform.reserve(POST_EVENT) and platform.reserve(POST_EVENT)
    assert not platform.reserve(POST_EVENT)
    platform.release(PROFILE_EVENT)
    assert platform.reserve(POST_EVENT) and platform.reserve(POST_EVENT) and not platform.reserve(PROFILE_EVENT)


class SnapshotDuringPushActor(FakeActor):
    """Saves RUN_STATE while a charged push is in flight, as a migration's PERSIST_STATE event can."""

    def __init__(self, state: dict, event: str) -> None:
        super().__init__()
        self.state, self.event, self.snapshot = state, event, None

    async def push_data(self, data, charged_event_name=None):
        if charged_event_name == self.event and self.snapshot is None:
            self.snapshot = copy.deepcopy(self.state)
        return await super().push_data(data, charged_event_name)


async def _restart_from_snapshot_taken_during_push(event, usernames, posts, max_posts):
    state: dict = {}
    first = SnapshotDuringPushActor(state, event)
    run1 = ScrapeRun(Platform(first), FakeFetcher(), max_posts_per_profile=max_posts, state=state)
    targets, _ = collect_targets(usernames, posts)
    await run1.run(targets)
    assert first.snapshot is not None
    # The container is killed after the push landed; the platform restarts from the saved state.
    second = FakeActor()
    run2 = ScrapeRun(Platform(second), FakeFetcher(), max_posts_per_profile=max_posts, state=first.snapshot)
    await run2.run(targets)
    return first, second, run2


async def test_restart_after_state_saved_mid_push_never_charges_a_post_twice():
    first, second, run2 = await _restart_from_snapshot_taken_during_push(POST_EVENT, [], [P + "DfahZrMjAqq/"], 0)
    assert first.manager.counts[POST_EVENT] == 1
    assert second.manager.counts[POST_EVENT] == 0, "the post row was pushed and charged again after the restart"
    assert run2.counts["post"] == 1 and not run2.counts["duplicate"]


async def test_restart_after_state_saved_mid_push_counts_the_profile_as_scraped():
    first, second, run2 = await _restart_from_snapshot_taken_during_push(PROFILE_EVENT, ["nasa"], [], 0)
    assert first.manager.counts[PROFILE_EVENT] == 1 and second.manager.counts[PROFILE_EVENT] == 0
    assert run2.counts["profile"] == 1 and not run2.counts["duplicate"]
    assert run2.summary() == "Done: 1 profile and 0 posts scraped."


async def test_restart_after_state_saved_mid_push_of_a_recent_post():
    first, second, run2 = await _restart_from_snapshot_taken_during_push(POST_EVENT, ["nasa"], [], 2)
    assert first.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 2}
    # Only the profile and its second post were left; the first post is counted, not pushed again.
    assert second.manager.counts == {PROFILE_EVENT: 1, POST_EVENT: 1}
    assert run2.counts["post"] == 1 + 1 and rows(second, "profile")[0][0]["recentPostsAnalysed"] == 2
