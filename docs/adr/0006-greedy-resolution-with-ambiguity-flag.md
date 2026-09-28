# Greedy best-score resolution, with near-ties flagged rather than guessed

When candidate matches compete for the same record, the engine sorts all candidates by descending Match score and assigns best-first, consuming each record once (ties broken by Record id for determinism). When the top two competing candidates for a record score within an epsilon of each other, the engine emits an **Ambiguous match** flagged for review instead of silently choosing one.

We chose greedy + flag over global optimal assignment (Hungarian) because Hungarian only helps the 1:1 case, is heavier, and would still pick silently in the near-tie cases that most need a human. Surfacing ambiguity is the safer default for a reconciliation library, where a confident wrong match is worse than a flagged uncertain one. The trade-off: greedy is not guaranteed to maximize total score across the whole set.
