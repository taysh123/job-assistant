# Job Assistant — Diagnostic Report

> **Read-only analysis.** Nothing in the codebase was modified to produce this report.
> Generated 2026-06-30 against `main` @ `47b8b53` (working tree clean). Version `1.0.0`.
> Verified by reading every file under `src/job_assistant/`, `config/`, `.github/`, and
> `tests/`, and by running the test suite live (`123 passed`).
> Line references are `file:line` against the current tree.

---

## 1. Executive summary

**Job Assistant is a personal, deterministic, low-cost job-finding bot.** On a GitHub
Actions cron it collects software-engineering postings from public APIs / RSS feeds,
filters and ranks them against a YAML preference profile, removes duplicates, persists
everything to a committed SQLite file (`data/jobs.db`), and delivers **one paginated
Telegram digest message** — one job card per page with `⬅️ Prev / Next ➡️` navigation and
`💾 Save / 🙈 Ignore / 🔗 Open / ✅ Mark-Applied` buttons. A weekly summary reports what was
found and what the user did with it.

By explicit design (`docs/project-vision.md`, `docs/CLAUDE.md`) v1 does **not**: submit
applications, scrape behind logins/captchas, or use any AI. Filtering is case-insensitive
keyword/rule matching. The whole system runs at ~zero cost on free GitHub Actions minutes
+ SQLite + the Telegram Bot API.

**End-to-end flow (one `collect` run):**

```
build_sources(config, secrets)        # registry: only enabled sources
  → source.collect() × N              # sources/*  (never raise; return [] on failure)
  → FilterEngine(config.filters).filter()   # filtering/filters.py  (allow/deny/boost, sort by score desc)
  → filter_unseen(matched, repo)      # filtering/dedup.py  (in-batch + DB-unseen by dedup_key)
  → repo.insert_new_jobs()            # db/repository.py  (INSERT OR IGNORE, status='new')
  → send_digest(client, repo, inserted[:max_jobs])  # telegram/  (ONE paginated message)
  → repo.record_run("collect", counts)
```

### Maturity matrix

| Area | State | Notes |
|---|---|---|
| Collection (Remotive, WWR, Greenhouse, Lever) | **Works** | 4 sources enabled; offline-tested `parse()` |
| Comeet source | **Works but OFF** | `enabled: false`, `companies: []` — code complete, zero companies configured |
| LinkedIn-email source | **Partial + OFF** | `enabled: false`; regex email scraping is best-effort; IMAP secrets not wired into any workflow |
| Filtering / scoring / experience detection | **Works** | Deterministic; one real substring bug (§12, Jerusalem) |
| Dedup | **Works** | Two-layer; cross-source merge intentionally not done (§6) |
| SQLite persistence | **Works** | 3 tables; no migration framework (§7) |
| Telegram digest + pagination | **Works** | Stateless paging via `callback_data`; self-heal |
| Telegram commands | **Works** | `/today /saved /applied /stats /config /help` (+ `/start`) |
| `OPENED` status | **Dead** | Declared everywhere; never written by any handler (§8, §12) |
| Weekly summary | **Works** | 7-day status/source/keyword rollup |
| CI / deployment | **Works** | 4 workflows; DB committed back; serialized on one concurrency group |
| Test suite | **Works** | **123 passing**, 0 failures, 0 skips, 0 warnings |
| TODO/FIXME debt | **None** | Zero `TODO`/`FIXME`/`XXX`/`HACK` markers in `src/` or `tests/` |

**Bottom line:** the core pipeline is production-quality and well-tested. The open
questions are operational (is the cron still running? — §11/§13) and coverage-oriented
(IL-specific sources, the Jerusalem substring bug — §12), not structural.

---

## 2. Architecture & full data flow

### 2.1 Orchestrator — `pipeline.py`

Two functions drive everything (`pipeline.py:19-68`):

- **`collect_all(config, secrets)`** (`:19-26`) — calls `build_sources(...)`, loops each
  source calling `source.collect()`, logs `"source %s returned %d jobs"`, and flattens to
  one `list[Job]`. Sources are guaranteed never to raise.
- **`run_collection(config, secrets, repo, *, send=True)`** (`:29-68`) — the full pipeline.

**Exact stage order (the object that flows is `list[Job]`):**

1. **Collect** — `raw = collect_all(config, secrets)` (`:36`).
2. **Filter + rank** — `matched = FilterEngine(config.filters).filter(raw)` (`:37`). Drops
   non-matches, returns survivors **sorted by `score` descending**.
3. **Dedup** — `new_jobs = filter_unseen(matched, repo)` (`:38`). Removes anything whose
   `dedup_key` already exists in SQLite (and intra-batch duplicates).
4. **Persist** — `inserted = repo.insert_new_jobs(new_jobs)` (`:39`). `INSERT OR IGNORE`;
   returns only the rows actually written, each with `id` set and `status='new'`.
5. **Deliver** (`:41-58`):
   - If `send and inserted` and `secrets.is_configured`: `to_send = inserted[:config.digest.max_jobs]`
     (cap **25**), then `send_digest(client, repo, to_send, summary_chars=config.digest.summary_chars,
     page_size=config.digest.page_size, tz=config.digest.timezone)` — i.e. `280 / 1 / "Asia/Jerusalem"`
     from the live config. **All four digest values are read from config, not hardcoded.**
   - If `send and not inserted` (and configured): sends an **empty "no new jobs" digest** (`:55-58`).
   - If `not secrets.is_configured`: logs a warning and **sends nothing** (`:43-44`) — note this
     is a silent no-op as far as Actions is concerned (§12).
   - `send=False` (dry-run): filter/dedup/persist still run; nothing is sent.
6. **Record** — `counts = {collected, matched, new, sent}`; `repo.record_run("collect", counts)`;
   returns `counts` (`:60-68`).

### 2.2 What schedules it

Three GitHub Actions crons drive the runtime (all serialized on one `concurrency` group
`job-assistant-db` so they never clash writing the DB), plus a test workflow:

| Workflow | Trigger | Runs |
|---|---|---|
| `collect.yml` | `0 7 * * *` & `0 18 * * *` (07:00 & 18:00 UTC) | `cli collect` → commit db |
| `bot.yml` | `*/20 * * * *` (every 20 min) | `cli process-updates` → commit db |
| `weekly.yml` | `0 8 * * 1` (Mon 08:00 UTC) | `cli weekly` → commit db |
| `ci.yml` | push to `main` (ignoring `data/**`) + PRs | `pytest` |

Interactivity is asynchronous: button presses/commands are processed at the next `bot.yml`
run (≤20 min latency), or near-instantly via the local `process-updates --watch` long-poll
loop. State persists entirely in `data/jobs.db`, which is committed back after each run as
the single durable copy (details §9).

---

## 3. Module-by-module breakdown (`src/job_assistant/`)

