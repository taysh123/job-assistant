"""Preference-based filtering with match scoring.

A job is kept when it:
  1. is not excluded by any deny keyword (title/summary),
  2. passes the remote/location/seniority gates,
  3. accumulates at least ``min_match_score`` allow-list hits.

Each kept job is annotated with human-readable ``match_reasons`` so the
Telegram card can explain *why* it surfaced.
"""

from __future__ import annotations

from ..config import FiltersConfig
from ..models import Job

REMOTE_ANY = "any"
REMOTE_ONLY = "remote_only"
ONSITE_ONLY = "onsite_only"


def _haystack(job: Job) -> str:
    return f"{job.title}\n{job.summary}".lower()


def _contains_any(text: str, needles: list[str]) -> list[str]:
    low = text.lower()
    return [n for n in needles if n and n.lower() in low]


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
        if _contains_any(job.location, cfg.locations_deny):
            return None

        # 2. Remote / location gates.
        if not self._passes_remote(job):
            return None
        if not self._passes_location(job):
            return None
        if not self._passes_seniority(job):
            return None

        # 3. Positive matches + score.
        reasons: list[str] = []
        for hit in _contains_any(job.title, cfg.titles_allow):
            reasons.append(f"title:{hit}")
        for hit in _contains_any(haystack, cfg.keywords_allow):
            reasons.append(f"keyword:{hit}")

        # With no allow-list configured, everything that passed the gates is kept.
        no_allowlist = not (cfg.titles_allow or cfg.keywords_allow)
        score = len(reasons)
        if not no_allowlist and score < cfg.min_match_score:
            return None

        if job.remote:
            reasons.append("remote")

        job.score = score if not no_allowlist else max(score, 1)
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
