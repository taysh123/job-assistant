"""Offline parser + registry-wiring tests for the Jobicy source."""

from __future__ import annotations

import json
from pathlib import Path

from job_assistant.config import Config, JobicyConfig
from job_assistant.sources import jobicy
from job_assistant.sources.jobicy import JobicySource
from job_assistant.sources.registry import build_sources

FIXTURES = Path(__file__).parent / "fixtures"


def test_jobicy_parse():
    payload = json.loads((FIXTURES / "jobicy.json").read_text(encoding="utf-8"))
    jobs = jobicy.parse(payload)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source == "jobicy"
    assert j.external_id == "147001"
    assert j.title == "Backend Engineer"
    assert j.company == "Acme Remote"
    assert j.url.startswith("https://jobicy.com/")
    assert j.location == "Anywhere"
    assert j.remote is True
    assert j.posted_at is not None
    assert "<" not in j.summary and "&amp;" not in j.summary  # tags + entities cleaned


def test_jobicy_registry_wiring():
    cfg = Config()
    cfg.sources.jobicy = JobicyConfig(enabled=True)
    assert any(isinstance(s, JobicySource) for s in build_sources(cfg, None))
    cfg.sources.jobicy = JobicyConfig(enabled=False)
    assert not any(isinstance(s, JobicySource) for s in build_sources(cfg, None))
