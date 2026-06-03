"""LinkedIn source via Job-Alert EMAIL ingestion (IMAP) — no scraping/login.

You create Job Alerts on LinkedIn; LinkedIn emails you matching jobs. This source
reads *your own* inbox over IMAP and parses those alert emails. ToS-clean, stdlib
only, and resilient: any failure (creds, network, changed template) is logged and
yields an empty result via ``Source._safe_collect``.

``parse()`` is pure and unit-tested against a saved fixture; the IMAP fetch is kept
separate so it never runs in tests.
"""

from __future__ import annotations

import email
import html as _html
import imaplib
import logging
import re
from datetime import date, timedelta
from email.message import Message

from ..config import LinkedInEmailConfig, Secrets
from ..models import Job
from .base import Source

logger = logging.getLogger(__name__)

# Anchor pointing at a concrete job posting: capture full href, the numeric id,
# and the link text (title). Search/unsubscribe links use other paths and are
# naturally excluded.
_JOB_LINK_RE = re.compile(
    r'<a\b[^>]*href="([^"]*?/jobs/view/(\d+)[^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BLOCK_SPLIT_RE = re.compile(r"</(?:td|p|div|tr|span|a|h[1-6])>", re.IGNORECASE)
_GENERIC_TITLES = {
    "view job", "view jobs", "see all jobs", "see more jobs", "view all jobs",
    "see jobs", "view", "apply", "apply now",
}


def _text(fragment: str) -> str:
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _looks_remote(value: str) -> bool:
    low = value.lower()
    return "remote" in low or "anywhere" in low


def parse(html_text: str) -> list[Job]:
    """Parse a LinkedIn Job-Alert email's HTML into Jobs (pure, offline-testable).

    Title + clean job URL + id are extracted reliably; company/location are a
    best-effort read of the text block following each job link.
    """
    matches = list(_JOB_LINK_RE.finditer(html_text))
    jobs: list[Job] = []
    seen: set[str] = set()
    for i, m in enumerate(matches):
        job_id, title = m.group(2), _text(m.group(3))
        if not title or title.lower() in _GENERIC_TITLES or job_id in seen:
            continue
        seen.add(job_id)

        block_end = matches[i + 1].start() if i + 1 < len(matches) else m.end() + 500
        tokens = [t for t in (_text(p) for p in _BLOCK_SPLIT_RE.split(html_text[m.end():block_end])) if t]
        company = tokens[0] if tokens else ""
        location = ""
        for tok in tokens[1:4]:
            low = tok.lower()
            if "," in tok or _looks_remote(tok) or "hybrid" in low or "on-site" in low or "onsite" in low:
                location = tok
                break

        jobs.append(Job(
            source="linkedin",
            external_id=job_id,
            title=title,
            company=company,
            url=f"https://www.linkedin.com/jobs/view/{job_id}/",
            location=location,
            remote=_looks_remote(location),
            summary="",
        ))
    return jobs


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def _html_part(msg: Message) -> str:
    """Return the message's HTML body (falling back to plain text)."""
    htmls, texts = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype == "text/html":
            htmls.append(_decode(part))
        elif ctype == "text/plain":
            texts.append(_decode(part))
    return "\n".join(htmls) or "\n".join(texts)


class LinkedInEmailSource(Source):
    name = "linkedin"

    def __init__(self, config: LinkedInEmailConfig, secrets: Secrets, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.secrets = secrets

    def collect(self) -> list[Job]:
        return self._safe_collect(self._fetch_and_parse)

    def _fetch_and_parse(self) -> list[Job]:
        cfg, sec = self.config, self.secrets
        since = (date.today() - timedelta(days=max(0, cfg.max_age_days))).strftime("%d-%b-%Y")
        conn = imaplib.IMAP4_SSL(cfg.imap_host)
        try:
            conn.login(sec.imap_username, sec.imap_password)
            conn.select(cfg.imap_folder)
            seen: dict[str, Job] = {}
            for sender in cfg.senders:
                typ, data = conn.search(None, f'(FROM "{sender}" SINCE {since})')
                if typ != "OK" or not data or not data[0]:
                    continue
                for num in data[0].split()[-cfg.limit:]:
                    typ, msg_data = conn.fetch(num, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    for job in parse(_html_part(msg)):
                        seen.setdefault(job.dedup_key, job)
                    if cfg.mark_seen:
                        conn.store(num, "+FLAGS", "\\Seen")
            return list(seen.values())
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - logout best-effort
                pass
