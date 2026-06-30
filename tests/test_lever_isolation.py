"""Per-source error isolation for the Lever source.

One board returning 404 must NOT abort the whole loop: the failing board is
logged and skipped while healthy boards still return their postings.
"""

from __future__ import annotations

import requests

from job_assistant.config import LeverConfig
from job_assistant.sources.lever import LeverSource


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_one_bad_board_does_not_drop_the_source(monkeypatch):
    src = LeverSource(LeverConfig(enabled=True, boards=["bad", "good"]))

    good_payload = [
        {
            "id": "abc-123",
            "text": "Full Stack Engineer",
            "hostedUrl": "https://jobs.lever.co/good/abc-123",
            "categories": {"location": "Remote - US"},
            "createdAt": 1700000000000,  # epoch ms
            "descriptionPlain": "Build full stack things.",
        }
    ]

    def fake_get(url, **kwargs):
        # The board slug is embedded in the request URL.
        if "bad" in url:
            raise requests.HTTPError("404 Not Found")
        return _FakeResp(good_payload)

    monkeypatch.setattr(src, "_get", fake_get)

    jobs = src.collect()

    assert len(jobs) == 1
    assert jobs[0].title == "Full Stack Engineer"
    assert jobs[0].company == "good"
