# Spec: reconcile-py core matching engine

Status: ready-for-agent

## Problem Statement

People reconciling money have two lists that should agree but don't line up cleanly: bank transactions on one side, and invoices or ledger entries on the other. The same payment shows up with a slightly different date, a rounded amount, a messy free-text reference, and a payee name spelled three ways. One bank payment often settles several invoices at once, and one invoice is sometimes paid in installments. Matching this by hand is slow and error-prone, and ad-hoc scripts give different answers on different runs, so nobody trusts the result or can explain why a given pair was matched.

## Solution

A Python library that fuzzy-matches one set of financial records against another under tolerance rules the caller configures, and returns a result that is deterministic (same inputs and config always produce the same output), explainable (every match records why it was made), and honest about uncertainty (near-tie matches are flagged for review rather than guessed). The caller supplies their own record types; the engine is a generic pairwise matcher, not tied to any particular bank/invoice/ledger schema. Callers who keep their data in pandas get a thin adapter so they need not hand-build records.

Vocabulary in this spec follows `CONTEXT.md`. Architectural decisions are recorded in `docs/adr/0001`–`0007`; this spec assumes them and does not re-argue them.

## User Stories

1. As a library user, I want to match a Left set of Records against a Right set through a single call, so that I get all matches and residuals in one deterministic pass.
2. As a library user, I want to supply my own typed record types rather than a fixed bank/invoice schema, so that the engine fits whatever domain model my project already uses.
3. As a library user, I want to declare which side is Left and which is Right freely, so that I can reconcile bank↔invoice, bank↔ledger, or invoice↔ledger with the same engine.
4. As a library user, I want to reconcile three sources by composing two pairwise passes, so that three-way reconciliation needs no special engine mode.
5. As a library user, I want Amount to be a mandatory matching criterion, so that no two records are ever matched when their money doesn't agree within tolerance.
6. As a library user, I want to configure amount tolerance as either an absolute value or a percentage, so that I can express "within one cent" or "within 0.5%" as my data demands.
7. As a library user, I want Date matched within a ± day window I set, so that a payment posting a few days after its invoice still matches.
8. As a library user, I want Amount and Date to act as hard gates, so that a pair failing either can never match regardless of how similar its text is.
9. As a library user, I want Reference and Counterparty compared as fuzzy graded fields, so that "INV-1024" vs "inv 1024" and "ACME Ltd" vs "ACME Limited" still score as close.
10. As a library user, I want graded string comparison to normalize case, punctuation, and whitespace before scoring, so that trivial formatting differences don't lower a score.
11. As a library user, I want each graded field's contribution weighted by a configurable weight, so that I can make Counterparty matter more than Reference when that fits my data.
12. As a library user, I want a match accepted only when its score clears a threshold I set, so that I control how strict matching is.
13. As a library user, I want a pass configured with only gate fields (no graded fields) to still work, treating any gate-passing candidate as a full match, so that exact-only reconciliation is a supported mode.
14. As a library user, I want one bank payment to match many invoices (a split match), so that batch settlements reconcile.
15. As a library user, I want one invoice to match many bank payments (a split match in the other direction), so that installment payments reconcile.
16. As a library user, I want split matches discovered only after the 1:1 pass, so that easy exact matches are claimed before the engine searches combinations.
17. As a library user, I want split search bounded by a max subset size and a max group size, so that pathological inputs leave records as residuals instead of hanging.
18. As a library user, I want records that match nothing returned as residuals, split by side, so that I can see exactly what went unmatched on the Left and on the Right.
19. As a library user, I want every Match to carry its reason (which gates passed, each graded field's similarity), so that I can audit or display why a match was made without re-running the pass.
20. As a library user, I want the whole result to be immutable, so that I can pass it around and persist it without fear of mutation.
21. As a library user, I want two candidates whose scores fall within an epsilon flagged as an Ambiguous match rather than silently resolved, so that genuinely uncertain matches surface for review.
22. As a library user, I want ambiguous matches to stay inside the matches list flagged in place, plus a convenience view of just the ambiguous ones, so that I can't accidentally forget to check them.
23. As a library user, I want the same records and config to always produce byte-identical output, so that runs are reproducible and comparable over time.
24. As a library user, I want output ordering to be stable, broken by a caller-supplied Record id and falling back to input position, so that determinism holds even when scores tie.
25. As a library user, I want to plug in my own Scorer for graded fields, so that I can use a different string algorithm without editing the engine.
26. As a library user, I want a working default Scorer with no extra dependencies, so that the library is useful out of the box.
27. As a pandas user, I want to build Left/Right record sets from DataFrames via an adapter, so that I don't hand-construct records when my data is already tabular.
28. As a pandas user, I want to convert a `ReconcileResult` back to DataFrames, so that I can feed matches and residuals into the rest of my pandas pipeline.
29. As a pandas user, I want the adapter to be the only place pandas touches, so that the core stays typed and free of dtype surprises.
30. As a library user, I want a typed public API (type hints on entrypoint, config, records, result), so that my type checker catches misuse before runtime.
31. As a library user, I want configuration collected in one immutable `ReconcileConfig` object, so that a pass is fully described by its inputs plus one config value.
32. As a library user, I want per-field tolerance and weight to live on that field's rule, so that configuration isn't scattered across global settings.
33. As a maintainer, I want the package installable from PyPI with a pinned Python floor, so that consumers can depend on it normally.
34. As a maintainer, I want a full pytest suite exercising the engine through its public seam, so that behavior is locked down against regressions.

## Implementation Decisions

**Modules**

- **Engine** — the pairwise matcher. Public entrypoint `reconcile(left, right, config) -> ReconcileResult`. Pure: no wall-clock, no randomness, no IO. Internally runs gate filtering → candidate scoring → threshold → greedy resolution with ambiguity flagging → bounded split search on residuals. (ADR-0001, 0003, 0004, 0006, 0007)
- **Records / domain types** — a Record is a caller-facing typed structure carrying at least Amount, plus optional Date, Reference, Counterparty, and an optional Record id. Left and Right sets are ordinary sequences of Records; the engine treats the sides symmetrically. (ADR-0001; CONTEXT: Record, Left/Right set)
- **Config** — `ReconcileConfig`, immutable, holding: a list of `FieldRule`s; global `threshold`; `ambiguity_epsilon`; `max_subset_size` (default 4); `max_group_size`; and the `scorer`. Each `FieldRule` names a criteria field, its role (`gate` or `grade`), and either its tolerance (Amount: absolute or percentage; Date: ± days) or its weight (graded fields). Amount must be present as a gate rule; construction rejects a config without it. (Q5, Q6, Q8, Q11)
- **Result** — `ReconcileResult`, frozen, with `matches: list[Match]`, `left_residuals`, `right_residuals`, and an `ambiguous` convenience view over `matches`. A `Match` is frozen with `left_ids: tuple`, `right_ids: tuple` (tuples carry 1:1 and split in either direction), `score`, `reasons` (per-gate pass + per-graded similarity), and `ambiguous: bool`. (Q10)
- **Scorer** — a pluggable component computing a graded field's Similarity (0..1). Default normalizes strings (case-fold, strip punctuation/whitespace) and uses `difflib.SequenceMatcher`. Injected via `ReconcileConfig`; no separate registration. (ADR-0005)
- **DataFrame adapter** — `from_dataframe` (DataFrame + column mapping → Records) and `to_dataframe` (`ReconcileResult` → DataFrames of matches and residuals). The only module importing pandas. (ADR-0002)

**Behavior contracts**

- **Gates before grades.** A candidate pair outside any gate's tolerance is rejected before scoring. Amount and Date are gates. (ADR-0003)
- **Score.** Weighted mean of graded-field Similarities; gate-only config yields score 1.0. Accept when `score ≥ threshold`. (ADR-0005)
- **Resolution.** All accepted candidates sorted by descending score; assigned best-first; each record consumed once (a record may appear in one Match only). Ties broken by Record id then input position → deterministic. (ADR-0004, 0006)
- **Ambiguity.** When the top two competing candidates for a record score within `ambiguity_epsilon`, emit an Ambiguous match flagged in place rather than choosing silently. (ADR-0006)
- **Splits.** Attempted only on residuals after the 1:1 pass. For a residual, group opposite-side residuals passing its gates, then search subsets whose Amount sums within tolerance of the residual's Amount, bounded by `max_subset_size` and `max_group_size`; over the group cap, leave as residual. Symmetric in both directions. (ADR-0007)
- **Sign convention** for Amount (payment negative vs invoice positive) is normalized by the caller / adapter, not inferred by the engine. (Q5)

## Testing Decisions

- **What a good test is here:** asserts on external behavior observed through a seam — the `ReconcileResult` returned by `reconcile()`, or the DataFrames returned by the adapter. Tests never reach into engine internals (candidate lists, intermediate scores, private helpers). A test names the scenario in `CONTEXT.md` vocabulary (gate, grade, split match, residual, ambiguous match).
- **Seam 1 — `reconcile(left, right, config)`:** carries nearly all engine tests. Coverage: exact 1:1 match; amount-gate rejection (perfect reference, amount one cent out → no match, per ADR-0003); date-window boundary; graded scoring and threshold boundary; weight effect on score; gate-only config (score 1.0); split match Left→many and many→Left; split bounded by subset/group cap → residual; residuals split by side; ambiguity flag on near-tie; determinism (same input+config → identical output, including stable ordering under score ties); custom scorer injection changes outcome. A property-style determinism check (shuffle input order, assert identical result) locks ADR-0004.
- **Seam 2 — DataFrame adapter:** DataFrame → Records → `reconcile()` → DataFrames round-trip; column mapping; confirms pandas dtype quirks (NaN, object columns, float money) are handled at the boundary and never reach the engine (ADR-0002).
- **Modules tested:** Engine (via seam 1) and adapter (via seam 2). Scorer default and pluggability tested through seam 1, not a private seam.
- **Prior art:** none — greenfield. The pytest suite is built from scratch; establish the two-seam pattern above as the prior art the rest of the suite follows. No fixtures/mocks needed — the engine is a pure function, so tests are plain input/output assertions.

## Out of Scope

- **Full many-to-many matching** — deferred; 1:1 and 1:many (both directions) only. (Q3)
- **Persisted decision/event log** the caller replays from — the consuming app persists deterministic results itself. (ADR-0004)
- **Global optimal assignment (Hungarian)** — greedy + ambiguity flag chosen instead. (ADR-0006)
- **`rapidfuzz` or other non-stdlib scorers** as a default — available only as a caller-supplied Scorer / optional extra. (ADR-0005)
- **A smarter (unbounded / exact large-scale) split-search solver** — bounded subset-sum only until a consumer hits the cap. (ADR-0007)
- **Making Amount optional** — Amount is a mandatory gate.
- **CLI, GUI, persistence, ingestion connectors** — this is a library; IO beyond the pandas adapter is the caller's.

## Further Notes

- **Deliberate shortcuts to track** (`ponytail:` ledger): (1) default Scorer is `difflib`; swap in `rapidfuzz` behind the pluggable seam only if similarity quality or hot-path speed measurably falls short. (2) Split search is bounded subset-sum; a smarter solver only if a consumer hits the cap on real data.
- **Packaging:** PyPI distribution, typed (ship `py.typed`), full pytest suite. Python version floor to be pinned during `/to-tickets` or first implementation ticket.
- **Determinism is a hard requirement, not an optimization** — any introduction of clock, randomness, or set-iteration-order dependence into the engine is a defect.