| File | Responsibility | Key functions / classes |
|---|---|---|
| `__init__.py` | Package marker | — |
| `models.py` | Core data model + dedup identity | `Job` dataclass (`:46-80`); `JobStatus` str-enum (`:12-19`); `compute_dedup_key` (`:33-43`); `_normalize` (`:29-30`); `ACTIONABLE_STATUSES` (`:23`, unused) |
| `config.py` | Pydantic config + env secrets | `Config` (`:144`), `SourcesConfig` (`:79`), `FiltersConfig` (`:90`), `DigestConfig` (`:135`), `Secrets` (`:152`); `load_config` (`:172`), `load_secrets` (`:186`) |
| `pipeline.py` | Orchestration | `collect_all` (`:19`), `run_collection` (`:29`) |
| `cli.py` | Command-line entrypoints | `build_parser` (`:158`), `main` (`:200`), `HANDLERS` table (`:189`), `cmd_*` handlers |
| `sources/base.py` | `Source` ABC + safety wrapper | `Source` (`:27`), `_get` (`:44`), `_safe_collect` (`:50`); `DEFAULT_TIMEOUT=20`, `USER_AGENT` |
| `sources/remotive.py` | Remotive REST JSON | `parse` (`:32`), `RemotiveSource.collect` |
| `sources/weworkremotely.py` | WWR RSS (feedparser) | `parse` (`:41`), `_split_title` (`:33`) |
| `sources/greenhouse.py` | Greenhouse board API | `parse(payload, board)` (`:37`) |
| `sources/lever.py` | Lever postings API | `parse(payload, board)` (`:30`) |
| `sources/comeet.py` | Comeet Careers API (per-company isolation) | `parse(payload, company)` (`:43`), `_details_text` (`:28`) |
| `sources/linkedin_email.py` | LinkedIn Job-Alert email via IMAP | `parse(html_text)` (`:53`), `_JOB_LINK_RE` (`:31`), `_html_part` (`:100`) |
| `sources/registry.py` | Config → source instances | `build_sources(config, secrets)` (`:24`) |
| `filtering/filters.py` | Allow/deny gating + scoring + ranking | `FilterEngine.evaluate` (`:61`), `.filter` (`:133`), `_haystack`/`_boost_haystack` (`:41-49`), `_contains_any` (`:52`) |
| `filtering/experience.py` | "X years experience" detection | `required_years(text)` (`:34`), `_PATTERNS`/`_RANGE`/`_SENIOR` (`:17-31`) |
| `filtering/dedup.py` | Dedup (in-batch + DB-unseen) | `dedup_in_batch` (`:15`), `filter_unseen` (`:27`) |
| `db/schema.sql` | DDL (idempotent) | tables `jobs`, `runs`, `bot_state` |
| `db/repository.py` | SQLite persistence layer | `Repository` (`:43`) + ~18 methods (§7) |
| `telegram/client.py` | Telegram Bot API wrapper | `TelegramClient` (`:23`): `send_message`, `edit_message_text`, `answer_callback_query`, `get_updates`; `TelegramError` |
| `telegram/formatting.py` | Cards, keyboards, badges | `format_job_card` (`:54`), `job_keyboard` (`:81`), `format_digest_page` (`:123`), `digest_keyboard` (`:169`), `_fit_badges` (`:112`), `format_job_list` (`:200`) |
| `telegram/digest.py` | Build & send the paginated digest | `send_digest` (`:17`) |
| `telegram/pagination.py` | Page state machine | `save_digest`/`load_digest` (`:25-36`), `page_slice` (`:39`), `render_page` (`:48`); `DEFAULT_PAGE_SIZE=5` |
| `telegram/handlers.py` | Buttons, commands, update drain | `handle_callback` (`:67`), `handle_command` (`:163`), `process_updates` (`:199`), `watch_updates` (`:220`); `CALLBACK_STATUS` (`:25`) |
| `summary/weekly.py` | Weekly rollup message | `build_weekly_summary` (`:20`), `send_weekly_summary` (`:44`), `_top_keywords` (`:14`) |

---

## 4. Sources deep-dive

All sources subclass `Source` (`sources/base.py:27-40`). The contract (module docstring
`base.py:5-9`): each source has a **module-level pure `parse(...)`** (offline/fixture-testable,
no network) and a private `_fetch_and_parse()` doing the HTTP/IMAP call; `collect()` is
literally `return self._safe_collect(self._fetch_and_parse)`. `_safe_collect` (`base.py:50-56`)
wraps the call in `try/except Exception`, logs `"source %s failed: %s"` at WARNING, and
returns `[]` — **this is the guarantee that one broken source can't break a run.** Shared
constants: `DEFAULT_TIMEOUT = 20`, `USER_AGENT = "job-assistant/1.0 (+https://github.com/) personal-use"`.

Every source returns `list[Job]`. Downstream fields (`score`, `match_reasons`, `id`,
`status`) are left at their defaults; sources populate `source, external_id, title,
company, url, location, remote, posted_at, summary`.

### Remotive — `sources/remotive.py` (REST JSON) — **ENABLED**
- **Fetch:** `GET https://remotive.com/api/remote-jobs` (`:15`), params `{"limit": 100}` (+
  optional `category`/`search`). Config lists `categories: ["software-dev"]` but the API
  **ignores the category param** (returns one general feed) — documented at `config.yaml:9-10`
  and `remotive.py:1-3`.
- **Parse:** `parse(payload)` over `payload["jobs"]` (`:32-49`); HTML stripped via regex
  `_TAG_RE = <[^>]+>`.
- **Fields:** `source="remotive"`, `external_id=str(id)`, `company=company_name`,
  `location=candidate_required_location or "Remote"`, `remote=True` (**hard-coded — all
  Remotive jobs are remote**), `posted_at=publication_date` (**naive datetime** — see §12),
  `summary=description` (stripped).

### We Work Remotely — `sources/weworkremotely.py` (RSS via feedparser) — **ENABLED**
- **Fetch:** `GET https://weworkremotely.com/categories/{slug}.rss` (`:19`), one per feed slug.
- **Parse:** `feedparser.parse(...)` over `entries` (`:41-64`). Title split on the **first
  colon** — `_split_title("Company: Title") → (company, title)`, fallback `("", raw)` when
  no colon (`:33-38`). `external_id` = last URL path segment (`:48-49`).
- **Fields:** `remote=True` (hard-coded), `location = region or location or "Remote"`,
  tz-aware `posted_at` from `published_parsed`.
- **Configured feeds (4):** `remote-programming-jobs`, `remote-full-stack-programming-jobs`,
  `remote-back-end-programming-jobs`, `remote-front-end-programming-jobs`.

### Greenhouse — `sources/greenhouse.py` (board API) — **ENABLED**
- **Fetch:** `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`
  (`:16,68-73`), one per board.
- **Parse:** over `payload["jobs"]` (`:37-55`); `content` HTML-unescaped + stripped;
  `posted_at` from **`updated_at`** (not created); `remote = "remote" in location.lower()`.
- **Fields:** `company = board` — **the config slug**, lowercase (e.g. `catonetworks`), shown
  as-is on the card (§12). `url=absolute_url`.
- **Configured boards (23):** `via, catonetworks, jfrog, payoneer, similarweb, taboola,
  fireblocks, forter, axonius, riskified, transmitsecurity, yotpo, augury, melio, orcasecurity,
  saltsecurity, lightricks, bigid, pagaya, bringg, cybereason, nice, appsflyer`.

### Lever — `sources/lever.py` (postings API) — **ENABLED**
- **Fetch:** `GET https://api.lever.co/v0/postings/{board}?mode=json` (`:14,66`), one per board.
- **Parse:** over a **top-level list** (`:30-50`); `remote = workplaceType=="remote" or "remote"
  in location`; `posted_at` from `createdAt` as **epoch milliseconds** → tz-aware UTC;
  `summary=descriptionPlain` (already plain text).
- **Fields:** `company = board` (slug); `url=hostedUrl`.
- **Configured boards (1):** `logz`.

### Comeet — `sources/comeet.py` (Careers API) — **DISABLED** (`enabled: false`, `companies: []`)
- **Fetch:** `GET https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token=...&details=true`
  (`:20,78-81`), one per configured company. **Only source with per-company error isolation:**
  each company is wrapped in its own `try/except` → `logger.warning("comeet company %s failed", ...)`
  (`:77-84`), so one bad company doesn't drop the rest.
- **Fields:** `company = config name or item.company_name`; `url = url_comeet_hosted_page or
  url_active_page`; tz-aware `posted_at` from `time_updated`.
- **Currently:** off, with **zero companies configured** (only a commented `Example Co`).

### LinkedIn — `sources/linkedin_email.py` (IMAP email ingestion, NO scraping) — **DISABLED**
- **Fetch:** stdlib `imaplib.IMAP4_SSL(imap_host)` (`:127`); logs in with IMAP creds, searches
  `(FROM "<sender>" SINCE <date>)` for `today - max_age_days`, fetches the last `limit` messages.
- **Parse:** pure-regex HTML scraping (`:53-88`). `_JOB_LINK_RE` captures
  `href=".../jobs/view/(\d+)..."` + anchor title; skips generic anchors. **Company/location are
  best-effort heuristics**; `summary=""` **always blank** (`:86`); **`posted_at` never set →
  `None`** (only source that omits it). `url` reconstructed clean as
  `https://www.linkedin.com/jobs/view/{id}/`.
