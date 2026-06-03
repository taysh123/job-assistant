"""Tests for the filter engine and dedup."""

from __future__ import annotations

from job_assistant.config import FiltersConfig
from job_assistant.filtering.dedup import dedup_in_batch, filter_unseen
from job_assistant.filtering.filters import FilterEngine
from tests.conftest import make_job


def engine(**cfg) -> FilterEngine:
    return FilterEngine(FiltersConfig(**cfg))


def test_keyword_allow_match_and_score():
    e = engine(keywords_allow=["python", "backend"], min_match_score=1)
    job = e.evaluate(make_job(title="Backend Engineer", summary="Python and SQL"))
    assert job is not None
    assert job.score == 2
    assert "keyword:python" in job.match_reasons
    assert "keyword:backend" in job.match_reasons


def test_min_match_score_filters_out():
    e = engine(keywords_allow=["python", "rust", "go"], min_match_score=2)
    assert e.evaluate(make_job(title="Python Dev", summary="just python")) is None


def test_title_allow_match():
    e = engine(titles_allow=["engineer"], min_match_score=1)
    job = e.evaluate(make_job(title="Software Engineer", summary=""))
    assert job is not None
    assert "title:engineer" in job.match_reasons


def test_deny_keyword_excludes():
    e = engine(keywords_allow=["engineer"], keywords_deny=["crypto"])
    assert e.evaluate(make_job(title="Engineer", summary="web3 crypto role")) is None


def test_seniority_deny_excludes_by_title():
    e = engine(seniority_deny=["senior", "staff"])
    assert e.evaluate(make_job(title="Senior Engineer", summary="")) is None
    assert e.evaluate(make_job(title="Junior Engineer", summary="")) is not None


def test_seniority_allow_requires_match():
    e = engine(seniority_allow=["junior", "entry"])
    assert e.evaluate(make_job(title="Junior Engineer", summary="")) is not None
    assert e.evaluate(make_job(title="Lead Engineer", summary="")) is None


def test_remote_only_gate():
    e = engine(remote="remote_only")
    assert e.evaluate(make_job(remote=True)) is not None
    assert e.evaluate(make_job(remote=False)) is None


def test_onsite_only_gate():
    e = engine(remote="onsite_only")
    assert e.evaluate(make_job(remote=False, location="Berlin")) is not None
    assert e.evaluate(make_job(remote=True)) is None


def test_location_allow_applies_to_onsite_only():
    e = engine(locations_allow=["berlin", "germany"])
    # Onsite job in allowed city passes; elsewhere fails.
    assert e.evaluate(make_job(remote=False, location="Berlin, Germany")) is not None
    assert e.evaluate(make_job(remote=False, location="Paris, France")) is None
    # Remote jobs are location-agnostic -> always pass the allow gate.
    assert e.evaluate(make_job(remote=True, location="Anywhere")) is not None


def test_location_deny_excludes():
    e = engine(locations_deny=["india"])
    assert e.evaluate(make_job(remote=False, location="Bangalore, India")) is None


def test_no_allowlist_keeps_everything_passing_gates():
    e = engine()  # empty allow lists
    job = e.evaluate(make_job(title="Anything"))
    assert job is not None
    assert job.score >= 1


def test_filter_sorts_by_score_desc():
    e = engine(keywords_allow=["python", "backend", "api"])
    jobs = [
        make_job(external_id="a", title="X", summary="python"),
        make_job(external_id="b", title="Backend API", summary="python api"),
    ]
    result = e.filter(jobs)
    assert [j.external_id for j in result] == ["b", "a"]


def test_dedup_in_batch():
    jobs = [make_job(external_id="1"), make_job(external_id="1"), make_job(external_id="2")]
    assert [j.external_id for j in dedup_in_batch(jobs)] == ["1", "2"]


def test_filter_unseen_against_db(repo):
    a = make_job(external_id="1")
    repo.insert_new_jobs([a])
    b = make_job(external_id="2")
    unseen = filter_unseen([a, b, make_job(external_id="2")], repo)
    assert [j.external_id for j in unseen] == ["2"]
