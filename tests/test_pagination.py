"""Digest pagination: page math + nav/action flow through the handlers."""

from __future__ import annotations

from job_assistant.config import Config
from job_assistant.telegram.digest import send_digest
from job_assistant.telegram.handlers import handle_update
from job_assistant.telegram.pagination import load_digest, page_slice
from tests.conftest import FakeTelegramClient, make_job


def test_page_slice_math_and_clamping():
    ids = list(range(1, 13))  # 12 ids
    assert page_slice(ids, 1, 5) == ([1, 2, 3, 4, 5], 3)
    assert page_slice(ids, 3, 5)[0] == [11, 12]
    assert page_slice(ids, 99, 5)[0] == [11, 12]  # clamp beyond last page
    assert page_slice([], 1, 5) == ([], 1)


def _seed(repo, n):
    return repo.insert_new_jobs([make_job(external_id=str(i), title=f"Role {i}") for i in range(n)])


def _cb(update_id, data, message_id):
    return {
        "update_id": update_id,
        "callback_query": {"id": f"c{update_id}", "data": data,
                           "message": {"message_id": message_id, "chat": {"id": 1}}},
    }


def test_send_digest_saves_state_and_renders_page_one(repo):
    jobs = _seed(repo, 7)
    client = FakeTelegramClient()
    assert send_digest(client, repo, jobs, page_size=5) == 1
    assert len(client.sent) == 1 and len(client.edits) == 1
    mid = client.sent[0]["message_id"]
    state = load_digest(repo, mid)
    assert state["page_size"] == 5 and len(state["job_ids"]) == 7
    assert "page 1/2" in client.edits[0]["text"]


def test_next_button_edits_same_message_to_page_two(repo):
    client = FakeTelegramClient()
    send_digest(client, repo, _seed(repo, 7), page_size=5)
    mid = client.sent[0]["message_id"]
    client.edits.clear()
    handle_update(client, repo, Config(), _cb(1, "page:2", mid))
    assert client.answered == ["c1"]
    assert client.edits[-1]["message_id"] == mid
    assert "page 2/2" in client.edits[-1]["text"]


def test_action_updates_status_and_keeps_current_page(repo):
    client = FakeTelegramClient()
    jobs = _seed(repo, 7)
    send_digest(client, repo, jobs, page_size=5)
    mid = client.sent[0]["message_id"]
    target = jobs[5].id  # 6th job -> lives on page 2
    client.edits.clear()
    handle_update(client, repo, Config(), _cb(2, f"applied:{target}:2", mid))
    assert repo.get_job(target).status.value == "applied"
    # Stayed on page 2 and reflects the new status.
    assert "page 2/2" in client.edits[-1]["text"]
    assert "✅" in client.edits[-1]["text"]


def test_noop_button_answers_without_editing(repo):
    client = FakeTelegramClient()
    send_digest(client, repo, _seed(repo, 3), page_size=5)
    client.edits.clear()
    handle_update(client, repo, Config(), _cb(3, "noop", client.sent[0]["message_id"]))
    assert client.answered[-1] == "c3"
    assert client.edits == []


def test_nav_on_unknown_message_reports_expired(repo):
    client = FakeTelegramClient()
    handle_update(client, repo, Config(), _cb(4, "page:2", 999999))
    assert client.answered == ["c4"]
    assert client.edits == []


def test_pagination_self_heals_when_digest_state_lost(repo):
    """If the digest:{mid} bot_state row is gone (e.g. a dropped commit), paging
    rebuilds the job list from each job's persisted telegram_message_id instead
    of dead-ending on 'Digest expired'. This is what makes Prev/Next robust."""
    client = FakeTelegramClient()
    send_digest(client, repo, _seed(repo, 3), page_size=1)  # 3 single-job pages
    mid = client.sent[0]["message_id"]
    # Simulate the lost cross-run state.
    repo.conn.execute("DELETE FROM bot_state WHERE key = ?", (f"digest:{mid}",))
    repo.conn.commit()
    client.edits.clear()
    handle_update(client, repo, Config(), _cb(5, "page:2", mid))
    assert client.answered == ["c5"]
    assert client.edits and client.edits[-1]["message_id"] == mid
    assert "page 2/3" in client.edits[-1]["text"]


def test_digest_paginates_across_separate_repository_instances(tmp_path):
    """A digest written by one process (collect) must be paginable by a later,
    separate process (bot) reading the committed single-file DB."""
    from job_assistant.db.repository import Repository

    db = tmp_path / "jobs.db"
    repo_a = Repository(str(db))
    repo_a.init_schema()
    jobs = repo_a.insert_new_jobs(
        [make_job(external_id=str(i), title=f"Role {i}") for i in range(7)]
    )
    client_a = FakeTelegramClient()
    send_digest(client_a, repo_a, jobs, page_size=1)
    mid = client_a.sent[0]["message_id"]
    repo_a.close()  # commit boundary between the two cron runs

    repo_b = Repository(str(db))
    repo_b.init_schema()
    client_b = FakeTelegramClient()
    handle_update(client_b, repo_b, Config(), _cb(1, "page:2", mid))
    repo_b.close()
    assert client_b.edits and "page 2/7" in client_b.edits[-1]["text"]
