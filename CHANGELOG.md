# Changelog

Notable changes, newest first. Version `1.0.0` is the `pyproject.toml` baseline;
no git tags yet. Routine `chore(data): …` commits (Actions committing `data/jobs.db`)
are not listed.

## Unreleased — 2026-06-12 (`6e1dd7f`)

### Changed
- **`locations_deny` now also drops region-locked "remote" roles** — a remote job
  whose location pins it to a denied foreign region (e.g. remote but "Sofia" or
  "Canada" only) is excluded, since it isn't hireable from Israel. A remote location
  containing *anywhere / worldwide / global / remote* (or no location at all) always
  stays eligible. On-site behavior unchanged. (`filtering/filters.py`)
- `titles_deny` additions observed slipping into real digests: `it specialist`,
  `developer advocate`, `noc engineer` (both config files).
- `/config` command now also reports the `comeet` and `linkedin` source state.
- Watch-loop exception handling simplified (redundant clause removed).

### Validation
Replayed the full filter set over all 261 collected jobs in `data/jobs.db`:
38 previously-sent noise rows (analyst/support/SRE/founding titles, foreign on-site,
region-locked remote, explicit 3–5-year-experience roles) would now be excluded;
every junior / Israel / globally-remote dev role survives. 123 tests passing.

## 2026-06-09 (`e995422`, `a99a786`)

### Added
- **`process-updates --watch`**: local long-poll loop for near real-time Prev/Next
  and button handling (~1–2 s) while actively browsing; the 20-min `bot.yml` cron
  remains the fallback. Client read-timeout extended past Telegram's server-side
  wait; transient errors / 409s retried.
- **Junior ranking tier**: `junior_boost_keywords` / `junior_boost_weight` (title-only,
  weight 8) so explicit Junior/Graduate/Entry roles sort above same-tech non-junior
  roles regardless of location.
- Digest cards show meaningful fit badges (🟢 Junior · 🏠 Remote) instead of the raw
  internal score.

### Changed
- Location boost capped (`LOCATION_BOOST_CAP = 2`) so one multi-token location
  ("Tel Aviv-Yafo, Gush Dan, Israel") can't stack past the intended two tiers.
- Engineering-focused profile: analyst/scientist titles removed from `titles_allow`;
  `titles_deny` greatly expanded (non-software engineering disciplines, GxP/lab,
  SRE/ops, analyst/scientist/designer/founding/admin roles); more foreign locations
  denied. Telegram pagination hardened (state self-heal, page carried in
  `callback_data`).

## 1.0.0 — baseline

Initial system: scheduled collection from Remotive / WeWorkRemotely / Greenhouse /
Lever (optional Comeet, LinkedIn alert-email ingestion) → keyword/rule filtering with
match-reason scoring → dedup → SQLite → one paginated Telegram digest with
Save / Ignore / Open / Mark-Applied → weekly summary. Runs free on GitHub Actions
crons (`collect` / `bot` / `weekly` / `ci`), DB committed back to the repo.