- **Config:** `imap_host: imap.gmail.com`, `imap_folder: INBOX`, senders
  `jobalerts-noreply@linkedin.com` + `jobs-noreply@linkedin.com`, `max_age_days: 3`,
  `mark_seen: false`, `limit: 50`. Gated on IMAP creds being present (registry).

### Registry wiring — `sources/registry.py`

`build_sources(config, secrets)` instantiates **only** enabled-and-configured sources
(`:24-35`):

| Config key | Class | Gate |
|---|---|---|
| `remotive` | `RemotiveSource` | `enabled` |
| `weworkremotely` | `WeWorkRemotelySource` | `enabled` **and** `feeds` non-empty |
| `greenhouse` | `GreenhouseSource` | `enabled` **and** `boards` non-empty |
| `lever` | `LeverSource` | `enabled` **and** `boards` non-empty |
| `comeet` | `ComeetSource` | `enabled` **and** `companies` non-empty |
| `linkedin` | `LinkedInEmailSource` | `enabled` **and** `secrets.is_imap_configured` |

### Sources ON in the current config

| Source | `enabled` | Effectively runs? |
|---|---|---|
| **remotive** | `true` | ✅ Yes |
| **weworkremotely** | `true` | ✅ Yes (4 feeds) |
| **greenhouse** | `true` | ✅ Yes (23 boards) |
| **lever** | `true` | ✅ Yes (1 board: `logz`) |
| comeet | `false` | ❌ No (and `companies: []`) |
| linkedin | `false` | ❌ No (and needs IMAP creds) |

**4 active sources: Remotive, We Work Remotely, Greenhouse, Lever.**

---

## 5. Filtering & scoring

Engine: `FilterEngine.evaluate(job)` (`filters.py:61-131`), executed in this exact order.
Two match surfaces and one matcher:
- `_haystack(job)` = `f"{title}\n{summary}".lower()` (title **+ summary**) (`:41-42`).
- `_boost_haystack(job)` = `f"{title}\n{location}".lower()` (title **+ location**, NOT summary) (`:45-49`).
- `_contains_any(text, needles)` = case-insensitive **substring** match returning hits in
  **config-list order** (`:52-54`).

### 5.1 Hard exclusions (run first, return `None` = drop)
| Check | Surface | Active value | Fires? |
|---|---|---|---|
| `keywords_deny` | title+summary | `[]` | never |
| `seniority_deny` | **title only** | `senior, sr., staff, principal, lead, head of, vice president, director, manager, architect, expert, experienced, 5+…10+ years, research scientist, phd, fellow, " ii", " iii", " iv"` | yes |
| `titles_deny` | **title only** | ~55 terms (`sales, support engineer, solutions engineer, …, analyst, scientist, designer, founding, it specialist, developer advocate, noc engineer`) | yes |
| `locations_deny` | **location only** | ~90 foreign cities/countries | yes, with global-marker exception |

The geo-deny logic (`:78-80`): if the location matches a denied term, drop **unless** the
job is remote AND `_location_is_global(location)` is true. `_location_is_global` (`:36-38`)
returns true when the location is empty or contains one of `("anywhere","worldwide","global",
"remote")`. So: on-site abroad → dropped; remote pinned to a denied region with no global
marker → dropped; remote + "anywhere/worldwide/global/remote" → kept. **(See §12 for the
`"usa" ⊂ "Jerusalem"` false-positive this produces.)**

### 5.2 Gates (all currently disabled / pass-through)
- `remote` mode `_passes_remote` (`:140-146`): active `"any"` → always passes.
- `locations_allow` `_passes_location` (`:148-155`): empty list → disabled; remote jobs always
  pass regardless. Active `[]`.
- `seniority_allow` `_passes_seniority` (`:157-161`): empty → disabled. Active `[]`.

### 5.3 Base score (`:91-103`)
```python
title_hits   = _contains_any(job.title, cfg.titles_allow)    # title only, UNCAPPED
keyword_hits = _contains_any(haystack, cfg.keywords_allow)   # title+summary
base = len(title_hits) + min(len(keyword_hits), KEYWORD_SCORE_CAP)   # KEYWORD_SCORE_CAP = 4
if base < cfg.min_match_score: return None        # min_match_score = 1
score = base
```
- `titles_allow` (24 terms) counted **fully (uncapped)**; `keywords_allow` (16 terms) capped at **4**.

### 5.4 Ranking boosts
- **Location boost** (`:106-109`): up to `LOCATION_BOOST_CAP = 2` hits from `_boost_haystack`,
  each `+boost_weight (3)` → **max +6**. Because `"israel"` is first in `boost_keywords`, an
  Israeli-center job scores `israel` + one center city. Reasons tagged `boost:<hit>`.
- **Junior boost** (`:112-115`): hits from `junior_boost_keywords` on the **title only,
  UNCAPPED**, each `+junior_boost_weight (8)`. Reasons tagged `junior:<hit>`. This is the
  heaviest signal by design — an explicit junior title outranks any location (decision log
  2026-06-09).

### 5.5 Experience adjustment (`:117-124`)
```python
req = required_years(haystack)
if req is not None and req > cfg.max_years_experience and cfg.experience_mode != "off":
    if cfg.experience_mode == "filter": return None     # ACTIVE MODE
    score -= cfg.experience_penalty                     # downrank mode only
```
`required_years` (`experience.py:34-44`) runs these patterns over title+summary and returns
**`min()`** of all years found (the lowest bar):
- `_PATTERNS[0]` — `(minimum|min|at least|requires?|required)\D{0,12}(\d{1,2})\s*\+?\s*years?`
- `_PATTERNS[1]` — `(\d{1,2})\s*\+?\s*years?(?:\s+of)?\s+(experience|industry|professional|hands-on|relevant|working|software|engineering|development|commercial|programming)`
- `_RANGE` — `(\d{1,2})\s*[-–]\s*\d{1,2}\s*years?\s+(of\s+)?(experience|exp)` → lower bound
- `_SENIOR` — `senior[- ]level` → sentinel `SENIOR_YEARS = 5`

**Catches:** `5+ years`, `minimum 3 years`, `at least 4 years`, `3-5 years of experience` (→3),
`senior-level`. **Does not catch:** plain `Software Engineer` (no digit), `0-2 years` (floor
keeps it `≤2`), or bare years with no experience-context word. With the **active
`experience_mode: "filter"` + `max_years_experience: 2`**, any role explicitly demanding >2
years is **removed**.

### 5.6 Final ranking (`filter`, `:133-136`)
```python
kept.sort(key=lambda j: j.score, reverse=True)   # score DESC, NO tie-breaker (stable → input order)
```

### 5.7 Worked example (real config values)

**Job:** title `Junior Backend Developer (Python)`, company `Riskified`, location
`Tel Aviv, Israel`, `remote=False`, summary `"…junior backend developer. Requirements: 1-2
years of experience with Python, SQL and Node.js. Strong software engineering fundamentals."`

| Step | Result |
|---|---|
| keywords_deny | `[]` → pass |
| seniority_deny (title) | no hit → pass |
| titles_deny (title) | no hit → pass |
| locations_deny (`tel aviv, israel`) | no foreign term → pass |
| remote/location/seniority gates | all pass (`any`/`[]`/`[]`) |
| `title_hits` (titles_allow) | `["developer","backend"]` → **2** |
| `keyword_hits` (keywords_allow) | `["junior","python","node","sql"]` → **4** |
| base = 2 + min(4,4) | **6** (≥ min_match_score 1 → kept) |
| location boost | `["israel","tel aviv"]` → +3 +3 → **12** |
| junior boost | `["junior"]` → +8 → **20** |
| experience | `min(1,2)=1`; `1 > 2`? no → unchanged |
| **FINAL** | **score = 20, PASSES** |

