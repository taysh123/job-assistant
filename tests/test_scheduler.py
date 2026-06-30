"""Wave B: the always-on scheduler (collect_due/weekly_due/run_due) + serve loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_assistant import scheduler
from job_assistant.config import Config, Secrets


def test_collect_due_when_no_runs(repo):
    assert scheduler.collect_due(repo, 12, datetime.now(timezone.utc)) is True


def test_collect_not_due_after_recent_run(repo):
    repo.record_run("collect", {})
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert scheduler.collect_due(repo, 12, later) is False


def test_collect_due_after_interval(repo):
    repo.record_run("collect", {})
    later = datetime.now(timezone.utc) + timedelta(hours=13)
    assert scheduler.collect_due(repo, 12, later) is True


def test_weekly_due_only_on_monday(repo):
    monday = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)   # Monday
    tuesday = datetime(2026, 6, 30, 9, tzinfo=timezone.utc)  # Tuesday
    assert scheduler.weekly_due(repo, monday) is True
    assert scheduler.weekly_due(repo, tuesday) is False


def test_run_due_runs_both_on_a_fresh_monday(repo, monkeypatch):
    ran_log = []
    monkeypatch.setattr(scheduler, "run_collection",
                        lambda cfg, sec, r, **k: ran_log.append("collect"))
    monkeypatch.setattr(scheduler, "send_weekly_summary",
                        lambda sec, r: ran_log.append("weekly"))
    cfg = Config()
    secrets = Secrets(telegram_bot_token="t", telegram_chat_id="c")
    monday = datetime(2026, 6, 29, 9, tzinfo=timezone.utc)
    ran = scheduler.run_due(cfg, secrets, repo, now=monday)
    assert ran == {"collect", "weekly"}
    assert sorted(ran_log) == ["collect", "weekly"]


def test_serve_runs_one_cycle_then_stops(repo, monkeypatch):
    calls = {"due": 0, "updates": 0}
    monkeypatch.setattr(scheduler, "run_due",
                        lambda *a, **k: calls.__setitem__("due", calls["due"] + 1) or set())
    monkeypatch.setattr(scheduler, "process_updates",
                        lambda *a, **k: calls.__setitem__("updates", calls["updates"] + 1) or 0)
    state = {"n": 0}

    def stop():
        state["n"] += 1
        return state["n"] > 1   # allow exactly one cycle

    cfg = Config()
    secrets = Secrets(telegram_bot_token="t", telegram_chat_id="c")
    scheduler.serve(cfg, secrets, repo, poll=0, stop=stop,
                    clock=lambda: datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert calls == {"due": 1, "updates": 1}
