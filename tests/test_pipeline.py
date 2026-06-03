"""Tests for the collection pipeline and digest sending."""

from __future__ import annotations

from job_assistant.config import Config
from job_assistant.pipeline import run_collection
from job_assistant.telegram.digest import send_digest
from tests.conftest import FakeTelegramClient, make_job


def test_send_digest_sends_one_paginated_message(repo):
    jobs = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
    client = FakeTelegramClient()
    sent = send_digest(client, repo, jobs, page_size=5)
    assert sent == 1
    assert len(client.sent) == 1   # ONE message, not one-per-job
    assert len(client.edits) == 1  # page 1 rendered in place
    for job in jobs:
        row = repo.conn.execute(
            "SELECT telegram_message_id FROM jobs WHERE id=?", (job.id,)
        ).fetchone()
        assert row["telegram_message_id"] is not None


def test_send_digest_empty(repo):
    client = FakeTelegramClient()
    assert send_digest(client, repo, []) == 0
    assert len(client.sent) == 1  # just the "no new jobs" header
    assert client.edits == []


def test_run_collection_dry_run_filters_dedups_persists(repo, monkeypatch):
    config = Config()
    config.filters.keywords_allow = ["python"]

    batch = [
        make_job(external_id="1", title="Python Engineer", summary="python"),
        make_job(external_id="2", title="Sales Lead", summary="quota"),  # filtered out
        make_job(external_id="1", title="Python Engineer", summary="python"),  # dup in batch
    ]
    monkeypatch.setattr("job_assistant.pipeline.collect_all", lambda cfg, secrets=None: list(batch))

    counts = run_collection(config, secrets=None_secrets(), repo=repo, send=False)
    assert counts == {"collected": 3, "matched": 2, "new": 1, "sent": 0}

    # Second run with the same batch -> nothing new (DB dedup).
    counts2 = run_collection(config, secrets=None_secrets(), repo=repo, send=False)
    assert counts2["new"] == 0


def None_secrets():
    from job_assistant.config import Secrets

    return Secrets()
