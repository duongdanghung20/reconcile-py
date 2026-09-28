"""The pairwise match engine. Public entrypoint: ``reconcile``.

Pure: no wall-clock, no randomness, no IO (ADR-0004). Determinism comes from
sorting records by a caller-supplied Record id, falling back to input position.

Ticket 01/02/03 scope: gate-only exact 1:1 matching, graded scoring behind a
configurable threshold and a pluggable Scorer, and greedy best-first 1:1
resolution with near-ties flagged Ambiguous. Ticket 04 adds bounded 1:many
split search over the residuals, behind this same seam.
"""

from __future__ import annotations

import difflib
import itertools
from collections.abc import Sequence
from decimal import Decimal
from functools import lru_cache
from typing import NamedTuple

from .types import FieldRule, Match, Reason, ReconcileConfig, ReconcileResult, Record, Scorer


class _Candidate(NamedTuple):
    """A pair that cleared gates and threshold, awaiting greedy resolution."""

    score: float
    li: int  # left input position
    ri: int  # right input position
    lrec: Record
    rrec: Record
    gates_passed: tuple[str, ...]
    similarities: tuple[tuple[str, float], ...]


def reconcile(
    left: Sequence[Record], right: Sequence[Record], config: ReconcileConfig
) -> ReconcileResult:
    """Match a Left set against a Right set, returning matches and residuals."""
    gate_rules = tuple(r for r in config.rules if r.role == "gate")
    grade_rules = tuple(r for r in config.rules if r.role == "grade")
    scorer = config.scorer or _default_scorer

    left_order = _ordered(left)
    right_order = _ordered(right)

    candidates: list[_Candidate] = []
    for li, lrec in left_order:
        for ri, rrec in right_order:
            gates_passed = _gates_pass(lrec, rrec, gate_rules)
            if gates_passed is None:
                continue
            score, similarities = _score(lrec, rrec, grade_rules, scorer)
            if score < config.threshold:
                continue  # passes gates but not the threshold
            candidates.append(_Candidate(score, li, ri, lrec, rrec, gates_passed, similarities))

    # Best-first, ties broken by Record id then input position (ADR-0004, 0006).
    candidates.sort(key=lambda c: (-c.score, _sort_key(c.lrec, c.li), _sort_key(c.rrec, c.ri)))

    used_left: set[int] = set()
    used_right: set[int] = set()
    matches: list[Match] = []
    for cand in candidates:
        if cand.li in used_left or cand.ri in used_right:
            continue  # a record is consumed by at most one Match
        ambiguous = _near_tie(cand, candidates, config.ambiguity_epsilon)
        used_left.add(cand.li)
        used_right.add(cand.ri)
        matches.append(
            Match(
                left_ids=(_identity(cand.lrec, cand.li),),
                right_ids=(_identity(cand.rrec, cand.ri),),
                score=cand.score,
                reasons=Reason(gates_passed=cand.gates_passed, similarities=cand.similarities),
                ambiguous=ambiguous,
            )
        )

    # Bounded 1:many split search on what the 1:1 pass left over (ADR-0007).
    left_avail = [(i, rec) for i, rec in left_order if i not in used_left]
    right_avail = [(i, rec) for i, rec in right_order if i not in used_right]
    split_matches, consumed_left, consumed_right = _split_search(
        left_avail, right_avail, gate_rules, grade_rules, scorer, config
    )
    matches.extend(split_matches)

    left_residuals = tuple(
        rec for i, rec in left_order if i not in used_left and i not in consumed_left
    )
    right_residuals = tuple(
        rec for i, rec in right_order if i not in used_right and i not in consumed_right
    )
    return ReconcileResult(tuple(matches), left_residuals, right_residuals)


