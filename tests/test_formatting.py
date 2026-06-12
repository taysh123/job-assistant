"""Tests for Telegram message formatting and keyboards."""

from __future__ import annotations

from datetime import datetime, timezone

from job_assistant.models import JobStatus
from job_assistant.telegram.formatting import (
    digest_keyboard,
    format_digest_header,
    format_digest_page,
    format_job_card,
    format_job_list,
    job_keyboard,
)
from tests.conftest import make_job


def _ided(jobs):
    for i, j in enumerate(jobs, start=1):
        j.id = i
    return jobs


def test_format_digest_page_header_and_compact_cards():
    jobs = _ided([make_job(external_id=str(i), title=f"Role {i}", company="Acme") for i in range(1, 4)])
    text = format_digest_page(
        jobs, page=1, total_pages=2, total_jobs=8,
        run_dt=datetime(2026, 6, 3, 20, 0, tzinfo=timezone.utc), tz="UTC",
    )
    assert "8 new jobs" in text
    assert "page 1/2" in text
    assert "3 on this page" in text
    assert "1. Role 1" in text and "3. Role 3" in text
    # Each numbered card is compact (<= 3 lines): 3 cards -> at most 9 card lines.
    card_block = text.split("\n\n", 1)[1]
    assert len([ln for ln in card_block.splitlines() if ln.strip()]) <= 9


def test_format_digest_page_single_job_per_page():
    job = _ided([make_job(title="Solo Role", company="Acme")])[0]
    text = format_digest_page([job], page=3, total_pages=12, total_jobs=12,
                              run_dt=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert "page 3/12" in text
    assert "on this page" not in text  # redundant clause omitted for one-job pages
    assert "1. Solo Role" in text
    # Prev + Next available mid-list when one job per page.
    nav = digest_keyboard([job], page=3, total_pages=12)["inline_keyboard"][-1]
    nav_data = [b.get("callback_data") for b in nav]
    assert "page:2" in nav_data and "page:4" in nav_data


def test_format_digest_page_uses_configured_timezone():
    job = _ided([make_job()])[0]
    text = format_digest_page([job], page=1, total_pages=1, total_jobs=1,
                              run_dt=datetime(2026, 6, 3, 20, 51, tzinfo=timezone.utc),
                              tz="Asia/Jerusalem")
    assert "23:51" in text  # UTC 20:51 -> IDT 23:51


def test_format_digest_page_escapes_html():
    job = _ided([make_job(title="C++ & <Rust>", company="A&B")])[0]
    text = format_digest_page([job], page=1, total_pages=1, total_jobs=1,
                              run_dt=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert "C++ &amp; &lt;Rust&gt;" in text and "A&amp;B" in text


def test_format_digest_page_shows_status_badge():
    job = _ided([make_job(status=JobStatus.APPLIED)])[0]
    text = format_digest_page([job], page=1, total_pages=1, total_jobs=1,
                              run_dt=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert "✅" in text


def test_compact_card_shows_junior_remote_badges_not_raw_score():
    job = _ided([make_job(title="Junior Backend Developer", remote=True, location="Remote")])[0]
    job.match_reasons = ["title:developer", "junior:junior", "remote"]
    job.score = 14
    text = format_digest_page([job], page=1, total_pages=1, total_jobs=1,
                              run_dt=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert "🟢 Junior" in text     # meaningful fit badge
    assert "🏠 Remote" in text
    assert "⭐" not in text         # raw internal score no longer shown


def test_compact_card_no_junior_badge_for_generic_role():
    job = _ided([make_job(title="Software Engineer", remote=False, location="Tel Aviv")])[0]
    job.match_reasons = ["title:engineer", "boost:tel aviv"]
    text = format_digest_page([job], page=1, total_pages=1, total_jobs=1,
                              run_dt=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert "🟢 Junior" not in text
    assert "🏠 Remote" not in text


def test_digest_keyboard_action_rows_and_nav():
    jobs = _ided([make_job(), make_job()])
    kb = digest_keyboard(jobs, page=2, total_pages=3)
    rows = kb["inline_keyboard"]
    assert len(rows) == 3  # 2 job rows + nav row
    assert rows[0][0]["callback_data"] == "save:1:2"
    assert rows[0][1]["callback_data"] == "ignore:1:2"
    assert rows[0][2]["url"] == jobs[0].url  # Open is a URL button
    assert rows[0][3]["callback_data"] == "applied:1:2"
    nav_texts = [b["text"] for b in rows[-1]]
    nav_data = [b.get("callback_data") for b in rows[-1]]
    assert any("Prev" in t for t in nav_texts)  # page 2 of 3 -> Prev shown
    assert any("Next" in t for t in nav_texts)  # ... and Next shown
    assert "page:1" in nav_data and "page:3" in nav_data and "noop" in nav_data


def test_digest_keyboard_hides_prev_on_first_and_next_on_last():
    jobs = _ided([make_job()])
    nav = digest_keyboard(jobs, page=1, total_pages=1)["inline_keyboard"][-1]
    texts = [b["text"] for b in nav]
    assert not any("Prev" in t for t in texts)
    assert not any("Next" in t for t in texts)
    assert any("Page 1/1" in t for t in texts)


def test_card_contains_core_fields_and_escapes_html():
    job = make_job(title="C++ & <Rust> Engineer", company="A&B", summary="Build <b>things</b>")
    job.match_reasons = ["keyword:rust", "remote"]
    card = format_job_card(job)
    assert "C++ &amp; &lt;Rust&gt; Engineer" in card
    assert "A&amp;B" in card
    assert "&lt;b&gt;things&lt;/b&gt;" in card  # summary HTML neutralized
    assert "Matched:" in card
    assert "rust" in card


def test_card_truncates_summary():
    job = make_job(summary="x" * 500)
    card = format_job_card(job, summary_chars=50)
    assert "…" in card


def test_keyboard_for_new_job_has_actions():
    job = make_job()
    job.id = 7
    kb = job_keyboard(job)
    rows = kb["inline_keyboard"]
    assert rows[0][0]["callback_data"] == "save:7"
    assert rows[0][1]["callback_data"] == "ignore:7"
    assert rows[1][0]["url"] == job.url  # Open is a URL button (instant)
    assert rows[1][1]["callback_data"] == "applied:7"


def test_keyboard_collapses_after_action():
    job = make_job(status=JobStatus.SAVED)
    job.id = 7
    kb = job_keyboard(job)
    assert kb["inline_keyboard"] == [[{"text": "🔗 Open", "url": job.url}]]


def test_digest_header():
    assert "No new" in format_digest_header(0)
    assert "1 new job" in format_digest_header(1)
    assert "3 new jobs" in format_digest_header(3)


def test_job_list_empty_and_populated():
    assert "nothing here yet" in format_job_list("Saved", [])
    out = format_job_list("Saved", [make_job(title="Role A", company="Acme")])
    assert "Role A" in out and "Acme" in out
