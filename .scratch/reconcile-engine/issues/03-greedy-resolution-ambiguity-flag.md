# 03: Greedy resolution + ambiguity flag

**What to build:** When several candidate matches compete for the same Record, the engine resolves them predictably instead of double-assigning, and when two candidates are too close to call, it surfaces the uncertainty as an Ambiguous match rather than guessing. A user gets a clean set of non-overlapping matches plus a clear view of the ones that need review.

**Blocked by:** 02

**Status:** done

- [x] All accepted candidate matches are resolved greedy best-first by descending Match score; each Record is consumed by at most one Match.
- [x] Resolution is deterministic: score ties are broken by Record id, then input position (ADR-0004, 0006).
- [x] When the top two competing candidates for a Record score within `ambiguity_epsilon`, an Ambiguous match is emitted flagged in place (`ambiguous = True`) instead of one being silently chosen (ADR-0006).
- [x] Ambiguous matches remain inside `matches`; `result.ambiguous` is a convenience view over just those.
- [x] Tests through the seam cover: two Left records competing for one Right (and vice versa), correct greedy assignment, consume-once, near-tie flagging, and the `result.ambiguous` view. Determinism holds.
