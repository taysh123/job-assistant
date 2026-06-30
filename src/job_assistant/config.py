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


class ComeetCompany(BaseModel):
    uid: str
    token: str
    name: str = ""  # optional display label; falls back to the API's company_name


class ComeetConfig(BaseModel):
    enabled: bool = False
    # One entry per company; uid+token come from the company's public Careers API
    # (Settings -> Careers Website -> Careers API on Comeet).
    companies: list[ComeetCompany] = Field(default_factory=list)


class LinkedInEmailConfig(BaseModel):
    # LinkedIn coverage via Job-Alert EMAIL ingestion (no scraping/login). You
    # create alerts on LinkedIn; LinkedIn emails matching jobs; we read your
    # inbox over IMAP and parse them. Needs IMAP_USERNAME/IMAP_PASSWORD secrets.
    enabled: bool = False
    imap_host: str = "imap.gmail.com"
    imap_folder: str = "INBOX"
    senders: list[str] = Field(default_factory=lambda: [
        "jobalerts-noreply@linkedin.com",
        "jobs-noreply@linkedin.com",
    ])
    max_age_days: int = 3
    mark_seen: bool = False
    limit: int = 50


class SourcesConfig(BaseModel):
    remotive: RemotiveConfig = Field(default_factory=RemotiveConfig)
    weworkremotely: WeWorkRemotelyConfig = Field(default_factory=WeWorkRemotelyConfig)
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    lever: LeverConfig = Field(default_factory=LeverConfig)
    comeet: ComeetConfig = Field(default_factory=ComeetConfig)
    linkedin: LinkedInEmailConfig = Field(default_factory=LinkedInEmailConfig)


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

    # Title-only hard exclusion of role *types* that aren't software-developer
    # jobs (e.g. "sales engineer", "support engineer", recruiter). Matched against
    # the title only, so a dev JD merely mentioning the word in its summary stays.
    titles_deny: list[str] = Field(default_factory=list)

    # Minimum number of allow-list hits required to keep a job.
    min_match_score: int = 1

    # Experience-requirement handling (keeps the search junior-friendly).
    # A role is acted on only if it *explicitly* requires more than
    # max_years_experience. experience_mode: downrank (penalise, stay visible) |
    # filter (exclude) | off. Generic roles with no stated years are untouched.
    max_years_experience: int = 2
    experience_mode: str = "downrank"
    experience_penalty: int = 8

    # Ranking only: jobs matching these terms (in title/location) get
    # `boost_weight` added to their score so they sort to the top of the digest.
    # Boost never lets a job bypass the allow gate; empty list = no effect.
    boost_keywords: list[str] = Field(default_factory=list)
    boost_weight: int = 3

    # Ranking only: explicit junior/graduate/entry signals (matched in the title)
    # add `junior_boost_weight` — set higher than the location boost so genuine
    # entry-level roles sort to the very top regardless of location.
    junior_boost_keywords: list[str] = Field(default_factory=list)
    junior_boost_weight: int = 8


class DigestConfig(BaseModel):
    max_jobs: int = 25
    summary_chars: int = 280
    timezone: str = "UTC"
    # Jobs shown per page in the single paginated digest message (1 = one card
    # at a time, browsed with Prev/Next).
    page_size: int = 1
    # When a run finds no new jobs, stay silent (no "no new jobs" message). The
    # run is still recorded in the runs table. Set true to be pinged every run.
    notify_empty: bool = False


class Config(BaseModel):
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)


# --- Secrets --------------------------------------------------------------

class Secrets(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    imap_username: str = ""
    imap_password: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def is_imap_configured(self) -> bool:
        return bool(self.imap_username and self.imap_password)


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
        imap_username=os.getenv("IMAP_USERNAME", ""),
        imap_password=os.getenv("IMAP_PASSWORD", ""),
    )
