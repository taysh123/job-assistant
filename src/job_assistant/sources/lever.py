"""Lever job boards (official public postings API).

Endpoint: https://api.lever.co/v0/postings/<company>?mode=json
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import LeverConfig
from ..models import Job
from .base import Source

API_URL = "https://api.lever.co/v0/postings/{board}"


def _parse_ms(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _is_remote(location: str, workplace_type: str) -> bool:
    return workplace_type.lower() == "remote" or "remote" in location.lower()


def parse(payload: list, board: str = "") -> list[Job]:
    """Parse a Lever postings response into Jobs (pure, offline-testable)."""
    jobs: list[Job] = []
    for item in payload:
        categories = item.get("categories") or {}
        location = (categories.get("location") or "").strip()
        workplace_type = item.get("workplaceType", "") or ""
        jobs.append(
            Job(
                source="lever",
                external_id=str(item.get("id", "")),
                title=item.get("text", "").strip(),
                company=board,
                url=item.get("hostedUrl", "").strip(),
                location=location,
                remote=_is_remote(location, workplace_type),
                posted_at=_parse_ms(item.get("createdAt")),
                summary=(item.get("descriptionPlain", "") or "").strip(),
            )
        )
    return jobs


class LeverSource(Source):
    name = "lever"

    def __init__(self, config: LeverConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        jobs: list[Job] = []
        for board in self.config.boards:
            payload = self._get(API_URL.format(board=board), params={"mode": "json"}).json()
            jobs.extend(parse(payload, board=board))
        return jobs
