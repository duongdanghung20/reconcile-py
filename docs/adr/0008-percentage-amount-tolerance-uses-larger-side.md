# Percentage amount tolerance is measured against the larger of the two amounts

When an Amount gate uses a percentage tolerance, the engine compares the absolute difference against `max(|left.amount|, |right.amount|)` times the percentage. The base is the larger-magnitude side — not the Left amount, the Right amount, or their mean.

We chose the larger side because the engine is symmetric (ADR-0001): swapping Left and Right must not change whether a pair matches, which a one-sided base would break, and `max` is the strictest symmetric choice, so a percentage tolerance never widens just because the smaller side shrank. The trade-off: a pair that a mean-based or smaller-side base would admit can fall just outside `max`-based tolerance; callers who need looser percentage matching raise the percentage.
