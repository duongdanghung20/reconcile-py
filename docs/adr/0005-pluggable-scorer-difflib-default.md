# Match score is a weighted mean; scorer is pluggable, difflib by default

A candidate's Match score is the weighted mean of its graded-field Similarities (weights configurable, equal by default), accepted when it clears a configurable threshold. Graded-field Similarity is computed by a pluggable **Scorer**; the default normalizes strings and uses the standard library's `difflib.SequenceMatcher`.

We chose `difflib` over `rapidfuzz` as the default despite rapidfuzz being faster and richer, because it keeps the package zero-dependency and correct out of the box; the pluggable seam means a caller who needs rapidfuzz's speed or token-set algorithms installs it as an optional extra and swaps it in by config, not by editing the engine. A reader expecting rapidfuzz will wonder why — this is the reason.
