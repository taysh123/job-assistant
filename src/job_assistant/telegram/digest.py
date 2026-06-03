"""Send the paginated digest and summaries to Telegram."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..db.repository import Repository
from ..models import Job
from .client import TelegramClient
from .formatting import format_digest_header
from .pagination import DEFAULT_PAGE_SIZE, render_page, save_digest

logger = logging.getLogger(__name__)


def send_digest(client: TelegramClient, repo: Repository, jobs: list[Job],
                *, summary_chars: int = 280, page_size: int = DEFAULT_PAGE_SIZE,
                tz: str = "UTC") -> int:
    """Send the run's jobs as ONE paginated message and persist its page state.

    Returns the number of messages sent (1, or 0 for an empty run). ``jobs`` are
    already filtered/deduped/capped by the pipeline and ordered by rank.
    """
    if not jobs:
        client.send_message(format_digest_header(0))
        return 0

    job_ids = [j.id for j in jobs if j.id is not None]

    # Send a placeholder first to obtain the message id, then render page 1 into
    # it (rendering needs the id so callback_data can be tied to this message).
    placeholder = client.send_message("🔎 Preparing your job digest…")
    message_id = placeholder["message_id"]
    save_digest(repo, message_id, job_ids, page_size)

    rendered = render_page(repo, message_id, 1, run_dt=datetime.now(timezone.utc), tz=tz)
    if rendered is None:  # pragma: no cover - state was just saved
        return 1
    text, keyboard = rendered
    try:
        client.edit_message_text(message_id, text, reply_markup=keyboard)
    except Exception as exc:  # noqa: BLE001 - keep the run resilient
        logger.warning("failed to render digest page 1: %s", exc)
    # Tie each job to this digest message for traceability.
    for job_id in job_ids:
        repo.set_message_id(job_id, message_id)
    return 1
