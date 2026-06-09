"""Guards for the shipped config: it must load and reflect the profile."""

from __future__ import annotations

from job_assistant.config import load_config
from job_assistant.filtering.filters import (
    ONSITE_ONLY,
    REMOTE_ANY,
    REMOTE_ONLY,
    FilterEngine,
)
from tests.conftest import make_job


def test_example_and_active_configs_load():
    for path in ("config/config.example.yaml", "config/config.yaml"):
        cfg = load_config(path)
        assert cfg.filters.remote in {REMOTE_ANY, REMOTE_ONLY, ONSITE_ONLY}
        # One job per page is the default browsing experience.
        assert cfg.digest.page_size == 1


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
    # Experience: junior-friendly — explicitly over-experienced roles are removed.
    assert cfg.max_years_experience == 2
    assert cfg.experience_mode == "filter"
    # Non-software role types (sales/support/etc.) are excluded by title.
    assert "sales" in cfg.titles_deny
    assert "support engineer" in cfg.titles_deny


def test_shipped_config_drops_support_noise_keeps_dev_roles():
    """IT-support/helpdesk roles match junior keywords but aren't a first dev job;
    the shipped titles_deny removes them while real junior dev roles survive."""
    e = FilterEngine(load_config("config/config.yaml").filters)
    assert e.evaluate(make_job(title="Helpdesk Specialist", summary="entry level python")) is None
    assert e.evaluate(make_job(title="IT Support Specialist", summary="junior, sql")) is None
    kept = e.evaluate(make_job(title="Junior Software Engineer",
                               summary="python", location="Tel Aviv, Israel"))
    assert kept is not None


def test_shipped_config_excludes_foreign_onsite_keeps_israel_and_remote():
    """Foreign on-site roles are dropped; ALL Israeli locations (incl. 'TLV') and
    every remote role stay eligible."""
    e = FilterEngine(load_config("config/config.yaml").filters)
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="Bangalore, India")) is None
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="Budapest, Hungary")) is None
    # Israeli on-site (incl. the bare 'TLV' abbreviation) is kept.
    assert e.evaluate(make_job(title="Backend Engineer", summary="python",
                               remote=False, location="TLV")) is not None
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="Tel Aviv, Israel")) is not None
    # Remote roles are location-agnostic and kept regardless of location text.
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=True, location="Anywhere in the World")) is not None


def test_israel_boards_enabled():
    sources = load_config("config/config.yaml").sources
    assert sources.greenhouse.enabled and len(sources.greenhouse.boards) >= 10
    assert sources.lever.enabled and sources.lever.boards
