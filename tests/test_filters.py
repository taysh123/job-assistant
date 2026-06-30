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


def test_titles_deny_excludes_non_dev_roles_by_title_only():
    e = engine(titles_allow=["engineer"], titles_deny=["sales", "support engineer"])
    # Non-dev role caught by title -> dropped.
    assert e.evaluate(make_job(title="Sales Engineer", summary="python")) is None
    assert e.evaluate(make_job(title="Application Support Engineer", summary="java")) is None
    # A real dev role that only mentions the term in its summary is kept.
    kept = e.evaluate(make_job(title="Backend Engineer", summary="partner with the sales team"))
    assert kept is not None


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


def test_location_deny_applies_to_onsite_only():
    # A foreign on-site role is dropped, but a REMOTE role whose location still
    # signals remote/global stays eligible even if it mentions a denied place.
    e = engine(locations_deny=["india", "london"])
    assert e.evaluate(make_job(remote=False, location="Bangalore, India")) is None
    assert e.evaluate(make_job(remote=True, location="Remote (London-based team)")) is not None
    # Israeli on-site roles are never touched by the foreign deny list.
    assert e.evaluate(make_job(remote=False, location="Tel Aviv, Israel")) is not None


def test_location_deny_drops_region_locked_remote_roles():
    # A "remote" job whose location pins it to a denied foreign region (with no
    # anywhere/worldwide/remote marker) is region-restricted hiring — dropped.
    e = engine(locations_deny=["bulgaria", "sofia", "canada"])
    assert e.evaluate(make_job(remote=True, location="Sofia")) is None
    assert e.evaluate(make_job(remote=True, location="Canada")) is None
    # Global markers (or no location at all) keep the role eligible.
    assert e.evaluate(make_job(remote=True, location="Anywhere in the World")) is not None
    assert e.evaluate(make_job(remote=True, location="Remote (Sofia-based team)")) is not None
    assert e.evaluate(make_job(remote=True, location="")) is not None
    assert e.evaluate(make_job(remote=True, location="Tel Aviv, Israel")) is not None


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


def test_keyword_hits_are_capped_so_verbose_jds_dont_dominate():
    # 6 keyword hits, but the base keyword contribution is capped at 4.
    e = engine(keywords_allow=["python", "java", "react", "node", "sql", "css"])
    job = e.evaluate(make_job(title="Role", summary="python java react node sql css"))
    assert job.score == 4  # capped, not 6
    # A boosted Israel/junior job with fewer keywords still wins.
    e2 = engine(
        keywords_allow=["python", "java", "react", "node", "sql", "css"],
        boost_keywords=["tel aviv", "junior"], boost_weight=3,
    )
    verbose = make_job(external_id="v", title="Engineer", summary="python java react node sql css", location="Remote")
    israeli = make_job(external_id="il", title="Junior Developer", summary="python", location="Tel Aviv, Israel")
    ranked = e2.filter([verbose, israeli])
    assert ranked[0].external_id == "il"


def test_boost_adds_weight_and_reason():
    e = engine(keywords_allow=["engineer"], boost_keywords=["junior"], boost_weight=3)
    job = e.evaluate(make_job(title="Junior Engineer", summary=""))
    assert job is not None
    # 1 base hit (engineer) + boost 3 = 4.
    assert job.score == 4
    assert "boost:junior" in job.match_reasons


def test_boost_matches_location_field():
    e = engine(keywords_allow=["engineer"], boost_keywords=["tel aviv"], boost_weight=3)
    job = e.evaluate(make_job(title="Software Engineer", summary="", location="Tel Aviv, Israel"))
    assert job is not None
    assert "boost:tel aviv" in job.match_reasons
    assert job.score == 4  # 1 (engineer) + 3


def test_boost_ranks_israel_junior_above_generic():
    e = engine(
        titles_allow=["engineer"],
        keywords_allow=["python", "react", "node", "api"],
        boost_keywords=["junior", "tel aviv"],
        boost_weight=3,
    )
    jobs = [
        # Tech-heavy generic remote job: 1 title + 4 keywords = 5.
        make_job(external_id="generic", title="Engineer", summary="python react node api", remote=True),
        # Israel junior job: 1 title + boost(junior)+boost(tel aviv) = 1 + 6 = 7.
        make_job(external_id="il", title="Junior Engineer", summary="", location="Tel Aviv", remote=False),
    ]
    result = e.filter(jobs)
    assert [j.external_id for j in result] == ["il", "generic"]


