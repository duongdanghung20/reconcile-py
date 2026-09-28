"""Seam-1 tests for ticket 02: graded scoring, threshold, pluggable Scorer.

Same seam as ``test_reconcile_seam.py`` — assertions on the ``ReconcileResult``
from ``reconcile()`` only, named in CONTEXT.md vocabulary (gate, grade,
Similarity, Match score, threshold, Scorer).
"""

import random
from decimal import Decimal

import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile


def _cfg(*rules: FieldRule, threshold: float = 1.0, scorer=None) -> ReconcileConfig:
    return ReconcileConfig(
        rules=(FieldRule("amount", "gate", abs_tol=Decimal("0")), *rules),
        threshold=threshold,
        scorer=scorer,
    )


# --- default Scorer: normalize then difflib -------------------------------


def test_reference_normalization_scores_identical():
    # "INV-1024" and "inv 1024" normalize (case-fold, strip punctuation/ws) to
    # the same string -> Similarity 1.0 -> score 1.0 clears the default threshold.
    cfg = _cfg(FieldRule("reference", "grade"), threshold=0.9)
    left = [Record(Decimal("100.00"), reference="INV-1024", id="L1")]
    right = [Record(Decimal("100.00"), reference="inv 1024", id="R1")]

    res = reconcile(left, right, cfg)

    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.score == 1.0
    assert m.reasons.similarities == (("reference", 1.0),)
    assert set(m.reasons.gates_passed) == {"amount"}


def test_counterparty_graded_is_not_pass_fail():
    # "ACME Ltd" vs "ACME Limited": close but not identical -> a real 0..1
    # Similarity (proves the default Scorer grades, not gates).
    left = [Record(Decimal("50.00"), counterparty="ACME Ltd", id="L1")]
    right = [Record(Decimal("50.00"), counterparty="ACME Limited", id="R1")]

    lenient = reconcile(left, right, _cfg(FieldRule("counterparty", "grade"), threshold=0.5))
    assert len(lenient.matches) == 1
    (field, sim) = lenient.matches[0].reasons.similarities[0]
    assert field == "counterparty"
    assert 0.0 < sim < 1.0  # graded, not 1.0 and not 0.0

    strict = reconcile(left, right, _cfg(FieldRule("counterparty", "grade"), threshold=0.99))
    assert strict.matches == ()  # threshold gates the graded score


# --- weighted mean + weight effect ----------------------------------------


def _binary_scorer(a: str, b: str) -> float:
    return 1.0 if a == b else 0.0


def test_weighted_mean_and_weight_effect():
    # reference equal (sim 1.0), counterparty differ (sim 0.0) via a stub scorer.
    left = [Record(Decimal("100.00"), reference="x", counterparty="a", id="L1")]
    right = [Record(Decimal("100.00"), reference="x", counterparty="b", id="R1")]

    def run(w_ref, w_cp):
        cfg = _cfg(
            FieldRule("reference", "grade", weight=w_ref),
            FieldRule("counterparty", "grade", weight=w_cp),
            threshold=0.0,  # accept regardless, inspect the score
            scorer=_binary_scorer,
        )
        return reconcile(left, right, cfg).matches[0].score

    assert run(None, None) == 0.5  # equal weights by default -> plain mean
    assert run(3.0, 1.0) == 0.75  # (3*1 + 1*0)/4
    assert run(1.0, 3.0) == 0.25  # (1*1 + 3*0)/4


# --- threshold boundary ----------------------------------------------------


def test_threshold_boundary_is_inclusive():
    # stub scorer pins the score at exactly 0.8; accept iff threshold <= 0.8.
    left = [Record(Decimal("100.00"), reference="x", id="L1")]
    right = [Record(Decimal("100.00"), reference="y", id="R1")]
    fixed = lambda a, b: 0.8  # noqa: E731

    on = reconcile(left, right, _cfg(FieldRule("reference", "grade"), threshold=0.8, scorer=fixed))
    assert len(on.matches) == 1  # score == threshold -> accepted

    over = reconcile(
        left, right, _cfg(FieldRule("reference", "grade"), threshold=0.81, scorer=fixed)
    )
    assert over.matches == ()  # score < threshold -> rejected, both residual
    assert [r.id for r in over.left_residuals] == ["L1"]
    assert [r.id for r in over.right_residuals] == ["R1"]


# --- custom Scorer injection changes outcome -------------------------------


def test_custom_scorer_changes_outcome():
    # Identical references: the default Scorer matches; a custom Scorer that
    # returns 0.0 makes the same pair fall below threshold -> no match.
    left = [Record(Decimal("100.00"), reference="INV-1", id="L1")]
    right = [Record(Decimal("100.00"), reference="INV-1", id="R1")]
    rule = FieldRule("reference", "grade")

    default = reconcile(left, right, _cfg(rule, threshold=0.9))
    assert len(default.matches) == 1

    injected = reconcile(left, right, _cfg(rule, threshold=0.9, scorer=lambda a, b: 0.0))
    assert injected.matches == ()


