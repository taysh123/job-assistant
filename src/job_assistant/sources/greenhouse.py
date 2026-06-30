"""Greenhouse job boards (official public board API).

Endpoint: https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime

from ..config import GreenhouseConfig
from ..models import Job
from .base import Source

API_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
_TAG_RE = re.compile(r"<[^>]+>")

logger = logging.getLogger(__name__)


def _strip_html(content: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(content or ""))).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_remote(location: str) -> bool:
    return "remote" in location.lower()


def parse(payload: dict, board: str = "") -> list[Job]:
    """Parse a Greenhouse board response into Jobs (pure, offline-testable)."""
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        location = (item.get("location") or {}).get("name", "").strip()
        jobs.append(
            Job(
                source="greenhouse",
                external_id=str(item.get("id", "")),
                title=item.get("title", "").strip(),
                company=board,
                url=item.get("absolute_url", "").strip(),
                location=location,
                remote=_is_remote(location),
                posted_at=_parse_date(item.get("updated_at")),
                summary=_strip_html(item.get("content", "")),
            )
        )
    return jobs


class GreenhouseSource(Source):
    name = "greenhouse"

    def __init__(self, config: GreenhouseConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        jobs: list[Job] = []
        for board in self.config.boards:
            try:
                payload = self._get(
                    API_URL.format(board=board), params={"content": "true"}
                ).json()
                jobs.extend(parse(payload, board=board))
            except Exception as exc:  # noqa: BLE001 - one bad board mustn't drop the source
                logger.warning("greenhouse board %s failed: %s", board, exc)
        return jobs
