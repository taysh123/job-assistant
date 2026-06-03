"""Render jobs as Telegram messages (HTML) with inline keyboards."""

from __future__ import annotations

from datetime import datetime
from html import escape

from ..models import Job, JobStatus

STATUS_LABEL = {
    JobStatus.NEW: "🆕 New",
    JobStatus.SAVED: "💾 Saved",
    JobStatus.IGNORED: "🙈 Ignored",
    JobStatus.OPENED: "🔗 Opened",
    JobStatus.APPLIED: "✅ Applied",
}


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "—"


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _reasons_line(job: Job) -> str:
    if not job.match_reasons:
        return ""
    pretty = [r.split(":", 1)[-1] for r in job.match_reasons]
    # De-duplicate while preserving order.
    seen, out = set(), []
    for p in pretty:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return ", ".join(out)


def format_job_card(job: Job, *, summary_chars: int = 280) -> str:
    """Build the HTML body of a single job card."""
    title = escape(job.title or "Untitled role")
    company = escape(job.company or "Unknown company")
    location = escape(job.location or "—")
    source = escape(job.source)
    remote = "Remote" if job.remote else "On-site/Hybrid"
    summary = escape(_truncate(job.summary, summary_chars)) if job.summary else ""
    reasons = escape(_reasons_line(job))

    lines = [
        f"<b>{title}</b>",
        f"🏢 {company}  •  📍 {location} ({remote})",
        f"🌐 {source}  •  🗓 {_fmt_date(job.posted_at)}",
    ]
    if summary:
        lines.append("")
        lines.append(summary)
    if reasons:
        lines.append("")
        lines.append(f"🔎 <i>Matched:</i> {reasons}")
    if job.status is not JobStatus.NEW:
        lines.append("")
        lines.append(f"<i>{STATUS_LABEL[job.status]}</i>")
    return "\n".join(lines)


def job_keyboard(job: Job) -> dict:
    """Inline keyboard: Save / Ignore + Open(url) / Mark Applied.

    Once a job has been actioned we collapse to the Open link only, so the
    card reflects its final state without stale action buttons.
    """
    open_button = {"text": "🔗 Open", "url": job.url}
    if job.status in (JobStatus.SAVED, JobStatus.IGNORED, JobStatus.APPLIED):
        return {"inline_keyboard": [[open_button]]}
    return {
        "inline_keyboard": [
            [
                {"text": "💾 Save", "callback_data": f"save:{job.id}"},
                {"text": "🙈 Ignore", "callback_data": f"ignore:{job.id}"},
            ],
            [
                open_button,
                {"text": "✅ Mark Applied", "callback_data": f"applied:{job.id}"},
            ],
        ]
    }


def format_digest_header(count: int) -> str:
    if count == 0:
        return "🔎 No new matching jobs this run."
    plural = "job" if count == 1 else "jobs"
    return f"🔎 <b>{count} new {plural}</b> matched your preferences:"


def format_job_list(title: str, jobs: list[Job]) -> str:
    """Compact one-line-per-job list used by /today, /saved, etc."""
    if not jobs:
        return f"<b>{escape(title)}</b>\n\n(nothing here yet)"
    lines = [f"<b>{escape(title)}</b>", ""]
    for job in jobs:
        t = escape(_truncate(job.title, 70))
        c = escape(job.company or "")
        lines.append(f"• <a href=\"{escape(job.url)}\">{t}</a> — {c}")
    return "\n".join(lines)
