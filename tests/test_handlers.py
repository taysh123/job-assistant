"""Tests for Telegram update handling (callbacks + commands)."""

from __future__ import annotations

from job_assistant.config import Config
from job_assistant.models import JobStatus
from job_assistant.telegram.handlers import (
    OFFSET_KEY,
    handle_update,
    process_updates,
)
from tests.conftest import FakeTelegramClient, make_job


def _callback_update(update_id: int, data: str, message_id: int = 500):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cq{update_id}",
            "data": data,
            "message": {"message_id": message_id, "chat": {"id": 1}},
        },
    }


def _command_update(update_id: int, text: str):
    return {
        "update_id": update_id,
        "message": {"text": text, "chat": {"id": 1}},
    }


def test_callback_save_updates_status_and_edits_card(repo):
    job = repo.insert_new_jobs([make_job(external_id="1")])[0]
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _callback_update(1, f"save:{job.id}"))
    assert repo.get_job(job.id).status is JobStatus.SAVED
    assert client.answered == ["cq1"]
    assert len(client.edits) == 1  # card edited to reflect Saved


def test_callback_applied(repo):
    job = repo.insert_new_jobs([make_job(external_id="1")])[0]
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _callback_update(2, f"applied:{job.id}"))
    assert repo.get_job(job.id).status is JobStatus.APPLIED


def test_callback_unknown_job(repo):
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _callback_update(3, "save:9999"))
    assert client.answered == ["cq3"]
    assert client.edits == []


def test_command_help(repo):
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _command_update(4, "/help"))
    assert "Commands" in client.sent[0]["text"]


def test_command_stats(repo):
    repo.insert_new_jobs([make_job(external_id="1")])
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _command_update(5, "/stats"))
    assert "Stats" in client.sent[0]["text"]


def test_command_config_lists_sources(repo):
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _command_update(6, "/config"))
    assert "Current config" in client.sent[0]["text"]


def test_command_saved_lists_saved_jobs(repo):
    job = repo.insert_new_jobs([make_job(external_id="1", title="Saved Role")])[0]
    repo.set_status(job.id, JobStatus.SAVED)
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _command_update(7, "/saved"))
    assert "Saved Role" in client.sent[0]["text"]


def test_process_updates_advances_offset(repo):
    job = repo.insert_new_jobs([make_job(external_id="1")])[0]
    client = FakeTelegramClient()
    updates = [
        _command_update(10, "/help"),
        _callback_update(11, f"save:{job.id}"),
    ]
    client.updates = updates
    n = process_updates(client, repo, Config())
    assert n == 2
    # Offset stored as last update_id + 1.
    assert repo.get_state(OFFSET_KEY) == "12"


def test_command_at_mention_stripped(repo):
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _command_update(8, "/stats@my_bot"))
    assert "Stats" in client.sent[0]["text"]
