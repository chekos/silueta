"""Semantic type validators.

Validators run in-process over sampled non-null values; only the aggregate
result — type, match rate, severity — ever reaches a profile. High-severity
types (SSN-like, credit card, NPI) alert on any hit regardless of rate:
sparse PII is exactly what must not slip through.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

HIGH_SEVERITY = {"us_ssn", "credit_card", "us_healthcare_npi", "us_dea_number", "mrn_like"}

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "uuid": re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    "us_zip": re.compile(r"\d{5}$"),
    "us_zip4": re.compile(r"\d{5}-\d{4}$"),
    "us_phone": re.compile(r"(\+?1[\s.-]?)?(\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}$"),
    "ipv4": re.compile(r"((25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(25[0-5]|2[0-4]\d|1?\d?\d)$"),
    "iso_date": re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$"),
    "us_date": re.compile(r"(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](\d{4}|\d{2})$"),
    # Structural shape only: real ICD-10 validation needs the CMS code list
    # (public domain, ~70k codes) — tracked as an optional data pack. The
    # first letter is restricted to valid chapters to cut false positives.
    "icd10_shape": re.compile(r"[A-TV-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$"),
}

_SSN = re.compile(r"(\d{3})-?(\d{2})-?(\d{4})$")
_DEA = re.compile(r"([A-Za-z])([A-Za-z9])(\d{7})$")


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def is_plausible_ssn(value: str) -> bool:
    m = _SSN.fullmatch(value)
    if not m:
        return False
    area, group, serial = m.groups()
    if area in {"000", "666"} or area >= "900":
        return False
    return group != "00" and serial != "0000"


def is_credit_card(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value)
    return 13 <= len(digits) <= 19 and digits.isdigit() and luhn_valid(digits)


def is_npi(value: str) -> bool:
    """NPI: 10 digits, Luhn-valid over an '80840' prefix on the first 9."""
    if not re.fullmatch(r"\d{10}", value):
        return False
    return luhn_valid("80840" + value)


def is_dea(value: str) -> bool:
    """DEA number: two letters + 7 digits; check digit is the ones digit of
    (d1+d3+d5) + 2*(d2+d4+d6)."""
    m = _DEA.fullmatch(value)
    if not m:
        return False
    d = [int(ch) for ch in m.group(3)]
    check = (d[0] + d[2] + d[4]) + 2 * (d[1] + d[3] + d[5])
    return check % 10 == d[6]


_CHECKS = {
    "us_ssn": is_plausible_ssn,
    "credit_card": is_credit_card,
    "us_healthcare_npi": is_npi,
    "us_dea_number": is_dea,
}

# Tier-1: column-name token signals. Cheap, touches no data, and catches what
# value shapes cannot (an MRN has no national format — the name is the signal).
_NAME_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    ("us_ssn", re.compile(r"\bssn\b|social.?security", re.IGNORECASE)),
    ("mrn_like", re.compile(r"\bmrn\b|med(ical)?.?rec(ord)?.?(num|no|nbr|#)?", re.IGNORECASE)),
    ("dob", re.compile(r"\bdob\b|date.?of.?birth|birth.?date", re.IGNORECASE)),
    ("us_healthcare_npi", re.compile(r"\bnpi\b", re.IGNORECASE)),
    ("us_dea_number", re.compile(r"\bdea\b", re.IGNORECASE)),
    ("us_zip", re.compile(r"\bzip\b|postal.?code", re.IGNORECASE)),
    ("us_phone", re.compile(r"\bphone\b|\bfax\b|\bmobile\b|\btel\b", re.IGNORECASE)),
    ("email", re.compile(r"\be?mail\b", re.IGNORECASE)),
    ("person_name", re.compile(r"(first|last|full|patient|member|middle).?name", re.IGNORECASE)),
]


def name_signals(column_name: str) -> list[str]:
    return [semantic for semantic, pattern in _NAME_SIGNALS if pattern.search(column_name)]


def mrn_heuristic(column_name: str, uniqueness_ratio: float | None, masks: list[dict]) -> bool:
    """MRNs have no national format: flag when the NAME says medical-record
    and the SHAPE behaves like an identifier (near-unique, one dominant
    digit-heavy mask)."""
    if "mrn_like" not in name_signals(column_name):
        return False
    if uniqueness_ratio is None or uniqueness_ratio < 0.9:
        return False
    if masks:
        top = masks[0]["mask"]
        digits = sum(1 for ch in top if ch == "9")
        return digits >= max(4, len(top) // 2) or top.startswith(("AAA-", "A9"))
    return True


@dataclass
class SemanticHit:
    type: str
    match_rate: float
    severity: str


def classify_sample(values: Iterable[str], min_rate: float = 0.6) -> list[SemanticHit]:
    """Classify a sample of non-null string values. Returns hits sorted by rate.

    Pattern types report only above `min_rate`; high-severity checksum types
    report on any hit so they can drive alerts.
    """
    values = [v for v in values if v]
    if not values:
        return []
    n = len(values)
    hits: list[SemanticHit] = []

    for name, pattern in _PATTERNS.items():
        matched = sum(1 for v in values if pattern.fullmatch(v.strip()))
        rate = matched / n
        if rate >= min_rate:
            hits.append(SemanticHit(name, round(rate, 4), "standard"))

    for name, check in _CHECKS.items():
        matched = sum(1 for v in values if check(v.strip()))
        if matched > 0:
            hits.append(SemanticHit(name, round(matched / n, 4), "high"))

    hits.sort(key=lambda h: -h.match_rate)
    return hits
