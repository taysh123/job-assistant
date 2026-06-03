"""Tests for the collection pipeline and digest sending."""

from __future__ import annotations

from job_assistant.config import Config
from job_assistant.pipeline import run_collection
from job_assistant.telegram.digest import send_digest
from tests.conftest import FakeTelegramClient, make_job


def test_send_digest_sends_header_and_cards_and_stores_message_ids(repo):
    jobs = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
    client = FakeTelegramClient()
    sent = send_digest(client, repo, jobs)
    assert sent == 2
    # 1 header + 2 cards.
    assert len(client.sent) == 3
    # message ids persisted on the jobs.
    for job in jobs:
        row = repo.conn.execute(
            "SELECT telegram_message_id FROM jobs WHERE id=?", (job.id,)
        ).fetchone()
        assert row["telegram_message_id"] is not None


def test_send_digest_empty(repo):
    client = FakeTelegramClient()
    assert send_digest(client, repo, []) == 0
    assert len(client.sent) == 1  # just the "no new jobs" header


def test_run_collection_dry_run_filters_dedups_persists(repo, monkeypatch):
    config = Config()
    config.filters.keywords_allow = ["python"]

    batch = [
        make_job(external_id="1", title="Python Engineer", summary="python"),
        make_job(external_id="2", title="Sales Lead", summary="quota"),  # filtered out
        make_job(external_id="1", title="Python Engineer", summary="python"),  # dup in batch
    ]
    monkeypatch.setattr("job_assistant.pipeline.collect_all", lambda cfg: list(batch))

    counts = run_collection(config, secrets=None_secrets(), repo=repo, send=False)
    assert counts == {"collected": 3, "matched": 2, "new": 1, "sent": 0}

    # Second run with the same batch -> nothing new (DB dedup).
    counts2 = run_collection(config, secrets=None_secrets(), repo=repo, send=False)
    assert counts2["new"] == 0


def None_secrets():
    from job_assistant.config import Secrets

    return Secrets()
