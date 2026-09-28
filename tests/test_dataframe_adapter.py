"""Seam-2 tests: exercise the pandas adapter around ``reconcile()``.

The adapter is the only place pandas touches the system (ADR-0002). These tests
drive the full boundary — DataFrame -> Records -> ``reconcile()`` -> DataFrames —
plus the column mapping and the dtype quirks the boundary is responsible for
absorbing (NaN, NaT, float money, float ids). Engine tests stay pandas-free; the
last test guards that the core package imports without pandas at all.
"""

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from reconcile import FieldRule, ReconcileConfig, Record, reconcile
from reconcile.pandas_adapter import from_dataframe, to_dataframe


def gate_config(abs_tol: str = "0.00", day_tol: int = 3) -> ReconcileConfig:
    return ReconcileConfig(
        rules=(
            FieldRule("amount", "gate", abs_tol=Decimal(abs_tol)),
            FieldRule("date", "gate", day_tol=day_tol),
        )
    )


def test_round_trip_dataframe_to_records_to_dataframe():
    left_df = pd.DataFrame(
        {
            "amount": [100.00, 250.00],
            "when": ["2024-01-01", "2024-01-05"],
            "ref": ["INV-1", "INV-2"],
            "id": ["L1", "L2"],
        }
    )
    right_df = pd.DataFrame(
        {
            "amount": [100.00, 999.00],
            "when": ["2024-01-02", "2024-01-05"],
            "ref": ["INV-1", "XXX"],
            "id": ["R1", "R2"],
        }
    )

    left = from_dataframe(left_df, amount="amount", date="when", reference="ref", id="id")
    right = from_dataframe(right_df, amount="amount", date="when", reference="ref", id="id")

    res = reconcile(left, right, gate_config(abs_tol="0.00", day_tol=3))
    frames = to_dataframe(res)

    assert len(frames.matches) == 1
    row = frames.matches.iloc[0]
    assert row["left_ids"] == ("L1",)
    assert row["right_ids"] == ("R1",)
    assert not row["ambiguous"]  # numpy.bool_ from the frame cell
    assert set(row["gates_passed"]) == {"amount", "date"}

    assert frames.left_residuals["id"].tolist() == ["L2"]
    assert frames.right_residuals["id"].tolist() == ["R2"]


def test_split_tuple_survives_to_dataframe():
    # One Left settled by two Rights: the Match carries a right_ids tuple, and the
    # matches DataFrame must preserve that tuple, not flatten it.
    cfg = ReconcileConfig((FieldRule("amount", "gate", abs_tol=Decimal("0")),))
    left = from_dataframe(pd.DataFrame({"amount": [300.00], "id": ["L1"]}), amount="amount", id="id")
    right = from_dataframe(
        pd.DataFrame({"amount": [100.00, 200.00], "id": ["R1", "R2"]}), amount="amount", id="id"
    )

    frames = to_dataframe(reconcile(left, right, cfg))

    assert len(frames.matches) == 1
    assert frames.matches.iloc[0]["left_ids"] == ("L1",)
    assert frames.matches.iloc[0]["right_ids"] == ("R1", "R2")


def test_ambiguous_flag_surfaces_in_dataframe():
    cfg = ReconcileConfig((FieldRule("amount", "gate", abs_tol=Decimal("0")),))
    left = from_dataframe(pd.DataFrame({"amount": [100.00], "id": ["L1"]}), amount="amount", id="id")
    right = from_dataframe(
        pd.DataFrame({"amount": [100.00, 100.00], "id": ["R1", "R2"]}), amount="amount", id="id"
    )

    frames = to_dataframe(reconcile(left, right, cfg))

    assert frames.matches.iloc[0]["ambiguous"]  # numpy.bool_ from the frame cell


def test_empty_result_yields_empty_frames_with_columns():
    frames = to_dataframe(reconcile([], [], gate_config()))
    assert frames.matches.empty
    assert list(frames.matches.columns) == [
        "left_ids",
        "right_ids",
        "score",
        "ambiguous",
        "gates_passed",
        "similarities",
    ]
    assert list(frames.left_residuals.columns) == [
        "id",
        "amount",
        "date",
        "reference",
        "counterparty",
    ]