`match_reasons = [title:developer, title:backend, keyword:junior, keyword:python,
keyword:node, keyword:sql, boost:israel, boost:tel aviv, junior:junior]`.

**Contrast:** change the summary to "requires 5+ years" → `required_years=5`, `5 > 2` with
`experience_mode="filter"` → **dropped entirely** (returns `None`, no score).

---

## 6. Dedup

### 6.1 `dedup_key` composition (`models.py:33-43`, exposed as `Job.dedup_key` property `:72-80`)
```python
if external_id:
    basis = f"{source}::{external_id}"                                  # raw, not normalized
else:
    basis = f"{source}::{_normalize(title)}::{_normalize(company)}::{_normalize(url)}"
return hashlib.sha1(basis.encode("utf-8")).hexdigest()
```
`_normalize` (`:29-30`) lowercases, strips, and collapses whitespace runs (fallback branch
only). **`source` is part of the basis in both branches** — see the cross-source caveat in §12.

### 6.2 Two-layer dedup (`filtering/dedup.py`)
- **In-batch** — `dedup_in_batch(jobs)` (`:15-24`): keep first occurrence of each `dedup_key`
  within one run (collapses WWR's overlapping sub-feeds, Remotive's category passes, etc.).
- **DB-unseen** — `filter_unseen(jobs, repo)` (`:27-31`):
  ```python
  batch = dedup_in_batch(jobs)
  existing = repo.existing_dedup_keys([j.dedup_key for j in batch])
  return [j for j in batch if j.dedup_key not in existing]
  ```
  `existing_dedup_keys` queries SQLite (chunked by 500) and returns the subset already stored;
  anything matching is dropped. The DB's `UNIQUE(dedup_key)` + `INSERT OR IGNORE` is the final
  backstop at persist time, so each posting is sent exactly once.

---

## 7. Database

### 7.1 Schema (`db/schema.sql`) — idempotent (`IF NOT EXISTS` everywhere)

**Table `jobs`** (`:3-21`) — canonical posting store:
```sql
CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key           TEXT NOT NULL UNIQUE,
    source              TEXT NOT NULL,
    external_id         TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL,
    company             TEXT NOT NULL DEFAULT '',
    location            TEXT NOT NULL DEFAULT '',
    remote_flag         INTEGER NOT NULL DEFAULT 0,
    url                 TEXT NOT NULL,
    posted_at           TEXT,                       -- nullable
    summary             TEXT NOT NULL DEFAULT '',
    match_reasons       TEXT NOT NULL DEFAULT '[]', -- JSON array
    score               INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'new', -- new|saved|ignored|opened|applied (NO CHECK)
    telegram_message_id INTEGER,                    -- nullable
    first_seen_at       TEXT NOT NULL,
    last_status_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source     ON jobs(source);
```
Only `UNIQUE(dedup_key)` enforces identity. `status` is free-form TEXT — **no `CHECK`
constraint** (§12). Only `posted_at` and `telegram_message_id` are nullable.

**Table `runs`** (`:28-33`) — one row per scheduled run; feeds `/stats` and the weekly rollup:
```sql
CREATE TABLE IF NOT EXISTS runs (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    kind   TEXT NOT NULL,             -- 'collect' | 'weekly'
    ran_at TEXT NOT NULL,
    counts TEXT NOT NULL DEFAULT '{}' -- JSON
);
CREATE INDEX IF NOT EXISTS idx_runs_kind_ran ON runs(kind, ran_at);
```

**Table `bot_state`** (`:38-41`) — KV store:
```sql
CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```
Keys in use: **`tg_offset`** (Telegram `getUpdates` offset) and **`digest:{message_id}`**
(per-digest pagination JSON). No FK constraints exist (despite `PRAGMA foreign_keys=ON`).

### 7.2 `Repository` (`db/repository.py`)

Connection (`__init__`, `:46-53`): creates parent dir (unless `:memory:`), `sqlite3.connect`,
`row_factory = sqlite3.Row`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`. `close()`
(`:61-69`) runs `PRAGMA wal_checkpoint(TRUNCATE)` to fold the WAL back into the single committed
`data/jobs.db` before closing; it's also a context manager.

| Method | Signature | Purpose |
|---|---|---|
| `init_schema` | `() -> None` | Runs `schema.sql` via `executescript` |
| `close` | `() -> None` | WAL checkpoint + close |
| `existing_dedup_keys` | `(keys: list[str]) -> set[str]` | Subset already stored (chunked 500) |
| `insert_new_jobs` | `(jobs: list[Job]) -> list[Job]` | `INSERT OR IGNORE`; returns rows actually inserted (forces `status='new'`) |
| `get_job` | `(job_id: int) -> Job \| None` | Single job |
| `get_jobs` | `(ids: list[int]) -> list[Job]` | Batch, preserves caller order (chunked 500) |
| `list_ids_by_message_id` | `(message_id: int) -> list[int]` | Ordered `score DESC, id ASC` (pagination self-heal) |
| `set_status` | `(job_id, status) -> bool` | The single status write-path; stamps `last_status_at` |
| `set_message_id` | `(job_id, message_id) -> None` | Links job → digest message |
| `reset_seen_jobs` | `(keep=(SAVED, APPLIED)) -> dict` | `DELETE … WHERE status NOT IN keep` |
| `list_by_status` | `(status, limit=25) -> list[Job]` | `ORDER BY first_seen_at DESC` |
| `list_since` | `(since_iso, limit=100) -> list[Job]` | `score DESC, first_seen_at DESC` |
| `status_counts` | `(since_iso=None) -> dict` | `GROUP BY status` |
| `source_counts` | `(since_iso=None) -> dict` | `GROUP BY source` |
| `match_reasons_since` | `(since_iso) -> list[str]` | Flattened reasons (weekly keywords) |
| `record_run` | `(kind, counts=None) -> None` | `INSERT INTO runs` |
| `last_run_at` | `(kind) -> datetime \| None` | **Defined but only used by tests** |
| `get_state` / `set_state` | `(key[, default])` / `(key, value)` | `bot_state` read / UPSERT |

`set_state` is a true UPSERT (`ON CONFLICT(key) DO UPDATE`). `insert_new_jobs` forces
`JobStatus.NEW` on write regardless of the in-memory value.

### 7.3 Job-status lifecycle: `new → saved | ignored | opened | applied`

Default `new` on insert (forced at `repository.py:112,117`; column default `:17`). **The
single transition path is `set_status`**, called exactly once in production at
`handlers.py:103`, driven by `CALLBACK_STATUS` (`handlers.py:25-29`):

| Transition | Button `callback_data` | Mapping → call |
|---|---|---|
| `new → saved` | `save:{id}[:page]` | `set_status(id, SAVED)` |
| `new → ignored` | `ignore:{id}[:page]` | `set_status(id, IGNORED)` |
| `new → applied` | `applied:{id}[:page]` | `set_status(id, APPLIED)` |
| `new → opened` | **none** | **never called** |

**`opened` is a dead status** — declared in the enum, `STATUS_LABEL`/`STATUS_BADGE`, and the
`/stats` order, but `🔗 Open` is a pure URL button (no callback), so `set_status(…, OPENED)`
is never reached; the "opened" count is permanently 0.

`reset-seen-jobs` (`repository.py:169-191`): `DELETE FROM jobs WHERE status NOT IN
(SAVED, APPLIED)` — clears `new`/`ignored`/`opened` (their dedup keys become "unseen" so they
can resurface), **preserves** `saved`/`applied`, and leaves config, the `runs` table, and
`bot_state` untouched. Note a previously *ignored* job can be re-sent after a reset.

---

## 8. Telegram layer

### 8.1 `client.py` — Bot API wrapper
Single URL template `https://api.telegram.org/bot{token}/{method}` (`:15`); every call is an
HTTP `POST` with a JSON body via a persistent `requests.Session`. **Four Telegram methods**
(no `editMessageReplyMarkup` — keyboard changes re-send full text via `editMessageText`):

