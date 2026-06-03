"""Comeet source (public Careers API) — common ATS among Israeli companies.

Endpoint: https://www.comeet.co/careers-api/2.0/company/<uid>/positions?token=<token>
Each company exposes a public UID + token (Settings → Careers Website → Careers API
on the company side). Opt-in; configure one entry per company.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from ..config import ComeetConfig
from ..models import Job
from .base import Source

logger = logging.getLogger(__name__)

API_URL = "https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", value or "")).strip()


def _details_text(details) -> str:
    if not isinstance(details, list):
        return ""
    return _strip_html(" ".join(d.get("value", "") for d in details if isinstance(d, dict)))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse(payload: list, company: str = "") -> list[Job]:
    """Parse a Comeet positions response into Jobs (pure, offline-testable)."""
    jobs: list[Job] = []
    for item in payload:
        location = ((item.get("location") or {}).get("name") or "").strip()
        workplace = (item.get("workplace_type") or "").strip()
        remote = workplace.lower() == "remote" or "remote" in location.lower()
        jobs.append(Job(
            source="comeet",
            external_id=str(item.get("uid", "")),
            title=(item.get("name") or "").strip(),
            company=company or (item.get("company_name") or "").strip(),
            url=(item.get("url_comeet_hosted_page") or item.get("url_active_page") or "").strip(),
            location=location,
            remote=remote,
            posted_at=_parse_dt(item.get("time_updated")),
            summary=_details_text(item.get("details")),
        ))
    return jobs


class ComeetSource(Source):
    name = "comeet"

    def __init__(self, config: ComeetConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        jobs: list[Job] = []
        for company in self.config.companies:
            try:
                payload = self._get(
                    API_URL.format(uid=company.uid),
                    params={"token": company.token, "details": "true"},
                ).json()
                jobs.extend(parse(payload, company=company.name))
            except Exception as exc:  # noqa: BLE001 - one bad company must not drop the rest
                logger.warning("comeet company %s failed: %s", company.uid, exc)
        return jobs
