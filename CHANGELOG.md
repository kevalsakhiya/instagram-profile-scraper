# Changelog

## 0.1 (2026-11-18)

- First version: profile rows (exact followers and following, posts, bio, links in bio, verified, private),
  recent post rows (type, date, caption, hashtags, mentions, likes, comments, images, video, location, collab)
  and engagement figures (average likes and comments, engagement rate, posting frequency without pinned posts,
  last post date). Single post and reel links.
- Pay per event: `profile` and `post`; error rows are free. Spending-limit room is reserved before each page.
- Free error rows: `notFound`, `privateProfile`, `restricted` (age-gated), `loginRequired`, `blocked`,
  `invalidInput`, `failed`.
- Logged-out only, curl_cffi Chrome impersonation, one session per proxy IP, at most 2 retries on fresh IPs.
- Restart safety: a post or profile is recorded in RUN_STATE before its charged push, so state saved while the
  push is in flight never leads to a second charge, and the row still counts as scraped after the restart.
- A single string given instead of a list of usernames or post links is read one entry per line.