| Telegram method | Wrapper | Params |
|---|---|---|
| `sendMessage` | `send_message` (`:52`) | `chat_id, text, parse_mode="HTML", disable_web_page_preview`, optional `reply_markup` |
| `editMessageText` | `edit_message_text` (`:66`) | `chat_id, message_id, text, parse_mode="HTML"`, optional `reply_markup` |
| `answerCallbackQuery` | `answer_callback_query` (`:71`) | `callback_query_id, text` (errors swallowed at `:72-73`) |
| `getUpdates` | `get_updates` (`:83`) | `timeout, allowed_updates=["message","callback_query"]`, optional `offset` |

Token is a constructor arg (not read from env here). Error chokepoint `_call` (`:36-38`):
any `{"ok": false}` raises `TelegramError`. **No `raise_for_status`, no 409-specific branch,
`resp.json()` unconditional** (a non-JSON 5xx page → raw `JSONDecodeError`). Long-poll read
timeout adapts: `read_timeout = timeout if timeout==0 else timeout+10` (`:81-83`).

### 8.2 `formatting.py` — cards, keyboards, badges
`parse_mode="HTML"`; all dynamic text run through `html.escape` (button URLs passed raw).

**Single card** `format_job_card` (`:54-78`):
```
<b>{title}</b>
🏢 {company}  •  📍 {location} ({Remote|On-site/Hybrid})
🌐 {source}  •  🗓 {posted_at:%Y-%m-%d}

{summary}                       ← if present (truncated to summary_chars=280)
🔎 <i>Matched:</i> {reasons}    ← if match_reasons present
<i>{STATUS_LABEL[status]}</i>   ← if status ≠ NEW
```

**Digest compact card** `_compact_card` (`:139-145`) — ≤3 short lines per job with the
`🟢 Junior · 🏠 Remote` **fit badges** (`_fit_badges`, `:112-120`, derived from `junior:`
match-reason prefixes + `job.remote`, **not** the raw score — decision 2026-06-09).

**callback_data scheme:** `noop` | `page:{N}` | `{save|ignore|applied}:{job_id}` (single card) |
`{save|ignore|applied}:{job_id}:{page}` (digest). Digest keyboard (`digest_keyboard`, `:169-190`)
emits one 4-button action row **per job on the page** (`💾 🙈 / 🔗 Open / ✅`) plus a nav row:
`⬅️ Prev → page:{p-1}` (only if `p>1`), center `Page {p}/{total} → noop`, `Next ➡️ → page:{p+1}`
(only if `p<total`). **Prev/Next are omitted at the ends — no wraparound.** Once a job is
actioned, `job_keyboard` collapses to Open-only (`:88-89`).

### 8.3 `digest.py` — assembling/sending
`send_digest` (`:17-48`): empty run → send `"🔎 No new matching jobs this run."` and return 0.
Otherwise the **placeholder-first** trick (the message id is needed before rendering because
`callback_data` ties buttons to it):
```python
placeholder = client.send_message("🔎 Preparing your job digest…")
message_id = placeholder["message_id"]
save_digest(repo, message_id, job_ids, page_size)   # persist ordered id list
# render page 1, edit the placeholder in place (failure caught + warned)
for jid in job_ids: repo.set_message_id(jid, message_id)   # back-link for self-heal
```
The whole run is **exactly one Telegram message**.

### 8.4 `pagination.py` — the state machine
Per-message state is one `bot_state` row keyed **`digest:{message_id}`** (`:18`). The JSON
stores the **ordered `job_ids` + `page_size` + `created_at`** — but **deliberately NOT the
current page**, which rides in each button's `callback_data` (docstring `:5-7`). This is what
makes paging **stateless across cron runs**.

`page_slice` (`:39-45`) is 1-based and **hard-clamped, no wraparound**: `page = max(1, min(page,
total_pages))`; Prev past the start no-ops on page 1. `render_page` (`:48-95`) looks up state
and **self-heals** if the `digest:{id}` row vanished (dropped commit between runs) by rebuilding
the ordered id list from `repo.list_ids_by_message_id(message_id)` (which works because
`digest.py` back-linked each job). It returns `(text, keyboard)`; the actual `editMessageText`
is done by the caller `handlers._edit_digest_page` (`:55-64`).

### 8.5 `handlers.py` — buttons, commands, drain loop
`handle_callback` (`:67-118`) branches: `noop` → just answer; `page:N` → re-render + edit
(or answer `"Digest expired"` if `render_page` returns `None`); `action:job_id[:page]` →
validate, `repo.set_status`, answer `"Marked {status}"`, then re-render the page in place
(falling back to the single-card layout if no digest state).

**Commands** `handle_command` (`:163-183`), token normalized (strips `/`, `@botname`, case):

| Command | Reply |
|---|---|
| `/start`, `/help` | `HELP_TEXT` — model overview + action/command list |
| `/today` | `repo.list_since(24h, limit=max_jobs)` as a linked bullet list |
| `/saved` | `repo.list_by_status(SAVED)` |
| `/applied` | `repo.list_by_status(APPLIED)` |
| `/stats` | All-time + last-7-days status breakdown (`new·saved·ignored·opened·applied`) + top-5 sources (7d) |
| `/config` | Enabled sources, remote mode, titles/keywords allow, locations allow/deny, min match score |
| anything else | `"Unknown command. Try /help"` |

