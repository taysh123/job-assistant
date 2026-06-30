"""Wave 0 FIX B: the Source._safe_collect contract — a misbehaving source is
logged and skipped (returns []) and never raises, so it can't break a run."""

from __future__ import annotations

from job_assistant.sources.base import Source


class _OkSource(Source):
    name = "ok"

    def collect(self):
        return self._safe_collect(lambda: [1, 2, 3])


class _BadSource(Source):
    name = "bad"

    def collect(self):
        return self._safe_collect(self._boom)

    def _boom(self):
        raise RuntimeError("nope")


def test_safe_collect_returns_results_on_success():
    assert _OkSource().collect() == [1, 2, 3]


def test_safe_collect_swallows_exceptions():
    assert _BadSource().collect() == []
