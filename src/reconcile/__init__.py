"""reconcile-py: deterministic, explainable fuzzy reconciliation of record sets."""

from .engine import reconcile
from .types import (
    FieldRule,
    Match,
    Reason,
    Record,
    ReconcileConfig,
    ReconcileResult,
    Scorer,
)

__all__ = [
    "reconcile",
    "Record",
    "FieldRule",
    "ReconcileConfig",
    "Match",
    "Reason",
    "ReconcileResult",
    "Scorer",
]