`process_updates` (`:199-217`): reads `tg_offset` from `bot_state`, `get_updates(offset, timeout)`,
handles each update (one bad update can't block the rest), and **persists `update_id+1` after
each** update. `watch_updates` (`:220-238`): infinite long-poll loop (`long_poll=25`),
`KeyboardInterrupt` breaks; any other exception (incl. the **409** from an overlapping `bot.yml`
cron — Telegram allows one `getUpdates` consumer) is warning-logged and retried after a 3s backoff.

---

## 9. Deployment

### 9.1 The four workflows

| Workflow | Schedule | Concurrency group | Steps | Secrets |
|---|---|---|---|---|
| `collect.yml` | `0 7 * * *`, `0 18 * * *` (07:00 & 18:00 UTC) + `workflow_dispatch` | `job-assistant-db`, `cancel-in-progress: false` | checkout → setup-python 3.11 → `pip install -e .` → `cli collect` → `commit-db.sh "chore(data): collect"` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `bot.yml` | `*/20 * * * *` (every 20 min) + dispatch | same group | … → `cli process-updates` → `commit-db.sh "chore(data): bot updates"` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `weekly.yml` | `0 8 * * 1` (Mon 08:00 UTC) + dispatch | same group | … → `cli weekly` → `commit-db.sh "chore(data): weekly summary"` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `ci.yml` | push to `main` (`paths-ignore: data/**`) + PRs | none | checkout → setup-python 3.11 → `pip install -e ".[dev]"` → `pytest` | none |

All three data-writers share **one** concurrency group so only one run touches `data/jobs.db`
at a time (queued, not cancelled). They declare `permissions: contents: write`; `ci.yml` is
read-only. The `paths-ignore: data/**` plus the `[skip ci]` commit tag prevent automated DB
commits from triggering CI loops.

### 9.2 `commit-db.sh` — committing state back
```bash
set -euo pipefail
MESSAGE="${1:-chore(data): update db}"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -f data/jobs.db
if git diff --cached --quiet; then echo "No database changes to commit."; exit 0; fi   # empty-commit guard
git commit -m "${MESSAGE} [skip ci]"                                                    # CI-loop guard
git pull --rebase --autostash origin "${GITHUB_REF_NAME}" || true                       # push-race rebase
git push origin "HEAD:${GITHUB_REF_NAME}"
```
`git add -f` forces past any `.gitignore`; the empty-commit guard avoids no-op commits; the
rebase-then-push handles the (rare, given serialization) push race. `.gitattributes` marks
`data/jobs.db` **binary** (no merge — concurrent writers clobber, not merge), which is why the
concurrency-group serialization matters.

### 9.3 Required secrets
- **`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`** — all three data workflows; read in `config.py:190-191`.
- **`IMAP_USERNAME`, `IMAP_PASSWORD`** — read in `config.py:192-193` for the LinkedIn source,
  but **injected by NO workflow** (latent foot-gun — §12). CI needs no secrets.

### 9.4 CLI surface (`cli.py`)
`init-db` · `collect [--dry-run]` · `process-updates [--watch] [--long-poll SECONDS=25]` ·
`weekly` · `reset-seen-jobs` · plus two **undocumented test helpers** `test-telegram` and
`test-job-card`. Subcommand required; dispatch via the `HANDLERS` table (`:189-197`).

---

## 10. Current config snapshot (`config/config.yaml`, verbatim)

> Reproduced exactly as on disk (214 lines). **I verified there are no secrets to redact:**
> `comeet.companies` is `[]`, the only `token:` is the `YOUR_TOKEN` placeholder inside a
> commented-out example, and no tokens / chat-ids / IMAP credentials appear (those live only
> in env / Actions secrets, never in this file).

```yaml
# Active preferences — tuned for a Graduate / Junior software job search in
# Israel (center-weighted), open to remote/hybrid/on-site, no relocation.
# Secrets live in environment variables / GitHub Actions secrets, not here.
# See config.example.yaml for full documentation of every field.

sources:
  remotive:
    enabled: true
    # NOTE: Remotive's public API returns one general feed; the category param
    # is effectively ignored, so listing more categories has no effect.
    categories: ["software-dev"]
    search: ""
    limit: 100

  weworkremotely:
    enabled: true
    feeds:
      - "remote-programming-jobs"
      - "remote-full-stack-programming-jobs"
      - "remote-back-end-programming-jobs"
      - "remote-front-end-programming-jobs"

  # Israeli tech companies with public Greenhouse boards (verified to return
  # jobs). Add/remove company slugs freely — a wrong/stale slug is skipped
  # safely. Slug = the token in https://boards.greenhouse.io/<slug>
  greenhouse:
    enabled: true
    boards:
      - "via"
      - "catonetworks"
      - "jfrog"
      - "payoneer"
      - "similarweb"
      - "taboola"
      - "fireblocks"
      - "forter"
      - "axonius"
      - "riskified"
      - "transmitsecurity"
      - "yotpo"
      - "augury"
      - "melio"
      - "orcasecurity"
      - "saltsecurity"
      - "lightricks"
      - "bigid"
      - "pagaya"
      - "bringg"
      - "cybereason"
      - "nice"
      - "appsflyer"

  # Israeli companies with public Lever boards. Slug = https://jobs.lever.co/<slug>
  lever:
    enabled: true
    boards:
      - "logz"

  # Comeet ATS (very common among Israeli companies). Public Careers API; opt-in.
  # Each company needs its uid + token (Comeet: Settings -> Careers Website ->
  # Careers API). Wrong/stale entries are skipped safely.
  comeet:
    enabled: false
    companies: []
      # - { name: "Example Co", uid: "30.005", token: "YOUR_TOKEN" }

  # LinkedIn via Job-Alert EMAIL ingestion (no scraping/login). Off by default.
  # To use: create Job Alerts on LinkedIn, set IMAP_USERNAME/IMAP_PASSWORD secrets
  # (e.g. a Gmail App Password), then set enabled: true. See README.
  linkedin:
    enabled: false
    imap_host: "imap.gmail.com"
    imap_folder: "INBOX"
    senders:
      - "jobalerts-noreply@linkedin.com"
      - "jobs-noreply@linkedin.com"
    max_age_days: 3
    mark_seen: false
    limit: 50

filters:
  # Broad set of junior-suitable software roles (matched in title/summary).
  # Profile is engineering-focused: pure analyst / data-scientist titles were
  # removed (Data Engineer + Machine Learning engineer roles still pass; the broad
  # "engineer"/"developer" terms cover AI/ML engineer titles too).
  titles_allow:
    ["engineer", "developer", "programmer", "software", "full stack", "fullstack",
     "full-stack", "front end", "frontend", "front-end", "back end", "backend",
     "back-end", "web", "mobile", "android", "ios", "qa", "automation", "test",
     "devops", "data engineer", "machine learning"]

  # Junior/grad terms + core entry-level tech. Drives the min_match_score gate.
  keywords_allow:
    ["junior", "graduate", "entry level", "entry-level", "new grad", "student",
     "python", "java", "javascript", "typescript", "react", "node", "c#", "sql",
     "html", "css"]

  # No topic exclusions for now (openness over a narrow filter).
  keywords_deny: []

  # Open to remote, hybrid, and on-site.
  remote: "any"

  # No hard geographic ALLOW filter: ALL Israeli locations (Tel Aviv, Haifa,
  # Jerusalem, Beer Sheva, the North, ...) AND remote jobs stay eligible. Center is
  # preferred via ranking (boost_keywords), not filtering. (An allow-list is
  # deliberately avoided — it would drop valid Israeli towns it forgot to list,
  # e.g. a job tagged just "TLV".)
  locations_allow: []

  # Removes roles abroad, since the search is Israel-wide + remote. Applies to
  # on-site roles, and to "remote" roles whose location pins them to a denied
  # region (region-restricted hiring) — a remote location containing anywhere/
  # worldwide/global/remote always stays. Israeli locations are never listed, so
  # they're never affected. Extend this list if foreign noise slips through.
  locations_deny:
    ["india", "bangalore", "bengaluru", "gurugram", "gurgaon", "hyderabad", "pune",
     "mumbai", "delhi", "noida", "china", "beijing", "shanghai", "guangzhou",
     "shenzhen", "hong kong", "japan", "tokyo", "singapore", "hungary", "budapest",
     "bulgaria", "sofia", "czech", "prague", "poland", "warsaw", "krakow", "romania",
     "bucharest", "ukraine", "kyiv", "kiev", "portugal", "lisbon", "porto", "spain",
     "madrid", "barcelona", "germany", "berlin", "munich", "france", "paris",
     "united kingdom", "london", "england", "manchester", "ireland", "dublin",
     "netherlands", "amsterdam", "united states", "usa", "new york",
     "san francisco", "austin", "boston", "seattle", "canada", "toronto",
     "vancouver", "brazil", "sao paulo", "mexico", "argentina", "buenos aires",
     "colombia", "bogota", "australia", "sydney", "melbourne", "philippines",
     "manila", "cebu", "uae", "dubai", "abu dhabi", "turkey", "istanbul",
     "egypt", "cairo", "vietnam", "thailand", "bangkok", "indonesia", "jakarta",
     "south africa"]

  # Do NOT hard-gate by title seniority — that would drop generic "Software
  # Engineer" roles that may well be junior. Ranking + seniority_deny handle it.
  seniority_allow: []

  # Drop clearly-not-junior titles (keeps the search realistic, including for AI
  # roles) without excluding whole topics.
  seniority_deny:
    ["senior", "sr.", "staff", "principal", "lead", "head of", "vice president",
     "director", "manager", "architect", "expert", "experienced", "5+ years",
     "6+ years", "7+ years", "8+ years", "9+ years", "10+ years",
     "research scientist", "phd", "fellow", " ii", " iii", " iv"]

  # Title-only exclusion of role TYPES that share a software word but aren't a
  # software-developer first job. NOTE: titles_allow includes the broad term
  # "engineer", so ANY "X Engineer" passes the gate — these deny terms remove the
  # non-software / non-junior "engineer" roles (electrical, mechanical, GxP/lab,
  # site-reliability/ops) plus sales/support/HR. Matched on the title only, so a
  # real dev role that merely mentions e.g. "the sales team" in its description
  # stays. (Management titles like "product/project manager" are already dropped by
  # seniority_deny.) Junior DevOps, QA Automation and junior AI/ML stay eligible.
  titles_deny:
    ["sales", "support engineer", "solutions engineer", "solution engineer",
     "presales", "pre-sales", "implementation", "customer engineer",
     "customer success", "account manager", "account executive", "recruit",
     "talent acquisition", "human resources", "marketing",
     "business development", "professional services", "field engineer",
     "helpdesk", "help desk", "service desk", "it support", "support specialist",
     "technical support",
     # Non-software engineering disciplines + pharma/lab.
     "electrical", "mechanical", "instrument", "instrumentation", "hardware",
     "civil", "chemical", "biomedical", "industrial", "manufacturing",
     "mechatronic", "aerospace", "automotive", "rf engineer", "optical",
     "process engineer", "gxp", "validation engineer",
     # Pure operations / SRE (Junior DevOps + QA Automation remain via titles_allow).
     "site reliability", "sre",
     # Non-engineering roles that slip in via summary keywords or "X Engineer":
     # analyst/business-analyst, research/data scientists, designers, pre-sales
     # "application engineer", founding (early-stage senior), and admin/community.
     "analyst", "scientist", "researcher", "research engineer", "designer",
     "application engineer", "founding", "office assistant", "administrative",
     "receptionist", "community", "website admin", "web admin",
     # IT-ops / advocacy roles observed in real collected data.
     "it specialist", "developer advocate", "noc engineer"]

  min_match_score: 1

  # Experience handling for a Graduate/Junior search. A role is acted on only if
  # it EXPLICITLY requires more than max_years_experience (e.g. "5+ years");
  # generic roles with no stated years are untouched.
  #   experience_mode: downrank (penalise but keep visible) | filter (exclude) | off
  # Set to "filter" for a no-experience first-job search: roles that explicitly
  # demand more than max_years_experience are removed (generic roles untouched).
  max_years_experience: 2
  experience_mode: "filter"
  experience_penalty: 8         # score penalty applied in downrank mode

  # LOCATION ranking only (does not gate). Each match (title + location) adds
  # boost_weight. Tiered so the digest sorts center Israel > rest of Israel >
  # remote/other — all remain eligible. "israel" lifts every Israeli role; center
  # cities give Tel Aviv / Gush Dan / Central District an extra edge.
  boost_keywords:
    ["israel",
     "tel aviv", "tel-aviv", "tel aviv-yafo", "tel aviv district", "gush dan",
     "ramat gan", "givatayim", "bnei brak", "holon", "bat yam", "herzliya",
     "petah tikva", "petach tikva", "ra'anana", "raanana", "kfar saba",
     "hod hasharon", "rosh haayin", "or yehuda", "rishon lezion", "rishon",
     "rehovot", "ness ziona", "nes ziona", "netanya", "central district", "merkaz"]
  boost_weight: 3

  # JUNIOR ranking (title only). A dedicated, heavier boost so explicit entry-level
  # roles sort to the very top — above same-tech non-junior roles, even Tel-Aviv
  # ones. Weight > (israel + one center city) so a remote junior role still wins.
  junior_boost_keywords:
    ["junior", "graduate", "entry level", "entry-level", "new grad", "new-grad",
     "student", "intern", "trainee", "associate"]
  junior_boost_weight: 8

digest:
  max_jobs: 25
  summary_chars: 280
  timezone: "Asia/Jerusalem"
  page_size: 1                # jobs per page (1 = one card at a time, Prev/Next to browse)
```

---

## 11. Current state & health

### 11.1 Tests — live run (2026-06-30)
`.\.venv\Scripts\python.exe -m pytest -v` → **`123 passed in 3.97s`**, 0 failed, 0 errors,
0 skipped, 0 xfail, **0 warnings**. Environment: Python **3.13.5**, pytest 9.0.3 (note: CI
pins Python **3.11** — local dev is on 3.13; both satisfy `requires-python >=3.11`). This
matches the `docs/PROJECT_STATE.md` claim of 123 passing.

Per-file counts: `test_filters` 25, `test_experience` 16, `test_formatting` 15, `test_repository`
14, `test_handlers` 11, `test_cli` 8, `test_config` 8, `test_pagination` 8, `test_sources` 5,
`test_comeet` 4, `test_linkedin` 4, `test_pipeline` 3, `test_weekly` 2. Fixtures (`conftest.py`):
an in-memory `repo`, a no-network `FakeTelegramClient` double, and a `make_job(**overrides)`
factory. Source tests call `parse()` directly on saved fixtures (`tests/fixtures/*`), bypassing
the network entirely.

### 11.2 Working vs partial vs stubbed
- **Fully working:** the 4 enabled sources' parsing, the filter/score/experience engine, dedup,
  the SQLite layer, the paginated digest + pagination state machine, all commands, the weekly
  summary, and all four workflows.
- **Partial:** LinkedIn-email parsing is best-effort by design (title + link guaranteed, the
  rest may be missing); Comeet is code-complete but `enabled: false` with zero companies.
- **Dead / unreachable (not stubs, but inert):** the `OPENED` status (never written),
  `Repository.last_run_at` (only tests call it; the schema's "gates once per day/week" comment
  is aspirational — real scheduling is the cron), and the `ACTIONABLE_STATUSES` constant
  (declared, referenced nowhere).
- **Nothing is a literal stub** — the only `raise NotImplementedError` is the `Source.collect`
  ABC contract (`base.py:40`), and the only "placeholder" is the digest's intentional
  message-id-priming send (`digest.py:33`).

### 11.3 TODO/FIXME/XXX
**Zero.** A full grep of `src/` and `tests/` for `TODO|FIXME|XXX|HACK` returns only false
positives (a `placeholders` SQL variable, the digest "placeholder" message, the ABC
`NotImplementedError`). The code is comment-rich but carries no flagged debt. All six analysis
passes independently confirmed this.

### 11.4 Recent commit themes
26 commits, all 2026-06-03 → 2026-06-12 (built in ~9 days):
- **2026-06-03:** initial setup + implementation; `reset-seen-jobs`; "Prioritize Israel by
  ranking, not hard geographic filtering"; YAML workflow fix.
- **2026-06-04:** "Add paginated 1/page digest, experience detection, LinkedIn & Comeet sources"
  (the big feature commit).
- **2026-06-09:** "Harden Telegram pagination and tighten junior/Israel job filtering"; watch
  mode; junior-boost tier; expanded `titles_deny`; digest fit badges.
- **2026-06-12:** region-locked foreign "remote" roles excluded; more noise titles denied;
  `/config` reports all six sources; **docs added** (PROJECT_STATE / DECISIONS / CHANGELOG).
- Interleaved automated `chore(data): collect|bot updates|weekly summary [skip ci]` commits
  from the Actions crons (these are the DB being committed back).

### 11.5 Operational health observation
The **last automated `chore(data)` commit is `789fab8` on 2026-06-09**. PROJECT_STATE (dated
2026-06-12) says the crons are "live" with DB `runs 1–17`, yet there is **no automated
collection/bot/weekly commit in the ~21 days since** (today is 2026-06-30) — only the manual
feature/docs commits on 06-12. This *may* mean the Actions schedules were paused/disabled after
06-09, the repo ran out of private-repo Actions minutes, or development simply paused without
the crons running. It cannot be determined from the code alone (see §13). Also: `data/jobs.db`
reportedly holds **261 jobs all still `status='new'`** — i.e. the Save/Ignore/Applied buttons
have working tests but **no real production use yet**.

---

## 12. Gaps, risks & limitations

### 12.1 🔴 Substring false-positive silently drops **on-site Jerusalem** jobs (real bug)
`locations_deny` contains `"usa"` (for "United States"), and `_contains_any` does
case-insensitive **substring** matching — `"usa"` is literally inside `"jer`**`usa`**`lem"`.
For an on-site Jerusalem posting (`remote=False`), the geo-deny at `filters.py:78-80` matches
and returns `None`. A remote Jerusalem role survives **only** if its location text literally
contains a global marker (`anywhere/worldwide/global/remote`); a remote job flagged
`remote=True` whose location is just `"Jerusalem"` is **also dropped**. This directly
contradicts the config's own claim that "Israeli locations are never listed, so they're never
affected" (`config.yaml:114-115`), and it removes a major Israeli tech hub from the user's
results. *Quick proof:* `"usa" in "jerusalem"` → `True`. **Highest-impact finding for this
user profile.**

### 12.2 🟠 Per-entry error isolation is missing in 4 of 6 sources
Only Comeet wraps each entry (company) in its own `try/except` (`comeet.py:77-84`).
Greenhouse, Lever, We Work Remotely and Remotive loop their boards/feeds/categories with **no
inner `try/except`**, so a single stale slug whose `raise_for_status()` 404s propagates out of
`_fetch_and_parse`, gets caught by `_safe_collect`, and **drops the entire source's results**
(one bad slug → all 23 Greenhouse boards lost for that run). This contradicts the config
comments promising "a wrong/stale slug is skipped safely" (`config.yaml:24-25,60-61`). And
because **`collect_all` is monkeypatched out in every test** and there is **no `test_base.py`**,
neither the per-entry behavior nor the `_safe_collect` "never raises" contract is exercised
by the suite (§12.7).

### 12.3 🟠 Substring matching produces other false hits
`_contains_any` is substring-based, not token-aware, so beyond Jerusalem: `"java" ⊂
"javascript"`, `"sql" ⊂ "mysql/nosql/postgresql"`, `"node" ⊂ "node.js"` (double-counted toward
`keyword_hits`); `"ios" ⊂ "kiosk"`, `"test" ⊂ "latest/testing"`, `"web" ⊂ "website"` (inflate
the uncapped `title_hits`); `" iv" ⊂ " Ivan…"`, `"lead" ⊂ "leading"` (possible title
false-drops). These mostly affect *ranking*, not gating — except Jerusalem, which gates.

### 12.4 🟠 Experience filter can't distinguish required vs. preferred
Under the active `experience_mode: "filter"`, a junior-friendly JD that says "3 years
experience **preferred**" yields `required_years=3 > 2` and is **removed** — a coverage loss
consistent with the user's stated "hard exclusion over downranking" preference, but worth
knowing. Edge cases: `_PATTERNS[0]`'s `\D{0,12}` can bridge unrelated text ("required: BSc.
5 years"); `_PATTERNS[1]`'s context word `"working"` filters "3 years working remotely".

### 12.5 🟡 Cross-source duplication is never merged
`source` is part of the `dedup_key` basis in **both** branches (`models.py:40-42`), so the same
posting appearing on two different sources (e.g. a role on both Greenhouse and a LinkedIn alert)
yields two distinct keys → two cards. Dedup only collapses identical `source`+`external_id`
(or identical normalized title/company/url within one source). Also, when `external_id` is
empty the fallback hashes the **raw URL** — a source emitting volatile tracking/query params
would re-surface the same job as "new" across runs.

### 12.6 🟡 Telegram robustness edges
- **`OPENED` status is dead** (§7.3/§8): the `/stats` "opened" count is permanently 0.
- **No 409-specific handling** in `client.py`: a 409 is a generic `TelegramError`, only
  absorbed by `watch_updates`' broad `except`. In plain cron mode (`process-updates` without
  `--watch`) a 409 from `get_updates` propagates with no catch at the `process_updates` level —
  the "harmless 409 and skips" narrative is only guaranteed under `--watch`.
