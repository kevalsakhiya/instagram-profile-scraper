"""The .actor files must match the code."""

import json
import re
from pathlib import Path

from instagram_profile import output
from instagram_profile.billing import EVENTS
from instagram_profile.main import (
    DEFAULT_CONCURRENCY,
    DEFAULT_PROXY,
    MAX_CONCURRENCY,
    MAX_POSTS_PER_PROFILE,
    read_concurrency,
    read_max_posts,
)
from instagram_profile.output import FIELDS
from instagram_profile.run import DEFAULT_MAX_POSTS

ROOT = Path(__file__).resolve().parent.parent
ACTOR = ROOT / ".actor"


def load(name):
    return json.loads((ACTOR / name).read_text())


def test_dataset_views_use_real_fields():
    for name, view in load("dataset_schema.json")["views"].items():
        fields = view["transformation"]["fields"]
        assert set(fields) <= set(FIELDS), name
        assert set(fields) == set(view["display"]["properties"]), name


def test_every_output_field_is_documented_in_the_readme():
    readme = (ACTOR / "README.md").read_text()
    table = readme[readme.index("## Output fields") :]
    for field in FIELDS:
        assert f"`{field}`" in table, field


def test_every_error_code_is_in_the_readme():
    readme = (ACTOR / "README.md").read_text()
    codes = [v for k, v in vars(output).items() if k.isupper() and isinstance(v, str) and v not in ("profile", "post")]
    for code in codes:
        assert f"`{code}`" in readme, code


def test_events_in_readme_pricing():
    readme = (ACTOR / "README.md").read_text()
    pricing = readme[readme.index("## Pricing") :]
    for event in EVENTS:
        assert re.search(rf"\| `{event}` \|", pricing), event


def test_input_defaults_match_code():
    props = load("input_schema.json")["properties"]
    assert props["proxyConfiguration"]["default"] == DEFAULT_PROXY
    assert props["maxConcurrency"]["default"] == DEFAULT_CONCURRENCY
    assert props["maxConcurrency"]["maximum"] == MAX_CONCURRENCY
    assert props["maxPostsPerProfile"]["default"] == DEFAULT_MAX_POSTS
    assert props["maxPostsPerProfile"]["maximum"] == MAX_POSTS_PER_PROFILE
    assert props["includeRecentPosts"]["default"] is True
    assert set(props) == {"usernames", "includeRecentPosts", "maxPostsPerProfile", "postUrls", "maxConcurrency", "proxyConfiguration"}


def test_output_schema_views_exist():
    views = load("dataset_schema.json")["views"]
    for key, prop in load("output_schema.json")["properties"].items():
        match = re.search(r"view=(\w+)", prop["template"])
        if match:
            assert match.group(1) in views, key


def test_actor_name():
    actor = load("actor.json")
    assert actor["name"] == "instagram-profile-scraper"
    assert actor["title"] == "Instagram Profile & Engagement Scraper"


def test_read_numbers():
    assert read_concurrency(None) == DEFAULT_CONCURRENCY
    assert read_concurrency("x") == DEFAULT_CONCURRENCY
    assert read_concurrency(0) == 1
    assert read_concurrency(99) == MAX_CONCURRENCY
    assert read_max_posts(None) == DEFAULT_MAX_POSTS
    assert read_max_posts(50) == 12
    assert read_max_posts(-1) == 0
    assert read_max_posts("3") == 3
