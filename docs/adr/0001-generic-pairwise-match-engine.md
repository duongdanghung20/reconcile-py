# Generic pairwise match engine, not hardcoded financial types

The core matches a caller-supplied Left set against a Right set of typed records; it has no built-in `BankTransaction`, `Invoice`, or `LedgerEntry` classes. Three-way reconciliation is composed as two pairwise passes rather than resolved in one hardcoded step.

We chose this over baking the bank/invoice/ledger domain into the engine because the two consuming projects model those entities differently, and a symmetric pairwise engine is one algorithm to test and reuse instead of three coupled ones. The trade-off: three-way reconciliation is the caller's composition, not a single call.
