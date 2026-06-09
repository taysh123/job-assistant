"""Digest pagination: per-message state + page rendering.

A digest is one Telegram message browsing a fixed, ordered list of job ids. The
list and page size are stored in the ``bot_state`` KV keyed by message id so the
state survives across stateless GitHub-Actions cron runs. The current page is NOT
stored — it is carried in each button's ``callback_data`` — so an action never
loses the user's place.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..db.repository import Repository
from .formatting import digest_keyboard, format_digest_page

DIGEST_KEY = "digest:{}"
DEFAULT_PAGE_SIZE = 5


def _key(message_id: int) -> str:
    return DIGEST_KEY.format(message_id)


def save_digest(repo: Repository, message_id: int, job_ids: list[int], page_size: int) -> None:
    repo.set_state(_key(message_id), json.dumps({
        "job_ids": job_ids,
        "page_size": page_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))


def load_digest(repo: Repository, message_id: int) -> dict | None:
    raw = repo.get_state(_key(message_id))
    return json.loads(raw) if raw else None


def page_slice(job_ids: list[int], page: int, page_size: int) -> tuple[list[int], int]:
    """Return (ids_on_page, total_pages). ``page`` is 1-based and clamped to range."""
    page_size = max(1, page_size)
    total_pages = max(1, (len(job_ids) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return job_ids[start : start + page_size], total_pages


def render_page(
    repo: Repository,
    message_id: int,
    page: int,
    *,
    run_dt: datetime | None = None,
    tz: str = "UTC",
    page_size: int | None = None,
) -> tuple[str, dict] | None:
    """Build (text, keyboard) for ``page`` of the digest, or None if unknown.

    If the digest's ``bot_state`` row is missing (e.g. a dropped commit between
    cron runs), rebuild the job list from each job's persisted
    ``telegram_message_id`` so Prev/Next still works. ``page_size`` (the caller's
    configured value) is used for that reconstruction.
    """
    state = load_digest(repo, message_id)
    if state:
        job_ids = state["job_ids"]
        page_size = state.get("page_size", DEFAULT_PAGE_SIZE)
    else:
        # Self-heal: reconstruct the ordered list from the linked job rows.
        job_ids = repo.list_ids_by_message_id(message_id)
        if not job_ids:
            return None
        page_size = page_size or DEFAULT_PAGE_SIZE

    ids_on_page, total_pages = page_slice(job_ids, page, page_size)
    page = max(1, min(page, total_pages))
    jobs = repo.get_jobs(ids_on_page)

    # Timestamp shown in the header: explicit run_dt, else the digest's creation time.
    run_at = run_dt
    if run_at is None and state and state.get("created_at"):
        run_at = datetime.fromisoformat(state["created_at"])
    if run_at is None:
        run_at = datetime.now(timezone.utc)

    text = format_digest_page(
        jobs,
        page=page,
        total_pages=total_pages,
        total_jobs=len(job_ids),
        run_dt=run_at,
        tz=tz,
    )
    keyboard = digest_keyboard(jobs, page=page, total_pages=total_pages)
    return text, keyboard