def _split_search(
    left_avail: list[tuple[int, Record]],
    right_avail: list[tuple[int, Record]],
    gate_rules: tuple[FieldRule, ...],
    grade_rules: tuple[FieldRule, ...],
    scorer: Scorer,
    config: ReconcileConfig,
) -> tuple[list[Match], set[int], set[int]]:
    """Search residuals for one-to-many Amount subset-sums (ADR-0007).

    Symmetric: one Left -> many Right first, then one Right -> many Left on what
    remains. A residual joins a Record's group only if it clears that Record's
    non-Amount gates (the Date window) and the grade threshold — the same bar a
    1:1 candidate clears, minus the Amount gate the subset-sum replaces (this is
    where "Counterparty if configured" filters the group). Deterministic: the
    residual lists arrive pre-sorted (Record id, then position), subsets are
    enumerated smallest-first in that order, and the first subset summing within
    Amount tolerance wins. A record is consumed by at most one split.

    The group is capped on its cheap gate-passing size *before* the (possibly
    expensive) Scorer runs, so both scoring and subset enumeration are bounded by
    max_group_size — over the cap the Record stays a Residual rather than blow up.
    """
    amount_rules = tuple(r for r in gate_rules if r.field == "amount")
    nonamount_gates = tuple(r for r in gate_rules if r.field != "amount")
    gate_names = ("amount",) + tuple(dict.fromkeys(r.field for r in nonamount_gates))

    consumed_left: set[int] = set()
    consumed_right: set[int] = set()
    matches: list[Match] = []

    def run(
        one_side: list[tuple[int, Record]],
        many_side: list[tuple[int, Record]],
        one_consumed: set[int],
        many_consumed: set[int],
        one_is_left: bool,
    ) -> None:
        for oi, orec in one_side:
            if oi in one_consumed:
                continue
            # Cheap non-Amount gate filter first, then the cap, so the Scorer
            # never runs on (nor does subset-sum enumerate) an oversized pool.
            candidates = [
                (mi, mrec)
                for mi, mrec in many_side
                if mi not in many_consumed
                and _gate_ok(orec, mrec, one_is_left, nonamount_gates)
            ]
            if len(candidates) > config.max_group_size:
                continue  # over the cap -> stays a Residual, no blowup (ADR-0007)
            # Grade-filter + score each candidate once; carry the score forward.
            group: list[tuple[int, Record, float]] = []
            for mi, mrec in candidates:
                s = _grade_score(orec, mrec, one_is_left, grade_rules, scorer)
                if s >= config.threshold:
                    group.append((mi, mrec, s))
            subset = _find_subset(orec, group, amount_rules, config.max_subset_size)
            if subset is None:
                continue
            one_consumed.add(oi)
            many_consumed.update(mi for mi, _, _ in subset)
            one_ids = (_identity(orec, oi),)
            many_ids = tuple(_identity(mrec, mi) for mi, mrec, _ in subset)
            left_ids, right_ids = (one_ids, many_ids) if one_is_left else (many_ids, one_ids)
            score = 1.0 if not grade_rules else sum(s for _, _, s in subset) / len(subset)
            # ponytail: splits ship unflagged. Ambiguity for splits (a residual
            # with several equally-valid decompositions, ADR-0006's analogue) is
            # not detected — out of ticket-04 scope. Add multi-decomposition
            # detection here if consumers need split ambiguity surfaced.
            matches.append(
                Match(
                    left_ids=left_ids,
                    right_ids=right_ids,
                    score=score,
                    reasons=Reason(gates_passed=gate_names),
                )
            )

    run(left_avail, right_avail, consumed_left, consumed_right, one_is_left=True)
    run(right_avail, left_avail, consumed_right, consumed_left, one_is_left=False)
    return matches, consumed_left, consumed_right


def _gate_ok(
    one: Record, member: Record, one_is_left: bool, nonamount_gates: tuple[FieldRule, ...]
) -> bool:
    """Does ``member`` clear ``one``'s non-Amount gates (the Date window)?"""
    left, right = (one, member) if one_is_left else (member, one)
    return _gates_pass(left, right, nonamount_gates) is not None


def _grade_score(
    one: Record,
    member: Record,
    one_is_left: bool,
    grade_rules: tuple[FieldRule, ...],
    scorer: Scorer,
) -> float:
    """Graded score of ``one`` against ``member`` in true Left/Right orientation."""
    left, right = (one, member) if one_is_left else (member, one)
    return _score(left, right, grade_rules, scorer)[0]


def _find_subset(
    target: Record,
    group: list[tuple[int, Record, float]],
    amount_rules: tuple[FieldRule, ...],
    max_subset_size: int,
) -> tuple[tuple[int, Record, float], ...] | None:
    """First 2..max-size subset whose Amounts sum within ``target``'s tolerance.

    ponytail: bounded exact subset-sum, worst case C(len(group), max_subset_size)
    per residual. The caller caps ``group`` before this runs, so that worst case
    is C(max_group_size, max_subset_size) (ADR-0007). A smarter solver (pruning /
    meet-in-the-middle) only if a consumer hits the cap on real data.
    """
    for size in range(2, max_subset_size + 1):  # a split is 1:many, so >= 2 members
        for combo in itertools.combinations(group, size):
            total = sum((rec.amount for _, rec, _ in combo), Decimal(0))
            if all(_amount_within(target.amount, total, r) for r in amount_rules):
                return combo
    return None


