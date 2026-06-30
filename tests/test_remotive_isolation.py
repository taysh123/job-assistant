"""Per-source error isolation for RemotiveSource.

One failing category request must be logged and skipped, not abort the
whole ``collect()`` loop (which would drop every other category's jobs and
return ``[]`` via ``_safe_collect``).
"""

from __future__ import annotations

import requests

from job_assistant.config import RemotiveConfig
from job_assistant.sources.remotive import RemotiveSource


class _FakeResp:
    def __init__(self, p):
        self._p = p

    def json(self):
        return self._p


_GOOD_PAYLOAD = {
    "jobs": [
        {
            "id": 4242,
            "title": "Backend Engineer",
            "company_name": "Acme",
            "url": "https://remotive.com/jobs/4242",
            "candidate_required_location": "Worldwide",
            "publication_date": "2026-06-29T08:00:00",
            "description": "<p>Build and ship backend APIs.</p>",
        }
    ]
}


def test_one_bad_category_does_not_drop_the_source(monkeypatch):
    """A single failing category is skipped; the good category still returns."""
    src = RemotiveSource(RemotiveConfig(enabled=True, categories=["bad", "good"]))

    def fake_get(url, **kwargs):
        category = kwargs["params"]["category"]
        if category == "bad":
            raise requests.HTTPError("500")
        return _FakeResp(_GOOD_PAYLOAD)

    monkeypatch.setattr(src, "_get", fake_get)

    jobs = src.collect()

    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
