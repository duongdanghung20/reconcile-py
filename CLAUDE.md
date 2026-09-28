# reconcile-py

## Commands

```bash
pip install -e '.[pandas]'   # editable install + optional pandas adapter (drop [pandas] for core only)
python -m pytest             # full suite (pythonpath/testpaths set in pyproject)
python -m build              # sdist+wheel for PyPI (needs: pip install build)
```

No linter/type-checker configured yet (`.ruff_cache`/`.mypy_cache` gitignored for when one is added).

## Architecture

`src/` layout, Python >= 3.10. Public entrypoint: `reconcile(left, right, config) -> ReconcileResult`.

- `src/reconcile/types.py` — frozen domain types (Record, FieldRule, ReconcileConfig, Match, Reason, ReconcileResult) + all config validation.
- `src/reconcile/engine.py` — pure pairwise engine: gates -> grades -> greedy 1:1 -> bounded split search.
- `src/reconcile/pandas_adapter.py` — optional pandas edge (`from_dataframe`/`to_dataframe`); the ONLY module importing pandas.
- `tests/` — one file per capability, all asserting through a public seam.

Two seams: the `reconcile()` call and the adapter functions. Test only through these.

## Gotchas

- **Determinism is a hard requirement (ADR-0004), not an optimization.** No wall-clock, randomness, or set/dict-iteration-order dependence in the engine — any is a defect. Ordering: Record id, then input position.
- **`import reconcile` must stay pandas-free.** pandas lives only in `pandas_adapter.py` (never imported from `__init__`); a subprocess test guards `sys.modules`.
- **Money is `Decimal`.** The pandas boundary converts amounts through `str` so float noise can't break the exact Amount gate; non-finite amounts are rejected.
- **New config invariants go in `ReconcileConfig.__post_init__`** (types.py) — fail loud there, not deep in the engine.

## Design docs

Read before changing behavior: `CONTEXT.md` (glossary) and `docs/adr/0001`–`0008` (decisions). Don't restate them here.

## Agent skills

### Issue tracker

Issues and specs are tracked as local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