def _near_tie(winner: _Candidate, candidates: list[_Candidate], epsilon: float) -> bool:
    """True when a Record the winner claims had a competing candidate within epsilon.

    A competitor shares exactly one endpoint with the winner (a different record
    on the other side). We compare against every such candidate, not only those
    still free: a Record contested by a near-equal alternative is uncertain even
    when that alternative's other side was claimed by a stronger match — the
    "top two competing candidate scores for a Record" of ADR-0006 / CONTEXT.md.
    """
    # ponytail: O(candidates) per winner (O(candidates * min(L,R)) total). Index
    # by endpoint if the all-pairs-pass worst case ever shows up on real data.
    for c in candidates:
        if c is winner:
            continue
        shares_one = (c.li == winner.li) != (c.ri == winner.ri)
        if shares_one and abs(winner.score - c.score) <= epsilon:
            return True
    return False


def _ordered(recs: Sequence[Record]) -> list[tuple[int, Record]]:
    """(position, record) pairs in deterministic order: Record id, then position."""
    return sorted(enumerate(recs), key=lambda ip: _sort_key(ip[1], ip[0]))


def _sort_key(rec: Record, pos: int) -> tuple[bool, str, int]:
    # id-bearing records first, ordered by id; id-less ones after, by position.
    # (avoids comparing str id against int position)
    return (rec.id is None, rec.id or "", pos)


def _identity(rec: Record, pos: int) -> str | int:
    return rec.id if rec.id is not None else pos


def _gates_pass(
    left: Record, right: Record, gate_rules: tuple[FieldRule, ...]
) -> tuple[str, ...] | None:
    """Return the names of gates that passed, or None if any gate failed."""
    passed: list[str] = []
    for rule in gate_rules:
        if rule.field == "amount":
            if not _amount_ok(left, right, rule):
                return None
            passed.append("amount")
        elif rule.field == "date":
            if left.date is None or right.date is None or rule.day_tol is None:
                return None
            if abs((left.date - right.date).days) > rule.day_tol:
                return None
            passed.append("date")
    return tuple(passed)


def _score(
    left: Record, right: Record, grade_rules: tuple[FieldRule, ...], scorer: Scorer
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Weighted mean of graded-field Similarities; 1.0 when no graded fields.

    Weights default to equal (1.0 each). A missing value on either side scores
    0.0 (no evidence) rather than being fed to the Scorer as an empty string,
    which difflib would rate as a perfect match against another empty string.
    """
    if not grade_rules:
        return 1.0, ()  # gate-only pass (CONTEXT.md: Match score)
    total_weight = 0.0
    weighted_sum = 0.0
    similarities: list[tuple[str, float]] = []
    for rule in grade_rules:
        left_val = getattr(left, rule.field)
        right_val = getattr(right, rule.field)
        sim = 0.0 if left_val is None or right_val is None else scorer(left_val, right_val)
        weight = rule.weight if rule.weight is not None else 1.0
        weighted_sum += weight * sim
        total_weight += weight
        similarities.append((rule.field, sim))
    score = weighted_sum / total_weight if total_weight else 1.0
    return score, tuple(similarities)


def _default_scorer(a: str, b: str) -> float:
    """Zero-dependency Similarity: normalize then difflib ratio (ADR-0005).

    autojunk=False keeps the ratio stable regardless of string length (the
    heuristic otherwise treats popular chars as junk once a side hits 200+).
    """
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b), autojunk=False).ratio()


@lru_cache(maxsize=4096)
def _normalize(s: str) -> str:
    """Case-fold and drop everything but alphanumerics (strips punctuation/ws).

    Cached: the match loop normalizes each left value once per right candidate.
    """
    return "".join(ch for ch in s.casefold() if ch.isalnum())


def _amount_ok(left: Record, right: Record, rule: FieldRule) -> bool:
    """Amount within absolute OR percentage tolerance; exact match if neither set."""
    return _amount_within(left.amount, right.amount, rule)


def _amount_within(a: Decimal, b: Decimal, rule: FieldRule) -> bool:
    """Tolerance check on two Amounts — the split subset-sum path calls this with
    a plain summed Decimal, avoiding a throwaway Record per enumerated combo."""
    diff = abs(a - b)
    if rule.abs_tol is None and rule.pct_tol is None:
        return diff == 0
    if rule.abs_tol is not None and diff <= rule.abs_tol:
        return True
    if rule.pct_tol is not None:
        base = max(abs(a), abs(b))  # symmetric base (ADR-0008)
        return diff <= base * rule.pct_tol / 100
    return False
