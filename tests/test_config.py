"""Guards for the shipped config: it must load and reflect the profile."""

from __future__ import annotations

from job_assistant.config import load_config
from job_assistant.filtering.filters import ONSITE_ONLY, REMOTE_ANY, REMOTE_ONLY


def test_example_and_active_configs_load():
    for path in ("config/config.example.yaml", "config/config.yaml"):
        cfg = load_config(path)
        assert cfg.filters.remote in {REMOTE_ANY, REMOTE_ONLY, ONSITE_ONLY}


def test_default_profile_is_graduate_junior_israel():
    cfg = load_config("config/config.yaml").filters
    # Junior prioritization via ranking, not a hard title gate.
    assert cfg.seniority_allow == []
    assert "junior" in cfg.boost_keywords
    assert "tel aviv" in cfg.boost_keywords
    assert cfg.boost_weight > 0
    # Senior roles are dropped; openness preserved (no topic exclusions).
    assert "senior" in cfg.seniority_deny
    assert cfg.keywords_deny == []
    # Remote stays included.
    assert cfg.remote == REMOTE_ANY
    # No HARD geographic filter — Israel-wide (Haifa/Jerusalem/Beer Sheva/North)
    # and remote all stay eligible; center is preferred via ranking only.
    assert cfg.locations_allow == []
    assert "israel" in cfg.boost_keywords  # Israel-wide ranking lift


def test_israel_boards_enabled():
    sources = load_config("config/config.yaml").sources
    assert sources.greenhouse.enabled and len(sources.greenhouse.boards) >= 10
    assert sources.lever.enabled and sources.lever.boards
