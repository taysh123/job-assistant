"""Experience-requirement detection + its effect in the filter engine."""

from __future__ import annotations

import pytest

from job_assistant.config import FiltersConfig
from job_assistant.filtering.experience import required_years
from job_assistant.filtering.filters import FilterEngine
from tests.conftest import make_job


@pytest.mark.parametrize("text, expected", [
    ("We require 5+ years of experience", 5),
    ("Minimum 3 years in software development", 3),
    ("At least 4 years experience", 4),
    ("3-5 years of experience required", 3),          # range -> lower bound
    ("Looking for a senior-level engineer", 5),       # phrase -> sentinel
    ("2+ years of experience", 2),
    ("0-2 years experience", 0),
    ("Software Engineer to join our backend team", None),  # no requirement stated
    ("Founded 20 years ago, we build great products", None),  # boilerplate, not tied to experience
    ("", None),
])
def test_required_years(text, expected):
    assert required_years(text) == expected


def test_required_years_takes_minimum_when_several():
    assert required_years("5+ years preferred; minimum 3 years required") == 3


def _engine(**cfg) -> FilterEngine:
    base = dict(keywords_allow=["engineer", "python"], min_match_score=1)
    base.update(cfg)
    return FilterEngine(FiltersConfig(**base))


def test_downrank_penalises_but_keeps_visible():
    e = _engine(experience_mode="downrank", experience_penalty=8, max_years_experience=2)
    senior = e.evaluate(make_job(title="Engineer", summary="python; 5+ years of experience"))
    junior = e.evaluate(make_job(title="Engineer", summary="python; entry level"))
    assert senior is not None  # still visible
    assert any(r.startswith("exp") for r in senior.match_reasons)
    assert senior.score < junior.score  # sinks below the junior role


def test_filter_mode_excludes_overqualified():
    e = _engine(experience_mode="filter", max_years_experience=2)
    assert e.evaluate(make_job(title="Engineer", summary="python; requires 6 years experience")) is None


def test_off_mode_ignores_experience():
    e = _engine(experience_mode="off")
    job = e.evaluate(make_job(title="Engineer", summary="python; 7+ years of experience"))
    assert job is not None
    assert not any(r.startswith("exp") for r in job.match_reasons)


def test_generic_role_unaffected():
    e = _engine(experience_mode="downrank")
    job = e.evaluate(make_job(title="Software Engineer", summary="python; build APIs"))
    assert job is not None
    assert not any(r.startswith("exp") for r in job.match_reasons)


def test_boundary_years_kept():
    e = _engine(experience_mode="downrank", max_years_experience=2)
    job = e.evaluate(make_job(title="Engineer", summary="python; 2+ years of experience"))
    assert not any(r.startswith("exp") for r in job.match_reasons)  # 2 is not > 2
