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

HIGH_SEVERITY = {"us_ssn", "credit_card", "us_healthcare_npi"}

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "uuid": re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    "us_zip": re.compile(r"\d{5}$"),
    "us_zip4": re.compile(r"\d{5}-\d{4}$"),
    "us_phone": re.compile(r"(\+?1[\s.-]?)?(\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}$"),
    "ipv4": re.compile(r"((25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(25[0-5]|2[0-4]\d|1?\d?\d)$"),
    "iso_date": re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$"),
}

_SSN = re.compile(r"(\d{3})-?(\d{2})-?(\d{4})$")


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


_CHECKS = {
    "us_ssn": is_plausible_ssn,
    "credit_card": is_credit_card,
    "us_healthcare_npi": is_npi,
}


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
