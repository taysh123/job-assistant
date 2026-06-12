"""Render jobs as Telegram messages (HTML) with inline keyboards."""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from ..models import Job, JobStatus

STATUS_LABEL = {
    JobStatus.NEW: "🆕 New",
    JobStatus.SAVED: "💾 Saved",
    JobStatus.IGNORED: "🙈 Ignored",
    JobStatus.OPENED: "🔗 Opened",
    JobStatus.APPLIED: "✅ Applied",
}

# Compact status badge shown after a job has been acted on in the digest.
STATUS_BADGE = {
    JobStatus.SAVED: "💾",
    JobStatus.IGNORED: "🙈",
    JobStatus.OPENED: "🔗",
    JobStatus.APPLIED: "✅",
}


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "—"


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _reasons_list(job: Job) -> list[str]:
    """Deduplicated, human-readable match reasons in order."""
    seen, out = set(), []
    for r in job.match_reasons:
        p = r.split(":", 1)[-1]
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _reasons_line(job: Job) -> str:
    return ", ".join(_reasons_list(job))


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


def _fmt_run_time(dt: datetime, tz: str) -> str:
    try:
        local = dt.astimezone(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 - bad tz string falls back to the given dt
        local = dt
    return local.strftime("%d %b %Y, %H:%M")


def _fit_badges(job: Job) -> str:
    """Meaningful, mobile-friendly fit badges from match reasons (not the raw score):
    a 🟢 Junior tag when an entry-level signal fired, and 🏠 Remote for remote roles."""
    tags = []
    if any(r.startswith("junior:") for r in job.match_reasons):
        tags.append("🟢 Junior")
    if job.remote:
        tags.append("🏠 Remote")
    return " · ".join(tags)


def _compact_card(index: int, job: Job, *, summary_chars: int = 110) -> str:
    """One numbered job entry: at most three short lines (no paragraphs)."""
    title = escape(_truncate(job.title or "Untitled role", 70))
    company = escape(job.company or "—")
    location = escape(_truncate(job.location or "—", 48))
    source = escape(job.source)
    badge = f"  {STATUS_BADGE[job.status]}" if job.status in STATUS_BADGE else ""
    badges = _fit_badges(job)
    badges_suffix = f" · {badges}" if badges else ""

    # Top few match reasons (location is already shown above, so this stays short);
    # fall back to a trimmed summary when a job has no reasons.
    reasons = ", ".join(_reasons_list(job)[:4])
    detail = reasons or _truncate(job.summary, summary_chars)
    detail_line = f"   🔎 {escape(_truncate(detail, summary_chars))}" if detail else ""

    lines = [
        f"<b>{index}. {title}</b> · 🏢 {company}{badge}",
        f"   📍 {location} · 🌐 {source}{badges_suffix}",
    ]
    if detail_line:
        lines.append(detail_line)
    return "\n".join(lines)


def format_digest_page(
    page_jobs: list[Job],
    *,
    page: int,
    total_pages: int,
    total_jobs: int,
    run_dt: datetime,
    tz: str = "UTC",
) -> str:
    """Render one page of the digest as a single compact HTML message."""
    plural = "job" if total_jobs == 1 else "jobs"
    # The "N on this page" count is only useful when a page holds several jobs.
    on_page = f" · {len(page_jobs)} on this page" if len(page_jobs) > 1 else ""
    header = (
        f"🔎 <b>{total_jobs} new {plural}</b> · page {page}/{total_pages}{on_page}\n"
        f"🗓 {_fmt_run_time(run_dt, tz)}"
    )
    cards = [_compact_card(i, job) for i, job in enumerate(page_jobs, start=1)]
    return "\n\n".join([header, *cards])


def digest_keyboard(page_jobs: list[Job], *, page: int, total_pages: int) -> dict:
    """Inline keyboard: one emoji action-row per job + a navigation row.

    Action callbacks carry the page so an action re-renders the *same* page.
    """
    rows: list[list[dict]] = []
    for job in page_jobs:
        rows.append([
            {"text": "💾", "callback_data": f"save:{job.id}:{page}"},
            {"text": "🙈", "callback_data": f"ignore:{job.id}:{page}"},
            {"text": "🔗 Open", "url": job.url},
            {"text": "✅", "callback_data": f"applied:{job.id}:{page}"},
        ])

    nav: list[dict] = []
    if page > 1:
        nav.append({"text": "⬅️ Prev", "callback_data": f"page:{page - 1}"})
    nav.append({"text": f"Page {page}/{total_pages}", "callback_data": "noop"})
    if page < total_pages:
        nav.append({"text": "Next ➡️", "callback_data": f"page:{page + 1}"})
    rows.append(nav)
    return {"inline_keyboard": rows}


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
