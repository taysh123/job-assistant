# Job Assistant Build-Out — Phased Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each wave task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Take the working v1 job-assistant from "~5 leads/week + noise" to a reliable, always-on, IL-junior-focused funnel that finds, ranks, and presents (never auto-applies) good-fit roles for a CS grad targeting junior software jobs in central Israel + real full-remote, in Hebrew and English.

**Architecture:** Keep the existing `sources → filtering → dedup → db → telegram` pipeline. Add correctness fixes (Wave 0), widen the funnel with IL-market sources + Hebrew matching (Wave A), move runtime off GitHub-cron onto a single always-on process (Wave B), add a cheap capped AI fit/draft layer (Wave C), and polish the Telegram UX (Wave D).

**Tech Stack:** Python 3.11+ (CI pins 3.11; dev on 3.13), pydantic v2, requests, feedparser, SQLite, Telegram Bot API, pytest. Wave C adds the Anthropic SDK (Claude Haiku). Wave B adds Docker.

## Global Constraints (apply to EVERY task)

- **No scraping behind logins/captchas.** Official/public APIs and RSS only. A task that would need to scrape a no-API site is raised as a DECISION, not done.
- **Never auto-apply.** The bot finds/ranks/presents; the human applies. (`docs/project-vision.md`, `docs/CLAUDE.md`.)
- **No AI in Waves 0/A/B.** AI is Wave C only, fully feature-flagged and **zero-cost when disabled**.
- **TDD always.** Each change = a failing test first, then minimal code to pass. **The full suite stays green (currently 123 passing).**
- **One branch + one PR per wave.** Never commit to `main`. After each PR: STOP, summarize, WAIT for go-ahead.
- **Intellectual honesty.** Verify external claims (e.g. "does Adzuna cover Israel?") before committing to them; show before/after evidence for filter changes; flag uncertainty.
- **Minimal changes; no gold-plating.** YAGNI/DRY.

---

## Execution model (honoring the working agreement)

Each wave is delivered as its own branch + PR off the latest `main`:

```
git checkout main; git pull
git checkout -b wave-0-correctness
# ... TDD tasks, frequent commits ...
git push -u origin wave-0-correctness
gh pr create --base main --title "Wave 0 — correctness + noise" --body "<summary, tests, secrets>"
# STOP → summarize → WAIT for go-ahead → only then start Wave A
```

Within a wave, independent tasks may be executed by parallel subagents (e.g. per-source edits in Wave 0 FIX B, source-research in Wave A). Pre-flight for Wave 0: confirm `gh auth status` is logged in; if not, I push the branch and you open the PR (DECISION D0).

---

## OPEN DECISIONS REGISTER (please answer before/at each wave)

| # | Wave | Decision | My recommendation |
|---|------|----------|-------------------|
| **D0** | 0 | Is `gh` authenticated for PR creation, or should I push the branch and you open the PR? | Confirm `gh auth status`; else push + you open |
| **D1** | 0 | Config flag name for empty-run silence: `digest.notify_empty: false`? | Yes — `notify_empty: false` (silent by default) |
| **D2** | A | **AllJobs / Drushim** have no public API → would require scraping (their ToS + our no-scraping principle). | **DO NOT scrape.** Use Comeet/Greenhouse/Lever/LinkedIn-email/aggregator-APIs instead |
| **D3** | A | `experience_mode`: switch `"filter"` → `"downrank"` so senior roles sink but stay visible (more leads)? | **Lean yes**, but only after I show before/after counts on the stored jobs |
| **D4** | A | Which aggregator APIs to add, IF they verify Israel coverage: Adzuna, Jobicy, Arbeitnow, RemoteOK? | Add only the ones that pass a live Israel/remote-coverage check; report results first |
| **D5** | A | Comeet starter company list — you supply real `uid`/`token` pairs. | You provide; I wire + test |
| **D6** | A | Enable the existing LinkedIn Job-Alert **email** source (compliant path)? Needs Gmail IMAP creds. | Optional; enable if you want LinkedIn volume |
| **D7** | B | Always-on host + Docker target (you provision with your advisor). Runtime DB stops being git-committed. | I make it cleanly deployable + documented; you host |
| **D8** | B | Keep GitHub cron workflows as disabled fallback, or delete? | Keep as **disabled** fallback; CI workflow stays |
| **D9** | C | Anthropic API key + **hard monthly USD cap** value. Model for drafting (Haiku vs Sonnet)? | You supply key + cap; Haiku for ranking, drafting model is a sub-decision |
| **D10** | C | Provide his **CV/profile text** for fit-scoring + cover-letter drafting. | You provide; stored locally, never committed |

