"""The pairwise match engine. Public entrypoint: ``reconcile``.

Pure: no wall-clock, no randomness, no IO (ADR-0004). Determinism comes from
sorting records by a caller-supplied Record id, falling back to input position.

Ticket 01 scope: gate-only exact 1:1 matching. Graded scoring/threshold (02),
ambiguity flagging (03) and bounded split search (04) are added later behind
this same seam.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import FieldRule, Match, Reason, ReconcileConfig, ReconcileResult, Record


def reconcile(
    left: Sequence[Record], right: Sequence[Record], config: ReconcileConfig
) -> ReconcileResult:
    """Match a Left set against a Right set, returning matches and residuals."""
    gate_rules = tuple(r for r in config.rules if r.role == "gate")

    left_order = _ordered(left)
    right_order = _ordered(right)

    used_right: set[int] = set()
    matched_left: set[int] = set()
    matches: list[Match] = []

    for li, lrec in left_order:
        for ri, rrec in right_order:
            if ri in used_right:
                continue
            gates_passed = _gates_pass(lrec, rrec, gate_rules)
            if gates_passed is None:
                continue
            used_right.add(ri)
            matched_left.add(li)
            matches.append(
                Match(
                    left_ids=(_identity(lrec, li),),
                    right_ids=(_identity(rrec, ri),),
                    score=1.0,  # gate-only pass scores 1.0 (CONTEXT.md: Match score)
                    reasons=Reason(gates_passed=gates_passed),
                )
            )
            break  # 1:1 — each record consumed once

    left_residuals = tuple(rec for i, rec in left_order if i not in matched_left)
    right_residuals = tuple(rec for i, rec in right_order if i not in used_right)
    return ReconcileResult(tuple(matches), left_residuals, right_residuals)


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


def _amount_ok(left: Record, right: Record, rule: FieldRule) -> bool:
    """Amount within absolute OR percentage tolerance; exact match if neither set."""
    diff = abs(left.amount - right.amount)
    if rule.abs_tol is None and rule.pct_tol is None:
        return diff == 0
    if rule.abs_tol is not None and diff <= rule.abs_tol:
        return True
    if rule.pct_tol is not None:
        base = max(abs(left.amount), abs(right.amount))  # symmetric base (ADR-0008)
        return diff <= base * rule.pct_tol / 100
    return False
