"""Seam-1 tests for ticket 04: bounded split matches (1:many, both directions).

Same seam as the other suites — assertions on the ``ReconcileResult`` from
``reconcile()`` only, named in CONTEXT.md vocabulary (split match, residual,
gate, subset). Amounts are chosen so subset sums land exactly on the residual's
Amount, keeping the intended split readable.
"""

from datetime import date
from decimal import Decimal

import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile

D = date(2024, 1, 1)


def _cfg(*, abs_tol="0.00", day_tol=5, max_subset_size=4, max_group_size=100):
    return ReconcileConfig(
        rules=(
            FieldRule("amount", "gate", abs_tol=Decimal(abs_tol)),
            FieldRule("date", "gate", day_tol=day_tol),
        ),
        max_subset_size=max_subset_size,
        max_group_size=max_group_size,
    )


def _pairs(res):
    return [(m.left_ids, m.right_ids) for m in res.matches]


# --- one Left settled by many Right (batch settlement) --------------------


def test_left_to_many_split():
    left = [Record(Decimal("100.00"), D, id="L1")]
    right = [Record(Decimal("60.00"), D, id="R1"), Record(Decimal("40.00"), D, id="R2")]

    res = reconcile(left, right, _cfg())

    assert _pairs(res) == [(("L1",), ("R1", "R2"))]  # many side in right_ids tuple
    assert res.left_residuals == ()
    assert res.right_residuals == ()


# --- one Right settled by many Left (installments, symmetric direction) ---


def test_right_to_many_split():
    left = [Record(Decimal("60.00"), D, id="L1"), Record(Decimal("40.00"), D, id="L2")]
    right = [Record(Decimal("100.00"), D, id="R1")]

    res = reconcile(left, right, _cfg())

    assert _pairs(res) == [(("L1", "L2"), ("R1",))]  # many side in left_ids tuple
    assert res.left_residuals == ()
    assert res.right_residuals == ()


# --- subset-size cap: a split needing more members than allowed -> residual -


def test_subset_size_cap_leaves_residual():
    # Only the full 5-invoice set sums to 150; every subset of <=4 falls short.
    left = [Record(Decimal("150.00"), D, id="L1")]
    right = [Record(Decimal(str(x)), D, id=f"R{x}") for x in (10, 20, 30, 40, 50)]

    capped = reconcile(left, right, _cfg(max_subset_size=4))
    assert capped.matches == ()
    assert [r.id for r in capped.left_residuals] == ["L1"]
    assert {r.id for r in capped.right_residuals} == {"R10", "R20", "R30", "R40", "R50"}

    # Raise the cap and the same input reconciles as one 1:5 split.
    lifted = reconcile(left, right, _cfg(max_subset_size=5))
    assert _pairs(lifted) == [(("L1",), ("R10", "R20", "R30", "R40", "R50"))]


# --- group-size cap: too many gate-passing candidates -> skip, stay residual -


def test_group_size_cap_leaves_residual():
    left = [Record(Decimal("100.00"), D, id="L1")]
    right = [
        Record(Decimal("60.00"), D, id="R1"),
        Record(Decimal("40.00"), D, id="R2"),
        Record(Decimal("1.00"), D, id="R3"),
    ]

    capped = reconcile(left, right, _cfg(max_group_size=2))  # group of 3 > cap
    assert capped.matches == ()
    assert [r.id for r in capped.left_residuals] == ["L1"]

    lifted = reconcile(left, right, _cfg(max_group_size=3))
    assert _pairs(lifted) == [(("L1",), ("R1", "R2"))]  # first size-2 subset summing to 100
    assert [r.id for r in lifted.right_residuals] == ["R3"]


# --- splits run only after the 1:1 pass claims exact matches --------------


def test_split_only_after_one_to_one():
    # L2<->R1 is an exact 1:1; only then does L1 split across the R2/R3 residuals.
    left = [Record(Decimal("100.00"), D, id="L1"), Record(Decimal("50.00"), D, id="L2")]
    right = [
        Record(Decimal("50.00"), D, id="R1"),
        Record(Decimal("60.00"), D, id="R2"),
        Record(Decimal("40.00"), D, id="R3"),
    ]

    res = reconcile(left, right, _cfg())

    # 1:1 match emitted first, split appended after; R1 never enters the split
    assert _pairs(res) == [(("L2",), ("R1",)), (("L1",), ("R2", "R3"))]
    assert res.left_residuals == ()
    assert res.right_residuals == ()


# --- a split carries an auditable reason and a score ----------------------


def test_split_carries_reason_and_score():
    left = [Record(Decimal("100.00"), D, id="L1")]
    right = [Record(Decimal("60.00"), D, id="R1"), Record(Decimal("40.00"), D, id="R2")]

    m = reconcile(left, right, _cfg()).matches[0]

    assert set(m.reasons.gates_passed) == {"amount", "date"}
    assert m.score == 1.0  # gate-only split
    assert m.ambiguous is False


# --- grouping honours the Date gate (a far-dated candidate is excluded) ---


def test_split_group_excludes_out_of_date_window():
    left = [Record(Decimal("100.00"), date(2024, 1, 1), id="L1")]
    right = [
        Record(Decimal("60.00"), date(2024, 1, 2), id="R1"),  # +1 day, in window
        Record(Decimal("40.00"), date(2024, 1, 20), id="R2"),  # +19 days, out
    ]

    res = reconcile(left, right, _cfg(day_tol=2))

    # R2 outside the window can't join L1's group -> no subset sums to 100
    assert res.matches == ()
    assert [r.id for r in res.left_residuals] == ["L1"]
    assert {r.id for r in res.right_residuals} == {"R1", "R2"}


# --- grouping honours a configured graded field ("Counterparty if configured") -


def test_split_group_filtered_by_graded_threshold():
    binary = lambda a, b: 1.0 if a == b else 0.0  # noqa: E731
    cfg = ReconcileConfig(
        rules=(
            FieldRule("amount", "gate", abs_tol=Decimal("0")),
            FieldRule("counterparty", "grade"),
        ),
        threshold=1.0,
        scorer=binary,
    )
    left = [Record(Decimal("100.00"), counterparty="ACME", id="L1")]

    mismatched = [
        Record(Decimal("60.00"), counterparty="ACME", id="R1"),
        Record(Decimal("40.00"), counterparty="OTHER", id="R2"),  # fails threshold, excluded
    ]
    res = reconcile(left, mismatched, cfg)
    assert res.matches == ()  # R2 excluded -> R1 alone can't sum to 100
    assert [r.id for r in res.left_residuals] == ["L1"]

    matched = [
        Record(Decimal("60.00"), counterparty="ACME", id="R1"),
        Record(Decimal("40.00"), counterparty="ACME", id="R2"),
    ]
    ok = reconcile(left, matched, cfg)
    assert _pairs(ok) == [(("L1",), ("R1", "R2"))]


# --- config rejects split knobs that would silently disable split search --


def test_config_rejects_subset_size_below_two():
    # max_subset_size < 2 makes range(2, size+1) empty -> every split skipped.
    for bad in (1, 0, -1):
        with pytest.raises(ValueError):
            ReconcileConfig(
                (FieldRule("amount", "gate", abs_tol=Decimal("0")),), max_subset_size=bad
            )


def test_config_rejects_nonpositive_group_size():
    # max_group_size < 1 makes len(candidates) > cap always true -> splits off.
    for bad in (0, -5):
        with pytest.raises(ValueError):
            ReconcileConfig(
                (FieldRule("amount", "gate", abs_tol=Decimal("0")),), max_group_size=bad
            )