## SECRETS / KEYS YOU MUST PROVIDE (per wave)

- **Wave 0:** none.
- **Wave A:** Comeet `uid`/`token` pairs (D5); *optional* aggregator API keys (e.g. `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) (D4); *optional* `IMAP_USERNAME`/`IMAP_PASSWORD` Gmail App Password for LinkedIn email (D6).
- **Wave B:** an always-on host + persistent volume; the existing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set as host env (D7).
- **Wave C:** `ANTHROPIC_API_KEY` + a monthly USD cap number (D9); his CV/profile text (D10).
- **Wave D:** none.

---

# WAVE 0 — Correctness + noise (one PR: `wave-0-correctness`)

Small, safe, highest ROI. Three independent fixes. No new dependencies, no secrets.

## Task 0.1 — FIX A: geo-deny matches whole words, not fragments

**Problem:** `filters.py:78` uses `_contains_any(job.location, cfg.locations_deny)` (substring), so `"usa"` ∈ `locations_deny` matches `"jer`**`usa`**`lem"` and silently drops on-site Jerusalem roles.

**Files:**
- Modify: `src/job_assistant/filtering/filters.py` (add `import re`; add `_location_denied` helper; use it at the geo-deny check ~line 78)
- Test: `tests/test_filters.py`

**Interfaces:**
- Produces: `_location_denied(location: str, needles: list[str]) -> list[str]` — whole-word/phrase location-deny matcher; returns matched terms in config order.

- [ ] **Step 1 — failing tests** (append to `tests/test_filters.py`):

```python
from job_assistant.config import load_config
from job_assistant.filtering.filters import FilterEngine

def _il_engine() -> FilterEngine:
    # Uses the real shipped profile (locations_deny has "usa","new york"; boost has "ramat gan")
    return FilterEngine(load_config("config/config.yaml").filters)

def test_onsite_jerusalem_passes_geo_deny():
    job = make_job(title="Junior Software Engineer", location="Jerusalem, Israel",
                   remote=False, summary="junior backend role, python")
    assert _il_engine().evaluate(job) is not None

def test_onsite_new_york_usa_denied():
    job = make_job(title="Junior Software Engineer", location="New York, USA",
                   remote=False, summary="junior backend role, python")
    assert _il_engine().evaluate(job) is None

def test_onsite_ramat_gan_passes():
    job = make_job(title="Junior Software Engineer", location="Ramat Gan, Israel",
                   remote=False, summary="junior backend role, python")
    assert _il_engine().evaluate(job) is not None

def test_remote_global_with_denied_country_passes():
    job = make_job(title="Junior Software Engineer", location="Remote — Anywhere (India team)",
                   remote=True, summary="junior backend role, python")
    assert _il_engine().evaluate(job) is not None

def test_remote_region_locked_still_denied():
    job = make_job(title="Junior Software Engineer", location="Bangalore, India",
                   remote=True, summary="junior backend role, python")
    assert _il_engine().evaluate(job) is None
```

- [ ] **Step 2 — run, verify FAIL:** `pytest tests/test_filters.py::test_onsite_jerusalem_passes_geo_deny -v` → FAIL (currently denied).

- [ ] **Step 3 — implement.** In `filters.py` add `import re` (top) and the helper near `_contains_any`:

```python
def _location_denied(location: str, needles: list[str]) -> list[str]:
    """Whole-word location-deny match.

    Unlike _contains_any (substring), a term only matches as a standalone token,
    so "usa" does NOT match "Jerusalem". Multi-word terms ("new york") match as
    phrases. Boundaries use non-alphanumeric so commas/spaces delimit tokens and
    Hebrew text (added in Wave A) keeps working.
    """
    low = location.lower()
    hits: list[str] = []
    for n in needles:
        if not n:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", low):
            hits.append(n)
    return hits
```

Then change the geo-deny check (was `if _contains_any(job.location, cfg.locations_deny):`):

```python
        if _location_denied(job.location, cfg.locations_deny):
            if not job.remote or not _location_is_global(job.location):
                return None
```

- [ ] **Step 4 — run, verify PASS:** `pytest tests/test_filters.py -v` → all green.
- [ ] **Step 5 — commit:** `git commit -m "fix(filters): geo-deny matches whole words so on-site Jerusalem isn't dropped"`

## Task 0.2 — FIX B: per-source error isolation + close the test gap

**Problem:** `greenhouse/lever/weworkremotely/remotive` loop their boards/feeds/categories with no inner `try/except`, so one stale slug's 404 drops the whole source. Only `comeet` isolates per-entry. Also no `test_base.py` and `collect_all` is mocked everywhere, so this path is untested.

**Files:**
- Modify: `src/job_assistant/sources/greenhouse.py`, `lever.py`, `weworkremotely.py`, `remotive.py` (wrap each loop iteration in `try/except` → log + continue; add a module `logger` where missing)
- Create: `tests/test_base.py` (the `_safe_collect` contract)
- Create: `tests/test_source_isolation.py` (per-source skip-failing-entry)

**Interfaces:**
- Consumes: `Source._safe_collect`, `Source._get` (existing, `base.py:44-56`).
- Produces: each source's `_fetch_and_parse` continues past a failing entry.

- [ ] **Step 1 — failing tests.** Create `tests/test_base.py`:

```python
from job_assistant.sources.base import Source

class _OkSource(Source):
    name = "ok"
    def collect(self): return self._safe_collect(lambda: [1, 2, 3])

class _BadSource(Source):
    name = "bad"
    def collect(self): return self._safe_collect(self._boom)
    def _boom(self): raise RuntimeError("nope")

def test_safe_collect_returns_results_on_success():
    assert _OkSource().collect() == [1, 2, 3]

def test_safe_collect_swallows_exceptions():
    assert _BadSource().collect() == []
```

Create `tests/test_source_isolation.py` (Greenhouse is the worked example; Lever/WWR/Remotive get an analogous test each):

```python
import requests
from job_assistant.config import GreenhouseConfig
from job_assistant.sources.greenhouse import GreenhouseSource

class _FakeResp:
    def __init__(self, payload): self._payload = payload
    def json(self): return self._payload

def test_greenhouse_skips_failing_board(monkeypatch):
    src = GreenhouseSource(GreenhouseConfig(enabled=True, boards=["bad", "good"]))
    def fake_get(url, **kwargs):
        if "bad" in url:
            raise requests.HTTPError("404 Not Found")
        return _FakeResp({"jobs": [{"id": 1, "title": "Backend Engineer",
                                    "absolute_url": "https://x/1",
                                    "location": {"name": "Tel Aviv"}}]})
    monkeypatch.setattr(src, "_get", fake_get)
    jobs = src.collect()
    assert [j.title for j in jobs] == ["Backend Engineer"]   # good board survives
```

- [ ] **Step 2 — run, verify FAIL:** `pytest tests/test_source_isolation.py -v` → FAIL (the `bad` board's exception currently propagates and `_safe_collect` returns `[]`, so `jobs == []`).

- [ ] **Step 3 — implement** (Greenhouse shown; apply the identical wrap to `lever.py` [`board`], `weworkremotely.py` [`feed`/`slug`], `remotive.py` [`category`]). In `greenhouse.py` add at top: `import logging` and `logger = logging.getLogger(__name__)`, then:

```python
    def _fetch_and_parse(self) -> list[Job]:
        jobs: list[Job] = []
        for board in self.config.boards:
            try:
                payload = self._get(
                    API_URL.format(board=board), params={"content": "true"}
                ).json()
                jobs.extend(parse(payload, board=board))
            except Exception as exc:  # noqa: BLE001 - one bad board mustn't drop the source
                logger.warning("greenhouse board %s failed: %s", board, exc)
        return jobs
```

- [ ] **Step 4 — run, verify PASS:** `pytest tests/test_base.py tests/test_source_isolation.py -v` → green; then full `pytest`.
- [ ] **Step 5 — commit:** `git commit -m "fix(sources): isolate per-board/feed failures + test _safe_collect contract"`

## Task 0.3 — FIX C: empty runs are silent by default

**Problem:** an empty run sends a "No new matching jobs this run" message, flooding the chat. (`pipeline.py:55-58` → `send_digest(client, repo, [])`.)

**Files:**
- Modify: `src/job_assistant/config.py` (`DigestConfig`: add `notify_empty: bool = False`)
- Modify: `src/job_assistant/pipeline.py` (gate the empty-send on `config.digest.notify_empty`)
- Modify: `config/config.yaml` + `config/config.example.yaml` (document the flag under `digest:`)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1 — failing tests** (append to `tests/test_pipeline.py`):

```python
from job_assistant import pipeline
from job_assistant.config import Config, DigestConfig
from job_assistant.config import Secrets

def _run_empty(repo, monkeypatch, notify_empty):
    monkeypatch.setattr(pipeline, "collect_all", lambda *a, **k: [])  # no jobs
    calls = []
    monkeypatch.setattr(pipeline, "send_digest", lambda *a, **k: calls.append(a) or 0)
    cfg = Config(digest=DigestConfig(notify_empty=notify_empty))
    secrets = Secrets(telegram_bot_token="t", telegram_chat_id="c")
    pipeline.run_collection(cfg, secrets, repo)
    return calls

def test_empty_run_silent_by_default(repo, monkeypatch):
    calls = _run_empty(repo, monkeypatch, notify_empty=False)
    assert calls == []                               # nothing sent
    assert repo.last_run_at("collect") is not None   # but the run IS recorded

def test_empty_run_notifies_when_enabled(repo, monkeypatch):
    calls = _run_empty(repo, monkeypatch, notify_empty=True)
    assert len(calls) == 1                            # the empty digest is sent
```

- [ ] **Step 2 — run, verify FAIL:** `pytest tests/test_pipeline.py::test_empty_run_silent_by_default -v` → FAIL (currently sends).

- [ ] **Step 3 — implement.** `config.py` `DigestConfig`:

```python
    page_size: int = 1
    # When a run finds no new jobs, stay silent (no "no new jobs" message). The
    # run is still recorded in the runs table. Set true to be pinged every run.
    notify_empty: bool = False
```

`pipeline.py` empty branch:

```python
    elif send and not inserted:
        if secrets.is_configured and config.digest.notify_empty:
            client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
            send_digest(client, repo, [])
```

Add `notify_empty: false` under `digest:` in both YAML files with a one-line comment.

- [ ] **Step 4 — run, verify PASS:** `pytest -q` → 123 + 9 new tests green.
- [ ] **Step 5 — commit:** `git commit -m "feat(digest): silence empty runs by default (digest.notify_empty)"`

## Wave 0 PR

- [ ] Push `wave-0-correctness`; `gh pr create` with summary (3 fixes, ~9 new tests, no secrets). **STOP, summarize, WAIT.**

---

# WAVE A — Fill the funnel (IL market + Hebrew + volume)

The wave that actually gets him hired. Delivered as `wave-a-funnel`. Detailed bite-sized TDD steps are finalized at wave start (several tasks depend on your inputs D3–D6 and live verification). Task-level plan:

## Task A.1 — Hebrew matching in the filter engine
- Add Hebrew vocabulary to allow/boost/deny: roles (`מתכנת/ת`, `מהנדס/ת תוכנה`, `פיתוח`, `בקאנד`, `פרונטאנד`, `פולסטאק`), junior signals (`ג'וניור`, `סטודנט/ית`, `מתמחה`, `התמחות`, `הנדסאי`), and Israeli city names (`תל אביב`, `רמת גן`, `פתח תקווה`, `הרצליה`, `רעננה`, `ירושלים`, `חיפה`, `באר שבע`).
- Handle Hebrew specifics in a normalization helper: no letter case; strip common attached prefixes (ה/ל/מ/ב/ו/ש/כ) when matching; tolerate gender suffixes (`/ת`, `ית`). Keep matching deterministic.
- Add Hebrew test fixtures (a real-shape Hebrew posting) + unit tests: a Hebrew junior dev post matches and ranks up; a Hebrew senior/QA-manager post is handled per existing deny rules.
- **No scraping** — this is pure matching logic over text sources already ingested.

## Task A.2 — Enable + seed Comeet (IL ATS, public API) — depends on **D5**
- Flip `comeet.enabled: true`; add the starter company list from the `uid`/`token` pairs you supply; wire secrets handling (tokens are config-borne today — confirm whether to move them to env). Add registry + parse tests (Comeet parse is already tested) and a seed-list smoke test.

## Task A.3 — Expand Greenhouse + Lever Israeli company lists (primary volume win)
- Research-only subagents compile candidate Israeli employers known to use Greenhouse/Lever; **verify each board returns jobs** (live check) before adding the slug. Add verified slugs to `config.yaml`; per-source isolation (Wave 0 FIX B) makes a stale slug harmless. Report the added/with-counts list.

## Task A.4 — Evaluate aggregator/remote APIs — depends on **D4** (+ keys)
- For each candidate (Adzuna, Jobicy, Arbeitnow, RemoteOK): **verify Israel/remote coverage with a live query first**; only then write a source module (fetch/parse split + registry entry + offline fixture tests), mirroring the existing source pattern. Report coverage findings; do not add a source that doesn't actually return relevant IL/remote roles.

## Task A.5 — LinkedIn Job-Alert email path — depends on **D6** (+ IMAP creds)
- Document + optionally enable the existing `linkedin` email source (the compliant LinkedIn path: parse Job-Alert emails over IMAP — no scraping). Add IMAP secrets to the runtime env (Wave B host, or Actions). Parsing is already tested; add a Hebrew-alert fixture if relevant.

## Task A.6 — Filter tuning for more leads — depends on **D3**, evidence-first
- Build an **offline replay** (no network, writes nothing): load every row from `data/jobs.db`, run the current vs proposed `FiltersConfig` (`experience_mode` filter→downrank, allow-list/`min_match_score` review), and **report before/after kept-counts** and which jobs change. Only apply changes you approve. Add tests for any new behavior.

## Task A.7 — Funnel diagnostics (`/diag` or enriched `/stats`)
- From the `runs` table `counts` JSON (`collected→matched→new→sent`) add a per-run, per-source funnel view so we can see where leads are lost. TDD with a seeded `runs`/`jobs` fixture.

## Wave A PR
- `wave-a-funnel`. **STOP, summarize (incl. replay evidence + source-coverage findings + any secrets needed), WAIT.**

---

# WAVE B — "Always on" (laptop-independent, instant 24/7)

Delivered as `wave-b-always-on`. Depends on **D7/D8**.

## Task B.1 — Single `serve` entrypoint
- Add `cli serve`: one long-running process that runs the Telegram watcher (instant Prev/Next, the single `getUpdates` consumer) **and** an internal scheduler (collect at the configured times + weekly) against **one** local SQLite as the single source of truth — no git-committed DB at runtime. TDD the scheduler tick logic (injectable clock; no real sleeps in tests). Keep all existing one-shot CLI commands working.

## Task B.2 — Dockerfile + DEPLOY.md
- Minimal Dockerfile (python:3.11-slim, `pip install -e .`, `CMD ["python","-m","job_assistant.cli","serve"]`), a persistent volume for the SQLite file, and `DEPLOY.md` for a small always-on host (env vars, volume, restart policy, how to back up the DB).

## Task B.3 — Move GitHub Actions to CI-only
- Keep `ci.yml`; make `collect.yml`/`bot.yml`/`weekly.yml` **disabled** fallbacks (documented), since the host now owns runtime. Update README + DEPLOY.md on the switch and the single-consumer rule (no overlap with the host's watcher).

## Wave B PR
- `wave-b-always-on`. **STOP, summarize (deploy steps + what you must provision), WAIT.**

---

# WAVE C — AI layer (cheap, capped, fail-closed)

Delivered as `wave-c-ai`. Depends on **D9/D10**. Mirrors the "T Poker AI Coach" discipline: hard monthly cap, fail-closed, rate-limited. Fully feature-flagged; **zero cost and identical behavior when disabled**. Wave-start step: consult the `claude-api` reference for the exact model id, pricing, and prompt-caching before writing calls (no guessing from memory).

## Task C.1 — Capped Anthropic client wrapper
- A small client with: a hard **monthly USD/token cap** (persisted in `bot_state`), per-call + per-minute rate limiting, **fail-closed** (any error or cap-hit → fall back to the deterministic ranking, never crash a run), and a feature flag (`ai.enabled`, default false). TDD the cap/fail-closed logic with a fake client (no network in tests).

## Task C.2 — AI fit-ranking
- For each new job, a cheap Claude Haiku call scores fit to his profile + CV and produces a one-line reason; re-rank the digest using the AI score as a tier on top of the deterministic score. Cache by `dedup_key` so a job is scored once. Off → deterministic order unchanged.

## Task C.3 — AI application help (he applies)
- A per-job Telegram action that drafts a tailored cover letter + CV-tailoring suggestions for that posting, returned to him to review/edit/send. **No auto-apply, no send-on-his-behalf.** Capped + flagged like C.1.

## Wave C PR
- `wave-c-ai`. **STOP, summarize (cap config, what the key/cap/CV inputs are), WAIT.**

---

# WAVE D — UX polish (`ui-ux-pro-max-skill` relevant here)

Delivered as `wave-d-ux`. Use the ui-ux-pro-max skill for the Telegram card/layout work.

## Task D.1 — Digest card readability
- Improve the card layout/legibility (Hebrew + English), badges, and truncation using the ui-ux-pro-max guidance. TDD against `formatting.py` output.

## Task D.2 — Fix the dead `OPENED` status
- `🔗 Open` is a URL button that never records `opened`. Add an `open:{id}[:page]` callback that records `OPENED` (and still deep-links), so `/stats` "opened" is real. TDD the handler + status transition.

## Task D.3 — Light in-Telegram filter tuning + spotted UX wins
- Optional commands to nudge filters (e.g. toggle remote mode / experience mode) from chat, plus any small UX wins found during the wave. Each TDD'd.

## Wave D PR
- `wave-d-ux`. **STOP, summarize, WAIT.**

---

## Self-review notes

- **Spec coverage:** Wave 0 ↔ FIX A/B/C (all three, with tests). Wave A ↔ Hebrew, Comeet, Greenhouse/Lever expansion, aggregator eval, LinkedIn-email, experience-mode evidence, diagnostics, and the AllJobs/Drushim no-scrape decision (D2). Wave B ↔ serve+Docker+CI-only. Wave C ↔ capped fit-ranking + application-help, fail-closed/flagged. Wave D ↔ card polish + OPENED fix + light tuning. Pain points: #1 volume → Wave A; #2 Jerusalem → 0.1; #3 source slug → 0.2; #4 always-on → Wave B.
- **No-placeholder check:** Wave 0 carries full code + tests (executable now). Waves A–D are intentionally task-level because they depend on your decisions (D2–D10), provided secrets, and live verification; each wave's bite-sized TDD steps are produced at wave start, not guessed now.
- **Principle check:** every external-source task is API/RSS/IMAP only; AllJobs/Drushim explicitly flagged as no-scrape (D2); no auto-apply anywhere; AI isolated to Wave C behind a flag.
```
