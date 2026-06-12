# Project State

> Single entry point for resuming development. Read this first, then
> [project-vision.md](project-vision.md) (goals/constraints), the
> [README](../README.md) (architecture, setup, config reference),
> [DECISIONS.md](DECISIONS.md) (why things are the way they are), and the
> [CHANGELOG](../CHANGELOG.md) (what changed when).

## Snapshot — 2026-06-12

| | |
|---|---|
| Branch / commit | `main` @ `6e1dd7f`, working tree clean |
| Version | `1.0.0` (pyproject baseline; no git tags yet) |
| Tests | **123 passing** (`pytest`, offline, no network) |
| Database | `data/jobs.db` committed; 261 jobs, runs 1–17, digests for messages 42–54 |
| Job statuses | All 261 still `new` — the user has not yet pressed Save/Ignore/Applied in production |
| Production | GH Actions crons live: `collect` (07:00/18:00 UTC), `bot` (every 20 min), `weekly` (Mon 08:00 UTC) |

## Latest milestone

**Filtering/ranking tuned for the real user profile (CS grad, no experience,
Israel-wide + remote, center-preferred) and validated against real collected data.**

Two sessions of work, all committed:

1. `a99a786` + `e995422` — Telegram pagination hardening; `process-updates --watch`
   local watcher for instant Prev/Next; junior-boost ranking tier (junior signal
   outranks location); location-boost cap; engineering-focused allow/deny lists;
   digest fit badges (🟢 Junior · 🏠 Remote) replacing the raw score.
2. `6e1dd7f` (this session) — region-locked foreign "remote" roles are now excluded
   (remote job pinned to a denied region, no anywhere/worldwide/global/remote marker);
   three more observed noise titles denied; `/config` reports all six sources.

**Evidence:** replaying the current filters over all 261 stored jobs excludes 38
previously-sent noise rows (analysts, support/SRE/founding engineers, foreign on-site,
region-locked remote, explicit 3–5y-experience roles) while keeping every junior /
Israel / globally-remote dev role. The Israel-located drops were individually checked:
all require 3–5 years explicitly (experience filter working as intended).

## Architecture status

Stable; no structural changes pending. The README's diagram and "Project layout"
section are accurate: `sources/` (base + per-source modules + registry) →
`filtering/` (filters + experience + dedup) → `db/` (schema + Repository) →
`telegram/` (client / formatting / pagination / digest / handlers) → GH Actions
crons. Adding a source = one module in `sources/`, a config block, one line in
`sources/registry.py`.

## Known limitations (accepted, v1)

- **Button latency**: cron-based `bot.yml` means up to ~20 min to process presses;
  the `--watch` watcher is the interactive workaround. Only one `getUpdates`
  consumer is allowed — an overlapping cron run gets a harmless 409 and skips.
- **Digest cap**: `pipeline.py` sends only the top `digest.max_jobs` (25) of a run's
  new jobs; overflow is persisted as seen and never sent. Non-issue at current
  volume (runs produce 0–7 new jobs). `reset-seen-jobs` exists if it ever matters.
- **LinkedIn email parsing** is best-effort (title + link guaranteed, rest may be
  missing). Comeet and LinkedIn sources are configured but disabled by default.
- **Substring matching**: all filters are case-insensitive substring checks — cheap
  and predictable, but new noise patterns need manual deny-list additions.
- **Privacy**: `data/jobs.db` is committed to the repo; making the repo public
  exposes the job history.

## Recommended next steps

1. **Use the buttons in production** — every job is still `new`; Save/Ignore/Applied
   and the watcher flow have passing tests but no real-world soak from the user yet.
2. **Watch the next few collect runs** for residual noise or over-filtering after the
   2026-06-09/12 tightening; extend `titles_deny` / `locations_deny` from evidence
   (replay technique below) rather than speculation.
3. Optional, when wanted: enable `comeet` (add company uid/token pairs) and/or
   `linkedin` (IMAP secrets); tag a `v1.1.0` release once the new filters have
   soaked; pause `bot.yml` during long watcher sessions.

No known bugs as of this snapshot.

## How to verify after changes

```powershell
pytest -q                                  # full offline suite
python -m job_assistant.cli collect --dry-run   # CAUTION: marks unseen jobs seen
```

Prefer the **offline replay** over a live dry-run for filter tuning (a dry-run
persists jobs as seen without sending them): build `Job` objects from every row in
`data/jobs.db` and run them through
`FilterEngine(load_config("config/config.yaml").filters).evaluate`, then diff
kept/dropped against `telegram_message_id` (was it previously sent?). This is how the
2026-06-12 changes were validated; it needs no network and writes nothing.
