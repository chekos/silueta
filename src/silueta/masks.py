"""Value-shape masks: digits become 9, uppercase A, lowercase a.

Punctuation and other symbols pass through, so '123-45-6789' -> '999-99-9999'
and 'Smith, John' -> 'Aaaaa, Aaaa'. The mask preserves structure while carrying
no value content; k-suppression in `contract` decides which masks are reported.
"""

from __future__ import annotations

import re

_DIGIT = re.compile(r"[0-9]")
_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
# Any non-ASCII character (accented letters, non-Latin scripts) becomes 'x'
# so the mask stays value-free. Applied last, after the ASCII substitutions.
_NON_ASCII = re.compile(r"[^\x00-\x7F]")


def mask_value(value: str) -> str:
    masked = _DIGIT.sub("9", value)
    masked = _UPPER.sub("A", masked)
    masked = _LOWER.sub("a", masked)
    masked = _NON_ASCII.sub("x", masked)
    return masked


# The same transformation, as DuckDB SQL over a column expression.
def mask_sql(column_sql: str) -> str:
    return (
        "regexp_replace(regexp_replace(regexp_replace(regexp_replace("
        f"{column_sql}, '[0-9]', '9', 'g'), '[A-Z]', 'A', 'g'), "
        "'[a-z]', 'a', 'g'), '[^\\x00-\\x7F]', 'x', 'g')"
    )
