"""The pandas boundary (ADR-0002): DataFrames in, DataFrames out.

pandas is imported here and nowhere else in the package — the engine and its
types stay pandas-free, so ``import reconcile`` never requires pandas. Callers
who keep their data in frames pay one ``from_dataframe`` / ``to_dataframe`` call
at each edge; everyone else ignores this module.

The boundary owns pandas' dtype quirks so they never reach the engine: NaN / NaT
/ None become absent optional fields, float money is converted through ``str``
so it can't drift off the exact Amount gate, and an integral float id (a column
pandas widened to float64 because of a NaN elsewhere) renders without a spurious
``.0``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import NamedTuple, Optional

import pandas as pd

from .types import Match, Record, ReconcileResult

_MATCH_COLUMNS = ["left_ids", "right_ids", "score", "ambiguous", "gates_passed", "similarities"]
_RECORD_COLUMNS = ["id", "amount", "date", "reference", "counterparty"]


class ReconciledFrames(NamedTuple):
    """The three output frames: matches (with split tuples + ambiguity), residuals."""

    matches: pd.DataFrame
    left_residuals: pd.DataFrame
    right_residuals: pd.DataFrame


def from_dataframe(
    df: pd.DataFrame,
    *,
    amount: str,
    date: Optional[str] = None,
    reference: Optional[str] = None,
    counterparty: Optional[str] = None,
    id: Optional[str] = None,  # noqa: A002 - "Record id" is the domain term
) -> list[Record]:
    """Build Records from a DataFrame and a column mapping.

    Each keyword names the column carrying that criteria field; ``amount`` is
    mandatory, the rest opt in. Columns are read one at a time (not row-wise) so
    each keeps its own dtype instead of being upcast into a shared row Series.
    """
    n = len(df)
    # `is not None`, not truthiness: an empty-string column name is a real (wrong)
    # mapping that should raise KeyError on df[""], not be silently treated as unmapped.
    amounts = [_to_decimal(v) for v in df[amount]]
    dates = [_to_date(v) for v in df[date]] if date is not None else [None] * n
    refs = [_to_str(v) for v in df[reference]] if reference is not None else [None] * n
    cps = [_to_str(v) for v in df[counterparty]] if counterparty is not None else [None] * n
    ids = [_to_str(v) for v in df[id]] if id is not None else [None] * n
    return [
        Record(amount=a, date=d, reference=r, counterparty=c, id=i)
        for a, d, r, c, i in zip(amounts, dates, refs, cps, ids)
    ]


def to_dataframe(result: ReconcileResult) -> ReconciledFrames:
    """Convert a ``ReconcileResult`` into matches and per-side residual frames.

    Match ``left_ids`` / ``right_ids`` are kept as tuples in their cells, so a
    split (1:many) Match survives intact rather than being flattened.
    """
    matches = pd.DataFrame([_match_row(m) for m in result.matches], columns=_MATCH_COLUMNS)
    return ReconciledFrames(
        matches=matches,
        left_residuals=_residual_frame(result.left_residuals),
        right_residuals=_residual_frame(result.right_residuals),
    )


def _match_row(m: Match) -> dict:
    return {
        "left_ids": m.left_ids,
        "right_ids": m.right_ids,
        "score": m.score,
        "ambiguous": m.ambiguous,
        "gates_passed": m.reasons.gates_passed,
        "similarities": m.reasons.similarities,
    }


def _residual_frame(records: tuple[Record, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": r.id,
                "amount": r.amount,
                "date": r.date,
                "reference": r.reference,
                "counterparty": r.counterparty,
            }
            for r in records
        ],
        columns=_RECORD_COLUMNS,
    )


def _to_decimal(v: object) -> Decimal:
    """Amount is mandatory, so a missing cell is an error, not a silent zero.

    Convert through ``str`` so a float amount lands on its exact decimal value
    (Decimal(0.10) would carry binary-float noise that breaks the zero-tolerance
    gate); a value already a Decimal round-trips unchanged.
    """
    if pd.isna(v):
        raise ValueError("Amount is mandatory but a value is missing (NaN)")
    dec = Decimal(str(v))
    if not dec.is_finite():  # inf/-inf slip past pd.isna and would poison tolerance math
        raise ValueError(f"Amount must be a finite number; got {v!r}")
    return dec


def _to_date(v: object) -> Optional[date]:
    if pd.isna(v):
        return None
    # A numeric date cell (Excel serial, epoch int, YYYYMMDD int) would be read by
    # pd.Timestamp as nanoseconds-since-epoch and silently collapse to ~1970. The
    # encoding is ambiguous, so reject rather than guess: the caller converts with
    # pd.to_datetime first. Genuine datetime-likes (Timestamp/datetime/np.datetime64/
    # date/str) are not numbers and pass through.
    if pd.api.types.is_number(v):
        raise ValueError(
            f"date column holds a numeric value ({v!r}); parse it with "
            "pd.to_datetime(...) before from_dataframe so its encoding is explicit"
        )
    return pd.Timestamp(v).date()


def _to_str(v: object) -> Optional[str]:
    if pd.isna(v):
        return None
    # A whole number widened to float (NaN elsewhere in the column) would stringify
    # as "123.0"; render it as "123" so ids and references stay stable.
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
