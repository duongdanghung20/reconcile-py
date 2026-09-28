# 04: Bounded split matches (1:many, both directions) + determinism property test

**What to build:** A user can reconcile batch settlements (one bank payment covering several invoices) and installment payments (one invoice settled by several payments). After the 1:1 pass, the engine searches the residuals for subsets whose Amounts sum, within tolerance, to an opposite-side Record — bounded so pathological inputs leave records as residuals instead of hanging. A whole-engine property test locks reproducibility across every match type.

**Blocked by:** 03

**Status:** done

- [x] Split search runs only on residuals left after the 1:1 pass (ADR-0007).
- [x] For a residual Record, opposite-side residuals are grouped by passing its gates (Date window, Counterparty if configured), then subsets whose Amount sums within tolerance of the residual's Amount are found.
- [x] Split search is symmetric: one Left → many Right and one Right → many Left both work; a `Match` carries the many side in its `left_ids` / `right_ids` tuple.
- [x] Search is bounded by `max_subset_size` (default 4) and `max_group_size`; above the group cap the Record stays a Residual, no exponential blowup (ADR-0007).
- [x] Split matches carry a Match reason and participate in deterministic ordering.
- [x] Property test: shuffling the input order of Left and Right sets produces an identical `ReconcileResult` (matches, residuals, ordering) across gate-only, graded, ambiguous, and split scenarios — locks ADR-0004 end to end.
- [x] Tests through the seam cover: Left→many split, Right→many split, subset-size cap → residual, group-size cap → residual, split only after 1:1.
