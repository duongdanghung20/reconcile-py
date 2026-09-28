"""Property test locking ADR-0004 end to end: shuffling the input order of the
Left and Right sets must never change the ``ReconcileResult`` — same matches,
same residuals, same ordering.

Covers all four match regimes in one place: gate-only, graded, ambiguous, and
split. Uses stdlib ``random`` over many seeds (the suite's prior art; no
``hypothesis`` dependency), asserting full ``ReconcileResult`` equality — which,
because the dataclasses compare by value in order, also pins output ordering.
"""

import random
from datetime import date
from decimal import Decimal

import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile

D = date(2024, 1, 1)


def _gate_only():
    cfg = ReconcileConfig(
        (
            FieldRule("amount", "gate", abs_tol=Decimal("0")),
            FieldRule("date", "gate", day_tol=2),
        )
    )
    left = [Record(Decimal(str(n)), D, id=f"L{n}") for n in (10, 20, 30, 40)]
    right = [Record(Decimal(str(n)), D, id=f"R{n}") for n in (20, 30, 50, 60)]
    return left, right, cfg


def _graded():
    cfg = ReconcileConfig(
        (FieldRule("amount", "gate", abs_tol=Decimal("0")), FieldRule("reference", "grade")),
        threshold=0.5,
    )
    left = [Record(Decimal("10.00"), reference=f"INV-{n}", id=f"L{n}") for n in (1, 2, 3, 4)]
    right = [Record(Decimal("10.00"), reference=f"inv {n}", id=f"R{n}") for n in (2, 3, 4, 5)]
    return left, right, cfg


def _ambiguous():
    # Several equal-scoring gate matches force near-tie flagging and id tiebreaks.
    cfg = ReconcileConfig(
        (FieldRule("amount", "gate", abs_tol=Decimal("0")),), ambiguity_epsilon=0.05
    )
    left = [Record(Decimal("100.00"), id=f"L{n}") for n in range(1, 5)]
    right = [Record(Decimal("100.00"), id=f"R{n}") for n in range(1, 4)]
    return left, right, cfg


def _split():
    # One 1:1, one Left->many, one Right->many, plus untouched residuals.
    cfg = ReconcileConfig(
        (
            FieldRule("amount", "gate", abs_tol=Decimal("0")),
            FieldRule("date", "gate", day_tol=5),
        )
    )
    # Amounts are distinct across sides except the L1/R1 pair, so the only 1:1 is
    # L1<->R1; everything else must go through the split phase.
    left = [
        Record(Decimal("50.00"), D, id="L1"),  # exact 1:1 with R1
        Record(Decimal("90.00"), D, id="L2"),  # -> R2 + R3
        Record(Decimal("30.00"), D, id="L3"),  # part of R4 split
        Record(Decimal("45.00"), D, id="L4"),  # part of R4 split
        Record(Decimal("13.00"), D, id="L5"),  # residual
    ]
    right = [
        Record(Decimal("50.00"), D, id="R1"),  # exact 1:1 with L1
        Record(Decimal("55.00"), D, id="R2"),  # part of L2 split
        Record(Decimal("35.00"), D, id="R3"),  # part of L2 split
        Record(Decimal("75.00"), D, id="R4"),  # <- L3 + L4
        Record(Decimal("17.00"), D, id="R5"),  # residual
    ]
    return left, right, cfg


@pytest.mark.parametrize("scenario", [_gate_only, _graded, _ambiguous, _split])
def test_result_invariant_under_input_shuffle(scenario):
    left, right, cfg = scenario()
    baseline = reconcile(left, right, cfg)

    for seed in range(25):
        sl, sr = left[:], right[:]
        random.Random(seed).shuffle(sl)
        random.Random(seed + 10_000).shuffle(sr)
        assert reconcile(sl, sr, cfg) == baseline


def test_split_scenario_actually_exercises_every_regime():
    # Guard the property test's own coverage: the split scenario must really
    # produce a 1:1, a Left->many, a Right->many and leftover residuals, or the
    # invariant above would be locking a trivial (empty) result.
    left, right, cfg = _split()
    res = reconcile(left, right, cfg)

    shapes = {(len(m.left_ids), len(m.right_ids)) for m in res.matches}
    assert (1, 1) in shapes  # a 1:1 match
    assert (1, 2) in shapes  # one Left -> many Right
    assert (2, 1) in shapes  # one Right -> many Left
    assert res.left_residuals and res.right_residuals  # untouched records remain
