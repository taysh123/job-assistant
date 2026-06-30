"""Always-on `serve` mode: an internal scheduler + a single-process loop.

``serve`` runs ONE process that (a) runs a collection when due and the weekly
summary on Mondays, and (b) long-polls Telegram for button/command handling —
the single ``getUpdates`` consumer, against ONE local SQLite. This replaces the
GitHub-Actions crons for users who run their own always-on host, so no DB is
committed to git at runtime.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .config import Config, Secrets
from .db.repository import Repository
from .pipeline import run_collection
from .summary.weekly import send_weekly_summary
from .telegram.client import TelegramClient
from .telegram.handlers import process_updates

logger = logging.getLogger(__name__)


def _hours_since(repo: Repository, kind: str, now: datetime) -> float | None:
    last = repo.last_run_at(kind)
    return None if last is None else (now - last).total_seconds() / 3600.0


def collect_due(repo: Repository, interval_hours: float, now: datetime) -> bool:
    """True if no collection has run yet, or the interval has elapsed."""
    hours = _hours_since(repo, "collect", now)
    return hours is None or hours >= interval_hours


def weekly_due(repo: Repository, now: datetime) -> bool:
    """True on Mondays when no weekly summary has gone out that day yet."""
    if now.weekday() != 0:  # 0 = Monday — mirrors the old weekly cron
        return False
    last = repo.last_run_at("weekly")
    return last is None or (now.date() - last.date()).days >= 1


def run_due(config: Config, secrets: Secrets, repo: Repository, *,
            now: datetime | None = None) -> set[str]:
    """Run any due collect/weekly jobs once. Returns the kinds that ran."""
    now = now or datetime.now(timezone.utc)
    ran: set[str] = set()
    if collect_due(repo, config.serve.collect_interval_hours, now):
        run_collection(config, secrets, repo, send=True)
        ran.add("collect")
    if weekly_due(repo, now):
        send_weekly_summary(secrets, repo)
        ran.add("weekly")
    return ran


def serve(config: Config, secrets: Secrets, repo: Repository, *,
          poll: int = 25, clock=None, stop=None) -> None:
    """Single-process always-on loop. Each cycle runs any due scheduled jobs,
    then long-polls Telegram (up to ``poll`` s) for live command/button handling.
    One getUpdates consumer, one SQLite connection — no threads, no committed DB.
    Runs until ``stop()`` returns True or KeyboardInterrupt.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
    logger.info("serve loop starting (long-poll %ss)", poll)
    while not (stop and stop()):
        try:
            ran = run_due(config, secrets, repo, now=clock())
            if ran:
                logger.info("scheduler ran: %s", ", ".join(sorted(ran)))
            process_updates(client, repo, config, long_poll=poll)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("serve cycle failed (continuing): %s", exc)
            time.sleep(3)
