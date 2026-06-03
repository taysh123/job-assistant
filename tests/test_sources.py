"""Offline parser tests for each source (fixtures only, no network)."""

from __future__ import annotations

import json
from pathlib import Path

from job_assistant.sources import greenhouse, lever, remotive, weworkremotely

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_remotive_parse():
    jobs = remotive.parse(json.loads(_load("remotive.json")))
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source == "remotive"
    assert j.external_id == "1001"
    assert j.title == "Backend Python Engineer"
    assert j.company == "Acme Cloud"
    assert j.remote is True
    assert j.location == "Worldwide"
    assert "Python backend engineer" in j.summary
    assert "<" not in j.summary  # HTML stripped
    assert j.posted_at is not None


def test_weworkremotely_parse_splits_company_and_title():
    jobs = weworkremotely.parse(_load("weworkremotely.rss"))
    assert len(jobs) == 2
    j = jobs[0]
    assert j.company == "Globex"
    assert j.title == "Senior Python Developer"
    assert j.external_id == "globex-senior-python-developer-2001"
    assert j.location == "Anywhere in the World"
    assert "Django" in j.summary
    assert "<" not in j.summary
    assert j.remote is True


def test_greenhouse_parse_remote_detection():
    jobs = greenhouse.parse(json.loads(_load("greenhouse.json")), board="acme")
    assert len(jobs) == 2
    remote_job, onsite_job = jobs
    assert remote_job.company == "acme"
    assert remote_job.location == "Remote - US"
    assert remote_job.remote is True
    assert onsite_job.location == "Berlin, Germany"
    assert onsite_job.remote is False
    assert "Go" in remote_job.summary
    assert "&" not in remote_job.summary  # entities unescaped + tags stripped


def test_lever_parse_remote_and_onsite():
    jobs = lever.parse(json.loads(_load("lever.json")), board="initrode")
    assert len(jobs) == 2
    remote_job, onsite_job = jobs
    assert remote_job.title == "Full Stack Engineer"
    assert remote_job.remote is True
    assert remote_job.posted_at is not None
    assert onsite_job.location == "London, UK"
    assert onsite_job.remote is False


def test_parsers_produce_stable_dedup_keys():
    jobs = remotive.parse(json.loads(_load("remotive.json")))
    again = remotive.parse(json.loads(_load("remotive.json")))
    assert jobs[0].dedup_key == again[0].dedup_key
    assert jobs[0].dedup_key != jobs[1].dedup_key