- **`resp.json()` is unconditional** (`client.py:35`): a non-JSON 5xx/HTML gateway response
  raises a raw `JSONDecodeError`, not `TelegramError`. No `raise_for_status`, no retry/backoff
  in the client itself.
- **`callback_data` 64-byte limit is unguarded**: `applied:{id}:{page}` is safe for normal
  integer ids but nothing enforces the cap.
- **Expired callback queries**: in cron mode (≤20 min latency) the toast answer is routinely
  lost ("query is too old", swallowed at `client.py:72-73`), though the status mutation still
  persists.

### 12.7 🟡 Deployment & config foot-guns
- **IMAP secrets never wired into CI**: `config.py` reads `IMAP_USERNAME`/`IMAP_PASSWORD`, but
  no workflow injects them. If a user flips `linkedin.enabled: true` expecting cron coverage,
  it silently no-ops (creds blank → `is_imap_configured` false). Needs adding to `collect.yml`'s
  `env:` block.
- **Silent-failure mode**: `collect`/`weekly`/`process-updates` degrade quietly (skip send /
  return 0) when Telegram secrets are absent, so a misconfigured cron run shows **green in
  Actions while sending nothing**. (By contrast `test-telegram`/`test-job-card` return exit 1.)
- **No schema migration framework**: `init_schema` only runs `IF NOT EXISTS` DDL against the
  committed binary DB — it adds missing tables/indexes but never `ALTER`s existing columns. Any
  future column/constraint change needs a hand-written migration. There's no schema-version
  table.
