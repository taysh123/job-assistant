"""Source interface.

A source knows how to **fetch** raw payloads from an external service and
**parse** them into :class:`~job_assistant.models.Job` objects. The two steps
are deliberately separate so parsing can be unit-tested offline against saved
fixtures, with no network access.

``collect()`` ties them together and must never raise: a misbehaving source is
logged and skipped so it can't break the whole run.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from ..models import Job

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20
USER_AGENT = "job-assistant/1.0 (+https://github.com/) personal-use"


class Source(ABC):
    """Base class for all job sources."""

    #: Stable identifier stored on every Job and used for dedup + stats.
    name: str = "base"

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)

    @abstractmethod
    def collect(self) -> list[Job]:
        """Fetch and parse postings. Returns [] on failure (never raises)."""
        raise NotImplementedError

    # Helpers ------------------------------------------------------------

    def _get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        resp = self._session.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def _safe_collect(self, fetch_and_parse) -> list[Job]:
        """Run ``fetch_and_parse`` guarding against any exception."""
        try:
            return fetch_and_parse()
        except Exception as exc:  # noqa: BLE001 - sources must not break the run
            logger.warning("source %s failed: %s", self.name, exc)
            return []
