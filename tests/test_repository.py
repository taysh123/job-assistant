"""Tests for the SQLite persistence layer."""

from __future__ import annotations

from job_assistant.models import JobStatus
from tests.conftest import make_job


def test_init_schema_is_idempotent(repo):
    repo.init_schema()  # second call should not raise
    repo.init_schema()


def test_insert_new_jobs_assigns_ids(repo):
    inserted = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
    assert len(inserted) == 2
    assert all(j.id is not None for j in inserted)
    assert all(j.status is JobStatus.NEW for j in inserted)


def test_insert_skips_duplicates(repo):
    repo.insert_new_jobs([make_job(external_id="1")])
    again = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
    # Only the genuinely new job is returned.
    assert [j.external_id for j in again] == ["2"]


def test_existing_dedup_keys(repo):
    a = make_job(external_id="1")
    b = make_job(external_id="2")
    repo.insert_new_jobs([a])
    found = repo.existing_dedup_keys([a.dedup_key, b.dedup_key])
    assert found == {a.dedup_key}


def test_status_transitions(repo):
    job = repo.insert_new_jobs([make_job(external_id="1")])[0]
    assert repo.set_status(job.id, JobStatus.SAVED) is True
    assert repo.get_job(job.id).status is JobStatus.SAVED
    assert repo.set_status(999, JobStatus.SAVED) is False


def test_list_by_status(repo):
    j1, j2 = repo.insert_new_jobs([make_job(external_id="1"), make_job(external_id="2")])
    repo.set_status(j1.id, JobStatus.SAVED)
    saved = repo.list_by_status(JobStatus.SAVED)
    assert [j.id for j in saved] == [j1.id]


def test_message_id_roundtrip(repo):
    job = repo.insert_new_jobs([make_job(external_id="1")])[0]
    repo.set_message_id(job.id, 555)
    row = repo.conn.execute("SELECT telegram_message_id FROM jobs WHERE id=?", (job.id,)).fetchone()
    assert row["telegram_message_id"] == 555


def test_status_and_source_counts(repo):
    j1, j2 = repo.insert_new_jobs([
        make_job(external_id="1", source="remotive"),
        make_job(external_id="2", source="weworkremotely"),
    ])
    repo.set_status(j1.id, JobStatus.APPLIED)
    assert repo.status_counts() == {"applied": 1, "new": 1}
    assert repo.source_counts() == {"remotive": 1, "weworkremotely": 1}


def test_reset_seen_jobs_keeps_saved_and_applied(repo):
    jobs = repo.insert_new_jobs([
        make_job(external_id="1"),  # new
        make_job(external_id="2"),  # -> saved
        make_job(external_id="3"),  # -> applied
        make_job(external_id="4"),  # -> ignored
    ])
    repo.set_status(jobs[1].id, JobStatus.SAVED)
    repo.set_status(jobs[2].id, JobStatus.APPLIED)
    repo.set_status(jobs[3].id, JobStatus.IGNORED)

    result = repo.reset_seen_jobs()
    assert result == {"deleted": 2, "kept": 2}  # new + ignored cleared

    remaining = repo.status_counts()
    assert remaining == {"saved": 1, "applied": 1}


def test_reset_seen_jobs_makes_jobs_resendable(repo):
    from job_assistant.filtering.dedup import filter_unseen

    a = make_job(external_id="1")
    repo.insert_new_jobs([a])
    # Already seen -> not eligible.
    assert filter_unseen([a], repo) == []
    repo.reset_seen_jobs()
    # After reset -> eligible again.
    assert [j.external_id for j in filter_unseen([a], repo)] == ["1"]


def test_reset_seen_jobs_empty_db(repo):
    assert repo.reset_seen_jobs() == {"deleted": 0, "kept": 0}


def test_bot_state_kv(repo):
    assert repo.get_state("offset") is None
    repo.set_state("offset", "42")
    assert repo.get_state("offset") == "42"
    repo.set_state("offset", "99")
    assert repo.get_state("offset") == "99"


def test_record_and_read_runs(repo):
    assert repo.last_run_at("collect") is None
    repo.record_run("collect", {"new": 3})
    assert repo.last_run_at("collect") is not None


def test_match_reasons_roundtrip(repo):
    job = make_job(external_id="1", match_reasons=["title:python", "keyword:backend"])
    repo.insert_new_jobs([job])
    loaded = repo.get_job(job.id)
    assert loaded.match_reasons == ["title:python", "keyword:backend"]