def test_amount_only_mapping_leaves_optionals_absent():
    recs = from_dataframe(pd.DataFrame({"amount": [10.00, 20.00]}), amount="amount")
    assert [r.amount for r in recs] == [Decimal("10.0"), Decimal("20.0")]
    assert all(r.date is None and r.reference is None and r.id is None for r in recs)


def test_float_money_never_breaks_the_amount_gate():
    # Decimal(0.10) == 0.1000000000000000055...; the adapter must go via str so a
    # float amount equals a hand-built Decimal("0.10") under a zero-tolerance gate.
    (rec,) = from_dataframe(pd.DataFrame({"amount": [0.10]}), amount="amount")
    assert rec.amount == Decimal("0.10")

    cfg = ReconcileConfig((FieldRule("amount", "gate", abs_tol=Decimal("0")),))
    res = reconcile([rec], [Record(Decimal("0.10"), id="R1")], cfg)
    assert len(res.matches) == 1


def test_nan_and_nat_become_absent_optional_fields():
    df = pd.DataFrame(
        {
            "amount": [50.00],
            "when": [pd.NaT],
            "ref": [float("nan")],
            "cp": [None],
            "id": [float("nan")],
        }
    )
    (rec,) = from_dataframe(
        df, amount="amount", date="when", reference="ref", counterparty="cp", id="id"
    )
    assert rec.date is None
    assert rec.reference is None
    assert rec.counterparty is None
    assert rec.id is None


def test_timestamp_column_coerced_to_date():
    df = pd.DataFrame({"amount": [1.00], "when": pd.to_datetime(["2024-03-10"])})
    (rec,) = from_dataframe(df, amount="amount", date="when")
    assert rec.date == date(2024, 3, 10)


def test_integral_float_id_renders_without_decimal_point():
    # ids read from a column that pandas widened to float64 (a NaN elsewhere) must
    # not become "123.0", which would break id-based ordering and round-trip.
    df = pd.DataFrame({"amount": [1.00], "id": [123.0]})
    (rec,) = from_dataframe(df, amount="amount", id="id")
    assert rec.id == "123"


def test_missing_amount_is_rejected():
    # Amount is mandatory (spec Q5): a NaN Amount cell is an error at the boundary,
    # not a silent zero or a dropped row.
    with pytest.raises(ValueError, match="[Aa]mount"):
        from_dataframe(pd.DataFrame({"amount": [float("nan")]}), amount="amount")


def test_infinite_amount_is_rejected():
    # inf slips past pd.isna; Decimal('Infinity') would poison the tolerance math,
    # so it must be rejected at the boundary like NaN.
    with pytest.raises(ValueError, match="finite"):
        from_dataframe(pd.DataFrame({"amount": [float("inf")]}), amount="amount")


def test_numeric_date_column_is_rejected_not_collapsed_to_1970():
    # An Excel serial / epoch / YYYYMMDD int would be read as nanoseconds-since-epoch
    # (~1970) by pd.Timestamp; the boundary rejects it rather than silently corrupt.
    with pytest.raises(ValueError, match="pd.to_datetime"):
        from_dataframe(
            pd.DataFrame({"amount": [1.00], "when": [20240115]}), amount="amount", date="when"
        )


def test_empty_string_column_name_is_not_silently_dropped():
    # '' is a (wrong) mapping, not an absent one: it must raise, not yield None.
    with pytest.raises(KeyError):
        from_dataframe(pd.DataFrame({"amount": [1.00]}), amount="amount", reference="")


def test_core_package_imports_without_pandas():
    # ADR-0002: the engine has no pandas dependency. Importing the core package
    # must not pull pandas into sys.modules — proven in a fresh interpreter so the
    # adapter this test already imported can't mask a stray core import.
    src = Path(__file__).resolve().parent.parent / "src"
    code = (
        "import sys, reconcile; "
        "assert 'pandas' not in sys.modules, "
        "sorted(m for m in sys.modules if m == 'pandas' or m.startswith('pandas.'))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
