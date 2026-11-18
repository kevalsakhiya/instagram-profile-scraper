"""The committed pages carry no personal data: every fixture is already reduced and scrubbed (doing it again
changes nothing), and no person's handle, name, photo, comment or other caption is left."""

from __future__ import annotations

import json
import re

import pytest

from .helpers import FIXTURES, html, names
from .scrub_fixtures import ALLOWED, NAMES, REDACTED, REDACTED_COMMENT, REDACTED_PIC, reduce_page

ALL = names()


def _relay_values(page: str):
    for match in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', page, re.S):
        yield json.loads(match.group(1))


def _walk(node, path=()):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, path)


def test_only_scrubbed_fixtures_are_committed():
    assert ALL, "no fixtures"
    assert {p.name for p in FIXTURES.iterdir()} == {f"{n}.html.gz" for n in ALL} | {"index.json"}
    assert set(json.loads((FIXTURES / "index.json").read_text())) == set(ALL)


@pytest.mark.parametrize("name", ALL)
def test_fixture_is_reduced_and_scrubbed(name):
    page = html(name)
    assert reduce_page(page) == page, f"run: .venv/bin/python tests/scrub_fixtures.py raw/{name}.html.gz"
    assert len(page) < 200_000  # reduced, never a raw 800 KB capture
    for person in NAMES:
        assert person not in page
    for handle in re.findall(r"(?:@|&#064;)([A-Za-z0-9_.]{1,30})", page):
        handle = handle.rstrip(".").lower()
        assert handle in ALLOWED or handle.startswith(REDACTED), handle
    for doc in _relay_values(page):
        for path, node in _walk(doc):
            username = node.get("username")
            if isinstance(username, str):
                assert username.lower() in ALLOWED or username.startswith(REDACTED), (path, username)
                if username.startswith(REDACTED):
                    for key in ("profile_pic_url", "profile_image_uri"):
                        assert node.get(key, REDACTED_PIC) == REDACTED_PIC
                    assert str(node.get("id", "0")) == "0" and str(node.get("pk", "0")) == "0"
            if "comments_connection" in node and node["comments_connection"]:
                edges = node["comments_connection"].get("edges") or []
                assert [e["node"]["text"] for e in edges] == [REDACTED_COMMENT] * len(edges)
            if path[-1:] == ("if_not_gated_logged_out",):
                assert "polaris_ordered_timeline_connection" not in (node.get("user") or {})


def test_scrub_removes_people_and_keeps_brand_data():
    page = html("post_nasa_image").replace(
        '"usertags":{"in":[]}',
        '"usertags":{"in":[{"user":{"id":"42","username":"jane.doe","full_name":"Jane Doe",'
        '"profile_pic_url":"https://scontent.cdninstagram.com/v/jane.jpg"}}]}',
        1,
    ).replace("Galaxy in bloom", "Galaxy in bloom by @jane.doe and @NASAHubble, photo Zoë Exampleperson", 1)
    clean = reduce_page(page, names=("Zoë Exampleperson",))
    for leak in ("jane.doe", "Jane Doe", "jane.jpg", '"42"', "Exampleperson"):
        assert leak not in clean, leak
    assert "@redacted.person.1 and @NASAHubble" in clean
    assert '"username":"redacted.person.1","full_name":"Redacted Person 1"' in clean
    assert reduce_page(clean, names=("Zoë Exampleperson",)) == clean
