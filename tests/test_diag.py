"""Wave A: funnel diagnostics — repo.recent_runs() and the /diag command."""

from __future__ import annotations

from job_assistant.config import Config
from job_assistant.telegram.handlers import handle_command
from tests.conftest import FakeTelegramClient, make_job


def test_recent_runs_returns_newest_first_with_parsed_counts(repo):
    repo.record_run("collect", {"collected": 50, "matched": 5, "new": 1, "sent": 1})
    repo.record_run("collect", {"collected": 80, "matched": 9, "new": 4, "sent": 4})
    runs = repo.recent_runs("collect", limit=5)
    assert len(runs) == 2
    assert runs[0]["counts"]["collected"] == 80   # newest first (by insertion id)
    assert runs[1]["counts"]["matched"] == 5


def test_diag_command_shows_funnel(repo):
    repo.record_run("collect", {"collected": 100, "matched": 12, "new": 3, "sent": 3})
    repo.insert_new_jobs([make_job(external_id="1")])
    client = FakeTelegramClient()
    handle_command(client, repo, Config(), "/diag", chat_id="1")
    text = client.sent[-1]["text"]
    assert "Diagnostics" in text
    assert "100" in text and "→" in text
