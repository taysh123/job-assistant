"""Handle Telegram updates: button callbacks and slash commands.

Used by the ``process-updates`` CLI entrypoint. Because the bot runs from a
GitHub Actions cron (not a live server), updates are drained from
``getUpdates`` using a stored offset and processed in a single batch.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from ..config import Config
from ..db.repository import Repository
from ..models import JobStatus
from .client import TelegramClient
from .formatting import format_job_card, format_job_list, job_keyboard
from .pagination import load_digest, render_page

logger = logging.getLogger(__name__)

OFFSET_KEY = "tg_offset"

CALLBACK_STATUS = {
    "save": JobStatus.SAVED,
    "ignore": JobStatus.IGNORED,
    "applied": JobStatus.APPLIED,
    "open": JobStatus.OPENED,
}

HELP_TEXT = (
    "<b>Job Assistant</b>\n\n"
    "Each run I send ONE digest message: a paginated list of new matching jobs "
    "(use ⬅️ Prev / Next ➡️ to browse). Each job has 💾 Save · 🙈 Ignore · 🔗 Open · "
    "✅ Mark-Applied — actions keep you on the same page.\n\n"
    "Commands:\n"
    "/today — jobs found in the last 24h\n"
    "/saved — your saved jobs\n"
    "/applied — jobs you've applied to\n"
    "/stats — counts by status\n"
    "/config — your current filter settings\n"
    "/diag — collection funnel (collected→matched→sent)\n"
    "/help — this message"
)


def _since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# --- callbacks -----------------------------------------------------------

def _edit_digest_page(client: TelegramClient, repo: Repository, config: Config,
                      message_id: int, page: int) -> bool:
    """Re-render and edit a digest message to ``page``. Returns False if unknown."""
    rendered = render_page(repo, message_id, page, tz=config.digest.timezone,
                           page_size=config.digest.page_size)
    if rendered is None:
        return False
    text, keyboard = rendered
    try:
        client.edit_message_text(message_id, text, reply_markup=keyboard)
    except Exception as exc:  # noqa: BLE001 - editing must not break the batch
        logger.debug("could not edit digest message %s: %s", message_id, exc)
    return True


def handle_callback(client: TelegramClient, repo: Repository, config: Config,
                    callback: dict) -> None:
    data = callback.get("data", "")
    cq_id = callback["id"]
    message_id = (callback.get("message") or {}).get("message_id")

    # Centre label button — nothing to do.
    if data == "noop":
        client.answer_callback_query(cq_id)
        return

    # Pagination: only change the visible page.
    if data.startswith("page:"):
        page = int(data.split(":", 1)[1])
        if message_id and _edit_digest_page(client, repo, config, message_id, page):
            client.answer_callback_query(cq_id)
        else:
            client.answer_callback_query(cq_id, "Digest expired")
        return

    # Job action: "action:job_id[:page]".
    parts = data.split(":")
    action = parts[0]
    status = CALLBACK_STATUS.get(action)
    raw_id = parts[1] if len(parts) > 1 else ""
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    if status is None or not raw_id.isdigit():
        client.answer_callback_query(cq_id, "Unknown action")
        return

    job = repo.get_job(int(raw_id))
    if job is None:
        client.answer_callback_query(cq_id, "Job not found")
        return

    if action == "open":
        # Opening is the weakest signal — record it only while the job is still
        # untouched, so a tap never clobbers a Save / Ignore / Applied.
        if job.status is JobStatus.NEW:
            repo.set_status(job.id, JobStatus.OPENED)
            job.status = JobStatus.OPENED
        client.answer_callback_query(cq_id, "Opened ↗ — tap the title to view")
    else:
        repo.set_status(job.id, status)
        job.status = status
        client.answer_callback_query(cq_id, f"Marked {status.value}")

    if message_id is None:
        return
    # Prefer re-rendering the digest page (keeps the user in place); fall back to
    # the single-card layout for legacy individual-card messages.
    if page is not None and _edit_digest_page(client, repo, config, message_id, page):
        return
    if load_digest(repo, message_id) and _edit_digest_page(client, repo, config, message_id, page or 1):
        return
    try:
        client.edit_message_text(message_id, format_job_card(job), reply_markup=job_keyboard(job))
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not edit message %s: %s", message_id, exc)


# --- commands ------------------------------------------------------------

def _enabled_sources(config: Config) -> list[str]:
    """Names of every source whose config has ``enabled=True`` (introspected, so a
    newly-added source appears automatically without editing this list)."""
    s = config.sources
    return [name for name in type(s).model_fields if getattr(s, name).enabled]


def _format_config(config: Config) -> str:
    f = config.filters
    enabled = _enabled_sources(config)
    return (
        "<b>Current config</b>\n\n"
        f"Sources: {', '.join(enabled) or 'none'}\n"
        f"Remote mode: {f.remote}\n"
        f"Titles allow: {', '.join(f.titles_allow) or '—'}\n"
        f"Keywords allow: {', '.join(f.keywords_allow) or '—'}\n"
        f"Keywords deny: {', '.join(f.keywords_deny) or '—'}\n"
        f"Locations allow: {', '.join(f.locations_allow) or '—'}\n"
        f"Locations deny: {', '.join(f.locations_deny) or '—'}\n"
        f"Min match score: {f.min_match_score}\n\n"
        "<i>Edit config/config.yaml to change these.</i>"
    )


def _format_stats(repo: Repository) -> str:
    total = repo.status_counts()
    week = repo.status_counts(_since_iso(24 * 7))
    sources = repo.source_counts(_since_iso(24 * 7))

    def line(counts: dict) -> str:
        order = ["new", "saved", "ignored", "opened", "applied"]
        return " · ".join(f"{k}: {counts.get(k, 0)}" for k in order)

    src = ", ".join(f"{k} ({v})" for k, v in list(sources.items())[:5]) or "—"
    return (
        "<b>Stats</b>\n\n"
        f"All time — {line(total)}\n"
        f"Last 7 days — {line(week)}\n"
        f"Top sources (7d): {src}"
    )


def _format_diag(repo: Repository, config: Config) -> str:
    """Collection-funnel diagnostics: recent runs (collected→matched→new→sent)
    plus which sources are enabled and how many stored jobs came from each."""
    runs = repo.recent_runs("collect", limit=8)
    funnel = "\n".join(
        f"{r['ran_at'][:16].replace('T', ' ')} — "
        f"{r['counts'].get('collected', 0)}→{r['counts'].get('matched', 0)}"
        f"→{r['counts'].get('new', 0)}→{r['counts'].get('sent', 0)}"
        for r in runs
    ) or "no collect runs recorded yet"
    sources = repo.source_counts()
    src = ", ".join(f"{k} ({v})" for k, v in list(sources.items())[:8]) or "—"
    return (
        "<b>Diagnostics</b>\n\n"
        f"Enabled sources: {', '.join(_enabled_sources(config)) or 'none'}\n\n"
        "<b>Recent collect runs</b> (collected→matched→new→sent):\n"
        f"{funnel}\n\n"
        f"<b>Stored jobs by source</b>: {src}"
    )


def handle_command(client: TelegramClient, repo: Repository, config: Config,
                   text: str, chat_id: str) -> None:
    cmd = text.strip().split()[0].lstrip("/").split("@")[0].lower()

    if cmd in ("start", "help"):
        client.send_message(HELP_TEXT, chat_id=chat_id)
    elif cmd == "today":
        jobs = repo.list_since(_since_iso(24), limit=config.digest.max_jobs)
        client.send_message(format_job_list("Jobs in the last 24h", jobs), chat_id=chat_id)
    elif cmd == "saved":
        client.send_message(
            format_job_list("Saved jobs", repo.list_by_status(JobStatus.SAVED)), chat_id=chat_id)
    elif cmd == "applied":
        client.send_message(
            format_job_list("Applied jobs", repo.list_by_status(JobStatus.APPLIED)), chat_id=chat_id)
    elif cmd == "stats":
        client.send_message(_format_stats(repo), chat_id=chat_id)
    elif cmd == "config":
        client.send_message(_format_config(config), chat_id=chat_id)
    elif cmd == "diag":
        client.send_message(_format_diag(repo, config), chat_id=chat_id)
    else:
        client.send_message("Unknown command. Try /help", chat_id=chat_id)


# --- dispatch ------------------------------------------------------------

def handle_update(client: TelegramClient, repo: Repository, config: Config, update: dict) -> None:
    if "callback_query" in update:
        handle_callback(client, repo, config, update["callback_query"])
    elif "message" in update:
        message = update["message"]
        text = message.get("text", "")
        if text.startswith("/"):
            chat_id = str(message["chat"]["id"])
            handle_command(client, repo, config, text, chat_id)


def process_updates(client: TelegramClient, repo: Repository, config: Config,
                    long_poll: int = 0) -> int:
    """Drain pending updates once and persist the new offset. Returns count.

    ``long_poll`` is the Telegram getUpdates timeout (seconds): 0 returns
    immediately (the cron/one-shot mode); a positive value makes Telegram hold the
    request until an update arrives, which the ``--watch`` loop uses for near
    real-time response.
    """
    offset_raw = repo.get_state(OFFSET_KEY)
    offset = int(offset_raw) if offset_raw else None
    updates = client.get_updates(offset=offset, timeout=long_poll)
    for update in updates:
        try:
            handle_update(client, repo, config, update)
        except Exception as exc:  # noqa: BLE001 - one bad update must not block the rest
            logger.warning("failed to handle update %s: %s", update.get("update_id"), exc)
        repo.set_state(OFFSET_KEY, str(update["update_id"] + 1))
    return len(updates)


def watch_updates(client: TelegramClient, repo: Repository, config: Config, *,
                  long_poll: int = 25, stop=None, error_backoff: float = 3.0) -> None:
    """Continuously process updates via long polling for near real-time browsing.

    Each cycle blocks (up to ``long_poll`` s) until Telegram has an update, then
    handles it immediately — so Prev/Next reacts in ~1-2s and callbacks are answered
    before they expire. Runs until ``stop()`` returns True or KeyboardInterrupt.
    Transient errors (network, or a 409 if the GitHub-Actions cron polls at the same
    time — Telegram allows only one getUpdates consumer) are logged and retried.
    """
    while not (stop and stop()):
        try:
            process_updates(client, repo, config, long_poll=long_poll)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.warning("watch cycle failed (retrying): %s", exc)
            time.sleep(error_backoff)
