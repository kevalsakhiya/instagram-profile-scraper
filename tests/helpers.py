"""Fixture loading shared by the tests."""

from __future__ import annotations

import gzip
import json
from functools import cache
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# Real logged-out responses captured 2026-11-18 from a US IP, reduced and scrubbed with
# tests/scrub_fixtures.py (see DEVELOPMENT.md).
PROFILE_FIXTURES = ("nasa", "nike", "budweiser", "nouser")
POST_FIXTURES = ("post_nasa_reel", "post_nasa_image", "post_nasa_collab", "post_natgeo_carousel", "post_missing")


def names() -> list[str]:
    return sorted(p.name.removesuffix(".html.gz") for p in FIXTURES.glob("*.html.gz"))


@cache
def html(name: str) -> str:
    return gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes()).decode("utf-8")


@cache
def index() -> dict:
    return json.loads((FIXTURES / "index.json").read_text())
