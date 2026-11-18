# Development notes

For people working on the code. The customer-facing description is `README.md`.

## Layout

| Path | What it does |
|---|---|
| `instagram_profile/inputs.py` | Turns `usernames` and `postUrls` (usernames, @handles, profile, post, reel and tv links) into unique targets |
| `instagram_profile/fetch.py` | curl_cffi sessions (Chrome impersonation, one per proxy IP), redirects, response classification, retries |
| `instagram_profile/parser.py` | Reads profile and post fields from the Relay preloads in the HTML (its docstring lists every key used) |
| `instagram_profile/output.py` | Row layout (every key in every row), engagement figures, pinned-post detection, error codes |
| `instagram_profile/billing.py` | Push and charge (`profile` and `post` events); reserves spending-limit room, in dollars, before each fetch |
| `instagram_profile/run.py` | Workers, profile -> recent posts -> profile row, duplicates, migration-safe progress (`RUN_STATE`), status text |
| `instagram_profile/main.py` | Actor entry point |
| `tests/scrub_fixtures.py` | Reduces a saved page to the parts the parser reads and removes people's data |
| `tools/capture.py` | Saves live pages to `raw/` (git-ignored) for exploration and new fixtures |

## How the data is read

Only the HTML pages a logged-out browser gets: `https://www.instagram.com/<username>/` (~800 KB) and
`https://www.instagram.com/p/<shortcode>/` (~680 KB). They embed Relay preloads:

- `PolarisLoggedOutDesktopWWWProfileRootContentQuery` -> `xig_user_by_username` (profile, exact follower counts)
- `PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery` -> the 12 grid posts (codes and types, no counts)
- `PolarisLoggedOutDesktopWWWPostRootContentQuery` -> `xig_polaris_media.if_not_gated_logged_out` (likes, comments, caption, media)

The page type is `"polarisRouteConfig":{...,"pageID":"profilePage|postPage|httpErrorPage"}`. Age-gated profiles
are `profilePage` with `xig_user_by_username: null` and `rootView.props.gating` set. The post count is not in
the JSON; it comes from the `og:description` meta tag, rounded by Instagram above 9,999.

## Rules

- Logged-out only: no login, no account cookies, no tokens, no `/graphql/query` or `/api/v1` calls.
  The logged-out comments query answers `401 require_login`; it is not called and no other comment route is tried.
- Preview comments sit in the post HTML (`comments_connection`); they are never read or output (personal data).
- Only temporary problems are retried, at most 2 more times on fresh proxy sessions. A login redirect is retried
  once on a fresh session (Instagram sends throttled IPs there), then it is a final `loginRequired` row.
- Only `profile` and `post` rows are charged. Error rows (also `privateProfile` and `restricted` profile rows
  with public counts) are pushed plainly. Do not add the synthetic `apify-default-dataset-item` event to the pricing.
- A profile's posts are fetched on the same worker (same proxy IP, paced 2-5 s); its row is pushed after them.
  Pushed posts are kept in `RUN_STATE.posts` (likes, comments, date), so after a migration they are neither
  pushed again nor lost from the profile's figures. A post reachable from two inputs is pushed once (per-shortcode lock).
- Pinned posts: the grid is newest first except up to 3 pinned posts at the top; a top-3 post older than a
  later post is pinned. They are left out of the posting frequency only.

## Tests

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

All tests are offline. `tests/fixtures/` holds real logged-out pages captured on 2026-11-18 from a US IP
(`index.json` has the status of each), **reduced and scrubbed** by `tests/scrub_fixtures.py`: only the meta tags,
the route excerpt and the three Relay preloads are kept; the owner's other posts are dropped from post pages, the
preview comments become one placeholder, and every account not on the brand allow-list (`ALLOWED`) becomes
`redacted.person.N`. `tests/test_fixtures_privacy.py` fails if a fixture is not reduced and scrubbed.

To add a fixture: `.venv/bin/python tools/capture.py name=url` (raw page into `raw/`, never committed), check the
captions for people's names (add them, one per line, to the git-ignored `raw/scrub_names.txt`; never to code) and brand handles (add them to `ALLOWED`), then
`.venv/bin/python tests/scrub_fixtures.py raw/name.html.gz`, add it to `tests/fixtures/index.json` and write the test.

## Run locally

Put an input in `storage/key_value_stores/default/INPUT.json` (use `"proxyConfiguration": {"useApifyProxy": false}`
without an Apify proxy password) and run `.venv/bin/python -m instagram_profile`.
