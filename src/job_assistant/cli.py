"""Command-line entrypoints.

Usage:
    python -m job_assistant.cli init-db
    python -m job_assistant.cli collect [--dry-run]
    python -m job_assistant.cli process-updates
    python -m job_assistant.cli weekly
    python -m job_assistant.cli test-telegram
    python -m job_assistant.cli test-job-card
    python -m job_assistant.cli reset-seen-jobs

Each subcommand is a single, stateless operation suitable for a GitHub
Actions cron step (or local invocation).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from .config import load_config, load_secrets
from .db.repository import Repository
from .models import Job
from .pipeline import run_collection
from .summary.weekly import send_weekly_summary
from .telegram.client import TelegramClient
from .telegram.formatting import format_job_card, job_keyboard
from .telegram.handlers import process_updates, watch_updates
from .scheduler import serve

DEFAULT_DB = "data/jobs.db"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_init_db(args) -> int:
    with Repository(args.db) as repo:
        repo.init_schema()
    print(f"Initialized database at {args.db}")
    return 0


def cmd_collect(args) -> int:
    config = load_config(args.config)
    secrets = load_secrets()
    with Repository(args.db) as repo:
        repo.init_schema()
        counts = run_collection(config, secrets, repo, send=not args.dry_run)
    print(f"Collect: {counts}")
    return 0


def cmd_process_updates(args) -> int:
    config = load_config(args.config)
    secrets = load_secrets()
    if not secrets.is_configured:
        print("Telegram secrets not configured; nothing to do.", file=sys.stderr)
        return 0
    client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
    with Repository(args.db) as repo:
        repo.init_schema()
        if getattr(args, "watch", False):
            print(f"Watching for updates (long-poll {args.long_poll}s)… Ctrl+C to stop.")
            try:
                watch_updates(client, repo, config, long_poll=args.long_poll)
            except KeyboardInterrupt:
                pass
            print("Stopped watching.")
            return 0
        n = process_updates(client, repo, config)
    print(f"Processed {n} update(s)")
    return 0


def cmd_test_telegram(args) -> int:
    secrets = load_secrets()
    if not secrets.is_configured:
        print("Telegram secrets not configured. Set TELEGRAM_BOT_TOKEN and "
              "TELEGRAM_CHAT_ID (env or .env).", file=sys.stderr)
        return 1
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
    client.send_message(
        f"🤖 <b>Job Assistant v1</b>\n"
        f"🗓 {timestamp}\n\n"
        "✅ Telegram integration is working"
    )
    print(f"Test message sent to chat {secrets.telegram_chat_id}")
    return 0


def _sample_job() -> Job:
    job = Job(
        source="remotive",
        external_id="sample-1",
        title="Senior Backend Engineer (Python)",
        company="Acme Cloud",
        url="https://example.com/jobs/senior-backend-engineer",
        location="Remote (Europe)",
        remote=True,
        posted_at=datetime.now(timezone.utc),
        summary=(
            "Join our platform team to design and scale REST APIs in Python/FastAPI, "
            "own services end to end, and mentor other engineers. PostgreSQL, AWS, and "
            "a strong testing culture."
        ),
        score=3,
        match_reasons=["title:engineer", "keyword:python", "keyword:fastapi"],
    )
    job.id = 0  # sample id; production cards use the real DB id
    return job


def cmd_test_job_card(args) -> int:
    secrets = load_secrets()
    if not secrets.is_configured:
        print("Telegram secrets not configured. Set TELEGRAM_BOT_TOKEN and "
              "TELEGRAM_CHAT_ID (env or .env).", file=sys.stderr)
        return 1
    config = load_config(args.config)
    job = _sample_job()
    client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
    client.send_message(
        format_job_card(job, summary_chars=config.digest.summary_chars),
        reply_markup=job_keyboard(job),
    )
    print(f"Sample job card sent to chat {secrets.telegram_chat_id}")
    return 0


def cmd_reset_seen_jobs(args) -> int:
    with Repository(args.db) as repo:
        repo.init_schema()
        result = repo.reset_seen_jobs()
    print(
        f"Reset dedup state: cleared {result['deleted']} job(s); "
        f"kept {result['kept']} saved/applied job(s). "
        "Previously-seen jobs will be collected and sent again on the next run."
    )
    return 0


def cmd_weekly(args) -> int:
    secrets = load_secrets()
    with Repository(args.db) as repo:
        repo.init_schema()
        text = send_weekly_summary(secrets, repo)
    print(text)
    return 0


def cmd_serve(args) -> int:
    config = load_config(args.config)
    secrets = load_secrets()
    if not secrets.is_configured:
        print("Telegram secrets not configured; cannot serve.", file=sys.stderr)
        return 1
    with Repository(args.db) as repo:
        repo.init_schema()
        print(
            f"Serving: collect every {config.serve.collect_interval_hours}h + weekly on "
            f"Mondays; Telegram long-poll {args.long_poll}s. Ctrl+C to stop."
        )
        try:
            serve(config, secrets, repo, poll=args.long_poll)
        except KeyboardInterrupt:
            pass
    print("Stopped serving.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-assistant", description="Personal job assistant")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite path (default: data/jobs.db)")
    parser.add_argument("--config", default=None, help="Path to config YAML")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database schema")

    p_collect = sub.add_parser("collect", help="Collect, filter, dedup, persist, and send digest")
    p_collect.add_argument("--dry-run", action="store_true",
                           help="Persist results but do not send to Telegram")

    p_updates = sub.add_parser(
        "process-updates", help="Handle pending Telegram commands and button presses")
    p_updates.add_argument(
        "--watch", action="store_true",
        help="Long-poll continuously for near real-time Prev/Next (Ctrl+C to stop)")
    p_updates.add_argument(
        "--long-poll", type=int, default=25, metavar="SECONDS",
        help="getUpdates long-poll timeout when --watch is set (default: 25)")
    sub.add_parser("weekly", help="Send the weekly summary")

    p_serve = sub.add_parser(
        "serve", help="Always-on loop: scheduled collect/weekly + live Telegram handling")
    p_serve.add_argument("--long-poll", type=int, default=25, metavar="SECONDS",
                         help="getUpdates long-poll timeout (default: 25)")
    sub.add_parser("test-telegram", help="Send a test message to verify Telegram connectivity")
    sub.add_parser("test-job-card", help="Send a sample job card (production formatting + buttons)")
    sub.add_parser(
        "reset-seen-jobs",
        help="Clear dedup state so stored jobs can be sent again (keeps Saved/Applied)",
    )
    return parser


HANDLERS = {
    "init-db": cmd_init_db,
    "collect": cmd_collect,
    "process-updates": cmd_process_updates,
    "weekly": cmd_weekly,
    "serve": cmd_serve,
    "test-telegram": cmd_test_telegram,
    "test-job-card": cmd_test_job_card,
    "reset-seen-jobs": cmd_reset_seen_jobs,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    return HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
