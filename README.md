# Job Assistant

A personal, low-cost job-finding assistant. On a schedule it collects new
software-engineering postings from configured sources, filters them by your
preferences, removes duplicates, and sends **one paginated digest message to
Telegram** — one job card at a time (default 1/page) with **⬅️ Prev /
Next ➡️** navigation. Each job has **Save / Ignore / Open / Mark-Applied**, and
everything is tracked in a local SQLite database. A **weekly summary** reports
what was found and what you did with it.

**v1 deliberately does _not_:** submit applications automatically, scrape behind
logins/captchas, or use any AI. It favours reliability and easy maintenance.

---

## How it works

```
sources ──► filter engine ──► dedup ──► SQLite ──► Telegram digest
(Remotive,    (allow/deny,    (per-run +   (jobs,      (ONE paginated
 WWR RSS,      remote/loc/     DB unseen)   runs,        message: Prev/Next +
 Greenhouse,   seniority,                   bot_state)   Save/Ignore/Open/
 Lever,        scoring)                                  Mark-Applied)
 LinkedIn*)   *opt: alert emails
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
> button presses — including **Prev/Next** paging and Save/Ignore/Apply — are
> processed at the next `bot.yml` run (default every 20 min), not instantly. The
> digest message then edits in place (page state is preserved in SQLite). The
> **Open** button is a direct URL link, so it always works immediately. To make
> paging/actions feel snappier, lower the `bot.yml` interval (a public repo gets
> unlimited Actions minutes; see _Cost_ below).

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
   - (optional, for LinkedIn) `IMAP_USERNAME`, `IMAP_PASSWORD`
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

### 4. Optional: LinkedIn via Job-Alert emails (no scraping)
LinkedIn has no open jobs API and scraping it is fragile/against its terms, so this
source ingests **the Job-Alert emails LinkedIn already sends you** — safe and stable.

1. On LinkedIn, run a job search and **turn on a Job Alert** (LinkedIn then emails you
   matching jobs).
2. Make those emails reachable over IMAP. For Gmail: enable IMAP, then create an
   **App Password** (Account → Security → App passwords).
3. Set secrets/env `IMAP_USERNAME` and `IMAP_PASSWORD` (use the App Password, not your
   login password). IMAP host/folder live in `config.yaml`.
4. In `config.yaml` set `sources.linkedin.enabled: true`.

The source reads recent alert emails from the configured LinkedIn senders, extracts the
job title + link (company/location best-effort), and feeds them through the same filter,
dedup, and digest pipeline. It's skipped automatically if IMAP creds are absent, and any
hiccup (bad creds, changed email layout) is logged and ignored — it never breaks a run.
Email-template parsing is inherently best-effort; the job title + direct link are always
captured so each lead stays actionable.

**Why no LinkedIn auto-apply / Easy Apply?** LinkedIn exposes no public apply API; submitting
Easy Apply programmatically would require logging in and automating the form — login automation
that's brittle and against LinkedIn's terms, so this project does **not** do it. The safe,
compliant flow is: leads arrive in the digest, you tap **🔗 Open** (it deep-links to the job's
apply-ready page), and you complete Easy Apply yourself in one tap.

### 5. Optional: Comeet ATS (Israeli companies, public API)
Comeet is a common ATS among Israeli employers and exposes a **public Careers API**.

1. For each target company, get its **uid** and **token** (on the Comeet side:
   Settings → Careers Website → Careers API).
2. In `config.yaml`, add entries under `sources.comeet.companies` and set `enabled: true`:
   ```yaml
   comeet:
     enabled: true
     companies:
       - { name: "Example Co", uid: "30.005", token: "YOUR_TOKEN" }
   ```

Each company is fetched from the public API and flows through the same filter/dedup/digest
pipeline. A wrong or stale uid/token is logged and skipped — it never breaks a run.

---

## Configuration (`config/config.yaml`)

Preferences are non-secret and committed. Secrets stay in env / Actions secrets.

The shipped defaults are tuned for a **Graduate / Junior software search in Israel**
(center-weighted, open to remote/hybrid/on-site, no relocation) — edit for your own profile.

- **sources** — toggle each source; the Greenhouse/Lever lists ship with a verified
  starter set of Israeli companies (add/remove slugs freely; WWR uses feed slugs).
  `comeet` (Israeli ATS, public API; off by default) and `linkedin` (Job-Alert email
  source; off by default) are optional — see Setup §4.
- **filters**
  - `titles_allow` / `keywords_allow` — a job needs ≥ `min_match_score` hits (title or summary).
  - `keywords_deny` / `seniority_deny` / `titles_deny` / `locations_deny` — hard exclusions.
    `titles_deny` is title-only and drops non-dev role types that share a software
    word (e.g. "sales/support/solutions engineer", recruiter, account/HR/marketing).
  - `remote`: `any` | `remote_only` | `onsite_only`.
  - `locations_allow` — optional HARD geo filter for on-site jobs (remote always passes);
    empty by default so all Israeli locations + remote stay eligible (center handled by ranking).
  - `seniority_allow` — optional gate matched against the title (left empty by default).
  - `boost_keywords` / `boost_weight` — **ranking only**: matches (in title + location)
    add weight so junior + Israel/center roles sort to the top, without excluding any
    Israeli location or remote.
  - `max_years_experience` / `experience_mode` / `experience_penalty` — junior-fit
    **experience detection** (see below).
- **digest** — `max_jobs` per run, `summary_chars`, `timezone`, `page_size` (1 = one job/page).

### Experience detection
Roles that **explicitly** require more years than `max_years_experience` (default `2`) are
handled per `experience_mode`: `filter` (the shipped default — exclude the role), `downrank`
(a `experience_penalty` is subtracted so the role sinks but stays visible), or `off`. Detection is tied to experience/
requirement context — it catches `"5+ years"`, `"minimum 3 years"`, `"at least 4 years"`,
`"3-5 years of experience"` (lower bound), and `"senior-level"`, while a plain `"Software
Engineer"` or `"0–2 years"` role is **never** affected. This trims senior roles that slip past
the title-based `seniority_deny` without hiding genuine junior leads.
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
