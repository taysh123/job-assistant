"""Wave 0 FIX B: GreenhouseSource isolates a failing board (one bad slug must
not drop the whole source)."""

from __future__ import annotations

import requests

from job_assistant.config import GreenhouseConfig
from job_assistant.sources.greenhouse import GreenhouseSource


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_greenhouse_skips_failing_board(monkeypatch):
    src = GreenhouseSource(GreenhouseConfig(enabled=True, boards=["bad", "good"]))

    def fake_get(url, **kwargs):
        if "bad" in url:
            raise requests.HTTPError("404 Not Found")
        return _FakeResp({"jobs": [{
            "id": 1,
            "title": "Backend Engineer",
            "absolute_url": "https://x/1",
            "location": {"name": "Tel Aviv"},
            "content": "<p>Build things</p>",
        }]})

    monkeypatch.setattr(src, "_get", fake_get)
    jobs = src.collect()
    assert [j.title for j in jobs] == ["Backend Engineer"]
