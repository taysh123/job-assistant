"""Collection pipeline: collect -> filter -> dedup -> persist -> deliver."""

from __future__ import annotations

import logging

from .config import Config, Secrets
from .db.repository import Repository
from .filtering.dedup import filter_unseen
from .filtering.filters import FilterEngine
from .models import Job
from .sources.registry import build_sources
from .telegram.client import TelegramClient
from .telegram.digest import send_digest

logger = logging.getLogger(__name__)


def collect_all(config: Config, secrets: Secrets | None = None) -> list[Job]:
    """Run every enabled source, aggregating results. Sources never raise."""
    jobs: list[Job] = []
    for source in build_sources(config, secrets):
        found = source.collect()
        logger.info("source %s returned %d jobs", source.name, len(found))
        jobs.extend(found)
    return jobs


def run_collection(config: Config, secrets: Secrets, repo: Repository,
                   *, send: bool = True) -> dict:
    """Full pipeline. Returns counts for logging / run records.

    When ``send`` is False (dry-run) jobs are still filtered, deduped and
    persisted but nothing is sent to Telegram.
    """
    raw = collect_all(config, secrets)
    matched = FilterEngine(config.filters).filter(raw)
    new_jobs = filter_unseen(matched, repo)
    inserted = repo.insert_new_jobs(new_jobs)

    sent = 0
    if send and inserted:
        if not secrets.is_configured:
            logger.warning("Telegram not configured; skipping send of %d jobs", len(inserted))
        else:
            client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
            # Respect the digest size cap; highest-scoring first.
            to_send = inserted[: config.digest.max_jobs]
            sent = send_digest(
                client, repo, to_send,
                summary_chars=config.digest.summary_chars,
                page_size=config.digest.page_size,
                tz=config.digest.timezone,
            )
    elif send and not inserted:
        if secrets.is_configured and config.digest.notify_empty:
            client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
            send_digest(client, repo, [])

    counts = {
        "collected": len(raw),
        "matched": len(matched),
        "new": len(inserted),
        "sent": sent,
    }
    repo.record_run("collect", counts)
    logger.info("collection complete: %s", counts)
    return counts