- **No `CHECK` on `status`**: integrity relies on app code; an out-of-enum string ever written
  would crash `_row_to_job`'s `JobStatus(row["status"])` on read.
- **Unpinned deps, no pip cache**: every workflow run reinstalls `-e .` from source unpinned.
- **Privacy**: `data/jobs.db` is committed; making the repo public exposes the full job history.
- **Test coverage gaps**: no `test_base.py` (the `_safe_collect` contract), no `test_client.py`
  (the real `requests` wrapper — `_call` error path, long-poll math), `test_registry.py` only
  partial (remotive/WWR/greenhouse/lever gating untested), and the real network fetch layer of
  every source is bypassed by fixtures.

### 12.8 🟡 Coverage for an Israeli junior dev specifically
The search leans heavily on **global remote boards** (Remotive, WWR — both always `remote=True`)
plus a curated set of **23 Greenhouse + 1 Lever** Israeli-company boards. Notable coverage gaps
for the IL junior market:
- **No Israeli-market job boards.** The big Hebrew/IL boards — **AllJobs, Drushim, JobMaster,
  Comeet-hosted career sites, GotFriends, and university/army-program pipelines** — are not
  sourced. Comeet (the most common IL ATS) is implemented but **off with zero companies**.
- **LinkedIn is off**, removing the single richest junior-role feed (it requires IMAP setup).
- The **Jerusalem bug (§12.1)** actively suppresses one of Israel's two largest tech cities.
- Only **one Lever board** (`logz`) — many IL companies use Lever; the list is thin.
- Greenhouse `company` shows the lowercase **slug** (e.g. `catonetworks`) rather than a display
  name, which reads oddly on the card.

Net: the pipeline is sound, but **raw IL junior-role volume is constrained by which sources are
on**. Enabling Comeet (with real company uid/token pairs) and LinkedIn, fixing the Jerusalem
deny term, and expanding the Lever/Greenhouse lists would have far more impact on "good-fit
jobs received" than any core-code change.

---

## 13. Open questions (need user input — not determinable from code)

1. **Is the Actions cron still running?** The last automated `chore(data)` commit was
   2026-06-09 (§11.5). Were the schedules paused/disabled, did the repo exhaust private-repo
   Actions minutes, or has the bot simply not been pushed since? This determines whether the
   system is currently *live* or *dormant*.
2. **Is the Jerusalem (`"usa"`) drop acceptable, and shall I treat the fix as in-scope later?**
   (This report is read-only; the fix — e.g. word-boundary matching or removing/redefining the
   `"usa"` term — is noted but not applied.)
3. **Should Comeet and/or LinkedIn be enabled?** Comeet needs real company `uid`/`token` pairs;
   LinkedIn needs `IMAP_USERNAME`/`IMAP_PASSWORD` secrets added to `collect.yml`. Both are the
   highest-leverage way to increase IL junior-role volume.
4. **Are IL-specific boards (AllJobs / Drushim / JobMaster / more Lever-Greenhouse-Comeet
   companies) wanted?** Adding them is the main lever for coverage, but each needs a source
   module or company list.
5. **Has the digest actually been used in production?** PROJECT_STATE says all 261 stored jobs
   are still `new` — have Save/Ignore/Applied ever been pressed against a real Telegram chat,
   or only in tests?
6. **Intended `experience_mode`?** Live config is `"filter"` (hard-exclude) while the pydantic
   default and example docs lean `"downrank"`. Confirm "filter" is the desired strictness given
   the preferred-vs-required edge (§12.4).
7. **Python version target?** CI pins 3.11; local dev runs 3.13.5. Any intent to standardize?

---

*End of report. Read-only analysis — no source files were modified.*
