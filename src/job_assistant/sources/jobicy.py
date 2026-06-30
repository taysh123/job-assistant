"""Jobicy remote-jobs aggregator (official public API, keyless).

Endpoint: https://jobicy.com/api/v2/remote-jobs?count=<N>&geo=<geo>&industry=<industry>
All listings are remote; geo "israel" returns EMEA/Anywhere roles open to an
Israel-based applicant.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime

from ..config import JobicyConfig
from ..models import Job
from .base import Source

API_URL = "https://jobicy.com/api/v2/remote-jobs"
_TAG_RE = re.compile(r"<[^>]+>")

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse(payload: dict) -> list[Job]:
    """Parse a Jobicy API response into Jobs (pure, offline-testable)."""
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        jobs.append(
            Job(
                source="jobicy",
                external_id=str(item.get("id", "")),
                title=(item.get("jobTitle") or "").strip(),
                company=(item.get("companyName") or "").strip(),
                url=(item.get("url") or "").strip(),
                location=(item.get("jobGeo") or "").strip(),
                remote=True,  # every Jobicy listing is remote
                posted_at=_parse_date(item.get("pubDate")),
                summary=_strip_html(item.get("jobExcerpt", "")),
            )
        )
    return jobs


class JobicySource(Source):
    name = "jobicy"

    def __init__(self, config: JobicyConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        params: dict[str, str | int] = {"count": self.config.count}
        if self.config.geo:
            params["geo"] = self.config.geo
        if self.config.industry:
            params["industry"] = self.config.industry
        payload = self._get(API_URL, params=params).json()
        return parse(payload)
