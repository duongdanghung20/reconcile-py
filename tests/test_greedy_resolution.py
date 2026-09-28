"""Seam-1 tests for ticket 03: greedy best-first resolution + ambiguity flag.

Same seam as the other suites — assertions on the ``ReconcileResult`` from
``reconcile()`` only, in CONTEXT.md vocabulary (match, residual, ambiguous
match, Match score). A stub Scorer pins each pair's score so the greedy order
and the near-tie epsilon are exact and readable, not difflib-approximate.
"""

import random
from decimal import Decimal

import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile


def _cfg(scores, *, threshold=0.0, epsilon=0.0):
    """Config whose Scorer looks each (left_ref, right_ref) pair up in ``scores``.

    Amount is an exact gate; records carry equal Amounts in these tests so the
    gate passes for every pair and the graded Reference score alone decides.
    """
    return ReconcileConfig(
        rules=(
            FieldRule("amount", "gate", abs_tol=Decimal("0")),
            FieldRule("reference", "grade"),
        ),
        threshold=threshold,
        ambiguity_epsilon=epsilon,
        scorer=lambda a, b: scores[(a, b)],
    )


def _rec(ref, id_):
    return Record(Decimal("100.00"), reference=ref, id=id_)


def _pairs(res):
    return [(m.left_ids, m.right_ids) for m in res.matches]


# --- two Left compete for one Right ---------------------------------------


def test_two_left_compete_for_one_right_greedy_and_consume_once():
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1")]
    cfg = _cfg({("l1", "r1"): 0.9, ("l2", "r1"): 0.6})

    res = reconcile(left, right, cfg)

    # higher-scoring candidate wins; R1 consumed once; L2 left over
    assert _pairs(res) == [(("L1",), ("R1",))]
    assert res.right_residuals == ()  # R1 not double-assigned, not residual
    assert [r.id for r in res.left_residuals] == ["L2"]
    assert res.matches[0].ambiguous is False  # 0.3 gap, no near-tie


# --- one Left competes for two Right (symmetric) --------------------------


def test_one_left_two_right_greedy():
    left = [_rec("l1", "L1")]
    right = [_rec("r1", "R1"), _rec("r2", "R2")]
    cfg = _cfg({("l1", "r1"): 0.6, ("l1", "r2"): 0.9})

    res = reconcile(left, right, cfg)

    assert _pairs(res) == [(("L1",), ("R2",))]  # R2 scores higher, wins
    assert [r.id for r in res.right_residuals] == ["R1"]
    assert res.left_residuals == ()


# --- greedy is best-first globally, not first-fit by left order -----------


def test_greedy_is_best_first_not_first_fit():
    # First-fit by left order would give L1->R1 (0.7) then L2->R2 (0.4).
    # Greedy assigns the best pair first: L1->R2 (0.95), L2->R1 (0.9).
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1"), _rec("r2", "R2")]
    cfg = _cfg(
        {
            ("l1", "r1"): 0.7,
            ("l1", "r2"): 0.95,
            ("l2", "r1"): 0.9,
            ("l2", "r2"): 0.4,
        }
    )

    res = reconcile(left, right, cfg)

    assert _pairs(res) == [(("L1",), ("R2",)), (("L2",), ("R1",))]
    assert res.left_residuals == ()
    assert res.right_residuals == ()
    assert all(m.ambiguous is False for m in res.matches)


# --- near-tie flags the winning match Ambiguous ---------------------------


def test_near_tie_within_epsilon_flags_ambiguous():
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1")]
    cfg = _cfg({("l1", "r1"): 0.90, ("l2", "r1"): 0.88}, epsilon=0.05)

    res = reconcile(left, right, cfg)

    # winner still emitted (greedy picks the higher), but flagged in place
    assert _pairs(res) == [(("L1",), ("R1",))]
    assert res.matches[0].ambiguous is True
    assert [r.id for r in res.left_residuals] == ["L2"]


