# AGENTS.md

Boundaries that always apply when working in this repository:

1. **The safety contract is the product.** No change may cause a raw cell value
   to appear in any silueta output (profile.json, reports, generated
   scaffolds). `tests/test_contract.py` gates this; extend it when adding any
   new output surface. When a statistic could reveal a value (min/max on
   strings/dates, masks on constant or sub-k values), suppress or coarsen —
   never emit.
2. **Never weaken suppression defaults** (k-threshold, constant-column
   reporting, small-table structure-only mode) without an explicit maintainer
   decision recorded in the PR.
3. Claims about privacy use the phrase "no raw values by construction" —
   never "anonymized" or "private."
4. Use `uv` for everything (`uv run pytest`, `uv run ruff check .`).
   Temporal plans live in GitHub issues, not in repo docs; design docs go in
   `docs/` with a date prefix.
