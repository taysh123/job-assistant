"""Deduplication helpers.

Two layers:
  * ``dedup_in_batch`` removes duplicates *within* a single collection run
    (e.g. the same posting returned by two feeds).
  * ``filter_unseen`` drops postings already stored in the database.
"""

from __future__ import annotations

from ..db.repository import Repository
from ..models import Job


def dedup_in_batch(jobs: list[Job]) -> list[Job]:
    """Keep the first occurrence of each dedup_key in this batch."""
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        key = job.dedup_key
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def filter_unseen(jobs: list[Job], repo: Repository) -> list[Job]:
    """Return only jobs whose dedup_key is not already persisted."""
    batch = dedup_in_batch(jobs)
    existing = repo.existing_dedup_keys([j.dedup_key for j in batch])
    return [j for j in batch if j.dedup_key not in existing]