def test_near_tie_flagged_even_when_rival_side_claimed_elsewhere():
    # ADR-0006 compares a Record's top two competing candidate scores, not just
    # still-free ones. R1's two closest are L2-R1=0.89 and L1-R1=0.87 (within
    # epsilon); L1 is claimed by its stronger L1-R2=0.95. R1->L2 must still flag.
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1"), _rec("r2", "R2")]
    cfg = _cfg(
        {
            ("l1", "r2"): 0.95,
            ("l2", "r1"): 0.89,
            ("l1", "r1"): 0.87,
            ("l2", "r2"): 0.10,
        },
        epsilon=0.05,
    )

    res = reconcile(left, right, cfg)

    assert _pairs(res) == [(("L1",), ("R2",)), (("L2",), ("R1",))]
    by_left = {m.left_ids: m.ambiguous for m in res.matches}
    assert by_left[("L1",)] is False  # L1-R2 clear winner, rivals far
    assert by_left[("L2",)] is True  # R1's 0.89 vs 0.87 near-tie


def test_gap_beyond_epsilon_is_not_ambiguous():
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1")]
    cfg = _cfg({("l1", "r1"): 0.90, ("l2", "r1"): 0.80}, epsilon=0.05)

    res = reconcile(left, right, cfg)

    assert res.matches[0].ambiguous is False  # 0.10 gap > 0.05 epsilon


def test_exact_tie_flags_ambiguous_at_zero_epsilon():
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1")]
    cfg = _cfg({("l1", "r1"): 0.9, ("l2", "r1"): 0.9})  # epsilon defaults to 0.0

    res = reconcile(left, right, cfg)

    assert res.matches[0].ambiguous is True
    # tie broken by Record id -> L1 wins deterministically
    assert res.matches[0].left_ids == ("L1",)


# --- result.ambiguous convenience view ------------------------------------


def test_ambiguous_view_is_just_the_flagged_matches():
    # one ambiguous cluster (L1/L2 vs R1) and one clean match (L3 vs R2)
    left = [_rec("l1", "L1"), _rec("l2", "L2"), _rec("l3", "L3")]
    right = [_rec("r1", "R1"), _rec("r2", "R2")]
    cfg = _cfg(
        {
            ("l1", "r1"): 0.90,
            ("l2", "r1"): 0.89,
            ("l1", "r2"): 0.10,
            ("l2", "r2"): 0.10,
            ("l3", "r1"): 0.10,
            ("l3", "r2"): 0.95,
        },
        epsilon=0.05,
    )

    res = reconcile(left, right, cfg)

    assert len(res.matches) == 2
    assert len(res.ambiguous) == 1
    assert res.ambiguous[0].left_ids == ("L1",)
    assert res.ambiguous[0].right_ids == ("R1",)
    assert all(m.ambiguous for m in res.ambiguous)


# --- determinism holds through resolution + flagging ----------------------


def test_determinism_under_shuffle_with_competition():
    scores = {
        ("l1", "r1"): 0.90,
        ("l1", "r2"): 0.70,
        ("l2", "r1"): 0.88,
        ("l2", "r2"): 0.95,
    }
    left = [_rec("l1", "L1"), _rec("l2", "L2")]
    right = [_rec("r1", "R1"), _rec("r2", "R2")]
    cfg = _cfg(scores, epsilon=0.05)

    baseline = reconcile(left, right, cfg)
    for seed in range(5):
        sl, sr = left[:], right[:]
        random.Random(seed).shuffle(sl)
        random.Random(seed + 99).shuffle(sr)
        assert reconcile(sl, sr, cfg) == baseline


# --- gate-only collision: two exact partners for one Record flag ambiguous --


def test_gate_only_collision_flags_ambiguous():
    # Two Left with identical Amount both gate-match one Right (score 1.0 each);
    # an exact tie under the default epsilon 0.0 -> the winner is flagged.
    cfg = ReconcileConfig((FieldRule("amount", "gate", abs_tol=Decimal("0")),))
    left = [Record(Decimal("100.00"), id="L1"), Record(Decimal("100.00"), id="L2")]
    right = [Record(Decimal("100.00"), id="R1")]

    res = reconcile(left, right, cfg)

    assert _pairs(res) == [(("L1",), ("R1",))]  # tie broken by Record id
    assert res.matches[0].ambiguous is True
    assert [r.id for r in res.left_residuals] == ["L2"]


# --- config rejects a negative epsilon -------------------------------------


def test_config_rejects_negative_epsilon():
    # A negative epsilon would silently disable all near-tie flagging.
    with pytest.raises(ValueError):
        ReconcileConfig(
            (FieldRule("amount", "gate", abs_tol=Decimal("0")),), ambiguity_epsilon=-0.01
        )
