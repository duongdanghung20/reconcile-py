"""Seam-1 tests: exercise the engine only through ``reconcile()``.

Establishes the prior-art pattern for the suite (spec Testing Decisions):
plain input/output assertions on the ``ReconcileResult`` — never reaching into
engine internals — named in CONTEXT.md vocabulary (gate, residual, match reason).
"""

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile


def gate_config(abs_tol: str = "0.00", day_tol: int = 3) -> ReconcileConfig:
    """Gate-only config: Amount (absolute tolerance) + Date (± day window)."""
    return ReconcileConfig(
        rules=(
            FieldRule("amount", "gate", abs_tol=Decimal(abs_tol)),
            FieldRule("date", "gate", day_tol=day_tol),
        )
    )


def test_exact_1to1_gate_match():
    left = [Record(Decimal("100.00"), date(2024, 1, 1), id="L1")]
    right = [Record(Decimal("100.00"), date(2024, 1, 2), id="R1")]

    res = reconcile(left, right, gate_config(abs_tol="0.00", day_tol=3))

    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.left_ids == ("L1",)
    assert m.right_ids == ("R1",)
    assert m.score == 1.0
    assert m.ambiguous is False
    # match reason records which gates passed
    assert set(m.reasons.gates_passed) == {"amount", "date"}
    assert res.left_residuals == ()
    assert res.right_residuals == ()


def test_amount_gate_rejects_one_cent_out():
    # ADR-0003: a perfect everything-else pair whose Amount is one cent outside
    # tolerance never matches — Amount is a gate, not a weight.
    cfg = gate_config(abs_tol="0.00", day_tol=30)
    left = [Record(Decimal("100.00"), date(2024, 1, 1), id="L1")]
    right = [Record(Decimal("100.01"), date(2024, 1, 1), id="R1")]

    res = reconcile(left, right, cfg)

    assert res.matches == ()
    assert [r.id for r in res.left_residuals] == ["L1"]
    assert [r.id for r in res.right_residuals] == ["R1"]


def test_amount_percentage_tolerance():
    # 0.5% tolerance, amount gate only (no date gate).
    cfg = ReconcileConfig((FieldRule("amount", "gate", pct_tol=Decimal("0.5")),))

    within = reconcile(
        [Record(Decimal("1000.00"), id="L1")],
        [Record(Decimal("1004.00"), id="R1")],  # 0.40% out -> within
        cfg,
    )
    assert len(within.matches) == 1

    outside = reconcile(
        [Record(Decimal("1000.00"), id="L1")],
        [Record(Decimal("1010.00"), id="R1")],  # 0.99% out -> rejected
        cfg,
    )
    assert outside.matches == ()


def test_date_window_boundary():
    cfg = gate_config(abs_tol="0.00", day_tol=3)
    left = Record(Decimal("50.00"), date(2024, 3, 10), id="L1")

    on_edge = Record(Decimal("50.00"), date(2024, 3, 13), id="R1")  # +3 days
    over_edge = Record(Decimal("50.00"), date(2024, 3, 14), id="R2")  # +4 days

    assert len(reconcile([left], [on_edge], cfg).matches) == 1
    assert reconcile([left], [over_edge], cfg).matches == ()


def test_residuals_split_by_side():
    cfg = gate_config(abs_tol="0.00", day_tol=2)
    left = [
        Record(Decimal("10.00"), date(2024, 1, 1), id="L1"),
        Record(Decimal("99.00"), date(2024, 1, 1), id="L2"),
    ]
    right = [
        Record(Decimal("10.00"), date(2024, 1, 1), id="R1"),
        Record(Decimal("77.00"), date(2024, 1, 1), id="R2"),
    ]

    res = reconcile(left, right, cfg)

    assert [(m.left_ids, m.right_ids) for m in res.matches] == [(("L1",), ("R1",))]
    assert [r.id for r in res.left_residuals] == ["L2"]
    assert [r.id for r in res.right_residuals] == ["R2"]


def test_deterministic_under_input_shuffle():
    # ADR-0004: same records + config -> identical output regardless of input order.
    import random

    cfg = gate_config(abs_tol="0.00", day_tol=1)
    left = [Record(Decimal(str(n)), date(2024, 1, 1), id=f"L{n}") for n in (100, 200, 300)]
    right = [Record(Decimal(str(n)), date(2024, 1, 1), id=f"R{n}") for n in (100, 200, 300)]

    baseline = reconcile(left, right, cfg)

    for seed in range(5):
        shuffled_left = left[:]
        shuffled_right = right[:]
        random.Random(seed).shuffle(shuffled_left)
        random.Random(seed + 99).shuffle(shuffled_right)
        assert reconcile(shuffled_left, shuffled_right, cfg) == baseline


def test_ordering_falls_back_to_input_position_without_id():
    cfg = gate_config(abs_tol="0.00", day_tol=1)
    res = reconcile(
        [Record(Decimal("5.00"), date(2024, 1, 1))],
        [Record(Decimal("5.00"), date(2024, 1, 1))],
        cfg,
    )
    assert res.matches[0].left_ids == (0,)
    assert res.matches[0].right_ids == (0,)


def test_config_requires_amount_gate():
    with pytest.raises(ValueError):
        ReconcileConfig((FieldRule("date", "gate", day_tol=1),))
    with pytest.raises(ValueError):
        ReconcileConfig(())


def test_config_rejects_gate_on_non_gate_field():
    # Only Amount and Date are gate fields (ADR-0003); a gate elsewhere would
    # otherwise be silently ignored by the engine.
    with pytest.raises(ValueError):
        ReconcileConfig(
            (
                FieldRule("amount", "gate", abs_tol=Decimal("0")),
                FieldRule("reference", "gate"),
            )
        )


def test_config_rejects_date_gate_without_day_tol():
    # A date gate with no window would silently reject every pair.
    with pytest.raises(ValueError):
        ReconcileConfig(
            (
                FieldRule("amount", "gate", abs_tol=Decimal("0")),
                FieldRule("date", "gate"),
            )
        )


def test_config_and_result_are_frozen():
    cfg = gate_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.threshold = 0.5  # type: ignore[misc]

    res = reconcile([], [], cfg)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.matches = ()  # type: ignore[misc]
