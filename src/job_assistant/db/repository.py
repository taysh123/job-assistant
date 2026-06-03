"""SQLite persistence layer.

All database access goes through ``Repository``. It owns the connection,
maps rows to :class:`~job_assistant.models.Job`, and exposes the queries the
rest of the app needs (insert-new, status transitions, listings, stats).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..models import Job, JobStatus

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row: sqlite3.Row) -> Job:
    posted = row["posted_at"]
    return Job(
        id=row["id"],
        source=row["source"],
        external_id=row["external_id"],
        title=row["title"],
        company=row["company"],
        url=row["url"],
        location=row["location"],
        remote=bool(row["remote_flag"]),
        posted_at=datetime.fromisoformat(posted) if posted else None,
        summary=row["summary"],
        score=row["score"],
        match_reasons=json.loads(row["match_reasons"] or "[]"),
        status=JobStatus(row["status"]),
    )


class Repository:
    """Thin, well-tested wrapper around a SQLite connection."""

    def __init__(self, db_path: str | Path = "data/jobs.db"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

    # --- lifecycle -------------------------------------------------------

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # --- dedup / insert --------------------------------------------------

    def existing_dedup_keys(self, keys: list[str]) -> set[str]:
        """Return the subset of ``keys`` already present in the DB."""
        if not keys:
            return set()
        found: set[str] = set()
        # Chunk to stay well under SQLite's variable limit.
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT dedup_key FROM jobs WHERE dedup_key IN ({placeholders})",
                chunk,
            ).fetchall()
            found.update(r["dedup_key"] for r in rows)
        return found

    def insert_new_jobs(self, jobs: list[Job]) -> list[Job]:
        """Insert jobs not already seen. Returns inserted jobs with ids set."""
        now = _utcnow()
        inserted: list[Job] = []
        for job in jobs:
            posted = job.posted_at.isoformat() if job.posted_at else None
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    dedup_key, source, external_id, title, company, location,
                    remote_flag, url, posted_at, summary, match_reasons, score,
                    status, first_seen_at, last_status_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job.dedup_key, job.source, job.external_id, job.title, job.company,
                    job.location, int(job.remote), job.url, posted, job.summary,
                    json.dumps(job.match_reasons), job.score, JobStatus.NEW.value, now, now,
                ),
            )
            if cur.rowcount:  # actually inserted (not ignored as duplicate)
                job.id = cur.lastrowid
                job.status = JobStatus.NEW
                inserted.append(job)
        self.conn.commit()
        return inserted

    # --- status / lookups ------------------------------------------------

    def get_job(self, job_id: int) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def set_status(self, job_id: int, status: JobStatus) -> bool:
        cur = self.conn.execute(
            "UPDATE jobs SET status = ?, last_status_at = ? WHERE id = ?",
            (status.value, _utcnow(), job_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_message_id(self, job_id: int, message_id: int) -> None:
        self.conn.execute(
            "UPDATE jobs SET telegram_message_id = ? WHERE id = ?",
            (message_id, job_id),
        )
        self.conn.commit()

    def list_by_status(self, status: JobStatus, limit: int = 25) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY first_seen_at DESC LIMIT ?",
            (status.value, limit),
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_since(self, since_iso: str, limit: int = 100) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE first_seen_at >= ? ORDER BY score DESC, first_seen_at DESC LIMIT ?",
            (since_iso, limit),
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    # --- stats -----------------------------------------------------------

    def status_counts(self, since_iso: str | None = None) -> dict[str, int]:
        if since_iso:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) c FROM jobs WHERE first_seen_at >= ? GROUP BY status",
                (since_iso,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) c FROM jobs GROUP BY status"
            ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def source_counts(self, since_iso: str | None = None) -> dict[str, int]:
        if since_iso:
            rows = self.conn.execute(
                "SELECT source, COUNT(*) c FROM jobs WHERE first_seen_at >= ? GROUP BY source ORDER BY c DESC",
                (since_iso,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT source, COUNT(*) c FROM jobs GROUP BY source ORDER BY c DESC"
            ).fetchall()
        return {r["source"]: r["c"] for r in rows}

    def match_reasons_since(self, since_iso: str) -> list[str]:
        """Flattened match reasons across jobs first seen since ``since_iso``."""
        rows = self.conn.execute(
            "SELECT match_reasons FROM jobs WHERE first_seen_at >= ?",
            (since_iso,),
        ).fetchall()
        reasons: list[str] = []
        for r in rows:
            reasons.extend(json.loads(r["match_reasons"] or "[]"))
        return reasons

    # --- runs ------------------------------------------------------------

    def record_run(self, kind: str, counts: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO runs (kind, ran_at, counts) VALUES (?,?,?)",
            (kind, _utcnow(), json.dumps(counts or {})),
        )
        self.conn.commit()

    def last_run_at(self, kind: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT ran_at FROM runs WHERE kind = ? ORDER BY ran_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
        return datetime.fromisoformat(row["ran_at"]) if row else None

    # --- bot_state -------------------------------------------------------

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()
