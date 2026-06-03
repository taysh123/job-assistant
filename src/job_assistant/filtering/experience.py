"""Detect a job's stated minimum years-of-experience requirement.

Used to keep the search junior-friendly: roles that explicitly demand more
experience than the user has can be down-ranked or filtered. Patterns are tied
to experience/requirement context so company boilerplate ("20 years in the
market") does not trip the detector. Returns the *minimum* requirement found
(the lowest bar a candidate must clear) so we never over-penalise.
"""

from __future__ import annotations

import re

# Sentinel years assigned to an explicit "senior-level" requirement phrase.
SENIOR_YEARS = 5

_PATTERNS = [
    # "minimum 3 years", "at least 4 years", "requires 5+ years"
    re.compile(r"(?:minimum|min\.?|at least|requires?|required)\D{0,12}(\d{1,2})\s*\+?\s*years?", re.I),
    # "3+ years of experience", "5 years software engineering experience"
    re.compile(
        r"(\d{1,2})\s*\+?\s*years?(?:\s+of)?\s+"
        r"(?:experience|industry|professional|hands[- ]?on|relevant|working|"
        r"software|engineering|development|commercial|programming)",
        re.I,
    ),
]
# Range like "3-5 years of experience" -> take the lower bound (3).
_RANGE = re.compile(r"(\d{1,2})\s*[-–]\s*\d{1,2}\s*years?(?:\s+of)?\s+(?:experience|exp)", re.I)
# Explicit senior-level requirement phrasing (not just the word "senior").
_SENIOR = re.compile(r"senior[- ]level", re.I)


def required_years(text: str) -> int | None:
    """Minimum stated years-of-experience requirement, or None if unstated."""
    if not text:
        return None
    found: list[int] = []
    for pat in _PATTERNS:
        found += [int(m) for m in pat.findall(text)]
    found += [int(m) for m in _RANGE.findall(text)]
    if _SENIOR.search(text):
        found.append(SENIOR_YEARS)
    return min(found) if found else None
