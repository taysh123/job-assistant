"""Preference-based filtering with match scoring.

A job is kept when it:
  1. is not excluded by any deny keyword (title/summary),
  2. passes the remote/location/seniority gates,
  3. accumulates at least ``min_match_score`` allow-list hits.

Each kept job is annotated with human-readable ``match_reasons`` so the
Telegram card can explain *why* it surfaced.
"""

from __future__ import annotations

import re

from ..config import FiltersConfig
from ..models import Job
from .experience import required_years

REMOTE_ANY = "any"
REMOTE_ONLY = "remote_only"
ONSITE_ONLY = "onsite_only"

# Cap on how much keyword (summary) hits contribute to the base relevance score,
# so a keyword-stuffed description can't outrank the location/junior boost.
KEYWORD_SCORE_CAP = 4

# Cap on how many LOCATION boost terms count, so one place written with several
# tokens ("Tel Aviv-Yafo, Gush Dan, Israel") can't stack — it scores at most the
# intended two tiers (israel + one center city), keeping junior the stronger signal.
LOCATION_BOOST_CAP = 2

# A remote job whose location contains one of these is hireable from anywhere; a
# remote job *without* one whose location names a denied region is region-locked.
GLOBAL_LOCATION_MARKERS = ("anywhere", "worldwide", "global", "remote")


def _location_is_global(location: str) -> bool:
    low = location.lower().strip()
    return not low or any(marker in low for marker in GLOBAL_LOCATION_MARKERS)


def _haystack(job: Job) -> str:
    return f"{job.title}\n{job.summary}".lower()


def _boost_haystack(job: Job) -> str:
    # Title + location ONLY (not the summary): boost should reflect the role and
    # where it actually is. Excluding the description avoids company boilerplate
    # (e.g. an Israeli firm's "HQ in Tel Aviv") inflating foreign-located jobs.
    return f"{job.title}\n{job.location}".lower()


# Hebrew loanwords (e.g. ג'וניור = "junior", סטאז' = "internship") appear with
# different apostrophe/geresh characters; fold them to one form so a base-form
# needle matches whichever variant the posting used. Hebrew has no letter case
# and its prefixes (ה/ל/מ/ב/ו/ש) + gender suffixes (ת/ית) are handled implicitly
# by substring matching of base-form terms (e.g. "מפתח" matches "המפתחת").
_GERESH = str.maketrans({"׳": "'", "’": "'", "ʼ": "'"})


def _contains_any(text: str, needles: list[str]) -> list[str]:
    low = text.lower().translate(_GERESH)
    return [n for n in needles if n and n.lower().translate(_GERESH) in low]


def _location_denied(location: str, needles: list[str]) -> list[str]:
    """Whole-word/phrase location-deny match.

    Unlike :func:`_contains_any` (substring), a deny term matches only when it
    appears as a standalone token, so ``"usa"`` does NOT match ``"Jerusalem"``.
    Multi-word terms (``"new york"``) match as phrases. Boundaries are
    non-alphanumeric, so commas/spaces delimit tokens and non-Latin text (Hebrew,
    added later) keeps working.
    """
    low = location.lower()
    hits: list[str] = []
    for n in needles:
        if not n:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", low):
            hits.append(n)
    return hits


class FilterEngine:
    def __init__(self, config: FiltersConfig):
        self.config = config

    def evaluate(self, job: Job) -> Job | None:
        """Return the job (annotated) if it passes, else None."""
        cfg = self.config
        haystack = _haystack(job)

        # 1. Hard exclusions.
        denied = _contains_any(haystack, cfg.keywords_deny)
        if denied:
            return None
        if _contains_any(job.title, cfg.seniority_deny):
            return None
        if _contains_any(job.title, cfg.titles_deny):
            return None
        # Geo deny: on-site roles abroad are dropped. A remote role is normally
        # location-agnostic, but when its location pins it to a denied region with
        # no anywhere/worldwide/remote marker, it's region-restricted hiring —
        # equally unusable — so it is dropped too.
        if _location_denied(job.location, cfg.locations_deny):
            if not job.remote or not _location_is_global(job.location):
                return None

        # 2. Remote / location gates.
        if not self._passes_remote(job):
            return None
        if not self._passes_location(job):
            return None
        if not self._passes_seniority(job):
            return None

        # 3. Positive matches + score. Title hits count fully (titles are short
        # and meaningful); keyword/summary hits are capped so a keyword-stuffed
        # description can't dominate the location/junior boost applied below.
        title_hits = _contains_any(job.title, cfg.titles_allow)
        keyword_hits = _contains_any(haystack, cfg.keywords_allow)
        reasons = [f"title:{h}" for h in title_hits] + [f"keyword:{h}" for h in keyword_hits]

        # With no allow-list configured, everything that passed the gates is kept.
        no_allowlist = not (cfg.titles_allow or cfg.keywords_allow)
        base = len(title_hits) + min(len(keyword_hits), KEYWORD_SCORE_CAP)
        if not no_allowlist and base < cfg.min_match_score:
            return None

        score = base if not no_allowlist else max(base, 1)

        # Ranking-only LOCATION boost (does not affect the gate above), capped so a
        # single multi-token location can't stack beyond the intended tiers.
        for hit in _contains_any(_boost_haystack(job), cfg.boost_keywords)[:LOCATION_BOOST_CAP]:
            score += cfg.boost_weight
            reasons.append(f"boost:{hit}")

        # Junior/graduate signals (title only) get a dedicated, heavier boost so
        # genuine entry-level roles sort above same-tech non-junior roles.
        for hit in _contains_any(job.title, cfg.junior_boost_keywords):
            score += cfg.junior_boost_weight
            reasons.append(f"junior:{hit}")

        # Experience requirement: act only when a role *explicitly* asks for more
        # years than allowed (generic roles with no stated years pass untouched).
        req = required_years(haystack)
        if req is not None and req > cfg.max_years_experience and cfg.experience_mode != "off":
            if cfg.experience_mode == "filter":
                return None
            score -= cfg.experience_penalty  # downrank: stays visible, sinks
            reasons.append(f"exp≥{req}y")

        if job.remote:
            reasons.append("remote")

        job.score = score
        job.match_reasons = reasons
        return job

    def filter(self, jobs: list[Job]) -> list[Job]:
        kept = [j for j in (self.evaluate(job) for job in jobs) if j is not None]
        kept.sort(key=lambda j: j.score, reverse=True)
        return kept

    # --- gates -----------------------------------------------------------

    def _passes_remote(self, job: Job) -> bool:
        mode = self.config.remote
        if mode == REMOTE_ONLY:
            return job.remote
        if mode == ONSITE_ONLY:
            return not job.remote
        return True

    def _passes_location(self, job: Job) -> bool:
        allow = self.config.locations_allow
        if not allow:
            return True
        # Remote jobs are location-agnostic and always pass the allow gate.
        if job.remote:
            return True
        return bool(_contains_any(job.location, allow))

    def _passes_seniority(self, job: Job) -> bool:
        allow = self.config.seniority_allow
        if not allow:
            return True
        return bool(_contains_any(job.title, allow))