# --- Amount stays a hard gate (ADR-0003) -----------------------------------


def test_amount_hard_gate_beats_perfect_reference():
    # Perfect reference (sim 1.0) but Amount one cent out of tolerance -> the
    # gate rejects before scoring, even with threshold 0.0.
    cfg = _cfg(FieldRule("reference", "grade"), threshold=0.0)
    left = [Record(Decimal("100.00"), reference="INV-1", id="L1")]
    right = [Record(Decimal("100.01"), reference="INV-1", id="R1")]

    res = reconcile(left, right, cfg)

    assert res.matches == ()
    assert [r.id for r in res.left_residuals] == ["L1"]


# --- gate-only regression (ticket 01 behavior) ----------------------------


def test_gate_only_config_scores_one():
    cfg = ReconcileConfig((FieldRule("amount", "gate", abs_tol=Decimal("0")),))
    res = reconcile(
        [Record(Decimal("100.00"), id="L1")], [Record(Decimal("100.00"), id="R1")], cfg
    )
    assert len(res.matches) == 1
    assert res.matches[0].score == 1.0
    assert res.matches[0].reasons.similarities == ()


# --- reason records every graded Similarity --------------------------------


def test_reason_records_each_graded_similarity():
    cfg = _cfg(
        FieldRule("reference", "grade"),
        FieldRule("counterparty", "grade"),
        threshold=0.0,
        scorer=_binary_scorer,
    )
    left = [Record(Decimal("100.00"), reference="x", counterparty="a", id="L1")]
    right = [Record(Decimal("100.00"), reference="x", counterparty="b", id="R1")]

    sims = reconcile(left, right, cfg).matches[0].reasons.similarities

    assert sims == (("reference", 1.0), ("counterparty", 0.0))


# --- missing graded values score 0.0, never a spurious perfect match ------


def test_both_missing_graded_field_is_not_a_perfect_match():
    # Two records that both simply omit the reference must not be reported as a
    # confident 1.0 match (difflib rates '' vs '' as 1.0; the engine must not).
    cfg = _cfg(FieldRule("reference", "grade"), threshold=0.99)
    res = reconcile(
        [Record(Decimal("100.00"), id="L1")], [Record(Decimal("100.00"), id="R1")], cfg
    )
    assert res.matches == ()

    # And with a permissive threshold the recorded Similarity is 0.0, not 1.0.
    seen = reconcile(
        [Record(Decimal("100.00"), id="L1")],
        [Record(Decimal("100.00"), id="R1")],
        _cfg(FieldRule("reference", "grade"), threshold=0.0),
    )
    assert seen.matches[0].reasons.similarities == (("reference", 0.0),)


def test_one_side_missing_graded_field_scores_zero():
    cfg = _cfg(FieldRule("reference", "grade"), threshold=0.0)
    res = reconcile(
        [Record(Decimal("100.00"), reference="INV-1", id="L1")],
        [Record(Decimal("100.00"), id="R1")],
        cfg,
    )
    assert res.matches[0].reasons.similarities == (("reference", 0.0),)


# --- config rejects misconfigured grade rules ------------------------------


def test_config_rejects_grade_on_gate_field():
    # Symmetric with the gate-field guard: only reference/counterparty grade.
    for bad in ("amount", "date"):
        with pytest.raises(ValueError):
            ReconcileConfig(
                (FieldRule("amount", "gate", abs_tol=Decimal("0")), FieldRule(bad, "grade"))
            )


def test_config_rejects_nonpositive_grade_weight():
    for bad_weight in (0.0, -1.0):
        with pytest.raises(ValueError):
            ReconcileConfig(
                (
                    FieldRule("amount", "gate", abs_tol=Decimal("0")),
                    FieldRule("reference", "grade", weight=bad_weight),
                )
            )


# --- determinism holds with scoring (ADR-0004) ----------------------------


def test_determinism_with_graded_scoring():
    cfg = _cfg(FieldRule("reference", "grade"), threshold=0.5)
    left = [Record(Decimal("10.00"), reference=f"INV-{n}", id=f"L{n}") for n in (1, 2, 3)]
    right = [Record(Decimal("10.00"), reference=f"inv {n}", id=f"R{n}") for n in (1, 2, 3)]

    baseline = reconcile(left, right, cfg)
    for seed in range(5):
        sl, sr = left[:], right[:]
        random.Random(seed).shuffle(sl)
        random.Random(seed + 99).shuffle(sr)
        assert reconcile(sl, sr, cfg) == baseline
