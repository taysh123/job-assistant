"""Optional AI layer: a disciplined, capped, fail-closed wrapper around a cheap
Claude model for job-fit ranking and application drafting.

Discipline (mirrors a hard-capped AI coach): feature-flagged (zero cost and no
behavior change when disabled), a HARD monthly USD cap (fail-closed when hit), a
per-run call limit, and a fallback to deterministic behavior on ANY error. The
``anthropic`` SDK is imported lazily, so it isn't even a required dependency
unless the feature is turned on. The bot never auto-applies — drafting only ever
returns text for the user to review and send themselves.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from .config import AIConfig, Secrets
from .db.repository import Repository
from .models import Job

logger = logging.getLogger(__name__)

# USD per 1,000,000 tokens (input, output) — used to meter spend against the cap.
_PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}

_JSON_RE = re.compile(r"\{.*\}", re.S)


class CappedAIClient:
    """Guarded Claude client. Every call goes through :meth:`complete`, which
    returns None (never raises) when the feature is disabled, unconfigured, over
    its per-run limit, over the monthly cap, or the API errors — so callers
    always have a deterministic fallback."""

    def __init__(self, config: AIConfig, repo: Repository, *, client=None, clock=None):
        self.config = config
        self.repo = repo
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._calls_this_run = 0

    # --- spend metering (persisted per calendar month in bot_state) --------
    def _month_key(self) -> str:
        return "ai_spend:" + self._clock().strftime("%Y-%m")

    def spent_this_month(self) -> float:
        return float(self.repo.get_state(self._month_key(), "0") or "0")

    def _record_cost(self, usd: float) -> None:
        self.repo.set_state(self._month_key(), f"{self.spent_this_month() + usd:.6f}")

    def _cost_of(self, resp) -> float:
        cin, cout = _PRICING.get(self.config.model, (1.0, 5.0))
        usage = resp.usage
        return (usage.input_tokens / 1e6) * cin + (usage.output_tokens / 1e6) * cout

    # --- gating ------------------------------------------------------------
    def available(self) -> bool:
        return bool(
            self.config.enabled
            and self._client is not None
            and self._calls_this_run < self.config.max_calls_per_run
            and self.spent_this_month() < self.config.monthly_usd_cap
        )

    def complete(self, system: str, user: str, *, max_tokens: int = 400) -> str | None:
        if not self.available():
            return None
        self._calls_this_run += 1
        try:
            resp = self._client.messages.create(
                model=self.config.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            self._record_cost(self._cost_of(resp))
            return "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            )
        except Exception as exc:  # noqa: BLE001 - fail closed to deterministic behavior
            logger.warning("AI call failed; falling back deterministically: %s", exc)
            return None


def build_ai_client(config: AIConfig, secrets: Secrets, repo: Repository) -> CappedAIClient:
    """Construct the client. Returns an UNAVAILABLE client (never makes a call)
    when AI is disabled, the key is missing, or the anthropic SDK isn't
    installed — so the rest of the system is unaffected and incurs zero cost."""
    client = None
    if config.enabled and secrets.is_ai_configured:
        try:
            import anthropic  # lazy: not a required dependency unless AI is on
            client = anthropic.Anthropic(api_key=secrets.anthropic_api_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anthropic SDK unavailable; AI disabled: %s", exc)
    return CappedAIClient(config, repo, client=client)


def score_job_fit(ai: CappedAIClient, job: Job, profile: str) -> dict | None:
    """Return ``{"score": 0-100, "reason": str}`` for this job, or None. Cached
    by ``dedup_key`` so a job is scored at most once (even across runs)."""
    cache_key = "ai_fit:" + job.dedup_key
    cached = ai.repo.get_state(cache_key)
    if cached:
        return json.loads(cached)
    system = (
        "You rate how well a software job fits a candidate. Reply with ONLY a "
        'JSON object: {"score": <integer 0-100>, "reason": "<one short sentence>"}.'
    )
    user = (
        f"Candidate profile:\n{profile}\n\n"
        f"Job:\nTitle: {job.title}\nCompany: {job.company}\n"
        f"Location: {job.location}\nSummary: {job.summary[:1000]}"
    )
    text = ai.complete(system, user, max_tokens=200)
    if text is None:
        return None
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        result = {"score": int(data["score"]), "reason": str(data.get("reason", ""))[:200]}
    except (ValueError, KeyError, TypeError):
        return None
    ai.repo.set_state(cache_key, json.dumps(result))
    return result


def apply_ai_ranking(ai: CappedAIClient, jobs: list[Job], profile: str) -> list[Job]:
    """Re-rank jobs by AI fit when available; otherwise return them unchanged
    (deterministic behavior, zero cost). Scored jobs sort to the front by score;
    unscored jobs keep their original relative order at the back."""
    if not ai.available():
        return jobs
    keyed = []
    for index, job in enumerate(jobs):
        fit = score_job_fit(ai, job, profile)
        if fit is not None:
            job.match_reasons = job.match_reasons + [f"ai:{fit['score']}"]
            keyed.append((0, -fit["score"], index, job))
        else:
            keyed.append((1, 0, index, job))  # unscored: after scored, original order
    keyed.sort(key=lambda t: (t[0], t[1], t[2]))
    return [job for *_rest, job in keyed]


def draft_application(ai: CappedAIClient, job: Job, profile: str, cv_text: str) -> str | None:
    """Draft a tailored cover letter + CV-tailoring suggestions for the user to
    review and send THEMSELVES. Never applies. Returns None if unavailable."""
    system = (
        "You help a job-seeker apply. Draft a concise, tailored cover letter and "
        "3 specific CV-tailoring suggestions for THIS job. The user reviews and "
        "sends it themselves — never claim to have applied or to send anything."
    )
    user = (
        f"Candidate profile:\n{profile}\n\nCV:\n{cv_text[:4000]}\n\n"
        f"Job:\nTitle: {job.title}\nCompany: {job.company}\n"
        f"Location: {job.location}\nSummary: {job.summary[:1500]}"
    )
    return ai.complete(system, user, max_tokens=800)
