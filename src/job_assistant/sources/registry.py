"""Build the list of enabled sources from config."""

from __future__ import annotations

from ..config import Config
from .base import Source
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .remotive import RemotiveSource
from .weworkremotely import WeWorkRemotelySource


def build_sources(config: Config) -> list[Source]:
    """Instantiate every enabled source. Disabled sources are skipped.

    Greenhouse/Lever are also skipped when no boards are configured so an
    enabled-but-empty source doesn't make a pointless network call.
    """
    sources: list[Source] = []
    s = config.sources
    if s.remotive.enabled:
        sources.append(RemotiveSource(s.remotive))
    if s.weworkremotely.enabled and s.weworkremotely.feeds:
        sources.append(WeWorkRemotelySource(s.weworkremotely))
    if s.greenhouse.enabled and s.greenhouse.boards:
        sources.append(GreenhouseSource(s.greenhouse))
    if s.lever.enabled and s.lever.boards:
        sources.append(LeverSource(s.lever))
    return sources
