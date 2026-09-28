# 01: Walking skeleton + exact 1:1 gate match

**What to build:** A user can `pip install` the package, define Records, build a gate-only `ReconcileConfig` (Amount + Date), call `reconcile(left, right, config)`, and get back a `ReconcileResult` whose 1:1 matches are correct and whose unmatched Records are returned as left and right residuals. This is the tracer bullet: the narrowest complete path through packaging, domain types, and the public entrypoint, with exact (gate-only) matching as the first behavior.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Package is installable and typed: `pyproject.toml` with a pinned Python floor, `py.typed` shipped, package importable.
- [ ] Domain types exist and are typed: Record (Amount required; optional Date, Reference, Counterparty, Record id), `FieldRule` (field, role `gate`/`grade`, tolerance or weight), `ReconcileConfig` (rules, threshold, ambiguity_epsilon, max_subset_size default 4, max_group_size, scorer), `Match` (left_ids tuple, right_ids tuple, score, reasons, ambiguous bool), `ReconcileResult` (matches, left_residuals, right_residuals, ambiguous view). Config and result are immutable/frozen.
- [ ] `ReconcileConfig` construction rejects a config with no Amount gate rule.
- [ ] `reconcile(left, right, config)` matches 1:1 on a gate-only config: a Left/Right pair within Amount tolerance (absolute or percentage) AND within the Date ± day window matches; a pair failing either gate does not.
- [ ] A gate-only match has score 1.0 and carries a Match reason recording which gates passed.
- [ ] Records matching nothing are returned in `left_residuals` / `right_residuals`, split by side.
- [ ] Output ordering is deterministic: stable, broken by Record id then input position.
- [ ] Engine is pure — no wall-clock, no randomness, no IO (ADR-0004).
- [ ] pytest suite tests the above through the `reconcile()` seam only (no reaching into internals). Establishes the seam-1 test pattern.
