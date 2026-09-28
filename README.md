# reconcile-py — deterministic reconciliation engine

- Python package that fuzzy-matches one set of records against another under configurable tolerance rules, in a deterministic, replayable matching pass. Its first use is bank-to-invoice/ledger reconciliation, but the core is a **generic pairwise matcher** with no hardcoded bank/invoice/ledger types (ADR-0001) — the caller supplies their own record types.
- Packaged with a full `pytest` suite and a typed public API (ships `py.typed`); used as the matching core in two of my own projects.
- Stack: Python, pytest, PyPI packaging. **pandas is optional** — installed as the `reconcile-py[pandas]` extra, it powers a `DataFrame` adapter at the edge; the engine itself never imports pandas (ADR-0002).