def test_location_boost_is_capped_so_one_city_does_not_stack():
    # A single Tel Aviv location string matches several boost tokens, but location
    # boost is capped (israel + one center tier) so it can't dwarf the junior boost.
    e = engine(titles_allow=["engineer"],
               boost_keywords=["israel", "tel aviv", "tel aviv-yafo", "gush dan"],
               boost_weight=3)
    j = e.evaluate(make_job(title="Software Engineer",
                            location="Tel Aviv-Yafo, Gush Dan, Israel"))
    # title:engineer(1) + capped location boost (2 * 3) = 7, not 1 + 4*3 = 13.
    assert j.score == 7


def test_boost_does_not_bypass_allow_gate():
    # A job that matches only a boost term (no allow hit) is still excluded.
    e = engine(keywords_allow=["python"], boost_keywords=["junior"], min_match_score=1)
    assert e.evaluate(make_job(title="Junior Marketing Lead", summary="seo")) is None


def test_junior_boost_ranks_junior_above_generic_israel_role():
    e = engine(
        titles_allow=["engineer"],
        boost_keywords=["israel", "tel aviv"], boost_weight=3,
        junior_boost_keywords=["junior", "graduate"], junior_boost_weight=8,
    )
    generic_il = make_job(external_id="il", title="Software Engineer",
                          location="Tel Aviv, Israel", remote=False)  # +israel +telaviv = 7
    junior_remote = make_job(external_id="jr", title="Junior Software Engineer",
                             location="Remote", remote=True)          # +junior = 9
    result = e.filter([generic_il, junior_remote])
    assert [j.external_id for j in result] == ["jr", "il"]
    jr = next(j for j in result if j.external_id == "jr")
    assert any(r.startswith("junior:") for r in jr.match_reasons)


def test_no_boost_keywords_keeps_scores_unchanged():
    e = engine(keywords_allow=["python", "backend"])
    job = e.evaluate(make_job(title="Backend", summary="python"))
    assert job.score == 2  # unchanged when boost not configured


def test_dedup_in_batch():
    jobs = [make_job(external_id="1"), make_job(external_id="1"), make_job(external_id="2")]
    assert [j.external_id for j in dedup_in_batch(jobs)] == ["1", "2"]


def test_filter_unseen_against_db(repo):
    a = make_job(external_id="1")
    repo.insert_new_jobs([a])
    b = make_job(external_id="2")
    unseen = filter_unseen([a, b, make_job(external_id="2")], repo)
    assert [j.external_id for j in unseen] == ["2"]


# --- Wave 0 FIX A: geo-deny matches whole words, not substrings -------------

def test_geo_deny_does_not_drop_onsite_jerusalem():
    # The real bug: "usa" in locations_deny matched the substring in "jerUSAlem".
    e = engine(titles_allow=["engineer"], locations_deny=["usa", "new york"])
    job = e.evaluate(make_job(title="Software Engineer", remote=False,
                              location="Jerusalem, Israel"))
    assert job is not None


def test_geo_deny_still_drops_standalone_denied_token():
    e = engine(titles_allow=["engineer"], locations_deny=["usa", "new york"])
    assert e.evaluate(make_job(title="Software Engineer", remote=False,
                               location="New York, USA")) is None


def test_geo_deny_whole_word_keeps_israeli_cities():
    e = engine(titles_allow=["engineer"], locations_deny=["usa", "india", "china"])
    for city in ["Jerusalem, Israel", "Ramat Gan, Israel", "Herzliya"]:
        assert e.evaluate(make_job(title="Software Engineer", remote=False,
                                   location=city)) is not None, city


def test_geo_deny_whole_word_preserves_region_lock_behavior():
    e = engine(titles_allow=["engineer"], locations_deny=["india", "bangalore"])
    # On-site abroad dropped.
    assert e.evaluate(make_job(title="Software Engineer", remote=False,
                               location="Bangalore, India")) is None
    # Remote pinned to a denied region (no global marker) dropped.
    assert e.evaluate(make_job(title="Software Engineer", remote=True,
                               location="Bangalore, India")) is None
    # Remote + a global marker stays eligible.
    assert e.evaluate(make_job(title="Software Engineer", remote=True,
                               location="Remote - Anywhere (India team)")) is not None
