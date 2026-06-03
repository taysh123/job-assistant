"""LinkedIn email-ingestion source: offline parse + registry wiring."""

from __future__ import annotations

from pathlib import Path

from job_assistant.config import Config, Secrets
from job_assistant.sources.linkedin_email import parse
from job_assistant.sources.registry import build_sources

FIXTURE = Path(__file__).parent / "fixtures" / "linkedin_alert.html"


def test_parse_extracts_jobs_and_skips_non_job_links():
    jobs = parse(FIXTURE.read_text(encoding="utf-8"))
    # The "Apply now" duplicate, "See all jobs" and "Unsubscribe" are excluded.
    assert len(jobs) == 2
    a, b = jobs

    assert a.source == "linkedin"
    assert a.external_id == "3812345678"
    assert a.title == "Junior Software Engineer"
    assert a.url == "https://www.linkedin.com/jobs/view/3812345678/"  # cleaned, no tracking
    assert a.company == "Acme Cloud"
    assert "Tel Aviv" in a.location
    assert a.remote is False

    assert b.external_id == "3899999999"
    assert b.title == "Backend Developer & API (Junior)"  # HTML entity unescaped
    assert b.company == "Globex"
    assert b.remote is True  # "Remote (Israel)"


def test_parse_dedupes_and_handles_empty():
    assert parse("") == []
    assert parse("<p>no jobs here</p>") == []


def test_parse_dedup_keys_are_stable_and_unique():
    jobs = parse(FIXTURE.read_text(encoding="utf-8"))
    again = parse(FIXTURE.read_text(encoding="utf-8"))
    assert jobs[0].dedup_key == again[0].dedup_key
    assert jobs[0].dedup_key != jobs[1].dedup_key


def _config(enabled: bool) -> Config:
    cfg = Config()
    cfg.sources.linkedin.enabled = enabled
    return cfg


def test_registry_adds_linkedin_only_when_enabled_and_creds_present():
    creds = Secrets(imap_username="u@x.com", imap_password="pw")
    names = {s.name for s in build_sources(_config(True), creds)}
    assert "linkedin" in names

    # Enabled but no IMAP creds -> skipped (safe).
    assert "linkedin" not in {s.name for s in build_sources(_config(True), Secrets())}
    # Disabled -> skipped even with creds.
    assert "linkedin" not in {s.name for s in build_sources(_config(False), creds)}
    # No secrets object at all -> skipped.
    assert "linkedin" not in {s.name for s in build_sources(_config(True), None)}
