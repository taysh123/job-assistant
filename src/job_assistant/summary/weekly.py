"""Weekly digest: counts, top keywords, and best-performing sources."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape

from ..config import Secrets
from ..db.repository import Repository
from ..telegram.client import TelegramClient


def _top_keywords(reasons: list[str], limit: int = 8) -> list[tuple[str, int]]:
    # reasons look like "keyword:python" / "title:engineer" / "remote".
    terms = [r.split(":", 1)[-1] for r in reasons if r != "remote"]
    return Counter(terms).most_common(limit)


def build_weekly_summary(repo: Repository, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).isoformat()

    status = repo.status_counts(since)
    sources = repo.source_counts(since)
    keywords = _top_keywords(repo.match_reasons_since(since))

    total_new = sum(status.values())
    kw = ", ".join(f"{escape(k)} ({n})" for k, n in keywords) or "—"
    src = ", ".join(f"{escape(k)} ({n})" for k, n in list(sources.items())[:5]) or "—"

    return (
        "📊 <b>Weekly Job Summary</b>\n"
        f"<i>{(now - timedelta(days=7)).date()} → {now.date()}</i>\n\n"
        f"🆕 New jobs found: <b>{total_new}</b>\n"
        f"💾 Saved: {status.get('saved', 0)}\n"
        f"🙈 Ignored: {status.get('ignored', 0)}\n"
        f"✅ Applied: {status.get('applied', 0)}\n\n"
        f"🔝 Top keywords: {kw}\n"
        f"🌐 Best sources: {src}"
    )


def send_weekly_summary(secrets: Secrets, repo: Repository) -> str:
    """Build and send the weekly summary. Returns the message text."""
    text = build_weekly_summary(repo)
    if secrets.is_configured:
        client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
        client.send_message(text)
    repo.record_run("weekly", {"new_last_7d": sum(repo.status_counts(
        (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()).values())})
    return text
