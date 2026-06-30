"""Per-source error isolation for We Work Remotely (Wave 0 FIX B).

One failing RSS feed must not abort the whole source: good feeds should
still return their jobs. WWR fetches an RSS *string* via ``_get(url).text``
and then runs feedparser on it, so we fake ``_get`` at the instance level.
"""

from __future__ import annotations

from pathlib import Path

import requests

from job_assistant.config import WeWorkRemotelyConfig
from job_assistant.sources.weworkremotely import WeWorkRemotelySource

FIXTURE = Path(__file__).parent / "fixtures" / "weworkremotely.rss"


class _FakeResp:
    def __init__(self, t):
        self.text = t


def test_bad_feed_is_skipped_good_feed_survives(monkeypatch):
    good_text = FIXTURE.read_text(encoding="utf-8")

    def fake_get(url, **kwargs):
        # The feed slug is embedded in the URL (.../categories/<slug>.rss).
        if "bad" in url:
            raise requests.HTTPError("503")
        return _FakeResp(good_text)

    src = WeWorkRemotelySource(WeWorkRemotelyConfig(enabled=True, feeds=["bad", "good"]))
    monkeypatch.setattr(src, "_get", fake_get)

    jobs = src.collect()

    # The bad feed raised, but the good feed's fixture parses into 2 jobs.
    assert len(jobs) >= 1
    assert all(j.source == "weworkremotely" for j in jobs)
