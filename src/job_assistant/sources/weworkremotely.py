"""We Work Remotely source (public RSS feeds).

Feeds live at https://weworkremotely.com/categories/<slug>.rss
RSS item titles use the form "Company: Job Title".
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import struct_time

import feedparser

from ..config import WeWorkRemotelyConfig
from ..models import Job
from .base import Source

logger = logging.getLogger(__name__)

FEED_URL = "https://weworkremotely.com/categories/{slug}.rss"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def _to_datetime(parsed: struct_time | None) -> datetime | None:
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def _split_title(raw: str) -> tuple[str, str]:
    """"Company: Title" -> (company, title). Falls back gracefully."""
    if ":" in raw:
        company, _, title = raw.partition(":")
        return company.strip(), title.strip()
    return "", raw.strip()


def parse(feed_text: str) -> list[Job]:
    """Parse RSS feed text into Jobs (pure, offline-testable)."""
    parsed = feedparser.parse(feed_text)
    jobs: list[Job] = []
    for entry in parsed.entries:
        company, title = _split_title(entry.get("title", ""))
        link = entry.get("link", "").strip()
        # The numeric id is the last path segment of the listing URL.
        external_id = link.rstrip("/").split("/")[-1] if link else entry.get("id", "")
        region = entry.get("region", "") or entry.get("location", "")
        jobs.append(
            Job(
                source="weworkremotely",
                external_id=external_id,
                title=title,
                company=company,
                url=link,
                location=(region or "Remote").strip(),
                remote=True,
                posted_at=_to_datetime(entry.get("published_parsed")),
                summary=_strip_html(entry.get("summary", "")),
            )
        )
    return jobs


class WeWorkRemotelySource(Source):
    name = "weworkremotely"

    def __init__(self, config: WeWorkRemotelyConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        seen: dict[str, Job] = {}
        for slug in self.config.feeds:
            try:
                text = self._get(FEED_URL.format(slug=slug)).text
                for job in parse(text):
                    seen.setdefault(job.dedup_key, job)
            except Exception as exc:  # noqa: BLE001 - one bad feed mustn't drop the source
                logger.warning("weworkremotely feed %s failed: %s", slug, exc)
                continue
        return list(seen.values())
