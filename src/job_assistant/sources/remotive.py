"""Remotive source (https://remotive.com/api/remote-jobs).

Official public JSON API for remote jobs. All listings are remote.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from ..config import RemotiveConfig
from ..models import Job
from .base import Source

API_URL = "https://remotive.com/api/remote-jobs"
_TAG_RE = re.compile(r"<[^>]+>")

logger = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse(payload: dict) -> list[Job]:
    """Parse a Remotive API response into Jobs (pure, offline-testable)."""
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        jobs.append(
            Job(
                source="remotive",
                external_id=str(item.get("id", "")),
                title=item.get("title", "").strip(),
                company=item.get("company_name", "").strip(),
                url=item.get("url", "").strip(),
                location=item.get("candidate_required_location", "").strip() or "Remote",
                remote=True,
                posted_at=_parse_date(item.get("publication_date")),
                summary=_strip_html(item.get("description", "")),
            )
        )
    return jobs


class RemotiveSource(Source):
    name = "remotive"

    def __init__(self, config: RemotiveConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        categories = self.config.categories or [None]
        seen: dict[str, Job] = {}
        for category in categories:
            try:
                params: dict[str, str | int] = {"limit": self.config.limit}
                if category:
                    params["category"] = category
                if self.config.search:
                    params["search"] = self.config.search
                payload = self._get(API_URL, params=params).json()
                for job in parse(payload):
                    seen.setdefault(job.dedup_key, job)
            except Exception as exc:  # noqa: BLE001 - one bad category mustn't drop the source
                logger.warning("remotive category %s failed: %s", category, exc)
                continue
        return list(seen.values())
