"""Core domain models shared across the application."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle status of a tracked job."""

    NEW = "new"
    SAVED = "saved"
    IGNORED = "ignored"
    OPENED = "opened"
    APPLIED = "applied"


# Statuses a user can set via Telegram callback actions.
ACTIONABLE_STATUSES = {JobStatus.SAVED, JobStatus.IGNORED, JobStatus.APPLIED, JobStatus.OPENED}


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").strip().lower())


def compute_dedup_key(source: str, external_id: str, *, title: str = "", company: str = "", url: str = "") -> str:
    """Stable identity for a posting.

    Prefer (source, external_id); fall back to a normalized
    title+company+url hash when a source lacks a reliable id.
    """
    if external_id:
        basis = f"{source}::{external_id}"
    else:
        basis = f"{source}::{_normalize(title)}::{_normalize(company)}::{_normalize(url)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


@dataclass
class Job:
    """A normalized job posting.

    Sources produce these; the filter engine annotates ``score`` and
    ``match_reasons``; the repository persists them and assigns ``status``.
    """

    source: str
    external_id: str
    title: str
    company: str
    url: str
    location: str = ""
    remote: bool = False
    posted_at: datetime | None = None
    summary: str = ""

    # Populated by the filter engine.
    score: int = 0
    match_reasons: list[str] = field(default_factory=list)

    # Populated by the persistence layer.
    id: int | None = None
    status: JobStatus = JobStatus.NEW

    @property
    def dedup_key(self) -> str:
        return compute_dedup_key(
            self.source,
            self.external_id,
            title=self.title,
            company=self.company,
            url=self.url,
        )
