# Deploying the always-on Job Assistant

v1 ran on GitHub-Actions crons that committed `data/jobs.db` back to the repo. For
instant, laptop-independent operation, run the single-process **`serve`** loop on a
small always-on host instead. One process owns everything:

- runs a **collection** every `serve.collect_interval_hours` (default 12h),
- sends the **weekly summary** on Mondays,
- **long-polls Telegram** so Prev/Next + Save/Ignore/Apply react in ~1–2s,
- against **one local SQLite** file on a persistent volume — no DB committed to git.

It is the single `getUpdates` consumer, so don't also run `process-updates` / the
`bot.yml` workflow against the same bot at the same time (Telegram allows one
consumer; overlap yields a harmless 409).

## Run with Docker (recommended)

```bash
docker build -t job-assistant .
docker run -d --name job-assistant --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxxx \
  -e TELEGRAM_CHAT_ID=xxxx \
  -v job-assistant-data:/data \
  job-assistant
# optional LinkedIn email source: add -e IMAP_USERNAME=xxx -e IMAP_PASSWORD=xxx
```

- `--restart unless-stopped` keeps it running across reboots/crashes.
- The named volume `job-assistant-data` persists `/data/jobs.db` (your jobs + statuses).
- Edit preferences in `config/config.yaml` and rebuild, or mount your own over `/app/config`.

Logs: `docker logs -f job-assistant` · Stop: `docker stop job-assistant`.

## Run without Docker

```bash
pip install -e .
# bash:        export TELEGRAM_BOT_TOKEN=xxxx TELEGRAM_CHAT_ID=xxxx
# PowerShell:  $env:TELEGRAM_BOT_TOKEN="xxxx"; $env:TELEGRAM_CHAT_ID="xxxx"
python -m job_assistant.cli --db /path/to/jobs.db serve
```

Use a process supervisor (systemd, pm2, or nssm on Windows) to keep it alive.

## GitHub Actions after the switch

`ci.yml` (tests) still runs on push/PR. The `collect` / `bot` / `weekly` workflows have
their **schedules disabled** (commented out) — kept only as manual fallbacks via the
Actions **Run workflow** button. Don't trigger `bot` manually while `serve` runs
(getUpdates 409). To revert to cron mode, uncomment the `schedule:` blocks (and stop
`serve` so the two don't both write the DB / poll Telegram).

## One-shot commands still work

`init-db`, `collect [--dry-run]`, `process-updates [--watch]`, `weekly`, and
`reset-seen-jobs` behave as before for local use against your `--db`.

## Back up

Your entire state is the one SQLite file. Periodically back up the volume, e.g.
`docker cp job-assistant:/data/jobs.db ./jobs-backup.db`.
