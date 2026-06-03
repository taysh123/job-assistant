"""Tests for the weekly summary."""

from __future__ import annotations

from job_assistant.models import JobStatus
from job_assistant.summary.weekly import build_weekly_summary
from tests.conftest import make_job


def test_weekly_summary_counts_and_keywords(repo):
    jobs = repo.insert_new_jobs([
        make_job(external_id="1", source="remotive", match_reasons=["keyword:python", "remote"]),
        make_job(external_id="2", source="remotive", match_reasons=["keyword:python"]),
        make_job(external_id="3", source="lever", match_reasons=["keyword:rust"]),
    ])
    repo.set_status(jobs[0].id, JobStatus.SAVED)
    repo.set_status(jobs[1].id, JobStatus.APPLIED)

    text = build_weekly_summary(repo)
    assert "New jobs found: <b>3</b>" in text
    assert "Saved: 1" in text
    assert "Applied: 1" in text
    # python appears twice -> ranked first; remote excluded from keywords.
    assert "python (2)" in text
    assert "remote (" not in text
    assert "remotive (2)" in text


def test_weekly_summary_empty(repo):
    text = build_weekly_summary(repo)
    assert "New jobs found: <b>0</b>" in text
    assert "Top keywords: —" in text
