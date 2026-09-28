# 05: DataFrame adapter

**What to build:** A pandas user can turn DataFrames into Left/Right Record sets, run `reconcile()`, and turn the `ReconcileResult` back into DataFrames of matches and residuals — without hand-constructing Records and without pandas leaking into the engine. This is the second seam; pandas is confined to this module (ADR-0002).

**Blocked by:** 01 *(can run in parallel with 02–04 — separate module, depends only on the domain/result types from 01)*

**Status:** done

- [x] `from_dataframe` builds a Record sequence from a DataFrame plus a column mapping (which columns are Amount, Date, Reference, Counterparty, Record id).
- [x] `to_dataframe` converts a `ReconcileResult` into DataFrames of matches (including split tuples and the ambiguous flag) and of left/right residuals.
- [x] pandas is imported only in this adapter module; the engine has no pandas dependency (ADR-0002). Guarded by a subprocess test that `import reconcile` never pulls pandas into `sys.modules`.
- [x] Pandas dtype quirks are handled at the boundary, not passed into the engine: NaN → absent optional field, object columns coerced, float money handled so it never silently breaks the Amount gate. Also rejects (rather than silently corrupts) inf amounts and numeric date columns, which `pd.Timestamp` would read as nanoseconds-since-epoch.
- [x] Tests through the adapter seam (seam 2): DataFrame → Records → `reconcile()` → DataFrames round-trip; column mapping; dtype-quirk handling. Engine tests stay pandas-free.

Implemented in `src/reconcile/pandas_adapter.py` (imported lazily, not from `reconcile.__init__`, so the core stays pandas-free). pandas declared as an optional dependency in `pyproject.toml` (`reconcile-py[pandas]`).
