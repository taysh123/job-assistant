"""Smoke tests for the CLI entrypoints (no network)."""

from __future__ import annotations

import sqlite3

from job_assistant.cli import main


def test_init_db_creates_schema(tmp_path, capsys):
    db = tmp_path / "jobs.db"
    rc = main(["--db", str(db), "init-db"])
    assert rc == 0
    assert db.exists()
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"jobs", "runs", "bot_state"} <= tables


def test_reset_seen_jobs_command(tmp_path, capsys):
    from job_assistant.db.repository import Repository
    from job_assistant.models import JobStatus
    from tests.conftest import make_job

    db = tmp_path / "jobs.db"
    with Repository(str(db)) as repo:
        repo.init_schema()
        jobs = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
        repo.set_status(jobs[0].id, JobStatus.SAVED)

    rc = main(["--db", str(db), "reset-seen-jobs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cleared 1" in out
    assert "kept 1" in out

    with Repository(str(db)) as repo:
        assert repo.status_counts() == {"saved": 1}


def test_collect_dry_run_offline(tmp_path, monkeypatch, capsys):
    # No sources enabled -> no network; exercises the full wiring.
    monkeypatch.setattr("job_assistant.pipeline.collect_all", lambda cfg: [])
    db = tmp_path / "jobs.db"
    rc = main(["--db", str(db), "--config", "config/config.example.yaml", "collect", "--dry-run"])
    assert rc == 0
    assert "Collect:" in capsys.readouterr().out


def test_test_telegram_sends_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    sent = {}

    def fake_send(self, text, **kwargs):
        sent["text"] = text
        return {"message_id": 1}

    monkeypatch.setattr("job_assistant.cli.TelegramClient.send_message", fake_send)
    rc = main(["test-telegram"])
    assert rc == 0
    assert "Job Assistant v1" in sent["text"]
    assert "Telegram integration is working" in sent["text"]
    assert "UTC" in sent["text"]  # timestamp present


def test_test_job_card_sends_card_with_buttons(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    captured = {}

    def fake_send(self, text, *, reply_markup=None, **kwargs):
        captured["text"] = text
        captured["reply_markup"] = reply_markup
        return {"message_id": 1}

    monkeypatch.setattr("job_assistant.cli.TelegramClient.send_message", fake_send)
    rc = main(["test-job-card"])
    assert rc == 0
    # Core fields present (production formatting).
    assert "Senior Backend Engineer" in captured["text"]
    assert "Acme Cloud" in captured["text"]
    assert "Remote (Europe)" in captured["text"]
    assert "remotive" in captured["text"]
    # Same production buttons.
    rows = captured["reply_markup"]["inline_keyboard"]
    assert rows[0][0]["callback_data"].startswith("save:")
    assert rows[0][1]["callback_data"].startswith("ignore:")
    assert rows[1][0]["url"]  # Open
    assert rows[1][1]["callback_data"].startswith("applied:")


def test_test_telegram_without_secrets_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("job_assistant.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert main(["test-telegram"]) == 1


def test_process_updates_without_secrets_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("job_assistant.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    db = tmp_path / "jobs.db"
    rc = main(["--db", str(db), "process-updates"])
    assert rc == 0
