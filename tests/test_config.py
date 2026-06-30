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
    # Junior prioritization via ranking, not a hard title gate. Junior signals get a
    # dedicated, heavier boost than location so entry-level roles sort to the top.
    assert cfg.seniority_allow == []
    assert "junior" in cfg.junior_boost_keywords
    assert cfg.junior_boost_weight > cfg.boost_weight
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
    # Abbreviations / additional foreign locations (surfaced by the NICE board).
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="USA - Sandy, UT")) is None
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="Philippines - Manila")) is None
    # Israeli on-site (incl. the bare 'TLV' abbreviation) is kept.
    assert e.evaluate(make_job(title="Backend Engineer", summary="python",
                               remote=False, location="TLV")) is not None
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=False, location="Tel Aviv, Israel")) is not None
    # Remote roles are location-agnostic and kept regardless of location text.
    assert e.evaluate(make_job(title="Software Engineer", summary="python",
                               remote=True, location="Anywhere in the World")) is not None


def test_shipped_config_drops_region_locked_remote_roles():
    """A 'remote' role pinned to a denied foreign region (no anywhere/worldwide/
    remote marker in its location) is region-restricted hiring — not usable from
    Israel — and is dropped. Truly global remote roles stay."""
    e = FilterEngine(load_config("config/config.yaml").filters)
    assert e.evaluate(make_job(title="Junior Software Engineer", summary="python",
                               remote=True, location="Sofia")) is None
    assert e.evaluate(make_job(title="Front End Web Developer", summary="javascript",
                               remote=True, location="Canada")) is None
    assert e.evaluate(make_job(title="Junior Software Engineer", summary="python",
                               remote=True, location="Anywhere in the World")) is not None
    assert e.evaluate(make_job(title="Junior Software Engineer", summary="python",
                               remote=True, location="Remote")) is not None


def test_shipped_config_drops_non_software_and_ops_engineer_roles():
    """The broad 'engineer' allow-term matches any 'X Engineer'. titles_deny removes
    non-software disciplines and pure-ops/SRE, while junior dev/DevOps/QA/ML stay."""
    e = FilterEngine(load_config("config/config.yaml").filters)
    drop = [
        "Site Reliability Engineer",
        "GxP Instrument Systems Engineer",
        "Electrical Engineer",
        "Mechanical Engineer",
    ]
    for title in drop:
        assert e.evaluate(make_job(title=title, summary="python",
                                   location="Tel Aviv, Israel")) is None, title
    keep = [
        "Junior DevOps Engineer",
        "QA Automation Engineer",
        "Backend Developer",
        "Junior Machine Learning Engineer",
    ]
    for title in keep:
        assert e.evaluate(make_job(title=title, summary="python",
                                   location="Tel Aviv, Israel")) is not None, title


def test_shipped_config_drops_analyst_scientist_designer_noise():
    """Profile is engineering-focused (no analyst/scientist/designer). These are
    dropped by title; junior dev/DevOps/QA/Data-Eng/ML stay eligible."""
    e = FilterEngine(load_config("config/config.yaml").filters)
    drop = [
        "Fraud Analyst", "Product Analyst", "Online Data Analyst",
        "AI Applied Scientist", "Algorithm and Applied AI Scientist",
        "AI Research Engineer", "Blockchain Engineer & Researcher",
        "Product Designer", "Web Designer", "Office Assistant",
        "Community Engagement Intern", "Application Engineer", "Founding Engineer",
        # Observed in real collected data: IT-ops / advocacy roles, not a dev job.
        "IT Specialist", "Developer Advocate", "NOC Engineer",
    ]
    for title in drop:
        assert e.evaluate(make_job(title=title, summary="python",
                                   location="Tel Aviv, Israel")) is None, title
    keep = [
        "Junior Software Engineer", "Backend Developer", "Junior DevOps Engineer",
        "QA Automation Engineer", "Data Engineer", "Machine Learning Engineer",
        "Integration Engineer", "Analytics Engineer",
    ]
    for title in keep:
        assert e.evaluate(make_job(title=title, summary="python",
                                   location="Tel Aviv, Israel")) is not None, title


def test_israel_boards_enabled():
    sources = load_config("config/config.yaml").sources
    assert sources.greenhouse.enabled and len(sources.greenhouse.boards) >= 10
    assert sources.lever.enabled and sources.lever.boards
