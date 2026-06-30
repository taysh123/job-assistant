# Decision log

Append-only. Newest first. Each entry: what was decided, why, and what it rules out.

## 2026-06-12 — Region-locked foreign "remote" roles are hard-excluded
A "remote" job whose location field names a denied foreign region (e.g. remote but
"Sofia" / "Canada" only) is **excluded**, not downranked — unless the location
contains an *anywhere / worldwide / global / remote* marker (or is empty).
**Why:** explicit user choice — such roles aren't hireable from Israel; the user
optimizes for high signal / low noise and accepts a small edge-case-coverage risk.
**Rules out:** downranking them or leaving remote fully location-agnostic.

## 2026-06-09 — Junior signal outranks geography (ranking, not gating)
Dedicated `junior_boost_keywords` (title-only, weight 8) above the location boost
(weight 3, capped at 2 hits via `LOCATION_BOOST_CAP`). A remote Junior role sorts
above a generic Tel-Aviv role.
**Why:** first-job search — explicit Junior/Graduate/Entry postings are the highest
value leads; location preference is secondary. The cap stops one multi-token
location string from stacking past two tiers.

## 2026-06-09 — Engineering-focused profile: analyst/scientist/designer denied
`titles_allow` dropped "data analyst" / "data scientist"; `titles_deny` excludes
analyst/scientist/researcher/designer plus non-software engineering disciplines
(electrical, mechanical, GxP/lab, …) and pure ops/SRE. Junior DevOps, QA Automation,
Data Engineer and ML Engineer remain eligible.
**Why:** the broad "engineer"/"developer" allow-terms admit any "X Engineer"; real
digests filled with non-dev roles. Title-only matching keeps dev roles that merely
mention such words in their summary.

## 2026-06-09 — Digest shows fit badges, not the raw score
Cards display 🟢 Junior / 🏠 Remote derived from match reasons; the internal score
number was removed from the UI.
**Why:** the score is a ranking artifact, meaningless to the reader on mobile;
badges answer "why am I seeing this?" directly.

## Earlier (baseline) decisions still in force

- **`experience_mode: filter`, `max_years_experience: 2`** — roles *explicitly*
  requiring more years are removed; roles with no stated years are never touched.
  Right for a no-experience grad; switch to `downrank` to make them visible again.
- **Location preference is ranking-only** — `locations_allow` stays empty; a hard
  geo allow-gate would drop valid Israeli towns/abbreviations (e.g. "TLV").
  Center-Israel preference is expressed via boost tiers. `locations_deny` removes
  foreign roles.
- **No title-seniority allow-gate** (`seniority_allow: []`) — generic "Software
  Engineer" postings are often junior; gating on "junior" in the title would lose
  them. `seniority_deny` + experience detection trim the senior end.
- **One paginated digest message** per run (not N cards) — page state in SQLite
  `bot_state`, current page carried in `callback_data` so actions never lose the
  user's place; survives stateless cron runs.
- **Interactivity via cron + optional local watcher** — GH Actions can't host a live
  bot; `bot.yml` drains updates every 20 min, `process-updates --watch` gives
  near-instant handling when actively browsing. Telegram allows one `getUpdates`
  consumer: overlap yields a harmless 409.
- **Standing product constraints** (docs/project-vision.md): no login scraping, no
  captcha bypass, no auto-apply, no AI in v1, no extra infrastructure — GitHub
  Actions + SQLite + Telegram at ~zero cost; DB committed to the repo as the single
  durable state copy.
