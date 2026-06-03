"""Configuration loading and validation.

Preferences come from a YAML file (non-secret, committed). Secrets come
from environment variables (or a local .env during development).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

try:  # python-dotenv is only needed for local development.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


# --- Source configs -------------------------------------------------------

class RemotiveConfig(BaseModel):
    enabled: bool = True
    # Remotive category slugs, e.g. "software-dev". Empty => all categories.
    categories: list[str] = Field(default_factory=lambda: ["software-dev"])
    search: str = ""
    limit: int = 100


class WeWorkRemotelyConfig(BaseModel):
    enabled: bool = True
    # WWR RSS feed slugs, e.g. "remote-programming-jobs".
    feeds: list[str] = Field(default_factory=lambda: ["remote-programming-jobs"])


class GreenhouseConfig(BaseModel):
    enabled: bool = False
    # Greenhouse board tokens (the company slug in the board URL).
    boards: list[str] = Field(default_factory=list)


class LeverConfig(BaseModel):
    enabled: bool = False
    # Lever company slugs.
    boards: list[str] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    remotive: RemotiveConfig = Field(default_factory=RemotiveConfig)
    weworkremotely: WeWorkRemotelyConfig = Field(default_factory=WeWorkRemotelyConfig)
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    lever: LeverConfig = Field(default_factory=LeverConfig)


# --- Filtering ------------------------------------------------------------

class FiltersConfig(BaseModel):
    # A job matches if its title/summary contains any allow keyword/title and
    # none of the deny keywords, and passes the remote/location/seniority gates.
    titles_allow: list[str] = Field(default_factory=list)
    keywords_allow: list[str] = Field(default_factory=list)
    keywords_deny: list[str] = Field(default_factory=list)

    locations_allow: list[str] = Field(default_factory=list)
    locations_deny: list[str] = Field(default_factory=list)

    # any | remote_only | onsite_only
    remote: str = "any"

    seniority_allow: list[str] = Field(default_factory=list)
    seniority_deny: list[str] = Field(default_factory=list)

    # Minimum number of allow-list hits required to keep a job.
    min_match_score: int = 1

    # Ranking only: jobs matching these terms (in title/summary/location) get
    # `boost_weight` added to their score so they sort to the top of the digest.
    # Boost never lets a job bypass the allow gate; empty list = no effect.
    boost_keywords: list[str] = Field(default_factory=list)
    boost_weight: int = 3


class DigestConfig(BaseModel):
    max_jobs: int = 25
    summary_chars: int = 280
    timezone: str = "UTC"


class Config(BaseModel):
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)


# --- Secrets --------------------------------------------------------------

class Secrets(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


# --- Loaders --------------------------------------------------------------

DEFAULT_CONFIG_PATHS = ("config/config.local.yaml", "config/config.yaml", "config/config.example.yaml")


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load preferences from YAML, falling back to sensible defaults.

    Resolution order when ``path`` is None: config.local.yaml ->
    config.yaml -> config.example.yaml -> built-in defaults.
    """
    candidates = [path] if path else list(DEFAULT_CONFIG_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            data = yaml.safe_load(Path(candidate).read_text(encoding="utf-8")) or {}
            return Config.model_validate(data)
    return Config()


def load_secrets() -> Secrets:
    """Read secrets from environment (loading a local .env if present)."""
    load_dotenv()
    return Secrets(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )
