"""Build the list of enabled sources from config."""

from __future__ import annotations

from ..config import Config, Secrets
from .base import Source
from .comeet import ComeetSource
from .greenhouse import GreenhouseSource
from .jobicy import JobicySource
from .lever import LeverSource
from .linkedin_email import LinkedInEmailSource
from .remotive import RemotiveSource
from .weworkremotely import WeWorkRemotelySource


def build_sources(config: Config, secrets: Secrets | None = None) -> list[Source]:
    """Instantiate every enabled source. Disabled sources are skipped.

    Greenhouse/Lever are skipped when no boards are configured so an
    enabled-but-empty source doesn't make a pointless network call. LinkedIn
    (email ingestion) is skipped unless IMAP credentials are present.
    """
    sources: list[Source] = []
    s = config.sources
    if s.remotive.enabled:
        sources.append(RemotiveSource(s.remotive))
    if s.jobicy.enabled:
        sources.append(JobicySource(s.jobicy))
    if s.weworkremotely.enabled and s.weworkremotely.feeds:
        sources.append(WeWorkRemotelySource(s.weworkremotely))
    if s.greenhouse.enabled and s.greenhouse.boards:
        sources.append(GreenhouseSource(s.greenhouse))
    if s.lever.enabled and s.lever.boards:
        sources.append(LeverSource(s.lever))
    if s.comeet.enabled and s.comeet.companies:
        sources.append(ComeetSource(s.comeet))
    if s.linkedin.enabled and secrets is not None and secrets.is_imap_configured:
        sources.append(LinkedInEmailSource(s.linkedin, secrets))
    return sources
