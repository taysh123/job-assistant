"""Send job cards and summaries to Telegram."""

from __future__ import annotations

import logging

from ..db.repository import Repository
from ..models import Job
from .client import TelegramClient
from .formatting import format_digest_header, format_job_card, job_keyboard

logger = logging.getLogger(__name__)


def send_digest(client: TelegramClient, repo: Repository, jobs: list[Job],
                *, summary_chars: int = 280) -> int:
    """Send one card per job and store each Telegram message id.

    Returns the number of cards successfully sent. A failure on one card is
    logged and skipped so the rest of the digest still goes out.
    """
    if not jobs:
        client.send_message(format_digest_header(0))
        return 0

    client.send_message(format_digest_header(len(jobs)))
    sent = 0
    for job in jobs:
        try:
            result = client.send_message(
                format_job_card(job, summary_chars=summary_chars),
                reply_markup=job_keyboard(job),
            )
            if job.id is not None:
                repo.set_message_id(job.id, result["message_id"])
            sent += 1
        except Exception as exc:  # noqa: BLE001 - one bad card must not abort the digest
            logger.warning("failed to send card for job %s: %s", job.id, exc)
    return sent
