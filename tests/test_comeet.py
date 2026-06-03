"""Comeet source: offline parse + registry wiring."""

from __future__ import annotations

import json
from pathlib import Path

from job_assistant.config import ComeetCompany, Config
from job_assistant.sources.comeet import parse
from job_assistant.sources.registry import build_sources

FIXTURE = Path(__file__).parent / "fixtures" / "comeet.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_extracts_fields():
    jobs = parse(_load(), company="Spark Hire")
    assert len(jobs) == 2
    a, b = jobs

    assert a.source == "comeet"
    assert a.external_id == "F1.B67"
    assert a.title == "AI Engineer"
    assert a.company == "Spark Hire"
    assert a.location == "Tel Aviv, Israel"
    assert a.remote is True  # workplace_type Remote
    assert a.url.endswith("/F1.B67")
    assert "practical AI" in a.summary and "<" not in a.summary  # details HTML stripped
    assert a.posted_at is not None

    assert b.external_id == "A2.C90"
    assert b.location == "Haifa, Israel"  # non-center Israel still produced
    assert b.remote is False
    assert "5+ years" in b.summary  # feeds experience detection downstream


def test_parse_company_falls_back_to_api_name():
    jobs = parse(_load())  # no override -> use company_name from payload
    assert jobs[0].company == "Spark Hire"


def test_parse_dedup_keys_stable_and_unique():
    jobs = parse(_load())
    assert jobs[0].dedup_key != jobs[1].dedup_key
    assert jobs[0].dedup_key == parse(_load())[0].dedup_key


def _config(enabled: bool, companies) -> Config:
    cfg = Config()
    cfg.sources.comeet.enabled = enabled
    cfg.sources.comeet.companies = companies
    return cfg


def test_registry_adds_comeet_only_when_enabled_with_companies():
    company = [ComeetCompany(uid="30.005", token="x", name="Demo")]
    assert "comeet" in {s.name for s in build_sources(_config(True, company))}
    assert "comeet" not in {s.name for s in build_sources(_config(False, company))}
    assert "comeet" not in {s.name for s in build_sources(_config(True, []))}
