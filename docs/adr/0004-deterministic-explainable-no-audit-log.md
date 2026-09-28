# Deterministic and explainable, but no persisted audit log

A match pass is pure: same records + same config → identical output. This is guaranteed by using no wall-clock time and no randomness in the engine, and by breaking ties on a caller-supplied Record id (falling back to input position). Every Match carries a Match reason (gates passed, per-field similarities) so a result explains itself.

We deliberately do **not** emit or persist a decision/event log the caller replays from. "Replayable" here means re-running the pass reproduces the result, not that the library owns a durable history — that belongs to the consuming application, and building it in would break the generic-engine boundary of ADR-0001. The trade-off: callers who want an immutable audit trail persist the (deterministic) results themselves.
