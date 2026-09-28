"""Domain types for the reconciliation engine (CONTEXT.md vocabulary).

Config and result are frozen dataclasses — the whole result is immutable so it
can be passed around and persisted without fear of mutation (spec Q20/Q31).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Literal, Optional

# A Scorer computes a graded field's Similarity (0..1). Used from ticket 02;
# gate-only passes never call it.
Scorer = Callable[[str, str], float]

# Closed vocabularies (CONTEXT.md): the criteria fields and the two field roles.
Field = Literal["amount", "date", "reference", "counterparty"]
Role = Literal["gate", "grade"]


@dataclass(frozen=True)
class Record:
    """One typed entry on either side of a pass. Amount mandatory; rest opt-in."""

    amount: Decimal
    date: Optional[date] = None
    reference: Optional[str] = None
    counterparty: Optional[str] = None
    id: Optional[str] = None  # noqa: A003 - "Record id" is the domain term


@dataclass(frozen=True)
class FieldRule:
    """How one criteria field participates: as a gate (pass/fail) or a grade (0..1)."""

    field: Field
    role: Role
    abs_tol: Optional[Decimal] = None  # amount gate: absolute tolerance
    pct_tol: Optional[Decimal] = None  # amount gate: percentage, e.g. Decimal("0.5") == 0.5%
    day_tol: Optional[int] = None  # date gate: ± day window
    weight: Optional[float] = None  # graded field weight (used from ticket 02)


@dataclass(frozen=True)
class ReconcileConfig:
    """Immutable description of a pass: the rules plus global knobs.

    Rejects a config with no Amount gate rule — Amount is mandatory (spec Q5).
    """

    rules: tuple[FieldRule, ...]
    threshold: float = 1.0
    ambiguity_epsilon: float = 0.0
    max_subset_size: int = 4
    # Split search enumerates C(max_group_size, max_subset_size) subsets per
    # residual in the worst case (ADR-0007). The default keeps that bound small
    # (C(16, 4) == 1820); raise it only when real batches exceed a 16-candidate
    # group and the cost is acceptable.
    max_group_size: int = 16
    scorer: Optional[Scorer] = None

    def __post_init__(self) -> None:
        # Coerce to tuple so immutability holds even if a caller passes a list.
        object.__setattr__(self, "rules", tuple(self.rules))
        for r in self.rules:
            # Only Amount and Date are gate fields (ADR-0003); a gate elsewhere
            # would otherwise be silently ignored by the engine.
            if r.role == "gate" and r.field not in ("amount", "date"):
                raise ValueError(f"{r.field!r} cannot be a gate field (only amount, date)")
            # ...and only Reference/Counterparty can be graded (ADR-0003); grading
            # amount/date would crash in the string Scorer instead of here.
            if r.role == "grade" and r.field not in ("reference", "counterparty"):
                raise ValueError(
                    f"{r.field!r} cannot be a graded field (only reference, counterparty)"
                )
            # A date gate with no window would silently reject every pair.
            if r.field == "date" and r.role == "gate" and r.day_tol is None:
                raise ValueError("date gate rule requires day_tol")
            # Non-positive weight breaks the weighted mean: zero sum bypasses the
            # threshold, negative pushes the score outside 0..1.
            if r.role == "grade" and r.weight is not None and r.weight <= 0:
                raise ValueError(f"graded field {r.field!r} weight must be positive")
        if not any(r.field == "amount" and r.role == "gate" for r in self.rules):
            raise ValueError("ReconcileConfig requires an Amount gate rule")
        # A negative epsilon silently disables all near-tie flagging (ADR-0006's
        # core safety feature): abs(score diff) is never <= a negative number.
        if self.ambiguity_epsilon < 0:
            raise ValueError("ambiguity_epsilon must be >= 0")
        # A split has at least two members; < 2 would make range(2, size+1) empty
        # and silently skip every split (ADR-0007), the same silent-misconfig
        # failure the guards above prevent.
        if self.max_subset_size < 2:
            raise ValueError("max_subset_size must be >= 2 (a split has at least two members)")
        # A non-positive group cap makes len(group) > cap always true, silently
        # disabling split search for every input.
        if self.max_group_size < 1:
            raise ValueError("max_group_size must be >= 1")


@dataclass(frozen=True)
class Reason:
    """Why a Match was made: which gates passed, and each graded Similarity."""

    gates_passed: tuple[str, ...] = ()
    similarities: tuple[tuple[str, float], ...] = ()  # (field, similarity), from ticket 02


@dataclass(frozen=True)
class Match:
    """An association of Left record id(s) to Right record id(s).

    Tuples carry both 1:1 and (from ticket 04) split matches in either direction.
    An id is the caller's Record id, falling back to input position when absent.
    """

    left_ids: tuple[str | int, ...]
    right_ids: tuple[str | int, ...]
    score: float
    reasons: Reason
    ambiguous: bool = False


@dataclass(frozen=True)
class ReconcileResult:
    """The frozen output of a pass: matches plus per-side residuals."""

    matches: tuple[Match, ...]
    left_residuals: tuple[Record, ...]
    right_residuals: tuple[Record, ...]

    @property
    def ambiguous(self) -> tuple[Match, ...]:
        """Convenience view over ``matches`` flagged ambiguous (populated from ticket 03)."""
        return tuple(m for m in self.matches if m.ambiguous)
