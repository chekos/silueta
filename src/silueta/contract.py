"""The safety contract: what a silueta profile may and may not contain.

Every emitter in this codebase routes through the rules here. The contract is
"no raw cell values by construction" — not "private" and not "anonymized".
"""

from __future__ import annotations

DEFAULT_K = 5

CONTRACT_STATEMENT = (
    "This profile contains no raw cell values by construction: no samples, no "
    "frequent values, no string/date min-max, no serialized sketches or value "
    "hashes. Statistics derived from values observed in fewer than k rows are "
    "suppressed or coarsened. It protects against accidental context leakage "
    "(values entering an LLM conversation, a log, a ticket); it does not claim "
    "formal anonymity against adversarial reconstruction of small populations."
)


def small_table(row_count: int, k: int = DEFAULT_K) -> bool:
    """Tables with fewer than k rows get structure-only profiles."""
    return row_count < k


def suppress_mask_counts(
    mask_counts: list[tuple[str, int]], k: int = DEFAULT_K, top: int = 5
) -> tuple[list[dict], float]:
    """Apply value-level k-suppression to a mask frequency list.

    Masks covering fewer than k rows are rolled into a suppressed bucket;
    only the `top` most frequent surviving masks are reported. Returns the
    reported masks (with coverage ratios) and the suppressed share.
    """
    total = sum(count for _, count in mask_counts)
    if total == 0:
        return [], 0.0
    kept = [(mask, count) for mask, count in mask_counts if count >= k]
    kept.sort(key=lambda mc: -mc[1])
    reported = [
        {"mask": mask, "coverage": round(count / total, 4)} for mask, count in kept[:top]
    ]
    reported_total = sum(count for _, count in kept[:top])
    suppressed_share = round((total - reported_total) / total, 4)
    return reported, suppressed_share
