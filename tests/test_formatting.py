"""Tests for Telegram message formatting and keyboards."""

from __future__ import annotations

from job_assistant.models import JobStatus
from job_assistant.telegram.formatting import (
    format_digest_header,
    format_job_card,
    format_job_list,
    job_keyboard,
)
from tests.conftest import make_job


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
