# Job Assistant

A personal, low-cost job-finding assistant. On a schedule it collects new
software-engineering postings from configured sources, filters them by your
preferences, removes duplicates, and sends concise **job cards to Telegram**.
You react with **Save / Ignore / Open / Mark-Applied**, and everything is tracked
in a local SQLite database. A **weekly summary** reports what was found and what
you did with it.

**v1 deliberately does _not_:** submit applications automatically, scrape behind
logins/captchas, or use any AI. It favours reliability and easy maintenance.

---

## How it works

```
sources ──► filter engine ──► dedup ──► SQLite ──► Telegram digest
(Remotive,    (allow/deny,    (per-run +   (jobs,      (one card per job,
 WWR RSS,      remote/loc/     DB unseen)   runs,        Save/Ignore/Open/
 Greenhouse,   seniority,                   bot_state)   Mark-Applied)
 Lever)        scoring)
```

Three scheduled jobs (GitHub Actions cron), all serialized on one `concurrency`
group so they never clash writing the database:

| Workflow | Schedule (default) | Does |
|----------|--------------------|------|
| `collect.yml` | 07:00 & 18:00 UTC | collect → filter → dedup → persist → send digest |
| `bot.yml` | every 20 min | drain Telegram updates: commands + button presses |
| `weekly.yml` | Mon 08:00 UTC | send the weekly summary |
| `ci.yml` | on push/PR | run the test suite |

> **Interactivity note.** GitHub Actions can't host a live bot, so commands and
> button presses are processed at the next `bot.yml` run (default every 20 min),
> not instantly. The **Open** button is a direct URL link, so it always works
> immediately. To make buttons feel snappier, lower the `bot.yml` interval
> (a public repo gets unlimited Actions minutes; see _Cost_ below).

State (`data/jobs.db`) is committed back to the repo after each run — the single
durable copy of your jobs and their statuses.

---

## Project layout

```
src/job_assistant/
  cli.py            # entrypoints: init-db | collect | process-updates | weekly
  config.py         # pydantic config models + env secrets
  models.py         # Job dataclass + dedup key
  pipeline.py       # collect -> filter -> dedup -> persist -> deliver
  db/               # schema.sql + Repository (persistence layer)
  sources/          # base + remotive/weworkremotely/greenhouse/lever + registry
  filtering/        # filters.py (scoring) + dedup.py
  telegram/         # client, formatting (cards/keyboards), digest, handlers
  summary/weekly.py # weekly digest
config/             # config.example.yaml + config.yaml (your preferences)
tests/              # offline tests (+ fixtures/)
.github/workflows/  # collect / bot / weekly / ci
```

Adding a source later means writing one module in `sources/` (a `fetch`/`parse`
split plus a `collect()`), adding a config block, and registering it in
`sources/registry.py`. The core doesn't change.

---

## Setup

### 1. Create your Telegram bot
1. Message **@BotFather** → `/newbot` → copy the **bot token**.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
   `message.chat.id` — that's your **chat id**.

### 2. Local development
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
# source .venv/bin/activate           # macOS/Linux
pip install -e ".[dev]"

copy .env.example .env                # then fill in your token + chat id
copy config\config.example.yaml config\config.yaml   # then edit preferences

python -m job_assistant.cli init-db
python -m job_assistant.cli collect            # collect + send a real digest
python -m job_assistant.cli collect --dry-run  # persist but don't send
python -m job_assistant.cli process-updates    # handle commands/buttons once
python -m job_assistant.cli weekly             # send the weekly summary
pytest                                          # run the tests
```

### 3. Deploy on GitHub Actions (free, runs when your laptop is closed)
1. Push this repo to GitHub.
2. **Settings → Secrets and variables → Actions** → add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **Settings → Actions → General → Workflow permissions** → enable
   **Read and write permissions** (so workflows can commit `data/jobs.db`).
4. Commit a config and an initialized DB so the first run has state:
   ```powershell
   python -m job_assistant.cli init-db
   git add config/config.yaml data/jobs.db
   git commit -m "chore: seed config and database"
   git push
   ```
5. The crons start automatically. Trigger any workflow manually from the
   **Actions** tab via **Run workflow** to test.

---

## Configuration (`config/config.yaml`)

Preferences are non-secret and committed. Secrets stay in env / Actions secrets.

- **sources** — toggle each source; list Greenhouse/Lever company slugs and WWR feed slugs.
- **filters**
  - `titles_allow` / `keywords_allow` — a job needs ≥ `min_match_score` hits (title or summary).
  - `keywords_deny` / `seniority_deny` / `locations_deny` — hard exclusions.
  - `remote`: `any` | `remote_only` | `onsite_only`.
  - `locations_allow` — applied to on-site jobs only (remote jobs always pass).
  - `seniority_allow` — optional gate matched against the title.
- **digest** — `max_jobs` per run, `summary_chars`, `timezone`.

See `config/config.example.yaml` for an annotated template.

## Telegram commands
`/today` · `/saved` · `/applied` · `/stats` · `/config` · `/help`

## Job statuses
`new → saved | ignored | opened | applied`. Each job is sent once
(`dedup_key` UNIQUE); the same posting is never re-sent.

## Maintenance

```powershell
python -m job_assistant.cli reset-seen-jobs
```

Clears the deduplication state so previously-seen jobs become eligible to be
collected and **sent again** on the next run. Useful after broadening your
filters or if a digest was lost.

It is non-destructive to your settings and tracking:
- **Configuration** (`config/*.yaml`) is never touched.
- **Saved** and **Applied** jobs are kept — their status is preserved and they
  stay de-duplicated, so you won't be re-notified about jobs you've acted on.
- Run history and Telegram state are untouched.

(New / ignored / opened jobs are the dedup entries that get cleared.)

---

## Cost

GitHub Actions is free. On a **private** repo you get 2,000 minutes/month; the
default `bot.yml` interval (every 20 min) uses ~1,440 of them. To poll more
often, either raise the interval budget or make the repo **public** (unlimited
Actions minutes — note the committed `data/jobs.db` would then be public too).

## Limitations / non-goals (v1)
- No automatic application submission — **Open** opens the posting for you to apply manually.
- No scraping behind logins or captchas; only official/public APIs and RSS feeds.
- No AI. Filtering is deterministic keyword/rule matching.
