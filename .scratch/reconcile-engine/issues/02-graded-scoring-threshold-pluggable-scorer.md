# 02: Graded scoring + threshold + pluggable Scorer

**What to build:** A user can add Reference and/or Counterparty as graded fields to their config and reconcile records whose text differs in trivial ways ("INV-1024" vs "inv 1024", "ACME Ltd" vs "ACME Limited"). Candidates that pass the Amount/Date gates are scored by a weighted mean of graded-field Similarities and accepted only when the score clears the configured threshold. A default, zero-dependency Scorer ships, and a user can inject their own.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Reference and Counterparty can be configured as graded fields with per-field weights.
- [ ] Default Scorer computes Similarity (0..1) by normalizing strings (case-fold, strip punctuation/whitespace) and using `difflib.SequenceMatcher`; no non-stdlib dependency (ADR-0005).
- [ ] Match score is the weighted mean of graded-field Similarities; weights configurable, equal by default.
- [ ] A candidate matches only when it passes all gates AND `score ≥ threshold`.
- [ ] Gate-only config (no graded fields) still yields score 1.0 (regression on T01 behavior).
- [ ] A caller-supplied Scorer can be injected via `ReconcileConfig` and changes matching outcomes.
- [ ] Each Match reason records every graded field's Similarity alongside the gate passes.
- [ ] Amount stays a hard gate: a pair with a perfect Reference/Counterparty but Amount outside tolerance does not match (ADR-0003).
- [ ] Tests through the `reconcile()` seam cover: scoring, weight effect, threshold boundary, string normalization, custom-scorer injection. Determinism holds.
