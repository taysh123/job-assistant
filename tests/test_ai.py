"""Wave C: the capped, fail-closed AI layer (disabled by default = zero cost)."""

from __future__ import annotations

from datetime import datetime, timezone

from job_assistant.ai import (CappedAIClient, apply_ai_ranking, draft_application,
                              score_job_fit)
from job_assistant.config import AIConfig
from tests.conftest import make_job


class _Resp:
    def __init__(self, text, in_tok=1000, out_tok=200):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": in_tok, "output_tokens": out_tok})()


class _FakeMessages:
    def __init__(self, responder):
        self._responder = responder
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self._responder(kwargs)


class _FakeAnthropic:
    def __init__(self, responder):
        self.messages = _FakeMessages(responder)


def _client(repo, responder, **cfg):
    cfg.setdefault("monthly_usd_cap", 10.0)
    cfg.setdefault("max_calls_per_run", 20)
    config = AIConfig(enabled=True, **cfg)
    fake = _FakeAnthropic(responder)
    ai = CappedAIClient(config, repo, client=fake,
                        clock=lambda: datetime(2026, 6, 30, tzinfo=timezone.utc))
    return ai, fake


def test_disabled_makes_no_calls(repo):
    fake = _FakeAnthropic(lambda k: _Resp("hi"))
    ai = CappedAIClient(AIConfig(enabled=False), repo, client=fake)
    assert ai.complete("s", "u") is None
    assert fake.messages.calls == 0


def test_complete_returns_text_and_meters_spend(repo):
    ai, fake = _client(repo, lambda k: _Resp("hello"))
    assert ai.complete("s", "u") == "hello"
    assert fake.messages.calls == 1
    assert ai.spent_this_month() > 0


def test_monthly_cap_fails_closed(repo):
    # Each call costs 1000/1e6*1 + 200/1e6*5 = 0.002 USD. Cap below 2 calls.
    ai, fake = _client(repo, lambda k: _Resp("x"), monthly_usd_cap=0.0015)
    assert ai.complete("s", "u") == "x"          # first call allowed
    assert ai.complete("s", "u") is None         # now over cap -> blocked
    assert fake.messages.calls == 1


def test_api_error_fails_closed(repo):
    def boom(kwargs):
        raise RuntimeError("network down")
    ai, fake = _client(repo, boom)
    assert ai.complete("s", "u") is None
    assert ai.spent_this_month() == 0


def test_per_run_call_limit(repo):
    ai, fake = _client(repo, lambda k: _Resp("x"), max_calls_per_run=1)
    assert ai.complete("s", "u") == "x"
    assert ai.complete("s", "u") is None
    assert fake.messages.calls == 1


def test_score_job_fit_parses_and_caches(repo):
    ai, fake = _client(repo, lambda k: _Resp('{"score": 87, "reason": "great match"}'))
    job = make_job(external_id="z1")
    fit = score_job_fit(ai, job, "junior dev")
    assert fit == {"score": 87, "reason": "great match"}
    again = score_job_fit(ai, job, "junior dev")   # cached -> no 2nd API call
    assert again == fit
    assert fake.messages.calls == 1


def test_apply_ai_ranking_noop_when_disabled(repo):
    fake = _FakeAnthropic(lambda k: _Resp("{}"))
    ai = CappedAIClient(AIConfig(enabled=False), repo, client=fake)
    jobs = [make_job(external_id="a"), make_job(external_id="b")]
    assert apply_ai_ranking(ai, jobs, "p") == jobs
    assert fake.messages.calls == 0


def test_apply_ai_ranking_reorders_by_score(repo):
    def responder(kwargs):
        text = kwargs["messages"][0]["content"]
        score = 90 if "Bravo" in text else 10
        return _Resp(f'{{"score": {score}, "reason": "r"}}')
    ai, fake = _client(repo, responder)
    a = make_job(external_id="a", title="Alpha Engineer")
    b = make_job(external_id="b", title="Bravo Engineer")
    ranked = apply_ai_ranking(ai, [a, b], "p")
    assert [j.external_id for j in ranked] == ["b", "a"]
    assert any(r.startswith("ai:") for r in ranked[0].match_reasons)


def test_draft_application_returns_text(repo):
    ai, fake = _client(repo, lambda k: _Resp("Dear hiring manager, ..."))
    draft = draft_application(ai, make_job(), "junior dev", "my CV text")
    assert "Dear hiring manager" in draft


def test_cli_draft_no_job_returns_1(tmp_path, monkeypatch):
    from job_assistant.cli import main
    from job_assistant.config import Secrets
    monkeypatch.setattr("job_assistant.cli.load_secrets", lambda: Secrets())
    assert main(["--db", str(tmp_path / "j.db"), "draft", "999"]) == 1
