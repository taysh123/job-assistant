"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from job_assistant.db.repository import Repository
from job_assistant.models import Job


@pytest.fixture
def repo() -> Repository:
    r = Repository(":memory:")
    r.init_schema()
    yield r
    r.close()


class FakeTelegramClient:
    """In-memory stand-in for TelegramClient used in tests (no network)."""

    def __init__(self):
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.answered: list[str] = []
        self.updates: list[dict] = []
        self._next_id = 1000

    def get_updates(self, offset=None, timeout=0):
        return self.updates

    def send_message(self, text, *, reply_markup=None, disable_preview=True, chat_id=None):
        self._next_id += 1
        self.sent.append({"text": text, "reply_markup": reply_markup, "message_id": self._next_id})
        return {"message_id": self._next_id}

    def edit_message_text(self, message_id, text, *, reply_markup=None, chat_id=None):
        self.edits.append({"message_id": message_id, "text": text, "reply_markup": reply_markup})
        return {"message_id": message_id}

    def answer_callback_query(self, callback_query_id, text=""):
        self.answered.append(callback_query_id)


def make_job(**overrides) -> Job:
    """Build a Job with sensible defaults for tests."""
    defaults = dict(
        source="remotive",
        external_id="123",
        title="Senior Python Engineer",
        company="Acme",
        url="https://example.com/jobs/123",
        location="Remote",
        remote=True,
        posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        summary="We are hiring a backend engineer.",
    )
    defaults.update(overrides)
    return Job(**defaults)
